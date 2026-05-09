__all__ = [
    "RegimeWeightTracker",
    "RegimeWeightSnapshot",
    "compute_regime_weight_series",
]

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from core.regime_detector import MarketRegime, MarketRegimeDetector

logger = logging.getLogger(__name__)


@dataclass
class RegimeWeightSnapshot:
    date: str
    regime: str
    regime_confidence: float
    strategy_weights: dict[str, float]
    strategy_scores: dict[str, float] = field(default_factory=dict)
    indicators: dict[str, float] = field(default_factory=dict)


class RegimeWeightTracker:
    def __init__(
        self,
        strategy_names: list[str],
        trend_window: int = 20,
        vol_window: int = 20,
        lookback: int = 120,
        max_history: int = 500,
    ):
        self._strategy_names = strategy_names
        self._detector = MarketRegimeDetector(
            trend_window=trend_window,
            vol_window=vol_window,
            lookback=lookback,
        )
        self._max_history = max_history
        self._history: list[RegimeWeightSnapshot] = []
        self._regime_weights: dict[str, dict[str, float]] = {
            MarketRegime.BULL_BREAKOUT.value: self._init_weights(bias="momentum"),
            MarketRegime.BULL_BASE.value: self._init_weights(bias="trend"),
            MarketRegime.DISTRIBUTED_HIGH.value: self._init_weights(bias="balanced"),
            MarketRegime.BEAR_RALLY.value: self._init_weights(bias="mean_reversion"),
            MarketRegime.BEAR_DISTRIBUTION.value: self._init_weights(bias="defensive"),
            MarketRegime.VOLATILE.value: self._init_weights(bias="mean_reversion"),
            MarketRegime.UNKNOWN.value: self._init_weights(bias="balanced"),
        }

    def _init_weights(self, bias: str = "balanced") -> dict[str, float]:
        n = len(self._strategy_names)
        if n == 0:
            return {}
        equal = 1.0 / n
        weights = {s: equal for s in self._strategy_names}

        if bias == "momentum":
            momentum_names = [s for s in self._strategy_names if any(k in s.lower() for k in ("momentum", "trend", "breakout", "supertrend"))]
            if momentum_names:
                boost = 0.15 / len(momentum_names)
                for s in momentum_names:
                    weights[s] += boost
                others = [s for s in self._strategy_names if s not in momentum_names]
                if others:
                    deduct = 0.15 / len(others)
                    for s in others:
                        weights[s] = max(0.01, weights[s] - deduct)

        elif bias == "trend":
            trend_names = [s for s in self._strategy_names if any(k in s.lower() for k in ("trend", "ma", "dual_ma", "supertrend"))]
            if trend_names:
                boost = 0.15 / len(trend_names)
                for s in trend_names:
                    weights[s] += boost
                others = [s for s in self._strategy_names if s not in trend_names]
                if others:
                    deduct = 0.15 / len(others)
                    for s in others:
                        weights[s] = max(0.01, weights[s] - deduct)

        elif bias == "mean_reversion":
            mr_names = [s for s in self._strategy_names if any(k in s.lower() for k in ("mean_reversion", "rsi", "bollinger", "vwap"))]
            if mr_names:
                boost = 0.15 / len(mr_names)
                for s in mr_names:
                    weights[s] += boost
                others = [s for s in self._strategy_names if s not in mr_names]
                if others:
                    deduct = 0.15 / len(others)
                    for s in others:
                        weights[s] = max(0.01, weights[s] - deduct)

        elif bias == "defensive":
            defensive_names = [s for s in self._strategy_names if any(k in s.lower() for k in ("mean_reversion", "vwap", "bollinger"))]
            if defensive_names:
                boost = 0.2 / len(defensive_names)
                for s in defensive_names:
                    weights[s] += boost
                others = [s for s in self._strategy_names if s not in defensive_names]
                if others:
                    deduct = 0.2 / len(others)
                    for s in others:
                        weights[s] = max(0.01, weights[s] - deduct)

        total = sum(weights.values())
        if total > 1e-12:
            weights = {s: round(v / total, 4) for s, v in weights.items()}
        return weights

    def update(
        self,
        df: pd.DataFrame,
        strategy_scores: dict[str, float] | None = None,
        custom_weights: dict[str, float] | None = None,
    ) -> RegimeWeightSnapshot:
        regime, context = self._detector.detect(df)

        date_str = ""
        if "date" in df.columns:
            date_str = str(df["date"].iloc[-1])[:10]

        if custom_weights:
            weights = dict(custom_weights)
        else:
            weights = dict(self._regime_weights.get(regime.value, self._init_weights("balanced")))

        if strategy_scores:
            score_adjusted = {}
            for s in self._strategy_names:
                base_w = weights.get(s, 0)
                score = strategy_scores.get(s, 0.5)
                score_adjusted[s] = base_w * (0.5 + score)
            total = sum(score_adjusted.values())
            if total > 1e-12:
                weights = {s: round(v / total, 4) for s, v in score_adjusted.items()}

        indicators = {}
        if context:
            for key in ("trend", "volatility", "momentum", "volume_profile"):
                if key in context:
                    indicators[key] = context[key]

        snapshot = RegimeWeightSnapshot(
            date=date_str,
            regime=regime.value,
            regime_confidence=context.get("confidence", 0.0) if context else 0.0,
            strategy_weights=weights,
            strategy_scores=strategy_scores or {},
            indicators=indicators,
        )

        self._history.append(snapshot)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        return snapshot

    def get_history(self) -> list[RegimeWeightSnapshot]:
        return list(self._history)

    def get_regime_transitions(self) -> list[dict[str, Any]]:
        if len(self._history) < 2:
            return []
        transitions = []
        for i in range(1, len(self._history)):
            prev = self._history[i - 1]
            curr = self._history[i]
            if prev.regime != curr.regime:
                transitions.append({
                    "from": prev.regime,
                    "to": curr.regime,
                    "date": curr.date,
                    "confidence": curr.regime_confidence,
                })
        return transitions

    def get_weight_series(self) -> pd.DataFrame:
        if not self._history:
            return pd.DataFrame()
        records = []
        for snap in self._history:
            row = {"date": snap.date, "regime": snap.regime, "confidence": snap.regime_confidence}
            for s in self._strategy_names:
                row[f"weight_{s}"] = snap.strategy_weights.get(s, 0.0)
            for k, v in snap.indicators.items():
                row[f"indicator_{k}"] = v
            records.append(row)
        return pd.DataFrame(records)

    def get_regime_distribution(self) -> dict[str, float]:
        if not self._history:
            return {}
        counts: dict[str, int] = {}
        for snap in self._history:
            counts[snap.regime] = counts.get(snap.regime, 0) + 1
        total = len(self._history)
        return {r: round(c / total, 4) for r, c in counts.items()}

    def get_average_weights_by_regime(self) -> dict[str, dict[str, float]]:
        if not self._history:
            return {}
        regime_weights: dict[str, list[dict[str, float]]] = {}
        for snap in self._history:
            if snap.regime not in regime_weights:
                regime_weights[snap.regime] = []
            regime_weights[snap.regime].append(snap.strategy_weights)

        result: dict[str, dict[str, float]] = {}
        for regime, weight_list in regime_weights.items():
            avg = {}
            for s in self._strategy_names:
                vals = [w.get(s, 0) for w in weight_list]
                avg[s] = round(float(np.mean(vals)), 4)
            result[regime] = avg
        return result

    def set_regime_weights(self, regime: str, weights: dict[str, float]) -> None:
        self._regime_weights[regime] = weights

    @property
    def current_snapshot(self) -> RegimeWeightSnapshot | None:
        return self._history[-1] if self._history else None


def compute_regime_weight_series(
    df: pd.DataFrame,
    strategy_names: list[str],
    window: int = 20,
) -> pd.DataFrame:
    if df is None or len(df) < window + 1:
        return pd.DataFrame()

    tracker = RegimeWeightTracker(strategy_names=strategy_names)
    snapshots: list[RegimeWeightSnapshot] = []

    for i in range(window, len(df)):
        window_df = df.iloc[max(0, i - window):i + 1]
        snap = tracker.update(window_df)
        snapshots.append(snap)

    if not snapshots:
        return pd.DataFrame()

    records = []
    for snap in snapshots:
        row = {"date": snap.date, "regime": snap.regime, "confidence": snap.regime_confidence}
        for s in strategy_names:
            row[f"weight_{s}"] = snap.strategy_weights.get(s, 0.0)
        records.append(row)
    return pd.DataFrame(records)
