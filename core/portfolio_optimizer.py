from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


__all__ = [
    "OptimizationMethod",
    "PortfolioOptimizer",
    "OptimizationResult",
    "mean_variance_optimize",
    "risk_parity_optimize",
    "ic_weighted_optimize",
]


def mean_variance_optimize(
    expected_returns: np.ndarray,
    cov: np.ndarray,
    max_weight: float = 1.0,
    min_weight: float = 0.0,
) -> np.ndarray:
    n = len(expected_returns)
    if n == 0:
        return np.array([])
    cov = _regularize_cov_internal(cov)
    ones = np.ones(n)
    try:
        inv_cov = np.linalg.inv(cov)
        w = inv_cov @ ones
        w = w / w.sum()
        w = np.clip(w, min_weight, max_weight)
        w = w / w.sum()
    except np.linalg.LinAlgError:
        w = np.ones(n) / n
    return w


def risk_parity_optimize(
    cov: np.ndarray,
    max_weight: float = 1.0,
    min_weight: float = 0.0,
) -> np.ndarray:
    n = cov.shape[0]
    if n == 0:
        return np.array([])
    target_risk = 1.0 / n

    def risk_contribution(w: np.ndarray) -> np.ndarray:
        portfolio_var = w @ cov @ w
        if portfolio_var < 1e-12:
            return np.zeros(n)
        marginal = cov @ w
        return np.array(w * marginal / np.sqrt(portfolio_var), dtype=float)

    def risk_parity_objective(w: np.ndarray) -> float:
        rc = risk_contribution(w)
        return float(np.sum((rc - target_risk) ** 2))

    w = np.ones(n) / n
    m = np.zeros(n)
    v = np.zeros(n)
    beta1, beta2, eps_adam = 0.9, 0.999, 1e-8
    lr = 0.01

    for iteration in range(500):
        grad = np.zeros(n)
        eps = 1e-6
        for i in range(n):
            w_plus = w.copy()
            w_plus[i] += eps
            loss_plus = risk_parity_objective(w_plus)
            w_minus = w.copy()
            w_minus[i] -= eps
            loss_minus = risk_parity_objective(w_minus)
            grad[i] = (loss_plus - loss_minus) / (2 * eps)

        m = beta1 * m + (1 - beta1) * grad
        v = beta2 * v + (1 - beta2) * grad ** 2
        m_hat = m / (1 - beta1 ** (iteration + 1))
        v_hat = v / (1 - beta2 ** (iteration + 1))
        w = w - lr * m_hat / (np.sqrt(v_hat) + eps_adam)
        w = np.clip(w, min_weight, max_weight)
        total = w.sum()
        if total > 0:
            w = w / total

        curr_obj = risk_parity_objective(w)
        if curr_obj < 1e-10:
            break
    return w


def ic_weighted_optimize(
    ics: np.ndarray,
    vols: np.ndarray,
) -> np.ndarray:
    n = len(ics)
    if n == 0:
        return np.array([])
    ic_ratio = np.maximum(ics, 0) / np.maximum(vols, 1e-8)
    total = ic_ratio.sum()
    weights = np.zeros_like(ic_ratio, dtype=float)
    if total > 0:
        weights = (ic_ratio / total).astype(float)
    return weights.astype(float)


def _regularize_cov_internal(cov: np.ndarray, delta: float = 0.01) -> np.ndarray:
    n = cov.shape[0]
    diag = np.diag(cov)
    if np.any(diag <= 0):
        cov = cov + delta * np.eye(n)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    eigenvalues = np.maximum(eigenvalues, 1e-8)
    cov = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
    return cov


class OptimizationMethod(Enum):
    MARKOWITZ = "markowitz"
    RISK_PARITY = "risk_parity"
    MIN_VARIANCE = "min_variance"
    MAX_SHARPE = "max_sharpe"


@dataclass
class OptimizationResult:
    weights: dict[str, float]
    expected_return: float
    volatility: float
    sharpe_ratio: float
    method: OptimizationMethod
    efficient_frontier: list[dict] | None


