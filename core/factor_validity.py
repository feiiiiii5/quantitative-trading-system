__all__ = [
    "FactorValidityMonitor",
    "ModelValidityMonitor",
    "CrossSectionalMomentum",
    "adf_test",
    "half_life",
]

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class FactorValidityMonitor:
    def __init__(self, lookback: int = 60, ic_threshold: float = 0.03):
        self._lookback = lookback
        self._ic_threshold = ic_threshold
        self._ic_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=lookback))
        self._rolling_ic: dict[str, deque] = defaultdict(lambda: deque(maxlen=lookback))

    def update(self, strategy_name: str, predicted_score: float, actual_return: float) -> None:
        self._ic_history[strategy_name].append((predicted_score, actual_return))
        history = self._ic_history[strategy_name]
        if len(history) >= 20:
            scores, returns = zip(*history, strict=True)
            scores_arr = np.array(scores, dtype=float)
            returns_arr = np.array(returns, dtype=float)
            valid = np.isfinite(scores_arr) & np.isfinite(returns_arr)
            if valid.sum() >= 10:
                s = scores_arr[valid]
                r = returns_arr[valid]
                if np.std(s) < 1e-12 or np.std(r) < 1e-12:
                    self._rolling_ic[strategy_name].append(0.0)
                    return
                corr_matrix = np.corrcoef(s, r)
                ic = float(corr_matrix[0, 1]) if np.isfinite(corr_matrix[0, 1]) else 0.0
                self._rolling_ic[strategy_name].append(ic)

    def is_valid(self, strategy_name: str) -> bool:
        history = self._ic_history[strategy_name]
        if len(history) < 20:
            return True
        ic = self._current_ic(strategy_name)
        return abs(ic) > self._ic_threshold

    def get_weight_adjustment(self, strategy_name: str) -> float:
        history = self._ic_history[strategy_name]
        if len(history) < 20:
            return 1.0
        ic = self._current_ic(strategy_name)
        return max(0.1, min(2.0, abs(ic) / self._ic_threshold))

    def _current_ic(self, strategy_name: str) -> float:
        rolling = self._rolling_ic.get(strategy_name)
        if not rolling or len(rolling) == 0:
            return 0.0
        return float(np.mean(list(rolling)[-20:]))

    def get_ic_series(self, strategy_name: str) -> list[float]:
        rolling = self._rolling_ic.get(strategy_name, deque())
        return list(rolling)

    def get_ic_mean(self, strategy_name: str) -> float:
        return self._current_ic(strategy_name)

    def get_ic_ir(self, strategy_name: str) -> float:
        rolling = self._rolling_ic.get(strategy_name, deque())
        if len(rolling) < 5:
            return 0.0
        ic_arr = np.array(list(rolling), dtype=float)
        mean = np.mean(ic_arr)
        std = np.std(ic_arr)
        if std < 1e-12:
            return 0.0
        return float(mean / std)

    def summary(self) -> dict[str, dict[str, Any]]:
        result = {}
        for name in self._ic_history:
            result[name] = {
                "current_ic": round(self._current_ic(name), 4),
                "ic_ir": round(self.get_ic_ir(name), 4),
                "is_valid": self.is_valid(name),
                "weight_adjustment": round(self.get_weight_adjustment(name), 4),
                "sample_count": len(self._ic_history[name]),
            }
        return result

    def reset(self, strategy_name: str | None = None) -> None:
        if strategy_name:
            self._ic_history.pop(strategy_name, None)
            self._rolling_ic.pop(strategy_name, None)
        else:
            self._ic_history.clear()
            self._rolling_ic.clear()


@dataclass
class _RankICRecord:
    date: str
    rank_ic: float
    n_stocks: int


