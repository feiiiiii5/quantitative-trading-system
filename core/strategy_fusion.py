import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.alpha_screener import AlphaResult

logger = logging.getLogger(__name__)


@dataclass
class FusionConfig:
    method: str = "ic_vol"
    min_ic: float = 0.02
    max_strategies: int = 10
    rebalance_frequency: int = 20
    smoothing_window: int = 5


@dataclass
class FusionResult:
    combined_signal: pd.Series
    strategy_weights: Dict[str, float]
    n_strategies: int
    method: str
    contribution: Dict[str, float]


def ic_vol_weight(alpha_results: Dict[str, AlphaResult]) -> Dict[str, float]:
    if not alpha_results:
        return {}
    ics = {name: abs(r.ic) for name, r in alpha_results.items()}
    vols = {}
    for name, r in alpha_results.items():
        std = r.values.std()
        vols[name] = std if std > 1e-10 else 1e-10

    raw_weights = {}
    for name in alpha_results:
        raw_weights[name] = ics[name] / vols[name]

    total = sum(raw_weights.values())
    if total < 1e-12:
        n = len(alpha_results)
        return {name: 1.0 / n for name in alpha_results}

    return {name: round(w / total, 6) for name, w in raw_weights.items()}


def equal_weight(alpha_results: Dict[str, AlphaResult]) -> Dict[str, float]:
    if not alpha_results:
        return {}
    n = len(alpha_results)
    return {name: round(1.0 / n, 6) for name in alpha_results}


def ic_weight(alpha_results: Dict[str, AlphaResult]) -> Dict[str, float]:
    if not alpha_results:
        return {}
    abs_ics = {name: abs(r.ic) for name, r in alpha_results.items()}
    total = sum(abs_ics.values())
    if total < 1e-12:
        return equal_weight(alpha_results)
    return {name: round(w / total, 6) for name, w in abs_ics.items()}


def sharpe_weight(alpha_results: Dict[str, AlphaResult]) -> Dict[str, float]:
    if not alpha_results:
        return {}
    sharpes = {}
    for name, r in alpha_results.items():
        mean_val = r.values.mean()
        std_val = r.values.std()
        sharpes[name] = abs(mean_val / std_val) if std_val > 1e-10 else 0.0
    total = sum(sharpes.values())
    if total < 1e-12:
        return equal_weight(alpha_results)
    return {name: round(w / total, 6) for name, w in sharpes.items()}


def rank_weight(alpha_results: Dict[str, AlphaResult]) -> Dict[str, float]:
    if not alpha_results:
        return {}
    ics = {name: r.ic for name, r in alpha_results.items()}
    sorted_names = sorted(ics.keys(), key=lambda x: abs(ics[x]), reverse=True)
    n = len(sorted_names)
    raw = {}
    for i, name in enumerate(sorted_names):
        raw[name] = (n - i) / (n * (n + 1) / 2)
    total = sum(raw.values())
    if total < 1e-12:
        return equal_weight(alpha_results)
    return {name: round(w / total, 6) for name, w in raw.items()}


class StrategyFusion:
    def __init__(self, config: FusionConfig = None):
        self._config = config or FusionConfig()
        self._weight_history: List[Dict[str, float]] = []
        self._weight_history_max = 120

    def fuse(
        self,
        alpha_results: Dict[str, AlphaResult],
        method: str = None,
    ) -> FusionResult:
        method = method or self._config.method

        if not alpha_results:
            return FusionResult(
                combined_signal=pd.Series(dtype=float),
                strategy_weights={},
                n_strategies=0,
                method=method,
                contribution={},
            )

        filtered = {
            name: r for name, r in alpha_results.items()
            if abs(r.ic) >= self._config.min_ic
        }

        if not filtered:
            filtered = dict(list(alpha_results.items())[:self._config.max_strategies])

        if len(filtered) > self._config.max_strategies:
            sorted_alphas = sorted(filtered.items(), key=lambda x: abs(x[1].ic_ir), reverse=True)
            filtered = dict(sorted_alphas[:self._config.max_strategies])

        if method == "ic_vol":
            weights = ic_vol_weight(filtered)
        elif method == "equal":
            weights = equal_weight(filtered)
        elif method == "ic":
            weights = ic_weight(filtered)
        elif method == "sharpe":
            weights = sharpe_weight(filtered)
        elif method == "rank":
            weights = rank_weight(filtered)
        else:
            weights = ic_vol_weight(filtered)

        self._weight_history.append(weights)
        if len(self._weight_history) > self._weight_history_max:
            self._weight_history = self._weight_history[-self._weight_history_max:]

        combined = pd.Series(0.0, index=next(iter(filtered.values())).values.index)
        contribution = {}
        for name, weight in weights.items():
            if name in filtered:
                signal = filtered[name].values
                valid = signal.notna() & combined.notna()
                combined[valid] += weight * signal[valid]
                contribution[name] = round(float((weight * signal).abs().mean()), 6)

        if self._config.smoothing_window > 1:
            combined = combined.rolling(self._config.smoothing_window, min_periods=1).mean()

        return FusionResult(
            combined_signal=combined,
            strategy_weights=weights,
            n_strategies=len(filtered),
            method=method,
            contribution=contribution,
        )

    def get_fusion_report(self, result: FusionResult) -> Dict:
        return {
            "method": result.method,
            "n_strategies": result.n_strategies,
            "weights": result.strategy_weights,
            "contribution": result.contribution,
            "signal_stats": {
                "mean": round(float(result.combined_signal.mean()), 6) if len(result.combined_signal) > 0 else 0.0,
                "std": round(float(result.combined_signal.std()), 6) if len(result.combined_signal) > 0 else 0.0,
                "min": round(float(result.combined_signal.min()), 6) if len(result.combined_signal) > 0 else 0.0,
                "max": round(float(result.combined_signal.max()), 6) if len(result.combined_signal) > 0 else 0.0,
            },
        }

    def get_weight_stability(self) -> Dict[str, float]:
        if len(self._weight_history) < 2:
            return {}
        all_names = set()
        for w in self._weight_history:
            all_names.update(w.keys())

        stability = {}
        for name in all_names:
            values = [w.get(name, 0.0) for w in self._weight_history]
            if len(values) >= 2:
                std = float(np.std(values))
                mean = float(np.mean(values))
                stability[name] = round(1.0 - std / max(mean, 1e-10), 4)
        return stability
