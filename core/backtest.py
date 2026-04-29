import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from core.strategies import BaseStrategy, CompositeStrategy, StrategyResult, SignalType

logger = logging.getLogger(__name__)


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
                 slippage_pct: float = 0.001, market_impact_pct: float = 0.0005):
        self._initial_capital = initial_capital
        self._commission = commission
        self._stamp_tax = stamp_tax
        self._slippage_pct = slippage_pct
        self._market_impact_pct = market_impact_pct

    def run(self, strategy: BaseStrategy, df: pd.DataFrame) -> BacktestResult:
        if df is None or len(df) < 10:
            return BacktestResult(strategy_name=strategy.name)

        df = df.copy()
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df.sort_values("date").reset_index(drop=True)

        if len(df) < 10:
            return BacktestResult(strategy_name=strategy.name)

        try:
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

        return self._build_result(strategy.name, df, buy_signals, sell_signals, result)

    def _build_result(
        self,
        name: str,
        df: pd.DataFrame,
        buy_signals: list,
        sell_signals: list,
        strategy_result: StrategyResult,
    ) -> BacktestResult:
        closes = df["close"].values.astype(float) if "close" in df.columns else np.array([])
        opens = df["open"].values.astype(float) if "open" in df.columns else closes
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

        buy_idx = 0
        sell_idx = 0

        volumes = df["volume"].values.astype(float) if "volume" in df.columns else None
        amounts_col = df["amount"].values.astype(float) if "amount" in df.columns else None

        for i in range(1, n):
            while buy_idx < len(buy_signals) and buy_signals[buy_idx].bar_index == i:
                sig = buy_signals[buy_idx]
                buy_idx += 1
                if position is not None:
                    continue

                fill_price = opens[i] if i < len(opens) and opens[i] > 0 else closes[i]
                if fill_price <= 0:
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

                lot_size = 100
                buy_shares = int(alloc_amount / fill_price / lot_size) * lot_size
                if buy_shares <= 0:
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
                    continue

                amount = buy_shares * fill_price
                fee = max(amount * self._commission, 5.0)
                total_cost = amount + fee

                if total_cost > cash:
                    buy_shares = int(cash * 0.98 / fill_price / lot_size) * lot_size
                    if buy_shares <= 0:
                        continue
                    amount = buy_shares * fill_price
                    fee = max(amount * self._commission, 5.0)
                    total_cost = amount + fee

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
                    "fee": round(fee, 2),
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

                fill_price = fill_price * (1 - self._slippage_pct)

                sell_shares = shares
                if volumes is not None:
                    bar_vol = volumes[i] if i < len(volumes) else 0
                    if np.isnan(bar_vol) or bar_vol <= 0:
                        continue
                    if amounts_col is not None:
                        bar_amount = amounts_col[i] if i < len(amounts_col) else 0
                        if not np.isnan(bar_amount) and bar_amount > 0:
                            max_amount = bar_amount * 0.25
                            max_shares_by_amount = int(max_amount / fill_price / lot_size) * lot_size
                            if max_shares_by_amount > 0 and sell_shares > max_shares_by_amount:
                                sell_shares = max_shares_by_amount
                        else:
                            max_amount_est = bar_vol * fill_price * 0.25
                            max_shares_by_amount = int(max_amount_est / fill_price / lot_size) * lot_size
                            if max_shares_by_amount > 0 and sell_shares > max_shares_by_amount:
                                sell_shares = max_shares_by_amount
                    else:
                        max_amount_est = bar_vol * fill_price * 0.25
                        max_shares_by_amount = int(max_amount_est / fill_price / lot_size) * lot_size
                        if max_shares_by_amount > 0 and sell_shares > max_shares_by_amount:
                            sell_shares = max_shares_by_amount

                revenue = sell_shares * fill_price
                fee = max(revenue * self._commission, 5.0)
                stamp = revenue * self._stamp_tax
                total_fee = fee + stamp
                net_revenue = revenue - total_fee

                pnl = (fill_price - position["entry_price"]) * sell_shares - total_fee

                cash += net_revenue

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
                        "reason": "止损",
                    })
                    sell_bar_set.add(i)
                    shares = 0
                    position = None
                elif position["take_profit"] > 0 and current_price >= position["take_profit"]:
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
                        "reason": "止盈",
                    })
                    sell_bar_set.add(i)
                    shares = 0
                    position = None

            bar_equity = cash + (shares * closes[i] if shares > 0 else 0)
            equity_curve.append(bar_equity)

        if position is not None and shares > 0:
            cash += shares * closes[-1]
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

        benchmark_return = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0
        alpha = total_return - benchmark_return

        bench_returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                bench_returns.append((closes[i] - closes[i - 1]) / closes[i - 1])

        beta = 1.0
        if len(returns) > 1 and len(bench_returns) > 1:
            min_len = min(len(returns), len(bench_returns))
            r = np.array(returns[:min_len])
            b = np.array(bench_returns[:min_len])
            bench_var = np.var(b)
            if bench_var > 0:
                beta = float(np.cov(r, b)[0][1] / bench_var)

        kline_with_signals = []
        highs = df["high"].values.astype(float) if "high" in df.columns else np.zeros(n)
        lows = df["low"].values.astype(float) if "low" in df.columns else np.zeros(n)
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
        )
        result.downsample_curves(500)
        return result


