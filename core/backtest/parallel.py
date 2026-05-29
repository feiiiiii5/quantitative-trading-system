import logging
import multiprocessing as mp

import pandas as pd

from core.memory_guard import (
    MemoryGuard,
    check_and_reclaim_if_needed,
    get_memory_usage,
    is_memory_critical,
    is_memory_pressure,
)
from core.strategies import STRATEGY_REGISTRY

from .engine import BacktestEngine

logger = logging.getLogger(__name__)


def _run_single_backtest(args: tuple) -> dict:
    strategy_name, strategy_cls_name, params, df_dict, symbol, initial_capital = args
    strategy_cls = STRATEGY_REGISTRY.get(strategy_cls_name)
    if strategy_cls is None:
        return {"strategy": strategy_name, "error": f"Unknown strategy: {strategy_cls_name}"}
    try:
        strat = strategy_cls(**(params or {}))
        df = pd.DataFrame(df_dict)
        engine = BacktestEngine(initial_capital=initial_capital)
        result = engine.run(strat, df, symbol=symbol)
        sell_trades = [t for t in result.trades if t.get("action") == "sell"]
        total_trades = len(sell_trades)
        win_trades = sum(1 for t in sell_trades if t.get("pnl", 0) > 0)
        daily_returns = []
        if result.equity_curve and len(result.equity_curve) > 1:
            for i in range(1, len(result.equity_curve)):
                prev = result.equity_curve[i - 1]
                curr = result.equity_curve[i]
                if prev > 0:
                    daily_returns.append((curr - prev) / prev)
        return {
            "strategy": strategy_name,
            "total_return": round(result.total_return, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "max_drawdown": round(result.max_drawdown, 4),
            "win_rate": round(win_trades / total_trades, 4) if total_trades > 0 else 0.0,
            "total_trades": total_trades,
            "daily_returns": daily_returns,
        }
    except Exception as e:
        return {"strategy": strategy_name, "error": str(e)}


def run_parallel_backtest(
    strategies: list[dict],
    df: pd.DataFrame,
    symbol: str = "",
    initial_capital: float = 1000000,
    max_workers: int = 0,
) -> list[dict]:
    mem_info = get_memory_usage()
    logger.info("并行回测启动 - 内存状态: RSS=%.0fMB, 系统使用率=%.1f%%",
                mem_info.get('rss_mb', 0), mem_info.get('system_used_pct', 0))

    if is_memory_critical():
        max_workers = 1
        logger.warning("内存临界状态，回退至单线程回测")
    elif is_memory_pressure():
        max_workers = min(max_workers if max_workers > 0 else 2, 2)
        logger.warning("内存压力较高，限制并行度为 %s", max_workers)
        check_and_reclaim_if_needed()

    if max_workers <= 0:
        cpu_count = mp.cpu_count() or 4
        mem_factor = min(1.0, (100 - mem_info.get('system_used_pct', 50)) / 60)
        max_workers = max(1, int(min(cpu_count, 4) * mem_factor))

    df_dict = df.to_dict("list")
    args_list = []
    for s in strategies:
        name = s.get("name", "")
        cls_name = s.get("class_name", name)
        params = s.get("params", {})
        args_list.append((name, cls_name, params, df_dict, symbol, initial_capital))

    if len(args_list) <= 2 or max_workers <= 1:
        results = []
        for i, args in enumerate(args_list):
            if i > 0 and i % 3 == 0:
                check_and_reclaim_if_needed()
            results.append(_run_single_backtest(args))
        return results

    try:
        with MemoryGuard("并行回测", max_mb=12000), mp.Pool(processes=max_workers) as pool:
            results = pool.map(_run_single_backtest, args_list)
        return results
    except MemoryError as e:
        logger.error("并行回测内存不足: %s", e)
        check_and_reclaim_if_needed()
        return [_run_single_backtest(a) for a in args_list]
    except Exception as e:
        logger.warning("Parallel backtest failed, falling back to sequential: %s", e)
        return [_run_single_backtest(a) for a in args_list]
