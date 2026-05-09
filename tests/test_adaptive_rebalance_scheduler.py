import numpy as np
import pandas as pd
import pytest

from core.adaptive_rebalance_scheduler import (
    AdaptiveRebalanceScheduler,
    RebalanceDecision,
    RebalanceVerdict,
)


def _make_market_df(n: int = 100, trend: float = 0.001, vol: float = 0.02) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100.0 * np.cumprod(1 + rng.normal(trend, vol, n))
    return pd.DataFrame({
        "date": dates,
        "open": close * (1 + rng.normal(0, 0.005, n)),
        "high": close * (1 + np.abs(rng.normal(0, 0.01, n))),
        "low": close * (1 - np.abs(rng.normal(0, 0.01, n))),
        "close": close,
        "volume": rng.integers(100000, 1000000, n),
    })


class TestRebalanceVerdict:

    def test_enum_values(self):
        assert RebalanceVerdict.REBALANCE_NOW.value == "rebalance_now"
        assert RebalanceVerdict.SKIP_LOW_DRIFT.value == "skip_low_drift"


class TestAdaptiveRebalanceScheduler:

    def test_rebalance_when_drift_exceeds(self):
        scheduler = AdaptiveRebalanceScheduler(base_drift_threshold=0.05)
        current = {"A": 0.5, "B": 0.5}
        target = {"A": 0.7, "B": 0.3}
        decision = scheduler.evaluate(current, target, day_index=100)
        assert decision.verdict == RebalanceVerdict.REBALANCE_NOW
        assert decision.current_drift >= 0.05

    def test_skip_when_drift_low(self):
        scheduler = AdaptiveRebalanceScheduler(base_drift_threshold=0.05)
        current = {"A": 0.5, "B": 0.5}
        target = {"A": 0.52, "B": 0.48}
        decision = scheduler.evaluate(current, target, day_index=100)
        assert decision.verdict in (RebalanceVerdict.SKIP_LOW_DRIFT, RebalanceVerdict.DEFER_CALM_MARKET)

    def test_cooldown_prevents_rebalance(self):
        scheduler = AdaptiveRebalanceScheduler(base_drift_threshold=0.01, cooldown_days=5)
        current = {"A": 0.3, "B": 0.7}
        target = {"A": 0.7, "B": 0.3}
        scheduler.evaluate(current, target, day_index=100)
        decision = scheduler.evaluate(current, target, day_index=102)
        assert decision.verdict == RebalanceVerdict.SKIP_RECENT_REBALANCE

    def test_with_market_data(self):
        scheduler = AdaptiveRebalanceScheduler(base_drift_threshold=0.05)
        df = _make_market_df()
        current = {"A": 0.3, "B": 0.7}
        target = {"A": 0.7, "B": 0.3}
        decision = scheduler.evaluate(current, target, day_index=100, market_df=df)
        assert isinstance(decision, RebalanceDecision)
        assert decision.regime != ""

    def test_turnover_cap(self):
        scheduler = AdaptiveRebalanceScheduler(
            base_drift_threshold=0.01,
            turnover_cap=0.05,
        )
        current = {"A": 0.1, "B": 0.9}
        target = {"A": 0.9, "B": 0.1}
        decision = scheduler.evaluate(current, target, day_index=100)
        assert decision.verdict != RebalanceVerdict.REBALANCE_NOW

    def test_regime_adjusts_threshold(self):
        scheduler = AdaptiveRebalanceScheduler(
            base_drift_threshold=0.05,
            volatile_drift_multiplier=1.5,
            calm_drift_multiplier=0.7,
        )
        df = _make_market_df(trend=0.005, vol=0.005)
        current = {"A": 0.5, "B": 0.5}
        target = {"A": 0.56, "B": 0.44}
        decision = scheduler.evaluate(current, target, day_index=100, market_df=df)
        assert decision.drift_threshold != 0.05, "Threshold should be adjusted by regime"

    def test_history_tracked(self):
        scheduler = AdaptiveRebalanceScheduler()
        current = {"A": 0.5, "B": 0.5}
        target = {"A": 0.5, "B": 0.5}
        for i in range(5):
            scheduler.evaluate(current, target, day_index=100 + i)
        assert len(scheduler.get_history()) == 5

    def test_stats(self):
        scheduler = AdaptiveRebalanceScheduler(base_drift_threshold=0.01)
        current = {"A": 0.3, "B": 0.7}
        target = {"A": 0.7, "B": 0.3}
        scheduler.evaluate(current, target, day_index=100)
        scheduler.evaluate(current, target, day_index=200)
        stats = scheduler.get_stats()
        assert stats["total_evaluations"] == 2
        assert "rebalance_rate" in stats

    def test_empty_weights(self):
        scheduler = AdaptiveRebalanceScheduler()
        decision = scheduler.evaluate({}, {}, day_index=100)
        assert decision.current_drift == 0.0

    def test_recommended_interval_varies(self):
        scheduler = AdaptiveRebalanceScheduler(base_interval_days=30)
        df_volatile = _make_market_df(trend=-0.002, vol=0.05)
        current = {"A": 0.5, "B": 0.5}
        target = {"A": 0.55, "B": 0.45}
        decision = scheduler.evaluate(current, target, day_index=100, market_df=df_volatile)
        assert decision.recommended_interval_days > 0
