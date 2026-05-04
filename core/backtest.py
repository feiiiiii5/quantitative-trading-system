import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from core.strategies import BaseStrategy, CompositeStrategy, StrategyResult, SignalType, STRATEGY_REGISTRY
from core.events import EventBus, Event, EventType
from core.risk_manager import EnhancedRiskManager

logger = logging.getLogger(__name__)


class RealisticCostModel:
    def __init__(
        self,
        commission: float = 0.0002,
        stamp_tax: float = 0.001,
        transfer_fee_sh: float = 0.00001,
        market_impact_pct: float = 0.0005,
        financing_rate: float = 0.045,
        min_commission: float = 5.0,
    ):
        self.commission = commission
        self.stamp_tax = stamp_tax
        self.transfer_fee_sh = transfer_fee_sh
        self.market_impact_pct = market_impact_pct
        self.financing_rate = financing_rate / 365
        self.min_commission = min_commission

    def calc_buy_cost(self, price: float, shares: int, amount: float = 0,
                      daily_amount: float = 0, is_sh: bool = False) -> dict:
        if amount <= 0:
            amount = price * shares
        fee = max(amount * self.commission, self.min_commission)
        transfer = shares * self.transfer_fee_sh if is_sh else 0.0
        impact = 0.0
        if daily_amount > 0:
            participation = amount / daily_amount
            impact = amount * self.market_impact_pct * np.sqrt(participation)
        total = fee + transfer + impact
        return {"commission": round(fee, 2), "transfer_fee": round(transfer, 2),
                "market_impact": round(impact, 2), "total": round(total, 2)}

    def calc_sell_cost(self, price: float, shares: int, amount: float = 0,
                       daily_amount: float = 0, is_sh: bool = False) -> dict:
        if amount <= 0:
            amount = price * shares
        fee = max(amount * self.commission, self.min_commission)
        stamp = amount * self.stamp_tax
        transfer = shares * self.transfer_fee_sh if is_sh else 0.0
        impact = 0.0
        if daily_amount > 0:
            participation = amount / daily_amount
            impact = amount * self.market_impact_pct * np.sqrt(participation)
        total = fee + stamp + transfer + impact
        return {"commission": round(fee, 2), "stamp_tax": round(stamp, 2),
                "transfer_fee": round(transfer, 2), "market_impact": round(impact, 2),
                "total": round(total, 2)}

    def calc_financing_cost(self, borrowed: float, days: int) -> float:
        return round(borrowed * self.financing_rate * days, 2)


def _simulate_call_auction_fill(open_price: float, rng: np.random.Generator = None) -> float:
    """模拟开盘集合竞价：以开盘价±0.1%的随机价格成交"""
    if rng is None:
        rng = np.random.default_rng()
    noise = rng.uniform(-0.001, 0.001)
    return open_price * (1 + noise)


def _simulate_twap_fill(price: float, shares: int, daily_amount: float,
                         n_slices: int = 4, rng: np.random.Generator = None) -> float:
    if daily_amount <= 0 or shares * price < daily_amount * 0.01:
        return price
    if rng is None:
        rng = np.random.default_rng()
    total_fill = 0.0
    per_slice = shares // n_slices
    for s in range(n_slices):
        slice_shares = per_slice if s < n_slices - 1 else shares - per_slice * s
        noise = rng.normal(0, 0.001)
        total_fill += slice_shares * price * (1 + noise)
    return total_fill / shares


def _check_limit_price(prev_close: float, price: float, is_buy: bool,
                       limit_pct: float = 0.10) -> tuple[bool, float]:
    if prev_close <= 0:
        return True, 1.0
    upper = prev_close * (1 + limit_pct)
    lower = prev_close * (1 - limit_pct)
    if is_buy and price >= upper:
        fill_prob = max(0.1, 1.0 - (price - upper) / (upper * 0.01 + 1e-9))
        return False, min(fill_prob, 0.9)
    if not is_buy and price <= lower:
        fill_prob = max(0.1, 1.0 - (lower - price) / (lower * 0.01 + 1e-9))
        return False, min(fill_prob, 0.9)
    return True, 1.0


def _get_limit_pct(symbol: str) -> float:
    if symbol.startswith(("3", "68")):
        return 0.20
    if symbol.startswith("8"):
        return 0.30
    return 0.10


@dataclass
class BacktestResult:
    strategy_name: str
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    calmar_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    avg_hold_days: float = 0.0
    benchmark_return: float = 0.0
    alpha: float = 0.0
    beta: float = 1.0
    equity_curve: list = field(default_factory=list)
    drawdown_curve: list = field(default_factory=list)
    dates: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    kline_with_signals: list = field(default_factory=list)
    max_points: int = 0
    sortino_ratio: float = 0.0
    max_consecutive_losses: int = 0
    omega_ratio: float = 0.0
    tail_ratio: float = 0.0
    information_ratio: float = 0.0
    recovery_factor: float = 0.0
    avg_mae: float = 0.0
    avg_mfe: float = 0.0
    cvar_95: float = 0.0
    annual_volatility: float = 0.0
    downside_deviation: float = 0.0
    monthly_returns: list = field(default_factory=list)
    monte_carlo: dict = field(default_factory=dict)
    optimization: dict = field(default_factory=dict)
    expectancy: float = 0.0
    payoff_ratio: float = 0.0

    def downsample_curves(self, max_points: int = 500) -> None:
        if max_points <= 0 or len(self.equity_curve) <= max_points:
            return
        step = len(self.equity_curve) / max_points
        indices = [int(i * step) for i in range(max_points)]
        if indices[-1] != len(self.equity_curve) - 1:
            indices.append(len(self.equity_curve) - 1)
        self.equity_curve = [self.equity_curve[i] for i in indices]
        self.drawdown_curve = [self.drawdown_curve[i] for i in indices]
        self.dates = [self.dates[i] for i in indices]


