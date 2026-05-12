import logging
from datetime import datetime

import numpy as np
import pandas as pd

from core.events import Event, EventType
from core.models import validate_signal_dict
from core.orders import Order, OrderSide, OrderType
from core.strategies import BaseStrategy

from .result import BacktestResult, InsufficientDataError, MIN_BARS_REQUIRED
from .stats import compute_backtest_statistics

logger = logging.getLogger(__name__)


def _calc_hold_days(entry_date: str, exit_date: str) -> int:
    if not entry_date or not exit_date:
        return 0
    try:
        d1 = datetime.strptime(entry_date[:10], "%Y-%m-%d")
        d2 = datetime.strptime(exit_date[:10], "%Y-%m-%d")
        return max(0, (d2 - d1).days)
    except (ValueError, TypeError):
        return 0


def run_event_driven(
    engine,
    strategy: BaseStrategy,
    df: pd.DataFrame,
    symbol: str = "",
    enable_risk_check: bool = True,
) -> BacktestResult:
    if df is None or len(df) < MIN_BARS_REQUIRED:
        raise InsufficientDataError(
            "%s requires at least %d bars; got %s" % (strategy.name, MIN_BARS_REQUIRED, len(df) if df is not None else 0)
        )

    df = df.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)

    if len(df) < MIN_BARS_REQUIRED:
        raise InsufficientDataError(
            "%s requires at least %d bars after date parsing/cleaning; got %s" % (strategy.name, MIN_BARS_REQUIRED, len(df))
        )

    if engine._data_quality is not None:
        df = engine._data_quality.process(df, symbol)

    strategy.reset()
    engine._event_bus.publish(Event(EventType.INIT, {"strategy": strategy.name}))

    closes = pd.to_numeric(df["close"], errors="coerce").dropna().values.astype(float) if "close" in df.columns else np.array([])
    opens = pd.to_numeric(df["open"], errors="coerce").dropna().values.astype(float) if "open" in df.columns else closes
    highs = pd.to_numeric(df["high"], errors="coerce").dropna().values.astype(float) if "high" in df.columns else closes
    lows = pd.to_numeric(df["low"], errors="coerce").dropna().values.astype(float) if "low" in df.columns else closes
    dates_col = df["date"].values if "date" in df.columns else np.arange(len(closes))
    volumes = pd.to_numeric(df["volume"], errors="coerce").dropna().values.astype(float) if "volume" in df.columns else None
    amounts_col = pd.to_numeric(df["amount"], errors="coerce").dropna().values.astype(float) if "amount" in df.columns else None

    n = len(closes)
    if n < 2:
        return BacktestResult(strategy_name=strategy.name)

    engine._progress_tracker.start(strategy.name, n)
    cash = float(engine._initial_capital)
    shares = 0
    position = None
    equity_curve = [cash]
    trades = []
    lot_size = 100

    for i in range(1, n):
        bar = {
            "open": float(opens[i]) if i < len(opens) else 0,
            "high": float(highs[i]) if i < len(highs) else 0,
            "low": float(lows[i]) if i < len(lows) else 0,
            "close": float(closes[i]) if i < len(closes) else 0,
            "volume": float(volumes[i]) if volumes is not None and i < len(volumes) else 0,
            "date": str(dates_col[i])[:10] if i < len(dates_col) else "",
            "symbol": symbol,
        }

        if position is not None:
            entry_price = position["entry_price"]
            stop_loss = position.get("stop_loss", 0)
            take_profit = position.get("take_profit", 0)
            bar_high = bar["high"]
            bar_low = bar["low"]

            if stop_loss > 0 and bar_low <= stop_loss:
                fill_price = max(stop_loss, float(lows[i])) if i < len(lows) else stop_loss
                fill_price = fill_price * (1 - engine._slippage_pct)
                sell_shares = shares
                amount = sell_shares * fill_price
                cost_detail = engine._cost_model.calc_sell_cost(fill_price, sell_shares, amount, 0)
                cash += amount - cost_detail["total"]
                pnl = (fill_price - entry_price) * sell_shares - cost_detail["total"]
                date_str = bar["date"]
                trades.append({
                    "action": "sell", "symbol": symbol,
                    "price": round(fill_price, 2), "shares": sell_shares,
                    "amount": round(amount, 2), "fee": round(cost_detail["total"], 2),
                    "cost_detail": cost_detail, "date": date_str, "bar_index": i,
                    "reason": "止损@%.2f" % stop_loss, "pnl": round(pnl, 2),
                    "mae": round(min(0, (float(lows[i]) - entry_price) / entry_price), 4) if entry_price > 1e-9 else 0,
                    "mfe": round(max(0, (float(highs[i]) - entry_price) / entry_price), 4) if entry_price > 1e-9 else 0,
                    "hold_days": _calc_hold_days(position.get("entry_date", ""), date_str),
                })
                position = None
                shares = 0
                equity_curve.append(cash)
                continue

            if take_profit > 0 and bar_high >= take_profit:
                fill_price = min(take_profit, float(highs[i])) if i < len(highs) else take_profit
                fill_price = fill_price * (1 - engine._slippage_pct)
                sell_shares = shares
                amount = sell_shares * fill_price
                cost_detail = engine._cost_model.calc_sell_cost(fill_price, sell_shares, amount, 0)
                cash += amount - cost_detail["total"]
                pnl = (fill_price - entry_price) * sell_shares - cost_detail["total"]
                date_str = bar["date"]
                trades.append({
                    "action": "sell", "symbol": symbol,
                    "price": round(fill_price, 2), "shares": sell_shares,
                    "amount": round(amount, 2), "fee": round(cost_detail["total"], 2),
                    "cost_detail": cost_detail, "date": date_str, "bar_index": i,
                    "reason": "止盈@%.2f" % take_profit, "pnl": round(pnl, 2),
                    "mae": round(min(0, (float(lows[i]) - entry_price) / entry_price), 4) if entry_price > 1e-9 else 0,
                    "mfe": round(max(0, (float(highs[i]) - entry_price) / entry_price), 4) if entry_price > 1e-9 else 0,
                    "hold_days": _calc_hold_days(position.get("entry_date", ""), date_str),
                })
                position = None
                shares = 0
                equity_curve.append(cash)
                continue

        portfolio = {
            "cash": cash,
            "positions": {symbol: position} if position else {},
            "total_assets": equity_curve[-1],
            "peak_value": max(equity_curve),
        }

        sigs = strategy.on_bar(bar, portfolio)

        for sig in sigs:
            if isinstance(sig, dict):
                try:
                    validated = validate_signal_dict(sig)
                    action = validated.signal_type.value
                    sig = {
                        "action": action,
                        "position_pct": validated.position_pct,
                        "stop_loss": validated.stop_loss,
                        "take_profit": validated.take_profit,
                        "reason": validated.reason,
                        "strength": validated.strength,
                    }
                except Exception as e:
                    logger.debug("Signal validation failed: %s", e)
                    action = sig.get("action", "hold")
            else:
                action = getattr(sig, "action", "hold")

            if action not in ("buy", "sell"):
                continue

            if action == "buy" and position is None:
                fill_price = bar["open"] if bar["open"] > 0 else bar["close"]
                if fill_price <= 0:
                    continue

                if volumes is not None and i < len(volumes):
                    bar_vol = volumes[i]
                    if np.isnan(bar_vol) or bar_vol <= 0:
                        continue

                fill_price = fill_price * (1 + engine._slippage_pct)

                alloc_pct = sig.get("position_pct", 0.3)
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
                    max_shares = int(bar_amount * 0.25 / fill_price / lot_size) * lot_size
                    if max_shares > 0 and buy_shares > max_shares:
                        buy_shares = max_shares
                if buy_shares <= 0:
                    continue

                amount = buy_shares * fill_price
                cost_detail = engine._cost_model.calc_buy_cost(fill_price, buy_shares, amount, bar_amount)
                total_cost = amount + cost_detail["total"]

                if total_cost > cash:
                    buy_shares = int(cash * 0.98 / fill_price / lot_size) * lot_size
                    if buy_shares <= 0:
                        continue
                    amount = buy_shares * fill_price
                    cost_detail = engine._cost_model.calc_buy_cost(fill_price, buy_shares, amount, bar_amount)
                    total_cost = amount + cost_detail["total"]
                    if total_cost > cash:
                        continue

                if enable_risk_check:
                    order = Order(
                        order_id="bt_buy_%d" % i,
                        symbol=symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=buy_shares,
                        price=fill_price,
                    )
                    risk_ctx = {"total_assets": equity_curve[-1], "current_positions": {}}
                    risk_ok, risk_reason = engine._risk_manager.check_order(order, risk_ctx)
                    if not risk_ok:
                        logger.debug("Risk check blocked buy: %s", risk_reason)
                        continue

                cash -= total_cost
                shares = buy_shares
                date_str = bar["date"]
                position = {
                    "entry_price": fill_price,
                    "shares": buy_shares,
                    "entry_idx": i,
                    "entry_date": date_str,
                    "stop_loss": sig.get("stop_loss", 0),
                    "take_profit": sig.get("take_profit", 0),
                    "highest_price": fill_price,
                }
                trades.append({
                    "action": "buy", "symbol": symbol,
                    "price": round(fill_price, 2), "shares": buy_shares,
                    "amount": round(amount, 2), "fee": round(cost_detail["total"], 2),
                    "cost_detail": cost_detail, "date": date_str, "bar_index": i,
                    "reason": sig.get("reason", ""),
                })

            elif action == "sell" and position is not None:
                entry_date = position.get("entry_date", "")
                bar_date = bar["date"]
                if entry_date and bar_date and entry_date == bar_date:
                    continue

                fill_price = bar["open"] if bar["open"] > 0 else bar["close"]
                if fill_price <= 0:
                    continue

                fill_price = fill_price * (1 - engine._slippage_pct)
                sell_shares = shares
                amount = sell_shares * fill_price
                cost_detail = engine._cost_model.calc_sell_cost(fill_price, sell_shares, amount, 0)
                cash += amount - cost_detail["total"]
                entry_price = position["entry_price"]
                pnl = (fill_price - entry_price) * sell_shares - cost_detail["total"]
                date_str = bar["date"]
                trades.append({
                    "action": "sell", "symbol": symbol,
                    "price": round(fill_price, 2), "shares": sell_shares,
                    "amount": round(amount, 2), "fee": round(cost_detail["total"], 2),
                    "cost_detail": cost_detail, "date": date_str, "bar_index": i,
                    "reason": sig.get("reason", ""), "pnl": round(pnl, 2),
                    "mae": round(min(0, (float(lows[i]) - entry_price) / entry_price), 4) if entry_price > 1e-9 else 0,
                    "mfe": round(max(0, (float(highs[i]) - entry_price) / entry_price), 4) if entry_price > 1e-9 else 0,
                    "hold_days": _calc_hold_days(position.get("entry_date", ""), date_str),
                })
                position = None
                shares = 0

        if position is not None:
            position["highest_price"] = max(position.get("highest_price", 0), bar["high"])

        eq = cash + (shares * bar["close"] if shares > 0 else 0)
        equity_curve.append(eq)
        engine._progress_tracker.on_bar(i, eq, bar["date"])

    if position is not None and shares > 0:
        close_price = closes[-1] * (1 - engine._slippage_pct)
        close_cost_detail = engine._cost_model.calc_sell_cost(close_price, shares, shares * close_price, 0)
        close_fee = close_cost_detail["total"]
        cash += shares * close_price - close_fee
        last_date = str(dates_col[-1])[:10] if len(dates_col) > 0 else ""
        trades.append({
            "action": "sell", "symbol": symbol,
            "price": round(close_price, 4), "shares": shares,
            "fee": round(close_fee, 2),
            "pnl": round(shares * close_price - shares * position["entry_price"] - close_fee, 2),
            "date": last_date, "reason": "回测结束强平",
        })
        shares = 0
        position = None

    dates_list = [str(d)[:10] for d in dates_col[:len(equity_curve)]]
    stats = compute_backtest_statistics(equity_curve, closes, trades, dates_list)

    result = BacktestResult(
        strategy_name=strategy.name,
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
        kline_with_signals=[],
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
    engine._progress_tracker.complete(result.summary_dict())
    return result
