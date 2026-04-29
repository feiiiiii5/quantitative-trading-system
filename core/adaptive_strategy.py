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


REGIME_LABELS = {
    MarketRegime.STRONG_TREND_UP: "强趋势上涨",
    MarketRegime.MILD_TREND_UP: "温和趋势上涨",
    MarketRegime.HIGH_VOLATILITY_RANGE: "高波动震荡",
    MarketRegime.LOW_VOLATILITY_CONSOLIDATION: "低波动盘整",
    MarketRegime.MILD_TREND_DOWN: "温和趋势下跌",
    MarketRegime.STRONG_TREND_DOWN: "强趋势下跌",
}

STRATEGY_ALLOCATION = {
    MarketRegime.STRONG_TREND_UP: {
        "strategies": [AdaptiveTrendFollowingStrategy, MultiFactorConfluenceStrategy, SuperTrendStrategy, MomentumStrategy],
        "weights": [0.30, 0.30, 0.25, 0.15],
    },
    MarketRegime.MILD_TREND_UP: {
        "strategies": [MultiFactorConfluenceStrategy, DualMAStrategy, MACDStrategy, VolatilitySqueezeBreakoutStrategy],
        "weights": [0.30, 0.25, 0.25, 0.20],
    },
    MarketRegime.HIGH_VOLATILITY_RANGE: {
        "strategies": [MeanReversionProStrategy, VolatilitySqueezeBreakoutStrategy, KDJStrategy, RSIMeanReversionStrategy],
        "weights": [0.30, 0.30, 0.20, 0.20],
    },
    MarketRegime.LOW_VOLATILITY_CONSOLIDATION: {
        "strategies": [VolatilitySqueezeBreakoutStrategy, MeanReversionProStrategy],
        "weights": [0.60, 0.40],
    },
    MarketRegime.MILD_TREND_DOWN: {
        "strategies": [SuperTrendStrategy, MACDStrategy, MeanReversionProStrategy],
        "weights": [0.35, 0.35, 0.30],
    },
    MarketRegime.STRONG_TREND_DOWN: {
        "strategies": [AdaptiveTrendFollowingStrategy, SuperTrendStrategy],
        "weights": [0.55, 0.45],
    },
}

