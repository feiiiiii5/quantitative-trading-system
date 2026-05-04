import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.strategies import (
    BaseStrategy,
    BollingerBreakoutStrategy,
    DualMAStrategy,
    KDJStrategy,
    MACDStrategy,
    MomentumStrategy,
    MultiFactorConfluenceStrategy,
    AdaptiveTrendFollowingStrategy,
    MeanReversionProStrategy,
    VolatilitySqueezeBreakoutStrategy,
    RSIMeanReversionStrategy,
    SuperTrendStrategy,
    IchimokuCloudStrategy,
    VWAPDeviationStrategy,
    OrderFlowImbalanceStrategy,
    RegimeSwitchingStrategy,
    FractalBreakoutStrategy,
    WyckoffAccumulationStrategy,
    ElliottWaveAIStrategy,
    MarketMicrostructureStrategy,
    CopulaCorrelationStrategy,
    QuantileRegressionStrategy,
    TurtleTradingStrategy,
    DualThrustStrategy,
    ATRChannelBreakoutStrategy,
    DonchianChannelStrategy,
    ChandeKrollStopStrategy,
    VolumeWeightedMACDStrategy,
    SignalType,
    StrategyResult,
    TradeSignal,
)
from core.backtest import BacktestResult
from core.indicators import calc_atr, calc_adx, calc_chandelier_exit, calc_kelly_fraction

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    STRONG_TREND_UP = "strong_trend_up"
    MILD_TREND_UP = "mild_trend_up"
    HIGH_VOLATILITY_RANGE = "high_volatility_range"
    LOW_VOLATILITY_CONSOLIDATION = "low_volatility_consolidation"
    MILD_TREND_DOWN = "mild_trend_down"
    STRONG_TREND_DOWN = "strong_trend_down"
    BEAR_TRAP = "bear_trap"
    DISTRIBUTION_TOP = "distribution_top"


REGIME_LABELS = {
    MarketRegime.STRONG_TREND_UP: "强趋势上涨",
    MarketRegime.MILD_TREND_UP: "温和趋势上涨",
    MarketRegime.HIGH_VOLATILITY_RANGE: "高波动震荡",
    MarketRegime.LOW_VOLATILITY_CONSOLIDATION: "低波动盘整",
    MarketRegime.MILD_TREND_DOWN: "温和趋势下跌",
    MarketRegime.STRONG_TREND_DOWN: "强趋势下跌",
    MarketRegime.BEAR_TRAP: "空头陷阱",
    MarketRegime.DISTRIBUTION_TOP: "派发顶部",
}

STRATEGY_ALLOCATION = {
    MarketRegime.STRONG_TREND_UP: {
        "strategies": [AdaptiveTrendFollowingStrategy, MultiFactorConfluenceStrategy, SuperTrendStrategy, TurtleTradingStrategy, MomentumStrategy],
        "weights": [0.22, 0.22, 0.20, 0.20, 0.16],
    },
    MarketRegime.MILD_TREND_UP: {
        "strategies": [MultiFactorConfluenceStrategy, DualMAStrategy, VolumeWeightedMACDStrategy, VolatilitySqueezeBreakoutStrategy, DonchianChannelStrategy],
        "weights": [0.22, 0.22, 0.20, 0.18, 0.18],
    },
    MarketRegime.HIGH_VOLATILITY_RANGE: {
        "strategies": [MeanReversionProStrategy, VolatilitySqueezeBreakoutStrategy, KDJStrategy, RSIMeanReversionStrategy, ATRChannelBreakoutStrategy],
        "weights": [0.24, 0.22, 0.20, 0.18, 0.16],
    },
    MarketRegime.LOW_VOLATILITY_CONSOLIDATION: {
        "strategies": [VolatilitySqueezeBreakoutStrategy, MeanReversionProStrategy, DualThrustStrategy, ATRChannelBreakoutStrategy, DonchianChannelStrategy],
        "weights": [0.25, 0.22, 0.22, 0.18, 0.13],
    },
    MarketRegime.MILD_TREND_DOWN: {
        "strategies": [SuperTrendStrategy, ChandeKrollStopStrategy, MACDStrategy, MeanReversionProStrategy, DualMAStrategy],
        "weights": [0.25, 0.22, 0.22, 0.18, 0.13],
    },
    MarketRegime.STRONG_TREND_DOWN: {
        "strategies": [AdaptiveTrendFollowingStrategy, SuperTrendStrategy, ChandeKrollStopStrategy, DonchianChannelStrategy, MACDStrategy],
        "weights": [0.25, 0.25, 0.20, 0.18, 0.12],
    },
    MarketRegime.BEAR_TRAP: {
        "strategies": [WyckoffAccumulationStrategy, MeanReversionProStrategy, RSIMeanReversionStrategy, OrderFlowImbalanceStrategy, TurtleTradingStrategy],
        "weights": [0.24, 0.22, 0.20, 0.18, 0.16],
    },
    MarketRegime.DISTRIBUTION_TOP: {
        "strategies": [ElliottWaveAIStrategy, SuperTrendStrategy, MarketMicrostructureStrategy, ChandeKrollStopStrategy, MACDStrategy],
        "weights": [0.24, 0.24, 0.20, 0.18, 0.14],
    },
}

BUY_THRESHOLD = 0.30
STRONG_BUY_THRESHOLD = 0.50
SELL_THRESHOLD = 0.25
ATR_STOP_MULTIPLIER = 2.5
MAX_DRAWDOWN_PROTECTION = 0.10
COOLDOWN_BARS = 3
TREND_FILTER_LOOKBACK = 60
KELLY_FRACTION = 0.5
CHANDELIER_PERIOD = 22
CHANDELIER_MULT = 3.0
CVAR_CONFIDENCE = 0.95
CVAR_LIMIT = 0.04
Q_LEARNING_RATE = 0.1
Q_DISCOUNT = 0.9
Q_EPSILON = 0.15
PARTIAL_EXIT_DRAWDOWN = 0.05
PARTIAL_EXIT_RATIO = 0.5
VOLATILITY_SCALING = True
MIN_TRADE_INTERVAL = 2