class PortfolioOptimizer:
    def __init__(
        self,
        risk_free_rate: float = 0.03,
        max_weight: float = 1.0,
        min_weight: float = 0.0,
    ):
        self._rf = risk_free_rate
        self._max_weight = max_weight
        self._min_weight = min_weight

    def optimize(
        self,
        returns: pd.DataFrame | np.ndarray,
        cov: np.ndarray | None = None,
        method: str | OptimizationMethod = OptimizationMethod.MARKOWITZ,
        target_return: float | None = None,
        long_only: bool = True,
        max_weight: float = 1.0,
        min_weight: float = 0.0,
    ) -> np.ndarray | OptimizationResult:
        if isinstance(returns, np.ndarray):
            if cov is None:
                raise ValueError("cov matrix required when returns is ndarray")
            method_enum = OptimizationMethod.MARKOWITZ if isinstance(method, str) else method
            if method_enum == OptimizationMethod.MIN_VARIANCE:
                return mean_variance_optimize(returns, cov, max_weight, min_weight)
            elif method_enum == OptimizationMethod.RISK_PARITY:
                return risk_parity_optimize(cov, max_weight, min_weight)
            elif method_enum == OptimizationMethod.MAX_SHARPE:
                return self._max_sharpe(returns, cov, long_only, max_weight, min_weight)
            else:
                return mean_variance_optimize(returns, cov, max_weight, min_weight)

        if returns.empty or returns.shape[1] < 2:
            raise ValueError("Need at least 2 assets with return data")

        symbols = list(returns.columns)
        n = len(symbols)
        mean_ret = returns.mean().values.astype(float)
        cov_mat = returns.cov().values.astype(float)
        if cov is not None:
            cov_mat = cov.values.astype(float) if hasattr(cov, "values") else np.asarray(cov, dtype=float)

        cov_mat = self._regularize_cov(cov_mat)

        if method == OptimizationMethod.MIN_VARIANCE:
            w = self._min_variance(cov_mat, long_only, max_weight, min_weight)
        elif method == OptimizationMethod.MAX_SHARPE:
            w = self._max_sharpe(mean_ret, cov_mat, long_only, max_weight, min_weight)
        elif method == OptimizationMethod.RISK_PARITY:
            w = risk_parity_optimize(cov_mat, max_weight, min_weight)
        elif method == OptimizationMethod.MARKOWITZ:
            w = self._markowitz(mean_ret, cov_mat, target_return, long_only, max_weight, min_weight)
        else:
            raise ValueError(f"Unknown optimization method: {method}")

        weights = {symbols[i]: float(w[i]) for i in range(n)}
        exp_ret = float(np.dot(w, mean_ret)) * 252
        vol = float(np.sqrt(w @ cov_mat @ w)) * np.sqrt(252)
        sharpe = (exp_ret - self._rf) / vol if vol > 1e-12 else 0.0

        frontier = None
        if method == OptimizationMethod.MARKOWITZ and target_return is not None:
            frontier = self._build_frontier(mean_ret, cov_mat, long_only, max_weight, min_weight)

        return OptimizationResult(
            weights=weights,
            expected_return=round(exp_ret, 4),
            volatility=round(vol, 4),
            sharpe_ratio=round(sharpe, 4),
            method=method if isinstance(method, OptimizationMethod) else OptimizationMethod.MARKOWITZ,
            efficient_frontier=frontier,
        )

    def get_portfolio_report(
        self,
        weights: np.ndarray,
        expected_returns: np.ndarray,
        cov: np.ndarray,
        symbols: list[str],
    ) -> dict:
        n = len(weights)
        if n == 0:
            return {"weights": {}, "expected_return": 0.0, "volatility": 0.0,
                    "sharpe_ratio": 0.0, "risk_contribution": {}}

        weights_dict = {symbols[i]: float(weights[i]) for i in range(n)}
        exp_ret = float(np.dot(weights, expected_returns)) * 252
        vol = float(np.sqrt(weights @ cov @ weights)) * np.sqrt(252)
        sharpe = (exp_ret - self._rf) / vol if vol > 1e-12 else 0.0

        marginal_risk = cov @ weights
        portfolio_var = weights @ marginal_risk
        risk_contrib = {}
        if portfolio_var > 1e-12:
            for i, sym in enumerate(symbols):
                risk_contrib[sym] = round(float(weights[i] * marginal_risk[i] / np.sqrt(portfolio_var)), 4)

        return {
            "weights": weights_dict,
            "expected_return": round(exp_ret, 4),
            "volatility": round(vol, 4),
            "sharpe_ratio": round(sharpe, 4),
            "risk_contribution": risk_contrib,
        }

    def efficient_frontier(
        self,
        expected_returns: np.ndarray,
        cov: np.ndarray,
        n_points: int = 20,
        target_return: float | None = None,
    ) -> list[dict]:
        if len(expected_returns) == 0 or cov.shape[0] == 0:
            return []
        if len(expected_returns) == 1:
            return []
        cov = _regularize_cov_internal(cov)
        min_ret = float(np.min(expected_returns) * 252)
        max_ret = float(np.max(expected_returns) * 252)
        if abs(max_ret - min_ret) < 1e-12:
            w = mean_variance_optimize(expected_returns, cov, self._max_weight, self._min_weight)
            exp_r = float(np.dot(w, expected_returns)) * 252
            vol = float(np.sqrt(w @ cov @ w)) * np.sqrt(252)
            return [{"return": round(exp_r, 4), "volatility": round(vol, 4), "sharpe": 0.0}]
        targets = np.linspace(min_ret, max_ret, n_points)
        frontier = []
        for tgt in targets:
            w = self._markowitz(
                expected_returns, cov, tgt,
                long_only=True, max_weight=self._max_weight, min_weight=self._min_weight,
            )
            exp_r = float(np.dot(w, expected_returns)) * 252
            vol = float(np.sqrt(w @ cov @ w)) * np.sqrt(252)
            sharpe = (exp_r - self._rf) / vol if vol > 1e-12 else 0.0
            frontier.append({"return": round(exp_r, 4), "volatility": round(vol, 4), "sharpe": round(sharpe, 4)})
        return frontier

    def _regularize_cov(self, cov: np.ndarray, delta: float = 0.01) -> np.ndarray:
        n = cov.shape[0]
        diag = np.diag(cov)
        if np.any(diag <= 0):
            logger.debug("Covariance diagonal contains non-positive values, applying regularization")
            cov = cov + delta * np.eye(n)
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
        eigenvalues = np.maximum(eigenvalues, 1e-8)
        cov = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
        return cov

    def _min_variance(
        self,
        cov: np.ndarray,
        long_only: bool,
        max_weight: float,
        min_weight: float,
    ) -> np.ndarray:
        n = cov.shape[0]
        w = np.ones(n) / n
        if long_only:
            ones = np.ones(n)
            try:
                inv_cov = np.linalg.inv(cov)
                w = inv_cov @ ones
                w = w / w.sum()
                w = np.clip(w, min_weight, max_weight)
                w = w / w.sum()
                return w
            except np.linalg.LinAlgError:
                logger.warning("Covariance matrix singular, using diagonal inversion")
                diag_inv = 1.0 / np.diag(cov)
                w = diag_inv / diag_inv.sum()
        else:
            try:
                inv_cov = np.linalg.inv(cov)
                ones = np.ones(n)
                w = inv_cov @ ones
                w = w / w.sum()
                return w
            except np.linalg.LinAlgError:
                diag_inv = 1.0 / np.diag(cov)
                w = diag_inv / diag_inv.sum()
        return w

    def _max_sharpe(
        self,
        mean_ret: np.ndarray,
        cov: np.ndarray,
        long_only: bool,
        max_weight: float,
        min_weight: float,
    ) -> np.ndarray:
        n = len(mean_ret)
        if long_only:
            ones = np.ones(n)
            try:
                inv_cov = np.linalg.inv(cov)
                numerator = inv_cov @ (mean_ret - self._rf)
                denominator = ones @ numerator
                if abs(denominator) < 1e-12:
                    return self._min_variance(cov, long_only, max_weight, min_weight)
                w = numerator / denominator
                w = np.clip(w, min_weight, max_weight)
                total = w.sum()
                if total > 0:
                    w = w / total
                else:
                    return np.ones(n) / n
                return np.array(w, dtype=float)
            except np.linalg.LinAlgError:
                ratios = (mean_ret - self._rf) / np.diag(cov)
                w = np.maximum(ratios, 0)
                total = w.sum()
                if total > 0:
                    return np.array(w / total, dtype=float)
                return np.ones(n) / n
        else:
            try:
                inv_cov = np.linalg.inv(cov)
                target = mean_ret - self._rf
                w = inv_cov @ target
                s = w.sum()
                if s != 0:
                    return np.array(w / s, dtype=float)
                return np.ones(n) / n
            except np.linalg.LinAlgError:
                ratios = (mean_ret - self._rf) / np.diag(cov)
                w = np.maximum(ratios, 0)
                total = w.sum()
                if total > 0:
                    return np.array(w / total, dtype=float)
                return np.ones(n) / n
        return np.ones(n) / n

    def _markowitz(
        self,
        mean_ret: np.ndarray,
        cov: np.ndarray,
        target_return: float | None,
        long_only: bool,
        max_weight: float,
        min_weight: float,
    ) -> np.ndarray:
        n = len(mean_ret)
        if target_return is None:
            target_return = float(np.mean(mean_ret) * 252)
        try:
            inv_cov = np.linalg.inv(cov)
            ones = np.ones(n)
            numerator = inv_cov @ ones
            denominator = ones @ numerator
            if abs(denominator) < 1e-12:
                return np.ones(n) / n
            w_min_var = numerator / denominator
            w_min_var = np.clip(w_min_var, min_weight, max_weight)
            t = w_min_var.sum()
            if t > 0:
                w_min_var = w_min_var / t
            min_ret = float(np.dot(w_min_var, mean_ret) * 252)
            max_ret = float(np.max(mean_ret) * 252)
            if target_return < min_ret or target_return > max_ret:
                target_return = min_ret
            ret_diff = target_return - min_ret
            if ret_diff < 1e-12:
                return w_min_var
            target_excess = (target_return / 252) - (min_ret / 252)
            min_var_ret = float(np.dot(w_min_var, mean_ret))
            denom_diff = float(np.dot(mean_ret, inv_cov @ mean_ret)) / (ones @ inv_cov @ mean_ret) - min_var_ret
            if abs(denom_diff) < 1e-12:
                return w_min_var
            diff = target_excess / denom_diff
            diff = np.clip(diff, 0, 1)
            tangency = inv_cov @ mean_ret
            denom_t = ones @ tangency
            if abs(denom_t) < 1e-12:
                return w_min_var
            w_tangency = tangency / denom_t
            w_target = (1 - diff) * w_min_var + diff * w_tangency
            w_target = np.clip(w_target, min_weight, max_weight)
            t = w_target.sum()
            if t > 0:
                w_target = w_target / t
            return np.array(w_target, dtype=float)
        except np.linalg.LinAlgError:
            logger.warning("Covariance matrix singular, falling back to equal weights")
            return np.ones(n) / n

    def _build_frontier(
        self,
        mean_ret: np.ndarray,
        cov: np.ndarray,
        long_only: bool,
        max_weight: float,
        min_weight: float,
    ) -> list[dict]:
        frontier = []
        min_ret = float(np.min(mean_ret) * 252)
        max_ret = float(np.max(mean_ret) * 252)
        for target in np.linspace(min_ret, max_ret, 20):
            try:
                w = self._markowitz(mean_ret, cov, target, long_only, max_weight, min_weight)
                exp_r = float(np.dot(w, mean_ret)) * 252
                vol = float(np.sqrt(w @ cov @ w)) * np.sqrt(252)
                sharpe = (exp_r - self._rf) / vol if vol > 1e-12 else 0.0
                frontier.append({
                    "return": round(exp_r, 4),
                    "volatility": round(vol, 4),
                    "sharpe": round(sharpe, 4),
                })
            except Exception as e:
                logger.debug("Frontier point failed: %s", e)
        return frontier
