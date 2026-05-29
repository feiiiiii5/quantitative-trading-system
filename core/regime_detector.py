"""
市场状态识别模块
识别六种市场状态并提供状态切换信号
"""
import logging
from enum import Enum
from typing import Literal

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    BULL_BREAKOUT = "bull_breakout"
    BULL_BASE = "bull_base"
    DISTRIBUTED_HIGH = "distributed_high"
    BEAR_RALLY = "bear_rally"
    BEAR_DISTRIBUTION = "bear_distribution"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


class MarketRegimeDetector:
    TREND_THRESHOLD = 0.15
    VOL_THRESHOLD = 1.5
    MOMENTUM_RANGE = (-25, 25)

    def __init__(
        self,
        trend_window: int = 20,
        vol_window: int = 20,
        lookback: int = 120,
    ):
        self._trend_window = trend_window
        self._vol_window = vol_window
        self._lookback = lookback

    def detect(self, df: pd.DataFrame) -> tuple[MarketRegime, dict]:
        if df is None or len(df) < max(self._trend_window, self._vol_window, 30):
            return MarketRegime.UNKNOWN, {}

        close = df["close"].astype(float)
        volume = df["volume"].astype(float)

        trend = self._compute_trend(close)
        volatility = self._compute_volatility(df)
        momentum = self._compute_momentum(close)
        volume_profile = self._compute_volume_profile(volume, close)
        regime_duration = self._detect_regime_duration(df)

        regime, confidence = self._classify_regime(
            trend, volatility, momentum, volume_profile, regime_duration
        )

        context = {
            "trend": round(trend, 4),
            "volatility": round(volatility, 4),
            "momentum": round(momentum, 4),
            "volume_profile": round(volume_profile, 4),
            "regime_duration": regime_duration,
            "confidence": round(confidence, 4),
            "regime_label": regime.value,
            "indicators": self._build_indicators(df, trend, volatility, momentum),
        }

        return regime, context

    def _compute_trend(self, close: pd.Series) -> float:
        ma_fast = close.rolling(self._trend_window).mean()
        ma_slow = close.rolling(self._trend_window * 2).mean()
        if len(ma_fast) < 2 or ma_fast.iloc[-1] <= 0 or ma_slow.iloc[-1] <= 0:
            return 0.0
        trend = (ma_fast.iloc[-1] - ma_slow.iloc[-1]) / ma_slow.iloc[-1]
        return float(trend)

    def _compute_volatility(self, df: pd.DataFrame) -> float:
        returns = df["close"].pct_change().dropna()
        if len(returns) < self._vol_window:
            return 1.0
        vol = returns.tail(self._vol_window).std()
        hist_vol = returns.tail(self._lookback).std()
        vol_ratio = vol / hist_vol if hist_vol > 0 else 1.0
        return float(vol_ratio)

    def _compute_momentum(self, close: pd.Series) -> float:
        if len(close) < self._lookback:
            return 0.0
        current = close.iloc[-1]
        past = close.iloc[-self._lookback]
        if past <= 0:
            return 0.0
        momentum = (current - past) / past * 100
        return float(np.clip(momentum, -60, 60))

    def _compute_volume_profile(self, volume: pd.Series, close: pd.Series) -> float:
        if len(volume) < 20:
            return 0.0
        avg_vol = volume.tail(20).mean()
        hist_avg = volume.tail(self._lookback).mean()
        if hist_avg <= 0:
            return 0.0
        vol_ratio = avg_vol / hist_avg
        price_change = close.pct_change().tail(20).mean()
        if vol_ratio > 1.2 and price_change > 0:
            return float(vol_ratio)
        elif vol_ratio > 1.2 and price_change < 0:
            return float(-vol_ratio)
        return 0.0

    def _detect_regime_duration(self, df: pd.DataFrame) -> int:
        if len(df) < 60:
            return 0
        returns = df["close"].pct_change().dropna()
        rolling_ret = returns.rolling(5).sum()
        signs = np.sign(rolling_ret)
        switches = np.sum(np.diff(signs.fillna(0)) != 0)
        regime_duration = int(len(returns) / max(switches, 1))
        return regime_duration

    def _classify_regime(
        self,
        trend: float,
        vol_ratio: float,
        momentum: float,
        vol_profile: float,
        regime_duration: int,
    ) -> tuple[MarketRegime, float]:
        high_vol = vol_ratio > self.VOL_THRESHOLD

        if high_vol:
            confidence = min(vol_ratio / 2.0, 1.0)
            return MarketRegime.VOLATILE, confidence

        if trend > self.TREND_THRESHOLD and momentum > 20:
            if vol_profile > 0:
                confidence = min((trend + momentum / 100) / 2, 1.0)
                return MarketRegime.BULL_BREAKOUT, confidence
            else:
                confidence = min(trend / 0.3, 0.9)
                return MarketRegime.BULL_BASE, confidence

        if trend > self.TREND_THRESHOLD * 0.5 and 0 < momentum <= 25:
            confidence = min(trend / 0.25, 0.85)
            return MarketRegime.BULL_BASE, confidence

        if trend > 0 and momentum < -15:
            confidence = min(abs(momentum) / 60, 0.9)
            return MarketRegime.DISTRIBUTED_HIGH, confidence

        if trend < -self.TREND_THRESHOLD and momentum > 15:
            confidence = min(abs(momentum) / 60, 0.85)
            return MarketRegime.BEAR_RALLY, confidence

        if trend < -self.TREND_THRESHOLD and momentum < -20:
            confidence = min(abs(momentum) / 60, 0.9)
            return MarketRegime.BEAR_DISTRIBUTION, confidence

        if abs(trend) < self.TREND_THRESHOLD * 0.5 and abs(momentum) < 10:
            confidence = 0.75
            return MarketRegime.VOLATILE, confidence

        confidence = 0.5
        return MarketRegime.UNKNOWN, confidence

    def _build_indicators(self, df: pd.DataFrame, trend: float, vol_ratio: float, momentum: float) -> dict:
        close = df["close"].astype(float)
        returns = df["close"].pct_change().dropna()

        returns_20d = returns.tail(20)
        downside = returns_20d[returns_20d < 0].std() if len(returns_20d[returns_20d < 0]) > 0 else 0
        upside = returns_20d[returns_20d > 0].std() if len(returns_20d[returns_20d > 0]) > 0 else 0
        asymmetry = (upside - downside) / (upside + downside + 1e-12)

        recent_high = close.tail(60).max()
        recent_low = close.tail(60).min()
        range_position = (close.iloc[-1] - recent_low) / (recent_high - recent_low + 1e-12) if recent_high > recent_low else 0.5

        adx = self._compute_adx(df) if len(df) > 14 else 50.0

        return {
            "asymmetry": round(float(asymmetry), 4),
            "range_position": round(float(range_position), 4),
            "adx": round(float(adx), 2),
            "trend_strength": "strong" if abs(trend) > self.TREND_THRESHOLD else "weak",
            "volatility_regime": "high" if vol_ratio > self.VOL_THRESHOLD else "normal",
        }

    def _compute_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        n = len(close)
        if n <= period:
            return 50.0

        tr1 = high.values[1:] - low.values[1:]
        tr2 = np.abs(high.values[1:] - close.values[:-1])
        tr3 = np.abs(low.values[1:] - close.values[:-1])
        tr = np.maximum(np.maximum(tr1, tr2), tr3)
        tr = np.insert(tr, 0, high.iloc[0] - low.iloc[0])
        plus_dm = np.maximum(np.diff(high, prepend=high.iloc[0]), 0)
        minus_dm = np.maximum(-np.diff(low, prepend=low.iloc[0]), 0)
        plus_dm[1:][plus_dm[1:] < minus_dm[:-1]] = 0
        minus_dm[1:][minus_dm[1:] < plus_dm[:-1]] = 0

        atr = pd.Series(tr).ewm(alpha=1 / period, min_periods=period).mean().values
        plus_di = pd.Series(plus_dm).ewm(alpha=1 / period, min_periods=period).mean().values / (atr + 1e-12) * 100
        minus_di = pd.Series(minus_dm).ewm(alpha=1 / period, min_periods=period).mean().values / (atr + 1e-12) * 100
        dx = np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-12) * 100
        adx = pd.Series(dx).ewm(alpha=1 / period, min_periods=period).mean().values[-1]
        return float(adx) if np.isfinite(adx) else 50.0