class BacktestEngine:
    def __init__(self, initial_capital: float = 1000000, commission: float = 0.0003, stamp_tax: float = 0.001,
                 slippage_pct: float = 0.001, market_impact_pct: float = 0.0005,
                 cost_model: RealisticCostModel = None, enable_twap: bool = True,
                 enable_limit_check: bool = True, use_vectorized: bool = True,
                 event_bus: Optional[EventBus] = None, risk_manager: Optional[EnhancedRiskManager] = None):
        self._initial_capital = initial_capital
        self._slippage_pct = slippage_pct
        self._cost_model = cost_model or RealisticCostModel(
            commission=commission, stamp_tax=stamp_tax, market_impact_pct=market_impact_pct)
        self._enable_twap = enable_twap
        self._enable_limit_check = enable_limit_check
        self._use_vectorized = use_vectorized
        self._rng = np.random.default_rng(42)
        self._event_bus = event_bus or EventBus()
        self._risk_manager = risk_manager or EnhancedRiskManager(initial_capital=initial_capital)

    def run(self, strategy: BaseStrategy, df: pd.DataFrame, symbol: str = "") -> BacktestResult:
        if df is None or len(df) < 10:
            return BacktestResult(strategy_name=strategy.name)

        df = df.copy()
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df.sort_values("date").reset_index(drop=True)

        if len(df) < 10:
            return BacktestResult(strategy_name=strategy.name)

        self._event_bus.publish(Event(EventType.INIT, {"strategy": strategy.name}))

        try:
            if self._use_vectorized and hasattr(strategy, 'populate_indicators'):
                has_custom = strategy.__class__.populate_indicators is not BaseStrategy.populate_indicators
                if has_custom:
                    result = strategy.generate_signals_vectorized(df)
                else:
                    result = strategy.generate_signals(df)
            else:
                result = strategy.generate_signals(df)
        except Exception as e:
            logger.error(f"Strategy {strategy.name} generate_signals failed: {e}")
            return BacktestResult(strategy_name=strategy.name)

        if not result.signals:
            return self._build_result(strategy.name, df, [], [], result)

        buy_signals = sorted(
            [s for s in result.signals if s.signal_type == SignalType.BUY],
            key=lambda s: s.bar_index,
        )
        sell_signals = sorted(
            [s for s in result.signals if s.signal_type == SignalType.SELL],
            key=lambda s: s.bar_index,
        )

        # 买卖信号优先级控制：同一K线同时出现买卖信号时，按优先级过滤
        sell_bars = {s.bar_index for s in sell_signals}
        buy_bars = {s.bar_index for s in buy_signals}
        conflicting_bars = sell_bars & buy_bars
        if conflicting_bars:
            # 默认卖信号优先：同一K线有买卖冲突时，保留卖信号，移除买信号
            buy_signals = [s for s in buy_signals if s.bar_index not in conflicting_bars]
            logger.debug(
                f"Signal priority: removed {len(conflicting_bars)} conflicting buy signal(s) on bars {conflicting_bars}"
            )

        return self._build_result(strategy.name, df, buy_signals, sell_signals, result, symbol)

    def run_multi(self, strategies: list[BaseStrategy], df: pd.DataFrame) -> dict[str, BacktestResult]:
        results = {}
        for strategy in strategies:
            try:
                results[strategy.name] = self.run(strategy, df)
            except Exception as e:
                logger.error(f"Backtest run_multi failed for {strategy.name}: {e}")
                results[strategy.name] = BacktestResult(strategy_name=strategy.name)
        return results

    def monte_carlo_analysis(self, result: BacktestResult, n_simulations: int = 1000) -> dict:
        sell_trades = [t for t in result.trades if t.get("action") == "sell"]
        if not sell_trades:
            return {"error": "交易样本不足，无法进行蒙特卡洛分析"}

        pnl = np.array([float(t.get("pnl", 0)) for t in sell_trades], dtype=float)
        if len(pnl) < 2:
            return {"error": "交易样本不足，无法进行蒙特卡洛分析"}

        rng = np.random.default_rng(42)
        finals = []
        max_dds = []
        sharpes = []
        all_curves = []
        for _ in range(max(1, int(n_simulations))):
            sampled = rng.choice(pnl, size=len(pnl), replace=True)
            curve = self._initial_capital + np.cumsum(sampled)
            peak = np.maximum.accumulate(curve)
            dd = np.where(peak > 0, (peak - curve) / peak * 100, 0)
            finals.append(float(curve[-1]))
            max_dds.append(float(np.max(dd)))
            trade_ret = sampled / max(self._initial_capital, 1)
            std = np.std(trade_ret)
            sharpes.append(float(np.mean(trade_ret) / std) if std > 0 else 0.0)
            all_curves.append(curve)

        n_sample_paths = min(30, n_simulations)
        sample_indices = rng.choice(len(all_curves), size=min(n_sample_paths, len(all_curves)), replace=False)
        paths = []
        for idx in sample_indices:
            raw = all_curves[idx]
            normalized = (raw / self._initial_capital).tolist()
            paths.append(normalized)

        final_arr = np.array(finals)
        dd_arr = np.array(max_dds)
        sharpe_arr = np.array(sharpes)
        sim_sharpe_median = float(np.median(sharpe_arr)) if len(sharpe_arr) else 0.0
        robustness = result.sharpe_ratio / sim_sharpe_median if abs(sim_sharpe_median) > 1e-9 else 0.0
        return {
            "paths": paths,
            "final_equity_p5": round(float(np.percentile(final_arr, 5)), 2),
            "final_equity_p50": round(float(np.percentile(final_arr, 50)), 2),
            "final_equity_p95": round(float(np.percentile(final_arr, 95)), 2),
            "max_drawdown_p5": round(float(np.percentile(dd_arr, 5)), 2),
            "max_drawdown_p50": round(float(np.percentile(dd_arr, 50)), 2),
            "max_drawdown_p95": round(float(np.percentile(dd_arr, 95)), 2),
            "sharpe_p50": round(sim_sharpe_median, 2),
            "robustness_score": round(float(robustness), 2),
        }

    def sensitivity_analysis(self, strategy_cls, df: pd.DataFrame,
                             base_params: dict, param_ranges: dict = None) -> dict:
        base_params = base_params or {}
        param_ranges = param_ranges or strategy_cls.get_param_space()
        if not param_ranges or df is None or df.empty:
            return {"parameters": {}, "heatmap": [], "recommendation": {}}

        output = {}
        for name, spec in param_ranges.items():
            base_val = base_params.get(name, (spec.get("min", 0) + spec.get("max", 0)) / 2)
            if not isinstance(base_val, (int, float)):
                continue
            low = max(spec.get("min", base_val * 0.8), base_val * 0.8)
            high = min(spec.get("max", base_val * 1.2), base_val * 1.2)
            values = np.linspace(low, high, 5)
            points = []
            sharpes = []
            for value in values:
                params = dict(base_params)
                params[name] = int(round(value)) if isinstance(base_val, int) else round(float(value), 4)
                try:
                    result = self.run(strategy_cls(**params), df)
                    sharpe = float(result.sharpe_ratio)
                except Exception:
                    sharpe = 0.0
                sharpes.append(sharpe)
                points.append({"value": params[name], "sharpe_ratio": round(sharpe, 4)})
            param_range = high - low
            elasticity = (max(sharpes) - min(sharpes)) / param_range if sharpes and param_range > 1e-9 else 0.0
            output[name] = {"points": points, "elasticity": round(float(elasticity), 6)}

        heatmap = []
        names = list(output.keys())[:2]
        if len(names) == 2:
            x_name, y_name = names
            x_values = [p["value"] for p in output[x_name]["points"]]
            y_values = [p["value"] for p in output[y_name]["points"]]
            for xv in x_values:
                for yv in y_values:
                    params = dict(base_params)
                    params[x_name] = xv
                    params[y_name] = yv
                    try:
                        result = self.run(strategy_cls(**params), df)
                        sharpe = float(result.sharpe_ratio)
                    except Exception:
                        sharpe = 0.0
                    heatmap.append({"x": xv, "y": yv, "sharpe_ratio": round(sharpe, 4)})

        recommendation = {}
        for name, data in output.items():
            points = data.get("points", [])
            if points:
                best = max(points, key=lambda x: x["sharpe_ratio"])
                recommendation[name] = best["value"]
        return {"parameters": output, "heatmap": heatmap, "recommendation": recommendation}

    def _build_result(
        self,
        name: str,
        df: pd.DataFrame,
        buy_signals: list,
        sell_signals: list,
        strategy_result: StrategyResult,
        symbol: str = "",
    ) -> BacktestResult:
        closes = df["close"].values.astype(float) if "close" in df.columns else np.array([])
        opens = df["open"].values.astype(float) if "open" in df.columns else closes
        highs = df["high"].values.astype(float) if "high" in df.columns else closes
        lows = df["low"].values.astype(float) if "low" in df.columns else closes
        dates_col = df["date"].values if "date" in df.columns else np.arange(len(closes))

        if len(closes) < 2:
            return BacktestResult(strategy_name=name)

        n = len(closes)
        cash = float(self._initial_capital)
        shares = 0
        position = None
        equity_curve = [cash]
        trades = []
        buy_bar_set = set()
        sell_bar_set = set()
        lot_size = 100

        buy_idx = 0
        sell_idx = 0

        volumes = df["volume"].values.astype(float) if "volume" in df.columns else None
        amounts_col = df["amount"].values.astype(float) if "amount" in df.columns else None

        def _excursion(position_data: dict, exit_idx: int) -> tuple[float, float]:
            entry_price = float(position_data.get("entry_price", 0))
            entry_idx = int(position_data.get("entry_idx", exit_idx))
            if entry_price <= 0:
                return 0.0, 0.0
            if entry_idx < 0 or exit_idx < 0 or entry_idx >= n or exit_idx >= n:
                return 0.0, 0.0
            start = max(0, min(entry_idx, exit_idx))
            end = max(start, min(exit_idx, n - 1)) + 1
            low_window = lows[start:end] if len(lows) >= end else closes[start:end]
            high_window = highs[start:end] if len(highs) >= end else closes[start:end]
            finite_lows = low_window[np.isfinite(low_window)]
            finite_highs = high_window[np.isfinite(high_window)]
            if len(finite_lows) == 0 or len(finite_highs) == 0:
                return 0.0, 0.0
            mae = (float(np.min(finite_lows)) / entry_price - 1) * 100
            mfe = (float(np.max(finite_highs)) / entry_price - 1) * 100
            return round(mae, 2), round(mfe, 2)

        prev_closes = np.roll(closes, 1)
        prev_closes[0] = closes[0] if len(closes) > 0 else 0

        for i in range(1, n):
            while buy_idx < len(buy_signals) and buy_signals[buy_idx].bar_index == i:
                sig = buy_signals[buy_idx]
                buy_idx += 1
                if position is not None:
                    continue

                fill_price = opens[i] if i < len(opens) and opens[i] > 0 else closes[i]
                if fill_price <= 0:
                    continue

                fill_price = _simulate_call_auction_fill(fill_price, self._rng)

                if self._enable_limit_check and i > 0:
                    prev_close = prev_closes[i] if i < len(prev_closes) else closes[i - 1]
                    limit_pct = _get_limit_pct(symbol)
                    is_normal, fill_prob = _check_limit_price(float(prev_close), fill_price, is_buy=True, limit_pct=limit_pct)
                    if not is_normal:
                        if self._rng.random() > fill_prob:
                            continue

                fill_price = fill_price * (1 + self._slippage_pct)

                if volumes is not None:
                    bar_vol = volumes[i] if i < len(volumes) else 0
                    if np.isnan(bar_vol) or bar_vol <= 0:
                        continue

                alloc_pct = sig.position_pct if sig.position_pct > 0 else 0.3
                if alloc_pct < 0.2:
                    alloc_pct = 0.3
                alloc_amount = equity_curve[-1] * alloc_pct
                if alloc_amount > cash * 0.98:
                    alloc_amount = cash * 0.98

                buy_shares = int(alloc_amount / fill_price / lot_size) * lot_size
                if buy_shares <= 0:
                    continue

                bar_amount = 0.0
                if amounts_col is not None and i < len(amounts_col):
                    bar_amount = float(amounts_col[i]) if not np.isnan(amounts_col[i]) else 0.0
                if bar_amount <= 0 and volumes is not None and i < len(volumes):
                    bar_amount = float(volumes[i]) * fill_price

                if bar_amount > 0:
                    max_shares_by_amount = int(bar_amount * 0.25 / fill_price / lot_size) * lot_size
                    if max_shares_by_amount > 0 and buy_shares > max_shares_by_amount:
                        buy_shares = max_shares_by_amount

                if buy_shares <= 0:
                    continue

                if self._enable_twap and bar_amount > 0:
                    fill_price = _simulate_twap_fill(fill_price, buy_shares, bar_amount, rng=self._rng)

                amount = buy_shares * fill_price
                cost_detail = self._cost_model.calc_buy_cost(fill_price, buy_shares, amount, bar_amount)
                total_cost = amount + cost_detail["total"]

                if total_cost > cash:
                    buy_shares = int(cash * 0.98 / fill_price / lot_size) * lot_size
                    if buy_shares <= 0:
                        continue
                    amount = buy_shares * fill_price
                    cost_detail = self._cost_model.calc_buy_cost(fill_price, buy_shares, amount, bar_amount)
                    total_cost = amount + cost_detail["total"]

                cash -= total_cost
                shares = buy_shares

                date_str = str(dates_col[i])[:10] if i < len(dates_col) else ""
                position = {
                    "entry_price": fill_price,
                    "shares": buy_shares,
                    "entry_idx": i,
                    "entry_date": date_str,
                    "stop_loss": sig.stop_loss,
                    "take_profit": sig.take_profit,
                }
                buy_bar_set.add(i)

                trades.append({
                    "action": "buy",
                    "symbol": "",
                    "price": fill_price,
                    "shares": buy_shares,
                    "amount": round(amount, 2),
                    "fee": round(cost_detail["total"], 2),
                    "cost_detail": cost_detail,
                    "date": date_str,
                    "bar_index": i,
                    "reason": sig.reason,
                })

            while sell_idx < len(sell_signals) and sell_signals[sell_idx].bar_index == i:
                sig = sell_signals[sell_idx]
                sell_idx += 1
                if position is None:
                    continue

                entry_date = position.get("entry_date", "")
                bar_date = str(dates_col[i])[:10] if i < len(dates_col) else ""
                if entry_date and bar_date and entry_date == bar_date:
                    continue

                fill_price = opens[i] if i < len(opens) and opens[i] > 0 else closes[i]
                if fill_price <= 0:
                    continue

                fill_price = _simulate_call_auction_fill(fill_price, self._rng)

                if self._enable_limit_check and i > 0:
                    prev_close = prev_closes[i] if i < len(prev_closes) else closes[i - 1]
                    limit_pct = _get_limit_pct(symbol)
                    is_normal, fill_prob = _check_limit_price(float(prev_close), fill_price, is_buy=False, limit_pct=limit_pct)
                    if not is_normal:
                        if self._rng.random() > fill_prob:
                            continue

                fill_price = fill_price * (1 - self._slippage_pct)

                sell_shares = shares
                bar_amount = 0.0
                if amounts_col is not None and i < len(amounts_col):
                    bar_amount = float(amounts_col[i]) if not np.isnan(amounts_col[i]) else 0.0
                if bar_amount <= 0 and volumes is not None and i < len(volumes):
                    bar_amount = float(volumes[i]) * fill_price

                if bar_amount > 0:
                    max_shares_by_amount = int(bar_amount * 0.25 / fill_price / lot_size) * lot_size
                    if max_shares_by_amount > 0 and sell_shares > max_shares_by_amount:
                        sell_shares = max_shares_by_amount

                if self._enable_twap and bar_amount > 0:
                    fill_price = _simulate_twap_fill(fill_price, sell_shares, bar_amount, rng=self._rng)

                revenue = sell_shares * fill_price
                cost_detail = self._cost_model.calc_sell_cost(fill_price, sell_shares, revenue, bar_amount)
                total_fee = cost_detail["total"]
                net_revenue = revenue - total_fee

                pnl = (fill_price - position["entry_price"]) * sell_shares - total_fee

                cash += net_revenue

                date_str = str(dates_col[i])[:10] if i < len(dates_col) else ""
                hold_days = i - position["entry_idx"]
                mae, mfe = _excursion(position, i)

                trades.append({
                    "action": "sell",
                    "symbol": "",
                    "price": fill_price,
                    "shares": sell_shares,
                    "amount": round(revenue, 2),
                    "fee": round(total_fee, 2),
                    "cost_detail": cost_detail,
                    "date": date_str,
                    "bar_index": i,
                    "pnl": round(pnl, 2),
                    "hold_days": hold_days,
                    "mae": mae,
                    "mfe": mfe,
                    "reason": sig.reason,
                })

                sell_bar_set.add(i)
                shares -= sell_shares
                if shares <= 0:
                    shares = 0
                    position = None

            if position is not None:
                current_price = closes[i]
                if position["stop_loss"] > 0 and current_price <= position["stop_loss"]:
                    exec_price = current_price * (1 - self._slippage_pct)
                    revenue = shares * exec_price
                    cost_detail = self._cost_model.calc_sell_cost(exec_price, shares, revenue)
                    total_fee = cost_detail["total"]
                    pnl = (exec_price - position["entry_price"]) * shares - total_fee
                    cash += revenue - total_fee
                    date_str = str(dates_col[i])[:10] if i < len(dates_col) else ""
                    hold_days = i - position["entry_idx"]
                    mae, mfe = _excursion(position, i)
                    trades.append({
                        "action": "sell",
                        "symbol": "",
                        "price": exec_price,
                        "shares": shares,
                        "amount": round(revenue, 2),
                        "fee": round(total_fee, 2),
                        "cost_detail": cost_detail,
                        "date": date_str,
                        "bar_index": i,
                        "pnl": round(pnl, 2),
                        "hold_days": hold_days,
                        "mae": mae,
                        "mfe": mfe,
                        "reason": "止损",
                    })
                    sell_bar_set.add(i)
                    shares = 0
                    position = None
                elif position["take_profit"] > 0 and current_price >= position["take_profit"]:
                    exec_price = current_price * (1 - self._slippage_pct)
                    revenue = shares * exec_price
                    cost_detail = self._cost_model.calc_sell_cost(exec_price, shares, revenue)
                    total_fee = cost_detail["total"]
                    pnl = (exec_price - position["entry_price"]) * shares - total_fee
                    cash += revenue - total_fee
                    date_str = str(dates_col[i])[:10] if i < len(dates_col) else ""
                    hold_days = i - position["entry_idx"]
                    mae, mfe = _excursion(position, i)
                    trades.append({
                        "action": "sell",
                        "symbol": "",
                        "price": exec_price,
                        "shares": shares,
                        "amount": round(revenue, 2),
                        "fee": round(total_fee, 2),
                        "cost_detail": cost_detail,
                        "date": date_str,
                        "bar_index": i,
                        "pnl": round(pnl, 2),
                        "hold_days": hold_days,
                        "mae": mae,
                        "mfe": mfe,
                        "reason": "止盈",
                    })
                    sell_bar_set.add(i)
                    shares = 0
                    position = None

            bar_equity = cash + (shares * closes[i] if shares > 0 else 0)
            equity_curve.append(bar_equity)

        dates_list = []
        for d in dates_col:
            ds = str(d)[:10] if hasattr(d, "__str__") else str(d)[:10]
            dates_list.append(ds)

        if position is not None and shares > 0:
            close_price = closes[-1] * (1 - self._slippage_pct)
            close_cost_detail = self._cost_model.calc_sell_cost(close_price, shares, shares * close_price)
            close_fee = close_cost_detail["total"]
            cash += shares * close_price - close_fee
            trades.append({
                "date": dates_list[-1] if dates_list else "",
                "action": "sell",
                "price": round(close_price, 4),
                "shares": shares,
                "fee": round(close_fee, 2),
                "pnl": round(shares * close_price - shares * position["entry_price"] - close_fee, 2),
                "reason": "回测结束强平",
            })
            shares = 0
            position = None

        eq_arr = np.array(equity_curve)
        peak_arr = np.maximum.accumulate(eq_arr)
        drawdown_curve = ((peak_arr - eq_arr) / np.where(peak_arr > 0, peak_arr, 1) * 100).tolist()
        max_dd = float(np.max(drawdown_curve))

        sell_trades = [t for t in trades if t["action"] == "sell"]
        total_trades = len(sell_trades)
        win_trades = 0
        loss_trades = 0
        total_win = 0.0
        total_loss = 0.0
        win_pnls = []
        loss_pnls = []
        hold_days_list = []
        for t in sell_trades:
            pnl = t.get("pnl", 0)
            if pnl > 0:
                win_trades += 1
                total_win += pnl
                win_pnls.append(pnl)
            elif pnl < 0:
                loss_trades += 1
                total_loss += abs(pnl)
                loss_pnls.append(abs(pnl))
            hd = t.get("hold_days", 0)
            if hd:
                hold_days_list.append(hd)
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
        profit_factor = (total_win / total_loss) if total_loss > 0 else 999 if total_win > 0 else 0
        avg_profit = np.mean(win_pnls) if win_pnls else 0
        avg_loss = np.mean(loss_pnls) if loss_pnls else 0
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

        benchmark_return = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0
        alpha = total_return - benchmark_return

        bench_returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                bench_returns.append((closes[i] - closes[i - 1]) / closes[i - 1])

        beta = 1.0
        information_ratio = 0.0
        if len(returns) > 1 and len(bench_returns) > 1:
            min_len = min(len(returns), len(bench_returns))
            r = np.array(returns[:min_len])
            b = np.array(bench_returns[:min_len])
            bench_var = np.var(b)
            if bench_var > 0:
                beta = float(np.cov(r, b)[0][1] / bench_var)
            excess = r - b
            tracking_error = np.std(excess)
            if tracking_error > 0:
                information_ratio = float(np.mean(excess) / tracking_error * np.sqrt(252))

        omega_ratio = 0.0
        tail_ratio = 0.0
        if returns:
            ret_arr = np.array(returns, dtype=float)
            ret_arr = ret_arr[np.isfinite(ret_arr)]
            if len(ret_arr) > 0:
                gains = ret_arr[ret_arr > 0].sum()
                losses = abs(ret_arr[ret_arr < 0].sum())
                if losses > 0:
                    omega_ratio = float(gains / losses)
                elif gains > 0:
                    omega_ratio = 999.0
                q95 = float(np.percentile(ret_arr, 95))
                q05 = float(np.percentile(ret_arr, 5))
                if q05 < 0:
                    tail_ratio = abs(q95 / q05)
                elif abs(q05) > 1e-12:
                    tail_ratio = abs(q95 / q05)

        recovery_factor = (total_return / max_dd) if max_dd > 0 else 0.0
        avg_mae = np.mean([abs(t.get("mae", 0)) for t in sell_trades]) if sell_trades else 0.0
        avg_mfe = np.mean([t.get("mfe", 0) for t in sell_trades]) if sell_trades else 0.0
        win_rate_frac = win_trades / total_trades if total_trades > 0 else 0.0
        loss_rate_frac = loss_trades / total_trades if total_trades > 0 else 0.0
        expectancy = win_rate_frac * avg_profit - loss_rate_frac * avg_loss
        payoff_ratio = (avg_profit / avg_loss) if avg_loss > 0 else 999 if avg_profit > 0 else 0.0

        cvar_95 = 0.0
        annual_vol = 0.0
        downside_dev = 0.0
        monthly_rets = []
        if returns:
            ret_arr = np.array(returns, dtype=float)
            ret_arr = ret_arr[np.isfinite(ret_arr)]
            if len(ret_arr) > 1:
                annual_vol = float(np.std(ret_arr) * np.sqrt(252))
                neg_rets = ret_arr[ret_arr < 0]
                if len(neg_rets) > 0:
                    downside_dev = float(np.std(neg_rets) * np.sqrt(252))
                var_5 = float(np.percentile(ret_arr, 5))
                tail_5 = ret_arr[ret_arr <= var_5]
                if len(tail_5) > 0:
                    cvar_95 = float(-np.mean(tail_5))
        if len(dates_list) > 20 and len(equity_curve) > 20:
            try:
                eq_arr = np.array(equity_curve, dtype=float)
                eq_dates = list(dates_list)
                monthly_map: dict[str, list[float]] = {}
                for j in range(1, len(eq_arr)):
                    if j >= len(eq_dates):
                        break
                    d = str(eq_dates[j])[:7]
                    if d not in monthly_map:
                        monthly_map[d] = []
                    if eq_arr[j - 1] > 0:
                        monthly_map[d].append((eq_arr[j] / eq_arr[j - 1]) - 1)
                for m in sorted(monthly_map.keys()):
                    vals = monthly_map[m]
                    if vals:
                        monthly_rets.append({"month": m, "return": float(np.mean(vals))})
            except Exception:
                pass

        kline_with_signals = []
        vols = df["volume"].values.astype(float) if "volume" in df.columns else np.zeros(n)
        for idx in range(n):
            item = {
                "date": dates_list[idx] if idx < len(dates_list) else "",
                "open": float(opens[idx]) if idx < len(opens) else 0,
                "close": float(closes[idx]),
                "high": float(highs[idx]),
                "low": float(lows[idx]),
                "volume": float(vols[idx]),
            }
            if idx in buy_bar_set:
                item["signal"] = "buy"
            elif idx in sell_bar_set:
                item["signal"] = "sell"
            kline_with_signals.append(item)

        result = BacktestResult(
            strategy_name=name,
            total_return=round(total_return, 2),
            annual_return=round(annual_return, 2),
            sharpe_ratio=round(sharpe, 2),
            max_drawdown=round(max_dd, 2),
            calmar_ratio=round(calmar_ratio, 2),
            win_rate=round(win_rate, 2),
            profit_factor=round(profit_factor, 2) if profit_factor != 999 else 999,
            total_trades=total_trades,
            win_trades=win_trades,
            loss_trades=loss_trades,
            avg_profit=round(avg_profit, 2),
            avg_loss=round(avg_loss, 2),
            avg_hold_days=round(avg_hold_days, 1),
            benchmark_return=round(benchmark_return, 2),
            alpha=round(alpha, 2),
            beta=round(beta, 2),
            equity_curve=equity_curve,
            drawdown_curve=drawdown_curve,
            dates=dates_list,
            trades=trades,
            kline_with_signals=kline_with_signals,
            sortino_ratio=round(sortino, 2),
            max_consecutive_losses=max_consec_losses,
            omega_ratio=round(omega_ratio, 2) if omega_ratio != 999.0 else 999.0,
            tail_ratio=round(tail_ratio, 2),
            information_ratio=round(information_ratio, 2),
            recovery_factor=round(recovery_factor, 2),
            avg_mae=round(float(avg_mae), 2),
            avg_mfe=round(float(avg_mfe), 2),
            cvar_95=round(cvar_95, 4),
            annual_volatility=round(annual_vol, 4),
            downside_deviation=round(downside_dev, 4),
            monthly_returns=monthly_rets,
            expectancy=round(float(expectancy), 2),
            payoff_ratio=round(float(payoff_ratio), 2) if payoff_ratio != 999 else 999,
        )
        result.downsample_curves(500)
        return result