class QLearningWeightAdapter:
    """Q-Learning策略权重自适应调整器"""

    def __init__(self, n_strategies: int, learning_rate: float = Q_LEARNING_RATE,
                 discount: float = Q_DISCOUNT, epsilon_start: float = 0.3,
                 epsilon_end: float = 0.05, epsilon_decay: float = 0.995,
                 seed: Optional[int] = None):
        self._n = n_strategies
        self._lr = learning_rate
        self._discount = discount
        self._epsilon = epsilon_start
        self._epsilon_start = epsilon_start
        self._epsilon_end = epsilon_end
        self._epsilon_decay = epsilon_decay
        self._q_table: Dict[str, np.ndarray] = {}
        self._rng = np.random.RandomState(seed)
        self._last_state: Optional[str] = None
        self._last_action: Optional[int] = None
        self._trade_count = 0

    def _discretize_state(self, regime: MarketRegime, volatility: float, trend: float) -> str:
        vol_bin = "low" if volatility < 0.15 else ("mid" if volatility < 0.30 else "high")
        trend_bin = "up" if trend > 0.01 else ("down" if trend < -0.01 else "flat")
        return f"{regime.value}_{vol_bin}_{trend_bin}"

    def select_weights(self, regime: MarketRegime, volatility: float, trend: float,
                       base_weights: List[float]) -> List[float]:
        state = self._discretize_state(regime, volatility, trend)
        if state not in self._q_table:
            self._q_table[state] = np.zeros(self._n)

        q_values = self._q_table[state]
        if self._rng.random() < self._epsilon:
            adapted = np.array(base_weights) + self._rng.normal(0, 0.02, self._n)
        else:
            best_action = int(np.argmax(q_values))
            adapted = np.array(base_weights)
            adapted[best_action] += 0.05

        adapted = np.clip(adapted, 0.05, 0.60)
        total = adapted.sum()
        if total > 0:
            adapted = adapted / total
        return adapted.tolist()

    def update(self, regime: MarketRegime, volatility: float, trend: float,
               strategy_idx: int, reward: float):
        self._trade_count += 1
        # ε随交易次数从0.3衰减至0.05
        self._epsilon = max(self._epsilon_end,
                            self._epsilon_start * (self._epsilon_decay ** self._trade_count))
        state = self._discretize_state(regime, volatility, trend)
        if state not in self._q_table:
            self._q_table[state] = np.zeros(self._n)
        old_q = self._q_table[state][strategy_idx]
        max_future_q = float(np.max(self._q_table[state]))
        self._q_table[state][strategy_idx] = old_q + self._lr * (
            reward + self._discount * max_future_q - old_q
        )


class MultiTimeframeAnalyzer:
    """多周期分析器 - 融合日线/周线/月线信号"""

    @staticmethod
    def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
        if "date" not in df.columns:
            return df
        df_copy = df.copy()
        df_copy["date"] = pd.to_datetime(df_copy["date"], errors="coerce")
        df_copy = df_copy.dropna(subset=["date"]).set_index("date")
        weekly = df_copy.resample("W").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()
        weekly = weekly.reset_index()
        return weekly

    @staticmethod
    def resample_monthly(df: pd.DataFrame) -> pd.DataFrame:
        if "date" not in df.columns:
            return df
        df_copy = df.copy()
        df_copy["date"] = pd.to_datetime(df_copy["date"], errors="coerce")
        df_copy = df_copy.dropna(subset=["date"]).set_index("date")
        monthly = df_copy.resample("ME").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()
        monthly = monthly.reset_index()
        return monthly

    @staticmethod
    def get_trend_alignment(daily_df: pd.DataFrame) -> float:
        """返回多周期趋势一致性分数 -1~1"""
        score = 0.0
        c = daily_df["close"].astype(float)
        if len(c) < 20:
            return 0.0

        # 日线趋势
        ma5 = float(c.rolling(5).mean().iloc[-1])
        ma20 = float(c.rolling(20).mean().iloc[-1])
        last_close = float(c.iloc[-1])
        if ma5 > ma20 and last_close > ma5:
            score += 0.4
        elif ma5 < ma20 and last_close < ma5:
            score -= 0.4

        # 周线趋势
        try:
            weekly = MultiTimeframeAnalyzer.resample_weekly(daily_df)
            if len(weekly) >= 10:
                wc = weekly["close"].astype(float)
                wma5 = float(wc.rolling(5).mean().iloc[-1])
                wma10 = float(wc.rolling(10).mean().iloc[-1])
                wlast = float(wc.iloc[-1])
                if wma5 > wma10 and wlast > wma5:
                    score += 0.3
                elif wma5 < wma10 and wlast < wma5:
                    score -= 0.3
        except Exception:
            pass

        # 月线趋势
        try:
            monthly = MultiTimeframeAnalyzer.resample_monthly(daily_df)
            if len(monthly) >= 6:
                mc = monthly["close"].astype(float)
                mma3 = float(mc.rolling(3).mean().iloc[-1])
                mlast = float(mc.iloc[-1])
                if mlast > mma3:
                    score += 0.3
                elif mlast < mma3:
                    score -= 0.3
        except Exception:
            pass

        return max(-1.0, min(1.0, score))


def calc_cvar(returns: np.ndarray, confidence: float = CVAR_CONFIDENCE) -> float:
    """计算条件风险价值(CVaR/ES)"""
    if len(returns) < 10:
        return 0.0
    sorted_ret = np.sort(returns)
    cutoff = int(np.floor(len(sorted_ret) * (1 - confidence)))
    if cutoff < 1:
        cutoff = 1
    tail = sorted_ret[:cutoff]
    return float(np.mean(tail)) if len(tail) > 0 else 0.0