class RegimeAwareSignalGenerator:
    REGIME_CONFIG = {
        MarketRegime.BULL_BREAKOUT: {
            "signal_bias": 1.0,
            "stop_loss_pct": 0.03,
            "take_profit_pct": 0.08,
            "position_scale": 1.2,
            "description": "强势上涨，建议追涨",
        },
        MarketRegime.BULL_BASE: {
            "signal_bias": 0.5,
            "stop_loss_pct": 0.05,
            "take_profit_pct": 0.10,
            "position_scale": 1.0,
            "description": "震荡蓄力，等待突破确认",
        },
        MarketRegime.DISTRIBUTED_HIGH: {
            "signal_bias": -0.5,
            "stop_loss_pct": 0.05,
            "take_profit_pct": 0.06,
            "position_scale": 0.7,
            "description": "高位派发，控制仓位",
        },
        MarketRegime.BEAR_RALLY: {
            "signal_bias": 0.3,
            "stop_loss_pct": 0.04,
            "take_profit_pct": 0.05,
            "position_scale": 0.5,
            "description": "熊市反弹，快进快出",
        },
        MarketRegime.BEAR_DISTRIBUTION: {
            "signal_bias": -1.0,
            "stop_loss_pct": 0.03,
            "take_profit_pct": 0.05,
            "position_scale": 0.3,
            "description": "趋势下跌，清仓观望",
        },
        MarketRegime.VOLATILE: {
            "signal_bias": 0.0,
            "stop_loss_pct": 0.06,
            "take_profit_pct": 0.08,
            "position_scale": 0.6,
            "description": "高波动，谨慎操作",
        },
        MarketRegime.UNKNOWN: {
            "signal_bias": 0.0,
            "stop_loss_pct": 0.05,
            "take_profit_pct": 0.08,
            "position_scale": 0.5,
            "description": "状态未知，轻仓试探",
        },
    }

    def __init__(self, detector: MarketRegimeDetector | None = None):
        self._detector = detector or MarketRegimeDetector()

    def analyze(self, df: pd.DataFrame) -> dict:
        regime, context = self._detector.detect(df)
        config = self.REGIME_CONFIG.get(regime, self.REGIME_CONFIG[MarketRegime.UNKNOWN])

        return {
            "regime": regime.value,
            "confidence": context.get("confidence", 0.0),
            "signal_bias": config["signal_bias"],
            "stop_loss_pct": config["stop_loss_pct"],
            "take_profit_pct": config["take_profit_pct"],
            "position_scale": config["position_scale"],
            "description": config["description"],
            "indicators": context.get("indicators", {}),
            "trend": context.get("trend", 0.0),
            "volatility": context.get("volatility", 1.0),
            "momentum": context.get("momentum", 0.0),
        }

    def get_regime_config(self, regime: MarketRegime) -> dict:
        return self.REGIME_CONFIG.get(regime, self.REGIME_CONFIG[MarketRegime.UNKNOWN])


