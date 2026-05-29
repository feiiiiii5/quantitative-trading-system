__all__ = [
    "FactorDecayDetector",
    "DecayVerdict",
    "DecayReport",
]

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class DecayVerdict(StrEnum):
    STABLE = "stable"
    SLOW_DECAY = "slow_decay"
    MODERATE_DECAY = "moderate_decay"
    SEVERE_DECAY = "severe_decay"
    DEAD = "dead"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class DecayReport:
    factor_name: str
    verdict: DecayVerdict
    ic_trend: float
    half_life: float | None
    recent_ic: float
    historical_ic: float
    decay_rate: float
    weight_adjustment: float
    details: dict[str, Any] = field(default_factory=dict)


class FactorDecayDetector:
    def __init__(
        self,
        lookback: int = 120,
        min_observations: int = 30,
        slow_decay_threshold: float = -0.005,
        moderate_decay_threshold: float = -0.015,
        severe_decay_threshold: float = -0.03,
        dead_ic_threshold: float = 0.005,
        half_life_warning: float = 30.0,
    ):
        self._lookback = lookback
        self._min_obs = min_observations
        self._slow_thresh = slow_decay_threshold
        self._moderate_thresh = moderate_decay_threshold
        self._severe_thresh = severe_decay_threshold
        self._dead_thresh = dead_ic_threshold
        self._half_life_warning = half_life_warning

        self._ic_history: dict[str, list[float]] = {}

    def update(self, factor_name: str, ic_value: float) -> None:
        if factor_name not in self._ic_history:
            self._ic_history[factor_name] = []
        self._ic_history[factor_name].append(ic_value)
        if len(self._ic_history[factor_name]) > self._lookback:
            self._ic_history[factor_name] = self._ic_history[factor_name][-self._lookback:]

    def detect(self, factor_name: str) -> DecayReport:
        history = self._ic_history.get(factor_name, [])
        if len(history) < self._min_obs:
            return DecayReport(
                factor_name=factor_name,
                verdict=DecayVerdict.INSUFFICIENT_DATA,
                ic_trend=0.0,
                half_life=None,
                recent_ic=0.0,
                historical_ic=0.0,
                decay_rate=0.0,
                weight_adjustment=1.0,
            )

        ic_arr = np.array(history)
        n = len(ic_arr)

        ic_trend = self._compute_trend(ic_arr)
        half_life = self._estimate_half_life(ic_arr)

        recent_n = max(n // 4, 10)
        recent_ic = float(np.mean(ic_arr[-recent_n:]))
        historical_ic = float(np.mean(ic_arr))

        decay_rate = ic_trend

        verdict = self._classify_verdict(recent_ic, ic_trend, half_life)
        weight_adj = self._compute_weight_adjustment(verdict, recent_ic, historical_ic)

        return DecayReport(
            factor_name=factor_name,
            verdict=verdict,
            ic_trend=round(ic_trend, 6),
            half_life=round(half_life, 1) if half_life is not None else None,
            recent_ic=round(recent_ic, 6),
            historical_ic=round(historical_ic, 6),
            decay_rate=round(decay_rate, 6),
            weight_adjustment=round(weight_adj, 4),
            details={
                "n_observations": n,
                "ic_std": round(float(np.std(ic_arr)), 6),
                "ic_min": round(float(np.min(ic_arr)), 6),
                "ic_max": round(float(np.max(ic_arr)), 6),
            },
        )

    def detect_all(self) -> list[DecayReport]:
        return [self.detect(name) for name in self._ic_history]

    def get_decaying_factors(self, min_verdict: DecayVerdict = DecayVerdict.SLOW_DECAY) -> list[DecayReport]:
        severity = list(DecayVerdict)
        min_idx = severity.index(min_verdict)
        reports = self.detect_all()
        return [r for r in reports if r.verdict in severity[min_idx:] and r.verdict != DecayVerdict.INSUFFICIENT_DATA]

    def _compute_trend(self, ic_arr: np.ndarray) -> float:
        n = len(ic_arr)
        if n < 10:
            return 0.0
        x = np.arange(n, dtype=float)
        x_mean = x.mean()
        y_mean = ic_arr.mean()
        numerator = np.sum((x - x_mean) * (ic_arr - y_mean))
        denominator = np.sum((x - x_mean) ** 2)
        if denominator < 1e-12:
            return 0.0
        slope = numerator / denominator
        return float(slope)

    def _estimate_half_life(self, ic_arr: np.ndarray) -> float | None:
        n = len(ic_arr)
        if n < 20:
            return None

        def halflife_from_ar1(series: np.ndarray) -> float | None:
            if len(series) < 10:
                return None
            y = series[1:]
            x = series[:-1]
            x_mean = x.mean()
            y_mean = y.mean()
            denom = np.sum((x - x_mean) ** 2)
            if denom < 1e-12:
                return None
            phi = np.sum((x - x_mean) * (y - y_mean)) / denom
            if phi <= 0 or phi >= 1:
                return None
            return -np.log(2) / np.log(phi)

        hl = halflife_from_ar1(ic_arr)
        if hl is not None and np.isfinite(hl) and hl > 0:
            return float(hl)
        return None

    def _classify_verdict(
        self,
        recent_ic: float,
        ic_trend: float,
        half_life: float | None,
    ) -> DecayVerdict:
        if abs(recent_ic) < self._dead_thresh and ic_trend < self._severe_thresh:
            return DecayVerdict.DEAD

        if ic_trend < self._severe_thresh:
            return DecayVerdict.SEVERE_DECAY

        if ic_trend < self._moderate_thresh:
            return DecayVerdict.MODERATE_DECAY

        if ic_trend < self._slow_thresh:
            if half_life is not None and half_life < self._half_life_warning:
                return DecayVerdict.MODERATE_DECAY
            return DecayVerdict.SLOW_DECAY

        return DecayVerdict.STABLE

    def _compute_weight_adjustment(
        self,
        verdict: DecayVerdict,
        recent_ic: float,
        historical_ic: float,
    ) -> float:
        adjustments = {
            DecayVerdict.STABLE: 1.0,
            DecayVerdict.SLOW_DECAY: 0.8,
            DecayVerdict.MODERATE_DECAY: 0.5,
            DecayVerdict.SEVERE_DECAY: 0.2,
            DecayVerdict.DEAD: 0.05,
            DecayVerdict.INSUFFICIENT_DATA: 1.0,
        }
        base_adj = adjustments.get(verdict, 1.0)

        if abs(historical_ic) > 1e-12:
            ic_ratio = abs(recent_ic) / abs(historical_ic)
            ic_ratio = np.clip(ic_ratio, 0.0, 1.0)
            base_adj *= (0.5 + 0.5 * ic_ratio)

        return float(base_adj)

    def summary(self) -> dict[str, Any]:
        reports = self.detect_all()
        verdict_counts: dict[str, int] = {}
        for r in reports:
            verdict_counts[r.verdict.value] = verdict_counts.get(r.verdict.value, 0) + 1
        return {
            "n_factors": len(self._ic_history),
            "verdict_distribution": verdict_counts,
            "decaying_factors": [r.factor_name for r in reports if r.verdict in (
                DecayVerdict.SLOW_DECAY, DecayVerdict.MODERATE_DECAY,
                DecayVerdict.SEVERE_DECAY, DecayVerdict.DEAD,
            )],
        }
