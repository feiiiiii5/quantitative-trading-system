"""
QuantCore 策略模块
提供多种量化策略实现
"""
import logging
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

try:
    from scipy.signal import find_peaks as _find_peaks
except ImportError:
    _find_peaks = None

logger = logging.getLogger(__name__)

__all__ = [
    'SignalType',
    'TradeSignal',
    'StrategyResult',
    'BaseStrategy',
    'DualMAStrategy',
    'MACDStrategy',
    'KDJStrategy',
    'BollingerBreakoutStrategy',
    'MomentumStrategy',
    'MultiFactorConfluenceStrategy',
    'AdaptiveTrendFollowingStrategy',
    'MeanReversionProStrategy',
    'VolatilitySqueezeBreakoutStrategy',
    'RSIMeanReversionStrategy',
    'SuperTrendStrategy',
    'IchimokuCloudStrategy',
    'VWAPDeviationStrategy',
    'OrderFlowImbalanceStrategy',
    'RegimeSwitchingStrategy',
    'FractalBreakoutStrategy',
    'WyckoffAccumulationStrategy',
    'ElliottWaveAIStrategy',
    'MarketMicrostructureStrategy',
    'CopulaCorrelationStrategy',
    'QuantileRegressionStrategy',
    'TurtleTradingStrategy',
    'DualThrustStrategy',
    'ATRChannelBreakoutStrategy',
    'DonchianChannelStrategy',
    'ChandeKrollStopStrategy',
    'VolumeWeightedMACDStrategy',
    'OrnsteinUhlenbeckStrategy',
    'KaufmanAdaptiveStrategy',
    'GARCHVolatilityStrategy',
    'MultiTimeframeMomentumStrategy',
    'ADXTrendStrengthStrategy',
    'ChaikinMoneyFlowStrategy',
    'ParabolicSARStrategy',
    'HurstExponentStrategy',
    'PairsTradingStrategy',
    'CompositeStrategy',
    'MultiFactorScoreStrategy',
    'MomentumRotationStrategy',
    'RegimeAdaptiveStrategy',
    'StrategyRegistry',
    'STRATEGY_REGISTRY',
]


def _safe_divide(
    numerator: np.ndarray | pd.Series | float,
    denominator: np.ndarray | pd.Series | float,
    default: float = 0.0
) -> np.ndarray | pd.Series | float:
    """
    安全除法，避免除零错误

    Args:
        numerator: 被除数
        denominator: 除数
        default: 除零时的默认返回值

    Returns:
        除法结果，如果除零则返回默认值
    """
    if isinstance(denominator, (np.ndarray, pd.Series)):
        safe_den = np.where(np.abs(denominator) > 1e-12, denominator, 1.0)
        result = np.where(np.abs(denominator) > 1e-12, numerator / safe_den, default)
        if isinstance(denominator, pd.Series):
            return pd.Series(result, index=denominator.index)
        return result
    if abs(denominator) > 1e-12:
        return numerator / denominator
    return default


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class TradeSignal:
    signal_type: SignalType
    strength: float = 0.0
    reason: str = ""
    bar_index: int = -1
    position_pct: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0


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
    signals: list = field(default_factory=list)


