import asyncio
import hashlib
import json
import logging
from datetime import datetime

import numpy as np
import pandas as pd

from core.strategies import STRATEGY_REGISTRY

from .engine import BacktestEngine
from .simulation import _get_strategy_min_bars

logger = logging.getLogger(__name__)

_BACKTEST_CACHE_MAX = 50
_BACKTEST_CACHE_TTL = 3600
_backtest_cache: dict[str, tuple[dict, float]] = {}


def _make_backtest_cache_key(symbol: str, strategy_name: str, start_date: str,
                              end_date: str, initial_capital: float, params: dict | None) -> str:
    raw = f"{symbol}:{strategy_name}:{start_date}:{end_date}:{initial_capital}:{json.dumps(params or {}, sort_keys=True)}"
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cached_result(key: str) -> dict | None:
    import time
    entry = _backtest_cache.get(key)
    if entry is None:
        return None
    result, ts = entry
    if time.monotonic() - ts > _BACKTEST_CACHE_TTL:
        del _backtest_cache[key]
        return None
    return {**result, "cached": True}


def _set_cached_result(key: str, result: dict) -> None:
    import time
    if len(_backtest_cache) >= _BACKTEST_CACHE_MAX:
        oldest_key = min(_backtest_cache, key=lambda k: _backtest_cache[k][1])
        del _backtest_cache[oldest_key]
    _backtest_cache[key] = (result, time.monotonic())


def run_backtest(
    symbol: str,
    strategy_name: str = "ma_cross",
    start_date: str = "2024-01-01",
    end_date: str = "2025-12-31",
    initial_capital: float = 1000000,
    params: dict | None = None,
    _df=None,
) -> dict:
    from core.data_fetcher import get_fetcher
    from core.memory_guard import check_and_reclaim_if_needed

    cache_key = _make_backtest_cache_key(symbol, strategy_name, start_date, end_date, initial_capital, params)
    cached = _get_cached_result(cache_key)
    if cached is not None:
        return cached

    check_and_reclaim_if_needed()

    if strategy_name == "adaptive":
        return _run_adaptive_backtest(symbol, start_date, end_date, initial_capital, params, _df)

    if strategy_name not in STRATEGY_REGISTRY:
        return {"error": f"未知策略: {strategy_name}"}

    strategy_cls = STRATEGY_REGISTRY[strategy_name]
    try:
        strategy = strategy_cls(**(params or {}))
    except (TypeError, ValueError) as e:
        return {"error": f"策略参数错误: {e}"}

    fetcher = get_fetcher()

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
        days_from_now = (datetime.now() - start_dt).days
    except (ValueError, TypeError):
        days_from_now = 370

    hist_period = "all" if days_from_now > 730 or days_from_now > 365 else "1y"

    if _df is not None:
        df = _df.copy()
    else:
        async def _fetch():
            return await fetcher.get_history(symbol, period=hist_period, kline_type="daily", adjust="qfq")

        try:
            try:
                loop = asyncio.get_running_loop()
                df = asyncio.run_coroutine_threadsafe(_fetch(), loop).result(timeout=30)
            except RuntimeError:
                df = asyncio.run(_fetch())
        except Exception as e:
            logger.error("Data fetch failed for %s: %s", symbol, e, exc_info=True)
            return {"error": f"获取 {symbol} 数据失败: {e}"}

    if df is None or df.empty:
        return {"error": f"无法获取 {symbol} 的历史数据，请检查股票代码是否正确"}

    min_bars = _get_strategy_min_bars(strategy_name, params)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df_full = df.copy()
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]
        df = df.sort_values("date").reset_index(drop=True)
        if len(df) < min_bars and len(df_full) >= min_bars:
            logger.warning("Date range %s~%s only has %d bars, using available data", start_date, end_date, len(df))
            df = df_full.sort_values("date").reset_index(drop=True)

    if len(df) < min_bars:
        return {"error": f"数据不足：仅有 {len(df)} 个交易日，{strategy_cls.__name__}策略至少需要{min_bars}个交易日，请选择更长的时间段"}

    try:
        engine = BacktestEngine(initial_capital=initial_capital, slippage_pct=0.001, market_impact_pct=0.0005)
        result = engine.run(strategy, df)
        try:
            from core.metrics import metrics
            metrics.increment("backtest_runs", tags={"strategy": strategy_name})
            metrics.gauge("backtest_sharpe", result.sharpe_ratio, tags={"strategy": strategy_name})
        except Exception as e:
            logger.debug("Metrics reporting failed: %s", e)
    except Exception as e:
        logger.error("Backtest engine failed for %s with %s: %s", symbol, strategy_name, e, exc_info=True)
        return {"error": f"回测执行失败: {e}"}

    if not result.dates or not result.equity_curve:
        return {"error": "回测未产生有效结果，请尝试更长的回测时间段"}

    closes_raw = pd.to_numeric(df["close"], errors="coerce").dropna().values.astype(float)
    date_close_map = {}
    if "date" in df.columns:
        ds_arr = df["date"].dt.strftime("%Y-%m-%d").values if hasattr(df["date"].dt, "strftime") else [str(d)[:10] for d in df["date"].values]
        close_arr = pd.to_numeric(df["close"], errors="coerce").dropna().values.astype(float)
        for j in range(len(ds_arr)):
            date_close_map[ds_arr[j]] = float(close_arr[j])

    first_close = float(closes_raw[0]) if closes_raw[0] > 0 else 1.0
    benchmark_curve = []
    for i in range(len(result.dates)):
        d = result.dates[i]
        close_val = date_close_map.get(d)
        if close_val is None:
            if i < len(closes_raw):
                close_val = float(closes_raw[i])
            else:
                continue
        benchmark_curve.append({"date": d, "value": initial_capital * (close_val / first_close)})

    result_dict = result.to_dict()
    result_dict["slippage_model"] = "fixed_pct"
    result_dict["benchmark_curve"] = benchmark_curve[-500:] if benchmark_curve else []
    _set_cached_result(cache_key, result_dict)
    return result_dict


