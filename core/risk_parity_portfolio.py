__all__ = [
    "RiskParityPortfolio",
    "PortfolioState",
    "ICWeightedRiskParity",
]

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.factor_validity import FactorValidityMonitor
from core.portfolio_optimizer import risk_parity_optimize, ic_weighted_optimize

logger = logging.getLogger(__name__)


@dataclass
class PortfolioState:
    weights: dict[str, float] = field(default_factory=dict)
    risk_contributions: dict[str, float] = field(default_factory=dict)
    portfolio_volatility: float = 0.0
    ic_adjustments: dict[str, float] = field(default_factory=dict)
    rebalance_needed: bool = False
    max_drift: float = 0.0


class RiskParityPortfolio:
    def __init__(
        self,
        symbols: list[str],
        lookback: int = 60,
        drift_threshold: float = 0.05,
        turnover_cap: float = 0.30,
        ic_threshold: float = 0.03,
        ic_weight_scale: float = 0.5,
    ):
        self._symbols = symbols
        self._lookback = lookback
        self._drift_threshold = drift_threshold
        self._turnover_cap = turnover_cap
        self._ic_weight_scale = ic_weight_scale
        self._factor_monitor = FactorValidityMonitor(lookback=lookback, ic_threshold=ic_threshold)
        self._current_weights: dict[str, float] = {}
        self._returns_buffer: list[np.ndarray] = []
        self._n_assets = len(symbols)

    def update_returns(self, returns: np.ndarray | pd.Series) -> None:
        arr = np.asarray(returns, dtype=float)
        if len(arr) != self._n_assets:
            logger.warning("Returns length %d != n_assets %d", len(arr), self._n_assets)
            return
        self._returns_buffer.append(arr)
        if len(self._returns_buffer) > self._lookback:
            self._returns_buffer = self._returns_buffer[-self._lookback:]

    def update_ic(self, symbol: str, predicted_score: float, actual_return: float) -> None:
        self._factor_monitor.update(symbol, predicted_score, actual_return)

    def compute_target_weights(self) -> PortfolioState:
        if len(self._returns_buffer) < 20:
            equal_w = 1.0 / self._n_assets
            return PortfolioState(
                weights={s: round(equal_w, 4) for s in self._symbols},
                risk_contributions={s: round(equal_w, 4) for s in self._symbols},
                portfolio_volatility=0.0,
            )

        returns_matrix = np.array(self._returns_buffer)
        cov = np.cov(returns_matrix.T)
        if cov.ndim == 0:
            cov = np.array([[float(cov)]])

        if cov.shape[0] != self._n_assets or cov.shape[1] != self._n_assets:
            equal_w = 1.0 / self._n_assets
            return PortfolioState(
                weights={s: round(equal_w, 4) for s in self._symbols},
                risk_contributions={s: round(equal_w, 4) for s in self._symbols},
                portfolio_volatility=0.0,
            )

        eigvals = np.linalg.eigvalsh(cov)
        if np.min(eigvals) < 1e-10:
            cov = cov + np.eye(self._n_assets) * (1e-10 - np.min(eigvals) + 1e-10)

        base_weights = risk_parity_optimize(cov)

        ic_adjustments: dict[str, float] = {}
        for i, sym in enumerate(self._symbols):
            adj = self._factor_monitor.get_weight_adjustment(sym)
            ic_adjustments[sym] = round(adj, 4)
            base_weights[i] *= adj

        total = base_weights.sum()
        if total > 1e-12:
            base_weights = base_weights / total

        portfolio_var = float(base_weights @ cov @ base_weights)
        portfolio_vol = float(np.sqrt(portfolio_var))

        risk_contribs: dict[str, float] = {}
        if portfolio_var > 1e-12:
            marginal = cov @ base_weights
            for i, sym in enumerate(self._symbols):
                rc = float(base_weights[i] * marginal[i] / np.sqrt(portfolio_var))
                risk_contribs[sym] = round(rc, 4)

        weights_dict = {self._symbols[i]: round(float(base_weights[i]), 4) for i in range(self._n_assets)}

        max_drift = 0.0
        rebalance_needed = False
        if self._current_weights:
            drifts = []
            for sym in self._symbols:
                current = self._current_weights.get(sym, 0.0)
                target = weights_dict.get(sym, 0.0)
                drifts.append(abs(target - current))
            max_drift = max(drifts) if drifts else 0.0
            rebalance_needed = max_drift >= self._drift_threshold

        return PortfolioState(
            weights=weights_dict,
            risk_contributions=risk_contribs,
            portfolio_volatility=round(portfolio_vol, 6),
            ic_adjustments=ic_adjustments,
            rebalance_needed=rebalance_needed,
            max_drift=round(max_drift, 4),
        )

    def apply_rebalance(self, target_state: PortfolioState) -> dict[str, float]:
        if not target_state.weights:
            return {}

        old_weights = dict(self._current_weights)
        new_weights = dict(target_state.weights)

        if not old_weights:
            self._current_weights = new_weights
            return new_weights

        deltas = {}
        for sym in self._symbols:
            deltas[sym] = new_weights.get(sym, 0.0) - old_weights.get(sym, 0.0)

        total_turnover = sum(abs(d) for d in deltas.values())
        if total_turnover > self._turnover_cap and total_turnover > 1e-12:
            scale = self._turnover_cap / total_turnover
            scaled_weights = {}
            for sym in self._symbols:
                delta = deltas[sym] * scale
                scaled_weights[sym] = round(old_weights.get(sym, 0.0) + delta, 4)
            total = sum(scaled_weights.values())
            if total > 1e-12:
                scaled_weights = {s: round(v / total, 4) for s, v in scaled_weights.items()}
            self._current_weights = scaled_weights
            return scaled_weights

        self._current_weights = new_weights
        return new_weights

    @property
    def current_weights(self) -> dict[str, float]:
        return dict(self._current_weights)

    @property
    def factor_summary(self) -> dict:
        return self._factor_monitor.summary()