class BaseStrategy:
    """策略基类 - 支持逐K线迭代和向量化两种模式

    策略可通过两种方式产生信号:
    1. on_bar() — 事件驱动逐bar接口，策略维护内部状态（推荐）
    2. generate_signal() — 向量化接口，接收DataFrame切片（向后兼容）

    on_bar() 是回测引擎和实盘信号的统一入口。默认实现桥接到
    generate_signal()，子类可直接覆盖 on_bar() 实现有状态策略。
    """

    _VERSION = "2.0.0"

    _PARAM_CONSTRAINTS: dict[str, tuple] = {}

    def __init__(self):
        self.name = self.__class__.__name__
        self._param_hash: str = ""
        self._created_at: str = ""
        self._bar_buffer: list[dict] = []
        self._bar_df: pd.DataFrame | None = None
        self._bar_index: int = 0
        self._validate_params()
        self._compute_param_hash()

    def reset(self) -> None:
        """重置策略内部状态，在回测开始前调用"""
        self._bar_buffer = []
        self._bar_df = None
        self._bar_index = 0

    def _validate_params(self) -> None:
        """Validate strategy parameters against defined constraints."""
        if not self._PARAM_CONSTRAINTS:
            return

        for param_name, constraints in self._PARAM_CONSTRAINTS.items():
            min_val, max_val, default_val = constraints
            value = getattr(self, param_name, None)
            if value is None:
                setattr(self, param_name, default_val)
                continue
            if not isinstance(value, (int, float)):
                raise ValueError(f"{self.name}.{param_name} must be numeric, got {type(value).__name__}")
            if value < min_val or value > max_val:
                raise ValueError(
                    f"{self.name}.{param_name}={value} outside valid range [{min_val}, {max_val}]"
                )

    @classmethod
    def get_param_space(cls) -> dict:
        return cls._PARAM_CONSTRAINTS

    def get_params(self) -> dict:
        """Get current parameters."""
        params = {}
        for param_name in self._PARAM_CONSTRAINTS:
            params[param_name] = getattr(self, param_name, None)
        return params

    def set_params(self, **params) -> "BaseStrategy":
        """Set parameters and validate."""
        for param_name, value in params.items():
            if param_name in self._PARAM_CONSTRAINTS:
                setattr(self, param_name, value)
        self._validate_params()
        return self

    def _compute_param_hash(self) -> None:
        import hashlib
        from datetime import datetime

        params = {
            k: v for k, v in self.__dict__.items()
            if k.startswith("_") and not k.startswith("__") and isinstance(v, (int, float, str, bool))
        }

        param_str = str(sorted(params.items()))
        self._param_hash = hashlib.md5(param_str.encode()).hexdigest()[:8]
        self._created_at = datetime.now().strftime("%Y%m%d_%H%M%S")

    def get_param_version(self) -> dict:
        params = {
            k: v for k, v in self.__dict__.items()
            if k.startswith("_") and not k.startswith("__") and isinstance(v, (int, float, str, bool))
        }

        return {
            "strategy": self.name,
            "version": self._VERSION,
            "param_hash": self._param_hash,
            "created_at": self._created_at,
            "params": params,
        }

    def on_bar(self, bar: dict, portfolio: dict) -> list[dict]:
        """事件驱动逐bar接口 — 回测引擎和实盘信号的统一入口

        Args:
            bar: 单根K线数据 {"open":..., "high":..., "low":..., "close":...,
                 "volume":..., "date":..., "symbol":...}
            portfolio: 当前组合状态 {"cash":..., "positions":{...},
                      "total_assets":..., "peak_value":...}

        Returns:
            信号列表 [{"action":"buy"|"sell", "reason":"...", "confidence":0.8,
                      "qty":100, "stop_loss":0, "take_profit":0}]
        """
        self._bar_index += 1

        max_window = int(getattr(self, "_long", 0) or getattr(self, "_period", 0) or 60)
        max_window = max(max_window, 2) + 5

        new_row = pd.DataFrame([bar])
        if self._bar_df is None:
            self._bar_df = new_row
        else:
            self._bar_df = pd.concat([self._bar_df, new_row], ignore_index=True)
            if len(self._bar_df) > max_window:
                self._bar_df = self._bar_df.iloc[-max_window:].reset_index(drop=True)

        min_bars = int(getattr(self, "min_bars", 2))
        if len(self._bar_df) < min_bars:
            return []

        try:
            df = self._bar_df.copy()
            for col in ("open", "high", "low", "close", "volume"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            signal = self._sanitize_signal(self.generate_signal(df))
        except Exception as e:
            logger.debug("%s on_bar bridge failed: %s", self, e)
            return []

        if signal.signal_type == SignalType.HOLD:
            return []

        action = signal.signal_type.value
        confidence = round(float(np.clip(signal.strength, 0, 1)), 2)
        result = {
            "action": action,
            "reason": signal.reason or f"{self.name} {action}",
            "confidence": confidence,
        }
        if signal.stop_loss > 0:
            result["stop_loss"] = round(float(signal.stop_loss), 2)
        if signal.take_profit > 0:
            result["take_profit"] = round(float(signal.take_profit), 2)
        if signal.position_pct > 0:
            result["position_pct"] = round(float(signal.position_pct), 2)
        return [result]

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        raise NotImplementedError

    def _sanitize_signal(self, signal: TradeSignal) -> TradeSignal:
        if not np.isfinite(signal.strength):
            signal.strength = 0.0
        if not np.isfinite(signal.stop_loss):
            signal.stop_loss = 0.0
        if not np.isfinite(signal.take_profit):
            signal.take_profit = 0.0
        if not np.isfinite(signal.position_pct):
            signal.position_pct = 0.0
        return signal

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def populate_entry_exit(self, df: pd.DataFrame) -> pd.DataFrame:
        if "enter_signal" not in df.columns:
            df["enter_signal"] = 0.0
        if "exit_signal" not in df.columns:
            df["exit_signal"] = 0.0
        return df

    def _has_indicator(self, df: pd.DataFrame, name: str) -> bool:
        """检查DataFrame中是否存在指定的指标列"""
        return name in df.columns and len(df[name].dropna()) > 0

    def generate_signals_vectorized(self, df: pd.DataFrame) -> StrategyResult:
        if df is None or len(df) < 2:
            return StrategyResult(strategy_name=self.name, signals=[])

        try:
            df = self.populate_indicators(df.copy())
            df = self.populate_entry_exit(df)
        except Exception as e:
            logger.debug("%s vectorized signal generation failed: %s", self, e)
            return self.generate_signals(df)

        signals = []
        for i in range(len(df)):
            enter = float(df["enter_signal"].iloc[i]) if "enter_signal" in df.columns else 0
            exit_s = float(df["exit_signal"].iloc[i]) if "exit_signal" in df.columns else 0
            if enter > 0.3:
                strength = min(float(np.clip(enter, 0, 1)), 0.95)
                signals.append(TradeSignal(
                    signal_type=SignalType.BUY,
                    strength=strength,
                    reason=f"{self.name} 向量化买入",
                    bar_index=i,
                    position_pct=round(float(np.clip(strength * 0.55, 0.2, 0.65)), 2),
                ))
            elif exit_s > 0.3:
                strength = min(float(np.clip(exit_s, 0, 1)), 0.95)
                signals.append(TradeSignal(
                    signal_type=SignalType.SELL,
                    strength=strength,
                    reason=f"{self.name} 向量化卖出",
                    bar_index=i,
                ))

        return StrategyResult(strategy_name=self.name, signals=signals)

    def generate_score(self, df: pd.DataFrame) -> float:
        signal = self._sanitize_signal(self.generate_signal(df))
        if signal.signal_type == SignalType.BUY:
            return round(float(np.clip(signal.strength, 0, 1)), 2)
        elif signal.signal_type == SignalType.SELL:
            return round(float(-np.clip(signal.strength, 0, 1)), 2)
        return 0.0

    def generate_signals(self, df: pd.DataFrame) -> StrategyResult:
        """逐bar生成信号 — 通过 on_bar() 统一入口

        .. deprecated::
            直接使用 on_bar() 事件驱动接口。此方法仅作为批量回放兼容层保留。
        """
        import warnings
        warnings.warn(
            "generate_signals() is deprecated; use on_bar() event-driven interface instead",
            DeprecationWarning,
            stacklevel=2,
        )
        signals = []
        if df is None or len(df) < 2:
            return StrategyResult(strategy_name=self.name, signals=signals)

        self.reset()

        for i in range(len(df)):
            row = df.iloc[i]
            bar = {
                "open": float(row.get("open", 0)) if pd.notna(row.get("open")) else 0,
                "high": float(row.get("high", 0)) if pd.notna(row.get("high")) else 0,
                "low": float(row.get("low", 0)) if pd.notna(row.get("low")) else 0,
                "close": float(row.get("close", 0)) if pd.notna(row.get("close")) else 0,
                "volume": float(row.get("volume", 0)) if pd.notna(row.get("volume")) else 0,
                "date": str(row.get("date", ""))[:10] if "date" in df.columns else "",
            }
            if "symbol" in df.columns and pd.notna(row.get("symbol")):
                bar["symbol"] = str(row["symbol"])

            sigs = self.on_bar(bar, {})
            for sig in sigs:
                action = sig.get("action", "hold")
                if action not in ("buy", "sell"):
                    continue
                st = SignalType.BUY if action == "buy" else SignalType.SELL
                ts = TradeSignal(
                    signal_type=st,
                    strength=sig.get("confidence", 0.5),
                    reason=sig.get("reason", ""),
                    bar_index=i,
                    position_pct=sig.get("position_pct", 0.0),
                    stop_loss=sig.get("stop_loss", 0.0),
                    take_profit=sig.get("take_profit", 0.0),
                )
                ts.strength = round(float(np.clip(ts.strength, 0, 1)), 2)
                if ts.position_pct <= 0:
                    ts.position_pct = round(float(np.clip(ts.strength * 0.55, 0.2, 0.65)), 2)
                signals.append(ts)

        return StrategyResult(strategy_name=self.name, signals=signals)

    def get_info(self) -> dict:
        base = self.__class__.__base__
        base_name = base.__name__ if base is not None else "Unknown"
        return {
            "name": self.name,
            "type": base_name,
            "version": self._VERSION,
            "param_hash": self._param_hash,
        }


def _safe_float(value, default: float = 0.0) -> float:
    try:
        value = float(value)
        return value if np.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _signal(signal_type: SignalType, strength: float = 0.0, reason: str = "",
            position_pct: float = 0.0) -> TradeSignal:
    return TradeSignal(
        signal_type=signal_type,
        strength=round(float(np.clip(strength, 0, 1)), 2),
        reason=reason,
        position_pct=position_pct,
    )


def _rsi_series(c: pd.Series, period: int = 14) -> pd.Series:
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _compute_supertrend(
    df: pd.DataFrame,
    atr_period: int = 10,
    multiplier: float = 3.0,
) -> tuple[np.ndarray, np.ndarray]:
    """计算SuperTrend指标，返回(supertrend, direction)数组"""
    c = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    tr = pd.concat([high - low, (high - c.shift(1)).abs(), (low - c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(atr_period).mean()
    hl2 = (high + low) / 2
    upper_band = (hl2 + multiplier * atr).values.copy()
    lower_band = (hl2 - multiplier * atr).values.copy()
    n = len(df)
    supertrend = np.zeros(n)
    direction = np.ones(n, dtype=int)
    for i in range(1, n):
        if not (lower_band[i] > lower_band[i - 1] or c.iloc[i - 1] < lower_band[i - 1]):
            lower_band[i] = lower_band[i - 1]
        if not (upper_band[i] < upper_band[i - 1] or c.iloc[i - 1] > upper_band[i - 1]):
            upper_band[i] = upper_band[i - 1]
        if direction[i - 1] == 1:
            if c.iloc[i] < lower_band[i]:
                direction[i] = -1
                supertrend[i] = upper_band[i]
            else:
                direction[i] = 1
                supertrend[i] = lower_band[i]
        else:
            if c.iloc[i] > upper_band[i]:
                direction[i] = 1
                supertrend[i] = lower_band[i]
            else:
                direction[i] = -1
                supertrend[i] = upper_band[i]
    return supertrend, direction


class DualMAStrategy(BaseStrategy):
    """双均线策略"""

    _PARAM_CONSTRAINTS = {
        "short_period": (2, 100, 5),
        "long_period": (5, 500, 20),
    }

    def __init__(self, short_period: int = 5, long_period: int = 20):
        self.short_period = short_period
        self.long_period = long_period
        super().__init__()
        self._short = self.short_period
        self._long = self.long_period

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        c = df["close"].astype(float)
        df[f"ma_{self._short}"] = c.rolling(self._short).mean()
        df[f"ma_{self._long}"] = c.rolling(self._long).mean()
        return df

    def populate_entry_exit(self, df: pd.DataFrame) -> pd.DataFrame:
        ma_s = df[f"ma_{self._short}"]
        ma_l = df[f"ma_{self._long}"]
        golden_cross = (ma_s > ma_l) & (ma_s.shift(1) <= ma_l.shift(1))
        death_cross = (ma_s < ma_l) & (ma_s.shift(1) >= ma_l.shift(1))
        bullish = ma_s > ma_l
        df["enter_signal"] = np.where(golden_cross, 0.7, np.where(bullish & ~golden_cross, 0.3, 0.0))
        df["exit_signal"] = np.where(death_cross, 0.7, np.where(~bullish & ~death_cross, 0.3, 0.0))
        return df

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < self._long + 1:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        ma_col_s = f"ma_{self._short}"
        ma_col_l = f"ma_{self._long}"
        if use_precomputed and self._has_indicator(df, ma_col_s) and self._has_indicator(df, ma_col_l):
            ma_short = df[ma_col_s]
            ma_long = df[ma_col_l]
        else:
            ma_short = c.rolling(self._short).mean()
            ma_long = c.rolling(self._long).mean()
        if ma_short.iloc[-1] > ma_long.iloc[-1] and ma_short.iloc[-2] <= ma_long.iloc[-2]:
            return TradeSignal(SignalType.BUY, 0.7, f"MA{self._short}上穿MA{self._long}")
        if ma_short.iloc[-1] < ma_long.iloc[-1] and ma_short.iloc[-2] >= ma_long.iloc[-2]:
            return TradeSignal(SignalType.SELL, 0.7, f"MA{self._short}下穿MA{self._long}")
        return TradeSignal(SignalType.HOLD)


class MACDStrategy(BaseStrategy):
    """MACD策略"""

    _PARAM_CONSTRAINTS = {
        "fast_period": (5, 30, 12),
        "slow_period": (15, 60, 26),
        "signal_period": (5, 20, 9),
    }

    def __init__(self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        super().__init__()

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        c = df["close"].astype(float)
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        df["dif"] = ema12 - ema26
        df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
        df["hist"] = (df["dif"] - df["dea"]) * 2
        return df

    def populate_entry_exit(self, df: pd.DataFrame) -> pd.DataFrame:
        dif = df["dif"]
        dea = df["dea"]
        hist = df["hist"]
        golden = (dif > dea) & (dif.shift(1) <= dea.shift(1))
        death = (dif < dea) & (dif.shift(1) >= dea.shift(1))
        hist_growing = (hist > 0) & (hist > hist.shift(1))
        hist_shrinking = (hist < 0) & (hist < hist.shift(1))
        df["enter_signal"] = np.where(golden, 0.8, np.where(hist_growing & ~golden, 0.4, 0.0))
        df["exit_signal"] = np.where(death, 0.8, np.where(hist_shrinking & ~death, 0.4, 0.0))
        return df

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < 35:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        if use_precomputed and self._has_indicator(df, "dif") and self._has_indicator(df, "dea"):
            dif = df["dif"]
            dea = df["dea"]
            hist = df["hist"] if self._has_indicator(df, "hist") else (dif - dea) * 2
        else:
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

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        c = df["close"].astype(float)
        n = 9
        hh = high.rolling(n).max()
        ll = low.rolling(n).min()
        denom = hh - ll
        rsv = np.where(denom != 0, (c - ll) / denom * 100, 50.0)
        rsv = pd.Series(rsv, index=df.index).fillna(50)
        df["k"] = rsv.ewm(alpha=1/3, adjust=False).mean()
        df["d"] = df["k"].ewm(alpha=1/3, adjust=False).mean()
        df["j"] = 3 * df["k"] - 2 * df["d"]
        return df

    def populate_entry_exit(self, df: pd.DataFrame) -> pd.DataFrame:
        k = df["k"]
        d = df["d"]
        j = df["j"]
        low_golden = (k > d) & (k.shift(1) <= d.shift(1)) & (k < 30)
        high_death = (k < d) & (k.shift(1) >= d.shift(1)) & (k > 70)
        j_oversold = j < 0
        j_overbought = j > 100
        df["enter_signal"] = np.where(low_golden, 0.8, np.where(j_oversold & ~low_golden, 0.5, 0.0))
        df["exit_signal"] = np.where(high_death, 0.8, np.where(j_overbought & ~high_death, 0.5, 0.0))
        return df

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < 12:
            return TradeSignal(SignalType.HOLD)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        c = df["close"].astype(float)
        if use_precomputed and self._has_indicator(df, "k") and self._has_indicator(df, "d"):
            k = df["k"]
            d = df["d"]
            j = df["j"] if self._has_indicator(df, "j") else 3 * k - 2 * d
        else:
            n = 9
            hh = high.rolling(n).max()
            ll = low.rolling(n).min()
            denom = hh - ll
            rsv = np.where(denom != 0, (c - ll) / denom * 100, 50.0)
            rsv = pd.Series(rsv, index=df.index).fillna(50)
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

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        c = df["close"].astype(float)
        df["bb_mid"] = c.rolling(20).mean()
        std = c.rolling(20).std()
        df["bb_upper"] = df["bb_mid"] + 2 * std
        df["bb_lower"] = df["bb_mid"] - 2 * std
        return df

    def populate_entry_exit(self, df: pd.DataFrame) -> pd.DataFrame:
        c = df["close"].astype(float)
        df["enter_signal"] = np.where(c <= df["bb_lower"], 0.7, 0.0)
        df["exit_signal"] = np.where(c >= df["bb_upper"], 0.7, 0.0)
        return df

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < 22:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        if use_precomputed and self._has_indicator(df, "bb_upper") and self._has_indicator(df, "bb_lower"):
            upper = df["bb_upper"]
            lower = df["bb_lower"]
        else:
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
    """动量策略 - 多周期动量+波动率缩放+加速度确认"""

    def __init__(self, period: int = 20, accel_period: int = 10):
        super().__init__()
        self._period = int(period)
        self._accel_period = int(accel_period)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < self._period + self._accel_period + 1:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)

        m1 = _safe_divide(c.iloc[-1], c.iloc[-self._period], 1.0) - 1
        m1 = m1 * 100 if isinstance(m1, (int, float)) else m1
        m2 = _safe_divide(c.iloc[-1], c.iloc[-self._accel_period], 1.0) - 1
        m2 = m2 * 100 if isinstance(m2, (int, float)) else m2
        accel = m1 - m2 if self._accel_period < self._period else 0

        realized_vol = c.pct_change().rolling(20).std().replace(0, np.nan).iloc[-1]
        target_vol = 0.02
        vol_scale = min(2.0, max(0.3, target_vol / max(_safe_float(realized_vol, 0.02), 0.005)))

        vol_ma = _safe_float(v.rolling(20).mean().iloc[-1])
        vol_ratio = _safe_float(v.iloc[-1]) / max(vol_ma, 1) if vol_ma > 0 else 1.0

        if m1 > 5 and accel > 0 and vol_ratio > 1.0:
            strength = min(0.95, (m1 / 10) * vol_scale)
            return _signal(SignalType.BUY, strength, f"动量加速上涨{m1:.1f}%(加速度={accel:.1f}%)", 0.45 * vol_scale)
        if m1 > 5 and accel < -2:
            return _signal(SignalType.BUY, min(0.6, m1 / 15), f"动量上涨{m1:.1f}%但减速，注意风险")
        if m1 < -5 and accel < 0 and vol_ratio > 1.0:
            strength = min(0.95, (abs(m1) / 10) * vol_scale)
            return _signal(SignalType.SELL, strength, f"动量加速下跌{m1:.1f}%(加速度={accel:.1f}%)")
        if m1 < -5 and accel > 2:
            return _signal(SignalType.SELL, min(0.6, abs(m1) / 15), f"动量下跌{m1:.1f}%但减速，关注反转")
        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"period": {"min": 10, "max": 30, "step": 5}, "accel_period": {"min": 5, "max": 15, "step": 5}}


class MultiFactorConfluenceStrategy(BaseStrategy):
    """多因子共振策略"""

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
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
        rsi = _safe_float(_rsi_series(c, 14).iloc[-1], 50)
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

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < 30:
            return TradeSignal(SignalType.HOLD)
        supertrend, direction = _compute_supertrend(df, atr_period=14, multiplier=3.0)
        c = df["close"].astype(float)
        if direction[-1] == 1 and direction[-2] == -1:
            return TradeSignal(SignalType.BUY, 0.8, "SuperTrend翻多")
        if direction[-1] == -1 and direction[-2] == 1:
            return TradeSignal(SignalType.SELL, 0.8, "SuperTrend翻空")
        if direction[-1] == 1:
            dist = (c.iloc[-1] - supertrend[-1]) / supertrend[-1] if supertrend[-1] > 0 else 0
            strength = min(0.7, 0.3 + abs(dist) * 5)
            return TradeSignal(SignalType.BUY, strength, "SuperTrend多头")
        dist = (supertrend[-1] - c.iloc[-1]) / supertrend[-1] if supertrend[-1] > 0 else 0
        strength = min(0.7, 0.3 + abs(dist) * 5)
        return TradeSignal(SignalType.SELL, strength, "SuperTrend空头")


class MeanReversionProStrategy(BaseStrategy):
    """均值回归增强策略 - 自适应Z-Score + 导数确认"""

    min_bars = 30

    def __init__(self, window: int = 20, entry_z: float = 2.0, exit_z: float = 0.5):
        super().__init__()
        self._window = int(window)
        self._entry_z = float(entry_z)
        self._exit_z = float(exit_z)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < self._window + 5:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        df["high"].astype(float)
        df["low"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)

        realized_vol = c.pct_change().rolling(20).std().replace(0, np.nan)
        long_run_vol = c.pct_change().rolling(60).std().replace(0, np.nan)
        vol_ratio = (realized_vol / long_run_vol).fillna(1.0).iloc[-1]
        adaptive_window = max(10, int(self._window * vol_ratio))

        ma = c.rolling(adaptive_window).mean()
        std = c.rolling(adaptive_window).std()
        z_score = (c - ma) / std.replace(0, np.nan)
        z = _safe_float(z_score.iloc[-1])
        z_prev = _safe_float(z_score.iloc[-2]) if len(z_score) > 1 else 0
        dz = z - z_prev

        adaptive_threshold = self._entry_z + 0.5 * max(0, vol_ratio - 1)

        rsi = _safe_float(_rsi_series(c, 14).iloc[-1], 50)
        vol_ma = _safe_float(v.rolling(20).mean().iloc[-1])
        vol_confirm = vol_ma > 0 and _safe_float(v.iloc[-1]) < vol_ma * 1.5

        bb_width = _safe_float(std.iloc[-1]) * 2 / max(_safe_float(ma.iloc[-1]), 1e-9)
        bb_width_ma = _safe_float((std * 2 / ma.replace(0, np.nan)).rolling(20).mean().iloc[-1])
        is_squeeze = bb_width_ma > 0 and bb_width < bb_width_ma * 0.7

        if z < -adaptive_threshold and dz > 0 and rsi < 40:
            strength = min(0.95, abs(z) / 3)
            if vol_confirm:
                strength = min(0.95, strength + 0.1)
            if is_squeeze:
                strength = min(0.95, strength + 0.1)
            return _signal(SignalType.BUY, strength, f"Z-score超卖回升({z:.2f},dz={dz:.2f})", 0.45)

        if z > adaptive_threshold and dz < 0 and rsi > 60:
            strength = min(0.95, z / 3)
            if vol_confirm:
                strength = min(0.95, strength + 0.1)
            return _signal(SignalType.SELL, strength, f"Z-score超买回落({z:.2f},dz={dz:.2f})")

        if z < -adaptive_threshold and dz <= 0:
            return TradeSignal(SignalType.HOLD, 0.3, f"Z-score超卖但仍在下跌({z:.2f})，等待确认")

        if z > adaptive_threshold and dz >= 0:
            return TradeSignal(SignalType.HOLD, 0.3, f"Z-score超买但仍在上涨({z:.2f})，等待确认")

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"window": {"min": 10, "max": 30, "step": 5}, "entry_z": {"min": 1.5, "max": 3.0, "step": 0.25}}


class VolatilitySqueezeBreakoutStrategy(BaseStrategy):
    """TTM Squeeze波动率收缩突破策略 - BB/KC对比+动量方向确认"""

    min_bars = 25

    def __init__(self, bb_period: int = 20, bb_mult: float = 2.0, kc_period: int = 20, kc_mult: float = 1.5, atr_period: int = 14):
        super().__init__()
        self._bb_period = int(bb_period)
        self._bb_mult = float(bb_mult)
        self._kc_period = int(kc_period)
        self._kc_mult = float(kc_mult)
        self._atr_period = int(atr_period)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < max(self._bb_period, self._kc_period) + 10:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        bb_mid = c.rolling(self._bb_period).mean()
        bb_std = c.rolling(self._bb_period).std()
        bb_upper = bb_mid + self._bb_mult * bb_std
        bb_lower = bb_mid - self._bb_mult * bb_std
        bb_width = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)

        tr = pd.concat([high - low, (high - c.shift(1)).abs(), (low - c.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(self._atr_period).mean()
        kc_mid = c.ewm(span=self._kc_period, adjust=False).mean()
        kc_upper = kc_mid + self._kc_mult * atr
        kc_lower = kc_mid - self._kc_mult * atr
        kc_width = (kc_upper - kc_lower) / kc_mid.replace(0, np.nan)

        squeeze_on = bb_width.iloc[-1] < kc_width.iloc[-1]
        prev_squeeze_on = bb_width.iloc[-2] < kc_width.iloc[-2] if len(bb_width) > 1 else False
        squeeze_fired = prev_squeeze_on and not squeeze_on

        n_lr = min(20, len(c) - 1)
        if n_lr >= 5:
            y = c.iloc[-n_lr:].values
            x = np.arange(n_lr)
            slope = np.polyfit(x, y, 1)[0]
            momentum = slope / max(np.mean(y), 1e-9)
        else:
            momentum = 0.0

        squeeze_score = _safe_float((kc_width.iloc[-1] - bb_width.iloc[-1]) / max(_safe_float(kc_width.iloc[-1]), 1e-9))

        if squeeze_fired and momentum > 0:
            strength = min(0.95, 0.6 + abs(momentum) * 10 + squeeze_score * 0.3)
            return _signal(SignalType.BUY, strength, f"TTM Squeeze释放+动量向上(mom={momentum:.4f})", 0.50)

        if squeeze_fired and momentum < 0:
            strength = min(0.95, 0.6 + abs(momentum) * 10 + squeeze_score * 0.3)
            return _signal(SignalType.SELL, strength, f"TTM Squeeze释放+动量向下(mom={momentum:.4f})")

        if squeeze_on and momentum > 0.003:
            return _signal(SignalType.BUY, 0.45, f"波动率收缩中+动量蓄势(mom={momentum:.4f})", 0.30)

        if squeeze_on and momentum < -0.003:
            return _signal(SignalType.SELL, 0.45, f"波动率收缩中+动量走弱(mom={momentum:.4f})")

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"bb_period": {"min": 15, "max": 25, "step": 5}, "kc_mult": {"min": 1.0, "max": 2.0, "step": 0.25}}


class RSIMeanReversionStrategy(BaseStrategy):
    """RSI均值回归策略"""

    _PARAM_CONSTRAINTS = {
        "rsi_period": (5, 50, 14),
        "oversold": (10, 40, 30),
        "overbought": (60, 90, 70),
    }

    def __init__(self, rsi_period: int = 14, oversold: float = 30, overbought: float = 70):
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        super().__init__()

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < 20:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        rsi_series = _rsi_series(c, 14)
        rsi_val = _safe_float(rsi_series.iloc[-1])
        if np.isnan(rsi_val):
            return TradeSignal(SignalType.HOLD)
        if rsi_val < 25:
            return TradeSignal(SignalType.BUY, 0.8, f"RSI深度超卖({rsi_val:.0f})")
        if rsi_val > 75:
            return TradeSignal(SignalType.SELL, 0.8, f"RSI深度超买({rsi_val:.0f})")
        if rsi_val < 35 and _safe_float(rsi_series.iloc[-2]) < rsi_val:
            return TradeSignal(SignalType.BUY, 0.5, "RSI超卖回升")
        if rsi_val > 65 and _safe_float(rsi_series.iloc[-2]) > rsi_val:
            return TradeSignal(SignalType.SELL, 0.5, "RSI超买回落")
        return TradeSignal(SignalType.HOLD)


class SuperTrendStrategy(BaseStrategy):
    """SuperTrend策略"""

    _PARAM_CONSTRAINTS = {
        "atr_period": (5, 30, 10),
        "multiplier": (1.0, 5.0, 3.0),
    }

    def __init__(self, atr_period: int = 10, multiplier: float = 3.0):
        self.atr_period = atr_period
        self.multiplier = multiplier
        super().__init__()

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < 30:
            return TradeSignal(SignalType.HOLD)
        supertrend, direction = _compute_supertrend(df, atr_period=self.atr_period, multiplier=self.multiplier)
        c = df["close"].astype(float)
        if direction[-1] == 1 and direction[-2] == -1:
            return TradeSignal(SignalType.BUY, 0.85, "SuperTrend翻多")
        if direction[-1] == -1 and direction[-2] == 1:
            return TradeSignal(SignalType.SELL, 0.85, "SuperTrend翻空")
        if direction[-1] == 1:
            dist = (c.iloc[-1] - supertrend[-1]) / supertrend[-1] if supertrend[-1] > 0 else 0
            strength = min(0.7, 0.3 + abs(dist) * 5)
            return TradeSignal(SignalType.BUY, strength, "SuperTrend看多")
        if direction[-1] == -1:
            dist = (supertrend[-1] - c.iloc[-1]) / supertrend[-1] if supertrend[-1] > 0 else 0
            strength = min(0.7, 0.3 + abs(dist) * 5)
            return TradeSignal(SignalType.SELL, strength, "SuperTrend看空")
        return TradeSignal(SignalType.HOLD)


class IchimokuCloudStrategy(BaseStrategy):
    """一目均衡表策略"""

    min_bars = 80

    def __init__(self, tenkan_period: int = 9, kijun_period: int = 26, senkou_b_period: int = 52):
        super().__init__()
        self._tenkan = int(tenkan_period)
        self._kijun = int(kijun_period)
        self._senkou_b = int(senkou_b_period)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._senkou_b + self._kijun + 2:
            return TradeSignal(SignalType.HOLD)

        high = df["high"].astype(float)
        low = df["low"].astype(float)
        c = df["close"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(0, index=df.index)

        def mid_line(high, low, period):
            return (high.rolling(period).max() + low.rolling(period).min()) / 2

        tenkan = mid_line(high, low, self._tenkan)
        kijun = mid_line(high, low, self._kijun)
        senkou_a = ((tenkan + kijun) / 2).shift(self._kijun)
        senkou_b = mid_line(high, low, self._senkou_b).shift(self._kijun)

        last_c = _safe_float(c.iloc[-1])
        prev_c = _safe_float(c.iloc[-2])
        cloud_top = max(_safe_float(senkou_a.iloc[-1]), _safe_float(senkou_b.iloc[-1]))
        cloud_bot = min(_safe_float(senkou_a.iloc[-1]), _safe_float(senkou_b.iloc[-1]))
        prev_cloud_top = max(_safe_float(senkou_a.iloc[-2]), _safe_float(senkou_b.iloc[-2]))

        if cloud_top <= 0 or cloud_bot <= 0:
            return TradeSignal(SignalType.HOLD)

        tk_cross_up = (
            _safe_float(tenkan.iloc[-1]) > _safe_float(kijun.iloc[-1])
            and _safe_float(tenkan.iloc[-2]) <= _safe_float(kijun.iloc[-2])
        )
        chikou_above_price = len(c) > self._kijun and last_c > _safe_float(c.iloc[-self._kijun])
        price_above_cloud = last_c > cloud_top
        price_below_cloud = last_c < cloud_bot

        # 云层变厚且上移，说明趋势支撑正在增强。
        cloud_thickness = abs(_safe_float(senkou_a.iloc[-1]) - _safe_float(senkou_b.iloc[-1]))
        prev_thickness = abs(_safe_float(senkou_a.iloc[-6]) - _safe_float(senkou_b.iloc[-6])) if len(df) > 6 else cloud_thickness
        cloud_confirm = cloud_thickness > prev_thickness and cloud_top > prev_cloud_top

        vol_ma = _safe_float(v.rolling(20).mean().iloc[-1])
        vol_expand = vol_ma > 0 and _safe_float(v.iloc[-1]) > vol_ma * 1.5

        if tk_cross_up and price_above_cloud and chikou_above_price:
            strength = 0.9 + (0.05 if cloud_confirm else 0)
            return _signal(SignalType.BUY, strength, "一目均衡金叉+云上+迟行线确认", 0.55)
        if prev_c <= prev_cloud_top and last_c > cloud_top and vol_expand:
            return _signal(SignalType.BUY, 0.75, "收盘价放量突破云层上沿", 0.45)
        if price_below_cloud:
            return _signal(SignalType.SELL, 0.8, "收盘价跌破云层下沿")
        if price_above_cloud and cloud_confirm:
            return _signal(SignalType.BUY, 0.45, "云层上移且趋势确认", 0.30)
        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {
            "tenkan_period": {"min": 7, "max": 15, "step": 1},
            "kijun_period": {"min": 20, "max": 32, "step": 2},
        }

    def generate_score(self, df: pd.DataFrame) -> float:
        """一目均衡表综合评分 [-1, 1]"""
        if df is None or len(df) < self._senkou_b + self._kijun + 2:
            return 0.0
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        c = df["close"].astype(float)
        def mid_line(high, low, period):
            return (high.rolling(period).max() + low.rolling(period).min()) / 2
        tenkan = mid_line(high, low, self._tenkan)
        kijun = mid_line(high, low, self._kijun)
        senkou_a = ((tenkan + kijun) / 2).shift(self._kijun)
        senkou_b = mid_line(high, low, self._senkou_b).shift(self._kijun)
        last_c = _safe_float(c.iloc[-1])
        cloud_top = max(_safe_float(senkou_a.iloc[-1]), _safe_float(senkou_b.iloc[-1]))
        cloud_bot = min(_safe_float(senkou_a.iloc[-1]), _safe_float(senkou_b.iloc[-1]))
        if cloud_top <= 0:
            return 0.0
        tk_diff = _safe_float(tenkan.iloc[-1]) - _safe_float(kijun.iloc[-1])
        cloud_mid = (cloud_top + cloud_bot) / 2
        price_pos = (last_c - cloud_mid) / max(cloud_top - cloud_bot, 1e-9)
        score = np.clip(tk_diff / max(abs(_safe_float(kijun.iloc[-1])), 1e-9) * 5 + price_pos * 0.3, -1, 1)
        return round(float(score), 2)


class VWAPDeviationStrategy(BaseStrategy):
    """VWAP偏离均值回归策略"""

    min_bars = 35

    def __init__(self, vwap_window: int = 20, sigma_mult: float = 2.5):
        super().__init__()
        self._window = int(vwap_window)
        self._sigma_mult = float(sigma_mult)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._window + 15:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)
        typical = (high + low + c) / 3
        vol_sum = v.rolling(self._window).sum().replace(0, np.nan)
        vwap = (typical * v).rolling(self._window).sum() / vol_sum
        spread = c - vwap
        sigma = spread.rolling(self._window).std().replace(0, np.nan)
        z = _safe_float((spread / sigma).iloc[-1])
        rsi = _safe_float(_rsi_series(c, 14).iloc[-1], 50)
        vol_ma = _safe_float(v.rolling(self._window).mean().iloc[-1])
        vol_not_expand = vol_ma <= 0 or _safe_float(v.iloc[-1]) <= vol_ma * 1.2

        if z < -self._sigma_mult and rsi < 35 and vol_not_expand:
            return _signal(SignalType.BUY, 0.8, f"价格低于VWAP {abs(z):.1f}σ且RSI超卖", 0.45)
        if z > self._sigma_mult and rsi > 65:
            return _signal(SignalType.SELL, 0.8, f"价格高于VWAP {z:.1f}σ且RSI超买")
        if abs(z) <= 0.3:
            return TradeSignal(SignalType.HOLD, 0.6, "价格回归VWAP附近")
        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {
            "vwap_window": {"min": 10, "max": 30, "step": 5},
            "sigma_mult": {"min": 1.5, "max": 3.0, "step": 0.25},
        }

    def generate_score(self, df: pd.DataFrame) -> float:
        """VWAP偏离评分 [-1, 1]"""
        if df is None or len(df) < self._window + 15:
            return 0.0
        c = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)
        typical = (high + low + c) / 3
        vol_sum = v.rolling(self._window).sum().replace(0, np.nan)
        vwap = (typical * v).rolling(self._window).sum() / vol_sum
        spread = c - vwap
        sigma = spread.rolling(self._window).std().replace(0, np.nan)
        z = _safe_float((spread / sigma).iloc[-1])
        if not np.isfinite(z):
            return 0.0
        return round(float(np.clip(-z / self._sigma_mult, -1, 1)), 2)


class OrderFlowImbalanceStrategy(BaseStrategy):
    """订单流失衡策略（日线近似）"""

    min_bars = 25

    def __init__(self, ofi_window: int = 10):
        super().__init__()
        self._window = int(ofi_window)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < 15:
            return TradeSignal(SignalType.HOLD)
        o = df["open"].astype(float) if "open" in df.columns else df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        c = df["close"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)
        spread = (high - low).replace(0, np.nan)

        buy_pressure = np.where(c > o, v * (c - low) / spread, v * (high - c) / spread * 0.5)
        sell_pressure = np.where(c < o, v * (high - c) / spread, v * (c - low) / spread * 0.5)
        buy_pressure = pd.Series(np.nan_to_num(buy_pressure, nan=0.0), index=df.index)
        sell_pressure = pd.Series(np.nan_to_num(sell_pressure, nan=0.0), index=df.index)
        total_vol = v.rolling(self._window).sum().replace(0, np.nan)
        ofi = ((buy_pressure - sell_pressure).rolling(self._window).sum() / total_vol).fillna(0)
        ofi_diff = ofi.diff().fillna(0)
        price_ret_3 = _safe_float(c.iloc[-1] / c.iloc[-4] - 1) if len(c) >= 4 and c.iloc[-4] > 0 else 0

        if _safe_float(ofi.iloc[-1]) > 0.3 and _safe_float(ofi_diff.iloc[-1]) > _safe_float(ofi_diff.iloc[-2]):
            return _signal(SignalType.BUY, 0.7, "订单流失衡向买方加速", 0.40)
        if _safe_float(ofi.iloc[-1]) < -0.3 and _safe_float(ofi_diff.iloc[-1]) < _safe_float(ofi_diff.iloc[-2]):
            return _signal(SignalType.SELL, 0.7, "订单流失衡向卖方加速")
        if price_ret_3 > 0.02 and _safe_float(ofi.iloc[-1]) < _safe_float(ofi.iloc[-4]):
            return _signal(SignalType.SELL, 0.5, "价涨但订单流转弱，反转预警")
        return TradeSignal(SignalType.HOLD)

    def generate_score(self, df: pd.DataFrame) -> float:
        # 基于订单流失衡OFI值评分：ofi>0看多，ofi<0看空，按0.5缩放至[-1,1]
        if df is None or len(df) < 15:
            return 0.0
        o = df["open"].astype(float) if "open" in df.columns else df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        c = df["close"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)
        spread = (high - low).replace(0, np.nan)
        buy_pressure = np.where(c > o, v * (c - low) / spread, v * (high - c) / spread * 0.5)
        sell_pressure = np.where(c < o, v * (high - c) / spread, v * (c - low) / spread * 0.5)
        buy_pressure = pd.Series(np.nan_to_num(buy_pressure, nan=0.0), index=df.index)
        sell_pressure = pd.Series(np.nan_to_num(sell_pressure, nan=0.0), index=df.index)
        total_vol = v.rolling(self._window).sum().replace(0, np.nan)
        ofi = ((buy_pressure - sell_pressure).rolling(self._window).sum() / total_vol).fillna(0)
        ofi_val = _safe_float(ofi.iloc[-1])
        score = ofi_val / 0.5
        return round(float(np.clip(score, -1, 1)), 2)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"ofi_window": {"min": 6, "max": 14, "step": 2}}


class RegimeSwitchingStrategy(BaseStrategy):
    """简化马尔科夫机制转换策略"""

    min_bars = 90
    _hmm_cache: dict = {}

    def __init__(self, window: int = 120, max_iter: int = 50, tol: float = 1e-6):
        super().__init__()
        self._window = int(window)
        self._max_iter = int(max_iter)
        self._tol = float(tol)

    @staticmethod
    def _normal_pdf(x: np.ndarray, mean: float, std: float) -> np.ndarray:
        std = max(float(std), 1e-6)
        z = (x - mean) / std
        return np.exp(-0.5 * z * z) / (std * np.sqrt(2 * np.pi)) + 1e-12

    def _fit_hmm(self, returns: np.ndarray) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
        x = np.asarray(returns, dtype=float)
        x = x[np.isfinite(x)]
        if len(x) < 30:
            return 0, np.array([[0.9, 0.1], [0.1, 0.9]]), np.zeros((len(x), 2)), np.array([0.0, 0.0])

        q25, q75 = np.quantile(x, [0.25, 0.75])
        means = np.array([q75, q25], dtype=float)
        upper = x[x >= np.median(x)]
        lower = x[x < np.median(x)]
        stds = np.array([
            max(np.std(upper), 1e-4) if len(upper) > 1 else 1e-4,
            max(np.std(lower), 1e-4) if len(lower) > 1 else 1e-4,
        ])
        trans = np.array([[0.92, 0.08], [0.12, 0.88]], dtype=float)
        pi = np.array([0.5, 0.5], dtype=float)
        prev_ll = -np.inf

        for _ in range(self._max_iter):
            emit = np.column_stack([
                self._normal_pdf(x, means[0], stds[0]),
                self._normal_pdf(x, means[1], stds[1]),
            ])
            alpha = np.zeros_like(emit)
            scale = np.zeros(len(x))
            alpha[0] = pi * emit[0]
            scale[0] = max(alpha[0].sum(), 1e-12)
            alpha[0] /= scale[0]
            for t in range(1, len(x)):
                alpha[t] = (alpha[t - 1] @ trans) * emit[t]
                scale[t] = max(alpha[t].sum(), 1e-12)
                alpha[t] /= scale[t]

            beta = np.ones_like(emit)
            for t in range(len(x) - 2, -1, -1):
                beta[t] = trans @ (emit[t + 1] * beta[t + 1])
                beta[t] /= max(scale[t + 1], 1e-12)

            gamma = alpha * beta
            gamma /= np.maximum(gamma.sum(axis=1, keepdims=True), 1e-12)

            xi_sum = np.zeros((2, 2))
            for t in range(len(x) - 1):
                xi = alpha[t][:, None] * trans * emit[t + 1][None, :] * beta[t + 1][None, :]
                xi_sum += xi / max(xi.sum(), 1e-12)

            pi = gamma[0]
            trans = xi_sum / np.maximum(gamma[:-1].sum(axis=0)[:, None], 1e-12)
            trans = np.nan_to_num(trans, nan=0.5)
            trans /= np.maximum(trans.sum(axis=1, keepdims=True), 1e-12)
            weights = np.maximum(gamma.sum(axis=0), 1e-12)
            means = (gamma * x[:, None]).sum(axis=0) / weights
            vars_ = (gamma * (x[:, None] - means) ** 2).sum(axis=0) / weights
            stds = np.sqrt(np.maximum(vars_, 1e-8))

            ll = float(np.sum(np.log(scale + 1e-12)))
            if abs(ll - prev_ll) < self._tol:
                break
            prev_ll = ll

        state_score = means - 0.5 * stds
        int(np.argmax(state_score))
        current_state = int(np.argmax(gamma[-1]))
        return current_state, trans, gamma, means

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < 60:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        returns = c.pct_change().replace([np.inf, -np.inf], np.nan).dropna().tail(self._window).values
        if len(returns) < 40:
            return TradeSignal(SignalType.HOLD)
        if np.std(returns) < 0.001:
            return TradeSignal(SignalType.HOLD)

        import time as _time
        cache_key = (len(returns), round(float(returns[-1]), 6), round(float(np.std(returns)), 6))
        cached_entry = self.__class__._hmm_cache.get(cache_key)
        if cached_entry is not None:
            ts_cached, cached_result = cached_entry
            if _time.monotonic() - ts_cached < 60:
                current_state, trans, gamma, means = cached_result
            else:
                del self.__class__._hmm_cache[cache_key]
                current_state, trans, gamma, means = self._fit_hmm(np.clip(returns, -0.12, 0.12))
                self.__class__._hmm_cache[cache_key] = (_time.monotonic(), (current_state, trans, gamma, means))
        else:
            current_state, trans, gamma, means = self._fit_hmm(np.clip(returns, -0.12, 0.12))
            self.__class__._hmm_cache[cache_key] = (_time.monotonic(), (current_state, trans, gamma, means))

        state_score = means - 0.5 * np.std(returns)
        bull_state = int(np.argmax(state_score))
        bear_state = 1 - bull_state
        p_bull_stay = _safe_float(trans[bull_state, bull_state])
        p_bull_to_bear = _safe_float(trans[bull_state, bear_state])

        if current_state == bull_state and p_bull_stay > 0.8:
            return _signal(SignalType.BUY, 0.7, f"低波动牛市状态延续(P={p_bull_stay:.2f})", 0.40)
        if current_state == bear_state and p_bull_to_bear > 0.22:
            return _signal(SignalType.SELL, 0.75, f"高波动熊市/转熊概率上升(P={p_bull_to_bear:.2f})")
        if current_state == bear_state and np.std(returns) > 0.005:
            return _signal(SignalType.SELL, 0.6, f"熊市状态(波动率={np.std(returns):.4f})")
        if len(gamma) > 5 and gamma[-1, bull_state] < gamma[-5, bull_state] - 0.2:
            return _signal(SignalType.SELL, 0.6, "牛市状态概率快速下降")
        return TradeSignal(SignalType.HOLD)

    def generate_score(self, df: pd.DataFrame) -> float:
        # 基于HMM机制转换评分：牛市状态gamma概率映射至[-1,1]，2*gamma_bull-1
        if df is None or len(df) < 60:
            return 0.0
        c = df["close"].astype(float)
        returns = c.pct_change().replace([np.inf, -np.inf], np.nan).dropna().tail(self._window).values
        if len(returns) < 40 or np.std(returns) < 0.001:
            return 0.0
        try:
            current_state, trans, gamma, means = self._fit_hmm(np.clip(returns, -0.12, 0.12))
        except Exception as e:
            logger.debug("HMM拟合失败: %s", e)
            return 0.0
        if gamma is None or len(gamma) == 0:
            return 0.0
        state_score = means - 0.5 * np.std(returns)
        bull_state = int(np.argmax(state_score))
        gamma_bull = _safe_float(gamma[-1, bull_state])
        score = 2 * gamma_bull - 1
        return round(float(np.clip(score, -1, 1)), 2)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"window": {"min": 80, "max": 160, "step": 20}}