def _run_adaptive_backtest(
    symbol: str,
    start_date: str = "2024-01-01",
    end_date: str = "2025-12-31",
    initial_capital: float = 1000000,
    params: dict | None = None,
    _df=None,
) -> dict:
    from core.adaptive_strategy import AdaptiveStrategyEngine

    cache_key = _make_backtest_cache_key(symbol, "adaptive", start_date, end_date, initial_capital, params)
    cached = _get_cached_result(cache_key)
    if cached is not None:
        return cached

    if _df is not None:
        df = _df.copy()
    else:
        from core.data_fetcher import get_fetcher
        fetcher = get_fetcher()

        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            days_from_now = (datetime.now() - start_dt).days
        except (ValueError, TypeError):
            days_from_now = 370

        hist_period = "all" if days_from_now > 365 else "1y"

        import asyncio

        async def _fetch():
            return await fetcher.get_history(symbol, period=hist_period, kline_type="daily", adjust="qfq")

        try:
            try:
                loop = asyncio.get_running_loop()
                df = asyncio.run_coroutine_threadsafe(_fetch(), loop).result(timeout=30)
            except RuntimeError:
                df = asyncio.run(_fetch())
        except Exception as e:
            logger.error("Data fetch failed for %s: %s", symbol, e, exc_info=True)
            return {"error": f"获取 {symbol} 数据失败: {e}"}

    if df is None or df.empty:
        return {"error": f"无法获取 {symbol} 的历史数据"}

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df_full = df.copy()
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]
        df = df.sort_values("date").reset_index(drop=True)
        if len(df) < 40 and len(df_full) >= 40:
            logger.warning("Adaptive: Date range %s~%s only has %d bars, using available data", start_date, end_date, len(df))
            df = df_full.sort_values("date").reset_index(drop=True)

    if len(df) < 40:
        return {"error": f"数据不足：自适应策略至少需要40个交易日，当前仅{len(df)}个"}

    try:
        engine = AdaptiveStrategyEngine(initial_capital=initial_capital)
        result = engine.run(df)
    except Exception as e:
        logger.error("Adaptive backtest failed for %s: %s", symbol, e, exc_info=True)
        return {"error": f"自适应回测执行失败: {e}"}

    if not result.get("equity_curve"):
        return {"error": "回测未产生有效结果，请尝试更长的回测时间段"}

    equity_curve = result.get("equity_curve", [])
    benchmark_curve = result.get("benchmark_curve", [])

    if equity_curve and isinstance(equity_curve[0], dict):
        equity_curve = [
            {"date": str(e.get("date", "")), "value": float(e.get("value", 0))}
            for e in equity_curve if isinstance(e, dict)
        ]
    else:
        dates_list = result.get("dates", [])
        ec_raw = equity_curve
        bc_raw = benchmark_curve
        equity_curve = []
        for i in range(min(len(dates_list), len(ec_raw))):
            equity_curve.append({"date": str(dates_list[i]), "value": float(ec_raw[i])})

    if benchmark_curve and isinstance(benchmark_curve[0], dict):
        benchmark_curve = [
            {"date": str(b.get("date", "")), "value": float(b.get("value", 0))}
            for b in benchmark_curve if isinstance(b, dict)
        ]
    else:
        dates_list = result.get("dates", [])
        bc_raw = result.get("benchmark_curve", [])
        benchmark_curve = []
        for i in range(min(len(dates_list), len(bc_raw))):
            benchmark_curve.append({"date": str(dates_list[i]), "value": float(bc_raw[i])})

    adaptive_result = {
        "strategy_name": result.get("strategy_name", "自适应量化策略引擎"),
        "total_return": result.get("total_return", 0),
        "annual_return": result.get("annual_return", 0),
        "max_drawdown": result.get("max_drawdown", 0),
        "sharpe_ratio": result.get("sharpe_ratio", 0),
        "sortino_ratio": result.get("sortino_ratio", 0),
        "calmar_ratio": result.get("calmar_ratio", 0),
        "win_rate": result.get("win_rate", 0),
        "profit_factor": result.get("profit_factor", 0),
        "total_trades": result.get("total_trades", 0),
        "win_trades": result.get("win_trades", 0),
        "loss_trades": result.get("loss_trades", 0),
        "avg_profit": result.get("avg_profit", 0),
        "avg_loss": result.get("avg_loss", 0),
        "avg_hold_days": result.get("avg_hold_days", 0),
        "max_consecutive_losses": result.get("max_consecutive_losses", 0),
        "omega_ratio": result.get("omega_ratio", 0),
        "tail_ratio": result.get("tail_ratio", 0),
        "information_ratio": result.get("information_ratio", 0),
        "recovery_factor": result.get("recovery_factor", 0),
        "expectancy": result.get("expectancy", 0),
        "payoff_ratio": result.get("payoff_ratio", 0),
        "benchmark_return": result.get("benchmark_return", 0),
        "alpha": result.get("alpha", 0),
        "beta": result.get("beta", 1),
        "cvar_95": result.get("cvar_95", 0),
        "var_95": result.get("var_95", 0),
        "annual_volatility": result.get("annual_volatility", 0),
        "downside_deviation": result.get("downside_deviation", 0),
        "equity_curve": equity_curve,
        "benchmark_curve": benchmark_curve,
        "trades": result.get("trades", []),
        "kline_with_signals": result.get("kline_with_signals", []),
        "market_regime_labels": result.get("market_regime_labels", []),
        "strategy_allocation": result.get("strategy_allocation", []),
    }
    _set_cached_result(cache_key, adaptive_result)
    return adaptive_result


