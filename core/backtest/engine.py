from __future__ import annotations

__all__ = [
    "BacktestEngine",
    "DEFAULT_COMMISSION",
    "DEFAULT_STAMP_TAX",
    "DEFAULT_SLIPPAGE_PCT",
    "DEFAULT_MARKET_IMPACT_PCT",
    "DEFAULT_INITIAL_CAPITAL",
]

import logging

import numpy as np
import pandas as pd

from core.data_governance import DataQualityPipeline
from core.events import BacktestProgressTracker, Event, EventBus, EventType
from core.memory_guard import memory_guard
from core.risk_manager import EnhancedRiskManager
from core.strategies import BaseStrategy, SignalType, TradeSignal

from .cost_model import RealisticCostModel
from .event_driven import run_event_driven
from .optimization import monte_carlo_analysis, parameter_grid_scan, parameter_sensitivity, sensitivity_analysis
from .result import BacktestResult, InsufficientDataError, MIN_BARS_REQUIRED
from .simulation import (
    _check_limit_price,
    _excursion,
    _get_limit_pct,
    _simulate_call_auction_fill,
    _simulate_twap_fill,
)
from .stats import compute_backtest_statistics

logger = logging.getLogger(__name__)

DEFAULT_COMMISSION = 0.0003
DEFAULT_STAMP_TAX = 0.001
DEFAULT_SLIPPAGE_PCT = 0.001
DEFAULT_MARKET_IMPACT_PCT = 0.0005
DEFAULT_INITIAL_CAPITAL = 1_000_000