class FractalBreakoutStrategy(BaseStrategy):
    """Bill Williams分形突破策略"""

    min_bars = 35

    def __init__(self, lookback: int = 20):
        super().__init__()
        self._lookback = int(lookback)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < 25:
            return TradeSignal(SignalType.HOLD)
        high = df["high"].astype(float).reset_index(drop=True)
        low = df["low"].astype(float).reset_index(drop=True)
        c = df["close"].astype(float).reset_index(drop=True)
        v = df["volume"].astype(float).reset_index(drop=True) if "volume" in df.columns else pd.Series(1, index=c.index)

        highs = high.values
        lows = low.values
        up_fractal = np.zeros(len(df), dtype=bool)
        down_fractal = np.zeros(len(df), dtype=bool)
        if len(df) >= 5:
            mid_high = highs[2:-2]
            mid_low = lows[2:-2]
            up_fractal[2:-2] = (
                (mid_high > highs[:-4]) & (mid_high > highs[1:-3])
                & (mid_high > highs[3:-1]) & (mid_high > highs[4:])
            )
            down_fractal[2:-2] = (
                (mid_low < lows[:-4]) & (mid_low < lows[1:-3])
                & (mid_low < lows[3:-1]) & (mid_low < lows[4:])
            )

        start = max(0, len(df) - self._lookback - 2)
        recent_up = high.iloc[start:-1][up_fractal[start:-1]]
        recent_down = low.iloc[start:-1][down_fractal[start:-1]]
        top_fractal = _safe_float(recent_up.max()) if len(recent_up) else 0
        bot_fractal = _safe_float(recent_down.min()) if len(recent_down) else 0
        vol_ma = _safe_float(v.rolling(20).mean().iloc[-1])
        vol_confirm = vol_ma > 0 and _safe_float(v.iloc[-1]) > vol_ma * 1.5

        ma5 = c.rolling(5).mean()
        ma8 = c.rolling(8).mean()
        ma13 = c.rolling(13).mean()
        alligator_open = (
            _safe_float(ma5.iloc[-1]) > _safe_float(ma8.iloc[-1]) > _safe_float(ma13.iloc[-1])
            and (_safe_float(ma5.iloc[-1]) - _safe_float(ma13.iloc[-1])) / max(_safe_float(c.iloc[-1]), 1) > 0.01
        )

        if top_fractal > 0 and _safe_float(c.iloc[-1]) > top_fractal and vol_confirm:
            strength = 0.75 + (0.1 if alligator_open else 0)
            return _signal(SignalType.BUY, strength, "向上分形被放量突破，鳄鱼线确认" if alligator_open else "向上分形被放量突破", 0.45)
        if bot_fractal > 0 and _safe_float(c.iloc[-1]) < bot_fractal:
            return _signal(SignalType.SELL, 0.75, "向下分形被跌破")
        if alligator_open and top_fractal > 0 and _safe_float(c.iloc[-1]) > top_fractal * 0.98:
            return _signal(SignalType.BUY, 0.45, "价格贴近向上分形且鳄鱼线张口", 0.30)
        return TradeSignal(SignalType.HOLD)

    def generate_score(self, df: pd.DataFrame) -> float:
        # 基于分形突破评分：价格在上下分形间的位置映射至[-1,1]
        if df is None or len(df) < 25:
            return 0.0
        high = df["high"].astype(float).reset_index(drop=True)
        low = df["low"].astype(float).reset_index(drop=True)
        c = df["close"].astype(float).reset_index(drop=True)
        highs = high.values
        lows = low.values
        up_fractal = np.zeros(len(df), dtype=bool)
        down_fractal = np.zeros(len(df), dtype=bool)
        if len(df) >= 5:
            mid_high = highs[2:-2]
            mid_low = lows[2:-2]
            up_fractal[2:-2] = (
                (mid_high > highs[:-4]) & (mid_high > highs[1:-3])
                & (mid_high > highs[3:-1]) & (mid_high > highs[4:])
            )
            down_fractal[2:-2] = (
                (mid_low < lows[:-4]) & (mid_low < lows[1:-3])
                & (mid_low < lows[3:-1]) & (mid_low < lows[4:])
            )
        start = max(0, len(df) - self._lookback - 2)
        recent_up = high.iloc[start:-1][up_fractal[start:-1]]
        recent_down = low.iloc[start:-1][down_fractal[start:-1]]
        top_fractal = _safe_float(recent_up.max()) if len(recent_up) else 0
        bot_fractal = _safe_float(recent_down.min()) if len(recent_down) else 0
        if top_fractal == 0 and bot_fractal == 0:
            return 0.0
        last_close = _safe_float(c.iloc[-1])
        fractal_range = top_fractal - bot_fractal
        if abs(fractal_range) < 1e-9:
            return 0.0
        score = 2 * (last_close - bot_fractal) / fractal_range - 1
        return round(float(np.clip(score, -1, 1)), 2)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"lookback": {"min": 15, "max": 30, "step": 5}}