class ModelValidityMonitor:
    def __init__(
        self,
        lookback: int = 60,
        warning_threshold: float = 0.02,
        critical_threshold: float = 0.0,
        min_samples: int = 20,
    ):
        self._lookback = lookback
        self._warning_threshold = warning_threshold
        self._critical_threshold = critical_threshold
        self._min_samples = min_samples
        self._rank_ic_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=lookback))

    def update_rank_ic(
        self,
        model_name: str,
        date: str,
        predicted_ranks: np.ndarray | pd.Series,
        actual_returns: np.ndarray | pd.Series,
    ) -> float:
        pred = np.asarray(predicted_ranks, dtype=float)
        actual = np.asarray(actual_returns, dtype=float)
        valid = np.isfinite(pred) & np.isfinite(actual)
        if valid.sum() < self._min_samples:
            return 0.0
        pred_valid = pred[valid]
        actual_valid = actual[valid]
        pred_ranks = pd.Series(pred_valid).rank().values
        actual_ranks = pd.Series(actual_valid).rank().values
        corr = np.corrcoef(pred_ranks, actual_ranks)[0, 1]
        rank_ic = float(corr) if np.isfinite(corr) else 0.0
        self._rank_ic_history[model_name].append(
            _RankICRecord(date=date, rank_ic=rank_ic, n_stocks=int(valid.sum()))
        )
        return rank_ic

    def get_status(self, model_name: str) -> dict[str, Any]:
        history = self._rank_ic_history.get(model_name, deque())
        if len(history) < 5:
            return {
                "status": "insufficient_data",
                "mean_rank_ic": 0.0,
                "ic_ir": 0.0,
                "decay_rate": 0.0,
                "sample_count": len(history),
            }

        ic_values = np.array([r.rank_ic for r in history])
        mean_ic = float(np.mean(ic_values))
        std_ic = float(np.std(ic_values))
        ic_ir = mean_ic / std_ic if std_ic > 1e-12 else 0.0

        decay_rate = 0.0
        if len(ic_values) >= 10:
            half = len(ic_values) // 2
            first_half = np.mean(ic_values[:half])
            second_half = np.mean(ic_values[half:])
            decay_rate = second_half - first_half

        if mean_ic < self._critical_threshold:
            status = "critical"
        elif mean_ic < self._warning_threshold:
            status = "warning"
        elif decay_rate < -0.02:
            status = "decaying"
        else:
            status = "healthy"

        return {
            "status": status,
            "mean_rank_ic": round(mean_ic, 4),
            "ic_ir": round(ic_ir, 4),
            "decay_rate": round(decay_rate, 4),
            "recent_ic": round(float(ic_values[-1]), 4) if len(ic_values) > 0 else 0.0,
            "sample_count": len(history),
        }

    def should_retrain(self, model_name: str) -> bool:
        status = self.get_status(model_name)
        return status["status"] in ("critical", "decaying")

    def get_position_scale(self, model_name: str) -> float:
        status = self.get_status(model_name)
        if status["status"] == "critical":
            return 0.1
        if status["status"] == "warning":
            return 0.5
        if status["status"] == "decaying":
            return 0.7
        return 1.0

    def summary(self) -> dict[str, dict[str, Any]]:
        return {name: self.get_status(name) for name in self._rank_ic_history}


class CrossSectionalMomentum:
    def __init__(
        self,
        lookback: int = 20,
        n_long: int = 5,
        n_short: int = 0,
        rebalance_freq: int = 5,
    ):
        self._lookback = lookback
        self._n_long = n_long
        self._n_short = n_short
        self._rebalance_freq = rebalance_freq
        self._last_rebalance_bar = -999
        self._current_ranks: dict[str, float] = {}
        self._momentum_scores: dict[str, float] = {}

    def compute_scores(
        self,
        price_dict: dict[str, np.ndarray],
        current_bar: int,
    ) -> dict[str, float]:
        if current_bar - self._last_rebalance_bar < self._rebalance_freq and self._momentum_scores:
            return self._momentum_scores

        scores: dict[str, float] = {}
        for symbol, prices in price_dict.items():
            if len(prices) < self._lookback + 1:
                continue
            recent = prices[-self._lookback:]
            if recent[0] > 1e-9:
                momentum = (recent[-1] - recent[0]) / recent[0]
                vol = float(np.std(np.diff(recent) / recent[:-1], where=recent[:-1] > 0))
                risk_adj_momentum = momentum / vol if vol > 1e-12 else 0.0
                scores[symbol] = risk_adj_momentum

        if not scores:
            return self._momentum_scores

        sorted_symbols = sorted(scores.keys(), key=lambda s: scores[s], reverse=True)
        n = len(sorted_symbols)

        self._current_ranks = {}
        for rank, sym in enumerate(sorted_symbols):
            self._current_ranks[sym] = rank + 1

        self._momentum_scores = {}
        for i, sym in enumerate(sorted_symbols):
            if i < self._n_long:
                self._momentum_scores[sym] = 1.0
            elif i >= n - self._n_short and self._n_short > 0:
                self._momentum_scores[sym] = -1.0
            else:
                self._momentum_scores[sym] = 0.0

        self._last_rebalance_bar = current_bar
        return self._momentum_scores

    def get_long_symbols(self) -> list[str]:
        return [s for s, v in self._momentum_scores.items() if v > 0]

    def get_short_symbols(self) -> list[str]:
        return [s for s, v in self._momentum_scores.items() if v < 0]

    def get_ranks(self) -> dict[str, int]:
        return dict(self._current_ranks)

    @property
    def lookback(self) -> int:
        return self._lookback

    @property
    def n_long(self) -> int:
        return self._n_long

    @property
    def n_short(self) -> int:
        return self._n_short