BUY_THRESHOLD = 0.60
STRONG_BUY_THRESHOLD = 0.75
SELL_THRESHOLD = 0.55
ATR_STOP_MULTIPLIER = 2.5
MAX_DRAWDOWN_PROTECTION = 0.08
KELLY_FRACTION = 0.5
CHANDELIER_PERIOD = 22
CHANDELIER_MULT = 3.0


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
            price = c[i]
            deviation = (price - ma20) / ma20 if ma20 > 0 else 0

            trend_strength = adx_val
            is_strong_trend = trend_strength > 30
            is_mild_trend = trend_strength > 20
            is_ranging = trend_strength < 20

            if is_strong_trend:
                if deviation > 0.02:
                    regimes[i] = MarketRegime.STRONG_TREND_UP
                elif deviation > 0:
                    regimes[i] = MarketRegime.STRONG_TREND_UP
                elif deviation < -0.02:
                    regimes[i] = MarketRegime.STRONG_TREND_DOWN
                else:
                    regimes[i] = MarketRegime.STRONG_TREND_DOWN
            elif is_mild_trend:
                if deviation > 0.005:
                    regimes[i] = MarketRegime.MILD_TREND_UP
                elif deviation < -0.005:
                    regimes[i] = MarketRegime.MILD_TREND_DOWN
                elif deviation > 0:
                    regimes[i] = MarketRegime.MILD_TREND_UP
                else:
                    regimes[i] = MarketRegime.MILD_TREND_DOWN
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

    def _kelly_position(self, c: np.ndarray, lookback: int = 60) -> float:
        return calc_kelly_fraction(c, lookback, half_kelly=KELLY_FRACTION)

    def _calc_chandelier(self, h: np.ndarray, low_arr: np.ndarray, c: np.ndarray,
                          atr: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        return calc_chandelier_exit(h, low_arr, c, atr, CHANDELIER_PERIOD, CHANDELIER_MULT)

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

    def _adapt_strategy_weights(self, regime: MarketRegime, alloc: dict):
        key = regime.value
        if key not in self._dynamic_weights:
            self._dynamic_weights[key] = list(alloc.get("weights", []))
            return self._dynamic_weights[key]

        base_weights = alloc.get("weights", [])
        strategy_names = [cls.__name__ for cls in alloc.get("strategies", [])]
        adapted = list(base_weights)

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

        cash = float(self._initial_capital)
        shares = 0
        position = None
        equity_curve = [cash]
        trades = []
        buy_bar_set = set()
        sell_bar_set = set()

        market_regime_labels = []
        strategy_allocation_records = []
        seen_regimes = set()

        for i in range(1, n):
            regime = regimes[i]
            market_regime_labels.append(REGIME_LABELS.get(regime, "未知"))

            if regime not in seen_regimes:
                seen_regimes.add(regime)
                alloc = STRATEGY_ALLOCATION.get(regime, {"strategies": [], "weights": []})
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
                        revenue = shares * current_price
                        fee = max(revenue * self._commission, 5.0)
                        stamp = revenue * self._stamp_tax
                        total_fee = fee + stamp
                        pnl = (current_price - position["entry_price"]) * shares - total_fee
                        cash += revenue - total_fee
                        date_str = str(dates_col[i])[:10] if i < len(dates_col) else ""
                        hold_days = i - position["entry_idx"]
                        trades.append({
                            "action": "sell",
                            "symbol": "",
                            "price": current_price,
                            "shares": shares,
                            "amount": round(revenue, 2),
                            "fee": round(total_fee, 2),
                            "date": date_str,
                            "bar_index": i,
                            "pnl": round(pnl, 2),
                            "hold_days": hold_days,
                            "reason": sell_reason,
                        })
                        sell_bar_set.add(i)
                        shares = 0
                        position = None

                bar_equity = cash
                equity_curve.append(bar_equity)
                continue

            buy_score = 0.0
            sell_score = 0.0
            total_weight = 0.0
            strong_sell = False

            instances = strategy_instances.get(regime, [])
            weights = self._adapt_strategy_weights(regime, alloc)
            regime_scores = precomputed_scores.get(regime, {})

            for idx, strategy in enumerate(instances):
                w = weights[idx] if idx < len(weights) else 0.1
                total_weight += w
                name = type(strategy).__name__
                bar_scores = regime_scores.get(name)
                score = bar_scores[i] if bar_scores is not None else 0.0
                if score >= 0:
                    buy_score += score * w
                else:
                    sell_score += abs(score) * w
                if score < -0.7:
                    strong_sell = True

            if total_weight > 0:
                buy_score /= total_weight
                sell_score /= total_weight

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
                    fee = max(revenue * self._commission, 5.0)
                    stamp = revenue * self._stamp_tax
                    total_fee = fee + stamp
                    pnl = (fill_price - position["entry_price"]) * sell_shares - total_fee
                    cash += revenue - total_fee
                    date_str = str(dates_col[i])[:10] if i < len(dates_col) else ""
                    hold_days = i - position["entry_idx"]
                    trades.append({
                        "action": "sell",
                        "symbol": "",
                        "price": fill_price,
                        "shares": sell_shares,
                        "amount": round(revenue, 2),
                        "fee": round(total_fee, 2),
                        "date": date_str,
                        "bar_index": i,
                        "pnl": round(pnl, 2),
                        "hold_days": hold_days,
                        "reason": sell_reason,
                    })
                    sell_bar_set.add(i)
                    shares -= sell_shares
                    if shares <= 0:
                        shares = 0
                        position = None

                    for idx, strategy in enumerate(instances):
                        name = type(strategy).__name__
                        if name not in self._strategy_perf:
                            self._strategy_perf[name] = []
                        self._strategy_perf[name].append(pnl)
                        if len(self._strategy_perf[name]) > 20:
                            self._strategy_perf[name] = self._strategy_perf[name][-20:]

            if position is None and buy_score > BUY_THRESHOLD:
                fill_price = opens[i] if i < len(opens) and opens[i] > 0 else c[i]
                if fill_price <= 0:
                    fill_price = c[i]
                if fill_price <= 0:
                    bar_equity = cash
                    equity_curve.append(bar_equity)
                    continue

                if volumes is not None:
                    bar_vol = volumes[i] if i < len(volumes) else 0
                    if np.isnan(bar_vol) or bar_vol <= 0:
                        bar_equity = cash
                        equity_curve.append(bar_equity)
                        continue

                if buy_score > STRONG_BUY_THRESHOLD:
                    kelly = self._kelly_position(c[:i + 1])
                    alloc_pct = min(0.60, kelly * 1.2)
                else:
                    kelly = self._kelly_position(c[:i + 1])
                    alloc_pct = min(0.40, kelly)

                alloc_amount = equity_curve[-1] * alloc_pct
                if alloc_amount > cash * 0.98:
                    alloc_amount = cash * 0.98

                lot_size = 100
                buy_shares = int(alloc_amount / fill_price / lot_size) * lot_size
                if buy_shares <= 0:
                    bar_equity = cash
                    equity_curve.append(bar_equity)
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
                    bar_equity = cash
                    equity_curve.append(bar_equity)
                    continue

                amount = buy_shares * fill_price
                fee = max(amount * self._commission, 5.0)
                total_cost = amount + fee

                if total_cost > cash:
                    buy_shares = int(cash * 0.98 / fill_price / lot_size) * lot_size
                    if buy_shares <= 0:
                        bar_equity = cash
                        equity_curve.append(bar_equity)
                        continue
                    amount = buy_shares * fill_price
                    fee = max(amount * self._commission, 5.0)
                    total_cost = amount + fee

                cash -= total_cost
                shares = buy_shares

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
                trades.append({
                    "action": "buy",
                    "symbol": "",
                    "price": fill_price,
                    "shares": buy_shares,
                    "amount": round(amount, 2),
                    "fee": round(fee, 2),
                    "date": date_str,
                    "bar_index": i,
                    "reason": f"{signal_label}(融合分数={buy_score:.2f}, 市场状态={REGIME_LABELS.get(regime, '')})",
                })

            bar_equity = cash + (shares * c[i] if shares > 0 else 0)
            equity_curve.append(bar_equity)

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

        returns = []
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
            "total_return": total_return / 100 if total_return else 0,
            "annual_return": annual_return / 100 if annual_return else 0,
            "max_drawdown": max_dd / 100 if max_dd else 0,
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "calmar_ratio": round(calmar_ratio, 2),
            "win_rate": win_rate / 100 if win_rate else 0,
            "profit_factor": round(profit_factor, 2) if profit_factor != 999 else 999,
            "total_trades": total_trades,
            "win_trades": win_trades,
            "loss_trades": loss_trades,
            "avg_hold_days": round(avg_hold_days, 1),
            "max_consecutive_losses": max_consec_losses,
            "benchmark_return": benchmark_return / 100 if benchmark_return else 0,
            "alpha": round(alpha, 2),
            "beta": round(beta, 2),
            "equity_curve": equity_curve_out,
            "benchmark_curve": benchmark_curve,
            "trades": trades,
            "kline_with_signals": kline_with_signals,
            "market_regime_labels": market_regime_labels,
            "strategy_allocation": strategy_allocation_records,
        }
