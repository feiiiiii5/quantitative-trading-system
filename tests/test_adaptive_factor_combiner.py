import numpy as np
import pytest

from core.adaptive_factor_combiner import (
    AdaptiveFactorCombiner,
    FactorSignal,
    CombinationMethod,
)


FACTORS = ["momentum", "value", "quality", "volatility"]


class TestFactorSignal:

    def test_dataclass_fields(self):
        sig = FactorSignal(
            factor_name="momentum",
            raw_score=0.8,
            rank_score=0.6,
            ic=0.05,
            ic_ir=1.2,
            weight=0.3,
            weighted_score=0.24,
        )
        assert sig.factor_name == "momentum"
        assert sig.raw_score == 0.8
        assert sig.weighted_score == 0.24


class TestAdaptiveFactorCombiner:

    def test_equal_weight_init(self):
        combiner = AdaptiveFactorCombiner(
            factor_names=FACTORS,
            method=CombinationMethod.EQUAL,
        )
        weights = combiner.weights
        assert len(weights) == 4
        for w in weights.values():
            assert abs(w - 0.25) < 0.01

    def test_update_returns_signal(self):
        combiner = AdaptiveFactorCombiner(factor_names=FACTORS)
        scores = {"momentum": 0.8, "value": 0.3, "quality": 0.5, "volatility": -0.2}
        signal = combiner.update(scores, actual_return=0.01)
        assert isinstance(signal, FactorSignal)

    def test_composite_signal(self):
        combiner = AdaptiveFactorCombiner(factor_names=FACTORS)
        scores = {"momentum": 0.8, "value": 0.3, "quality": 0.5, "volatility": -0.2}
        composite = combiner.get_composite_signal(scores)
        assert isinstance(composite, float)
        assert np.isfinite(composite)

    def test_factor_signals_list(self):
        combiner = AdaptiveFactorCombiner(factor_names=FACTORS)
        scores = {"momentum": 0.8, "value": 0.3, "quality": 0.5, "volatility": -0.2}
        signals = combiner.get_factor_signals(scores)
        assert len(signals) == 4
        assert all(isinstance(s, FactorSignal) for s in signals)

    def test_ic_weighted_reweighting(self):
        combiner = AdaptiveFactorCombiner(
            factor_names=FACTORS,
            method=CombinationMethod.IC_WEIGHTED,
            reweight_interval=1,
        )
        rng = np.random.default_rng(42)
        for _ in range(20):
            scores = {f: rng.normal(0, 1) for f in FACTORS}
            combiner.update(scores, actual_return=rng.normal(0.001, 0.02))
        weights = combiner.weights
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.05

    def test_ic_ir_weighted(self):
        combiner = AdaptiveFactorCombiner(
            factor_names=FACTORS,
            method=CombinationMethod.IC_IR_WEIGHTED,
            reweight_interval=1,
        )
        rng = np.random.default_rng(42)
        for _ in range(20):
            scores = {f: rng.normal(0, 1) for f in FACTORS}
            combiner.update(scores, actual_return=rng.normal(0.001, 0.02))
        weights = combiner.weights
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.05

    def test_shrinkage_method(self):
        combiner = AdaptiveFactorCombiner(
            factor_names=FACTORS,
            method=CombinationMethod.SHRINKAGE,
            shrinkage_target=0.5,
            reweight_interval=1,
        )
        rng = np.random.default_rng(42)
        for _ in range(20):
            scores = {f: rng.normal(0, 1) for f in FACTORS}
            combiner.update(scores, actual_return=rng.normal(0.001, 0.02))
        weights = combiner.weights
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.05

    def test_max_weight_cap(self):
        combiner = AdaptiveFactorCombiner(
            factor_names=["a", "b"],
            method=CombinationMethod.IC_WEIGHTED,
            max_weight=0.6,
            reweight_interval=1,
        )
        np.random.default_rng(42)
        for _ in range(20):
            scores = {"a": 1.0, "b": 0.0}
            combiner.update(scores, actual_return=0.01)
        for w in combiner.weights.values():
            assert w <= 0.65

    def test_summary(self):
        combiner = AdaptiveFactorCombiner(factor_names=FACTORS)
        scores = {"momentum": 0.8, "value": 0.3, "quality": 0.5, "volatility": -0.2}
        combiner.update(scores, actual_return=0.01)
        s = combiner.summary()
        assert "method" in s
        assert "weights" in s
        assert "mean_ics" in s
        assert "ic_irs" in s

    def test_ic_history(self):
        combiner = AdaptiveFactorCombiner(factor_names=FACTORS)
        scores = {"momentum": 0.8, "value": 0.3, "quality": 0.5, "volatility": -0.2}
        combiner.update(scores, actual_return=0.01)
        history = combiner.ic_history
        assert isinstance(history, dict)
        assert "momentum" in history

    def test_no_actual_return(self):
        combiner = AdaptiveFactorCombiner(factor_names=FACTORS)
        scores = {"momentum": 0.8, "value": 0.3, "quality": 0.5, "volatility": -0.2}
        signal = combiner.update(scores)
        assert isinstance(signal, FactorSignal)

    def test_single_factor(self):
        combiner = AdaptiveFactorCombiner(factor_names=["alpha"])
        scores = {"alpha": 0.5}
        composite = combiner.get_composite_signal(scores)
        assert abs(composite - 0.5) < 0.01

    def test_ic_nonzero_with_correlated_data(self):
        combiner = AdaptiveFactorCombiner(
            factor_names=["momentum", "value"],
            method=CombinationMethod.IC_WEIGHTED,
            reweight_interval=1,
        )
        rng = np.random.default_rng(123)
        base_returns = rng.normal(0, 0.02, 60)
        for ret in base_returns:
            momentum_score = ret * 3.0 + rng.normal(0, 0.01)
            value_score = rng.normal(0, 1)
            scores = {"momentum": momentum_score, "value": value_score}
            combiner.update(scores, actual_return=ret)
        momentum_ic = combiner._get_mean_ic("momentum")
        value_ic = combiner._get_mean_ic("value")
        assert abs(momentum_ic) > 0.01, f"momentum IC should be non-zero with correlated data, got {momentum_ic}"
        assert abs(momentum_ic) > abs(value_ic), "momentum IC should exceed value IC"

    def test_score_history_stored_per_factor(self):
        combiner = AdaptiveFactorCombiner(
            factor_names=["a", "b"],
            reweight_interval=10,
        )
        for i in range(15):
            combiner.update({"a": float(i), "b": float(i * 2)}, actual_return=float(i) * 0.01)
        assert len(combiner._score_history["a"]) == 15
        assert len(combiner._score_history["b"]) == 15
        assert combiner._score_history["a"][-1] == 14.0
        assert combiner._score_history["b"][-1] == 28.0
