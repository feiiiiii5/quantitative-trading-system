import logging
from typing import Any, Callable

import numpy as np

from quantcore_backtest.tick_engine import BacktestResult, SlippageModel, TickLevelBacktester

logger = logging.getLogger(__name__)

try:
    import cupy as cp
    _GPU_AVAILABLE = True
    _xp = cp
    logger.info("CuPy detected — GPU acceleration enabled")
except ImportError:
    _GPU_AVAILABLE = False
    _xp = np
    logger.info("CuPy not available — falling back to NumPy")


def _to_host(arr: Any) -> np.ndarray:
    if _GPU_AVAILABLE and hasattr(arr, "get"):
        return arr.get()
    return np.asarray(arr)


class GPUAccelerator:
    def __init__(self) -> None:
        self._gpu_available = _GPU_AVAILABLE
        self._xp = _xp

    @property
    def gpu_available(self) -> bool:
        return self._gpu_available

    def compute_portfolio_vectorized(
        self,
        returns_matrix: np.ndarray,
        weights: np.ndarray,
    ) -> np.ndarray:
        xp = self._xp

        if returns_matrix.ndim != 2:
            raise ValueError(f"returns_matrix must be 2-D, got {returns_matrix.ndim}-D")
        if weights.ndim != 1:
            raise ValueError(f"weights must be 1-D, got {weights.ndim}-D")
        if returns_matrix.shape[1] != weights.shape[0]:
            raise ValueError(
                f"Dimension mismatch: returns_matrix has {returns_matrix.shape[1]} "
                f"assets but weights has {weights.shape[0]} elements"
            )

        ret_xp = xp.asarray(returns_matrix, dtype=xp.float64)
        w_xp = xp.asarray(weights, dtype=xp.float64)

        portfolio_returns = ret_xp @ w_xp
        return _to_host(portfolio_returns)

    def compute_drawdown_gpu(self, equity_curves: np.ndarray) -> np.ndarray:
        xp = self._xp

        if equity_curves.ndim == 1:
            equity_curves = equity_curves.reshape(1, -1)

        eq_xp = xp.asarray(equity_curves, dtype=xp.float64)
        peaks = xp.maximum.accumulate(eq_xp, axis=1)
        safe_peaks = xp.where(peaks > 1e-9, peaks, 1.0)
        drawdowns = (peaks - eq_xp) / safe_peaks

        return _to_host(drawdowns)

    def monte_carlo_sim_gpu(
        self,
        returns: np.ndarray,
        n_sims: int = 10_000,
        n_periods: int = 252,
    ) -> np.ndarray:
        xp = self._xp

        ret_xp = xp.asarray(returns, dtype=xp.float64)
        mean_ret = float(xp.mean(ret_xp))
        std_ret = float(xp.std(ret_xp))

        if std_ret < 1e-12:
            return np.full((n_sims, n_periods), mean_ret)

        rng = xp.random.default_rng(42)
        simulated = rng.normal(
            loc=mean_ret,
            scale=std_ret,
            size=(n_sims, n_periods),
        )

        cumulative = xp.cumprod(1.0 + simulated, axis=1)
        return _to_host(cumulative)

    def batch_backtest_gpu(
        self,
        ticks_batch: list[list[dict[str, Any]]],
        strategy_params_batch: list[dict[str, Any]],
        initial_capital: float = 1_000_000.0,
        strategy_fn: Callable | None = None,
    ) -> list[BacktestResult]:
        if len(ticks_batch) != len(strategy_params_batch):
            raise ValueError(
                f"Batch size mismatch: {len(ticks_batch)} tick batches vs "
                f"{len(strategy_params_batch)} strategy param sets"
            )

        if strategy_fn is None:
            strategy_fn = self._default_strategy_fn

        results: list[BacktestResult] = []
        for ticks, params in zip(ticks_batch, strategy_params_batch, strict=True):
            backtester = TickLevelBacktester(
                commission=params.get("commission", 0.0003),
                slippage_model=params.get("slippage_model") or SlippageModel.SQUARE_ROOT,
                slippage_base_bps=params.get("slippage_base_bps", 1.0),
                slippage_impact_coeff=params.get("slippage_impact_coeff", 0.1),
            )
            result = backtester.run(
                ticks=ticks,
                strategy_fn=strategy_fn,
                initial_capital=initial_capital,
            )
            results.append(result)

        if self._gpu_available and len(results) > 1:
            equity_arrays = np.array(
                [r.equity_curve for r in results if r.equity_curve],
                dtype=np.float64,
            )
            if equity_arrays.size > 0:
                _drawdowns = self.compute_drawdown_gpu(equity_arrays)

        return results

    @staticmethod
    def _default_strategy_fn(
        tick: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        return {}