def _get_strategy_min_bars(strategy_name: str, params: dict = None) -> int:
    _min_bars = {
        "ma_cross": 30, "dual_ma": 30, "macd": 45, "rsi": 30,
        "supertrend": 25, "kdj": 25, "bollinger": 35, "bollinger_breakout": 35,
        "momentum": 35, "volume_breakout": 35, "multi_factor": 65,
        "adaptive_trend": 70, "mean_reversion_pro": 55, "mean_reversion": 55,
        "vol_squeeze": 45, "volatility_squeeze": 45,
        "ichimoku": 90, "ichimoku_cloud": 90,
        "vwap_deviation": 40, "vwap": 40,
        "order_flow": 30, "order_flow_imbalance": 30,
        "regime_switching": 90, "regime": 90,
        "fractal_breakout": 35, "fractal": 35,
        "wyckoff": 70, "wyckoff_accumulation": 70,
        "elliott_wave": 140, "elliott": 140,
        "market_microstructure": 35, "microstructure": 35,
        "copula": 80, "copula_correlation": 80,
        "quantile": 80, "quantile_regression": 80,
        "rsi_mean_reversion": 30,
        "turtle": 35, "turtle_trading": 35,
        "dual_thrust": 30,
        "atr_channel": 30, "atr_channel_breakout": 30,
        "donchian": 30, "donchian_channel": 30,
        "chande_kroll": 40, "chande_kroll_stop": 40,
        "vw_macd": 50, "volume_weighted_macd": 50,
        "ornstein_uhlenbeck": 60,
        "kaufman_adaptive": 40,
        "garch_volatility": 60,
        "mtf_momentum": 50, "multi_timeframe_momentum": 50,
        "adx_trend": 55, "adx_trend_strength": 55,
        "cmf": 50, "chaikin_money_flow": 50,
        "psar": 25, "parabolic_sar": 25,
        "hurst": 100, "hurst_exponent": 100,
        "pairs": 65, "pairs_trading": 65,
    }
    return _min_bars.get(strategy_name, 30)


