__all__ = [
    "FactorLifecycleOrchestrator",
    "FactorLifecycleState",
    "OrchestrationResult",
]

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from core.adaptive_factor_combiner import AdaptiveFactorCombiner, CombinationMethod
from core.adaptive_rebalance_scheduler import AdaptiveRebalanceScheduler, RebalanceVerdict
from core.black_litterman_ic import BlackLittermanIC, BLView
from core.factor_decay_detector import DecayVerdict, FactorDecayDetector
from core.factor_validity import FactorValidityMonitor

logger = logging.getLogger(__name__)


class FactorLifecycleState(str, Enum):
    INCUBATION = "incubation"
    ACTIVE = "active"
    WATCH = "watch"
    DEGRADED = "degraded"
    RETIRED = "retired"


@dataclass
class FactorState:
    name: str
    lifecycle: FactorLifecycleState = FactorLifecycleState.INCUBATION
    current_ic: float = 0.0
    ic_ir: float = 0.0
    decay_verdict: DecayVerdict = DecayVerdict.INSUFFICIENT_DATA
    weight: float = 0.0
    bl_view_delta: float = 0.0
    observations: int = 0
    days_active: int = 0


@dataclass
class OrchestrationResult:
    factor_states: dict[str, FactorState]
    composite_signal: float
    target_weights: dict[str, float]
    rebalance_decision: str
    bl_posterior_shift: bool
    lifecycle_transitions: list[dict[str, str]]
    summary: dict[str, Any] = field(default_factory=dict)


