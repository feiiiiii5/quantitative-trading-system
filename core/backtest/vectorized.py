__all__ = [
    "vectorized_backtest",
    "vectorized_equity_curve",
]

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_NUMBA_AVAILABLE = False
try:
    from numba import njit

    _NUMBA_AVAILABLE = True
    logger.debug("Numba JIT available for vectorized backtest")
except ImportError:
    logger.debug("Numba not available, using pure Python for vectorized backtest")


if _NUMBA_AVAILABLE:

    @njit(cache=True)
    def _equity_curve_numba(
        closes: np.ndarray,
        buy_shares_arr: np.ndarray,
        sell_shares_arr: np.ndarray,
        initial_capital: float,
        commission: float,
        stamp_tax: float,
    ) -> np.ndarray:
        n = len(closes)
        equity = np.zeros(n)
        cash = initial_capital
        hold_shares = np.int64(0)
        for i in range(n):
            if buy_shares_arr[i] > 0:
                buy_shares = np.int64(buy_shares_arr[i])
                cost = buy_shares * closes[i] * (1.0 + commission)
                cash -= cost
                hold_shares += buy_shares
            elif sell_shares_arr[i] > 0:
                sell_shares_count = np.int64(sell_shares_arr[i])
                revenue = sell_shares_count * closes[i] * (1.0 - commission - stamp_tax)
                cash += revenue
                hold_shares -= sell_shares_count
            equity[i] = cash + hold_shares * closes[i]
        return equity


def _equity_curve_pure(
    closes: np.ndarray,
    buy_shares_arr: np.ndarray,
    sell_shares_arr: np.ndarray,
    initial_capital: float,
    commission: float,
    stamp_tax: float,
) -> np.ndarray:
    n = len(closes)
    equity = np.zeros(n)
    cash = float(initial_capital)
    hold_shares = 0
    for i in range(n):
        if buy_shares_arr[i] > 0:
            buy_shares = int(buy_shares_arr[i])
            cost = buy_shares * closes[i] * (1 + commission)
            cash -= cost
            hold_shares += buy_shares
        elif sell_shares_arr[i] > 0:
            sell_shares_count = int(sell_shares_arr[i])
            revenue = sell_shares_count * closes[i] * (1 - commission - stamp_tax)
            cash += revenue
            hold_shares -= sell_shares_count
        equity[i] = cash + hold_shares * closes[i]
    return equity


def vectorized_equity_curve(
    closes: np.ndarray,
    entries: np.ndarray,
    exits: np.ndarray,
    initial_capital: float = 1_000_000.0,
    commission: float = 0.0003,
    stamp_tax: float = 0.001,
    lot_size: int = 100,
) -> tuple[np.ndarray, list[dict]]:
    n = len(closes)
    if n < 2 or not np.any(entries) or not np.any(exits):
        return np.full(n, initial_capital), []

    position = np.zeros(n, dtype=np.int64)
    in_market = False
    entry_price = 0.0
    shares = 0

    for i in range(n):
        if not in_market and entries[i]:
            in_market = True
            entry_price = closes[i]
            alloc = initial_capital * 0.3
            shares = int(alloc / entry_price / lot_size) * lot_size
            if shares <= 0:
                in_market = False
                continue
            position[i] = shares
        elif in_market and exits[i]:
            in_market = False
            position[i] = -shares
            shares = 0
        elif in_market:
            position[i] = shares

    pos_changes = np.diff(np.concatenate([[0], position.astype(float)]))
    buy_mask = pos_changes > 0
    sell_mask = pos_changes < 0

    buy_shares_arr = np.where(buy_mask, pos_changes, 0)
    sell_shares_arr = np.where(sell_mask, -pos_changes, 0)

    equity_func = _equity_curve_numba if _NUMBA_AVAILABLE else _equity_curve_pure
    equity = equity_func(closes, buy_shares_arr, sell_shares_arr, initial_capital, commission, stamp_tax)

    trades: list[dict] = []
    current_entry_idx = -1
    current_entry_price = 0.0
    for i in range(n):
        if buy_shares_arr[i] > 0:
            current_entry_idx = i
            current_entry_price = closes[i]
            buy_shares = int(buy_shares_arr[i])
            trades.append({
                "action": "buy",
                "price": round(closes[i], 2),
                "shares": buy_shares,
                "amount": round(buy_shares * closes[i], 2),
                "fee": round(buy_shares * closes[i] * commission, 2),
                "bar_index": i,
            })
        elif sell_shares_arr[i] > 0:
            sell_shares_count = int(sell_shares_arr[i])
            pnl = (closes[i] - current_entry_price) * sell_shares_count
            pnl -= sell_shares_count * closes[i] * (commission + stamp_tax)
            trades.append({
                "action": "sell",
                "price": round(closes[i], 2),
                "shares": sell_shares_count,
                "amount": round(sell_shares_count * closes[i], 2),
                "fee": round(sell_shares_count * closes[i] * (commission + stamp_tax), 2),
                "pnl": round(pnl, 2),
                "hold_days": i - current_entry_idx if current_entry_idx >= 0 else 0,
                "bar_index": i,
            })

    return equity, trades