def adf_test(series: np.ndarray | pd.Series, significance: float = 0.05) -> dict[str, Any]:
    try:
        from statsmodels.tsa.stattools import adfuller
    except ImportError:
        return _simplified_adf(series, significance)

    arr = np.asarray(series, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 20:
        return {"is_stationary": False, "p_value": 1.0, "test_statistic": 0.0, "method": "insufficient_data"}

    try:
        result = adfuller(arr, autolag="AIC")
        p_value = float(result[1])
        test_stat = float(result[0])
        critical_values = {k: float(v) for k, v in result[4].items()}
        return {
            "is_stationary": p_value < significance,
            "p_value": round(p_value, 6),
            "test_statistic": round(test_stat, 4),
            "critical_values": critical_values,
            "method": "augmented_dickey_fuller",
        }
    except Exception as e:
        logger.debug("ADF test failed: %s", e)
        return _simplified_adf(series, significance)


def _simplified_adf(series: np.ndarray | pd.Series, significance: float = 0.05) -> dict[str, Any]:
    arr = np.asarray(series, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 20:
        return {"is_stationary": False, "p_value": 1.0, "test_statistic": 0.0, "method": "insufficient_data"}

    diff = np.diff(arr)
    y = diff[1:]
    x = diff[:-1]
    x = np.column_stack([x, arr[1:-1]])
    x = np.column_stack([np.ones(len(y)), x])

    try:
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
        residuals = y - x @ beta
        n = len(y)
        k = x.shape[1]
        sigma2 = np.sum(residuals ** 2) / (n - k)
        xtx_inv = np.linalg.inv(x.T @ x)
        se = np.sqrt(np.diag(xtx_inv) * sigma2)
        t_stat = float(beta[2] / se[2]) if abs(se[2]) > 1e-12 else 0.0

        approx_p = 0.05 if t_stat < -2.86 else (0.01 if t_stat < -3.43 else 0.10)
        return {
            "is_stationary": t_stat < -2.86,
            "p_value": approx_p,
            "test_statistic": round(t_stat, 4),
            "method": "simplified_adf",
        }
    except Exception:
        return {"is_stationary": False, "p_value": 1.0, "test_statistic": 0.0, "method": "fallback"}


def half_life(series: np.ndarray | pd.Series) -> float:
    arr = np.asarray(series, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 10:
        return float("inf")

    lagged = arr[:-1]
    diff = arr[1:] - lagged

    valid = np.isfinite(lagged) & np.isfinite(diff)
    if valid.sum() < 10:
        return float("inf")

    x = lagged[valid].reshape(-1, 1)
    x = np.column_stack([np.ones(len(x)), x])
    y = diff[valid]

    try:
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
        lam = float(beta[1])
        if lam >= 0 or abs(lam) < 1e-12:
            return float("inf")
        return round(-np.log(2) / lam, 2)
    except Exception:
        return float("inf")