class WyckoffAccumulationStrategy(BaseStrategy):
    """威科夫积累阶段策略 - 识别PS/SC/AR/ST/SOS五个阶段"""

    min_bars = 65

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < 60:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)

        window = min(60, len(df) - 1)
        recent_c = c.iloc[-window:]
        recent_l = low.iloc[-window:]
        recent_h = high.iloc[-window:]
        recent_v = v.iloc[-window:]

        vol_ma = _safe_float(recent_v.rolling(20).mean().iloc[-1])
        last_vol = _safe_float(recent_v.iloc[-1])
        vol_ratio = last_vol / vol_ma if vol_ma > 0 else 1.0

        # SC阶段：价格创新低+成交量暴增+下影线>实体2倍
        last_close = _safe_float(recent_c.iloc[-1])
        last_low = _safe_float(recent_l.iloc[-1])
        _safe_float(recent_h.iloc[-1])
        body = abs(last_close - _safe_float(recent_c.iloc[-2]))
        lower_shadow = _safe_float(min(recent_c.iloc[-1], recent_c.iloc[-2])) - last_low
        is_sc = (
            last_close <= _safe_float(recent_c.rolling(20).min().iloc[-1])
            and vol_ratio > 3.0
            and lower_shadow > body * 2
        )

        # AR高点：SC后反弹的最高价
        low_20 = _safe_float(recent_l.rolling(20).min().iloc[-1])
        ar_high = _safe_float(recent_h.iloc[-5:].max())

        # SOS阶段：价格突破AR高点+成交量确认
        is_sos = last_close > ar_high and vol_ratio > 1.2

        # 跌破SC低点
        if last_close < low_20:
            return _signal(SignalType.SELL, 0.9, "价格跌破SC低点，威科夫派发")

        if is_sos:
            return _signal(SignalType.BUY, 0.85, "威科夫SOS阶段：力量显现，突破AR高点")

        if is_sc:
            return _signal(SignalType.BUY, 0.7, "威科夫SC阶段：抛售高潮，关注买入")

        return TradeSignal(SignalType.HOLD)

    def generate_score(self, df: pd.DataFrame) -> float:
        # 基于威科夫阶段评分：SOS=0.85，SC=0.7，跌破SC低点=-0.9，否则按20日价格区间位置映射
        if df is None or len(df) < 60:
            return 0.0
        c = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)
        window = min(60, len(df) - 1)
        recent_c = c.iloc[-window:]
        recent_l = low.iloc[-window:]
        recent_h = high.iloc[-window:]
        recent_v = v.iloc[-window:]
        vol_ma = _safe_float(recent_v.rolling(20).mean().iloc[-1])
        last_vol = _safe_float(recent_v.iloc[-1])
        vol_ratio = last_vol / vol_ma if vol_ma > 0 else 1.0
        last_close = _safe_float(recent_c.iloc[-1])
        last_low = _safe_float(recent_l.iloc[-1])
        body = abs(last_close - _safe_float(recent_c.iloc[-2]))
        lower_shadow = _safe_float(min(recent_c.iloc[-1], recent_c.iloc[-2])) - last_low
        is_sc = (
            last_close <= _safe_float(recent_c.rolling(20).min().iloc[-1])
            and vol_ratio > 3.0
            and lower_shadow > body * 2
        )
        low_20 = _safe_float(recent_l.rolling(20).min().iloc[-1])
        ar_high = _safe_float(recent_h.iloc[-5:].max())
        is_sos = last_close > ar_high and vol_ratio > 1.2
        if last_close < low_20:
            return -0.9
        if is_sos:
            return 0.85
        if is_sc:
            return 0.7
        high_20 = _safe_float(recent_h.rolling(20).max().iloc[-1])
        price_range = high_20 - low_20
        if abs(price_range) < 1e-9:
            return 0.0
        score = 2 * (last_close - low_20) / price_range - 1
        return round(float(np.clip(score, -1, 1)), 2)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"window": {"min": 40, "max": 80, "step": 10}}


class ElliottWaveAIStrategy(BaseStrategy):
    """简化艾略特波浪策略 - 用波峰波谷识别5浪/ABC结构"""

    min_bars = 130

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < 120:
            return TradeSignal(SignalType.HOLD)
        if _find_peaks is None:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float).reset_index(drop=True)
        v = df["volume"].astype(float).reset_index(drop=True) if "volume" in df.columns else pd.Series(1, index=c.index)
        prices = c.values

        try:
            peaks, _ = _find_peaks(prices, distance=5, prominence=prices.std() * 0.3)
            troughs, _ = _find_peaks(-prices, distance=5, prominence=prices.std() * 0.3)
        except ValueError:
            return TradeSignal(SignalType.HOLD)

        if len(peaks) < 3 or len(troughs) < 3:
            return TradeSignal(SignalType.HOLD)

        # 合并波峰波谷并按位置排序
        pivots = sorted(
            [(int(p), float(prices[p]), "peak") for p in peaks[-6:]] +
            [(int(t), float(prices[t]), "trough") for t in troughs[-6:]],
            key=lambda x: x[0],
        )

        if len(pivots) < 5:
            return TradeSignal(SignalType.HOLD)

        # 检查5浪上升结构
        last_5 = pivots[-5:]
        is_impulse_up = (
            last_5[0][2] == "trough" and last_5[1][2] == "peak" and
            last_5[2][2] == "trough" and last_5[3][2] == "peak" and
            last_5[4][2] == "trough" and
            last_5[1][1] > last_5[0][1] and
            last_5[3][1] > last_5[1][1] and
            last_5[2][1] > last_5[0][1]
        )

        # 检查第3浪初期（最强上升浪）
        if is_impulse_up and len(pivots) >= 3:
            last_pivot = pivots[-1]
            prev_pivot = pivots[-2]
            if last_pivot[2] == "trough" and prev_pivot[2] == "peak":
                wave3_ratio = prev_pivot[1] / max(last_5[0][1], 1e-9)
                if 1.618 < wave3_ratio < 4.236:
                    return _signal(SignalType.BUY, 0.9, "艾略特第3浪初期，最强上升浪")

        # 第5浪末期：RSI背离+成交量萎缩
        rsi = _safe_float(_rsi_series(c, 14).iloc[-1], 50)
        vol_ma = _safe_float(v.rolling(20).mean().iloc[-1])
        vol_shrink = vol_ma > 0 and _safe_float(v.iloc[-1]) < vol_ma * 0.7

        if is_impulse_up and rsi > 70 and vol_shrink:
            return _signal(SignalType.SELL, 0.85, "艾略特第5浪末期，RSI背离+量缩")

        # ABC调整浪C浪末端
        if len(pivots) >= 3:
            last_3 = pivots[-3:]
            if (last_3[0][2] == "peak" and last_3[1][2] == "trough" and
                    last_3[2][2] == "peak" and rsi < 35):
                return _signal(SignalType.BUY, 0.7, "ABC调整浪C浪末端，超卖买入")

        return TradeSignal(SignalType.HOLD)

    def generate_score(self, df: pd.DataFrame) -> float:
        # 基于艾略特波浪位置评分：第3浪初期=0.9，第5浪末期=-0.85，ABC C浪末端=0.7，否则按枢轴趋势方向
        if df is None or len(df) < 120:
            return 0.0
        c = df["close"].astype(float).reset_index(drop=True)
        prices = c.values
        try:
            if _find_peaks is None:
                return 0.0
            peaks, _ = _find_peaks(prices, distance=5, prominence=prices.std() * 0.3)
            troughs, _ = _find_peaks(-prices, distance=5, prominence=prices.std() * 0.3)
        except ValueError:
            return 0.0
        if len(peaks) < 3 or len(troughs) < 3:
            return 0.0
        pivots = sorted(
            [(int(p), float(prices[p]), "peak") for p in peaks[-6:]] +
            [(int(t), float(prices[t]), "trough") for t in troughs[-6:]],
            key=lambda x: x[0],
        )
        if len(pivots) < 5:
            return 0.0
        last_5 = pivots[-5:]
        is_impulse_up = (
            last_5[0][2] == "trough" and last_5[1][2] == "peak" and
            last_5[2][2] == "trough" and last_5[3][2] == "peak" and
            last_5[4][2] == "trough" and
            last_5[1][1] > last_5[0][1] and
            last_5[3][1] > last_5[1][1] and
            last_5[2][1] > last_5[0][1]
        )
        if is_impulse_up and len(pivots) >= 3:
            last_pivot = pivots[-1]
            prev_pivot = pivots[-2]
            if last_pivot[2] == "trough" and prev_pivot[2] == "peak":
                wave3_ratio = prev_pivot[1] / max(last_5[0][1], 1e-9)
                if 1.618 < wave3_ratio < 4.236:
                    return 0.9
        v = df["volume"].astype(float).reset_index(drop=True) if "volume" in df.columns else pd.Series(1, index=c.index)
        rsi = _safe_float(_rsi_series(c, 14).iloc[-1], 50)
        vol_ma = _safe_float(v.rolling(20).mean().iloc[-1])
        vol_shrink = vol_ma > 0 and _safe_float(v.iloc[-1]) < vol_ma * 0.7
        if is_impulse_up and rsi > 70 and vol_shrink:
            return -0.85
        if len(pivots) >= 3:
            last_3 = pivots[-3:]
            if (last_3[0][2] == "peak" and last_3[1][2] == "trough" and
                    last_3[2][2] == "peak" and rsi < 35):
                return 0.7
        if len(pivots) >= 2:
            if pivots[-1][2] == "peak" and pivots[-2][2] == "trough":
                return 0.3
            if pivots[-1][2] == "trough" and pivots[-2][2] == "peak":
                return -0.3
        return 0.0

    @classmethod
    def get_param_space(cls) -> dict:
        return {"min_bars": {"min": 100, "max": 160, "step": 20}}


class MarketMicrostructureStrategy(BaseStrategy):
    """市场微观结构策略 - 用日线近似Amihud非流动性和价格冲击"""

    min_bars = 30

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < 25:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)
        df["open"].astype(float) if "open" in df.columns else c

        # Amihud非流动性比率：|收益率|/成交额，滚动20日均值
        returns = c.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0)
        amount = v * c
        illiq = (returns.abs() / amount.replace(0, np.nan)).rolling(20).mean().fillna(0)
        illiq_mean = _safe_float(illiq.rolling(60).mean().iloc[-1]) if len(illiq) >= 60 else _safe_float(illiq.mean())
        illiq_current = _safe_float(illiq.iloc[-1])

        # 非流动性突然下降（流动性改善）且价格上涨
        liquidity_improve = illiq_mean > 0 and illiq_current < illiq_mean * 0.7
        price_up = _safe_float(returns.iloc[-1]) > 0

        if liquidity_improve and price_up:
            return _signal(SignalType.BUY, 0.65, "流动性改善且价格上涨")

        # 价格冲击系数：大成交量对应的价格变动幅度
        spread = high - low
        impact = (spread / v.replace(0, np.nan)).rolling(10).mean().fillna(0)
        impact_diff = impact.diff().fillna(0)

        # 连续3日冲击系数下降+价格上行 → 机构吸筹
        if len(impact_diff) >= 3:
            impact_declining = all(_safe_float(impact_diff.iloc[-i]) < 0 for i in range(1, 4))
            if impact_declining and price_up:
                return _signal(SignalType.BUY, 0.75, "冲击系数连续下降+价格上行，机构吸筹信号")

        return TradeSignal(SignalType.HOLD)

    def generate_score(self, df: pd.DataFrame) -> float:
        # 基于市场微观结构评分：流动性改善+价格上涨→0.65，冲击系数下降+价格上行→0.75，按非流动性比率缩放
        if df is None or len(df) < 25:
            return 0.0
        c = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)
        returns = c.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0)
        amount = v * c
        illiq = (returns.abs() / amount.replace(0, np.nan)).rolling(20).mean().fillna(0)
        illiq_mean = _safe_float(illiq.rolling(60).mean().iloc[-1]) if len(illiq) >= 60 else _safe_float(illiq.mean())
        illiq_current = _safe_float(illiq.iloc[-1])
        liquidity_improve = illiq_mean > 0 and illiq_current < illiq_mean * 0.7
        price_up = _safe_float(returns.iloc[-1]) > 0
        spread = high - low
        impact = (spread / v.replace(0, np.nan)).rolling(10).mean().fillna(0)
        impact_diff = impact.diff().fillna(0)
        impact_declining = False
        if len(impact_diff) >= 3:
            impact_declining = all(_safe_float(impact_diff.iloc[-i]) < 0 for i in range(1, 4))
        if liquidity_improve and price_up:
            illiq_ratio = illiq_current / illiq_mean if illiq_mean > 0 else 1.0
            score = 0.65 * (1 - illiq_ratio)
            return round(float(np.clip(score, -1, 1)), 2)
        if impact_declining and price_up:
            illiq_ratio = illiq_current / illiq_mean if illiq_mean > 0 else 1.0
            score = 0.75 * (1 - illiq_ratio)
            return round(float(np.clip(score, -1, 1)), 2)
        return 0.0

    @classmethod
    def get_param_space(cls) -> dict:
        return {"illiq_window": {"min": 15, "max": 30, "step": 5}}


