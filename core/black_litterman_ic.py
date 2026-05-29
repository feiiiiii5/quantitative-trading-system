__all__ = [
    "BlackLittermanIC",
    "BLView",
    "BLResult",
]

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BLView:
    asset_index: int
    expected_return: float
    confidence: float = 1.0


@dataclass
class BLResult:
    posterior_returns: np.ndarray
    posterior_cov: np.ndarray
    weights: np.ndarray
    prior_weights: np.ndarray
    view_deltas: dict[int, float] = field(default_factory=dict)


class BlackLittermanIC:
    def __init__(
        self,
        tau: float = 0.05,
        risk_aversion: float = 2.5,
        ic_confidence_scale: float = 1.0,
        min_view_confidence: float = 0.1,
        max_view_confidence: float = 5.0,
    ):
        self._tau = tau
        self._delta = risk_aversion
        self._ic_scale = ic_confidence_scale
        self._min_conf = min_view_confidence
        self._max_conf = max_view_confidence

    def optimize(
        self,
        cov: np.ndarray,
        market_weights: np.ndarray,
        views: list[BLView],
    ) -> BLResult:
        n = cov.shape[0]
        if n == 0:
            return BLResult(
                posterior_returns=np.array([]),
                posterior_cov=np.array([]),
                weights=np.array([]),
                prior_weights=np.array([]),
            )

        cov = self._ensure_positive_definite(cov)
        market_weights = self._normalize(market_weights)

        pi = self._delta * cov @ market_weights

        if not views:
            w = self._implied_weights(pi, cov)
            return BLResult(
                posterior_returns=pi,
                posterior_cov=self._tau * cov,
                weights=w,
                prior_weights=market_weights.copy(),
            )

        P = np.zeros((len(views), n))  # noqa: N806
        q = np.zeros(len(views))
        omega = np.zeros((len(views), len(views)))

        for i, view in enumerate(views):
            P[i, view.asset_index] = 1.0
            q[i] = view.expected_return
            conf = np.clip(view.confidence * self._ic_scale, self._min_conf, self._max_conf)
            omega[i, i] = 1.0 / conf

        tau_cov = self._tau * cov
        try:
            tau_cov_inv = np.linalg.inv(tau_cov)
        except np.linalg.LinAlgError:
            logger.warning("tau*Sigma singular, using pseudo-inverse")
            tau_cov_inv = np.linalg.pinv(tau_cov)

        omega_inv = np.linalg.inv(omega) if np.linalg.det(omega) != 0 else np.zeros_like(omega)

        M = tau_cov_inv + P.T @ omega_inv @ P  # noqa: N806
        try:
            M_inv = np.linalg.inv(M)  # noqa: N806
        except np.linalg.LinAlgError:
            M_inv = np.linalg.pinv(M)  # noqa: N806

        posterior_returns = M_inv @ (tau_cov_inv @ pi + P.T @ omega_inv @ q)
        posterior_cov = M_inv + cov

        w = self._implied_weights(posterior_returns, cov)

        view_deltas = {}
        for view in views:
            idx = view.asset_index
            view_deltas[idx] = round(float(posterior_returns[idx] - pi[idx]), 6)

        return BLResult(
            posterior_returns=posterior_returns,
            posterior_cov=posterior_cov,
            weights=w,
            prior_weights=market_weights.copy(),
            view_deltas=view_deltas,
        )

    def optimize_with_ic(
        self,
        cov: np.ndarray,
        market_weights: np.ndarray,
        factor_ics: dict[int, float],
        factor_returns: dict[int, float],
        ic_ir_threshold: float = 0.5,
    ) -> BLResult:
        views: list[BLView] = []
        for idx, ic in factor_ics.items():
            if idx >= cov.shape[0]:
                continue
            abs_ic = abs(ic)
            if abs_ic < 0.01:
                continue
            expected_ret = factor_returns.get(idx, 0.0)
            if abs(expected_ret) < 1e-10:
                continue
            confidence = min(abs_ic * 10.0, self._max_conf)
            if abs_ic / 0.03 > ic_ir_threshold:
                confidence *= 1.5
            views.append(BLView(
                asset_index=idx,
                expected_return=expected_ret,
                confidence=confidence,
            ))

        return self.optimize(cov, market_weights, views)

    @staticmethod
    def _ensure_positive_definite(cov: np.ndarray, min_eigenvalue: float = 1e-10) -> np.ndarray:
        eigvals = np.linalg.eigvalsh(cov)
        min_ev = np.min(eigvals)
        if min_ev < min_eigenvalue:
            cov = cov + (min_eigenvalue - min_ev + 1e-10) * np.eye(cov.shape[0])
        return cov

    @staticmethod
    def _normalize(w: np.ndarray) -> np.ndarray:
        total = w.sum()
        if total > 1e-12:
            return w / total
        n = len(w)
        return np.ones(n) / n

    def _implied_weights(self, mu: np.ndarray, cov: np.ndarray) -> np.ndarray:
        try:
            inv_cov = np.linalg.inv(cov)
        except np.linalg.LinAlgError:
            inv_cov = np.linalg.pinv(cov)
        w = inv_cov @ mu
        w = np.maximum(w, 0)
        total = w.sum()
        if total > 1e-12:
            return w / total
        n = len(w)
        return np.ones(n) / n