_regime_detector: MarketRegimeDetector | None = None
_regime_lock: Literal["threading"] | None = None


def get_regime_detector() -> MarketRegimeDetector:
    global _regime_detector
    if _regime_detector is None:
        import threading
        global _regime_lock
        if _regime_lock is None:
            _regime_lock = threading.Lock()
        with _regime_lock:
            if _regime_detector is None:
                _regime_detector = MarketRegimeDetector()
    return _regime_detector


def detect_market_regime(df: pd.DataFrame) -> tuple[str, dict]:
    detector = get_regime_detector()
    regime, context = detector.detect(df)
    return regime.value, context


def analyze_regime_signals(df: pd.DataFrame) -> dict:
    generator = RegimeAwareSignalGenerator()
    return generator.analyze(df)



class _RegimeResult:
    """Backward-compatible result object matching old RegimeDetector interface.

    Old code expects: .current_regime (Enum), .confidence, .trend_strength,
                      .volatility_level, .mean_reversion_score, .transition_probabilities
    New interface:   detect() returns (MarketRegime, dict)
    """

    def __init__(
        self,
        regime: MarketRegime,
        context: dict,
        trend_strength: float = 50.0,
        volatility_level: float = 1.0,
        mean_reversion_score: float = 0.0,
        transition_probabilities: dict | None = None,
    ):
        self.current_regime = regime
        self.confidence = context.get("confidence", 0.5)
        self.trend_strength = trend_strength
        self.volatility_level = volatility_level
        self.mean_reversion_score = mean_reversion_score
        self.transition_probabilities = transition_probabilities or {}