def run_backtest(
    symbol: str,
    strategy_name: str = "ma_cross",
    start_date: str = "2024-01-01",
    end_date: str = "2025-12-31",
    initial_capital: float = 1000000,
    params: dict = None,
    _df=None,
) -> dict:
    from core.data_fetcher import get_fetcher

    if strategy_name == "adaptive":
        return _run_adaptive_backtest(symbol, start_date, end_date, initial_capital, params, _df)

    if strategy_name not in STRATEGY_REGISTRY:
        return {"error": f"未知策略: {strategy_name}"}

    strategy_cls = STRATEGY_REGISTRY[strategy_name]
    try:
        strategy = strategy_cls(**(params or {}))
    except (TypeError, ValueError) as e:
        return {"error": f"策略参数错误: {e}"}

    fetcher = get_fetcher()

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days_from_now = (datetime.now() - start_dt).days
    except (ValueError, TypeError):
        days_from_now = 370

    if days_from_now > 730:
        hist_period = "all"
    elif days_from_now > 365:
        hist_period = "all"
    else:
        hist_period = "1y"

    if _df is not None:
        df = _df.copy()
    else:
        async def _fetch():
            return await fetcher.get_history(symbol, period=hist_period, kline_type="daily", adjust="qfq")

        try:
            try:
                loop = asyncio.get_running_loop()
                df = asyncio.run_coroutine_threadsafe(_fetch(), loop).result(timeout=30)
            except RuntimeError:
                df = asyncio.run(_fetch())
        except Exception as e:
            logger.error(f"Data fetch failed for {symbol}: {e}")
            return {"error": f"获取 {symbol} 数据失败: {e}"}

    if df is None or df.empty:
        return {"error": f"无法获取 {symbol} 的历史数据，请检查股票代码是否正确"}

    min_bars = _get_strategy_min_bars(strategy_name, params)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df_full = df.copy()
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]
        df = df.sort_values("date").reset_index(drop=True)
        if len(df) < min_bars and len(df_full) >= min_bars:
            logger.warning(f"Date range {start_date}~{end_date} only has {len(df)} bars, using available data")
            df = df_full.sort_values("date").reset_index(drop=True)

    if len(df) < min_bars:
        return {"error": f"数据不足：仅有 {len(df)} 个交易日，{strategy_cls.__name__}策略至少需要{min_bars}个交易日，请选择更长的时间段"}

    try:
        engine = BacktestEngine(initial_capital=initial_capital, slippage_pct=0.001, market_impact_pct=0.0005)
        result = engine.run(strategy, df)
        try:
            from core.metrics import metrics
            metrics.increment("backtest_runs", tags={"strategy": strategy_name})
            metrics.gauge("backtest_sharpe", result.sharpe_ratio, tags={"strategy": strategy_name})
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Backtest engine failed for {symbol} with {strategy_name}: {e}")
        return {"error": f"回测执行失败: {e}"}

    if not result.dates or not result.equity_curve:
        return {"error": "回测未产生有效结果，请尝试更长的回测时间段"}

    closes_raw = df["close"].values.astype(float)
    n_dates = len(result.dates)
    n_equity = len(result.equity_curve)

    date_close_map = {}
    if "date" in df.columns:
        ds_arr = df["date"].dt.strftime("%Y-%m-%d").values if hasattr(df["date"].dt, "strftime") else [str(d)[:10] for d in df["date"].values]
        close_arr = df["close"].values.astype(float)
        for j in range(len(ds_arr)):
            date_close_map[ds_arr[j]] = float(close_arr[j])

    equity_curve = []
    for i in range(min(n_dates, n_equity)):
        equity_curve.append({"date": result.dates[i], "value": result.equity_curve[i]})

    benchmark_curve = []
    first_close = float(closes_raw[0]) if closes_raw[0] > 0 else 1.0
    for i in range(n_dates):
        d = result.dates[i]
        close_val = date_close_map.get(d)
        if close_val is None:
            if i < len(closes_raw):
                close_val = float(closes_raw[i])
            else:
                continue
        benchmark_curve.append({"date": d, "value": initial_capital * (close_val / first_close)})

    return {
        "strategy_name": result.strategy_name,
        "total_return": round(result.total_return, 4) if result.total_return else 0,
        "annual_return": round(result.annual_return, 4) if result.annual_return else 0,
        "max_drawdown": round(result.max_drawdown, 4) if result.max_drawdown else 0,
        "sharpe_ratio": result.sharpe_ratio,
        "calmar_ratio": result.calmar_ratio,
        "win_rate": round(result.win_rate, 2) if result.win_rate else 0,
        "profit_factor": result.profit_factor,
        "total_trades": result.total_trades,
        "win_trades": result.win_trades,
        "loss_trades": result.loss_trades,
        "avg_hold_days": result.avg_hold_days,
        "benchmark_return": round(result.benchmark_return, 4) if result.benchmark_return else 0,
        "alpha": round(result.alpha, 4) if result.alpha else 0,
        "beta": result.beta,
        "slippage_model": "fixed_pct",
        "sortino_ratio": result.sortino_ratio,
        "max_consecutive_losses": result.max_consecutive_losses,
        "omega_ratio": result.omega_ratio,
        "tail_ratio": result.tail_ratio,
        "information_ratio": result.information_ratio,
        "recovery_factor": result.recovery_factor,
        "avg_mae": result.avg_mae,
        "avg_mfe": result.avg_mfe,
        "expectancy": result.expectancy,
        "payoff_ratio": result.payoff_ratio,
        "cvar_95": result.cvar_95,
        "annual_volatility": result.annual_volatility,
        "downside_deviation": result.downside_deviation,
        "equity_curve": equity_curve[-500:] if equity_curve else [],
        "benchmark_curve": benchmark_curve[-500:] if benchmark_curve else [],
        "trades": result.trades[-200:] if result.trades else [],
        "kline_with_signals": result.kline_with_signals[-500:] if result.kline_with_signals else [],
    }


