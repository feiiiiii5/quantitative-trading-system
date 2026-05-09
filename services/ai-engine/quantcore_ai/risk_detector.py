import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

_MIN_DATA_POINTS = 30


@dataclass
class FlashCrashEvent:
    start_index: int
    peak_index: int
    recovery_index: int | None
    drop_pct: float
    duration_bars: int
    severity: str


@dataclass
class StressScenario:
    name: str
    factor_shocks: dict[str, float]
    portfolio_impact: float
    probability: float


class AIRiskDetector:

    def detect_anomalies(
        self,
        returns: pd.Series,
        window: int = 60,
        threshold: float = 3.0,
    ) -> pd.Series:
        if len(returns) < window:
            logger.warning("Insufficient data for anomaly detection: %d < %d", len(returns), window)
            return pd.Series(dtype=float, name="anomaly_zscore")

        rolling_mean = returns.rolling(window).mean()
        rolling_std = returns.rolling(window).std()
        z_scores = (returns - rolling_mean) / (rolling_std + 1e-10)
        z_scores.name = "anomaly_zscore"

        n_anomalies = int((z_scores.abs() > threshold).sum())
        logger.info("Detected %d anomalies (threshold=%.1f, window=%d)", n_anomalies, threshold, window)
        return z_scores

    def detect_regime_change(
        self,
        prices: pd.Series,
        min_length: int = 20,
    ) -> list[int]:
        if len(prices) < 2 * min_length:
            logger.warning("Insufficient data for regime change detection")
            return []

        returns = prices.pct_change().dropna()
        change_points = self._cusum_detect(returns.values, min_length)

        logger.info("Detected %d regime change points", len(change_points))
        return change_points

    def estimate_var_ml(
        self,
        returns: pd.DataFrame,
        confidence: float = 0.95,
    ) -> float:
        if returns.empty:
            return 0.0

        if isinstance(returns, pd.DataFrame):
            portfolio_returns = returns.mean(axis=1)
        else:
            portfolio_returns = returns

        clean = portfolio_returns.dropna()
        if len(clean) < _MIN_DATA_POINTS:
            logger.warning("Insufficient data for ML VaR estimation")
            return float(np.percentile(clean, (1 - confidence) * 100)) if len(clean) > 0 else 0.0

        var_historic = float(np.percentile(clean, (1 - confidence) * 100))

        try:
            from sklearn.neighbors import KernelDensity

            kde = KernelDensity(bandwidth="scott", kernel="gaussian")
            kde.fit(clean.values.reshape(-1, 1))

            n_samples = 10000
            samples = kde.sample(n_samples, random_state=42).flatten()
            var_kde = float(np.percentile(samples, (1 - confidence) * 100))

            result = max(var_historic, var_kde)
            logger.info("ML VaR(%.0f%%): historic=%.4f, kde=%.4f, selected=%.4f",
                        confidence * 100, var_historic, var_kde, result)
            return result
        except ImportError:
            logger.info("scikit-learn not available, using historic VaR")
            return var_historic

    def detect_flash_crash(
        self,
        orderbook_snapshots: list[dict],
        threshold_pct: float = 5.0,
    ) -> list[dict]:
        if not orderbook_snapshots or len(orderbook_snapshots) < 3:
            return []

        events: list[FlashCrashEvent] = []
        prices = np.array([
            float(s.get("mid_price", s.get("last_price", 0)))
            for s in orderbook_snapshots
        ])

        if len(prices) < 3:
            return []

        i = 0
        while i < len(prices) - 2:
            peak_idx = i
            for j in range(i + 1, min(i + 60, len(prices))):
                if prices[j] > prices[peak_idx]:
                    peak_idx = j

            if peak_idx == i:
                i += 1
                continue

            drop_pct = (prices[peak_idx] - prices[peak_idx + 1:]) / (prices[peak_idx] + 1e-10) * 100
            significant = np.where(drop_pct >= threshold_pct)[0]

            if len(significant) == 0:
                i = peak_idx + 1
                continue

            trough_offset = significant[0]
            trough_idx = peak_idx + 1 + trough_offset
            max_drop = float(drop_pct[trough_offset])

            recovery_idx = None
            for k in range(trough_idx + 1, min(trough_idx + 120, len(prices))):
                if prices[k] >= prices[peak_idx] * 0.98:
                    recovery_idx = k
                    break

            if max_drop >= 10:
                severity = "critical"
            elif max_drop >= threshold_pct:
                severity = "warning"
            else:
                severity = "info"

            events.append(FlashCrashEvent(
                start_index=i,
                peak_index=peak_idx,
                recovery_index=recovery_idx,
                drop_pct=round(max_drop, 2),
                duration_bars=trough_idx - peak_idx,
                severity=severity,
            ))

            i = (recovery_idx if recovery_idx is not None else trough_idx) + 1

        logger.info("Detected %d flash crash events (threshold=%.1f%%)", len(events), threshold_pct)
        return [
            {
                "start_index": e.start_index,
                "peak_index": e.peak_index,
                "recovery_index": e.recovery_index,
                "drop_pct": e.drop_pct,
                "duration_bars": e.duration_bars,
                "severity": e.severity,
            }
            for e in events
        ]

    def compute_stress_scenarios(
        self,
        positions: dict[str, float],
        factors: pd.DataFrame,
        n_scenarios: int = 1000,
    ) -> list[dict]:
        if not positions or factors.empty:
            return []

        factor_returns = factors.pct_change().dropna()
        if len(factor_returns) < _MIN_DATA_POINTS:
            logger.warning("Insufficient factor history for stress testing")
            return []

        mean_returns = factor_returns.mean().values
        cov_matrix = factor_returns.cov().values

        try:
            rng = np.random.default_rng(seed=42)
            simulated = rng.multivariate_normal(mean_returns, cov_matrix, size=n_scenarios)
        except np.linalg.LinAlgError:
            logger.warning("Covariance matrix not positive semi-definite, using diagonal approximation")
            variances = np.diag(cov_matrix)
            rng = np.random.default_rng(seed=42)
            simulated = rng.normal(mean_returns, np.sqrt(np.maximum(variances, 0)), size=(n_scenarios, len(mean_returns)))

        worst_pct = 5
        n_worst = max(n_scenarios * worst_pct // 100, 1)

        portfolio_impacts = np.zeros(n_scenarios)
        factor_names = list(factor_returns.columns)

        for i, sim in enumerate(simulated):
            impact = 0.0
            for symbol, weight in positions.items():
                matching = [j for j, fn in enumerate(factor_names) if fn.lower() in symbol.lower() or symbol.lower() in fn.lower()]
                if matching:
                    factor_impact = sum(sim[j] for j in matching) / len(matching)
                else:
                    factor_impact = float(np.mean(sim))
                impact += weight * factor_impact
            portfolio_impacts[i] = impact

        worst_indices = np.argsort(portfolio_impacts)[:n_worst]

        scenarios: list[StressScenario] = []
        for rank, idx in enumerate(worst_indices):
            shock_dict = {fn: float(simulated[idx, j]) for j, fn in enumerate(factor_names)}
            scenarios.append(StressScenario(
                name=f"stress_worst_{rank + 1}",
                factor_shocks=shock_dict,
                portfolio_impact=round(float(portfolio_impacts[idx]), 6),
                probability=worst_pct / 100.0,
            ))

        tail_idx = np.argmin(portfolio_impacts)
        scenarios.insert(0, StressScenario(
            name="tail_event",
            factor_shocks={fn: float(simulated[tail_idx, j]) for j, fn in enumerate(factor_names)},
            portfolio_impact=round(float(portfolio_impacts[tail_idx]), 6),
            probability=1.0 / n_scenarios,
        ))

        logger.info("Generated %d stress scenarios from %d Monte Carlo simulations", len(scenarios), n_scenarios)
        return [
            {
                "name": s.name,
                "factor_shocks": s.factor_shocks,
                "portfolio_impact": s.portfolio_impact,
                "probability": s.probability,
            }
            for s in scenarios
        ]

    def _cusum_detect(self, returns: np.ndarray, min_length: int) -> list[int]:
        n = len(returns)
        if n < 2 * min_length:
            return []

        cumsum = np.cumsum(returns)
        change_points: list[int] = []

        threshold = np.std(returns) * 2.0
        if threshold < 1e-10:
            return []

        s_pos = np.zeros(n)
        s_neg = np.zeros(n)

        for i in range(1, n):
            s_pos[i] = max(0, s_pos[i - 1] + returns[i] - np.mean(returns[:i]))
            s_neg[i] = min(0, s_neg[i - 1] + returns[i] - np.mean(returns[:i]))

            if s_pos[i] > threshold or s_neg[i] < -threshold:
                if not change_points or (i - change_points[-1]) >= min_length:
                    change_points.append(i)
                s_pos[i] = 0
                s_neg[i] = 0

        return change_points