def vectorized_backtest(
    df: pd.DataFrame,
    entry_signals: pd.Series,
    exit_signals: pd.Series,
    initial_capital: float = 1_000_000.0,
    commission: float = 0.0003,
    stamp_tax: float = 0.001,
    slippage_pct: float = 0.001,
    lot_size: int = 100,
) -> dict:
    if df.empty or "close" not in df.columns:
        return {"equity_curve": np.array([]), "trades": [], "stats": {}}

    closes = df["close"].values.astype(float)
    entries = entry_signals.values.astype(bool) if isinstance(entry_signals, pd.Series) else np.array(entry_signals, dtype=bool)
    exits = exit_signals.values.astype(bool) if isinstance(exit_signals, pd.Series) else np.array(exit_signals, dtype=bool)

    n = len(closes)
    if len(entries) != n or len(exits) != n:
        logger.warning("Signal length mismatch: closes=%d, entries=%d, exits=%d", n, len(entries), len(exits))
        return {"equity_curve": np.full(n, initial_capital), "trades": [], "stats": {}}

    position = np.zeros(n, dtype=bool)
    in_market = False
    for i in range(n):
        if not in_market and entries[i]:
            in_market = True
            position[i] = True
        elif in_market and exits[i]:
            in_market = False
            position[i] = False
        elif in_market:
            position[i] = True

    prev_position = np.concatenate([[False], position[:-1]])

    buy_mask = position & ~prev_position
    sell_mask = ~position & prev_position

    buy_indices = np.where(buy_mask)[0]
    sell_indices = np.where(sell_mask)[0]

    cash = float(initial_capital)
    shares = 0
    equity_curve = np.zeros(n)
    trades: list[dict] = []
    entry_price = 0.0
    entry_idx = -1

    for i in range(n):
        if buy_mask[i] and shares == 0:
            fill_price = closes[i] * (1 + slippage_pct)
            alloc = cash * 0.3
            buy_shares = int(alloc / fill_price / lot_size) * lot_size
            if buy_shares > 0:
                cost = buy_shares * fill_price
                fee = cost * commission
                total_cost = cost + fee
                if total_cost <= cash:
                    cash -= total_cost
                    shares = buy_shares
                    entry_price = fill_price
                    entry_idx = i
                    trades.append({
                        "action": "buy",
                        "price": round(fill_price, 2),
                        "shares": buy_shares,
                        "amount": round(cost, 2),
                        "fee": round(fee, 2),
                        "bar_index": i,
                    })

        if sell_mask[i] and shares > 0:
            fill_price = closes[i] * (1 - slippage_pct)
            revenue = shares * fill_price
            fee = revenue * (commission + stamp_tax)
            net_revenue = revenue - fee
            pnl = (fill_price - entry_price) * shares - fee
            cash += net_revenue
            trades.append({
                "action": "sell",
                "price": round(fill_price, 2),
                "shares": shares,
                "amount": round(revenue, 2),
                "fee": round(fee, 2),
                "pnl": round(pnl, 2),
                "hold_days": i - entry_idx if entry_idx >= 0 else 0,
                "bar_index": i,
            })
            shares = 0

        equity_curve[i] = cash + shares * closes[i]

    return {
        "equity_curve": equity_curve,
        "trades": trades,
        "position": position,
        "buy_indices": buy_indices,
        "sell_indices": sell_indices,
    }