class BacktestEngine:
    def __init__(self, initial_capital: float = DEFAULT_INITIAL_CAPITAL, commission: float = DEFAULT_COMMISSION, stamp_tax: float = DEFAULT_STAMP_TAX,
                 slippage_pct: float = DEFAULT_SLIPPAGE_PCT, market_impact_pct: float = DEFAULT_MARKET_IMPACT_PCT,
                 cost_model: RealisticCostModel = None, enable_twap: bool = True,
                 enable_limit_check: bool = True, use_vectorized: bool = True,
                 event_bus: EventBus | None = None, risk_manager: EnhancedRiskManager | None = None,
                 enable_data_quality: bool = True):
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
        self._progress_tracker = BacktestProgressTracker(self._event_bus)
        self._data_quality = DataQualityPipeline() if enable_data_quality else None

    def run(self, strategy: BaseStrategy, df: pd.DataFrame, symbol: str = "") -> BacktestResult:
        if df is None or len(df) < MIN_BARS_REQUIRED:
            raise InsufficientDataError(
                f"{strategy.name} requires at least {MIN_BARS_REQUIRED} bars; got {len(df) if df is not None else 0}"
            )

        df = df.copy()
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df.sort_values("date").reset_index(drop=True)

        if len(df) < MIN_BARS_REQUIRED:
            raise InsufficientDataError(
                f"{strategy.name} requires at least {MIN_BARS_REQUIRED} bars after date parsing/cleaning; got {len(df)}"
            )

        if self._data_quality is not None:
            df = self._data_quality.process(df, symbol)

        strategy.reset()
        self._event_bus.publish(Event(EventType.INIT, {"strategy": strategy.name}))

        with memory_guard(f"Backtest_{strategy.name}", max_mb=2048):
            return self._build_result(strategy.name, df, strategy, symbol)

    def run_event_driven(
        self,
        strategy: BaseStrategy,
        df: pd.DataFrame,
        symbol: str = "",
        enable_risk_check: bool = True,
    ) -> BacktestResult:
        return run_event_driven(self, strategy, df, symbol, enable_risk_check)

    def run_multi(self, strategies: list[BaseStrategy], df: pd.DataFrame) -> dict[str, BacktestResult]:
        results = {}
        for strategy in strategies:
            results[strategy.name] = self.run(strategy, df)
        return results

    def monte_carlo_analysis(self, result: BacktestResult, n_simulations: int = 1000) -> dict:
        return monte_carlo_analysis(self, result, n_simulations)

    def sensitivity_analysis(self, strategy_cls, df: pd.DataFrame,
                             base_params: dict, param_ranges: dict | None = None) -> dict:
        return sensitivity_analysis(self, strategy_cls, df, base_params, param_ranges)

    def parameter_grid_scan(self, strategy_cls, df: pd.DataFrame, param_x: str, param_y: str,
                            x_range: tuple | None = None, y_range: tuple | None = None,
                            grid_size: int = 7, base_params: dict | None = None,
                            metric: str = "sharpe_ratio") -> dict:
        return parameter_grid_scan(self, strategy_cls, df, param_x, param_y,
                                   x_range, y_range, grid_size, base_params, metric)

    def parameter_sensitivity(self, strategy_cls, df: pd.DataFrame, param_name: str,
                              param_range: tuple | None = None, num_points: int = 11,
                              base_params: dict | None = None,
                              metrics: tuple[str, ...] = ("sharpe_ratio", "total_return", "max_drawdown", "win_rate")) -> dict:
        return parameter_sensitivity(self, strategy_cls, df, param_name, param_range,
                                     num_points, base_params, metrics)

    def _build_result(
        self,
        name: str,
        df: pd.DataFrame,
        strategy: BaseStrategy,
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
        self._progress_tracker.start(name, n)
        cash = float(self._initial_capital)
        shares = 0
        position = None
        equity_curve = [cash]
        trades = []
        buy_bar_set = set()
        sell_bar_set = set()
        lot_size = 100

        atr_values = np.zeros(n)
        if n > 14 and len(highs) == n and len(lows) == n:
            tr_arr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(
                    np.abs(highs[1:] - closes[:-1]),
                    np.abs(lows[1:] - closes[:-1]),
                ),
            )
            tr_arr = np.concatenate([[0], tr_arr])
            cumsum = np.cumsum(tr_arr)
            atr_values[0] = tr_arr[1] if len(tr_arr) > 1 else 0
            window = 14
            for k in range(1, min(window, n)):
                atr_values[k] = cumsum[k] / k
            if n > window:
                atr_values[window:] = (cumsum[window:] - cumsum[:-window]) / window

        volumes = df["volume"].values.astype(float) if "volume" in df.columns else None
        amounts_col = df["amount"].values.astype(float) if "amount" in df.columns else None

        prev_closes = np.empty_like(closes)
        prev_closes[0] = closes[0] if len(closes) > 0 else 0
        prev_closes[1:] = closes[:-1]

        for i in range(1, n):
            bar = {
                "open": float(opens[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "close": float(closes[i]),
                "volume": float(volumes[i]) if volumes is not None else 0,
                "date": str(dates_col[i])[:10],
            }

            try:
                sigs = strategy.on_bar(bar, {})
            except Exception as e:
                logger.debug("Strategy on_bar error at bar %d: %s", i, e)
                sigs = []

            bar_buy = False
            bar_sell = False
            for sig in sigs:
                action = sig.get("action", "hold")
                if action not in ("buy", "sell"):
                    continue
                if action == "buy" and action == "sell":
                    continue
                if action == "buy" and bar_sell:
                    continue
                if action == "sell" and bar_buy:
                    continue

                ts = TradeSignal(
                    signal_type=SignalType.BUY if action == "buy" else SignalType.SELL,
                    strength=sig.get("confidence", 0.5),
                    reason=sig.get("reason", ""),
                    bar_index=i,
                    position_pct=sig.get("position_pct", 0.3),
                    stop_loss=sig.get("stop_loss", 0.0),
                    take_profit=sig.get("take_profit", 0.0),
                )

                if action == "buy":
                    bar_buy = True
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
                        if not is_normal and self._rng.random() > fill_prob:
                            continue

                    fill_price = fill_price * (1 + self._slippage_pct)

                    if volumes is not None:
                        bar_vol = volumes[i] if i < len(volumes) else 0
                        if np.isnan(bar_vol) or bar_vol <= 0:
                            continue

                    alloc_pct = ts.position_pct if ts.position_pct > 0 else 0.3
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
                        if total_cost > cash:
                            buy_shares = int((cash - cost_detail["total"]) / fill_price / lot_size) * lot_size
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
                        "stop_loss": ts.stop_loss,
                        "take_profit": ts.take_profit,
                        "highest_price": fill_price,
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
                        "reason": ts.reason,
                    })

                elif action == "sell":
                    bar_sell = True
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
                        if not is_normal and self._rng.random() > fill_prob:
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
                    mae, mfe = _excursion(position, i, lows, highs, n)

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
                        "reason": ts.reason,
                    })

                    sell_bar_set.add(i)
                    shares -= sell_shares
                    if shares <= 0:
                        shares = 0
                        position = None
                    elif position is not None:
                        position["shares"] = shares

            if position is not None:
                bar_low = float(lows[i]) if i < len(lows) else closes[i]
                bar_high = float(highs[i]) if i < len(highs) else closes[i]

                if bar_high > position["highest_price"]:
                    position["highest_price"] = bar_high

                effective_stop = position["stop_loss"]
                if effective_stop <= 0 and i < len(atr_values) and atr_values[i] > 0:
                    effective_stop = position["entry_price"] - 2 * atr_values[i]

                trailing_stop = 0.0
                if i < len(atr_values) and atr_values[i] > 0:
                    trailing_stop = position["highest_price"] - 2 * atr_values[i]

                if trailing_stop > 0:
                    effective_stop = max(effective_stop, trailing_stop)

                exit_reason = None
                exit_price = 0.0
                if effective_stop > 0 and bar_low <= effective_stop:
                    exit_reason = "止损"
                    exit_price = effective_stop * (1 - self._slippage_pct)
                elif position["take_profit"] > 0 and bar_high >= position["take_profit"]:
                    exit_reason = "止盈"
                    exit_price = position["take_profit"] * (1 - self._slippage_pct)

                if exit_reason is not None:
                    revenue = shares * exit_price
                    cost_detail = self._cost_model.calc_sell_cost(exit_price, shares, revenue)
                    total_fee = cost_detail["total"]
                    pnl = (exit_price - position["entry_price"]) * shares - total_fee
                    cash += revenue - total_fee
                    date_str = str(dates_col[i])[:10] if i < len(dates_col) else ""
                    hold_days = i - position["entry_idx"]
                    mae, mfe = _excursion(position, i, lows, highs, n)
                    trades.append({
                        "action": "sell",
                        "symbol": "",
                        "price": exit_price,
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
                        "reason": exit_reason,
                    })
                    sell_bar_set.add(i)
                    shares = 0
                    position = None

            bar_equity = cash + (shares * closes[i] if shares > 0 else 0)
            equity_curve.append(bar_equity)
            date_str_progress = str(dates_col[i])[:10] if i < len(dates_col) else ""
            if i % 50 == 0 or i == n - 1:
                self._progress_tracker.on_bar(i, bar_equity, date_str_progress)

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

        stats = compute_backtest_statistics(equity_curve, closes, trades, dates_list)

        kline_with_signals = []
        vols = df["volume"].values.astype(float) if "volume" in df.columns else np.zeros(n)
        for idx in range(n):
            item = {
                "d": dates_list[idx] if idx < len(dates_list) else "",
                "o": round(float(opens[idx]), 2) if idx < len(opens) else 0,
                "c": round(float(closes[idx]), 2),
                "h": round(float(highs[idx]), 2) if idx < len(highs) else 0,
                "l": round(float(lows[idx]), 2) if idx < len(lows) else 0,
                "v": int(vols[idx]) if idx < len(vols) else 0,
            }
            if idx in buy_bar_set:
                item["s"] = "buy"
            elif idx in sell_bar_set:
                item["s"] = "sell"
            kline_with_signals.append(item)

        result = BacktestResult(
            strategy_name=name,
            total_return=stats["total_return"],
            annual_return=stats["annual_return"],
            sharpe_ratio=stats["sharpe_ratio"],
            max_drawdown=stats["max_drawdown"],
            calmar_ratio=stats["calmar_ratio"],
            win_rate=stats["win_rate"],
            profit_factor=stats["profit_factor"],
            total_trades=stats["total_trades"],
            win_trades=stats["win_trades"],
            loss_trades=stats["loss_trades"],
            avg_profit=stats["avg_profit"],
            avg_loss=stats["avg_loss"],
            avg_hold_days=stats["avg_hold_days"],
            benchmark_return=stats["benchmark_return"],
            alpha=stats["alpha"],
            beta=stats["beta"],
            equity_curve=equity_curve,
            drawdown_curve=stats["drawdown_curve"],
            dates=dates_list,
            trades=trades,
            kline_with_signals=kline_with_signals,
            sortino_ratio=stats["sortino_ratio"],
            max_consecutive_losses=stats["max_consecutive_losses"],
            omega_ratio=stats["omega_ratio"],
            tail_ratio=stats["tail_ratio"],
            information_ratio=stats["information_ratio"],
            recovery_factor=stats["recovery_factor"],
            avg_mae=stats["avg_mae"],
            avg_mfe=stats["avg_mfe"],
            cvar_95=stats["cvar_95"],
            var_95=stats["var_95"],
            annual_volatility=stats["annual_volatility"],
            downside_deviation=stats["downside_deviation"],
            monthly_returns=stats["monthly_returns"],
            expectancy=stats["expectancy"],
            payoff_ratio=stats["payoff_ratio"],
        )
        result.downsample_curves(500)
        self._progress_tracker.complete(result.summary_dict())
        return result