class CopulaCorrelationStrategy(BaseStrategy):
    """Copula相关性策略 - 用秩相关检测与基准的偏离"""

    min_bars = 75

    def __init__(self, corr_window: int = 60, threshold: float = 0.3):
        super().__init__()
        self._window = int(corr_window)
        self._threshold = float(threshold)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._window + 5:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)

        bench = df["benchmark_close"].astype(float) if "benchmark_close" in df.columns else c.rolling(60).mean()

        stock_ret = c.pct_change().dropna()
        bench_ret = bench.pct_change().dropna()
        n = min(len(stock_ret), len(bench_ret))
        if n < self._window:
            return TradeSignal(SignalType.HOLD)

        stock_recent = stock_ret.iloc[-self._window:].values
        bench_recent = bench_ret.iloc[-self._window:].values

        if np.std(stock_recent) < 1e-10 or np.std(bench_recent) < 1e-10:
            return TradeSignal(SignalType.HOLD)

        try:
            from scipy.stats import spearmanr
            with np.errstate(invalid='ignore'):
                corr, _ = spearmanr(stock_recent, bench_recent)
            if not np.isfinite(corr):
                corr = 0.0
        except Exception as e:
            logger.debug("CopulaCorrelation correlation error: %s", e)
            corr = 0.0
        hist_corrs = []
        step = max(20, self._window // 3)
        for i in range(step, n, step):
            try:
                seg_corr, _ = spearmanr(stock_recent[:i], bench_recent[:i])
                if np.isfinite(seg_corr):
                    hist_corrs.append(seg_corr)
            except Exception as e:
                logger.debug("CopulaCorrelation hist_corr error: %s", e)
        hist_mean = np.mean(hist_corrs) if hist_corrs else 0.0

        # 个股相对强弱
        stock_cum = (1 + stock_recent).prod()
        bench_cum = (1 + bench_recent).prod()
        stock_stronger = stock_cum > bench_cum

        # 相关性骤降且个股强于基准
        if abs(corr - hist_mean) > self._threshold and stock_stronger:
            return _signal(SignalType.BUY, 0.75, f"相关性骤降(Δ={abs(corr - hist_mean):.2f})且个股强于基准")

        # 相关性骤升+个股弱于基准
        if (corr - hist_mean) > self._threshold and not stock_stronger:
            return _signal(SignalType.SELL, 0.7, "相关性骤升且个股弱于基准")

        return TradeSignal(SignalType.HOLD)

    def generate_score(self, df: pd.DataFrame) -> float:
        # 基于相关性偏离和相对强弱评分：相关性骤降+个股强→正分，相关性骤升+个股弱→负分
        if df is None or len(df) < self._window + 5:
            return 0.0
        c = df["close"].astype(float)
        bench = df["benchmark_close"].astype(float) if "benchmark_close" in df.columns else c.rolling(60).mean()
        stock_ret = c.pct_change().dropna()
        bench_ret = bench.pct_change().dropna()
        n = min(len(stock_ret), len(bench_ret))
        if n < self._window:
            return 0.0
        stock_recent = stock_ret.iloc[-self._window:].values
        bench_recent = bench_ret.iloc[-self._window:].values
        if np.std(stock_recent) < 1e-10 or np.std(bench_recent) < 1e-10:
            return 0.0
        try:
            from scipy.stats import spearmanr
            with np.errstate(invalid='ignore'):
                corr, _ = spearmanr(stock_recent, bench_recent)
            if not np.isfinite(corr):
                corr = 0.0
        except Exception as e:
            logger.debug("Spearman相关计算失败: %s", e)
            corr = 0.0
        hist_corrs = []
        step = max(20, self._window // 3)
        for i in range(step, n, step):
            try:
                seg_corr, _ = spearmanr(stock_recent[:i], bench_recent[:i])
                if np.isfinite(seg_corr):
                    hist_corrs.append(seg_corr)
            except Exception as e:
                logger.debug("分段相关计算失败: %s", e)
                pass
        hist_mean = np.mean(hist_corrs) if hist_corrs else 0.0
        stock_cum = (1 + stock_recent).prod()
        bench_cum = (1 + bench_recent).prod()
        stock_stronger = stock_cum > bench_cum
        corr_deviation = corr - hist_mean
        if abs(corr_deviation) > self._threshold and stock_stronger:
            score = min(abs(corr_deviation) / self._threshold, 1.0)
            return round(float(np.clip(score, -1, 1)), 2)
        if corr_deviation > self._threshold and not stock_stronger:
            score = -min(corr_deviation / self._threshold, 1.0)
            return round(float(np.clip(score, -1, 1)), 2)
        return 0.0

    @classmethod
    def get_param_space(cls) -> dict:
        return {"corr_window": {"min": 40, "max": 80, "step": 10}}


class QuantileRegressionStrategy(BaseStrategy):
    """分位数回归策略 - 用τ=0.1/0.5/0.9分位线识别超买超卖"""

    min_bars = 75

    def __init__(self, window: int = 60):
        super().__init__()
        self._window = int(window)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._window + 5:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float).reset_index(drop=True)
        prices = c.values
        len(prices)

        # 向量化滚动分位数计算，替代O(n*window)的for循环
        s = pd.Series(prices)
        q10 = s.rolling(self._window, min_periods=10).quantile(0.1).values
        q50 = s.rolling(self._window, min_periods=10).quantile(0.5).values
        q90 = s.rolling(self._window, min_periods=10).quantile(0.9).values

        last_price = _safe_float(prices[-1])
        last_q10 = _safe_float(q10[-1])
        last_q50 = _safe_float(q50[-1])
        last_q90 = _safe_float(q90[-1])

        if last_q10 <= 0 or last_q50 <= 0 or last_q90 <= 0:
            return TradeSignal(SignalType.HOLD)

        # 中位数线斜率（趋势方向）
        slope = (q50[-1] - q50[-5]) / max(abs(q50[-5]), 1e-09) if len(q50) > 5 and not np.isnan(q50[-5]) else 0.0

        # 价格跌破τ=0.1分位线且斜率为正 → 超跌买入
        if last_price < last_q10 and slope > 0:
            return _signal(SignalType.BUY, 0.8, "价格跌破10%分位线且趋势向上，超跌买入")

        # 价格超过τ=0.9分位线且斜率放缓 → 超买卖出
        if last_price > last_q90 and slope < 0.01:
            return _signal(SignalType.SELL, 0.75, "价格超过90%分位线且斜率放缓，超买卖出")

        # 中位数线方向代表趋势强度
        if slope > 0.02 and last_price > last_q50:
            return _signal(SignalType.BUY, 0.35, "分位数趋势向上且价格在中位数上方")

        if slope < -0.02 and last_price < last_q50:
            return _signal(SignalType.SELL, 0.35, "分位数趋势向下且价格在中位数下方")

        return TradeSignal(SignalType.HOLD)

    def generate_score(self, df: pd.DataFrame) -> float:
        # 基于分位数回归评分：价格在q10-q90分位带中的位置映射至[-1,1]
        if df is None or len(df) < self._window + 5:
            return 0.0
        c = df["close"].astype(float).reset_index(drop=True)
        prices = c.values
        s = pd.Series(prices)
        q10 = s.rolling(self._window, min_periods=10).quantile(0.1).values
        q50 = s.rolling(self._window, min_periods=10).quantile(0.5).values
        q90 = s.rolling(self._window, min_periods=10).quantile(0.9).values
        last_price = _safe_float(prices[-1])
        last_q10 = _safe_float(q10[-1])
        last_q50 = _safe_float(q50[-1])
        last_q90 = _safe_float(q90[-1])
        if last_q10 <= 0 or last_q50 <= 0 or last_q90 <= 0:
            return 0.0
        band_width = last_q90 - last_q10
        if abs(band_width) < 1e-9:
            return 0.0
        score = (last_price - last_q50) / band_width
        return round(float(np.clip(score, -1, 1)), 2)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"window": {"min": 40, "max": 80, "step": 10}}


class TurtleTradingStrategy(BaseStrategy):
    """海龟交易策略 - 经典唐奇安通道突破+ATR仓位管理"""

    min_bars = 30

    def __init__(self, entry_window: int = 20, exit_window: int = 10, atr_period: int = 20, risk_pct: float = 0.02):
        super().__init__()
        self._entry_window = int(entry_window)
        self._exit_window = int(exit_window)
        self._atr_period = int(atr_period)
        self._risk_pct = float(risk_pct)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._entry_window + 5:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float).reset_index(drop=True)
        high = df["high"].astype(float).reset_index(drop=True)
        low = df["low"].astype(float).reset_index(drop=True)

        entry_high = high.iloc[-self._entry_window - 1:-1].max()
        entry_low = low.iloc[-self._entry_window - 1:-1].min()
        exit_low = low.iloc[-self._exit_window - 1:-1].min()

        last_close = _safe_float(c.iloc[-1])
        prev_close = _safe_float(c.iloc[-2])

        tr = pd.concat([high - low, (high - c.shift(1)).abs(), (low - c.shift(1)).abs()], axis=1).max(axis=1)
        atr = _safe_float(tr.rolling(self._atr_period).mean().iloc[-1])

        if last_close > entry_high and prev_close <= entry_high:
            strength = min(0.95, 0.6 + (last_close - entry_high) / max(atr, 1e-9) * 0.1)
            return _signal(SignalType.BUY, strength, f"海龟突破{self._entry_window}日高点({entry_high:.2f})", 0.50)

        if last_close < exit_low and prev_close >= exit_low:
            return _signal(SignalType.SELL, 0.8, f"海龟跌破{self._exit_window}日低点({exit_low:.2f})")

        if last_close < entry_low and prev_close >= entry_low:
            return _signal(SignalType.SELL, 0.8, f"海龟跌破{self._entry_window}日低点({entry_low:.2f})")

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"entry_window": {"min": 15, "max": 30, "step": 5}, "exit_window": {"min": 7, "max": 15, "step": 2}}


class DualThrustStrategy(BaseStrategy):
    """Dual Thrust策略 - 经典日内突破策略的日线版本"""

    min_bars = 25

    def __init__(self, lookback: int = 4, k1: float = 0.5, k2: float = 0.5):
        super().__init__()
        self._lookback = int(lookback)
        self._k1 = float(k1)
        self._k2 = float(k2)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._lookback + 5:
            return TradeSignal(SignalType.HOLD)
        high = df["high"].astype(float).reset_index(drop=True)
        low = df["low"].astype(float).reset_index(drop=True)
        c = df["close"].astype(float).reset_index(drop=True)
        o = df["open"].astype(float).reset_index(drop=True) if "open" in df.columns else c

        len(df)
        hh = high.iloc[-self._lookback - 1:-1].max()
        hc = c.iloc[-self._lookback - 1:-1].max()
        lc = c.iloc[-self._lookback - 1:-1].min()
        ll = low.iloc[-self._lookback - 1:-1].min()

        range_val = max(hh - lc, hc - ll)
        if range_val <= 0:
            return TradeSignal(SignalType.HOLD)

        last_open = _safe_float(o.iloc[-1])
        last_close = _safe_float(c.iloc[-1])
        prev_close = _safe_float(c.iloc[-2])

        upper_break = last_open + self._k1 * range_val
        lower_break = last_open - self._k2 * range_val

        if last_close > upper_break and prev_close <= upper_break:
            strength = min(0.9, 0.5 + (last_close - upper_break) / range_val * 0.3)
            return _signal(SignalType.BUY, strength, f"Dual Thrust上破({upper_break:.2f})", 0.45)

        if last_close < lower_break and prev_close >= lower_break:
            strength = min(0.9, 0.5 + (lower_break - last_close) / range_val * 0.3)
            return _signal(SignalType.SELL, strength, f"Dual Thrust下破({lower_break:.2f})")

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"lookback": {"min": 3, "max": 7, "step": 1}, "k1": {"min": 0.3, "max": 0.7, "step": 0.1}}


class ATRChannelBreakoutStrategy(BaseStrategy):
    """ATR通道突破策略 - Keltner Channel突破"""

    min_bars = 25

    def __init__(self, ema_period: int = 20, atr_period: int = 14, atr_mult: float = 2.0):
        super().__init__()
        self._ema_period = int(ema_period)
        self._atr_period = int(atr_period)
        self._atr_mult = float(atr_mult)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < max(self._ema_period, self._atr_period) + 5:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        ema = c.ewm(span=self._ema_period, adjust=False).mean()
        tr = pd.concat([high - low, (high - c.shift(1)).abs(), (low - c.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(self._atr_period).mean()

        upper = ema + self._atr_mult * atr
        lower = ema - self._atr_mult * atr

        last_close = _safe_float(c.iloc[-1])
        last_ema = _safe_float(ema.iloc[-1])
        last_upper = _safe_float(upper.iloc[-1])
        last_lower = _safe_float(lower.iloc[-1])
        prev_close = _safe_float(c.iloc[-2])
        prev_upper = _safe_float(upper.iloc[-2])
        prev_lower = _safe_float(lower.iloc[-2])

        if last_close > last_upper and prev_close <= prev_upper:
            return _signal(SignalType.BUY, 0.8, f"ATR通道上轨突破({last_upper:.2f})", 0.45)

        if last_close < last_lower and prev_close >= prev_lower:
            return _signal(SignalType.SELL, 0.8, f"ATR通道下轨突破({last_lower:.2f})")

        if last_close > last_ema and prev_close <= last_ema:
            return _signal(SignalType.BUY, 0.4, "价格回到EMA上方", 0.30)

        if last_close < last_ema and prev_close >= last_ema:
            return _signal(SignalType.SELL, 0.4, "价格回到EMA下方")

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"ema_period": {"min": 10, "max": 30, "step": 5}, "atr_mult": {"min": 1.5, "max": 3.0, "step": 0.25}}


class DonchianChannelStrategy(BaseStrategy):
    """唐奇安通道策略 - 价格突破N日高低点"""

    min_bars = 25

    def __init__(self, upper_period: int = 20, lower_period: int = 20):
        super().__init__()
        self._upper_period = int(upper_period)
        self._lower_period = int(lower_period)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < max(self._upper_period, self._lower_period) + 2:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float).reset_index(drop=True)
        high = df["high"].astype(float).reset_index(drop=True)
        low = df["low"].astype(float).reset_index(drop=True)

        upper_channel = high.iloc[-self._upper_period - 1:-1].max()
        lower_channel = low.iloc[-self._lower_period - 1:-1].min()
        mid_channel = (upper_channel + lower_channel) / 2

        last_close = _safe_float(c.iloc[-1])
        prev_close = _safe_float(c.iloc[-2])

        if last_close > upper_channel and prev_close <= upper_channel:
            return _signal(SignalType.BUY, 0.85, f"突破{self._upper_period}日高点({upper_channel:.2f})", 0.45)

        if last_close < lower_channel and prev_close >= lower_channel:
            return _signal(SignalType.SELL, 0.85, f"跌破{self._lower_period}日低点({lower_channel:.2f})")

        if last_close > mid_channel and prev_close <= mid_channel:
            return _signal(SignalType.BUY, 0.35, "价格回到通道中轨上方", 0.25)

        if last_close < mid_channel and prev_close >= mid_channel:
            return _signal(SignalType.SELL, 0.35, "价格回到通道中轨下方")

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"upper_period": {"min": 10, "max": 30, "step": 5}, "lower_period": {"min": 10, "max": 30, "step": 5}}


class ChandeKrollStopStrategy(BaseStrategy):
    """Chande-Kroll止损策略 - 基于ATR的动态止损追踪"""

    min_bars = 30

    def __init__(self, atr_period: int = 10, atr_mult_first: float = 2.0, atr_mult_second: float = 3.0, lookback: int = 10):
        super().__init__()
        self._atr_period = int(atr_period)
        self._mult1 = float(atr_mult_first)
        self._mult2 = float(atr_mult_second)
        self._lookback = int(lookback)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._atr_period + self._lookback + 5:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float).reset_index(drop=True)
        high = df["high"].astype(float).reset_index(drop=True)
        low = df["low"].astype(float).reset_index(drop=True)

        tr = pd.concat([high - low, (high - c.shift(1)).abs(), (low - c.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(self._atr_period).mean()

        first_high_stop = high - self._mult1 * atr
        first_low_stop = low + self._mult1 * atr

        stop_long = first_high_stop.rolling(self._lookback).min()
        stop_short = first_low_stop.rolling(self._lookback).max()

        last_close = _safe_float(c.iloc[-1])
        last_stop_long = _safe_float(stop_long.iloc[-1])
        last_stop_short = _safe_float(stop_short.iloc[-1])
        prev_close = _safe_float(c.iloc[-2])
        prev_stop_long = _safe_float(stop_long.iloc[-2]) if len(stop_long) > 1 else 0
        prev_stop_short = _safe_float(stop_short.iloc[-2]) if len(stop_short) > 1 else float('inf')

        if prev_close <= prev_stop_long and last_close > last_stop_long:
            return _signal(SignalType.BUY, 0.8, f"突破Chande-Kroll多头止损线({last_stop_long:.2f})", 0.45)

        if prev_close >= prev_stop_short and last_close < last_stop_short:
            return _signal(SignalType.SELL, 0.8, f"跌破Chande-Kroll空头止损线({last_stop_short:.2f})")

        if last_close > last_stop_long:
            return _signal(SignalType.BUY, 0.3, "价格在多头止损线上方", 0.20)

        if last_close < last_stop_short:
            return _signal(SignalType.SELL, 0.3, "价格在空头止损线下方")

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"atr_period": {"min": 7, "max": 14, "step": 1}, "atr_mult_first": {"min": 1.5, "max": 3.0, "step": 0.25}}


class VolumeWeightedMACDStrategy(BaseStrategy):
    """成交量加权MACD策略 - 将成交量融入MACD信号"""

    min_bars = 40

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < 40:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)

        vol_ratio = v / v.rolling(20).mean().replace(0, np.nan)
        vol_ratio = vol_ratio.fillna(1.0)

        weighted_close = c * vol_ratio
        ema12 = weighted_close.ewm(span=12, adjust=False).mean()
        ema26 = weighted_close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        hist = (dif - dea) * 2

        last_dif = _safe_float(dif.iloc[-1])
        last_dea = _safe_float(dea.iloc[-1])
        prev_dif = _safe_float(dif.iloc[-2])
        prev_dea = _safe_float(dea.iloc[-2])
        last_hist = _safe_float(hist.iloc[-1])
        prev_hist = _safe_float(hist.iloc[-2])
        last_vol_ratio = _safe_float(vol_ratio.iloc[-1])

        if last_dif > last_dea and prev_dif <= prev_dea:
            vol_confirm = last_vol_ratio > 1.0
            strength = 0.85 if vol_confirm else 0.6
            reason = f"量价MACD金叉(量比={last_vol_ratio:.1f})" if vol_confirm else "量价MACD金叉(量能不足)"
            return _signal(SignalType.BUY, strength, reason, 0.45 if vol_confirm else 0.30)

        if last_dif < last_dea and prev_dif >= prev_dea:
            vol_confirm = last_vol_ratio > 1.0
            strength = 0.85 if vol_confirm else 0.6
            reason = f"量价MACD死叉(量比={last_vol_ratio:.1f})" if vol_confirm else "量价MACD死叉(量能不足)"
            return _signal(SignalType.SELL, strength, reason)

        if last_hist > 0 and last_hist > prev_hist and last_vol_ratio > 1.2:
            return _signal(SignalType.BUY, 0.45, "量价MACD柱放量增长", 0.25)

        if last_hist < 0 and last_hist < prev_hist and last_vol_ratio > 1.2:
            return _signal(SignalType.SELL, 0.45, "量价MACD柱放量缩短")

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"vol_ma_window": {"min": 10, "max": 30, "step": 5}}