def _run_adaptive_backtest(
    symbol: str,
    start_date: str = "2024-01-01",
    end_date: str = "2025-12-31",
    initial_capital: float = 1000000,
    params: dict = None,
    _df=None,
) -> dict:
    from core.adaptive_strategy import AdaptiveStrategyEngine

    if _df is not None:
        df = _df.copy()
    else:
        from core.data_fetcher import get_fetcher
        fetcher = get_fetcher()

        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            days_from_now = (datetime.now() - start_dt).days
        except (ValueError, TypeError):
            days_from_now = 370

        hist_period = "all" if days_from_now > 365 else "1y"

        import asyncio

        async def _fetch():
            return await fetcher.get_history(symbol, period=hist_period, kline_type="daily", adjust="qfq")

        try:
            try:
                loop = asyncio.get_running_loop()
                df = asyncio.run_coroutine_threadsafe(_fetch(), loop).result(timeout=30)
            except RuntimeError:
                df = asyncio.run(_fetch())
        except Exception as e:
            logger.error(f"Data fetch failed for {symbol}: {e}")
            return {"error": f"获取 {symbol} 数据失败: {e}"}

    if df is None or df.empty:
        return {"error": f"无法获取 {symbol} 的历史数据"}

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df_full = df.copy()
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]
        df = df.sort_values("date").reset_index(drop=True)
        if len(df) < 40 and len(df_full) >= 40:
            logger.warning(f"Adaptive: Date range {start_date}~{end_date} only has {len(df)} bars, using available data")
            df = df_full.sort_values("date").reset_index(drop=True)

    if len(df) < 40:
        return {"error": f"数据不足：自适应策略至少需要40个交易日，当前仅{len(df)}个"}

    try:
        engine = AdaptiveStrategyEngine(initial_capital=initial_capital)
        result = engine.run(df)
    except Exception as e:
        logger.error(f"Adaptive backtest failed for {symbol}: {e}")
        return {"error": f"自适应回测执行失败: {e}"}

    if not result.get("equity_curve"):
        return {"error": "回测未产生有效结果，请尝试更长的回测时间段"}

    equity_curve = result.get("equity_curve", [])
    benchmark_curve = result.get("benchmark_curve", [])

    if equity_curve and isinstance(equity_curve[0], dict):
        equity_curve = [
            {"date": str(e.get("date", "")), "value": float(e.get("value", 0))}
            for e in equity_curve if isinstance(e, dict)
        ]
    else:
        dates_list = result.get("dates", [])
        ec_raw = equity_curve
        bc_raw = benchmark_curve
        equity_curve = []
        for i in range(min(len(dates_list), len(ec_raw))):
            equity_curve.append({"date": str(dates_list[i]), "value": float(ec_raw[i])})

    if benchmark_curve and isinstance(benchmark_curve[0], dict):
        benchmark_curve = [
            {"date": str(b.get("date", "")), "value": float(b.get("value", 0))}
            for b in benchmark_curve if isinstance(b, dict)
        ]
    else:
        dates_list = result.get("dates", [])
        bc_raw = result.get("benchmark_curve", [])
        benchmark_curve = []
        for i in range(min(len(dates_list), len(bc_raw))):
            benchmark_curve.append({"date": str(dates_list[i]), "value": float(bc_raw[i])})

    return {
        "strategy_name": result.get("strategy_name", "自适应量化策略引擎"),
        "total_return": result.get("total_return", 0),
        "annual_return": result.get("annual_return", 0),
        "max_drawdown": result.get("max_drawdown", 0),
        "sharpe_ratio": result.get("sharpe_ratio", 0),
        "sortino_ratio": result.get("sortino_ratio", 0),
        "calmar_ratio": result.get("calmar_ratio", 0),
        "win_rate": result.get("win_rate", 0),
        "profit_factor": result.get("profit_factor", 0),
        "total_trades": result.get("total_trades", 0),
        "win_trades": result.get("win_trades", 0),
        "loss_trades": result.get("loss_trades", 0),
        "avg_hold_days": result.get("avg_hold_days", 0),
        "max_consecutive_losses": result.get("max_consecutive_losses", 0),
        "benchmark_return": result.get("benchmark_return", 0),
        "alpha": result.get("alpha", 0),
        "beta": result.get("beta", 1),
        "equity_curve": equity_curve,
        "benchmark_curve": benchmark_curve,
        "trades": result.get("trades", []),
        "kline_with_signals": result.get("kline_with_signals", []),
        "market_regime_labels": result.get("market_regime_labels", []),
        "strategy_allocation": result.get("strategy_allocation", []),
    }