def classify_market_regime(df: pd.DataFrame, window: int = 20) -> List[MarketRegime]:
    n = len(df)
    regimes = [MarketRegime.LOW_VOLATILITY_CONSOLIDATION] * n

    if n < window + 1:
        return regimes

    c = df["close"].values.astype(float)
    h = df["high"].values.astype(float)
    low_arr = df["low"].values.astype(float)
    v = df["volume"].values.astype(float) if "volume" in df.columns else np.ones(n)

    adx_full = calc_adx(h, low_arr, c, period=14)
    atr_full = calc_atr(h, low_arr, c, period=14)

    adx_strong_threshold = 30.0
    adx_mild_threshold = 20.0
    adx_window = adx_full[max(0, len(adx_full) - 252):]
    valid_adx = adx_window[np.isfinite(adx_window)]
    if len(valid_adx) > 60:
        adx_strong_threshold = float(np.percentile(valid_adx, 75))
        adx_mild_threshold = float(np.percentile(valid_adx, 50))
        adx_strong_threshold = max(25, min(40, adx_strong_threshold))
        adx_mild_threshold = max(15, min(30, adx_mild_threshold))

    for i in range(window, n):
        try:
            segment_c = c[i - window:i]
            segment_v = v[i - window:i]
            segment_atr = atr_full[i - window:i]

            adx_val = adx_full[i] if not np.isnan(adx_full[i]) else 0
            returns = np.diff(segment_c) / segment_c[:-1]
            returns = returns[np.isfinite(returns)]
            hist_vol = float(np.std(returns) * np.sqrt(252)) if len(returns) > 1 else 0

            vol_x = np.arange(len(segment_v))
            if len(segment_v) > 1:
                vol_slope = float(np.polyfit(vol_x, segment_v, 1)[0])
            else:
                vol_slope = 0

            ma20 = float(np.mean(segment_c))
            ma10 = float(np.mean(segment_c[-10:])) if len(segment_c) >= 10 else ma20
            price = c[i]
            deviation = (price - ma20) / ma20 if ma20 > 0 else 0
            short_deviation = (price - ma10) / ma10 if ma10 > 0 else 0

            trend_strength = adx_val
            is_strong_trend = trend_strength > adx_strong_threshold
            is_mild_trend = trend_strength > adx_mild_threshold
            is_ranging = trend_strength < adx_mild_threshold

            if i >= window + 10:
                support = float(np.min(low_arr[i - window:i - 5]))
                recent_low = float(np.min(low_arr[i - 5:i + 1]))
                recent_high = float(np.max(h[i - 3:i + 1]))
                recent_vol = float(np.mean(v[i - 3:i + 1]))
                avg_vol = float(np.mean(v[i - window:i - 5])) if i > window + 5 else 1
                vol_shrink = avg_vol > 0 and recent_vol < avg_vol * 0.8
                if (recent_low < support and price > support and
                        vol_shrink and price > ma20 * 0.98):
                    regimes[i] = MarketRegime.BEAR_TRAP
                    continue

            if i >= window + 5:
                prev_high = float(np.max(h[i - window:i - 3]))
                recent_peak = float(np.max(h[i - 3:i + 1]))
                recent_vol_avg = float(np.mean(v[i - 5:i + 1]))
                longer_vol_avg = float(np.mean(v[i - window:i - 5])) if i > window + 5 else 1
                adx_declining = adx_val < 25
                if (recent_peak >= prev_high * 0.99 and adx_declining and
                        recent_vol_avg < longer_vol_avg * 0.8 and deviation > 0.01):
                    regimes[i] = MarketRegime.DISTRIBUTION_TOP
                    continue

            if is_strong_trend:
                if deviation > 0.02:
                    regimes[i] = MarketRegime.STRONG_TREND_UP
                elif deviation > 0 or short_deviation > 0:
                    regimes[i] = MarketRegime.STRONG_TREND_UP
                elif deviation < -0.03:
                    regimes[i] = MarketRegime.STRONG_TREND_DOWN
                elif deviation < -0.01:
                    regimes[i] = MarketRegime.STRONG_TREND_DOWN
                else:
                    if short_deviation > 0:
                        regimes[i] = MarketRegime.MILD_TREND_UP
                    else:
                        regimes[i] = MarketRegime.MILD_TREND_DOWN
            elif is_mild_trend:
                if deviation > 0.005:
                    regimes[i] = MarketRegime.MILD_TREND_UP
                elif deviation < -0.005:
                    regimes[i] = MarketRegime.MILD_TREND_DOWN
                elif short_deviation > 0:
                    regimes[i] = MarketRegime.MILD_TREND_UP
                elif short_deviation < 0:
                    regimes[i] = MarketRegime.MILD_TREND_DOWN
                else:
                    if hist_vol > 0.20:
                        regimes[i] = MarketRegime.HIGH_VOLATILITY_RANGE
                    else:
                        regimes[i] = MarketRegime.LOW_VOLATILITY_CONSOLIDATION
            elif is_ranging:
                if hist_vol > 0.25:
                    regimes[i] = MarketRegime.HIGH_VOLATILITY_RANGE
                else:
                    regimes[i] = MarketRegime.LOW_VOLATILITY_CONSOLIDATION
            else:
                if hist_vol > 0.20:
                    regimes[i] = MarketRegime.HIGH_VOLATILITY_RANGE
                else:
                    regimes[i] = MarketRegime.LOW_VOLATILITY_CONSOLIDATION
        except Exception as e:
            logger.debug(f"Regime classification failed at index {i}: {e}")
            regimes[i] = MarketRegime.LOW_VOLATILITY_CONSOLIDATION

    return regimes