class FactorLifecycleOrchestrator:
    def __init__(
        self,
        factor_names: list[str],
        ic_threshold: float = 0.03,
        ic_ir_threshold: float = 0.5,
        incubation_min_observations: int = 20,
        retirement_ic_threshold: float = 0.005,
        watch_decay_verdicts: set[DecayVerdict] | None = None,
        bl_tau: float = 0.05,
        rebalance_base_drift: float = 0.05,
    ):
        self._factor_names = factor_names
        self._ic_threshold = ic_threshold
        self._ic_ir_threshold = ic_ir_threshold
        self._incubation_min = incubation_min_observations
        self._retirement_ic = retirement_ic_threshold
        self._watch_verdicts = watch_decay_verdicts or {
            DecayVerdict.SLOW_DECAY, DecayVerdict.MODERATE_DECAY,
        }

        self._factor_monitor = FactorValidityMonitor(lookback=60, ic_threshold=ic_threshold)
        self._decay_detector = FactorDecayDetector(lookback=120, min_observations=incubation_min_observations)
        self._combiner = AdaptiveFactorCombiner(
            factor_names=factor_names,
            method=CombinationMethod.IC_WEIGHTED,
        )
        self._bl = BlackLittermanIC(tau=bl_tau)
        self._scheduler = AdaptiveRebalanceScheduler(base_drift_threshold=rebalance_base_drift)

        self._states: dict[str, FactorState] = {
            f: FactorState(name=f) for f in factor_names
        }
        self._current_weights: dict[str, float] = {f: 1.0 / len(factor_names) for f in factor_names}
        self._day_counter: int = 0
        self._transition_log: list[dict[str, str]] = []

    def update(
        self,
        factor_scores: dict[str, float],
        actual_returns: dict[str, float] | None = None,
        market_df: Any = None,
    ) -> OrchestrationResult:
        self._day_counter += 1

        for name in self._factor_names:
            score = factor_scores.get(name, 0.0)
            ret = actual_returns.get(name) if actual_returns else None

            if ret is not None:
                self._factor_monitor.update(name, score, ret)
                ic_val = self._factor_monitor.get_ic_mean(name)
                self._decay_detector.update(name, ic_val)
                self._states[name].current_ic = ic_val
                self._states[name].ic_ir = self._factor_monitor.get_ic_ir(name)
                self._states[name].observations += 1

            self._states[name].days_active += 1

        self._update_lifecycle_states()

        signal = self._combiner.update(factor_scores)

        bl_shift = False
        if actual_returns:
            bl_result = self._compute_bl_weights(factor_scores, actual_returns)
            if bl_result is not None:
                for name in self._factor_names:
                    idx = self._factor_names.index(name)
                    self._states[name].bl_view_delta = bl_result.view_deltas.get(idx, 0.0)
                bl_shift = any(abs(d) > 0.001 for d in bl_result.view_deltas.values())

        rebalance_verdict = "not_evaluated"
        if market_df is not None:
            decision = self._scheduler.evaluate(
                self._current_weights,
                self._get_target_weights(),
                self._day_counter,
                market_df,
            )
            rebalance_verdict = decision.verdict.value
            if decision.verdict == RebalanceVerdict.REBALANCE_NOW:
                self._current_weights = self._get_target_weights()

        self._current_weights = self._get_target_weights()

        return OrchestrationResult(
            factor_states=dict(self._states),
            composite_signal=signal.weighted_score,
            target_weights=dict(self._current_weights),
            rebalance_decision=rebalance_verdict,
            bl_posterior_shift=bl_shift,
            lifecycle_transitions=list(self._transition_log[-10:]),
            summary=self._build_summary(),
        )

    def get_factor_state(self, name: str) -> FactorState | None:
        return self._states.get(name)

    def get_active_factors(self) -> list[str]:
        return [f for f, s in self._states.items() if s.lifecycle == FactorLifecycleState.ACTIVE]

    def get_retired_factors(self) -> list[str]:
        return [f for f, s in self._states.items() if s.lifecycle == FactorLifecycleState.RETIRED]

    def _update_lifecycle_states(self) -> None:
        for name in self._factor_names:
            state = self._states[name]
            old_lifecycle = state.lifecycle
            new_lifecycle = self._determine_lifecycle(state)

            if new_lifecycle != old_lifecycle:
                state.lifecycle = new_lifecycle
                self._transition_log.append({
                    "factor": name,
                    "from": old_lifecycle.value,
                    "to": new_lifecycle.value,
                    "day": str(self._day_counter),
                })
                logger.info(
                    "Factor %s lifecycle transition: %s → %s (IC=%.4f, obs=%d)",
                    name, old_lifecycle.value, new_lifecycle.value,
                    state.current_ic, state.observations,
                )

    def _determine_lifecycle(self, state: FactorState) -> FactorLifecycleState:
        if state.observations < self._incubation_min:
            return FactorLifecycleState.INCUBATION

        if state.current_ic < self._retirement_ic and state.observations > self._incubation_min * 2:
            return FactorLifecycleState.RETIRED

        decay_report = self._decay_detector.detect(state.name)
        state.decay_verdict = decay_report.verdict

        if decay_report.verdict in (DecayVerdict.SEVERE_DECAY, DecayVerdict.DEAD):
            return FactorLifecycleState.DEGRADED

        if decay_report.verdict in self._watch_verdicts:
            return FactorLifecycleState.WATCH

        if abs(state.current_ic) >= self._ic_threshold and abs(state.ic_ir) >= self._ic_ir_threshold:
            return FactorLifecycleState.ACTIVE

        if abs(state.current_ic) >= self._ic_threshold * 0.5:
            return FactorLifecycleState.WATCH

        return FactorLifecycleState.INCUBATION

    def _get_target_weights(self) -> dict[str, float]:
        weights = {}
        total_active = 0.0
        for name in self._factor_names:
            state = self._states[name]
            if state.lifecycle == FactorLifecycleState.RETIRED:
                weights[name] = 0.0
                continue
            decay_report = self._decay_detector.detect(name)
            base_w = self._combiner.weights.get(name, 1.0 / len(self._factor_names))
            adjusted_w = base_w * decay_report.weight_adjustment
            if state.lifecycle == FactorLifecycleState.INCUBATION:
                adjusted_w *= 0.5
            elif state.lifecycle == FactorLifecycleState.DEGRADED:
                adjusted_w *= 0.2
            weights[name] = adjusted_w
            total_active += adjusted_w

        if total_active > 1e-12:
            weights = {k: round(v / total_active, 4) for k, v in weights.items()}
        else:
            n = len(self._factor_names)
            weights = {f: round(1.0 / n, 4) for f in self._factor_names}
        return weights

    def _compute_bl_weights(
        self,
        factor_scores: dict[str, float],
        actual_returns: dict[str, float],
    ) -> Any:
        n = len(self._factor_names)
        if n < 2:
            return None

        returns_arr = np.array([actual_returns.get(f, 0.0) for f in self._factor_names])
        if np.std(returns_arr) < 1e-12:
            return None

        cov = np.diag(np.maximum(returns_arr ** 2, 1e-8))
        if n > 1:
            for i in range(n):
                for j in range(i + 1, n):
                    corr = 0.3 if i != j else 1.0
                    cov[i, j] = corr * np.sqrt(cov[i, i] * cov[j, j])
                    cov[j, i] = cov[i, j]

        market_w = np.array([self._current_weights.get(f, 1.0 / n) for f in self._factor_names])

        views: list[BLView] = []
        for i, name in enumerate(self._factor_names):
            ic = self._factor_monitor.get_ic_mean(name)
            if abs(ic) > 0.01:
                views.append(BLView(
                    asset_index=i,
                    expected_return=factor_scores.get(name, 0.0) * ic * 10,
                    confidence=min(abs(ic) * 20, 5.0),
                ))

        if not views:
            return None

        return self._bl.optimize(cov, market_w, views)

    def _build_summary(self) -> dict[str, Any]:
        lifecycle_counts: dict[str, int] = {}
        for state in self._states.values():
            key = state.lifecycle.value
            lifecycle_counts[key] = lifecycle_counts.get(key, 0) + 1
        return {
            "day": self._day_counter,
            "lifecycle_distribution": lifecycle_counts,
            "active_factors": len(self.get_active_factors()),
            "retired_factors": len(self.get_retired_factors()),
            "current_weights": {k: round(v, 4) for k, v in self._current_weights.items()},
        }