class OrnsteinUhlenbeckStrategy(BaseStrategy):
    """OU过程均值回归策略 - 最大似然估计回归参数+半衰期过滤"""

    min_bars = 60

    def __init__(self, window: int = 60, min_half_life: float = 5, max_half_life: float = 30, entry_sigma: float = 2.0):
        super().__init__()
        self._window = int(window)
        self._min_hl = float(min_half_life)
        self._max_hl = float(max_half_life)
        self._entry_sigma = float(entry_sigma)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._window + 5:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        prices = c.iloc[-self._window:].values
        if len(prices) < 30:
            return TradeSignal(SignalType.HOLD)

        x_t = prices[:-1]
        x_t1 = prices[1:]
        n = len(x_t)
        if n < 10:
            return TradeSignal(SignalType.HOLD)

        x_mean = np.mean(x_t)
        denom = np.sum((x_t - x_mean) ** 2)
        if denom < 1e-12:
            return TradeSignal(SignalType.HOLD)
        beta_hat = np.sum((x_t - x_mean) * (x_t1 - x_mean)) / denom
        alpha_hat = np.mean(x_t1) - beta_hat * np.mean(x_t)

        residuals = x_t1 - (alpha_hat + beta_hat * x_t)
        sigma_eps = np.sqrt(np.mean(residuals ** 2))

        dt = 1.0
        if abs(beta_hat) >= 1.0 or beta_hat <= 0:
            return TradeSignal(SignalType.HOLD)

        kappa = -np.log(beta_hat) / dt
        if kappa <= 0:
            return TradeSignal(SignalType.HOLD)

        mu = _safe_divide(alpha_hat, 1 - beta_hat, 0.0)
        half_life = np.log(2) / kappa

        if half_life < self._min_hl or half_life > self._max_hl:
            return TradeSignal(SignalType.HOLD)

        sigma_eq = sigma_eps / np.sqrt(2 * kappa * dt) if kappa > 0 else sigma_eps
        if sigma_eq <= 0:
            return TradeSignal(SignalType.HOLD)

        current_price = _safe_float(c.iloc[-1])
        z = (current_price - mu) / sigma_eq

        prev_price = _safe_float(c.iloc[-2])
        prev_z = (prev_price - mu) / sigma_eq
        dz = z - prev_z

        if z < -self._entry_sigma and dz > 0:
            strength = min(0.95, abs(z) / 4)
            return _signal(SignalType.BUY, strength, f"OU超卖回升(z={z:.2f},HL={half_life:.1f}d)", 0.45)

        if z > self._entry_sigma and dz < 0:
            strength = min(0.95, z / 4)
            return _signal(SignalType.SELL, strength, f"OU超买回落(z={z:.2f},HL={half_life:.1f}d)")

        if abs(z) > self._entry_sigma * 2:
            if z < 0:
                return TradeSignal(SignalType.HOLD, 0.3, f"OU深度超卖(z={z:.2f})但未回升，等待确认")
            else:
                return TradeSignal(SignalType.HOLD, 0.3, f"OU深度超买(z={z:.2f})但未回落，等待确认")

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"window": {"min": 40, "max": 80, "step": 10}, "entry_sigma": {"min": 1.5, "max": 3.0, "step": 0.25}}


class KaufmanAdaptiveStrategy(BaseStrategy):
    """Kaufman自适应移动平均策略 - 效率比率+KAMA+波动率过滤"""

    min_bars = 35

    def __init__(self, er_period: int = 10, fast_sc: float = 2.0, slow_sc: float = 30.0, er_threshold: float = 0.3):
        super().__init__()
        self._er_period = int(er_period)
        self._fast_sc = float(fast_sc)
        self._slow_sc = float(slow_sc)
        self._er_threshold = float(er_threshold)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._er_period + 10:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float).reset_index(drop=True)
        n = len(c)
        if n < self._er_period + 5:
            return TradeSignal(SignalType.HOLD)

        direction = (c - c.shift(self._er_period)).abs()
        volatility = c.diff().abs().rolling(self._er_period).sum()
        er_series = (direction / volatility.replace(0, np.nan)).fillna(0)

        fast_sc_val = 2.0 / (self._fast_sc + 1.0)
        slow_sc_val = 2.0 / (self._slow_sc + 1.0)

        kama = np.zeros(n)
        kama[self._er_period] = _safe_float(c.iloc[self._er_period])
        er_vals = er_series.values
        c_vals = c.values
        for i in range(self._er_period + 1, n):
            prev_kama = kama[i - 1]
            bar_er = er_vals[i] if i < len(er_vals) else 0.0
            cur_sc = (bar_er * (fast_sc_val - slow_sc_val) + slow_sc_val) ** 2
            kama[i] = prev_kama + cur_sc * (c_vals[i] - prev_kama)

        last_price = _safe_float(c.iloc[-1])
        last_kama = kama[-1]
        prev_price = _safe_float(c.iloc[-2])
        prev_kama = kama[-2]
        er = _safe_float(er_series.iloc[-1])

        if er > self._er_threshold:
            if prev_price <= prev_kama and last_price > last_kama:
                strength = min(0.9, 0.5 + er * 0.4)
                return _signal(SignalType.BUY, strength, f"KAMA金叉(ER={er:.2f}，趋势有效)", 0.45)
            if prev_price >= prev_kama and last_price < last_kama:
                strength = min(0.9, 0.5 + er * 0.4)
                return _signal(SignalType.SELL, strength, f"KAMA死叉(ER={er:.2f}，趋势有效)")
            if last_price > last_kama and er > 0.5:
                return _signal(SignalType.BUY, 0.4, f"价格在KAMA上方且趋势强(ER={er:.2f})", 0.30)
            if last_price < last_kama and er > 0.5:
                return _signal(SignalType.SELL, 0.4, f"价格在KAMA下方且趋势强(ER={er:.2f})")
        else:
            if last_price < last_kama * 0.97:
                return _signal(SignalType.BUY, 0.5, f"震荡市价格偏离KAMA(ER={er:.2f})", 0.35)
            if last_price > last_kama * 1.03:
                return _signal(SignalType.SELL, 0.5, f"震荡市价格偏离KAMA(ER={er:.2f})")

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"er_period": {"min": 5, "max": 15, "step": 2}, "er_threshold": {"min": 0.2, "max": 0.5, "step": 0.05}}


class GARCHVolatilityStrategy(BaseStrategy):
    """GARCH波动率策略 - 基于GARCH(1,1)波动率预测进行仓位管理"""

    min_bars = 60

    def __init__(self, vol_lookback: int = 60, vol_surge_threshold: float = 1.5, vol_drop_threshold: float = 0.7):
        super().__init__()
        self._lookback = int(vol_lookback)
        self._surge_threshold = float(vol_surge_threshold)
        self._drop_threshold = float(vol_drop_threshold)

    def _fit_garch(self, returns: np.ndarray) -> tuple[float, float, float]:
        r = np.asarray(returns, dtype=float)
        r = r[np.isfinite(r)]
        if len(r) < 30:
            return 0.0, 0.0, 0.0

        omega = np.var(r) * 0.1
        alpha = 0.1
        beta = 0.85

        n = len(r)
        sigma2 = np.zeros(n)
        sigma2[0] = omega / (1 - alpha - beta) if (1 - alpha - beta) > 0 else np.var(r)

        for _ in range(5):
            for t in range(1, n):
                sigma2[t] = omega + alpha * r[t - 1] ** 2 + beta * sigma2[t - 1]
            num_omega = np.mean(sigma2[1:] - alpha * r[:-1] ** 2 - beta * sigma2[:-1])
            omega = max(num_omega, 1e-10)
            num_alpha = np.mean(r[:-1] ** 2 * (sigma2[1:] - omega - beta * sigma2[:-1])) / max(np.mean(r[:-1] ** 2 * sigma2[:-1]), 1e-12)
            alpha = max(0.01, min(0.3, num_alpha))
            num_beta = np.mean(sigma2[:-1] * (sigma2[1:] - omega - alpha * r[:-1] ** 2)) / max(np.mean(sigma2[:-1] ** 2), 1e-12)
            beta = max(0.5, min(0.95, num_beta))
            if alpha + beta >= 1.0:
                beta = 0.99 - alpha

        current_vol = np.sqrt(sigma2[-1])
        forecast_5d = np.sqrt(omega / (1 - alpha - beta) + (alpha + beta) ** 4 * (sigma2[-1] - omega / (1 - alpha - beta))) if (1 - alpha - beta) > 0 else current_vol

        return current_vol, forecast_5d, omega / (1 - alpha - beta) if (1 - alpha - beta) > 0 else sigma2[-1]

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._lookback:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        returns = c.pct_change().dropna().tail(self._lookback).values
        if len(returns) < 30:
            return TradeSignal(SignalType.HOLD)

        current_vol, forecast_vol, long_run_vol = self._fit_garch(np.clip(returns, -0.12, 0.12))
        if current_vol <= 0 or forecast_vol <= 0:
            return TradeSignal(SignalType.HOLD)

        vol_ratio = forecast_vol / current_vol
        trend = _safe_float(_safe_divide(c.iloc[-1], c.iloc[-20], 1.0) - 1) if len(c) > 20 else 0

        if vol_ratio > self._surge_threshold:
            if trend > 0:
                return _signal(SignalType.BUY, 0.6, f"波动率飙升+上涨趋势(vol_ratio={vol_ratio:.2f})", 0.30)
            else:
                return _signal(SignalType.SELL, 0.8, f"波动率飙升+下跌趋势(vol_ratio={vol_ratio:.2f})，减仓避险")

        if vol_ratio < self._drop_threshold:
            if trend > 0:
                return _signal(SignalType.BUY, 0.75, f"波动率收缩+上涨趋势(vol_ratio={vol_ratio:.2f})", 0.50)
            elif trend < 0:
                return _signal(SignalType.SELL, 0.5, f"波动率收缩+下跌趋势(vol_ratio={vol_ratio:.2f})")
            else:
                return _signal(SignalType.BUY, 0.4, f"低波动盘整(vol_ratio={vol_ratio:.2f})，布局机会", 0.30)

        if current_vol < long_run_vol * 0.7 and trend > 0:
            return _signal(SignalType.BUY, 0.5, "波动率低于长期均值+上涨趋势", 0.35)

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"vol_lookback": {"min": 40, "max": 80, "step": 10}, "vol_surge_threshold": {"min": 1.2, "max": 2.0, "step": 0.1}}


class MultiTimeframeMomentumStrategy(BaseStrategy):
    """多周期动量融合策略 - 融合短/中/长期动量信号+趋势一致性"""

    min_bars = 60

    def __init__(self, short_period: int = 5, mid_period: int = 20, long_period: int = 60):
        super().__init__()
        self._short = int(short_period)
        self._mid = int(mid_period)
        self._long = int(long_period)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._long + 5:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)

        ret_short = _safe_float(_safe_divide(c.iloc[-1], c.iloc[-self._short], 1.0) - 1)
        ret_mid = _safe_float(_safe_divide(c.iloc[-1], c.iloc[-self._mid], 1.0) - 1)
        ret_long = _safe_float(_safe_divide(c.iloc[-1], c.iloc[-self._long], 1.0) - 1)

        score = 0.0
        reasons = []

        if ret_short > 0:
            score += 0.2
            reasons.append(f"短期动量+{ret_short * 100:.1f}%")
        else:
            score -= 0.2
            reasons.append(f"短期动量{ret_short * 100:.1f}%")

        if ret_mid > 0:
            score += 0.3
            reasons.append(f"中期动量+{ret_mid * 100:.1f}%")
        else:
            score -= 0.3
            reasons.append(f"中期动量{ret_mid * 100:.1f}%")

        if ret_long > 0:
            score += 0.3
            reasons.append(f"长期动量+{ret_long * 100:.1f}%")
        else:
            score -= 0.3
            reasons.append(f"长期动量{ret_long * 100:.1f}%")

        if ret_short > 0 and ret_mid > 0 and ret_long > 0:
            score += 0.2
            reasons.append("三周期共振")
        elif ret_short < 0 and ret_mid < 0 and ret_long < 0:
            score -= 0.2
            reasons.append("三周期共振下跌")

        ma5 = c.rolling(5).mean().iloc[-1]
        ma20 = c.rolling(20).mean().iloc[-1]
        ma60 = c.rolling(60).mean().iloc[-1]
        if _safe_float(ma5) > _safe_float(ma20) > _safe_float(ma60):
            score += 0.15
            reasons.append("均线多头排列")
        elif _safe_float(ma5) < _safe_float(ma20) < _safe_float(ma60):
            score -= 0.15
            reasons.append("均线空头排列")

        vol_ma = _safe_float(v.rolling(20).mean().iloc[-1])
        vol_ratio = _safe_float(v.iloc[-1]) / max(vol_ma, 1) if vol_ma > 0 else 1.0
        if vol_ratio > 1.5:
            score *= 1.2

        if score >= 0.6:
            strength = min(0.95, score)
            return _signal(SignalType.BUY, strength, "+".join(reasons[:3]), 0.45)
        if score <= -0.6:
            strength = min(0.95, abs(score))
            return _signal(SignalType.SELL, strength, "+".join(reasons[:3]))

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"short_period": {"min": 3, "max": 10, "step": 1}, "mid_period": {"min": 15, "max": 30, "step": 5}}


class ADXTrendStrengthStrategy(BaseStrategy):
    """ADX趋势强度策略 - ADX判断趋势强度+DI方向确认"""

    min_bars = 40

    def __init__(self, adx_period: int = 14, adx_threshold: float = 25.0, strong_threshold: float = 40.0):
        super().__init__()
        self._period = int(adx_period)
        self._threshold = float(adx_threshold)
        self._strong_threshold = float(strong_threshold)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._period + 15:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        from core.indicators import calc_adx, calc_atr
        h_arr = high.values
        l_arr = low.values
        c_arr = c.values
        adx_arr = calc_adx(h_arr, l_arr, c_arr, self._period)
        atr_arr = calc_atr(h_arr, l_arr, c_arr, self._period)

        n = len(c)
        pd.concat([high - low, (high - c.shift(1)).abs(), (low - c.shift(1)).abs()], axis=1).max(axis=1)
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        for i in range(1, n):
            up = _safe_float(high.iloc[i]) - _safe_float(high.iloc[i - 1])
            down = _safe_float(low.iloc[i - 1]) - _safe_float(low.iloc[i])
            if up > down and up > 0:
                plus_dm[i] = up
            if down > up and down > 0:
                minus_dm[i] = down

        pd.Series(atr_arr)
        plus_di = np.where(atr_arr > 0, pd.Series(plus_dm).ewm(alpha=1 / self._period, min_periods=self._period).mean().values / atr_arr * 100, 0)
        minus_di = np.where(atr_arr > 0, pd.Series(minus_dm).ewm(alpha=1 / self._period, min_periods=self._period).mean().values / atr_arr * 100, 0)

        adx_val = _safe_float(adx_arr[-1])
        pdi_val = _safe_float(plus_di[-1])
        mdi_val = _safe_float(minus_di[-1])
        prev_adx = _safe_float(adx_arr[-2]) if len(adx_arr) > 1 else 0
        prev_pdi = _safe_float(plus_di[-2]) if len(plus_di) > 1 else 0
        prev_mdi = _safe_float(minus_di[-2]) if len(minus_di) > 1 else 0

        adx_rising = adx_val > prev_adx

        if adx_val > self._strong_threshold and pdi_val > mdi_val and prev_pdi <= prev_mdi:
            return _signal(SignalType.BUY, 0.9, f"强趋势+DI金叉(ADX={adx_val:.1f})", 0.55)

        if adx_val > self._threshold and pdi_val > mdi_val and adx_rising:
            strength = min(0.85, 0.5 + (adx_val - self._threshold) / 30)
            return _signal(SignalType.BUY, strength, f"趋势增强+多头方向(ADX={adx_val:.1f})", 0.45)

        if adx_val > self._strong_threshold and mdi_val > pdi_val and prev_mdi <= prev_pdi:
            return _signal(SignalType.SELL, 0.9, f"强趋势+DI死叉(ADX={adx_val:.1f})")

        if adx_val > self._threshold and mdi_val > pdi_val and adx_rising:
            strength = min(0.85, 0.5 + (adx_val - self._threshold) / 30)
            return _signal(SignalType.SELL, strength, f"趋势增强+空头方向(ADX={adx_val:.1f})")

        if adx_val < self._threshold and adx_val < prev_adx:
            return TradeSignal(SignalType.HOLD, 0.3, f"无趋势(ADX={adx_val:.1f})，等待突破")

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"adx_period": {"min": 10, "max": 20, "step": 2}, "adx_threshold": {"min": 20, "max": 30, "step": 5}}


class ChaikinMoneyFlowStrategy(BaseStrategy):
    """Chaikin资金流策略 - CMF衡量买卖压力+价格确认"""

    min_bars = 30

    def __init__(self, cmf_period: int = 20, cmf_threshold: float = 0.05):
        super().__init__()
        self._period = int(cmf_period)
        self._threshold = float(cmf_threshold)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._period + 5:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)

        spread = high - low
        clv = np.where(spread > 0, ((c - low) - (high - c)) / spread, 0.0)
        mfv = clv * v
        cmf = _safe_divide(pd.Series(mfv).rolling(self._period).sum(), v.rolling(self._period).sum(), 0.0)
        cmf = cmf.fillna(0)

        cmf_val = _safe_float(cmf.iloc[-1])
        cmf_prev = _safe_float(cmf.iloc[-2]) if len(cmf) > 1 else 0
        _safe_float(cmf.rolling(10).mean().iloc[-1]) if len(cmf) >= 10 else cmf_val

        price_up = _safe_float(c.iloc[-1]) > _safe_float(c.iloc[-2])
        vol_ma = _safe_float(v.rolling(20).mean().iloc[-1])
        vol_confirm = vol_ma > 0 and _safe_float(v.iloc[-1]) > vol_ma * 1.3

        if cmf_val > self._threshold and cmf_prev <= self._threshold and price_up:
            strength = 0.8 + (0.1 if vol_confirm else 0)
            return _signal(SignalType.BUY, strength, f"CMF突破零轴上方({cmf_val:.3f})+价格上涨", 0.45)

        if cmf_val < -self._threshold and cmf_prev >= -self._threshold and not price_up:
            strength = 0.8 + (0.1 if vol_confirm else 0)
            return _signal(SignalType.SELL, strength, f"CMF跌破零轴下方({cmf_val:.3f})+价格下跌")

        if cmf_val > self._threshold and cmf_val > cmf_prev and price_up:
            return _signal(SignalType.BUY, 0.6, f"CMF持续走强({cmf_val:.3f})", 0.35)

        if cmf_val < -self._threshold and cmf_val < cmf_prev and not price_up:
            return _signal(SignalType.SELL, 0.6, f"CMF持续走弱({cmf_val:.3f})")

        if abs(cmf_val) < self._threshold * 0.5 and cmf_val > cmf_prev and price_up:
            return _signal(SignalType.BUY, 0.35, "CMF从弱势区回升+价格上涨", 0.25)

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"cmf_period": {"min": 10, "max": 30, "step": 5}, "cmf_threshold": {"min": 0.03, "max": 0.10, "step": 0.01}}


