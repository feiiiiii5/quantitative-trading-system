import numpy as np
import pandas as pd
import pytest

from core.regime_weight_tracker import (
    RegimeWeightTracker,
    RegimeWeightSnapshot,
    compute_regime_weight_series,
)
from core.regime_detector import MarketRegime


def _make_trend_df(n: int = 200, trend: float = 0.05) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    close = np.cumsum(rng.normal(trend, 1.0, n)) + 100
    return pd.DataFrame({
        "date": dates,
        "open": close - 0.3,
        "high": close + 0.8,
        "low": close - 0.8,
        "close": close,
        "volume": rng.integers(1000, 10000, n),
    })


def _make_volatile_df(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(123)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    close = np.cumsum(rng.normal(0, 3.0, n)) + 100
    return pd.DataFrame({
        "date": dates,
        "open": close - 0.5,
        "high": close + 1.5,
        "low": close - 1.5,
        "close": close,
        "volume": rng.integers(1000, 10000, n),
    })


STRATEGIES = ["momentum_strategy", "mean_reversion_strategy", "trend_following"]


class TestRegimeWeightSnapshot:

    def test_dataclass_fields(self):
        snap = RegimeWeightSnapshot(
            date="2023-06-01",
            regime="bull_breakout",
            regime_confidence=0.8,
            strategy_weights={"s1": 0.6, "s2": 0.4},
        )
        assert snap.date == "2023-06-01"
        assert snap.regime == "bull_breakout"
        assert snap.strategy_weights["s1"] == 0.6


class TestRegimeWeightTracker:

    def test_update_returns_snapshot(self):
        tracker = RegimeWeightTracker(strategy_names=STRATEGIES)
        df = _make_trend_df(200)
        snap = tracker.update(df)
        assert isinstance(snap, RegimeWeightSnapshot)
        assert snap.regime in [r.value for r in MarketRegime]
        assert len(snap.strategy_weights) == 3

    def test_weights_sum_to_one(self):
        tracker = RegimeWeightTracker(strategy_names=STRATEGIES)
        df = _make_trend_df(200)
        snap = tracker.update(df)
        total = sum(snap.strategy_weights.values())
        assert abs(total - 1.0) < 0.05

    def test_history_accumulates(self):
        tracker = RegimeWeightTracker(strategy_names=STRATEGIES)
        df = _make_trend_df(200)
        tracker.update(df)
        tracker.update(df)
        tracker.update(df)
        assert len(tracker.get_history()) == 3

    def test_max_history_respected(self):
        tracker = RegimeWeightTracker(strategy_names=STRATEGIES, max_history=5)
        df = _make_trend_df(200)
        for _ in range(10):
            tracker.update(df)
        assert len(tracker.get_history()) <= 5

    def test_regime_transitions(self):
        tracker = RegimeWeightTracker(strategy_names=STRATEGIES)
        trend_df = _make_trend_df(200)
        vol_df = _make_volatile_df(200)
        tracker.update(trend_df)
        tracker.update(vol_df)
        transitions = tracker.get_regime_transitions()
        assert isinstance(transitions, list)

    def test_weight_series_dataframe(self):
        tracker = RegimeWeightTracker(strategy_names=STRATEGIES)
        df = _make_trend_df(200)
        for _ in range(5):
            tracker.update(df)
        series_df = tracker.get_weight_series()
        assert isinstance(series_df, pd.DataFrame)
        assert len(series_df) == 5
        assert "date" in series_df.columns
        assert "regime" in series_df.columns
        assert "weight_momentum_strategy" in series_df.columns

    def test_regime_distribution(self):
        tracker = RegimeWeightTracker(strategy_names=STRATEGIES)
        df = _make_trend_df(200)
        for _ in range(10):
            tracker.update(df)
        dist = tracker.get_regime_distribution()
        assert isinstance(dist, dict)
        total_prob = sum(dist.values())
        assert abs(total_prob - 1.0) < 0.05

    def test_average_weights_by_regime(self):
        tracker = RegimeWeightTracker(strategy_names=STRATEGIES)
        df = _make_trend_df(200)
        for _ in range(10):
            tracker.update(df)
        avg = tracker.get_average_weights_by_regime()
        assert isinstance(avg, dict)
        for regime_weights in avg.values():
            for s in STRATEGIES:
                assert s in regime_weights

    def test_custom_weights(self):
        tracker = RegimeWeightTracker(strategy_names=STRATEGIES)
        df = _make_trend_df(200)
        custom = {"momentum_strategy": 0.5, "mean_reversion_strategy": 0.3, "trend_following": 0.2}
        snap = tracker.update(df, custom_weights=custom)
        assert abs(snap.strategy_weights["momentum_strategy"] - 0.5) < 0.01

    def test_strategy_scores_adjust_weights(self):
        tracker = RegimeWeightTracker(strategy_names=STRATEGIES)
        df = _make_trend_df(200)
        scores = {"momentum_strategy": 0.9, "mean_reversion_strategy": 0.1, "trend_following": 0.5}
        snap_with_scores = tracker.update(df, strategy_scores=scores)
        assert isinstance(snap_with_scores, RegimeWeightSnapshot)

    def test_current_snapshot(self):
        tracker = RegimeWeightTracker(strategy_names=STRATEGIES)
        assert tracker.current_snapshot is None
        df = _make_trend_df(200)
        tracker.update(df)
        assert tracker.current_snapshot is not None

    def test_set_regime_weights(self):
        tracker = RegimeWeightTracker(strategy_names=STRATEGIES)
        new_weights = {"momentum_strategy": 0.7, "mean_reversion_strategy": 0.2, "trend_following": 0.1}
        tracker.set_regime_weights("bull_breakout", new_weights)
        assert tracker._regime_weights["bull_breakout"] == new_weights

    def test_empty_history_methods(self):
        tracker = RegimeWeightTracker(strategy_names=STRATEGIES)
        assert tracker.get_regime_transitions() == []
        assert tracker.get_weight_series().empty
        assert tracker.get_regime_distribution() == {}
        assert tracker.get_average_weights_by_regime() == {}


class TestComputeRegimeWeightSeries:

    def test_insufficient_data(self):
        result = compute_regime_weight_series(
            pd.DataFrame(), strategy_names=STRATEGIES, window=20,
        )
        assert result.empty

    def test_sufficient_data(self):
        df = _make_trend_df(200)
        result = compute_regime_weight_series(df, strategy_names=STRATEGIES, window=20)
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
        assert "regime" in result.columns
