import logging
import multiprocessing
import os
from itertools import product
from typing import Any, Callable

from quantcore_backtest.tick_engine import BacktestResult, TickLevelBacktester

logger = logging.getLogger(__name__)


def _run_single_backtest(args: tuple) -> BacktestResult:
    ticks, strategy_fn, initial_capital, backtester_kwargs = args
    backtester = TickLevelBacktester(**backtester_kwargs)
    return backtester.run(ticks=ticks, strategy_fn=strategy_fn, initial_capital=initial_capital)


def _run_param_sweep_single(args: tuple) -> BacktestResult:
    ticks, strategy_fn, initial_capital, backtester_kwargs, param_override = args
    merged_kwargs = {**backtester_kwargs, **param_override}
    backtester = TickLevelBacktester(**merged_kwargs)
    return backtester.run(ticks=ticks, strategy_fn=strategy_fn, initial_capital=initial_capital)


class ParallelBacktester:
    def __init__(self, max_workers: int | None = None) -> None:
        self._max_workers = max_workers or os.cpu_count() or 4
        self._pool: multiprocessing.Pool | None = None

    def __enter__(self) -> "ParallelBacktester":
        self._pool = multiprocessing.Pool(processes=self._max_workers)
        logger.info("ParallelBacktester pool started with %d workers", self._max_workers)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool.join()
            self._pool = None
            logger.info("ParallelBacktester pool shut down")

    def _ensure_pool(self) -> multiprocessing.Pool:
        if self._pool is None:
            self._pool = multiprocessing.Pool(processes=self._max_workers)
            logger.info("ParallelBacktester pool lazily started with %d workers", self._max_workers)
        return self._pool

    def run_parallel(
        self,
        strategies: list[dict[str, Any]],
        ticks: list[dict[str, Any]],
        initial_capital: float = 1_000_000.0,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[BacktestResult]:
        if not strategies:
            return []

        args_list = [
            (
                ticks,
                s.get("strategy_fn"),
                initial_capital,
                s.get("backtester_kwargs", {}),
            )
            for s in strategies
        ]

        pool = self._ensure_pool()

        if progress_callback is not None:
            results: list[BacktestResult] = []
            for i, result in enumerate(pool.imap(_run_single_backtest, args_list)):
                results.append(result)
                progress_callback(i + 1, len(args_list))
            return results

        return pool.map(_run_single_backtest, args_list)

    def run_param_sweep(
        self,
        base_strategy: dict[str, Any],
        param_grid: dict[str, list[Any]],
        ticks: list[dict[str, Any]],
        initial_capital: float = 1_000_000.0,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[BacktestResult]:
        if not param_grid:
            return [self._run_single(base_strategy, ticks, initial_capital)]

        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        combinations = list(product(*param_values))

        logger.info(
            "Parameter sweep: %d combinations across %d params",
            len(combinations),
            len(param_names),
        )

        base_kwargs = base_strategy.get("backtester_kwargs", {})
        strategy_fn = base_strategy.get("strategy_fn")

        args_list = [
            (
                ticks,
                strategy_fn,
                initial_capital,
                base_kwargs,
                dict(zip(param_names, combo, strict=True)),
            )
            for combo in combinations
        ]

        pool = self._ensure_pool()

        if progress_callback is not None:
            results: list[BacktestResult] = []
            for i, result in enumerate(pool.imap(_run_param_sweep_single, args_list)):
                results.append(result)
                progress_callback(i + 1, len(args_list))
            return results

        return pool.map(_run_param_sweep_single, args_list)

    @staticmethod
    def _run_single(
        strategy: dict[str, Any],
        ticks: list[dict[str, Any]],
        initial_capital: float,
    ) -> BacktestResult:
        backtester = TickLevelBacktester(**strategy.get("backtester_kwargs", {}))
        return backtester.run(
            ticks=ticks,
            strategy_fn=strategy.get("strategy_fn"),
            initial_capital=initial_capital,
        )
