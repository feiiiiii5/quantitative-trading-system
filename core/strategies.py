"""
QuantCore 策略模块
提供多种量化策略实现
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class TradeSignal:
    signal_type: SignalType
    strength: float = 0.0
    reason: str = ""


@dataclass
class StrategyResult:
    strategy_name: str
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    benchmark_return: float = 0.0
    alpha: float = 0.0
    beta: float = 1.0
    equity_curve: list = field(default_factory=list)
    drawdown_curve: list = field(default_factory=list)
    dates: list = field(default_factory=list)


class BaseStrategy:
    """策略基类"""

    def __init__(self):
        self.name = self.__class__.__name__

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        raise NotImplementedError

    def generate_score(self, df: pd.DataFrame) -> float:
        signal = self.generate_signal(df)
        if signal.signal_type == SignalType.BUY:
            return signal.strength
        elif signal.signal_type == SignalType.SELL:
            return -signal.strength
        return 0.0

    def get_info(self) -> dict:
        return {"name": self.name, "type": self.__class__.__base__.__name__}


class DualMAStrategy(BaseStrategy):
    """双均线策略"""

    def __init__(self, short_period: int = 5, long_period: int = 20):
        super().__init__()
        self._short = short_period
        self._long = long_period

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < self._long + 1:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        ma_short = c.rolling(self._short).mean()
        ma_long = c.rolling(self._long).mean()
        if ma_short.iloc[-1] > ma_long.iloc[-1] and ma_short.iloc[-2] <= ma_long.iloc[-2]:
            return TradeSignal(SignalType.BUY, 0.7, f"MA{self._short}上穿MA{self._long}")
        if ma_short.iloc[-1] < ma_long.iloc[-1] and ma_short.iloc[-2] >= ma_long.iloc[-2]:
            return TradeSignal(SignalType.SELL, 0.7, f"MA{self._short}下穿MA{self._long}")
        if ma_short.iloc[-1] > ma_long.iloc[-1]:
            return TradeSignal(SignalType.BUY, 0.3, f"MA{self._short}>MA{self._long}")
        return TradeSignal(SignalType.SELL, 0.3, f"MA{self._short}<MA{self._long}")


class MACDStrategy(BaseStrategy):
    """MACD策略"""

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < 35:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        hist = (dif - dea) * 2
        if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
            return TradeSignal(SignalType.BUY, 0.8, "MACD金叉")
        if dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2]:
            return TradeSignal(SignalType.SELL, 0.8, "MACD死叉")
        if hist.iloc[-1] > 0 and hist.iloc[-1] > hist.iloc[-2]:
            return TradeSignal(SignalType.BUY, 0.4, "MACD柱增长")
        if hist.iloc[-1] < 0 and hist.iloc[-1] < hist.iloc[-2]:
            return TradeSignal(SignalType.SELL, 0.4, "MACD柱缩短")
        return TradeSignal(SignalType.HOLD)


class KDJStrategy(BaseStrategy):
    """KDJ策略"""

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < 12:
            return TradeSignal(SignalType.HOLD)
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        c = df["close"].astype(float)
        n = 9
        hh = h.rolling(n).max()
        ll = l.rolling(n).min()
        rsv = (c - ll) / (hh - ll) * 100
        rsv = rsv.fillna(50)
        k = rsv.ewm(alpha=1/3, adjust=False).mean()
        d = k.ewm(alpha=1/3, adjust=False).mean()
        j = 3 * k - 2 * d
        if k.iloc[-1] > d.iloc[-1] and k.iloc[-2] <= d.iloc[-2] and k.iloc[-1] < 30:
            return TradeSignal(SignalType.BUY, 0.8, "KDJ低位金叉")
        if k.iloc[-1] < d.iloc[-1] and k.iloc[-2] >= d.iloc[-2] and k.iloc[-1] > 70:
            return TradeSignal(SignalType.SELL, 0.8, "KDJ高位死叉")
        if j.iloc[-1] < 0:
            return TradeSignal(SignalType.BUY, 0.5, "J值超卖")
        if j.iloc[-1] > 100:
            return TradeSignal(SignalType.SELL, 0.5, "J值超买")
        return TradeSignal(SignalType.HOLD)


class BollingerBreakoutStrategy(BaseStrategy):
    """布林带突破策略"""

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < 22:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        mid = c.rolling(20).mean()
        std = c.rolling(20).std()
        upper = mid + 2 * std
        lower = mid - 2 * std
        if c.iloc[-1] <= lower.iloc[-1]:
            return TradeSignal(SignalType.BUY, 0.7, "触及布林下轨")
        if c.iloc[-1] >= upper.iloc[-1]:
            return TradeSignal(SignalType.SELL, 0.7, "触及布林上轨")
        return TradeSignal(SignalType.HOLD)


class MomentumStrategy(BaseStrategy):
    """动量策略"""

    def __init__(self, period: int = 20):
        super().__init__()
        self._period = period

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < self._period + 1:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        ret = (c.iloc[-1] / c.iloc[-self._period] - 1) * 100
        if ret > 5:
            return TradeSignal(SignalType.BUY, min(0.9, ret / 10), f"动量上涨{ret:.1f}%")
        if ret < -5:
            return TradeSignal(SignalType.SELL, min(0.9, abs(ret) / 10), f"动量下跌{ret:.1f}%")
        return TradeSignal(SignalType.HOLD)


class MultiFactorConfluenceStrategy(BaseStrategy):
    """多因子共振策略"""

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < 60:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        score = 0
        reasons = []
        ma5 = c.rolling(5).mean().iloc[-1]
        ma20 = c.rolling(20).mean().iloc[-1]
        ma60 = c.rolling(60).mean().iloc[-1]
        if ma5 > ma20 > ma60:
            score += 0.3
            reasons.append("多头排列")
        elif ma5 < ma20 < ma60:
            score -= 0.3
            reasons.append("空头排列")
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        if dif.iloc[-1] > dea.iloc[-1]:
            score += 0.2
            reasons.append("MACD多头")
        else:
            score -= 0.2
            reasons.append("MACD空头")
        delta = c.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = (100 - 100 / (1 + rs)).iloc[-1]
        if rsi < 30:
            score += 0.3
            reasons.append(f"RSI超卖({rsi:.0f})")
        elif rsi > 70:
            score -= 0.3
            reasons.append(f"RSI超买({rsi:.0f})")
        elif rsi < 50:
            score += 0.1
        else:
            score -= 0.1
        if score >= 0.5:
            return TradeSignal(SignalType.BUY, min(1.0, score), "+".join(reasons))
        if score <= -0.5:
            return TradeSignal(SignalType.SELL, min(1.0, abs(score)), "+".join(reasons))
        return TradeSignal(SignalType.HOLD, abs(score), "多因子中性")


class AdaptiveTrendFollowingStrategy(BaseStrategy):
    """自适应趋势跟踪策略"""

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < 30:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        if atr <= 0 or np.isnan(atr):
            return TradeSignal(SignalType.HOLD)
        hl2 = (h + l) / 2
        upper = hl2 + 3 * tr.rolling(14).mean()
        lower = hl2 - 3 * tr.rolling(14).mean()
        supertrend = lower.copy()
        direction = pd.Series(1, index=df.index)
        for i in range(1, len(df)):
            if c.iloc[i] > supertrend.iloc[i - 1]:
                direction.iloc[i] = 1
                supertrend.iloc[i] = max(lower.iloc[i], supertrend.iloc[i - 1])
            else:
                direction.iloc[i] = -1
                supertrend.iloc[i] = min(upper.iloc[i], supertrend.iloc[i - 1])
        if direction.iloc[-1] == 1 and direction.iloc[-2] == -1:
            return TradeSignal(SignalType.BUY, 0.8, "SuperTrend翻多")
        if direction.iloc[-1] == -1 and direction.iloc[-2] == 1:
            return TradeSignal(SignalType.SELL, 0.8, "SuperTrend翻空")
        if direction.iloc[-1] == 1:
            return TradeSignal(SignalType.BUY, 0.4, "SuperTrend多头")
        return TradeSignal(SignalType.SELL, 0.4, "SuperTrend空头")


class MeanReversionProStrategy(BaseStrategy):
    """均值回归增强策略"""

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < 30:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        ma = c.rolling(20).mean()
        std = c.rolling(20).std()
        z_score = (c - ma) / std.replace(0, np.nan)
        z = z_score.iloc[-1]
        if np.isnan(z):
            return TradeSignal(SignalType.HOLD)
        if z < -2.0:
            return TradeSignal(SignalType.BUY, min(0.9, abs(z) / 3), f"Z-score超卖({z:.2f})")
        if z > 2.0:
            return TradeSignal(SignalType.SELL, min(0.9, z / 3), f"Z-score超买({z:.2f})")
        return TradeSignal(SignalType.HOLD)


class VolatilitySqueezeBreakoutStrategy(BaseStrategy):
    """波动率收缩突破策略"""

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < 25:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        bb_width = c.rolling(20).std() * 4 / c.rolling(20).mean().replace(0, np.nan)
        squeeze = bb_width.iloc[-1] < bb_width.rolling(20).mean().iloc[-1] * 0.6
        if squeeze and c.iloc[-1] > c.rolling(20).mean().iloc[-1]:
            return TradeSignal(SignalType.BUY, 0.7, "波动率收缩向上突破")
        if squeeze and c.iloc[-1] < c.rolling(20).mean().iloc[-1]:
            return TradeSignal(SignalType.SELL, 0.7, "波动率收缩向下突破")
        return TradeSignal(SignalType.HOLD)


class RSIMeanReversionStrategy(BaseStrategy):
    """RSI均值回归策略"""

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < 20:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        delta = c.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)
        rsi_val = rsi.iloc[-1]
        if np.isnan(rsi_val):
            return TradeSignal(SignalType.HOLD)
        if rsi_val < 25:
            return TradeSignal(SignalType.BUY, 0.8, f"RSI深度超卖({rsi_val:.0f})")
        if rsi_val > 75:
            return TradeSignal(SignalType.SELL, 0.8, f"RSI深度超买({rsi_val:.0f})")
        if rsi_val < 35 and rsi.iloc[-2] < rsi.iloc[-1]:
            return TradeSignal(SignalType.BUY, 0.5, "RSI超卖回升")
        if rsi_val > 65 and rsi.iloc[-2] > rsi.iloc[-1]:
            return TradeSignal(SignalType.SELL, 0.5, "RSI超买回落")
        return TradeSignal(SignalType.HOLD)


class SuperTrendStrategy(BaseStrategy):
    """SuperTrend策略"""

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        if len(df) < 30:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(10).mean()
        hl2 = (h + l) / 2
        upper_band = hl2 + 3.0 * atr
        lower_band = hl2 - 3.0 * atr
        n = len(df)
        supertrend = pd.Series(0.0, index=df.index)
        direction = pd.Series(1, index=df.index)
        for i in range(1, n):
            if lower_band.iloc[i] > lower_band.iloc[i - 1] or c.iloc[i - 1] < lower_band.iloc[i - 1]:
                pass
            else:
                lower_band.iloc[i] = lower_band.iloc[i - 1]
            if upper_band.iloc[i] < upper_band.iloc[i - 1] or c.iloc[i - 1] > upper_band.iloc[i - 1]:
                pass
            else:
                upper_band.iloc[i] = upper_band.iloc[i - 1]
            if direction.iloc[i - 1] == 1:
                if c.iloc[i] < lower_band.iloc[i]:
                    direction.iloc[i] = -1
                    supertrend.iloc[i] = upper_band.iloc[i]
                else:
                    direction.iloc[i] = 1
                    supertrend.iloc[i] = lower_band.iloc[i]
            else:
                if c.iloc[i] > upper_band.iloc[i]:
                    direction.iloc[i] = 1
                    supertrend.iloc[i] = lower_band.iloc[i]
                else:
                    direction.iloc[i] = -1
                    supertrend.iloc[i] = upper_band.iloc[i]
        if direction.iloc[-1] == 1 and direction.iloc[-2] == -1:
            return TradeSignal(SignalType.BUY, 0.85, "SuperTrend翻多")
        if direction.iloc[-1] == -1 and direction.iloc[-2] == 1:
            return TradeSignal(SignalType.SELL, 0.85, "SuperTrend翻空")
        return TradeSignal(SignalType.HOLD)


class CompositeStrategy:
    """组合策略"""

    def __init__(self):
        self.strategies = [
            DualMAStrategy(),
            MACDStrategy(),
            KDJStrategy(),
            BollingerBreakoutStrategy(),
            MomentumStrategy(),
            MultiFactorConfluenceStrategy(),
        ]

    def get_strategy_info(self) -> list[dict]:
        return [s.get_info() for s in self.strategies]
