__all__ = [
    "AdaptiveFactorCombiner",
    "FactorSignal",
    "CombinationMethod",
]

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class CombinationMethod(StrEnum):
    IC_WEIGHTED = "ic_weighted"
    EQUAL = "equal"
    IC_IR_WEIGHTED = "ic_ir_weighted"
    SHRINKAGE = "shrinkage"


@dataclass
class FactorSignal:
    factor_name: str
    raw_score: float
    rank_score: float = 0.0
    ic: float = 0.0
    ic_ir: float = 0.0
    weight: float = 0.0
    weighted_score: float = 0.0


class AdaptiveFactorCombiner:
    def __init__(
        self,
        factor_names: list[str],
        method: CombinationMethod = CombinationMethod.IC_WEIGHTED,
        ic_lookback: int = 60,
        ic_threshold: float = 0.02,
        shrinkage_target: float = 0.5,
        min_ic_for_weight: float = 0.01,
        max_weight: float = 0.5,
        reweight_interval: int = 5,
    ):
        self._factor_names = factor_names
        self._method = method
        self._ic_lookback = ic_lookback
        self._ic_threshold = ic_threshold
        self._shrinkage_target = shrinkage_target
        self._min_ic_for_weight = min_ic_for_weight
        self._max_weight = max_weight
        self._reweight_interval = reweight_interval

        self._rolling_ic: dict[str, list[float]] = {f: [] for f in factor_names}
        self._rolling_returns: list[float] = []
        self._score_history: dict[str, list[float]] = {f: [] for f in factor_names}
        self._current_weights: dict[str, float] = {f: 1.0 / len(factor_names) for f in factor_names}
        self._update_count: int = 0
        self._last_scores: dict[str, float] = {}

    def update(
        self,
        factor_scores: dict[str, float],
        actual_return: float | None = None,
    ) -> FactorSignal:
        self._update_count += 1
        self._last_scores = dict(factor_scores)

        if actual_return is not None:
            self._rolling_returns.append(actual_return)
            if len(self._rolling_returns) > self._ic_lookback:
                self._rolling_returns = self._rolling_returns[-self._ic_lookback:]

            for name in self._factor_names:
                score = factor_scores.get(name, 0.0)
                self._score_history[name].append(score)
                if len(self._score_history[name]) > self._ic_lookback:
                    self._score_history[name] = self._score_history[name][-self._ic_lookback:]

                n_pairs = min(len(self._score_history[name]), len(self._rolling_returns))
                if n_pairs >= 10:
                    scores_arr = np.array(self._score_history[name][-n_pairs:])
                    returns_arr = np.array(self._rolling_returns[-n_pairs:])
                    if np.std(scores_arr) > 1e-12 and np.std(returns_arr) > 1e-12:
                        ic = float(np.corrcoef(scores_arr, returns_arr)[0, 1])
                        ic = ic if np.isfinite(ic) else 0.0
                    else:
                        ic = 0.0
                else:
                    ic = 0.0
                self._rolling_ic[name].append(ic)
                if len(self._rolling_ic[name]) > self._ic_lookback:
                    self._rolling_ic[name] = self._rolling_ic[name][-self._ic_lookback:]

        if self._update_count % self._reweight_interval == 0:
            self._reweight()

        composite = 0.0
        for name in self._factor_names:
            w = self._current_weights.get(name, 0.0)
            s = factor_scores.get(name, 0.0)
            composite += w * s

        primary_name = self._factor_names[0] if self._factor_names else ""
        return FactorSignal(
            factor_name=primary_name,
            raw_score=factor_scores.get(primary_name, 0.0),
            rank_score=0.0,
            ic=self._get_mean_ic(primary_name),
            ic_ir=self._get_ic_ir(primary_name),
            weight=self._current_weights.get(primary_name, 0.0),
            weighted_score=composite,
        )

    def get_composite_signal(self, factor_scores: dict[str, float]) -> float:
        composite = 0.0
        for name in self._factor_names:
            w = self._current_weights.get(name, 0.0)
            s = factor_scores.get(name, 0.0)
            composite += w * s
        return composite

    def get_factor_signals(self, factor_scores: dict[str, float]) -> list[FactorSignal]:
        score_values = np.array([factor_scores.get(n, 0.0) for n in self._factor_names])
        ranked = self._rank_normalize(score_values) if len(score_values) > 0 else np.array([])
        signals = []
        for i, name in enumerate(self._factor_names):
            ic = self._get_mean_ic(name)
            ic_ir = self._get_ic_ir(name)
            w = self._current_weights.get(name, 0.0)
            s = factor_scores.get(name, 0.0)
            signals.append(FactorSignal(
                factor_name=name,
                raw_score=s,
                rank_score=float(ranked[i]) if i < len(ranked) else 0.0,
                ic=ic,
                ic_ir=ic_ir,
                weight=w,
                weighted_score=w * s,
            ))
        return signals

    def _reweight(self) -> None:
        if self._method == CombinationMethod.EQUAL:
            n = len(self._factor_names)
            self._current_weights = dict.fromkeys(self._factor_names, 1.0 / n)
            return

        ics = {}
        ic_irs = {}
        for name in self._factor_names:
            ics[name] = self._get_mean_ic(name)
            ic_irs[name] = self._get_ic_ir(name)

        if self._method == CombinationMethod.IC_WEIGHTED:
            raw_weights = {}
            for name in self._factor_names:
                abs_ic = abs(ics.get(name, 0.0))
                raw_weights[name] = max(abs_ic, self._min_ic_for_weight)

        elif self._method == CombinationMethod.IC_IR_WEIGHTED:
            raw_weights = {}
            for name in self._factor_names:
                raw_weights[name] = max(abs(ic_irs.get(name, 0.0)), self._min_ic_for_weight)

        elif self._method == CombinationMethod.SHRINKAGE:
            raw_weights = {}
            n = len(self._factor_names)
            equal_w = 1.0 / n
            for name in self._factor_names:
                ic_w = abs(ics.get(name, 0.0))
                raw_weights[name] = self._shrinkage_target * equal_w + (1 - self._shrinkage_target) * ic_w
        else:
            n = len(self._factor_names)
            raw_weights = dict.fromkeys(self._factor_names, 1.0 / n)

        total = sum(raw_weights.values())
        if total > 1e-12:
            self._current_weights = {}
            for name in self._factor_names:
                w = raw_weights[name] / total
                self._current_weights[name] = min(w, self._max_weight)
            total = sum(self._current_weights.values())
            if total > 1e-12:
                self._current_weights = {f: w / total for f, w in self._current_weights.items()}

    def _get_mean_ic(self, name: str) -> float:
        ic_list = self._rolling_ic.get(name, [])
        if not ic_list:
            return 0.0
        return float(np.mean(ic_list))

    def _get_ic_ir(self, name: str) -> float:
        ic_list = self._rolling_ic.get(name, [])
        if len(ic_list) < 5:
            return 0.0
        mean = float(np.mean(ic_list))
        std = float(np.std(ic_list))
        if std < 1e-12:
            return 0.0
        return mean / std

    @staticmethod
    def _rank_normalize(scores: np.ndarray) -> np.ndarray:
        n = len(scores)
        if n == 0:
            return np.array([])
        order = np.argsort(scores)
        ranks = np.empty(n)
        ranks[order] = np.arange(1, n + 1)
        return (ranks - (n + 1) / 2) / (n / 2)

    @property
    def weights(self) -> dict[str, float]:
        return dict(self._current_weights)

    @property
    def ic_history(self) -> dict[str, list[float]]:
        return {k: list(v) for k, v in self._rolling_ic.items()}

    def summary(self) -> dict[str, Any]:
        return {
            "method": self._method.value,
            "weights": dict(self._current_weights),
            "update_count": self._update_count,
            "mean_ics": {f: round(self._get_mean_ic(f), 4) for f in self._factor_names},
            "ic_irs": {f: round(self._get_ic_ir(f), 4) for f in self._factor_names},
        }