class ICWeightedRiskParity:
    def __init__(
        self,
        ic_decay_half_life: int = 20,
        min_ic_weight: float = 0.3,
        max_ic_weight: float = 2.0,
    ):
        self._ic_decay_half_life = ic_decay_half_life
        self._min_ic_weight = min_ic_weight
        self._max_ic_weight = max_ic_weight

    def compute_weights(
        self,
        cov: np.ndarray,
        ics: np.ndarray,
    ) -> np.ndarray:
        n = cov.shape[0]
        if n == 0:
            return np.array([])
        if len(ics) != n:
            logger.warning("IC length %d != n_assets %d, falling back to equal weight", len(ics), n)
            return np.ones(n) / n

        base_weights = risk_parity_optimize(cov)

        ic_weights = np.zeros(n)
        for i in range(n):
            abs_ic = abs(float(ics[i]))
            if abs_ic < 0.01:
                ic_weights[i] = self._min_ic_weight
            else:
                raw = abs_ic / 0.03
                ic_weights[i] = np.clip(raw, self._min_ic_weight, self._max_ic_weight)

        adjusted = base_weights * ic_weights
        total = adjusted.sum()
        if total > 1e-12:
            adjusted = adjusted / total
        else:
            adjusted = np.ones(n) / n

        return adjusted

    def compute_risk_contributions(
        self,
        weights: np.ndarray,
        cov: np.ndarray,
    ) -> np.ndarray:
        if len(weights) == 0 or cov.shape[0] == 0:
            return np.array([])
        portfolio_var = weights @ cov @ weights
        if portfolio_var < 1e-12:
            return np.zeros(len(weights))
        marginal = cov @ weights
        return np.array(weights * marginal / np.sqrt(portfolio_var), dtype=float)
