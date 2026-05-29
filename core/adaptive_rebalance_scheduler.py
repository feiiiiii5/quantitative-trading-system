__all__ = [
    "AdaptiveRebalanceScheduler",
    "RebalanceDecision",
    "RebalanceVerdict",
]

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

from core.regime_detector import MarketRegime, MarketRegimeDetector

logger = logging.getLogger(__name__)


class RebalanceVerdict(StrEnum):
    REBALANCE_NOW = "rebalance_now"
    SKIP_LOW_DRIFT = "skip_low_drift"
    SKIP_RECENT_REBALANCE = "skip_recent_rebalance"
    SKIP_VOLATILE_MARKET = "skip_volatile_market"
    DEFER_CALM_MARKET = "defer_calm_market"


@dataclass
class RebalanceDecision:
    verdict: RebalanceVerdict
    current_drift: float
    drift_threshold: float
    regime: str
    regime_confidence: float
    days_since_last: int
    recommended_interval_days: int
    details: dict[str, Any] = field(default_factory=dict)


class AdaptiveRebalanceScheduler:
    def __init__(
        self,
        base_drift_threshold: float = 0.05,
        base_interval_days: int = 30,
        turnover_cap: float = 0.30,
        volatile_drift_multiplier: float = 1.5,
        calm_drift_multiplier: float = 0.7,
        min_interval_days: int = 5,
        max_interval_days: int = 90,
        cooldown_days: int = 3,
    ):
        self._base_drift = base_drift_threshold
        self._base_interval = base_interval_days
        self._turnover_cap = turnover_cap
        self._volatile_mult = volatile_drift_multiplier
        self._calm_mult = calm_drift_multiplier
        self._min_interval = min_interval_days
        self._max_interval = max_interval_days
        self._cooldown = cooldown_days

        self._detector = MarketRegimeDetector()
        self._last_rebalance_day: int = -999
        self._last_regime: str = ""
        self._last_regime_confidence: float = 0.0
        self._history: list[RebalanceDecision] = []

    def evaluate(
        self,
        current_weights: dict[str, float],
        target_weights: dict[str, float],
        day_index: int,
        market_df: Any = None,
    ) -> RebalanceDecision:
        drift = self._compute_max_drift(current_weights, target_weights)
        days_since = day_index - self._last_rebalance_day

        regime = "unknown"
        confidence = 0.0
        if market_df is not None:
            try:
                regime_enum, context = self._detector.detect(market_df)
                regime = regime_enum.value
                confidence = context.get("confidence", 0.0) if context else 0.0
            except Exception as e:
                logger.debug("Regime detection failed: %s", e)

        self._last_regime = regime
        self._last_regime_confidence = confidence

        adjusted_drift = self._adjust_drift_threshold(regime)
        recommended_interval = self._adjust_interval(regime)

        if days_since < self._cooldown:
            verdict = RebalanceVerdict.SKIP_RECENT_REBALANCE
        elif drift < adjusted_drift * 0.5 and regime in (
            MarketRegime.VOLATILE.value, MarketRegime.BEAR_DISTRIBUTION.value,
        ):
            verdict = RebalanceVerdict.SKIP_VOLATILE_MARKET
        elif drift < adjusted_drift:
            if regime in (MarketRegime.BULL_BASE.value, MarketRegime.UNKNOWN.value):
                verdict = RebalanceVerdict.DEFER_CALM_MARKET
            else:
                verdict = RebalanceVerdict.SKIP_LOW_DRIFT
        else:
            verdict = RebalanceVerdict.REBALANCE_NOW
            self._last_rebalance_day = day_index

        turnover = self._estimate_turnover(current_weights, target_weights)
        if turnover > self._turnover_cap and verdict == RebalanceVerdict.REBALANCE_NOW:
            verdict = RebalanceVerdict.SKIP_LOW_DRIFT
            self._last_rebalance_day = self._last_rebalance_day

        decision = RebalanceDecision(
            verdict=verdict,
            current_drift=round(drift, 6),
            drift_threshold=round(adjusted_drift, 6),
            regime=regime,
            regime_confidence=round(confidence, 4),
            days_since_last=days_since,
            recommended_interval_days=recommended_interval,
            details={
                "base_drift": self._base_drift,
                "base_interval": self._base_interval,
                "turnover_estimate": round(turnover, 4),
                "regime_adjusted": True,
            },
        )

        self._history.append(decision)
        if len(self._history) > 500:
            self._history = self._history[-500:]

        return decision

    def get_history(self) -> list[RebalanceDecision]:
        return list(self._history)

    def get_stats(self) -> dict[str, Any]:
        if not self._history:
            return {"total_evaluations": 0}
        verdict_counts: dict[str, int] = {}
        for d in self._history:
            verdict_counts[d.verdict.value] = verdict_counts.get(d.verdict.value, 0) + 1
        rebalance_count = verdict_counts.get(RebalanceVerdict.REBALANCE_NOW.value, 0)
        return {
            "total_evaluations": len(self._history),
            "verdict_distribution": verdict_counts,
            "rebalance_rate": round(rebalance_count / len(self._history), 4),
            "avg_drift_at_rebalance": round(
                float(np.mean([d.current_drift for d in self._history
                               if d.verdict == RebalanceVerdict.REBALANCE_NOW])) if rebalance_count > 0 else 0.0,
                6,
            ),
        }

    def _compute_max_drift(
        self,
        current: dict[str, float],
        target: dict[str, float],
    ) -> float:
        all_keys = set(current.keys()) | set(target.keys())
        if not all_keys:
            return 0.0
        drifts = [abs(current.get(k, 0.0) - target.get(k, 0.0)) for k in all_keys]
        return max(drifts)

    def _adjust_drift_threshold(self, regime: str) -> float:
        if regime in (MarketRegime.VOLATILE.value, MarketRegime.BEAR_DISTRIBUTION.value):
            return self._base_drift * self._volatile_mult
        if regime in (MarketRegime.BULL_BASE.value, MarketRegime.BULL_BREAKOUT.value):
            return self._base_drift * self._calm_mult
        return self._base_drift

    def _adjust_interval(self, regime: str) -> int:
        if regime in (MarketRegime.VOLATILE.value, MarketRegime.BEAR_DISTRIBUTION.value):
            interval = int(self._base_interval * 0.6)
        elif regime in (MarketRegime.BULL_BREAKOUT.value,):
            interval = int(self._base_interval * 0.8)
        elif regime in (MarketRegime.BULL_BASE.value,):
            interval = int(self._base_interval * 1.2)
        else:
            interval = self._base_interval
        return max(self._min_interval, min(interval, self._max_interval))

    @staticmethod
    def _estimate_turnover(
        current: dict[str, float],
        target: dict[str, float],
    ) -> float:
        all_keys = set(current.keys()) | set(target.keys())
        if not all_keys:
            return 0.0
        return sum(abs(current.get(k, 0.0) - target.get(k, 0.0)) for k in all_keys) / 2