class AdaptiveStrategyEngine:
    def __init__(self, initial_capital: float = 1000000, commission: float = 0.0003, stamp_tax: float = 0.001):
        self._initial_capital = initial_capital
        self._commission = commission
        self._stamp_tax = stamp_tax
        self._strategy_perf = {}
        self._dynamic_weights = {}
        self._q_adapters: Dict[str, QLearningWeightAdapter] = {}
        self._mtf_analyzer = MultiTimeframeAnalyzer()
        self._returns_history: List[float] = []
        self._returns_history_max = 120

    def _kelly_position(self, c: np.ndarray, lookback: int = 60) -> float:
        return calc_kelly_fraction(c, lookback, half_kelly=KELLY_FRACTION)

    def _calc_chandelier(self, h: np.ndarray, low_arr: np.ndarray, c: np.ndarray,
                          atr: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        return calc_chandelier_exit(h, low_arr, c, atr, CHANDELIER_PERIOD, CHANDELIER_MULT)

    def _get_q_adapter(self, regime: MarketRegime, n_strategies: int) -> QLearningWeightAdapter:
        key = regime.value
        if key not in self._q_adapters:
            self._q_adapters[key] = QLearningWeightAdapter(n_strategies)
        return self._q_adapters[key]

    def _cvar_position_adjustment(self) -> float:
        """基于CVaR的仓位调整因子，CVaR>5%减仓，>8%暂停买入"""
        if len(self._returns_history) < 20:
            return 1.0
        ret_arr = np.array(self._returns_history[-60:])
        cvar = calc_cvar(ret_arr, CVAR_CONFIDENCE)
        if abs(cvar) > 0.08:
            return 0.0
        if abs(cvar) > CVAR_LIMIT:
            reduction = min(0.5, abs(cvar) / CVAR_LIMIT * 0.3)
            return max(0.3, 1.0 - reduction)
        return 1.0

    def _correlation_dedup_adjustment(self, new_symbol: str, existing_positions: dict,
                                       correlation_threshold: float = 0.85) -> float:
        """相关性去重：新标的与现有持仓相关性>0.85时降低仓位至50%"""
        if not existing_positions or len(existing_positions) < 1:
            return 1.0
        if len(existing_positions) < 3:
            return 1.0
        # 用收益率相关性判断：基于已有的收益率历史
        if len(self._returns_history) < 30:
            return 1.0
        new_rets = np.array(self._returns_history[-60:])
        for sym, pos_info in existing_positions.items():
            pos_rets = pos_info.get("returns_history")
            if pos_rets is None or len(pos_rets) < 30:
                continue
            pos_ret_arr = np.array(pos_rets[-60:])
            min_len = min(len(new_rets), len(pos_ret_arr))
            if min_len < 20:
                continue
            r_new = new_rets[-min_len:]
            r_pos = pos_ret_arr[-min_len:]
            valid = np.isfinite(r_new) & np.isfinite(r_pos)
            if valid.sum() < 20:
                continue
            corr = np.corrcoef(r_new[valid], r_pos[valid])[0, 1]
            if np.isfinite(corr) and abs(corr) > correlation_threshold:
                return 0.5
        return 1.0

    def _precompute_scores(self, strategy_instances: dict, df: pd.DataFrame, n: int) -> dict:
        scores = {}
        step = max(1, n // 100)
        for regime, instances in strategy_instances.items():
            regime_scores = {}
            for strategy in instances:
                name = type(strategy).__name__
                bar_scores = np.zeros(n)
                last_score = 0.0
                for i in range(step, n, step):
                    try:
                        score = strategy.generate_score(df.iloc[:i + 1])
                        last_score = score if np.isfinite(score) else last_score
                    except Exception:
                        pass
                    bar_scores[i:min(i + step, n)] = last_score
                regime_scores[name] = bar_scores
            scores[regime] = regime_scores
        return scores

    def _adapt_strategy_weights(self, regime: MarketRegime, alloc: dict,
                                 volatility: float = 0.0, trend: float = 0.0):
        key = regime.value
        base_weights = alloc.get("weights", [])
        strategy_names = [cls.__name__ for cls in alloc.get("strategies", [])]
        n_strategies = len(strategy_names)

        # Q-Learning权重调整
        q_adapter = self._get_q_adapter(regime, n_strategies)
        q_weights = q_adapter.select_weights(regime, volatility, trend, base_weights)

        # 历史表现调整
        adapted = list(q_weights)
        for idx, name in enumerate(strategy_names):
            if name in self._strategy_perf and len(self._strategy_perf[name]) >= 3:
                recent = self._strategy_perf[name][-5:]
                avg_pnl = np.mean(recent)
                win_rate = sum(1 for p in recent if p > 0) / len(recent)
                score = avg_pnl * 0.6 + win_rate * 0.4
                adjustment = np.clip(score * 0.03, -0.02, 0.04)
                if idx < len(adapted):
                    adapted[idx] = max(0.05, adapted[idx] + adjustment)

        total = sum(adapted)
        if total > 0:
            adapted = [w / total for w in adapted]

        self._dynamic_weights[key] = adapted
        return adapted

    @staticmethod
    def _record_trade(trades: list, action: str, price: float, trade_shares: int,
                      commission: float, stamp_tax: float, date_str: str,
                      bar_index: int, reason: str, entry_price: float = 0.0) -> dict:
        revenue = trade_shares * price
        fee = max(revenue * commission, 5.0)
        stamp = revenue * stamp_tax
        total_fee = fee + stamp
        pnl = (price - entry_price) * trade_shares - total_fee if action == "sell" else 0.0
        trade = {
            "action": action,
            "symbol": "",
            "price": price,
            "shares": trade_shares,
            "amount": round(revenue, 2),
            "fee": round(total_fee, 2),
            "date": date_str,
            "bar_index": bar_index,
            "pnl": round(pnl, 2) if action == "sell" else 0.0,
            "reason": reason,
        }
        if action == "sell":
            trade["hold_days"] = 0
        trades.append(trade)
        return {"revenue": revenue, "total_fee": total_fee, "pnl": pnl}

    def _append_equity(self, equity_curve: list, cash: float, shares: int,
                        price: float) -> None:
        bar_equity = cash + (shares * price if shares > 0 else 0)
        equity_curve.append(bar_equity)
        if len(equity_curve) >= 2 and equity_curve[-2] > 0:
            daily_ret = (equity_curve[-1] - equity_curve[-2]) / equity_curve[-2]
            self._returns_history.append(daily_ret)
            if len(self._returns_history) > self._returns_history_max:
                self._returns_history = self._returns_history[-self._returns_history_max:]

    def run(self, df: pd.DataFrame) -> dict:
        if df is None or len(df) < 50:
            return {"error": "数据不足，至少需要50个交易日"}

        df = df.copy()
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df.sort_values("date").reset_index(drop=True)

        if len(df) < 50:
            return {"error": "数据不足，至少需要50个交易日"}

        regimes = classify_market_regime(df)

        c = df["close"].values.astype(float)
        h = df["high"].values.astype(float)
        low_arr = df["low"].values.astype(float)
        opens = df["open"].values.astype(float) if "open" in df.columns else c
        dates_col = df["date"].values if "date" in df.columns else np.arange(len(c))
        atr_full = calc_atr(h, low_arr, c, period=14)
        chandelier_long, chandelier_short = self._calc_chandelier(h, low_arr, c, atr_full)
        volumes = df["volume"].values.astype(float) if "volume" in df.columns else None
        amounts_col = df["amount"].values.astype(float) if "amount" in df.columns else None

        strategy_instances = {}
        for regime, alloc in STRATEGY_ALLOCATION.items():
            strategy_instances[regime] = [cls() for cls in alloc["strategies"]]

        n = len(c)
        precomputed_scores = self._precompute_scores(strategy_instances, df, n)

        # 多周期趋势一致性
        mtf_score = self._mtf_analyzer.get_trend_alignment(df)

        cash = float(self._initial_capital)
        shares = 0
        position = None
        equity_curve = [cash]
        trades = []
        buy_bar_set = set()
        sell_bar_set = set()
        last_sell_bar = -COOLDOWN_BARS - 1

        market_regime_labels = []
        strategy_allocation_records = []
        seen_regimes = set()

        returns_arr = np.diff(c) / np.where(c[:-1] > 0, c[:-1], 1)
        returns_arr = np.where(np.isfinite(returns_arr), returns_arr, 0)

        for i in range(1, n):
            regime = regimes[i]
            market_regime_labels.append(REGIME_LABELS.get(regime, "未知"))

            lookback_vol = min(i, 20)
            current_vol = float(np.std(returns_arr[max(0, i - lookback_vol):i]) * np.sqrt(252)) if i > 1 else 0
            current_trend = float((c[i] - c[max(0, i - 20)]) / c[max(0, i - 20)]) if c[max(0, i - 20)] > 0 else 0

            alloc = STRATEGY_ALLOCATION.get(regime, {"strategies": [], "weights": []})
            if regime not in seen_regimes:
                seen_regimes.add(regime)
                strategy_names = [type(s).__name__ for s in strategy_instances.get(regime, [])]
                weights = alloc.get("weights", [])
                alloc_items = []
                for j, sname in enumerate(strategy_names):
                    w = weights[j] if j < len(weights) else 0
                    alloc_items.append({"name": sname, "weight": round(w, 4)})
                strategy_allocation_records.append({
                    "regime": regime.value,
                    "name": REGIME_LABELS.get(regime, ""),
                    "strategies": alloc_items,
                })

            if regime == MarketRegime.LOW_VOLATILITY_CONSOLIDATION:
                if position is not None:
                    current_price = c[i]
                    atr_val = atr_full[i] if not np.isnan(atr_full[i]) else c[i] * 0.02
                    ch_stop_val = chandelier_long[i] if not np.isnan(chandelier_long[i]) else 0
                    trailing_stop = current_price - ATR_STOP_MULTIPLIER * 1.5 * atr_val
                    if trailing_stop > position.get("trailing_stop", 0):
                        position["trailing_stop"] = trailing_stop
                    if ch_stop_val > position.get("chandelier_stop", 0):
                        position["chandelier_stop"] = ch_stop_val

                    should_sell = False
                    sell_reason = ""
                    if current_price <= position["trailing_stop"]:
                        should_sell = True
                        sell_reason = f"低波动收紧止损(止损价={position['trailing_stop']:.2f})"
                    elif position.get("chandelier_stop") and current_price <= position["chandelier_stop"]:
                        should_sell = True
                        sell_reason = f"Chandelier止损(止损价={position['chandelier_stop']:.2f})"

                    if should_sell:
                        date_str = str(dates_col[i])[:10] if i < len(dates_col) else ""
                        result = self._record_trade(
                            trades, "sell", current_price, shares,
                            self._commission, self._stamp_tax, date_str, i,
                            sell_reason, position["entry_price"])
                        cash += result["revenue"] - result["total_fee"]
                        trades[-1]["hold_days"] = i - position["entry_idx"]
                        sell_bar_set.add(i)
                        last_sell_bar = i
                        shares = 0
                        position = None

            buy_score = 0.0
            sell_score = 0.0
            buy_weight = 0.0
            sell_weight = 0.0
            strong_sell = False
            best_buy_idx = -1
            best_buy_contrib = 0.0

            instances = strategy_instances.get(regime, [])
            weights = self._adapt_strategy_weights(regime, alloc, current_vol, current_trend)
            regime_scores = precomputed_scores.get(regime, {})

            for idx, strategy in enumerate(instances):
                w = weights[idx] if idx < len(weights) else 0.1
                name = type(strategy).__name__
                bar_scores = regime_scores.get(name)
                score = bar_scores[i] if bar_scores is not None else 0.0
                if score > 0:
                    contrib = score * w
                    buy_score += contrib
                    buy_weight += w
                    if contrib > best_buy_contrib:
                        best_buy_contrib = contrib
                        best_buy_idx = idx
                elif score < 0:
                    sell_score += abs(score) * w
                    sell_weight += w
                if score < -0.7:
                    strong_sell = True

            if buy_weight > 0:
                buy_score /= buy_weight
            if sell_weight > 0:
                sell_score /= sell_weight

            if position is not None:
                current_price = c[i]
                atr_val = atr_full[i] if not np.isnan(atr_full[i]) else c[i] * 0.02
                trailing_stop = current_price - ATR_STOP_MULTIPLIER * atr_val
                if trailing_stop > position.get("trailing_stop", 0):
                    position["trailing_stop"] = trailing_stop

                if not np.isnan(chandelier_long[i]):
                    ch_stop = chandelier_long[i]
                    if ch_stop > position.get("chandelier_stop", 0):
                        position["chandelier_stop"] = ch_stop

                peak_price = position.get("peak_price", position["entry_price"])
                if current_price > peak_price:
                    position["peak_price"] = current_price
                drawdown_from_peak = (position["peak_price"] - current_price) / position["peak_price"] if position["peak_price"] > 0 else 0

                should_sell = False
                sell_reason = ""

                if current_price <= position["trailing_stop"]:
                    should_sell = True
                    sell_reason = f"ATR追踪止损(止损价={position['trailing_stop']:.2f})"
                elif position.get("chandelier_stop") and current_price <= position["chandelier_stop"]:
                    should_sell = True
                    sell_reason = f"Chandelier Exit止损(止损价={position['chandelier_stop']:.2f})"
                elif drawdown_from_peak >= MAX_DRAWDOWN_PROTECTION:
                    should_sell = True
                    sell_reason = f"最大回撤保护(回撤={drawdown_from_peak * 100:.1f}%)"
                elif drawdown_from_peak >= PARTIAL_EXIT_DRAWDOWN and shares > 100:
                    partial_shares = int(shares * PARTIAL_EXIT_RATIO) // 100 * 100
                    if partial_shares >= 100:
                        fill_price = opens[i] if i < len(opens) and opens[i] > 0 else current_price
                        if fill_price <= 0:
                            fill_price = current_price
                        date_str = str(dates_col[i])[:10] if i < len(dates_col) else ""
                        result = self._record_trade(
                            trades, "sell", fill_price, partial_shares,
                            self._commission, self._stamp_tax, date_str, i,
                            f"部分止盈(回撤={drawdown_from_peak * 100:.1f}%)",
                            position["entry_price"])
                        cash += result["revenue"] - result["total_fee"]
                        shares -= partial_shares
                        position["shares"] = shares
                        trades[-1]["hold_days"] = i - position["entry_idx"]
                        sell_bar_set.add(i)
                elif strong_sell or sell_score > SELL_THRESHOLD:
                    should_sell = True
                    sell_reason = f"融合卖出信号(卖出分数={sell_score:.2f})"

                if should_sell:
                    fill_price = opens[i] if i < len(opens) and opens[i] > 0 else current_price
                    if fill_price <= 0:
                        fill_price = current_price

                    sell_shares = shares
                    if volumes is not None:
                        bar_vol = volumes[i] if i < len(volumes) else 0
                        if not np.isnan(bar_vol) and bar_vol > 0:
                            if amounts_col is not None:
                                bar_amount = amounts_col[i] if i < len(amounts_col) else 0
                                if not np.isnan(bar_amount) and bar_amount > 0:
                                    max_amount = bar_amount * 0.25
                                    max_shares_by_amount = int(max_amount / fill_price / 100) * 100
                                    if max_shares_by_amount > 0 and sell_shares > max_shares_by_amount:
                                        sell_shares = max_shares_by_amount
                                else:
                                    max_amount_est = bar_vol * fill_price * 0.25
                                    max_shares_by_amount = int(max_amount_est / fill_price / 100) * 100
                                    if max_shares_by_amount > 0 and sell_shares > max_shares_by_amount:
                                        sell_shares = max_shares_by_amount
                            else:
                                max_amount_est = bar_vol * fill_price * 0.25
                                max_shares_by_amount = int(max_amount_est / fill_price / 100) * 100
                                if max_shares_by_amount > 0 and sell_shares > max_shares_by_amount:
                                    sell_shares = max_shares_by_amount

                    revenue = sell_shares * fill_price
                    date_str = str(dates_col[i])[:10] if i < len(dates_col) else ""
                    result = self._record_trade(
                        trades, "sell", fill_price, sell_shares,
                        self._commission, self._stamp_tax, date_str, i,
                        sell_reason, position["entry_price"])
                    cash += result["revenue"] - result["total_fee"]
                    trades[-1]["hold_days"] = i - position["entry_idx"]
                    sell_bar_set.add(i)
                    last_sell_bar = i
                    shares = max(0, shares - sell_shares)
                    if shares <= 0:
                        shares = 0
                        position = None

                    if best_buy_idx >= 0 and best_buy_idx < len(instances):
                        name = type(instances[best_buy_idx]).__name__
                        if name not in self._strategy_perf:
                            self._strategy_perf[name] = []
                        self._strategy_perf[name].append(result["pnl"])
                        if len(self._strategy_perf[name]) > 20:
                            self._strategy_perf[name] = self._strategy_perf[name][-20:]
                        reward = 1.0 if result["pnl"] > 0 else -1.0
                        q_adapter = self._get_q_adapter(regime, len(instances))
                        q_adapter.update(regime, current_vol, current_trend, best_buy_idx, reward)

            in_cooldown = (i - last_sell_bar) <= COOLDOWN_BARS

            if position is None and buy_score > BUY_THRESHOLD and not in_cooldown:
                adjusted_buy_score = buy_score
                if mtf_score > 0.3:
                    adjusted_buy_score = min(1.0, adjusted_buy_score * 1.5)
                elif mtf_score < -0.3:
                    adjusted_buy_score *= 0.5

                if i >= TREND_FILTER_LOOKBACK:
                    ma_long = float(np.mean(c[i - TREND_FILTER_LOOKBACK:i]))
                    if c[i] < ma_long * 0.95 and regime in (
                        MarketRegime.STRONG_TREND_DOWN, MarketRegime.MILD_TREND_DOWN,
                    ):
                        adjusted_buy_score *= 0.3

                if adjusted_buy_score < BUY_THRESHOLD:
                    self._append_equity(equity_curve, cash, shares, c[i])
                    continue

                fill_price = opens[i] if i < len(opens) and opens[i] > 0 else c[i]
                if fill_price <= 0:
                    fill_price = c[i]
                if fill_price <= 0:
                    self._append_equity(equity_curve, cash, shares, c[i])
                    continue

                if volumes is not None:
                    bar_vol = volumes[i] if i < len(volumes) else 0
                    if np.isnan(bar_vol) or bar_vol <= 0:
                        self._append_equity(equity_curve, cash, shares, c[i])
                        continue

                cvar_adj = self._cvar_position_adjustment()
                if cvar_adj <= 0:
                    self._append_equity(equity_curve, cash, shares, c[i])
                    continue

                vol_adj = 1.0
                if VOLATILITY_SCALING and current_vol > 0:
                    target_vol = 0.15
                    vol_adj = min(1.5, max(0.3, target_vol / current_vol))

                conviction_mult = min(1.5, adjusted_buy_score / BUY_THRESHOLD)
                if adjusted_buy_score > STRONG_BUY_THRESHOLD:
                    kelly = self._kelly_position(c[:i + 1])
                    alloc_pct = min(0.60, kelly * 1.2) * cvar_adj * conviction_mult * vol_adj
                else:
                    kelly = self._kelly_position(c[:i + 1])
                    alloc_pct = min(0.40, kelly) * cvar_adj * conviction_mult * vol_adj

                current_equity = cash + (shares * c[i] if shares > 0 else 0)
                alloc_amount = current_equity * alloc_pct
                if alloc_amount > cash * 0.98:
                    alloc_amount = cash * 0.98

                lot_size = 100
                buy_shares = int(alloc_amount / fill_price / lot_size) * lot_size
                if buy_shares <= 0:
                    self._append_equity(equity_curve, cash, shares, c[i])
                    continue

                if volumes is not None and amounts_col is not None:
                    bar_amount = amounts_col[i] if i < len(amounts_col) else 0
                    if not np.isnan(bar_amount) and bar_amount > 0:
                        max_amount = bar_amount * 0.25
                        max_shares_by_amount = int(max_amount / fill_price / lot_size) * lot_size
                        if max_shares_by_amount > 0 and buy_shares > max_shares_by_amount:
                            buy_shares = max_shares_by_amount
                elif volumes is not None:
                    bar_vol_val = volumes[i] if i < len(volumes) else 0
                    if not np.isnan(bar_vol_val) and bar_vol_val > 0:
                        max_amount = bar_vol_val * fill_price * 0.25
                        max_shares_by_amount = int(max_amount / fill_price / lot_size) * lot_size
                        if max_shares_by_amount > 0 and buy_shares > max_shares_by_amount:
                            buy_shares = max_shares_by_amount

                if buy_shares <= 0:
                    self._append_equity(equity_curve, cash, shares, c[i])
                    continue

                amount = buy_shares * fill_price
                fee = max(amount * self._commission, 5.0)
                total_cost = amount + fee

                if total_cost > cash:
                    buy_shares = int(cash * 0.98 / fill_price / lot_size) * lot_size
                    if buy_shares <= 0:
                        self._append_equity(equity_curve, cash, shares, c[i])
                        continue
                    amount = buy_shares * fill_price
                    fee = max(amount * self._commission, 5.0)
                    total_cost = amount + fee

                cash -= total_cost
                shares += buy_shares

                atr_val = atr_full[i] if not np.isnan(atr_full[i]) else fill_price * 0.02
                trailing_stop = fill_price - ATR_STOP_MULTIPLIER * atr_val
                chandelier_stop = chandelier_long[i] if not np.isnan(chandelier_long[i]) else 0

                date_str = str(dates_col[i])[:10] if i < len(dates_col) else ""
                position = {
                    "entry_price": fill_price,
                    "shares": buy_shares,
                    "entry_idx": i,
                    "entry_date": date_str,
                    "trailing_stop": trailing_stop,
                    "peak_price": fill_price,
                    "chandelier_stop": chandelier_stop,
                }
                buy_bar_set.add(i)

                signal_label = "强力买入" if buy_score > STRONG_BUY_THRESHOLD else "买入"
                self._record_trade(
                    trades, "buy", fill_price, buy_shares,
                    self._commission, self._stamp_tax, date_str, i,
                    f"{signal_label}(融合分数={buy_score:.2f}, 市场状态={REGIME_LABELS.get(regime, '')})")

            self._append_equity(equity_curve, cash, shares, c[i])

        if position is not None and shares > 0:
            cash += shares * c[-1]
            shares = 0
            position = None

        dates_list = []
        for d in dates_col:
            ds = str(d)[:10] if hasattr(d, "__str__") else str(d)[:10]
            dates_list.append(ds)

        peak = equity_curve[0]
        eq_arr = np.array(equity_curve)
        peak_arr = np.maximum.accumulate(eq_arr)
        drawdown_curve = ((peak_arr - eq_arr) / np.where(peak_arr > 0, peak_arr, 1) * 100).tolist()
        max_dd = float(np.max(drawdown_curve))

        sell_trades = [t for t in trades if t["action"] == "sell"]
        total_trades = len(sell_trades)
        win_trades = sum(1 for t in sell_trades if t.get("pnl", 0) > 0)
        loss_trades = sum(1 for t in sell_trades if t.get("pnl", 0) <= 0)
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0

        total_win = sum(t.get("pnl", 0) for t in sell_trades if t.get("pnl", 0) > 0)
        total_loss = sum(abs(t.get("pnl", 0)) for t in sell_trades if t.get("pnl", 0) <= 0)
        profit_factor = (total_win / total_loss) if total_loss > 0 else 999 if total_win > 0 else 0

        avg_profit = np.mean([t["pnl"] for t in sell_trades if t.get("pnl", 0) > 0]) if win_trades > 0 else 0
        avg_loss = np.mean([abs(t["pnl"]) for t in sell_trades if t.get("pnl", 0) <= 0]) if loss_trades > 0 else 0

        hold_days_list = [t.get("hold_days", 0) for t in sell_trades if t.get("hold_days")]
        avg_hold_days = np.mean(hold_days_list) if hold_days_list else 0

        total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0] * 100 if equity_curve[0] > 0 else 0
        trading_days = len(equity_curve)
        annual_return = ((1 + total_return / 100) ** (252 / max(trading_days, 1)) - 1) * 100 if trading_days > 0 else 0
        calmar_ratio = (annual_return / max_dd) if max_dd > 0 else 0

        returns = self._returns_history if self._returns_history else []
        if not returns:
            eq_arr_full = np.array(equity_curve)
            if len(eq_arr_full) > 1:
                mask = eq_arr_full[:-1] > 0
                ret = np.where(mask, (eq_arr_full[1:] - eq_arr_full[:-1]) / eq_arr_full[:-1], 0)
                returns = ret.tolist()

        sharpe = 0
        if returns:
            avg_ret = np.mean(returns)
            std_ret = np.std(returns)
            if std_ret > 0:
                sharpe = avg_ret / std_ret * np.sqrt(252)

        sortino = 0.0
        if returns:
            ret_arr = np.array(returns)
            avg_ret = np.mean(ret_arr)
            neg_mask = ret_arr < 0
            if np.any(neg_mask):
                downside_std = np.std(ret_arr[neg_mask])
                if downside_std > 0:
                    sortino = (avg_ret * 252) / (downside_std * np.sqrt(252))

        max_consec_losses = 0
        consec_count = 0
        for t in sell_trades:
            if t.get("pnl", 0) < 0:
                consec_count += 1
                if consec_count > max_consec_losses:
                    max_consec_losses = consec_count
            else:
                consec_count = 0

        benchmark_return = (c[-1] - c[0]) / c[0] * 100 if c[0] > 0 else 0
        alpha = total_return - benchmark_return

        bench_returns = []
        c_arr = np.array(c)
        if len(c_arr) > 1:
            mask = c_arr[:-1] > 0
            bench_ret = np.where(mask, (c_arr[1:] - c_arr[:-1]) / c_arr[:-1], 0)
            bench_returns = bench_ret.tolist()

        beta = 1.0
        if len(returns) > 1 and len(bench_returns) > 1:
            min_len = min(len(returns), len(bench_returns))
            r = np.array(returns[:min_len])
            b = np.array(bench_returns[:min_len])
            bench_var = np.var(b)
            if bench_var > 0:
                beta = float(np.cov(r, b)[0][1] / bench_var)

        max_points = 500
        ds_indices = None
        if len(equity_curve) > max_points:
            step = len(equity_curve) / max_points
            indices = [int(i * step) for i in range(max_points)]
            if indices[-1] != len(equity_curve) - 1:
                indices.append(len(equity_curve) - 1)
            ds_indices = indices
            equity_curve = [equity_curve[i] for i in indices]
            drawdown_curve = [drawdown_curve[i] for i in indices]
            dates_out = [dates_list[i] for i in indices]
        else:
            dates_out = dates_list

        kline_with_signals = []
        vols = df["volume"].values.astype(float) if "volume" in df.columns else np.zeros(len(c))
        for idx in range(len(c)):
            item = {
                "date": dates_list[idx] if idx < len(dates_list) else "",
                "open": float(opens[idx]) if idx < len(opens) else 0,
                "close": float(c[idx]),
                "high": float(h[idx]) if idx < len(h) else 0,
                "low": float(low_arr[idx]) if idx < len(low_arr) else 0,
                "volume": float(vols[idx]),
            }
            if idx in buy_bar_set:
                item["signal"] = "buy"
            elif idx in sell_bar_set:
                item["signal"] = "sell"
            kline_with_signals.append(item)

        first_close = float(c[0]) if c[0] > 0 else 1.0
        equity_curve_out = []
        for i in range(min(len(dates_out), len(equity_curve))):
            equity_curve_out.append({"date": dates_out[i], "value": equity_curve[i]})

        benchmark_curve = []
        if ds_indices is not None:
            for idx in ds_indices:
                if idx < len(c):
                    benchmark_curve.append({"date": dates_list[idx], "value": self._initial_capital * (float(c[idx]) / first_close)})
        else:
            for i in range(min(len(dates_out), len(c))):
                benchmark_curve.append({"date": dates_out[i], "value": self._initial_capital * (float(c[i]) / first_close)})

        return {
            "strategy_name": "自适应量化策略引擎",
            "total_return": round(total_return, 4) if total_return else 0,
            "annual_return": round(annual_return, 4) if annual_return else 0,
            "max_drawdown": round(max_dd, 4) if max_dd else 0,
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "calmar_ratio": round(calmar_ratio, 2),
            "win_rate": round(win_rate, 2) if win_rate else 0,
            "profit_factor": round(profit_factor, 2) if profit_factor != 999 else 999,
            "total_trades": total_trades,
            "win_trades": win_trades,
            "loss_trades": loss_trades,
            "avg_hold_days": round(avg_hold_days, 1),
            "max_consecutive_losses": max_consec_losses,
            "benchmark_return": round(benchmark_return, 4) if benchmark_return else 0,
            "alpha": round(alpha, 4) if alpha else 0,
            "beta": round(beta, 2),
            "cvar_95": round(calc_cvar(np.array(self._returns_history[-60:]), 0.95), 4) if len(self._returns_history) >= 20 else 0,
            "mtf_alignment": round(mtf_score, 2),
            "equity_curve": equity_curve_out,
            "benchmark_curve": benchmark_curve,
            "trades": trades[-200:] if trades else [],
            "kline_with_signals": kline_with_signals[-500:] if kline_with_signals else [],
            "market_regime_labels": market_regime_labels,
            "strategy_allocation": strategy_allocation_records,
        }
