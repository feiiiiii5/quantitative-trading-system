import logging
import random

from .result import BacktestResult

logger = logging.getLogger(__name__)


def grid_search_params(strategy_cls, df, max_combinations: int = 50) -> list:
    param_space = strategy_cls.get_param_space()
    if not param_space:
        return []

    param_names = list(param_space.keys())
    param_values_list = []
    for name in param_names:
        spec = param_space[name]
        vals = []
        v = spec["min"]
        while v <= spec["max"]:
            vals.append(v)
            v += spec["step"]
        param_values_list.append(vals)

    from itertools import product
    all_combos = list(product(*param_values_list))

    if len(all_combos) > max_combinations:
        all_combos = random.sample(all_combos, max_combinations)

    from .runner import run_backtest
    results = []
    for combo in all_combos:
        params = dict(zip(param_names, combo, strict=False))
        try:
            bt_result = run_backtest(
                symbol="grid_search",
                strategy_name=strategy_cls.__name__,
                initial_capital=1000000,
                params=params,
                _df=df,
            )
        except Exception as e:
            logger.debug("Grid search iteration failed: %s", e)
            continue

        if "error" in bt_result:
            continue

        results.append({
            "params": params,
            "sharpe_ratio": bt_result.get("sharpe_ratio", 0),
            "total_return": bt_result.get("total_return", 0),
            "max_drawdown": bt_result.get("max_drawdown", 0),
        })

    results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)
    return results[:10]


def compare_results(results: list[BacktestResult]) -> dict:
    """对比多个回测结果，返回排名和对比数据"""
    if not results:
        return {"error": "no results to compare"}

    metrics = [
        ("total_return", "总收益率", True),
        ("annual_return", "年化收益率", True),
        ("sharpe_ratio", "夏普比率", True),
        ("max_drawdown", "最大回撤", False),
        ("win_rate", "胜率", True),
        ("profit_factor", "盈亏比", True),
        ("calmar_ratio", "卡尔马比率", True),
        ("sortino_ratio", "索提诺比率", True),
        ("total_trades", "交易次数", True),
        ("avg_hold_days", "平均持仓天数", False),
        ("expectancy", "期望值", True),
        ("payoff_ratio", "赔率", True),
    ]

    comparison = []
    for r in results:
        entry = {"strategy_name": r.strategy_name}
        for metric_key, _, _ in metrics:
            entry[metric_key] = getattr(r, metric_key, 0.0)
        comparison.append(entry)

    # 综合排名：对每个指标排名后加权
    ranks = {r.strategy_name: 0.0 for r in results}
    weights = {
        "total_return": 0.20, "sharpe_ratio": 0.25, "max_drawdown": 0.15,
        "win_rate": 0.10, "profit_factor": 0.10, "calmar_ratio": 0.10,
        "sortino_ratio": 0.10,
    }

    for metric_key, _, higher_is_better in metrics:
        if metric_key not in weights:
            continue
        values = [(r.strategy_name, getattr(r, metric_key, 0.0)) for r in results]
        values.sort(key=lambda x: x[1], reverse=higher_is_better)
        for rank, (name, _) in enumerate(values):
            ranks[name] += (len(values) - rank) * weights[metric_key]

    ranked = sorted(ranks.items(), key=lambda x: x[1], reverse=True)
    final_ranking = [{"rank": i + 1, "strategy_name": name, "score": round(score, 4)}
                     for i, (name, score) in enumerate(ranked)]

    return {
        "comparison": comparison,
        "ranking": final_ranking,
        "metrics": [{"key": k, "label": label} for k, label, _ in metrics],
    }