class ParabolicSARStrategy(BaseStrategy):
    """抛物线SAR策略 - 趋势跟踪止损反转系统"""

    min_bars = 25

    def __init__(self, af_start: float = 0.02, af_step: float = 0.02, af_max: float = 0.20):
        super().__init__()
        self._af_start = float(af_start)
        self._af_step = float(af_step)
        self._af_max = float(af_max)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < 10:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float).reset_index(drop=True)
        high = df["high"].astype(float).reset_index(drop=True)
        low = df["low"].astype(float).reset_index(drop=True)
        n = len(c)
        if n < 5:
            return TradeSignal(SignalType.HOLD)

        sar = np.zeros(n)
        af = self._af_start
        is_long = True
        ep = high.iloc[1] if n > 1 else high.iloc[0]
        sar[0] = low.iloc[0]

        for i in range(1, n):
            sar[i] = sar[i - 1] + af * (ep - sar[i - 1])

            if is_long:
                if low.iloc[i] < sar[i]:
                    is_long = False
                    sar[i] = ep
                    af = self._af_start
                    ep = low.iloc[i]
                else:
                    if high.iloc[i] > ep:
                        ep = high.iloc[i]
                        af = min(af + self._af_step, self._af_max)
            else:
                if high.iloc[i] > sar[i]:
                    is_long = True
                    sar[i] = ep
                    af = self._af_start
                    ep = high.iloc[i]
                else:
                    if low.iloc[i] < ep:
                        ep = low.iloc[i]
                        af = min(af + self._af_step, self._af_max)

        last_sar = _safe_float(sar[-1])
        prev_sar = _safe_float(sar[-2]) if n >= 2 else last_sar
        last_close = _safe_float(c.iloc[-1])
        prev_close = _safe_float(c.iloc[-2]) if n >= 2 else last_close

        currently_long = last_close > last_sar
        previously_long = prev_close > prev_sar

        if currently_long and not previously_long:
            return _signal(SignalType.BUY, 0.85, f"Parabolic SAR翻多(SAR={last_sar:.2f})", 0.50)

        if not currently_long and previously_long:
            return _signal(SignalType.SELL, 0.85, f"Parabolic SAR翻空(SAR={last_sar:.2f})")

        if currently_long:
            dist = (last_close - last_sar) / last_close if last_close > 0 else 0
            strength = min(0.7, 0.3 + abs(dist) * 10)
            return _signal(SignalType.BUY, strength, f"SAR多头跟踪(SAR={last_sar:.2f})", 0.30)

        dist = (last_sar - last_close) / last_close if last_close > 0 else 0
        strength = min(0.7, 0.3 + abs(dist) * 10)
        return _signal(SignalType.SELL, strength, f"SAR空头跟踪(SAR={last_sar:.2f})")

    @classmethod
    def get_param_space(cls) -> dict:
        return {"af_start": {"min": 0.01, "max": 0.04, "step": 0.01}, "af_max": {"min": 0.10, "max": 0.30, "step": 0.05}}


class HurstExponentStrategy(BaseStrategy):
    """Hurst指数策略 - 判断价格序列的持续性/反持续性/随机性"""

    min_bars = 100

    def __init__(self, window: int = 100, hurst_persistent: float = 0.6, hurst_anti: float = 0.4):
        super().__init__()
        self._window = int(window)
        self._hurst_persistent = float(hurst_persistent)
        self._hurst_anti = float(hurst_anti)

    def _calc_hurst(self, prices: np.ndarray) -> float:
        if len(prices) < 30:
            return 0.5
        returns = np.diff(np.log(prices))
        returns = returns[np.isfinite(returns)]
        if len(returns) < 20:
            return 0.5

        max_k = min(len(returns) // 2, 50)
        if max_k < 5:
            return 0.5

        rs_list = []
        ns = []
        for k in [10, 20, max_k]:
            if k > len(returns):
                continue
            n_segments = len(returns) // k
            if n_segments < 1:
                continue
            rs_vals = []
            for seg in range(n_segments):
                segment = returns[seg * k:(seg + 1) * k]
                mean_seg = np.mean(segment)
                deviations = np.cumsum(segment - mean_seg)
                r = np.max(deviations) - np.min(deviations)
                s = np.std(segment, ddof=1)
                if s > 0 and np.isfinite(r):
                    rs_vals.append(r / s)
            if rs_vals:
                rs_list.append(np.mean(rs_vals))
                ns.append(k)

        if len(rs_list) < 2:
            return 0.5

        try:
            log_ns = np.log(ns)
            log_rs = np.log(rs_list)
            hurst = np.polyfit(log_ns, log_rs, 1)[0]
            return float(np.clip(hurst, 0.0, 1.0))
        except Exception as e:
            logger.debug("Hurst exponent calculation failed: %s", e)
            return 0.5

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._window:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)

        prices = c.iloc[-self._window:].values
        hurst = self._calc_hurst(prices)

        ret_5 = _safe_float(_safe_divide(c.iloc[-1], c.iloc[-6], 1.0) - 1) if len(c) >= 6 else 0
        ret_20 = _safe_float(_safe_divide(c.iloc[-1], c.iloc[-21], 1.0) - 1) if len(c) >= 21 else 0
        vol_ma = _safe_float(v.rolling(20).mean().iloc[-1])
        vol_confirm = vol_ma > 0 and _safe_float(v.iloc[-1]) > vol_ma * 1.2

        if hurst > self._hurst_persistent:
            if ret_5 > 0 and ret_20 > 0:
                strength = min(0.9, 0.5 + (hurst - 0.5) * 1.5)
                if vol_confirm:
                    strength = min(0.95, strength + 0.1)
                return _signal(SignalType.BUY, strength, f"持续性趋势(H={hurst:.2f})+上涨", 0.50)
            if ret_5 < 0 and ret_20 < 0:
                strength = min(0.9, 0.5 + (hurst - 0.5) * 1.5)
                if vol_confirm:
                    strength = min(0.95, strength + 0.1)
                return _signal(SignalType.SELL, strength, f"持续性趋势(H={hurst:.2f})+下跌")

        if hurst < self._hurst_anti:
            rsi = _safe_float(_rsi_series(c, 14).iloc[-1], 50)
            if rsi < 30:
                return _signal(SignalType.BUY, 0.7, f"反持续性+超卖(H={hurst:.2f},RSI={rsi:.0f})，均值回归买入", 0.40)
            if rsi > 70:
                return _signal(SignalType.SELL, 0.7, f"反持续性+超买(H={hurst:.2f},RSI={rsi:.0f})，均值回归卖出")

        if 0.45 <= hurst <= 0.55:
            bb_mid = _safe_float(c.rolling(20).mean().iloc[-1])
            bb_std = _safe_float(c.rolling(20).std().iloc[-1])
            if bb_mid > 0 and bb_std > 0:
                z = (_safe_float(c.iloc[-1]) - bb_mid) / bb_std
                if z < -2:
                    return _signal(SignalType.BUY, 0.5, f"随机游走+Z超卖(H={hurst:.2f},Z={z:.1f})", 0.35)
                if z > 2:
                    return _signal(SignalType.SELL, 0.5, f"随机游走+Z超买(H={hurst:.2f},Z={z:.1f})")

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"window": {"min": 60, "max": 150, "step": 30}}


class PairsTradingStrategy(BaseStrategy):
    """配对交易策略 - 用自身价格与长期均值的偏离模拟配对交易"""

    min_bars = 60

    def __init__(self, window: int = 60, entry_z: float = 2.0, exit_z: float = 0.5,
                 half_life_min: float = 3, half_life_max: float = 30):
        super().__init__()
        self._window = int(window)
        self._entry_z = float(entry_z)
        self._exit_z = float(exit_z)
        self._hl_min = float(half_life_min)
        self._hl_max = float(half_life_max)

    def _calc_half_life(self, spread: np.ndarray) -> float:
        if len(spread) < 20:
            return 999.0
        y = spread[1:]
        x = spread[:-1]
        x_mean = np.mean(x)
        denom = np.sum((x - x_mean) ** 2)
        if denom < 1e-12:
            return 999.0
        beta = np.sum((x - x_mean) * (y - np.mean(y))) / denom
        if beta <= 0 or beta >= 1:
            return 999.0
        return -np.log(beta)

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if df is None or len(df) < self._window + 5:
            return TradeSignal(SignalType.HOLD)
        c = df["close"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)

        ma_long = c.rolling(self._window).mean()
        spread = (c - ma_long).values
        spread_series = pd.Series(spread)
        spread_mean = spread_series.rolling(self._window).mean()
        spread_std = spread_series.rolling(self._window).std().replace(0, np.nan)
        z_score = (spread_series - spread_mean) / spread_std

        z = _safe_float(z_score.iloc[-1])
        z_prev = _safe_float(z_score.iloc[-2]) if len(z_score) > 1 else 0
        dz = z - z_prev

        recent_spread = spread[-self._window:]
        half_life = self._calc_half_life(recent_spread)

        if half_life > self._hl_max or half_life < self._hl_min:
            return TradeSignal(SignalType.HOLD)

        rsi = _safe_float(_rsi_series(c, 14).iloc[-1], 50)
        vol_ma = _safe_float(v.rolling(20).mean().iloc[-1])
        vol_shrink = vol_ma > 0 and _safe_float(v.iloc[-1]) < vol_ma * 0.8

        if z < -self._entry_z and dz > 0:
            strength = min(0.95, abs(z) / 3)
            confirm = "RSI确认" if rsi < 40 else ""
            confirm += "量缩确认" if vol_shrink else ""
            return _signal(SignalType.BUY, strength, f"配对交易做多(Z={z:.2f},HL={half_life:.1f}d){confirm}", 0.45)

        if z > self._entry_z and dz < 0:
            strength = min(0.95, z / 3)
            confirm = "RSI确认" if rsi > 60 else ""
            confirm += "量缩确认" if vol_shrink else ""
            return _signal(SignalType.SELL, strength, f"配对交易做空(Z={z:.2f},HL={half_life:.1f}d){confirm}")

        if abs(z) < self._exit_z and abs(z_prev) >= self._exit_z:
            if z_prev < 0:
                return _signal(SignalType.SELL, 0.5, f"配对交易平仓做多(Z回归={z:.2f})")
            else:
                return _signal(SignalType.BUY, 0.5, f"配对交易平仓做空(Z回归={z:.2f})", 0.30)

        return TradeSignal(SignalType.HOLD)

    @classmethod
    def get_param_space(cls) -> dict:
        return {"window": {"min": 40, "max": 80, "step": 10}, "entry_z": {"min": 1.5, "max": 3.0, "step": 0.25}}


class CompositeStrategy(BaseStrategy):
    """组合策略"""

    def __init__(self):
        super().__init__()
        self.strategies = [
            DualMAStrategy(),
            MACDStrategy(),
            KDJStrategy(),
            BollingerBreakoutStrategy(),
            MomentumStrategy(),
            MultiFactorConfluenceStrategy(),
            AdaptiveTrendFollowingStrategy(),
            MeanReversionProStrategy(),
            VolatilitySqueezeBreakoutStrategy(),
            RSIMeanReversionStrategy(),
            SuperTrendStrategy(),
            IchimokuCloudStrategy(),
            VWAPDeviationStrategy(),
            OrderFlowImbalanceStrategy(),
            RegimeSwitchingStrategy(),
            FractalBreakoutStrategy(),
            WyckoffAccumulationStrategy(),
            ElliottWaveAIStrategy(),
            MarketMicrostructureStrategy(),
            CopulaCorrelationStrategy(),
            QuantileRegressionStrategy(),
            TurtleTradingStrategy(),
            DualThrustStrategy(),
            ATRChannelBreakoutStrategy(),
            DonchianChannelStrategy(),
            ChandeKrollStopStrategy(),
            VolumeWeightedMACDStrategy(),
            OrnsteinUhlenbeckStrategy(),
            KaufmanAdaptiveStrategy(),
            GARCHVolatilityStrategy(),
            MultiTimeframeMomentumStrategy(),
            ADXTrendStrengthStrategy(),
            ChaikinMoneyFlowStrategy(),
            ParabolicSARStrategy(),
            HurstExponentStrategy(),
            PairsTradingStrategy(),
        ]
        self._cache_key: tuple | None = None
        self._cache_result: TradeSignal | None = None

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) > 0:
            cache_key = (len(df), id(df), float(df["close"].iloc[-1]))
            if cache_key == self._cache_key and self._cache_result is not None:
                return self._cache_result
        else:
            cache_key = None

        buy_strength = 0.0
        sell_strength = 0.0
        buy_count = 0
        sell_count = 0
        for s in self.strategies:
            try:
                sig = self._sanitize_signal(s.generate_signal(df))
                if sig.signal_type == SignalType.BUY:
                    buy_count += 1
                    buy_strength += sig.strength
                elif sig.signal_type == SignalType.SELL:
                    sell_count += 1
                    sell_strength += sig.strength
            except Exception as e:
                logger.debug("CompositeStrategy %s error: %s", type, e)
        n = len(self.strategies) or 1
        net_strength = buy_strength - sell_strength
        if buy_count >= 2 and buy_count > sell_count:
            result = TradeSignal(signal_type=SignalType.BUY, strength=round(min(abs(net_strength) / n, 1.0), 2), reason=f"{buy_count}个策略看多(加权{buy_strength:.1f})")
        elif sell_count >= 2 and sell_count > buy_count:
            result = TradeSignal(signal_type=SignalType.SELL, strength=round(min(abs(net_strength) / n, 1.0), 2), reason=f"{sell_count}个策略看空(加权{sell_strength:.1f})")
        else:
            result = TradeSignal(signal_type=SignalType.HOLD, strength=0.0, reason="多空分歧")

        if cache_key is not None:
            self._cache_key = cache_key
            self._cache_result = result
        return result

    def get_strategy_info(self) -> list[dict]:
        return [s.get_info() for s in self.strategies]


