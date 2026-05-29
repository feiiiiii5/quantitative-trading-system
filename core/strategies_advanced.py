from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from core.strategies import STRATEGY_REGISTRY, BaseStrategy, SignalType, TradeSignal

logger = logging.getLogger(__name__)

__all__ = [
    "CTATrendStrategy",
    "EnhancedStatArbStrategy",
    "AQRMomentumStrategy",
    "MLSignalStrategy",
    "MarketMakingStrategy",
    "STRATEGY_META",
]


def _ewma(series: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1)
    out = np.empty_like(series, dtype=np.float64)
    out[0] = series[0]
    for i in range(1, len(series)):
        out[i] = alpha * series[i] + (1.0 - alpha) * out[i - 1]
    return out


def _atr_array(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
    tr[0] = high[0] - low[0]
    atr = _ewma(tr, span=period)
    return atr


def _rsi_array(close: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = _ewma(gain, span=period)
    avg_loss = _ewma(loss, span=period)
    rs = np.where(avg_loss > 1e-12, avg_gain / avg_loss, 100.0)
    return 100.0 - 100.0 / (1.0 + rs)


def _macd_array(close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ema_fast = _ewma(close, span=fast)
    ema_slow = _ewma(close, span=slow)
    dif = ema_fast - ema_slow
    dea = _ewma(dif, span=signal)
    hist = (dif - dea) * 2.0
    return dif, dea, hist


def _bollinger_width(close: np.ndarray, period: int = 20) -> np.ndarray:
    rolling_mean = np.full_like(close, np.nan)
    rolling_std = np.full_like(close, np.nan)
    for i in range(period - 1, len(close)):
        window = close[i - period + 1 : i + 1]
        rolling_mean[i] = np.mean(window)
        rolling_std[i] = np.std(window, ddof=1)
    width = np.where(rolling_mean > 1e-12, 2.0 * rolling_std / rolling_mean, 0.0)
    return np.nan_to_num(width, nan=0.0)


def _cvar(returns: np.ndarray, alpha: float = 0.05) -> float:
    if len(returns) < 10:
        return 0.0
    sorted_r = np.sort(returns)
    cutoff = max(1, int(len(sorted_r) * alpha))
    return float(np.mean(sorted_r[:cutoff]))


def _ols_residual(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, float]:
    x_with_const = np.column_stack([np.ones(len(x)), x])
    beta, _, _, _ = np.linalg.lstsq(x_with_const, y, rcond=None)
    resid = y - x_with_const @ beta
    return resid, beta[0], beta[1]


def _half_life(spread: np.ndarray) -> float:
    if len(spread) < 10:
        return 20.0
    y_lag = spread[:-1]
    y_diff = np.diff(spread)
    x_with_const = np.column_stack([np.ones(len(y_lag)), y_lag])
    beta, _, _, _ = np.linalg.lstsq(x_with_const, y_diff, rcond=None)
    if abs(beta[1]) < 1e-12:
        return 20.0
    hl = -np.log(2.0) / beta[1]
    return max(1.0, min(hl, 252.0))


class CTATrendStrategy(BaseStrategy):
    _PARAM_CONSTRAINTS = {
        "fast_span": (5, 60, 16),
        "slow_span": (20, 200, 48),
        "atr_period": (5, 50, 20),
        "target_vol": (0.05, 0.40, 0.15),
    }

    def __init__(
        self,
        fast_span: int = 16,
        slow_span: int = 48,
        atr_period: int = 20,
        target_vol: float = 0.15,
    ):
        self.fast_span = fast_span
        self.slow_span = slow_span
        self.atr_period = atr_period
        self.target_vol = target_vol
        super().__init__()
        self._short = self.fast_span
        self._long = self.slow_span
        self._prev_signal: str = "hold"
        self._returns_buffer: list[float] = []

    def reset(self) -> None:
        super().reset()
        self._prev_signal = "hold"
        self._returns_buffer = []

    def on_bar(self, bar: dict, portfolio: dict) -> list[dict]:
        self._bar_index += 1
        max_window = self._long + 10
        new_row = pd.DataFrame([bar])
        if self._bar_df is None:
            self._bar_df = new_row
        else:
            self._bar_df = pd.concat([self._bar_df, new_row], ignore_index=True)
            if len(self._bar_df) > max_window:
                self._bar_df = self._bar_df.iloc[-max_window:].reset_index(drop=True)

        if len(self._bar_df) < self._long + 2:
            return []

        close = self._bar_df["close"].astype(float).values
        high = self._bar_df["high"].astype(float).values
        low = self._bar_df["low"].astype(float).values

        ewma_fast = _ewma(close, span=self.fast_span)
        ewma_slow = _ewma(close, span=self.slow_span)
        atr = _atr_array(high, low, close, period=self.atr_period)

        trend_diff = ewma_fast - ewma_slow
        norm_trend = np.where(atr > 1e-12, trend_diff / atr, 0.0)

        daily_returns = np.diff(close, prepend=close[0]) / np.where(close > 0, np.roll(close, 1), 1.0)
        daily_returns[0] = 0.0
        self._returns_buffer.extend(daily_returns[-3:].tolist())
        if len(self._returns_buffer) > 60:
            self._returns_buffer = self._returns_buffer[-60:]

        realized_vol = float(np.std(self._returns_buffer, ddof=1)) * np.sqrt(252) if len(self._returns_buffer) >= 10 else self.target_vol
        vol_scalar = self.target_vol / max(realized_vol, 0.01)

        curr_norm = norm_trend[-1]
        prev_norm = norm_trend[-2]

        signal_action = "hold"
        confidence = 0.0
        reason = ""

        if prev_norm <= 0 and curr_norm > 0:
            signal_action = "buy"
            confidence = min(abs(curr_norm) * 0.3, 0.95)
            reason = f"CTA trend bullish crossover norm={curr_norm:.2f}"
        elif prev_norm >= 0 and curr_norm < 0:
            signal_action = "sell"
            confidence = min(abs(curr_norm) * 0.3, 0.95)
            reason = f"CTA trend bearish crossover norm={curr_norm:.2f}"
        elif curr_norm > 0.5 and self._prev_signal == "buy":
            signal_action = "buy"
            confidence = min(abs(curr_norm) * 0.2, 0.7)
            reason = f"CTA trend holding long norm={curr_norm:.2f}"
        elif curr_norm < -0.5 and self._prev_signal == "sell":
            signal_action = "sell"
            confidence = min(abs(curr_norm) * 0.2, 0.7)
            reason = f"CTA trend holding short norm={curr_norm:.2f}"

        if signal_action != "hold":
            self._prev_signal = signal_action

        if signal_action == "hold":
            return []

        position_pct = round(float(np.clip(vol_scalar * 0.5, 0.05, 1.0)), 2)
        stop_dist = 2.0 * atr[-1] if atr[-1] > 0 else close[-1] * 0.02

        result = {
            "action": signal_action,
            "reason": reason,
            "confidence": round(confidence, 2),
            "position_pct": position_pct,
        }
        if signal_action == "buy":
            result["stop_loss"] = round(close[-1] - stop_dist, 2)
            result["take_profit"] = round(close[-1] + stop_dist * 2.0, 2)
        else:
            result["stop_loss"] = round(close[-1] + stop_dist, 2)
            result["take_profit"] = round(close[-1] - stop_dist * 2.0, 2)

        return [result]

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < self._long + 2:
            return TradeSignal(SignalType.HOLD)
        close = df["close"].astype(float).values
        high = df["high"].astype(float).values
        low = df["low"].astype(float).values
        ewma_fast = _ewma(close, span=self.fast_span)
        ewma_slow = _ewma(close, span=self.slow_span)
        atr = _atr_array(high, low, close, period=self.atr_period)
        trend_diff = ewma_fast - ewma_slow
        norm_trend = np.where(atr > 1e-12, trend_diff / atr, 0.0)
        curr = norm_trend[-1]
        prev = norm_trend[-2]
        if prev <= 0 and curr > 0:
            return TradeSignal(SignalType.BUY, min(abs(curr) * 0.3, 0.95), "CTA trend bullish crossover")
        if prev >= 0 and curr < 0:
            return TradeSignal(SignalType.SELL, min(abs(curr) * 0.3, 0.95), "CTA trend bearish crossover")
        return TradeSignal(SignalType.HOLD)


class EnhancedStatArbStrategy(BaseStrategy):
    _PARAM_CONSTRAINTS = {
        "lookback": (30, 252, 120),
        "entry_z": (1.0, 3.5, 2.0),
        "exit_z": (0.0, 1.5, 0.5),
        "kalman_Q": (1e-8, 1e-2, 1e-5),
        "kalman_R": (1e-4, 1.0, 1e-3),
    }

    def __init__(
        self,
        lookback: int = 120,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
        kalman_Q: float = 1e-5,  # noqa: N803
        kalman_R: float = 1e-3,  # noqa: N803
    ):
        self.lookback = lookback
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.kalman_Q = kalman_Q
        self.kalman_R = kalman_R
        super().__init__()
        self._long = self.lookback
        self._kf_mean: float = 0.0
        self._kf_var: float = 1.0
        self._kf_beta: float = 1.0
        self._spread_history: list[float] = []
        self._position: str = "flat"

    def reset(self) -> None:
        super().reset()
        self._kf_mean = 0.0
        self._kf_var = 1.0
        self._kf_beta = 1.0
        self._spread_history = []
        self._position = "flat"

    def _kalman_update(self, observation: float) -> tuple[float, float]:
        pred_mean = self._kf_mean
        pred_var = self._kf_var + self.kalman_Q
        kalman_gain = pred_var / (pred_var + self.kalman_R)
        updated_mean = pred_mean + kalman_gain * (observation - pred_mean)
        updated_var = (1.0 - kalman_gain) * pred_var
        self._kf_mean = updated_mean
        self._kf_var = max(updated_var, 1e-12)
        return updated_mean, np.sqrt(max(pred_var + self.kalman_R, 1e-12))

    def _kalman_beta_update(self, y: float, x: float) -> None:
        pred_beta = self._kf_beta
        pred_var = self._kf_var + self.kalman_Q * 100.0
        innovation = y - pred_beta * x
        innovation_var = pred_var * x * x + self.kalman_R * 1000.0
        if innovation_var > 1e-12:
            kalman_gain = pred_var * x / innovation_var
            self._kf_beta = pred_beta + kalman_gain * innovation / max(abs(x), 1e-12)
            self._kf_var = max((1.0 - kalman_gain * x) * pred_var, 1e-12)

    def on_bar(self, bar: dict, portfolio: dict) -> list[dict]:
        self._bar_index += 1
        max_window = self.lookback + 10
        new_row = pd.DataFrame([bar])
        if self._bar_df is None:
            self._bar_df = new_row
        else:
            self._bar_df = pd.concat([self._bar_df, new_row], ignore_index=True)
            if len(self._bar_df) > max_window:
                self._bar_df = self._bar_df.iloc[-max_window:].reset_index(drop=True)

        if len(self._bar_df) < 30:
            return []

        close = self._bar_df["close"].astype(float).values

        if "close_y" in self._bar_df.columns and "close_x" in self._bar_df.columns:
            y = self._bar_df["close_y"].astype(float).values
            x = self._bar_df["close_x"].astype(float).values
        else:
            y = close
            x = np.roll(close, 1)
            x[0] = close[0]

        self._kalman_beta_update(y[-1], x[-1])
        spread = y - self._kf_beta * x
        current_spread = float(spread[-1])

        self._spread_history.append(current_spread)
        if len(self._spread_history) > self.lookback:
            self._spread_history = self._spread_history[-self.lookback:]

        if len(self._spread_history) < 20:
            return []

        spread_arr = np.array(self._spread_history)
        kf_mean, kf_std = self._kalman_update(current_spread)

        if kf_std < 1e-12:
            return []

        z_score = (current_spread - kf_mean) / kf_std
        hl = _half_life(spread_arr)

        hl_scalar = min(1.0, 20.0 / max(hl, 1.0))

        returns = np.diff(spread_arr, prepend=spread_arr[0])
        cvar_val = _cvar(returns, alpha=0.05)
        mean_ret = float(np.mean(returns[-60:])) if len(returns) >= 10 else 0.0
        var_ret = float(np.var(returns[-60:], ddof=1)) if len(returns) >= 10 else 1.0
        kelly = mean_ret / max(var_ret, 1e-12) if var_ret > 1e-12 else 0.0
        kelly = np.clip(kelly, -1.0, 1.0)

        cvar_limit = 0.02
        cvar_sizing = cvar_limit / abs(cvar_val) if abs(cvar_val) > 1e-12 else 1.0
        position_size = float(np.clip(abs(kelly) * hl_scalar * cvar_sizing, 0.05, 1.0))

        signal_action = "hold"
        confidence = 0.0
        reason = ""

        if self._position == "flat":
            if z_score > self.entry_z:
                signal_action = "sell"
                confidence = min(abs(z_score) / 4.0, 0.95)
                reason = f"StatArb short spread z={z_score:.2f} hl={hl:.1f}"
                self._position = "short_spread"
            elif z_score < -self.entry_z:
                signal_action = "buy"
                confidence = min(abs(z_score) / 4.0, 0.95)
                reason = f"StatArb long spread z={z_score:.2f} hl={hl:.1f}"
                self._position = "long_spread"
        elif self._position == "short_spread":
            if z_score < self.exit_z:
                signal_action = "buy"
                confidence = 0.6
                reason = f"StatArb close short spread z={z_score:.2f}"
                self._position = "flat"
        elif self._position == "long_spread" and z_score > -self.exit_z:
            signal_action = "sell"
            confidence = 0.6
            reason = f"StatArb close long spread z={z_score:.2f}"
            self._position = "flat"

        if signal_action == "hold":
            return []

        return [{
            "action": signal_action,
            "reason": reason,
            "confidence": round(confidence, 2),
            "position_pct": round(position_size, 2),
        }]

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < 30:
            return TradeSignal(SignalType.HOLD)
        close = df["close"].astype(float).values
        if "close_y" in df.columns and "close_x" in df.columns:
            y = df["close_y"].astype(float).values
            x = df["close_x"].astype(float).values
        else:
            y = close
            x = np.roll(close, 1)
            x[0] = close[0]
        resid, _, beta = _ols_residual(x[-self.lookback:], y[-self.lookback:])
        if len(resid) < 10:
            return TradeSignal(SignalType.HOLD)
        z = (resid[-1] - np.mean(resid)) / max(np.std(resid, ddof=1), 1e-12)
        if z > self.entry_z:
            return TradeSignal(SignalType.SELL, min(abs(z) / 4.0, 0.95), f"StatArb short z={z:.2f}")
        if z < -self.entry_z:
            return TradeSignal(SignalType.BUY, min(abs(z) / 4.0, 0.95), f"StatArb long z={z:.2f}")
        return TradeSignal(SignalType.HOLD)


class AQRMomentumStrategy(BaseStrategy):
    _PARAM_CONSTRAINTS = {
        "lookback_months": (6, 24, 12),
        "skip_months": (0, 3, 1),
        "n_long": (1, 50, 10),
        "n_short": (0, 50, 10),
    }

    def __init__(
        self,
        lookback_months: int = 12,
        skip_months: int = 1,
        n_long: int = 10,
        n_short: int = 10,
    ):
        self.lookback_months = lookback_months
        self.skip_months = skip_months
        self.n_long = n_long
        self.n_short = n_short
        super().__init__()
        self._long = self.lookback_months * 22
        self._returns_by_asset: dict[str, list[float]] = {}
        self._industry_map: dict[str, str] = {}
        self._current_ranking: list[tuple[str, float]] = []

    def reset(self) -> None:
        super().reset()
        self._returns_by_asset = {}
        self._industry_map = {}
        self._current_ranking = []

    def on_bar(self, bar: dict, portfolio: dict) -> list[dict]:
        self._bar_index += 1
        max_window = self._long + 10
        new_row = pd.DataFrame([bar])
        if self._bar_df is None:
            self._bar_df = new_row
        else:
            self._bar_df = pd.concat([self._bar_df, new_row], ignore_index=True)
            if len(self._bar_df) > max_window:
                self._bar_df = self._bar_df.iloc[-max_window:].reset_index(drop=True)

        symbol = bar.get("symbol", "default")
        close = float(bar.get("close", 0))

        if symbol not in self._returns_by_asset:
            self._returns_by_asset[symbol] = []

        if close > 0 and len(self._bar_df) > 1:
            prev_close = float(self._bar_df["close"].iloc[-2]) if len(self._bar_df) >= 2 else close
            if prev_close > 0:
                ret = close / prev_close - 1.0
                self._returns_by_asset[symbol].append(ret)
            else:
                self._returns_by_asset[symbol].append(0.0)
        else:
            self._returns_by_asset[symbol].append(0.0)

        if len(self._returns_by_asset[symbol]) > self._long + 5:
            self._returns_by_asset[symbol] = self._returns_by_asset[symbol][-(self._long + 5):]

        if "industry" in bar and bar["industry"]:
            self._industry_map[symbol] = bar["industry"]

        if self._bar_index % 22 != 0:
            return []

        lookback_days = self.lookback_months * 22
        skip_days = self.skip_months * 22
        momentum_end = max(0, len(self._returns_by_asset[symbol]) - skip_days)
        _momentum_start = max(0, momentum_end - lookback_days)

        momentum_scores: dict[str, float] = {}
        for sym, rets in self._returns_by_asset.items():
            if len(rets) < lookback_days:
                continue
            end_idx = max(0, len(rets) - skip_days)
            start_idx = max(0, end_idx - lookback_days)
            if end_idx <= start_idx:
                continue
            cumulative = 1.0
            for r in rets[start_idx:end_idx]:
                cumulative *= (1.0 + r)
            momentum_scores[sym] = cumulative - 1.0

        if len(momentum_scores) < 3:
            return []

        industry_residuals: dict[str, float] = {}
        industries: dict[str, list[tuple[str, float]]] = {}
        for sym, score in momentum_scores.items():
            ind = self._industry_map.get(sym, "unknown")
            if ind not in industries:
                industries[ind] = []
            industries[ind].append((sym, score))

        for _ind, members in industries.items():
            if len(members) < 2:
                for sym, score in members:
                    industry_residuals[sym] = score
                continue
            scores = [s for _, s in members]
            ind_mean = float(np.mean(scores))
            ind_std = float(np.std(scores, ddof=1)) if len(scores) > 1 else 1.0
            for sym, score in members:
                industry_residuals[sym] = (score - ind_mean) / max(ind_std, 1e-12)

        sorted_assets = sorted(industry_residuals.items(), key=lambda x: x[1], reverse=True)
        self._current_ranking = sorted_assets

        signals: list[dict] = []
        long_candidates = sorted_assets[: self.n_long]
        short_candidates = sorted_assets[-self.n_short:] if self.n_short > 0 else []

        for sym, score in long_candidates:
            confidence = min(abs(score) * 0.2, 0.95)
            signals.append({
                "action": "buy",
                "reason": f"AQR momentum long {sym} score={score:.2f}",
                "confidence": round(confidence, 2),
                "position_pct": round(1.0 / max(self.n_long, 1), 2),
                "symbol": sym,
            })

        for sym, score in short_candidates:
            confidence = min(abs(score) * 0.2, 0.95)
            signals.append({
                "action": "sell",
                "reason": f"AQR momentum short {sym} score={score:.2f}",
                "confidence": round(confidence, 2),
                "position_pct": round(1.0 / max(self.n_short, 1), 2),
                "symbol": sym,
            })

        return signals

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < self._long + 1:
            return TradeSignal(SignalType.HOLD)
        close = df["close"].astype(float).values
        lookback_days = self.lookback_months * 22
        skip_days = self.skip_months * 22
        end_idx = max(0, len(close) - skip_days)
        start_idx = max(0, end_idx - lookback_days)
        if end_idx <= start_idx:
            return TradeSignal(SignalType.HOLD)
        momentum = close[end_idx - 1] / close[start_idx] - 1.0 if close[start_idx] > 0 else 0.0
        if momentum > 0.15:
            return TradeSignal(SignalType.BUY, min(momentum, 0.95), f"AQR momentum={momentum:.2f}")
        if momentum < -0.15:
            return TradeSignal(SignalType.SELL, min(abs(momentum), 0.95), f"AQR momentum={momentum:.2f}")
        return TradeSignal(SignalType.HOLD)


class _DecisionStump:
    __slots__ = ("feature_idx", "threshold", "left_value", "right_value")

    def __init__(self) -> None:
        self.feature_idx: int = 0
        self.threshold: float = 0.0
        self.left_value: float = 0.0
        self.right_value: float = 0.0

    def predict(self, X: np.ndarray) -> np.ndarray:  # noqa: N803
        if X.ndim == 1:
            return self.right_value if X[self.feature_idx] > self.threshold else self.left_value
        return np.where(X[:, self.feature_idx] > self.threshold, self.right_value, self.left_value)


class _GradientBoostedTrees:
    def __init__(
        self,
        n_estimators: int = 50,
        learning_rate: float = 0.1,
        max_depth: int = 3,
        min_samples_leaf: int = 20,
        subsample: float = 0.8,
    ) -> None:
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.subsample = subsample
        self._trees: list[list[_DecisionStump]] = []
        self._base_prediction: float = 0.0

    def _build_stumps(
        self,
        X: np.ndarray,  # noqa: N803
        residuals: np.ndarray,
        depth: int,
        indices: np.ndarray,
    ) -> list[_DecisionStump]:
        if depth == 0 or len(indices) < self.min_samples_leaf * 2:
            stump = _DecisionStump()
            stump.left_value = float(np.mean(residuals[indices]))
            stump.right_value = stump.left_value
            return [stump]

        n_features = X.shape[1]
        best_gain = -np.inf
        best_feature = 0
        best_threshold = 0.0

        for feat in range(n_features):
            values = np.unique(X[indices, feat])
            if len(values) <= 1:
                continue
            thresholds = (values[:-1] + values[1:]) / 2.0
            for thr in thresholds[:20]:
                left_mask = X[indices, feat] <= thr
                right_mask = ~left_mask
                n_left = int(np.sum(left_mask))
                n_right = int(np.sum(right_mask))
                if n_left < self.min_samples_leaf or n_right < self.min_samples_leaf:
                    continue
                left_mean = float(np.mean(residuals[indices[left_mask]]))
                right_mean = float(np.mean(residuals[indices[right_mask]]))
                gain = n_left * left_mean ** 2 + n_right * right_mean ** 2
                if gain > best_gain:
                    best_gain = gain
                    best_feature = feat
                    best_threshold = thr

        stump = _DecisionStump()
        stump.feature_idx = best_feature
        stump.threshold = best_threshold

        left_indices = indices[X[indices, best_feature] <= best_threshold]
        right_indices = indices[X[indices, best_feature] > best_threshold]

        if len(left_indices) < self.min_samples_leaf:
            stump.left_value = float(np.mean(residuals[indices]))
        else:
            stump.left_value = float(np.mean(residuals[left_indices]))

        if len(right_indices) < self.min_samples_leaf:
            stump.right_value = float(np.mean(residuals[indices]))
        else:
            stump.right_value = float(np.mean(residuals[right_indices]))

        result = [stump]
        if depth > 1:
            if len(left_indices) >= self.min_samples_leaf * 2:
                result.extend(self._build_stumps(X, residuals, depth - 1, left_indices))
            if len(right_indices) >= self.min_samples_leaf * 2:
                result.extend(self._build_stumps(X, residuals, depth - 1, right_indices))

        return result

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:  # noqa: N803
        n_samples = X.shape[0]
        self._base_prediction = float(np.mean(y))
        current_pred = np.full(n_samples, self._base_prediction)

        self._trees = []
        for _ in range(self.n_estimators):
            residuals = y - current_pred
            sample_size = max(int(n_samples * self.subsample), self.min_samples_leaf * 2)
            sample_indices = np.random.choice(n_samples, size=sample_size, replace=False)
            sample_indices.sort()

            tree_stumps = self._build_stumps(
                X, residuals, self.max_depth, sample_indices
            )
            self._trees.append(tree_stumps)

            update = np.zeros(n_samples)
            for stump in tree_stumps:
                update += stump.predict(X)
            update /= max(len(tree_stumps), 1)
            current_pred += self.learning_rate * update

    def predict(self, X: np.ndarray) -> np.ndarray:  # noqa: N803
        if X.ndim == 1:
            X = X.reshape(1, -1)  # noqa: N806
        pred = np.full(X.shape[0], self._base_prediction)
        for tree_stumps in self._trees:
            update = np.zeros(X.shape[0])
            for stump in tree_stumps:
                update += stump.predict(X)
            update /= max(len(tree_stumps), 1)
            pred += self.learning_rate * update
        return pred


class MLSignalStrategy(BaseStrategy):
    _PARAM_CONSTRAINTS = {
        "train_window": (60, 504, 252),
        "n_estimators": (10, 200, 50),
        "learning_rate": (0.01, 0.5, 0.1),
        "max_depth": (1, 6, 3),
        "retrain_freq": (10, 63, 21),
    }

    def __init__(
        self,
        train_window: int = 252,
        n_estimators: int = 50,
        learning_rate: float = 0.1,
        max_depth: int = 3,
        retrain_freq: int = 21,
    ):
        self.train_window = train_window
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.retrain_freq = retrain_freq
        super().__init__()
        self._long = self.train_window
        self._model: _GradientBoostedTrees | None = None
        self._last_train_bar: int = -9999
        self._feature_names: list[str] = []

    def reset(self) -> None:
        super().reset()
        self._model = None
        self._last_train_bar = -9999
        self._feature_names = []

    def _compute_features(self, close: np.ndarray, high: np.ndarray, low: np.ndarray, volume: np.ndarray) -> np.ndarray:
        n = len(close)
        features = np.zeros((n, 6))

        features[:, 0] = _rsi_array(close, period=14)

        _, _, macd_hist = _macd_array(close)
        features[:, 1] = macd_hist

        features[:, 2] = _bollinger_width(close, period=20)

        vol_ma = _ewma(volume, span=20)
        features[:, 3] = np.where(vol_ma > 1e-12, volume / vol_ma, 1.0)

        intraday_range = np.where(close > 1e-12, (high - low) / close, 0.0)
        features[:, 4] = intraday_range

        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        overnight_gap = np.where(prev_close > 1e-12, (close - prev_close) / prev_close, 0.0)
        overnight_gap[0] = 0.0
        features[:, 5] = overnight_gap

        features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
        return features

    def _create_labels(self, close: np.ndarray, horizon: int = 5) -> np.ndarray:
        future_returns = np.roll(close, -horizon) / close - 1.0
        future_returns[-horizon:] = 0.0
        labels = np.sign(future_returns)
        labels[np.abs(future_returns) < 0.005] = 0.0
        return labels

    def on_bar(self, bar: dict, portfolio: dict) -> list[dict]:
        self._bar_index += 1
        max_window = self.train_window + 20
        new_row = pd.DataFrame([bar])
        if self._bar_df is None:
            self._bar_df = new_row
        else:
            self._bar_df = pd.concat([self._bar_df, new_row], ignore_index=True)
            if len(self._bar_df) > max_window:
                self._bar_df = self._bar_df.iloc[-max_window:].reset_index(drop=True)

        if len(self._bar_df) < 60:
            return []

        close = self._bar_df["close"].astype(float).values
        high = self._bar_df["high"].astype(float).values
        low = self._bar_df["low"].astype(float).values
        volume = self._bar_df["volume"].astype(float).values

        features = self._compute_features(close, high, low, volume)

        need_retrain = (
            self._model is None
            or (self._bar_index - self._last_train_bar) >= self.retrain_freq
        )

        if need_retrain and len(close) >= 60:
            labels = self._create_labels(close, horizon=5)
            train_start = max(0, len(close) - self.train_window)
            X_train = features[train_start:-5]  # noqa: N806
            y_train = labels[train_start:-5]

            valid_mask = y_train != 0.0
            if np.sum(valid_mask) < 30:
                return []

            self._model = _GradientBoostedTrees(
                n_estimators=self.n_estimators,
                learning_rate=self.learning_rate,
                max_depth=self.max_depth,
                min_samples_leaf=20,
                subsample=0.8,
            )
            self._model.fit(X_train[valid_mask], y_train[valid_mask])
            self._last_train_bar = self._bar_index
            logger.debug("MLSignalStrategy retrained at bar %d", self._bar_index)

        if self._model is None:
            return []

        current_features = features[-1].reshape(1, -1)
        prediction = float(self._model.predict(current_features)[0])

        if abs(prediction) < 0.1:
            return []

        signal_action = "buy" if prediction > 0 else "sell"
        confidence = min(abs(prediction) * 0.5, 0.95)
        reason = f"ML prediction={prediction:.3f}"

        return [{
            "action": signal_action,
            "reason": reason,
            "confidence": round(confidence, 2),
            "position_pct": round(float(np.clip(abs(prediction) * 0.3, 0.05, 0.8)), 2),
        }]

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < 60:
            return TradeSignal(SignalType.HOLD)
        close = df["close"].astype(float).values
        high = df["high"].astype(float).values
        low = df["low"].astype(float).values
        volume = df["volume"].astype(float).values
        features = self._compute_features(close, high, low, volume)
        labels = self._create_labels(close, horizon=5)
        train_start = max(0, len(close) - self.train_window)
        X_train = features[train_start:-5]  # noqa: N806
        y_train = labels[train_start:-5]
        valid_mask = y_train != 0.0
        if np.sum(valid_mask) < 30:
            return TradeSignal(SignalType.HOLD)
        model = _GradientBoostedTrees(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
        )
        model.fit(X_train[valid_mask], y_train[valid_mask])
        pred = float(model.predict(features[-1].reshape(1, -1))[0])
        if pred > 0.1:
            return TradeSignal(SignalType.BUY, min(abs(pred) * 0.5, 0.95), f"ML prediction={pred:.3f}")
        if pred < -0.1:
            return TradeSignal(SignalType.SELL, min(abs(pred) * 0.5, 0.95), f"ML prediction={pred:.3f}")
        return TradeSignal(SignalType.HOLD)


class MarketMakingStrategy(BaseStrategy):
    _PARAM_CONSTRAINTS = {
        "gamma": (0.01, 2.0, 0.1),
        "kappa": (0.1, 10.0, 1.5),
        "inventory_limit": (0.1, 1.0, 0.5),
        "vpin_window": (10, 100, 50),
        "vpin_threshold": (0.3, 0.9, 0.6),
    }

    def __init__(
        self,
        gamma: float = 0.1,
        kappa: float = 1.5,
        inventory_limit: float = 0.5,
        vpin_window: int = 50,
        vpin_threshold: float = 0.6,
    ):
        self.gamma = gamma
        self.kappa = kappa
        self.inventory_limit = inventory_limit
        self.vpin_window = vpin_window
        self.vpin_threshold = vpin_threshold
        super().__init__()
        self._long = self.vpin_window
        self._inventory: float = 0.0
        self._mid_price: float = 0.0
        self._vol_estimate: float = 0.01
        self._volume_buckets: list[dict[str, float]] = []
        self._prev_close: float = 0.0

    def reset(self) -> None:
        super().reset()
        self._inventory = 0.0
        self._mid_price = 0.0
        self._vol_estimate = 0.01
        self._volume_buckets = []
        self._prev_close = 0.0

    def _compute_vpin(self) -> float:
        if len(self._volume_buckets) < 10:
            return 0.0
        recent = self._volume_buckets[-self.vpin_window:]
        total_vol = sum(b["volume"] for b in recent)
        if total_vol < 1e-12:
            return 0.0
        vpin = sum(abs(b["buy_vol"] - b["sell_vol"]) for b in recent) / total_vol
        return vpin

    def _classify_volume(self, close: float, prev_close: float, volume: float) -> tuple[float, float]:
        if prev_close < 1e-12:
            return volume * 0.5, volume * 0.5
        price_change = close - prev_close
        if abs(price_change) < 1e-12:
            return volume * 0.5, volume * 0.5
        buy_frac = max(0.0, min(1.0, 0.5 + price_change / (2.0 * abs(price_change))))
        buy_vol = volume * buy_frac
        sell_vol = volume * (1.0 - buy_frac)
        return buy_vol, sell_vol

    def on_bar(self, bar: dict, portfolio: dict) -> list[dict]:
        self._bar_index += 1
        max_window = self.vpin_window + 10
        new_row = pd.DataFrame([bar])
        if self._bar_df is None:
            self._bar_df = new_row
        else:
            self._bar_df = pd.concat([self._bar_df, new_row], ignore_index=True)
            if len(self._bar_df) > max_window:
                self._bar_df = self._bar_df.iloc[-max_window:].reset_index(drop=True)

        close = float(bar.get("close", 0))
        high = float(bar.get("high", close))
        low = float(bar.get("low", close))
        volume = float(bar.get("volume", 0))

        if close <= 0:
            return []

        self._mid_price = (high + low) / 2.0

        if self._prev_close > 0:
            returns = close / self._prev_close - 1.0
            self._vol_estimate = 0.94 * self._vol_estimate + 0.06 * returns ** 2

        prev_close_snapshot = self._prev_close
        self._prev_close = close

        sigma = np.sqrt(self._vol_estimate * 252) if self._vol_estimate > 0 else 0.01

        buy_vol, sell_vol = self._classify_volume(close, prev_close_snapshot, volume)
        self._volume_buckets.append({"buy_vol": buy_vol, "sell_vol": sell_vol, "volume": volume})
        if len(self._volume_buckets) > self.vpin_window + 10:
            self._volume_buckets = self._volume_buckets[-(self.vpin_window + 10):]

        vpin = self._compute_vpin()
        vpin_risk_mult = 1.0 + max(0.0, (vpin - self.vpin_threshold)) * 5.0

        inventory_ratio = self._inventory / max(self.inventory_limit, 1e-12)
        inventory_skew = -self.gamma * inventory_ratio * sigma * self._mid_price

        reservation_price = self._mid_price + inventory_skew

        spread_half = self.gamma * sigma ** 2 * self._bar_index * 0.001 + self.kappa * sigma * vpin_risk_mult
        spread_half = max(spread_half, self._mid_price * 0.0001)

        bid = reservation_price - spread_half
        ask = reservation_price + spread_half

        if vpin > self.vpin_threshold:
            spread_half *= vpin_risk_mult
            bid = reservation_price - spread_half
            ask = reservation_price + spread_half

        signals: list[dict] = []

        if self._inventory < self.inventory_limit:
            confidence = min(0.5 + 0.5 * (1.0 - abs(inventory_ratio)), 0.95)
            signals.append({
                "action": "buy",
                "reason": f"MM bid={bid:.2f} inv={self._inventory:.3f} vpin={vpin:.3f}",
                "confidence": round(confidence, 2),
                "position_pct": round(float(np.clip(0.1 * (1.0 - abs(inventory_ratio)), 0.02, 0.2)), 2),
                "price": round(bid, 2),
            })

        if self._inventory > -self.inventory_limit:
            confidence = min(0.5 + 0.5 * (1.0 - abs(inventory_ratio)), 0.95)
            signals.append({
                "action": "sell",
                "reason": f"MM ask={ask:.2f} inv={self._inventory:.3f} vpin={vpin:.3f}",
                "confidence": round(confidence, 2),
                "position_pct": round(float(np.clip(0.1 * (1.0 - abs(inventory_ratio)), 0.02, 0.2)), 2),
                "price": round(ask, 2),
            })

        if close <= bid and self._inventory < self.inventory_limit:
            self._inventory += 0.1
        elif close >= ask and self._inventory > -self.inventory_limit:
            self._inventory -= 0.1

        return signals

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < 10:
            return TradeSignal(SignalType.HOLD)
        close = df["close"].astype(float).values
        high = df["high"].astype(float).values
        low = df["low"].astype(float).values
        mid = (high[-1] + low[-1]) / 2.0
        returns = np.diff(close, prepend=close[0]) / np.where(np.roll(close, 1) > 0, np.roll(close, 1), 1.0)
        returns[0] = 0.0
        sigma = float(np.std(returns[-20:], ddof=1)) * np.sqrt(252) if len(returns) >= 20 else 0.01
        spread_half = self.gamma * sigma ** 2 + self.kappa * sigma
        bid = mid - spread_half
        ask = mid + spread_half
        if close[-1] <= bid:
            return TradeSignal(SignalType.BUY, 0.6, f"MM bid fill at {bid:.2f}")
        if close[-1] >= ask:
            return TradeSignal(SignalType.SELL, 0.6, f"MM ask fill at {ask:.2f}")
        return TradeSignal(SignalType.HOLD)


STRATEGY_META: dict[str, dict[str, Any]] = {
    "cta_trend": {
        "class": CTATrendStrategy,
        "name": "CTATrendStrategy",
        "category": "trend",
        "description": "Multi-timeframe trend following with EWMA diff / ATR normalization and 15% annual volatility targeting",
        "risk_level": "medium",
        "typical_horizon": "days_to_weeks",
        "min_capital": 100000,
        "instruments": ["futures", "equity_index", "forex"],
        "parameters": {
            "fast_span": {"type": "int", "default": 16, "range": [5, 60]},
            "slow_span": {"type": "int", "default": 48, "range": [20, 200]},
            "atr_period": {"type": "int", "default": 20, "range": [5, 50]},
            "target_vol": {"type": "float", "default": 0.15, "range": [0.05, 0.40]},
        },
    },
    "enhanced_stat_arb": {
        "class": EnhancedStatArbStrategy,
        "name": "EnhancedStatArbStrategy",
        "category": "mean_reversion",
        "description": "Kalman filter dynamic cointegration estimation with half-life adaptive sizing and Kelly+CVaR position control",
        "risk_level": "medium_high",
        "typical_horizon": "hours_to_days",
        "min_capital": 500000,
        "instruments": ["equity_pairs", "etf_pairs", "futures_spread"],
        "parameters": {
            "lookback": {"type": "int", "default": 120, "range": [30, 252]},
            "entry_z": {"type": "float", "default": 2.0, "range": [1.0, 3.5]},
            "exit_z": {"type": "float", "default": 0.5, "range": [0.0, 1.5]},
            "kalman_Q": {"type": "float", "default": 1e-5, "range": [1e-8, 1e-2]},
            "kalman_R": {"type": "float", "default": 1e-3, "range": [1e-4, 1.0]},
        },
    },
    "aqr_momentum": {
        "class": AQRMomentumStrategy,
        "name": "AQRMomentumStrategy",
        "category": "momentum",
        "description": "12-1 month momentum with skip-last-month, industry neutralization, and long-short portfolio construction",
        "risk_level": "medium",
        "typical_horizon": "months",
        "min_capital": 1000000,
        "instruments": ["equity_universe", "country_index"],
        "parameters": {
            "lookback_months": {"type": "int", "default": 12, "range": [6, 24]},
            "skip_months": {"type": "int", "default": 1, "range": [0, 3]},
            "n_long": {"type": "int", "default": 10, "range": [1, 50]},
            "n_short": {"type": "int", "default": 10, "range": [0, 50]},
        },
    },
    "ml_signal": {
        "class": MLSignalStrategy,
        "name": "MLSignalStrategy",
        "category": "machine_learning",
        "description": "Pure numpy gradient boosted trees with RSI/MACD/BB width/volume ratio/intraday range/overnight gap features and rolling 252-day training",
        "risk_level": "medium_high",
        "typical_horizon": "days",
        "min_capital": 200000,
        "instruments": ["equity", "etf", "futures"],
        "parameters": {
            "train_window": {"type": "int", "default": 252, "range": [60, 504]},
            "n_estimators": {"type": "int", "default": 50, "range": [10, 200]},
            "learning_rate": {"type": "float", "default": 0.1, "range": [0.01, 0.5]},
            "max_depth": {"type": "int", "default": 3, "range": [1, 6]},
            "retrain_freq": {"type": "int", "default": 21, "range": [10, 63]},
        },
    },
    "market_making": {
        "class": MarketMakingStrategy,
        "name": "MarketMakingStrategy",
        "category": "market_making",
        "description": "Avellaneda-Stoikov optimal quote model with inventory risk adjustment and VPIN toxic flow detection",
        "risk_level": "high",
        "typical_horizon": "intraday",
        "min_capital": 500000,
        "instruments": ["equity", "futures", "crypto"],
        "parameters": {
            "gamma": {"type": "float", "default": 0.1, "range": [0.01, 2.0]},
            "kappa": {"type": "float", "default": 1.5, "range": [0.1, 10.0]},
            "inventory_limit": {"type": "float", "default": 0.5, "range": [0.1, 1.0]},
            "vpin_window": {"type": "int", "default": 50, "range": [10, 100]},
            "vpin_threshold": {"type": "float", "default": 0.6, "range": [0.3, 0.9]},
        },
    },
}

_ADVANCED_REGISTRY: dict[str, type[BaseStrategy]] = {
    "cta_trend": CTATrendStrategy,
    "CTATrendStrategy": CTATrendStrategy,
    "enhanced_stat_arb": EnhancedStatArbStrategy,
    "EnhancedStatArbStrategy": EnhancedStatArbStrategy,
    "aqr_momentum": AQRMomentumStrategy,
    "AQRMomentumStrategy": AQRMomentumStrategy,
    "ml_signal": MLSignalStrategy,
    "MLSignalStrategy": MLSignalStrategy,
    "market_making": MarketMakingStrategy,
    "MarketMakingStrategy": MarketMakingStrategy,
}

STRATEGY_REGISTRY.update(_ADVANCED_REGISTRY)