def run_walk_forward(
    symbol: str,
    strategy_name: str = "ma_cross",
    start_date: str = "2024-01-01",
    end_date: str = "2025-12-31",
    train_days: int = 252,
    test_days: int = 63,
    initial_capital: float = 1000000,
    params: dict | None = None,
) -> dict:
    import asyncio

    from core.data_fetcher import get_fetcher

    fetcher = get_fetcher()

    async def _fetch_df():
        return await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                df = pool.submit(asyncio.run, _fetch_df()).result(timeout=30)
        else:
            df = asyncio.run(_fetch_df())
    except Exception as e:
        logger.error("Walk-forward data fetch failed for %s: %s", symbol, e, exc_info=True)
        return {"error": f"获取数据失败: {e}"}

    if df is None or df.empty:
        return {"error": f"无法获取 {symbol} 的历史数据"}

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)

    start_dt = pd.Timestamp(start_date)
    end_dt = pd.Timestamp(end_date)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)].reset_index(drop=True)

    if len(df) < train_days + test_days:
        return {"error": f"数据不足：至少需要{train_days + test_days}个交易日，当前仅{len(df)}个"}

    windows = []
    i = 0
    while i + train_days + test_days <= len(df):
        train_df = df.iloc[i:i + train_days]
        test_df = df.iloc[i + train_days:i + train_days + test_days]

        train_start = str(train_df["date"].iloc[0])[:10]
        train_end = str(train_df["date"].iloc[-1])[:10]
        test_start = str(test_df["date"].iloc[0])[:10]
        test_end = str(test_df["date"].iloc[-1])[:10]

        bt_result = run_backtest(
            symbol=symbol,
            strategy_name=strategy_name,
            start_date=test_start,
            end_date=test_end,
            initial_capital=initial_capital,
            params=params,
            _df=test_df,
        )

        metrics = {}
        if "error" not in bt_result:
            metrics = {
                "sharpe_ratio": bt_result.get("sharpe_ratio", 0),
                "total_return": bt_result.get("total_return", 0),
                "max_drawdown": bt_result.get("max_drawdown", 0),
            }
        else:
            metrics = {"sharpe_ratio": 0, "total_return": 0, "max_drawdown": 0}

        windows.append({
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
            "metrics": metrics,
        })

        i += test_days

    if not windows:
        return {"error": "无法生成有效的滚动窗口"}

    test_sharpes = [w["metrics"]["sharpe_ratio"] for w in windows]
    test_returns = [w["metrics"]["total_return"] for w in windows]
    profitable_count = sum(1 for r in test_returns if r > 0)

    return {
        "windows": windows,
        "avg_test_sharpe": round(float(np.mean(test_sharpes)), 4) if test_sharpes else 0,
        "avg_test_return": round(float(np.mean(test_returns)), 4) if test_returns else 0,
        "consistency_rate": round(profitable_count / len(windows), 4) if windows else 0,
    }