def grid_search_params(strategy_cls, df, max_combinations: int = 50) -> list:
    import random
    param_space = strategy_cls.get_param_space()
    if not param_space:
        return []

    param_names = list(param_space.keys())
    param_values_list = []
    for name in param_names:
        spec = param_space[name]
        vals = []
        v = spec["min"]
        while v <= spec["max"]:
            vals.append(v)
            v += spec["step"]
        param_values_list.append(vals)

    from itertools import product
    all_combos = list(product(*param_values_list))

    if len(all_combos) > max_combinations:
        all_combos = random.sample(all_combos, max_combinations)

    results = []
    for combo in all_combos:
        params = dict(zip(param_names, combo))
        try:
            bt_result = run_backtest(
                symbol="grid_search",
                strategy_name=strategy_cls.__name__,
                initial_capital=1000000,
                params=params,
                _df=df,
            )
        except Exception:
            continue

        if "error" in bt_result:
            continue

        results.append({
            "params": params,
            "sharpe_ratio": bt_result.get("sharpe_ratio", 0),
            "total_return": bt_result.get("total_return", 0),
            "max_drawdown": bt_result.get("max_drawdown", 0),
        })

    results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)
    return results[:10]


def run_walk_forward(
    symbol: str,
    strategy_name: str = "ma_cross",
    start_date: str = "2024-01-01",
    end_date: str = "2025-12-31",
    train_days: int = 252,
    test_days: int = 63,
    initial_capital: float = 1000000,
    params: dict = None,
) -> dict:
    from core.data_fetcher import get_fetcher
    import asyncio

    fetcher = get_fetcher()

    async def _fetch_df():
        return await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                df = pool.submit(asyncio.run, _fetch_df()).result(timeout=30)
        else:
            df = asyncio.run(_fetch_df())
    except Exception as e:
        logger.error(f"Walk-forward data fetch failed for {symbol}: {e}")
        return {"error": f"获取数据失败: {e}"}

    if df is None or df.empty:
        return {"error": f"无法获取 {symbol} 的历史数据"}

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)

    start_dt = pd.Timestamp(start_date)
    end_dt = pd.Timestamp(end_date)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)].reset_index(drop=True)

    if len(df) < train_days + test_days:
        return {"error": f"数据不足：至少需要{train_days + test_days}个交易日，当前仅{len(df)}个"}

    windows = []
    i = 0
    while i + train_days + test_days <= len(df):
        train_df = df.iloc[i:i + train_days]
        test_df = df.iloc[i + train_days:i + train_days + test_days]

        train_start = str(train_df["date"].iloc[0])[:10]
        train_end = str(train_df["date"].iloc[-1])[:10]
        test_start = str(test_df["date"].iloc[0])[:10]
        test_end = str(test_df["date"].iloc[-1])[:10]

        bt_result = run_backtest(
            symbol=symbol,
            strategy_name=strategy_name,
            start_date=test_start,
            end_date=test_end,
            initial_capital=initial_capital,
            params=params,
            _df=test_df,
        )

        metrics = {}
        if "error" not in bt_result:
            metrics = {
                "sharpe_ratio": bt_result.get("sharpe_ratio", 0),
                "total_return": bt_result.get("total_return", 0),
                "max_drawdown": bt_result.get("max_drawdown", 0),
            }
        else:
            metrics = {"sharpe_ratio": 0, "total_return": 0, "max_drawdown": 0}

        windows.append({
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
            "metrics": metrics,
        })

        i += test_days

    if not windows:
        return {"error": "无法生成有效的滚动窗口"}

    test_sharpes = [w["metrics"]["sharpe_ratio"] for w in windows]
    test_returns = [w["metrics"]["total_return"] for w in windows]
    profitable_count = sum(1 for r in test_returns if r > 0)

    return {
        "windows": windows,
        "avg_test_sharpe": round(float(np.mean(test_sharpes)), 4) if test_sharpes else 0,
        "avg_test_return": round(float(np.mean(test_returns)), 4) if test_returns else 0,
        "consistency_rate": round(profitable_count / len(windows), 4) if windows else 0,
    }