class RegimeAdapter:
    """Backward-compatible adapter for code expecting old RegimeDetector interface.

    Old code calls: detector.detect(df) → object with .current_regime.value,
                    .confidence, .trend_strength, .volatility_level,
                    .mean_reversion_score, .transition_probabilities
    New interface:  detector.detect(df) → (MarketRegime, dict)
    """

    def __init__(self):
        self._inner = MarketRegimeDetector()

    def detect(self, df: pd.DataFrame) -> _RegimeResult:
        regime, ctx = self._inner.detect(df)
        if df is None or len(df) < 30:
            return _RegimeResult(regime, ctx)

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        returns = close.pct_change().dropna()

        trend_strength = float(self._inner._compute_adx(df))

        if len(close) >= 14:
            tr1 = high.values[1:] - low.values[1:]
            tr2 = np.abs(high.values[1:] - close.values[:-1])
            tr3 = np.abs(low.values[1:] - close.values[:-1])
            tr = np.maximum(np.maximum(tr1, tr2), tr3)
            tr = np.insert(tr, 0, high.iloc[0] - low.iloc[0])
            atr = pd.Series(tr).ewm(alpha=1 / 14, min_periods=14).mean().values
            volatility_level = float(atr[-1] / close.mean())
        else:
            volatility_level = float(returns.std() * np.sqrt(252))

        z_window = min(20, len(close) - 1)
        if z_window > 5:
            ma = close.rolling(z_window).mean()
            std = close.rolling(z_window).std()
            z = (close.iloc[-1] - ma.iloc[-1]) / (std.iloc[-1] + 1e-12)
            mean_reversion_score = float(np.clip(-z, -1, 1))
        else:
            mean_reversion_score = 0.0

        transitions = {
            "bull_breakout": 0.4,
            "bull_base": 0.3,
            "volatile": 0.2,
            "distributed_high": 0.05,
            "bear_rally": 0.03,
            "bear_distribution": 0.02,
        }
        if regime == MarketRegime.BULL_BREAKOUT:
            transitions["bull_breakout"] = 0.55
            transitions["bull_base"] = 0.25
            transitions["volatile"] = 0.1
        elif regime == MarketRegime.BULL_BASE:
            transitions["bull_base"] = 0.45
            transitions["bull_breakout"] = 0.3
            transitions["volatile"] = 0.15
        elif regime == MarketRegime.VOLATILE:
            transitions["volatile"] = 0.4
            transitions["bull_base"] = 0.25
            transitions["bull_breakout"] = 0.15
        elif regime == MarketRegime.DISTRIBUTED_HIGH:
            transitions["distributed_high"] = 0.4
            transitions["bear_distribution"] = 0.3
            transitions["volatile"] = 0.2
        elif regime == MarketRegime.BEAR_RALLY:
            transitions["bear_rally"] = 0.4
            transitions["volatile"] = 0.3
            transitions["bear_distribution"] = 0.2
        elif regime == MarketRegime.BEAR_DISTRIBUTION:
            transitions["bear_distribution"] = 0.5
            transitions["bear_rally"] = 0.25
            transitions["volatile"] = 0.15

        return _RegimeResult(
            regime, ctx, trend_strength, volatility_level,
            mean_reversion_score, transitions
        )

    def _recommend_strategy(self, result: _RegimeResult) -> str:
        regime = result.current_regime
        regime_str = regime.value if isinstance(regime, MarketRegime) else str(regime)
        recommendations = {
            "bull_breakout": "momentum",
            "bull_base": "base_building",
            "distributed_high": "mean_reversion",
            "bear_rally": "counter_trend",
            "bear_distribution": "short_term_reversal",
            "volatile": "volatility_breakout",
        }
        if regime_str == "bull_breakout" and result.trend_strength > 60:
            return "trailing_stop"
        elif regime_str == "bull_base" and result.volatility_level < 0.02:
            return "breakout"
        elif regime_str == "volatile" and result.trend_strength < 20:
            return "range_bound"
        elif regime_str in ("bear_rally", "bear_distribution"):
            return recommendations.get(regime_str, "conservative")
        return recommendations.get(regime_str, "adaptive")


def RegimeDetector() -> RegimeAdapter:  # noqa: N802
    return RegimeAdapter()