class MultiFactorScoreStrategy(BaseStrategy):
    """多因子评分策略：标准化因子打分 + 加权综合评分"""

    min_bars = 60

    FACTOR_WEIGHTS = {
        "trend": 0.25,
        "momentum": 0.20,
        "volatility": 0.15,
        "volume": 0.15,
        "mean_reversion": 0.15,
        "quality": 0.10,
    }

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < self.min_bars:
            return TradeSignal(SignalType.HOLD)

        c = df["close"].astype(float)
        high = df["high"].astype(float) if "high" in df.columns else c
        low = df["low"].astype(float) if "low" in df.columns else c
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)

        scores = {}

        # 趋势因子：均线多头/空头排列 + ADX
        scores["trend"] = self._score_trend(c, high, low)

        # 动量因子：RSI + 价格动量
        scores["momentum"] = self._score_momentum(c)

        # 波动率因子：波动率位置 + ATR通道
        scores["volatility"] = self._score_volatility(c, high, low)

        # 成交量因子：量价配合度
        scores["volume"] = self._score_volume(c, v)

        # 均值回归因子：Z-Score + 自相关
        scores["mean_reversion"] = self._score_mean_reversion(c)

        # 质量因子：收益率稳定性
        scores["quality"] = self._score_quality(c)

        total = 0.0
        for factor, weight in self.FACTOR_WEIGHTS.items():
            total += scores.get(factor, 0.0) * weight

        if total > 0.35:
            strength = min(0.95, total * 1.5)
            return TradeSignal(SignalType.BUY, strength, f"多因子看多({total:.2f})")
        if total < -0.35:
            strength = min(0.95, abs(total) * 1.5)
            return TradeSignal(SignalType.SELL, strength, f"多因子看空({total:.2f})")
        return TradeSignal(SignalType.HOLD, 0.0, f"多因子中性({total:.2f})")

    def _score_trend(self, c, high, low) -> float:
        if len(c) < 60:
            return 0.0
        ma5 = c.rolling(5).mean().iloc[-1]
        ma20 = c.rolling(20).mean().iloc[-1]
        ma60 = c.rolling(60).mean().iloc[-1]
        score = 0.0
        if ma5 > ma20 > ma60:
            score += 0.5
        elif ma5 < ma20 < ma60:
            score -= 0.5
        if ma5 > ma20:
            score += 0.2
        else:
            score -= 0.2
        # ADX方向
        tr = pd.concat([high - low, (high - c.shift(1)).abs(), (low - c.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
        atr_safe = atr.replace(0, np.nan)
        plus_di = 100 * (plus_dm.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / atr_safe)
        minus_di = 100 * (minus_dm.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / atr_safe)
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        adx = dx.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        adx_val = _safe_float(adx.iloc[-1])
        if adx_val > 25:
            di_diff = _safe_float(plus_di.iloc[-1]) - _safe_float(minus_di.iloc[-1])
            score += 0.3 * (1 if di_diff > 0 else -1)
        return np.clip(score, -1.0, 1.0)

    def _score_momentum(self, c) -> float:
        if len(c) < 20:
            return 0.0
        rsi = _rsi_series(c, 14)
        rsi_val = _safe_float(rsi.iloc[-1])
        score = 0.0
        if rsi_val > 70:
            score -= 0.4
        elif rsi_val > 55:
            score += 0.3
        elif rsi_val < 30:
            score += 0.4
        elif rsi_val < 45:
            score -= 0.3
        # 价格动量
        ret_5 = _safe_float(c.pct_change(5).iloc[-1])
        ret_20 = _safe_float(c.pct_change(20).iloc[-1])
        if ret_5 > 0.03:
            score += 0.3
        elif ret_5 < -0.03:
            score -= 0.3
        if ret_20 > 0.05:
            score += 0.2
        elif ret_20 < -0.05:
            score -= 0.2
        return np.clip(score, -1.0, 1.0)

    def _score_volatility(self, c, high, low) -> float:
        if len(c) < 20:
            return 0.0
        ret = c.pct_change().dropna()
        vol = ret.rolling(20).std().iloc[-1] * np.sqrt(252)
        vol_val = _safe_float(vol)
        # 低波动率偏多，高波动率偏空
        if vol_val < 0.15:
            return 0.3
        if vol_val < 0.25:
            return 0.1
        if vol_val > 0.50:
            return -0.4
        if vol_val > 0.35:
            return -0.2
        return 0.0

    def _score_volume(self, c, v) -> float:
        if len(c) < 20 or len(v) < 20:
            return 0.0
        vol_ma = v.rolling(20).mean().iloc[-1]
        vol_cur = _safe_float(v.iloc[-1])
        if vol_ma < 1e-6:
            return 0.0
        ratio = vol_cur / vol_ma
        ret = _safe_float(c.pct_change().iloc[-1])
        score = 0.0
        # 放量上涨
        if ratio > 1.5 and ret > 0:
            score += 0.5
        # 放量下跌
        elif ratio > 1.5 and ret < 0:
            score -= 0.5
        # 缩量
        elif ratio < 0.5:
            score -= 0.1
        return np.clip(score, -1.0, 1.0)

    def _score_mean_reversion(self, c) -> float:
        if len(c) < 30:
            return 0.0
        ma = c.rolling(20).mean().iloc[-1]
        std = c.rolling(20).std().iloc[-1]
        if _safe_float(std) < 1e-10:
            return 0.0
        z = _safe_float((c.iloc[-1] - ma) / std)
        # 极端Z值偏均值回归
        if z > 2.0:
            return -0.6
        if z > 1.5:
            return -0.3
        if z < -2.0:
            return 0.6
        if z < -1.5:
            return 0.3
        return 0.0

    def _score_quality(self, c) -> float:
        if len(c) < 20:
            return 0.0
        ret = c.pct_change().dropna()
        if len(ret) < 20:
            return 0.0
        win_rate = (ret.iloc[-20:] > 0).mean()
        sharpe_like = _safe_float(ret.iloc[-20:].mean() / (ret.iloc[-20:].std() + 1e-10)) * np.sqrt(252)
        score = 0.0
        if win_rate > 0.6:
            score += 0.3
        elif win_rate < 0.4:
            score -= 0.3
        if sharpe_like > 1.0:
            score += 0.3
        elif sharpe_like < -0.5:
            score -= 0.3
        return np.clip(score, -1.0, 1.0)


class MomentumRotationStrategy(BaseStrategy):
    """动量轮动策略：基于多周期动量评分，捕捉趋势加速"""

    min_bars = 40

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < self.min_bars:
            return TradeSignal(SignalType.HOLD)

        c = df["close"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1, index=df.index)

        # 多周期动量
        ret_5 = _safe_float(c.pct_change(5).iloc[-1])
        ret_10 = _safe_float(c.pct_change(10).iloc[-1])
        ret_20 = _safe_float(c.pct_change(20).iloc[-1])

        # 动量加速度（短期动量 vs 中期动量）
        accel = ret_5 - ret_10 * 0.5

        # RSI过滤
        rsi = _rsi_series(c, 14)
        rsi_val = _safe_float(rsi.iloc[-1])

        # 量价确认
        vol_ma = v.rolling(20).mean().iloc[-1]
        vol_cur = _safe_float(v.iloc[-1])
        vol_ratio = vol_cur / vol_ma if _safe_float(vol_ma) > 1e-6 else 1.0

        # 综合动量评分
        score = 0.0
        score += ret_5 * 3.0
        score += ret_10 * 2.0
        score += ret_20 * 1.0
        score += accel * 2.0

        # 量价确认加成
        if vol_ratio > 1.3 and score > 0 or vol_ratio > 1.3 and score < 0:
            score *= 1.3

        # RSI过滤
        if rsi_val > 75 or rsi_val < 25:
            score *= 0.5

        if score > 0.15:
            strength = min(0.9, abs(score) * 2)
            return TradeSignal(SignalType.BUY, strength, "动量加速多头")
        if score < -0.15:
            strength = min(0.9, abs(score) * 2)
            return TradeSignal(SignalType.SELL, strength, "动量加速空头")
        return TradeSignal(SignalType.HOLD, 0.0, "动量中性")


class RegimeAdaptiveStrategy(BaseStrategy):
    """市场状态自适应策略：根据市场状态动态调整子策略权重"""

    min_bars = 60

    REGIME_WEIGHTS = {
        "trending_up": {
            "trend": 0.50, "momentum": 0.30, "mean_reversion": 0.05,
            "volatility": 0.05, "channel": 0.10,
        },
        "trending_down": {
            "trend": 0.40, "momentum": 0.10, "mean_reversion": 0.10,
            "volatility": 0.20, "channel": 0.20,
        },
        "mean_reverting": {
            "trend": 0.10, "momentum": 0.05, "mean_reversion": 0.55,
            "volatility": 0.10, "channel": 0.20,
        },
        "high_volatility": {
            "trend": 0.15, "momentum": 0.10, "mean_reversion": 0.15,
            "volatility": 0.40, "channel": 0.20,
        },
        "low_volatility": {
            "trend": 0.30, "momentum": 0.20, "mean_reversion": 0.20,
            "volatility": 0.10, "channel": 0.20,
        },
        "sideways": {
            "trend": 0.10, "momentum": 0.05, "mean_reversion": 0.45,
            "volatility": 0.10, "channel": 0.30,
        },
        "unknown": {
            "trend": 0.25, "momentum": 0.15, "mean_reversion": 0.20,
            "volatility": 0.15, "channel": 0.25,
        },
    }

    def __init__(self):
        super().__init__()
        self._detector = None
        self._sub_strategies: dict[str, BaseStrategy] = {}
        self._last_regime: str = "unknown"
        self._last_weights: dict[str, float] = self.REGIME_WEIGHTS["unknown"]

    def _get_detector(self):
        if self._detector is None:
            from core.regime_detector import RegimeDetector
            self._detector = RegimeDetector()
        return self._detector

    def _get_sub_strategies(self) -> dict[str, BaseStrategy]:
        if not self._sub_strategies:
            self._sub_strategies = {
                "trend": DualMAStrategy(short_period=5, long_period=20),
                "momentum": MACDStrategy(),
                "mean_reversion": MeanReversionProStrategy(),
                "volatility": BollingerBreakoutStrategy(),
                "channel": DonchianChannelStrategy(),
            }
        return self._sub_strategies

    def generate_signal(self, df: pd.DataFrame, use_precomputed: bool = True) -> TradeSignal:
        if len(df) < self.min_bars:
            return TradeSignal(SignalType.HOLD)

        detector = self._get_detector()
        regime_result = detector.detect(df)
        regime_name = regime_result.current_regime.value
        self._last_regime = regime_name
        self._last_weights = self.REGIME_WEIGHTS.get(regime_name, self.REGIME_WEIGHTS["unknown"])

        sub_strategies = self._get_sub_strategies()
        weighted_bull = 0.0
        weighted_bear = 0.0
        total_weight = 0.0

        for category, weight in self._last_weights.items():
            strategy = sub_strategies.get(category)
            if strategy is None:
                continue
            try:
                sig = strategy.generate_signal(df)
            except Exception as e:
                logger.debug("子策略信号生成失败: %s, %s", category, e)
                continue
            strength = sig.strength if sig.strength else 0.0
            if sig.signal_type == SignalType.BUY:
                weighted_bull += strength * weight
            elif sig.signal_type == SignalType.SELL:
                weighted_bear += strength * weight
            total_weight += weight

        if total_weight < 1e-6:
            return TradeSignal(SignalType.HOLD)

        net = weighted_bull - weighted_bear
        confidence = regime_result.confidence

        if net > 0.15:
            strength = min(0.95, net * confidence * 2)
            return TradeSignal(SignalType.BUY, strength, f"自适应多头[{regime_name}]")
        if net < -0.15:
            strength = min(0.95, abs(net) * confidence * 2)
            return TradeSignal(SignalType.SELL, strength, f"自适应空头[{regime_name}]")
        return TradeSignal(SignalType.HOLD, 0.0, f"观望[{regime_name}]")

    def get_regime_info(self) -> dict:
        return {
            "current_regime": self._last_regime,
            "weights": dict(self._last_weights),
        }


STRATEGY_REGISTRY = {
    "ma_cross": DualMAStrategy,
    "dual_ma": DualMAStrategy,
    "DualMAStrategy": DualMAStrategy,
    "macd": MACDStrategy,
    "MACDStrategy": MACDStrategy,
    "kdj": KDJStrategy,
    "KDJStrategy": KDJStrategy,
    "bollinger": BollingerBreakoutStrategy,
    "bollinger_breakout": BollingerBreakoutStrategy,
    "BollingerBreakoutStrategy": BollingerBreakoutStrategy,
    "momentum": MomentumStrategy,
    "MomentumStrategy": MomentumStrategy,
    "multi_factor": MultiFactorConfluenceStrategy,
    "MultiFactorConfluenceStrategy": MultiFactorConfluenceStrategy,
    "adaptive_trend": AdaptiveTrendFollowingStrategy,
    "AdaptiveTrendFollowingStrategy": AdaptiveTrendFollowingStrategy,
    "mean_reversion_pro": MeanReversionProStrategy,
    "MeanReversionProStrategy": MeanReversionProStrategy,
    "vol_squeeze": VolatilitySqueezeBreakoutStrategy,
    "volatility_squeeze": VolatilitySqueezeBreakoutStrategy,
    "VolatilitySqueezeBreakoutStrategy": VolatilitySqueezeBreakoutStrategy,
    "rsi": RSIMeanReversionStrategy,
    "rsi_mean_reversion": RSIMeanReversionStrategy,
    "RSIMeanReversionStrategy": RSIMeanReversionStrategy,
    "supertrend": SuperTrendStrategy,
    "SuperTrendStrategy": SuperTrendStrategy,
    "ichimoku": IchimokuCloudStrategy,
    "ichimoku_cloud": IchimokuCloudStrategy,
    "IchimokuCloudStrategy": IchimokuCloudStrategy,
    "vwap_deviation": VWAPDeviationStrategy,
    "VWAPDeviationStrategy": VWAPDeviationStrategy,
    "order_flow": OrderFlowImbalanceStrategy,
    "order_flow_imbalance": OrderFlowImbalanceStrategy,
    "OrderFlowImbalanceStrategy": OrderFlowImbalanceStrategy,
    "regime_switching": RegimeSwitchingStrategy,
    "RegimeSwitchingStrategy": RegimeSwitchingStrategy,
    "fractal_breakout": FractalBreakoutStrategy,
    "FractalBreakoutStrategy": FractalBreakoutStrategy,
    "wyckoff": WyckoffAccumulationStrategy,
    "wyckoff_accumulation": WyckoffAccumulationStrategy,
    "WyckoffAccumulationStrategy": WyckoffAccumulationStrategy,
    "elliott_wave": ElliottWaveAIStrategy,
    "ElliottWaveAIStrategy": ElliottWaveAIStrategy,
    "microstructure": MarketMicrostructureStrategy,
    "market_microstructure": MarketMicrostructureStrategy,
    "MarketMicrostructureStrategy": MarketMicrostructureStrategy,
    "copula": CopulaCorrelationStrategy,
    "copula_correlation": CopulaCorrelationStrategy,
    "CopulaCorrelationStrategy": CopulaCorrelationStrategy,
    "quantile": QuantileRegressionStrategy,
    "quantile_regression": QuantileRegressionStrategy,
    "QuantileRegressionStrategy": QuantileRegressionStrategy,
    "turtle": TurtleTradingStrategy,
    "turtle_trading": TurtleTradingStrategy,
    "TurtleTradingStrategy": TurtleTradingStrategy,
    "dual_thrust": DualThrustStrategy,
    "DualThrustStrategy": DualThrustStrategy,
    "atr_channel": ATRChannelBreakoutStrategy,
    "atr_channel_breakout": ATRChannelBreakoutStrategy,
    "ATRChannelBreakoutStrategy": ATRChannelBreakoutStrategy,
    "donchian": DonchianChannelStrategy,
    "donchian_channel": DonchianChannelStrategy,
    "DonchianChannelStrategy": DonchianChannelStrategy,
    "chande_kroll": ChandeKrollStopStrategy,
    "chande_kroll_stop": ChandeKrollStopStrategy,
    "ChandeKrollStopStrategy": ChandeKrollStopStrategy,
    "vw_macd": VolumeWeightedMACDStrategy,
    "volume_weighted_macd": VolumeWeightedMACDStrategy,
    "VolumeWeightedMACDStrategy": VolumeWeightedMACDStrategy,
    "ou_mean_reversion": OrnsteinUhlenbeckStrategy,
    "ornstein_uhlenbeck": OrnsteinUhlenbeckStrategy,
    "OrnsteinUhlenbeckStrategy": OrnsteinUhlenbeckStrategy,
    "kaufman": KaufmanAdaptiveStrategy,
    "kaufman_adaptive": KaufmanAdaptiveStrategy,
    "KaufmanAdaptiveStrategy": KaufmanAdaptiveStrategy,
    "garch_vol": GARCHVolatilityStrategy,
    "garch_volatility": GARCHVolatilityStrategy,
    "GARCHVolatilityStrategy": GARCHVolatilityStrategy,
    "mtf_momentum": MultiTimeframeMomentumStrategy,
    "multi_timeframe_momentum": MultiTimeframeMomentumStrategy,
    "MultiTimeframeMomentumStrategy": MultiTimeframeMomentumStrategy,
    "adx_trend": ADXTrendStrengthStrategy,
    "adx_trend_strength": ADXTrendStrengthStrategy,
    "ADXTrendStrengthStrategy": ADXTrendStrengthStrategy,
    "cmf": ChaikinMoneyFlowStrategy,
    "chaikin_money_flow": ChaikinMoneyFlowStrategy,
    "ChaikinMoneyFlowStrategy": ChaikinMoneyFlowStrategy,
    "psar": ParabolicSARStrategy,
    "parabolic_sar": ParabolicSARStrategy,
    "ParabolicSARStrategy": ParabolicSARStrategy,
    "hurst": HurstExponentStrategy,
    "hurst_exponent": HurstExponentStrategy,
    "HurstExponentStrategy": HurstExponentStrategy,
    "pairs": PairsTradingStrategy,
    "pairs_trading": PairsTradingStrategy,
    "PairsTradingStrategy": PairsTradingStrategy,
    "regime_adaptive": RegimeAdaptiveStrategy,
    "RegimeAdaptiveStrategy": RegimeAdaptiveStrategy,
    "multi_factor_score": MultiFactorScoreStrategy,
    "MultiFactorScoreStrategy": MultiFactorScoreStrategy,
    "momentum_rotation": MomentumRotationStrategy,
    "MomentumRotationStrategy": MomentumRotationStrategy,
}


def unique_strategies():
    seen = set()
    for cls in STRATEGY_REGISTRY.values():
        if cls not in seen:
            seen.add(cls)
            yield cls


class StrategyRegistry:
    """策略注册中心：自动发现、元数据管理、插件注册"""

    CATEGORIES = {
        "trend": ["ma_cross", "dual_ma", "macd", "supertrend", "ichimoku", "ichimoku_cloud",
                   "kaufman", "kaufman_adaptive", "adx_trend", "adx_trend_strength", "psar", "parabolic_sar"],
        "mean_reversion": ["bollinger", "bollinger_breakout", "rsi", "rsi_mean_reversion",
                           "mean_reversion_pro", "ou_mean_reversion", "ornstein_uhlenbeck"],
        "momentum": ["momentum", "multi_factor", "multi_factor_score", "momentum_rotation", "mtf_momentum", "multi_timeframe_momentum"],
        "volatility": ["vol_squeeze", "volatility_squeeze", "garch_vol", "garch_volatility",
                       "atr_channel", "atr_channel_breakout", "dual_thrust"],
        "channel": ["donchian", "donchian_channel", "chande_kroll", "chande_kroll_stop", "turtle", "turtle_trading"],
        "volume": ["vwap_deviation", "order_flow", "order_flow_imbalance", "cmf", "chaikin_money_flow",
                   "vw_macd", "volume_weighted_macd"],
        "advanced": ["regime_switching", "regime_adaptive", "copula", "copula_correlation", "quantile", "quantile_regression",
                     "microstructure", "market_microstructure", "hurst", "hurst_exponent", "pairs", "pairs_trading"],
        "pattern": ["fractal_breakout", "wyckoff", "wyckoff_accumulation", "elliott_wave",
                    "kdj", "KDJStrategy"],
    }

    def __init__(self, base_registry: dict | None = None):
        self._registry = dict(base_registry) if base_registry else dict(STRATEGY_REGISTRY)
        self._metadata = {}
        self._init_metadata()

    def _init_metadata(self):
        seen_classes = set()
        for key, cls in self._registry.items():
            if cls in seen_classes:
                continue
            seen_classes.add(cls)
            if key == cls.__name__:
                self._metadata[key] = {
                    "class_name": cls.__name__,
                    "category": self._get_category(key),
                    "has_param_space": hasattr(cls, "get_param_space"),
                    "has_vectorized": hasattr(cls, "generate_signals_vectorized"),
                }

    def _get_category(self, key: str) -> str:
        for cat, keys in self.CATEGORIES.items():
            if key in keys:
                return cat
        return "other"

    def register(self, name: str, strategy_cls: type, aliases: list | None = None, category: str = "other") -> None:
        """注册新策略（插件模式）"""
        self._registry[name] = strategy_cls
        self._registry[strategy_cls.__name__] = strategy_cls
        if aliases:
            for alias in aliases:
                self._registry[alias] = strategy_cls
        self._metadata[strategy_cls.__name__] = {
            "class_name": strategy_cls.__name__,
            "category": category,
            "has_param_space": hasattr(strategy_cls, "get_param_space"),
            "has_vectorized": hasattr(strategy_cls, "generate_signals_vectorized"),
        }

    def get(self, name: str):
        return self._registry.get(name)

    def list_strategies(self, category: str | None = None) -> list:
        """列出所有可用策略，可按类别过滤"""
        seen = set()
        result = []
        for key, cls in self._registry.items():
            cname = cls.__name__
            if cname in seen:
                continue
            seen.add(cname)
            cat = self._get_category(key)
            if category and cat != category:
                continue
            result.append({
                "name": cname,
                "key": key,
                "category": cat,
                "has_param_space": hasattr(cls, "get_param_space"),
                "has_vectorized": hasattr(cls, "generate_signals_vectorized"),
            })
        return result

    def list_categories(self) -> dict:
        return {cat: len(keys) for cat, keys in self.CATEGORIES.items()}

    def __contains__(self, name: str) -> bool:
        return name in self._registry

    def __getitem__(self, name: str):
        return self._registry[name]


_registry_instance = None


def get_strategy_registry() -> StrategyRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = StrategyRegistry()
    return _registry_instance
