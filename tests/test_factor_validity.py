import pytest
import numpy as np

from core.factor_validity import (
    FactorValidityMonitor,
    ModelValidityMonitor,
    CrossSectionalMomentum,
    adf_test,
    half_life,
)


class TestFactorValidityMonitor:

    def test_insufficient_data_is_valid(self):
        monitor = FactorValidityMonitor()
        assert monitor.is_valid("test_strategy")

    def test_update_and_validity(self):
        monitor = FactorValidityMonitor(lookback=60, ic_threshold=0.03)
        np.random.seed(42)
        for _ in range(30):
            monitor.update("test", np.random.randn(), np.random.randn() * 0.02)
        assert isinstance(monitor.is_valid("test"), bool)

    def test_weight_adjustment_range(self):
        monitor = FactorValidityMonitor()
        adj = monitor.get_weight_adjustment("nonexistent")
        assert adj == 1.0

    def test_ic_ir_insufficient_data(self):
        monitor = FactorValidityMonitor()
        assert monitor.get_ic_ir("nonexistent") == 0.0

    def test_summary(self):
        monitor = FactorValidityMonitor()
        monitor.update("test", 0.5, 0.01)
        summary = monitor.summary()
        assert "test" in summary

    def test_reset(self):
        monitor = FactorValidityMonitor()
        monitor.update("test", 0.5, 0.01)
        monitor.reset("test")
        assert monitor.get_ic_mean("test") == 0.0


class TestModelValidityMonitor:

    def test_insufficient_data_status(self):
        mvm = ModelValidityMonitor()
        status = mvm.get_status("nonexistent")
        assert status["status"] == "insufficient_data"

    def test_healthy_model(self):
        mvm = ModelValidityMonitor()
        np.random.seed(42)
        for i in range(30):
            pred = np.random.randn(50)
            actual = pred * 0.5 + np.random.randn(50) * 0.1
            mvm.update_rank_ic("model", f"2024-01-{i+1:02d}", pred, actual)
        status = mvm.get_status("model")
        assert status["status"] in ("healthy", "warning", "critical", "decaying")

    def test_position_scale(self):
        mvm = ModelValidityMonitor()
        scale = mvm.get_position_scale("nonexistent")
        assert scale == 1.0


class TestCrossSectionalMomentum:

    def test_compute_scores(self):
        csm = CrossSectionalMomentum(lookback=20, n_long=3, n_short=1, rebalance_freq=5)
        np.random.seed(42)
        price_dict = {f"s{i}": np.cumsum(np.random.randn(100) * 0.5) + 100 for i in range(10)}
        scores = csm.compute_scores(price_dict, 50)
        assert len(scores) > 0

    def test_long_symbols(self):
        csm = CrossSectionalMomentum(lookback=20, n_long=3, n_short=0, rebalance_freq=1)
        np.random.seed(42)
        price_dict = {f"s{i}": np.cumsum(np.random.randn(100) * 0.5) + 100 for i in range(10)}
        csm.compute_scores(price_dict, 50)
        long = csm.get_long_symbols()
        assert len(long) == 3


class TestADFTest:

    def test_stationary_series(self):
        series = np.sin(np.linspace(0, 20, 200)) * 5 + 100
        result = adf_test(series)
        assert "is_stationary" in result
        assert "p_value" in result

    def test_insufficient_data(self):
        result = adf_test(np.array([1.0, 2.0]))
        assert result["is_stationary"] is False


class TestHalfLife:

    def test_mean_reverting_series(self):
        np.random.seed(42)
        series = np.cumsum(np.random.randn(200) * 0.1 - 0.01 * np.arange(200) * 0.1) + 100
        hl = half_life(series)
        assert hl > 0

    def test_insufficient_data(self):
        hl = half_life(np.array([1.0, 2.0]))
        assert hl == float("inf")
