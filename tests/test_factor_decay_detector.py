import numpy as np
import pytest

from core.factor_decay_detector import FactorDecayDetector, DecayVerdict, DecayReport


class TestDecayVerdict:

    def test_enum_values(self):
        assert DecayVerdict.STABLE.value == "stable"
        assert DecayVerdict.DEAD.value == "dead"


class TestFactorDecayDetector:

    def test_insufficient_data(self):
        detector = FactorDecayDetector(min_observations=30)
        for i in range(10):
            detector.update("alpha", 0.05)
        report = detector.detect("alpha")
        assert report.verdict == DecayVerdict.INSUFFICIENT_DATA
        assert report.weight_adjustment == 1.0

    def test_stable_factor(self):
        detector = FactorDecayDetector(min_observations=30, lookback=200)
        rng = np.random.default_rng(42)
        for _ in range(60):
            detector.update("stable_factor", rng.normal(0.05, 0.01))
        report = detector.detect("stable_factor")
        assert report.verdict == DecayVerdict.STABLE
        assert report.weight_adjustment >= 0.9

    def test_decaying_factor(self):
        detector = FactorDecayDetector(min_observations=30, lookback=200, slow_decay_threshold=-0.001)
        for i in range(80):
            ic = 0.08 - i * 0.002
            detector.update("decaying_factor", ic)
        report = detector.detect("decaying_factor")
        assert report.verdict in (
            DecayVerdict.SLOW_DECAY,
            DecayVerdict.MODERATE_DECAY,
            DecayVerdict.SEVERE_DECAY,
            DecayVerdict.DEAD,
        )
        assert report.weight_adjustment < 1.0

    def test_dead_factor(self):
        detector = FactorDecayDetector(
            min_observations=30,
            lookback=200,
            slow_decay_threshold=-0.001,
            moderate_decay_threshold=-0.003,
            severe_decay_threshold=-0.005,
        )
        for i in range(60):
            ic = max(0.08 - i * 0.003, 0.0)
            detector.update("dead_factor", ic)
        report = detector.detect("dead_factor")
        assert report.verdict in (DecayVerdict.DEAD, DecayVerdict.SEVERE_DECAY, DecayVerdict.MODERATE_DECAY)
        assert report.weight_adjustment <= 0.5

    def test_ic_trend_negative_for_decay(self):
        detector = FactorDecayDetector(min_observations=30)
        for i in range(50):
            detector.update("declining", 0.10 - i * 0.002)
        report = detector.detect("declining")
        assert report.ic_trend < 0

    def test_ic_trend_positive_for_improving(self):
        detector = FactorDecayDetector(min_observations=30)
        for i in range(50):
            detector.update("improving", 0.01 + i * 0.001)
        report = detector.detect("improving")
        assert report.ic_trend > 0

    def test_half_life_estimation(self):
        detector = FactorDecayDetector(min_observations=30)
        rng = np.random.default_rng(42)
        ic_val = 0.05
        for _ in range(80):
            ic_val = 0.7 * ic_val + rng.normal(0, 0.005)
            detector.update("meanrev", ic_val)
        report = detector.detect("meanrev")
        if report.half_life is not None:
            assert report.half_life > 0

    def test_detect_all(self):
        detector = FactorDecayDetector(min_observations=30)
        for _ in range(40):
            detector.update("a", 0.05)
            detector.update("b", 0.03)
        reports = detector.detect_all()
        assert len(reports) == 2
        assert all(isinstance(r, DecayReport) for r in reports)

    def test_get_decaying_factors(self):
        detector = FactorDecayDetector(min_observations=30, slow_decay_threshold=-0.001)
        for i in range(60):
            detector.update("stable", 0.05 + np.random.normal(0, 0.005))
            detector.update("decaying", max(0.08 - i * 0.003, 0.0))
        decaying = detector.get_decaying_factors(min_verdict=DecayVerdict.SLOW_DECAY)
        names = [r.factor_name for r in decaying]
        assert "decaying" in names

    def test_summary(self):
        detector = FactorDecayDetector(min_observations=30)
        for _ in range(40):
            detector.update("x", 0.05)
        s = detector.summary()
        assert "n_factors" in s
        assert "verdict_distribution" in s
        assert s["n_factors"] == 1

    def test_recent_vs_historical_ic(self):
        detector = FactorDecayDetector(min_observations=30)
        for i in range(60):
            if i < 30:
                detector.update("shift", 0.08)
            else:
                detector.update("shift", 0.01)
        report = detector.detect("shift")
        assert report.recent_ic < report.historical_ic

    def test_lookback_truncation(self):
        detector = FactorDecayDetector(min_observations=10, lookback=30)
        for i in range(100):
            detector.update("truncated", 0.05)
        assert len(detector._ic_history["truncated"]) <= 30
