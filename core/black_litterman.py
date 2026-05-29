"""
QuantCore Black-Litterman 模型
将投资者观点融入均衡收益，生成更稳定的投资组合配置
使用 Ledoit-Wolf 收缩估计增强协方差矩阵的数值稳定性
"""
import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


@dataclass
class BlackLittermanResult:
    posterior_returns: dict[str, float]
    posterior_covariance: dict[str, dict[str, float]]
    weights: dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    is_valid: bool
    message: str


def _ledoit_wolf_shrinkage(returns: pd.DataFrame) -> np.ndarray:
    """Ledoit-Wolf shrinkage estimator for covariance matrix."""
    x = returns.values
    n, p = x.shape

    mean = x.mean(axis=0)
    z = x - mean

    sample_cov = np.dot(z.T, z) / n

    target = np.trace(sample_cov) / p * np.eye(p)

    z2 = z ** 2
    phi_mat = np.dot(z2.T, z2) / n - sample_cov ** 2
    phi = np.sum(phi_mat)

    gamma = np.sum((sample_cov - target) ** 2)

    if gamma < 1e-15:
        return sample_cov

    kappa = phi / gamma
    delta = max(0.0, min(1.0, kappa / n))

    return delta * target + (1 - delta) * sample_cov


class BlackLittermanModel:

    def __init__(
        self,
        risk_free_rate: float = 0.03,
        tau: float = 0.05,
        min_weight: float = 0.0,
        max_weight: float = 1.0,
        risk_aversion: float = 2.5,
    ):
        self.risk_free_rate = risk_free_rate
        self.tau = tau
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.risk_aversion = risk_aversion

    def _equilibrium_returns(
        self,
        cov_matrix: np.ndarray,
        market_weights: np.ndarray,
    ) -> np.ndarray:
        """Implied equilibrium returns: pi = delta * Sigma * w_mkt"""
        return self.risk_aversion * cov_matrix @ market_weights

    def _posterior_distribution(
        self,
        pi: np.ndarray,
        sigma: np.ndarray,
        pick_matrix: np.ndarray,
        view_returns: np.ndarray,
        omega: np.ndarray,
    ) -> tuple:
        """
        Compute posterior returns and covariance.

        pick_matrix: K x N matrix — pick matrix (which assets each view applies to)
        view_returns: K vector — view returns
        omega: K x K — view uncertainty matrix
        """
        tau_sigma = self.tau * sigma
        try:
            tau_sigma_inv = np.linalg.inv(tau_sigma)
        except np.linalg.LinAlgError:
            tau_sigma_inv = np.linalg.pinv(tau_sigma)

        try:
            omega_inv = np.linalg.inv(omega)
        except np.linalg.LinAlgError:
            omega_inv = np.linalg.pinv(omega)

        posterior_cov_inv = tau_sigma_inv + pick_matrix.T @ omega_inv @ pick_matrix
        try:
            posterior_cov = np.linalg.inv(posterior_cov_inv)
        except np.linalg.LinAlgError:
            posterior_cov = np.linalg.pinv(posterior_cov_inv)

        posterior_returns = posterior_cov @ (tau_sigma_inv @ pi + pick_matrix.T @ omega_inv @ view_returns)
        posterior_cov_sum = sigma + posterior_cov

        return posterior_returns, posterior_cov_sum

    def optimize(
        self,
        prices: pd.DataFrame,
        views: list[dict[str, Any]] | None = None,
        market_weights: dict[str, float] | None = None,
        view_confidences: list[float] | None = None,
    ) -> BlackLittermanResult:
        """
        Run Black-Litterman optimization.

        Parameters
        ----------
        prices : DataFrame with asset prices (columns=assets)
        views : List of dicts with keys:
            - "assets": List[str] — assets the view applies to
            - "signs": List[float] — +1/-1 for long/short in each asset
            - "return": float — expected return of this view
        market_weights : Optional market cap weights. If None, equal weight.
        view_confidences : Optional confidence [0,1] for each view.
        """
        try:
            returns = np.log(prices / prices.shift(1)).dropna()
            if len(returns) < 10:
                return BlackLittermanResult(
                    posterior_returns={}, posterior_covariance={},
                    weights={}, expected_return=0.0, expected_volatility=0.0,
                    sharpe_ratio=0.0, is_valid=False,
                    message="Insufficient data, need at least 10 days",
                )

            columns = prices.columns
            n = len(columns)
            views = views or []
            view_confidences = view_confidences or [0.5] * len(views)

            # Shrinkage covariance
            cov_arr = _ledoit_wolf_shrinkage(returns) * 252

            # Market weights
            if market_weights is not None:
                w_mkt = np.array([market_weights.get(col, 0.0) for col in columns])
                w_sum = w_mkt.sum()
                w_mkt = w_mkt / w_sum if w_sum > 0 else np.ones(n) / n
            else:
                w_mkt = np.ones(n) / n

            # Equilibrium returns
            pi = self._equilibrium_returns(cov_arr, w_mkt)

            # Build view matrices
            if len(views) > 0:
                n_views = len(views)
                pick_mat = np.zeros((n_views, n))
                view_rets = np.zeros(n_views)
                omega_diag = np.zeros(n_views)

                for k, view in enumerate(views):
                    assets = view.get("assets", [])
                    signs = view.get("signs", [1.0] * len(assets))
                    view_ret = view.get("return", 0.0)
                    confidence = view_confidences[k] if k < len(view_confidences) else 0.5

                    view_rets[k] = view_ret

                    for asset, sign in zip(assets, signs, strict=False):
                        if asset in columns:
                            idx = list(columns).index(asset)
                            pick_mat[k, idx] = sign

                    p_row = pick_mat[k]
                    omega_diag[k] = (1.0 / max(confidence, 0.01)) * (p_row @ cov_arr @ p_row.T)

                omega = np.diag(omega_diag)

                posterior_ret, posterior_cov = self._posterior_distribution(
                    pi, cov_arr, pick_mat, view_rets, omega
                )
            else:
                posterior_ret = pi
                posterior_cov = cov_arr

            # Optimize: max Sharpe using posterior
            ret_arr = posterior_ret

            def neg_sharpe(w: np.ndarray) -> float:
                port_ret = np.dot(w, ret_arr)
                port_vol = np.sqrt(np.dot(w.T, np.dot(posterior_cov, w)))
                if port_vol < 1e-12:
                    return 0.0
                return -(port_ret - self.risk_free_rate) / port_vol

            bounds = tuple((self.min_weight, self.max_weight) for _ in range(n))
            constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
            x0 = w_mkt.copy()

            result = minimize(
                neg_sharpe, x0, method="SLSQP",
                bounds=bounds, constraints=constraints,
                options={"maxiter": 500, "ftol": 1e-10},
            )

            weights_arr = result.x if result.success else x0
            weights_arr = np.clip(weights_arr, 0.0, 1.0)
            total = np.sum(weights_arr)
            if total > 0:
                weights_arr = weights_arr / total

            weights_dict = {col: float(weights_arr[i]) for i, col in enumerate(columns)}
            post_ret_dict = {col: float(posterior_ret[i]) for i, col in enumerate(columns)}
            post_cov_dict = {
                col: {col2: float(posterior_cov[i, j])
                      for j, col2 in enumerate(columns)}
                for i, col in enumerate(columns)
            }

            exp_return = float(np.dot(weights_arr, ret_arr))
            exp_vol = float(np.sqrt(weights_arr.T @ posterior_cov @ weights_arr))
            sharpe = (exp_return - self.risk_free_rate) / exp_vol if exp_vol > 0 else 0.0

            return BlackLittermanResult(
                posterior_returns=post_ret_dict,
                posterior_covariance=post_cov_dict,
                weights=weights_dict,
                expected_return=exp_return,
                expected_volatility=exp_vol,
                sharpe_ratio=sharpe,
                is_valid=True,
                message="Black-Litterman optimization successful",
            )
        except Exception as e:
            logger.warning("Black-Litterman optimization failed: %s", e)
            return BlackLittermanResult(
                posterior_returns={}, posterior_covariance={},
                weights={}, expected_return=0.0, expected_volatility=0.0,
                sharpe_ratio=0.0, is_valid=False,
                message=f"Optimization failed: {e}",
            )