def _run_single_backtest(args: tuple) -> dict:
    strategy_name, strategy_cls_name, params, df_dict, symbol, initial_capital = args
    strategy_cls = STRATEGY_REGISTRY.get(strategy_cls_name)
    if strategy_cls is None:
        return {"strategy": strategy_name, "error": f"Unknown strategy: {strategy_cls_name}"}
    try:
        strat = strategy_cls(**(params or {}))
        df = pd.DataFrame(df_dict)
        engine = BacktestEngine(initial_capital=initial_capital)
        result = engine.run(strat, df, symbol=symbol)
        sell_trades = [t for t in result.trades if t.get("action") == "sell"]
        total_trades = len(sell_trades)
        win_trades = sum(1 for t in sell_trades if t.get("pnl", 0) > 0)
        return {
            "strategy": strategy_name,
            "total_return": round(result.total_return, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "max_drawdown": round(result.max_drawdown, 4),
            "win_rate": round(win_trades / total_trades, 4) if total_trades > 0 else 0.0,
            "total_trades": total_trades,
        }
    except Exception as e:
        return {"strategy": strategy_name, "error": str(e)}


def run_parallel_backtest(
    strategies: list[dict],
    df: pd.DataFrame,
    symbol: str = "",
    initial_capital: float = 1000000,
    max_workers: int = 0,
) -> list[dict]:
    import multiprocessing as mp
    if max_workers <= 0:
        max_workers = min(mp.cpu_count() or 4, 6)
    df_dict = df.to_dict("list")
    args_list = []
    for s in strategies:
        name = s.get("name", "")
        cls_name = s.get("class_name", name)
        params = s.get("params", {})
        args_list.append((name, cls_name, params, df_dict, symbol, initial_capital))
    if len(args_list) <= 2 or max_workers <= 1:
        return [_run_single_backtest(a) for a in args_list]
    try:
        with mp.Pool(processes=max_workers) as pool:
            results = pool.map(_run_single_backtest, args_list)
        return results
    except Exception as e:
        logger.warning(f"Parallel backtest failed, falling back to sequential: {e}")
        return [_run_single_backtest(a) for a in args_list]