def _get_strategy_min_bars(strategy_name: str, params: dict = None) -> int:
    _min_bars = {
        "ma_cross": 30,
        "macd": 45,
        "rsi": 30,
        "supertrend": 25,
        "kdj": 25,
        "bollinger": 35,
        "momentum": 35,
        "volume_breakout": 35,
        "multi_factor": 65,
        "adaptive_trend": 70,
        "mean_reversion_pro": 55,
        "vol_squeeze": 45,
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
    from core.data_fetcher import SmartDataFetcher
    from core.strategies import STRATEGY_REGISTRY

    if strategy_name == "adaptive":
        return _run_adaptive_backtest(symbol, start_date, end_date, initial_capital, params)

    if strategy_name not in STRATEGY_REGISTRY:
        return {"error": f"未知策略: {strategy_name}"}

    strategy_cls = STRATEGY_REGISTRY[strategy_name]
    try:
        strategy = strategy_cls(**(params or {}))
    except (TypeError, ValueError) as e:
        return {"error": f"策略参数错误: {e}"}

    fetcher = SmartDataFetcher()

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
        return {"error": f"无法获取 {symbol} 的历史数据，请检查股票代码是否正确"}

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]
        df = df.sort_values("date").reset_index(drop=True)

    min_bars = _get_strategy_min_bars(strategy_name, params)
    if len(df) < min_bars:
        return {"error": f"数据不足：指定时间段内仅有 {len(df)} 个交易日，{strategy_cls.__name__}策略至少需要{min_bars}个交易日"}

    try:
        engine = BacktestEngine(initial_capital=initial_capital, slippage_pct=0.001, market_impact_pct=0.0005)
        result = engine.run(strategy, df)
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
        "total_return": result.total_return / 100 if result.total_return else 0,
        "annual_return": result.annual_return / 100 if result.annual_return else 0,
        "max_drawdown": result.max_drawdown / 100 if result.max_drawdown else 0,
        "sharpe_ratio": result.sharpe_ratio,
        "calmar_ratio": result.calmar_ratio,
        "win_rate": result.win_rate / 100 if result.win_rate else 0,
        "profit_factor": result.profit_factor,
        "total_trades": result.total_trades,
        "win_trades": result.win_trades,
        "loss_trades": result.loss_trades,
        "avg_hold_days": result.avg_hold_days,
        "benchmark_return": result.benchmark_return / 100 if result.benchmark_return else 0,
        "alpha": result.alpha,
        "beta": result.beta,
        "slippage_model": "fixed_pct",
        "sortino_ratio": result.sortino_ratio,
        "max_consecutive_losses": result.max_consecutive_losses,
        "equity_curve": equity_curve,
        "benchmark_curve": benchmark_curve,
        "trades": result.trades,
        "kline_with_signals": result.kline_with_signals,
    }


def _run_adaptive_backtest(
    symbol: str,
    start_date: str = "2024-01-01",
    end_date: str = "2025-12-31",
    initial_capital: float = 1000000,
    params: dict = None,
) -> dict:
    from core.data_fetcher import SmartDataFetcher
    from core.adaptive_strategy import AdaptiveStrategyEngine

    fetcher = SmartDataFetcher()

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
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]
        df = df.sort_values("date").reset_index(drop=True)

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
        pass
    else:
        dates_list = result.get("dates", [])
        ec_raw = equity_curve
        bc_raw = benchmark_curve
        equity_curve = []
        for i in range(min(len(dates_list), len(ec_raw))):
            equity_curve.append({"date": dates_list[i], "value": ec_raw[i]})
        benchmark_curve = []
        for i in range(min(len(dates_list), len(bc_raw))):
            benchmark_curve.append({"date": dates_list[i], "value": bc_raw[i]})

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
    from core.data_fetcher import SmartDataFetcher
    import asyncio

    fetcher = SmartDataFetcher()

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
