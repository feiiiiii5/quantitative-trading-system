import numpy as np
import pytest

from core.factor_lifecycle_orchestrator import (
    FactorLifecycleOrchestrator,
    FactorLifecycleState,
    FactorState,
    OrchestrationResult,
)
from core.factor_decay_detector import DecayVerdict


FACTORS = ["momentum", "value", "quality", "volatility"]


class TestFactorState:

    def test_default_state(self):
        state = FactorState(name="test")
        assert state.lifecycle == FactorLifecycleState.INCUBATION
        assert state.current_ic == 0.0
        assert state.observations == 0


class TestFactorLifecycleOrchestrator:

    def test_initial_state_incubation(self):
        orch = FactorLifecycleOrchestrator(factor_names=FACTORS)
        for name in FACTORS:
            state = orch.get_factor_state(name)
            assert state is not None
            assert state.lifecycle == FactorLifecycleState.INCUBATION

    def test_update_returns_orchestration_result(self):
        orch = FactorLifecycleOrchestrator(factor_names=FACTORS)
        scores = {"momentum": 0.8, "value": 0.3, "quality": 0.5, "volatility": -0.2}
        result = orch.update(scores)
        assert isinstance(result, OrchestrationResult)
        assert isinstance(result.composite_signal, float)
        assert isinstance(result.target_weights, dict)

    def test_weights_sum_to_one(self):
        orch = FactorLifecycleOrchestrator(factor_names=FACTORS)
        scores = {"momentum": 0.8, "value": 0.3, "quality": 0.5, "volatility": -0.2}
        result = orch.update(scores)
        total = sum(result.target_weights.values())
        assert abs(total - 1.0) < 0.05

    def test_lifecycle_transitions_to_active(self):
        orch = FactorLifecycleOrchestrator(
            factor_names=["alpha"],
            ic_threshold=0.02,
            ic_ir_threshold=0.3,
            incubation_min_observations=10,
        )
        rng = np.random.default_rng(42)
        for _ in range(25):
            score = rng.normal(0.5, 0.1)
            ret = score * 0.1 + rng.normal(0, 0.01)
            orch.update({"alpha": score}, actual_returns={"alpha": ret})
        state = orch.get_factor_state("alpha")
        assert state.lifecycle in (
            FactorLifecycleState.ACTIVE,
            FactorLifecycleState.WATCH,
            FactorLifecycleState.INCUBATION,
        )

    def test_retirement_for_dead_factor(self):
        orch = FactorLifecycleOrchestrator(
            factor_names=["dead"],
            ic_threshold=0.03,
            retirement_ic_threshold=0.01,
            incubation_min_observations=10,
        )
        for _ in range(50):
            orch.update({"dead": 0.0}, actual_returns={"dead": 0.0})
        state = orch.get_factor_state("dead")
        assert state.lifecycle in (
            FactorLifecycleState.RETIRED,
            FactorLifecycleState.DEGRADED,
            FactorLifecycleState.INCUBATION,
        )

    def test_get_active_factors(self):
        orch = FactorLifecycleOrchestrator(factor_names=FACTORS)
        active = orch.get_active_factors()
        assert isinstance(active, list)

    def test_get_retired_factors(self):
        orch = FactorLifecycleOrchestrator(factor_names=FACTORS)
        retired = orch.get_retired_factors()
        assert isinstance(retired, list)
        assert len(retired) == 0

    def test_lifecycle_transitions_logged(self):
        orch = FactorLifecycleOrchestrator(
            factor_names=["test"],
            ic_threshold=0.02,
            incubation_min_observations=5,
        )
        rng = np.random.default_rng(42)
        for _ in range(20):
            score = rng.normal(0.5, 0.1)
            ret = score * 0.15 + rng.normal(0, 0.01)
            orch.update({"test": score}, actual_returns={"test": ret})
        result = orch.update({"test": 0.5}, actual_returns={"test": 0.05})
        assert isinstance(result.lifecycle_transitions, list)

    def test_bl_posterior_shift_detected(self):
        orch = FactorLifecycleOrchestrator(
            factor_names=["a", "b"],
            ic_threshold=0.01,
            incubation_min_observations=5,
        )
        rng = np.random.default_rng(42)
        for _ in range(30):
            scores = {"a": rng.normal(0.8, 0.1), "b": rng.normal(0.2, 0.1)}
            returns = {"a": rng.normal(0.01, 0.02), "b": rng.normal(0.005, 0.02)}
            orch.update(scores, actual_returns=returns)
        result = orch.update(
            {"a": 0.9, "b": 0.1},
            actual_returns={"a": 0.02, "b": -0.01},
        )
        assert isinstance(result.bl_posterior_shift, bool)

    def test_summary_structure(self):
        orch = FactorLifecycleOrchestrator(factor_names=FACTORS)
        scores = {"momentum": 0.8, "value": 0.3, "quality": 0.5, "volatility": -0.2}
        result = orch.update(scores)
        s = result.summary
        assert "day" in s
        assert "lifecycle_distribution" in s
        assert "active_factors" in s
        assert "current_weights" in s

    def test_no_actual_returns(self):
        orch = FactorLifecycleOrchestrator(factor_names=FACTORS)
        scores = {"momentum": 0.8, "value": 0.3, "quality": 0.5, "volatility": -0.2}
        result = orch.update(scores)
        assert isinstance(result, OrchestrationResult)
        assert not result.bl_posterior_shift

    def test_single_factor(self):
        orch = FactorLifecycleOrchestrator(factor_names=["solo"])
        result = orch.update({"solo": 0.5})
        assert abs(result.target_weights["solo"] - 1.0) < 0.01
