import logging

import numpy as np
import pandas as pd

from core.strategies import BaseStrategy

from .analysis import compare_results
from .engine import BacktestEngine
from .result import BacktestResult

logger = logging.getLogger(__name__)


class BatchStrategyRunner:
    """Batch strategy runner for multi-strategy backtesting and optimization."""

    def __init__(self, initial_capital: float = 1000000, commission: float = 0.0003,
                 slippage_pct: float = 0.001, market_impact_pct: float = 0.0005):
        self._initial_capital = initial_capital
        self._engine = BacktestEngine(
            initial_capital=initial_capital,
            commission=commission,
            slippage_pct=slippage_pct,
            market_impact_pct=market_impact_pct,
        )

    def run_strategies(
        self,
        strategy_classes: list[type[BaseStrategy]],
        df: pd.DataFrame,
        top_n: int = 5,
        metric: str = "sharpe_ratio",
    ) -> dict:
        """Run multiple strategies and return ranked results.

        Args:
            strategy_classes: List of strategy classes to test
            df: Market data
            top_n: Return only top N strategies
            metric: Optimization metric (sharpe_ratio, total_return, max_drawdown, win_rate)

        Returns:
            Dict with results, rankings, and summary
        """
        if not strategy_classes or df is None or len(df) < 10:
            return {"error": "Invalid input: need strategy classes and sufficient data"}

        results: list[BacktestResult] = []
        for strat_cls in strategy_classes:
            try:
                strategy = strat_cls()
                result = self._engine.run(strategy, df)
                results.append(result)
            except Exception as e:
                logger.debug("Strategy %s failed: %s", strat_cls, e)

        if not results:
            return {"error": "All strategies failed"}

        comparison = compare_results(results)
        rankings = comparison.get("ranking", [])
        top_results = []
        for rank_entry in rankings[:top_n]:
            strat_name = rank_entry["strategy_name"]
            matched = next((r for r in results if r.strategy_name == strat_name), None)
            if matched:
                top_results.append(matched)

        return {
            "results": [r.get_performance_summary() for r in top_results],
            "rankings": rankings[:top_n],
            "comparison": comparison.get("comparison", []),
            "summary": self._build_summary(top_results, metric),
        }

    def auto_optimize(
        self,
        strategy_classes: list[type[BaseStrategy]],
        df: pd.DataFrame,
        param_spaces: dict[type[BaseStrategy], dict] = None,
        max_combinations: int = 30,
        metric: str = "sharpe_ratio",
    ) -> dict:
        """Auto-optimize: find best strategy and parameters for the given data.

        Args:
            strategy_classes: List of strategy classes to optimize
            df: Market data
            param_spaces: Optional param spaces per strategy class
            max_combinations: Max parameter combinations to test per strategy
            metric: Optimization metric

        Returns:
            Best strategy, parameters, and performance summary
        """
        if not strategy_classes or df is None or len(df) < 20:
            return {"error": "Need at least 20 bars of data for auto-optimization"}

        param_spaces = param_spaces or {}
        all_candidates: list[dict] = []

        for strat_cls in strategy_classes:
            param_space = param_spaces.get(strat_cls, {})
            if not param_space and hasattr(strat_cls, "get_param_space"):
                param_space = strat_cls.get_param_space()

            if not param_space:
                try:
                    result = self._engine.run(strat_cls(), df)
                    all_candidates.append({
                        "strategy_class": strat_cls,
                        "strategy_name": strat_cls.__name__,
                        "params": {},
                        "result": result,
                    })
                except Exception as e:
                    logger.debug("Default params failed for %s: %s", strat_cls, e)
                continue

            param_names = list(param_space.keys())
            param_values: list[list] = []
            for name in param_names:
                spec = param_space[name]
                if isinstance(spec, dict):
                    v_min = spec.get("min", 5)
                    v_max = spec.get("max", 60)
                    step = spec.get("step", 1)
                else:
                    v_min, v_max, _ = spec if len(spec) >= 3 else (5, 60, 1)
                    step = 5
                vals = list(range(int(v_min), int(v_max) + 1, int(step)))
                if not vals:
                    vals = [v_min]
                param_values.append(vals)

            from itertools import product
            combinations = list(product(*param_values))
            if len(combinations) > max_combinations:
                indices = np.random.default_rng(42).choice(
                    len(combinations), max_combinations, replace=False
                )
                combinations = [combinations[i] for i in sorted(indices)]

            for combo in combinations:
                params = dict(zip(param_names, combo, strict=False))
                try:
                    result = self._engine.run(strat_cls(**params), df)
                    all_candidates.append({
                        "strategy_class": strat_cls,
                        "strategy_name": strat_cls.__name__,
                        "params": params,
                        "result": result,
                    })
                except Exception as e:
                    logger.debug("Param combo failed for %s: %s", strat_cls, e)

        if not all_candidates:
            return {"error": "No valid configurations found"}

        best_candidate = max(
            all_candidates,
            key=lambda x: self._get_metric(x["result"], metric),
        )
        best_result = best_candidate["result"]

        return {
            "best_strategy": best_candidate["strategy_name"],
            "best_params": best_candidate["params"],
            "best_result": best_result.get_performance_summary(),
            "all_candidates_summary": [
                {
                    "strategy": c["strategy_name"],
                    "params": c["params"],
                    "sharpe": round(c["result"].sharpe_ratio, 2),
                    "return_pct": round(c["result"].total_return, 2),
                    "max_dd_pct": round(c["result"].max_drawdown, 2),
                }
                for c in sorted(
                    all_candidates,
                    key=lambda x: self._get_metric(x["result"], metric),
                    reverse=True,
                )[:10]
            ],
        }

    def _get_metric(self, result: BacktestResult, metric: str) -> float:
        val = getattr(result, metric, 0.0) or 0.0
        if metric == "max_drawdown":
            return -val
        return val

    def _build_summary(self, results: list[BacktestResult], metric: str) -> dict:
        if not results:
            return {}
        best = max(results, key=lambda x: self._get_metric(x, metric))
        return {
            "total_strategies_tested": len(results),
            "best_strategy": best.strategy_name,
            "best_sharpe": round(best.sharpe_ratio, 2),
            "best_return_pct": round(best.total_return, 2),
            "best_max_drawdown_pct": round(best.max_drawdown, 2),
            "metric_used": metric,
        }
