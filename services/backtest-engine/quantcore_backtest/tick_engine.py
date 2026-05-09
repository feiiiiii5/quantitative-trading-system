import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

import numpy as np

logger = logging.getLogger(__name__)

_TRADING_DAYS_PER_YEAR = 252
_RISK_FREE_RATE = 0.0
_MIN_TRADES_FOR_METRICS = 2


class SlippageModel(Enum):
    LINEAR = "linear"
    SQUARE_ROOT = "square_root"
    PROPORTIONAL = "proportional"


@dataclass(frozen=True)
class BacktestMetrics:
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    avg_trade_return: float = 0.0
    calmar_ratio: float = 0.0


@dataclass
class BacktestResult:
    metrics: BacktestMetrics = field(default_factory=BacktestMetrics)
    equity_curve: list[float] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    positions_history: list[dict[str, Any]] = field(default_factory=list)
    backtest_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


def _compute_slippage(
    price: float,
    order_size: float,
    avg_daily_volume: float,
    model: SlippageModel,
    base_bps: float,
    impact_coeff: float,
) -> float:
    if avg_daily_volume <= 0:
        return price * base_bps / 10_000

    participation_rate = abs(order_size) / avg_daily_volume

    if model == SlippageModel.LINEAR:
        slip_bps = base_bps + impact_coeff * participation_rate * 10_000
    elif model == SlippageModel.SQUARE_ROOT:
        slip_bps = base_bps + impact_coeff * np.sqrt(participation_rate) * 10_000
    elif model == SlippageModel.PROPORTIONAL:
        slip_bps = base_bps * (1.0 + participation_rate)
    else:
        slip_bps = base_bps

    return price * slip_bps / 10_000


class TickLevelBacktester:
    def __init__(
        self,
        commission: float = 0.0003,
        slippage_model: SlippageModel = SlippageModel.SQUARE_ROOT,
        slippage_base_bps: float = 1.0,
        slippage_impact_coeff: float = 0.1,
        lot_size: int = 100,
    ) -> None:
        self._commission = commission
        self._slippage_model = slippage_model
        self._slippage_base_bps = slippage_base_bps
        self._slippage_impact_coeff = slippage_impact_coeff
        self._lot_size = lot_size

    def run(
        self,
        ticks: list[dict[str, Any]],
        strategy_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
        initial_capital: float = 1_000_000.0,
    ) -> BacktestResult:
        if not ticks:
            logger.warning("Empty tick list provided; returning empty result")
            return BacktestResult()

        cash = initial_capital
        position_qty = 0
        position_avg_price = 0.0
        equity_curve: list[float] = [initial_capital]
        trades: list[dict[str, Any]] = []
        positions_history: list[dict[str, Any]] = []
        state: dict[str, Any] = {"cash": cash, "position_qty": 0, "position_avg_price": 0.0}

        prices = np.array([t.get("price", 0.0) for t in ticks], dtype=np.float64)
        volumes = np.array([t.get("size", 0) for t in ticks], dtype=np.float64)
        avg_volume = float(np.mean(volumes)) if len(volumes) > 0 else 1.0

        for idx, tick in enumerate(ticks):
            signal = strategy_fn(tick, state)

            if signal and signal.get("action") in ("buy", "sell"):
                result = self._process_tick(
                    tick=tick,
                    signal=signal,
                    cash=cash,
                    position_qty=position_qty,
                    position_avg_price=position_avg_price,
                    avg_volume=avg_volume,
                )

                if result["filled"]:
                    cash = result["cash"]
                    position_qty = result["position_qty"]
                    position_avg_price = result["position_avg_price"]
                    trades.append(result["trade"])
                    state.update({
                        "cash": cash,
                        "position_qty": position_qty,
                        "position_avg_price": position_avg_price,
                    })

            mid_price = tick.get("price", 0.0)
            if position_qty > 0 and mid_price > 0:
                equity = cash + position_qty * mid_price
            else:
                equity = cash
            equity_curve.append(equity)

            positions_history.append({
                "timestamp_ns": tick.get("timestamp_ns", 0),
                "qty": position_qty,
                "avg_price": position_avg_price,
                "equity": equity,
            })

        if position_qty > 0 and len(ticks) > 0:
            last_price = ticks[-1].get("price", 0.0)
            if last_price > 0:
                close_signal = {"action": "sell", "qty": position_qty, "reason": "end_of_backtest"}
                result = self._process_tick(
                    tick=ticks[-1],
                    signal=close_signal,
                    cash=cash,
                    position_qty=position_qty,
                    position_avg_price=position_avg_price,
                    avg_volume=avg_volume,
                )
                if result["filled"]:
                    cash = result["cash"]
                    position_qty = 0
                    position_avg_price = 0.0
                    trades.append(result["trade"])

        metrics = self._compute_metrics(equity_curve, trades, initial_capital)

        return BacktestResult(
            metrics=metrics,
            equity_curve=equity_curve,
            trades=trades,
            positions_history=positions_history,
        )

    def _process_tick(
        self,
        tick: dict[str, Any],
        signal: dict[str, Any],
        cash: float,
        position_qty: float,
        position_avg_price: float,
        avg_volume: float,
    ) -> dict[str, Any]:
        action = signal["action"]
        price = tick.get("price", 0.0)
        if price <= 0:
            return {"filled": False}

        if action == "buy":
            return self._handle_buy(
                tick, signal, price, cash, position_qty, position_avg_price, avg_volume,
            )
        if action == "sell":
            return self._handle_sell(
                tick, signal, price, cash, position_qty, position_avg_price, avg_volume,
            )
        return {"filled": False}

    def _handle_buy(
        self,
        tick: dict[str, Any],
        signal: dict[str, Any],
        price: float,
        cash: float,
        position_qty: float,
        position_avg_price: float,
        avg_volume: float,
    ) -> dict[str, Any]:
        if position_qty > 0:
            return {"filled": False}

        requested_qty = signal.get("qty", 0)
        if requested_qty <= 0:
            alloc_pct = signal.get("alloc_pct", 0.3)
            alloc_amount = cash * alloc_pct
            requested_qty = int(alloc_amount / price / self._lot_size) * self._lot_size

        if requested_qty <= 0:
            return {"filled": False}

        order_value = requested_qty * price
        if order_value > cash * 0.98:
            requested_qty = int(cash * 0.98 / price / self._lot_size) * self._lot_size
            if requested_qty <= 0:
                return {"filled": False}

        fill = self._simulate_fill(
            order={"action": "buy", "qty": requested_qty, "price": price},
            tick=tick,
            avg_volume=avg_volume,
        )

        commission_cost = fill["fill_value"] * self._commission
        total_cost = fill["fill_value"] + commission_cost

        if total_cost > cash:
            requested_qty = int((cash * 0.98) / fill["fill_price"] / self._lot_size) * self._lot_size
            if requested_qty <= 0:
                return {"filled": False}
            fill = self._simulate_fill(
                order={"action": "buy", "qty": requested_qty, "price": price},
                tick=tick,
                avg_volume=avg_volume,
            )
            commission_cost = fill["fill_value"] * self._commission
            total_cost = fill["fill_value"] + commission_cost

        new_cash = cash - total_cost
        new_qty = position_qty + fill["fill_qty"]
        new_avg = fill["fill_price"] if new_qty > 0 else 0.0

        trade = {
            "action": "buy",
            "timestamp_ns": tick.get("timestamp_ns", 0),
            "symbol": tick.get("symbol", ""),
            "price": fill["fill_price"],
            "qty": fill["fill_qty"],
            "commission": round(commission_cost, 2),
            "slippage": round(fill["slippage"], 4),
            "reason": signal.get("reason", ""),
        }

        return {
            "filled": True,
            "cash": new_cash,
            "position_qty": new_qty,
            "position_avg_price": new_avg,
            "trade": trade,
        }

    def _handle_sell(
        self,
        tick: dict[str, Any],
        signal: dict[str, Any],
        price: float,
        cash: float,
        position_qty: float,
        position_avg_price: float,
        avg_volume: float,
    ) -> dict[str, Any]:
        if position_qty <= 0:
            return {"filled": False}

        sell_qty = min(signal.get("qty", position_qty), position_qty)
        if sell_qty <= 0:
            return {"filled": False}

        fill = self._simulate_fill(
            order={"action": "sell", "qty": sell_qty, "price": price},
            tick=tick,
            avg_volume=avg_volume,
        )

        commission_cost = fill["fill_value"] * self._commission
        net_proceeds = fill["fill_value"] - commission_cost

        pnl = (fill["fill_price"] - position_avg_price) * fill["fill_qty"] - commission_cost

        new_cash = cash + net_proceeds
        new_qty = position_qty - fill["fill_qty"]
        new_avg = position_avg_price if new_qty > 0 else 0.0

        trade = {
            "action": "sell",
            "timestamp_ns": tick.get("timestamp_ns", 0),
            "symbol": tick.get("symbol", ""),
            "price": fill["fill_price"],
            "qty": fill["fill_qty"],
            "commission": round(commission_cost, 2),
            "slippage": round(fill["slippage"], 4),
            "pnl": round(pnl, 2),
            "reason": signal.get("reason", ""),
        }

        return {
            "filled": True,
            "cash": new_cash,
            "position_qty": new_qty,
            "position_avg_price": new_avg,
            "trade": trade,
        }

    def _simulate_fill(
        self,
        order: dict[str, Any],
        tick: dict[str, Any],
        avg_volume: float,
    ) -> dict[str, Any]:
        price = order["price"]
        qty = order["qty"]
        action = order["action"]

        slippage = _compute_slippage(
            price=price,
            order_size=qty * price,
            avg_daily_volume=avg_volume,
            model=self._slippage_model,
            base_bps=self._slippage_base_bps,
            impact_coeff=self._slippage_impact_coeff,
        )

        if action == "buy":
            fill_price = price + slippage
        else:
            fill_price = price - slippage

        fill_price = max(fill_price, 1e-9)
        fill_value = qty * fill_price

        return {
            "fill_price": fill_price,
            "fill_qty": qty,
            "fill_value": fill_value,
            "slippage": slippage,
        }

    def _compute_metrics(
        self,
        equity_curve: list[float],
        trades: list[dict[str, Any]],
        initial_capital: float,
    ) -> BacktestMetrics:
        eq = np.array(equity_curve, dtype=np.float64)

        if len(eq) < 2 or eq[0] <= 0:
            return BacktestMetrics()

        returns = np.diff(eq) / eq[:-1]
        returns = returns[np.isfinite(returns)]

        if len(returns) == 0:
            return BacktestMetrics()

        avg_ret = float(np.mean(returns))
        std_ret = float(np.std(returns))

        sharpe = (avg_ret / std_ret * np.sqrt(_TRADING_DAYS_PER_YEAR)) if std_ret > 1e-12 else 0.0

        downside = returns[returns < 0]
        downside_dev = float(np.sqrt(np.mean(downside ** 2))) if len(downside) > 0 else 0.0
        sortino = (avg_ret * _TRADING_DAYS_PER_YEAR) / (downside_dev * np.sqrt(_TRADING_DAYS_PER_YEAR)) if downside_dev > 1e-12 else 0.0

        peaks = np.maximum.accumulate(eq)
        drawdowns = (peaks - eq) / np.where(peaks > 1e-9, peaks, 1.0)
        max_drawdown = float(np.max(drawdowns))

        sell_trades = [t for t in trades if t.get("action") == "sell"]
        total_trades = len(sell_trades)

        if total_trades >= _MIN_TRADES_FOR_METRICS:
            pnls = np.array([t.get("pnl", 0.0) for t in sell_trades], dtype=np.float64)
            win_mask = pnls > 0
            win_rate = float(np.mean(win_mask))
            total_wins = float(np.sum(pnls[win_mask])) if np.any(win_mask) else 0.0
            total_losses = abs(float(np.sum(pnls[~win_mask]))) if np.any(~win_mask) else 0.0
            profit_factor = total_wins / total_losses if total_losses > 1e-9 else (999.0 if total_wins > 0 else 0.0)
            avg_trade_return = float(np.mean(pnls)) / initial_capital if initial_capital > 0 else 0.0
        else:
            win_rate = 0.0
            profit_factor = 0.0
            avg_trade_return = 0.0

        annual_return = ((eq[-1] / eq[0]) ** (_TRADING_DAYS_PER_YEAR / max(len(eq) - 1, 1)) - 1) if eq[0] > 0 else 0.0
        calmar_ratio = annual_return / max_drawdown if max_drawdown > 1e-9 else 0.0

        return BacktestMetrics(
            sharpe=round(sharpe, 4),
            sortino=round(sortino, 4),
            max_drawdown=round(max_drawdown, 6),
            win_rate=round(win_rate, 4),
            profit_factor=round(profit_factor, 4),
            total_trades=total_trades,
            avg_trade_return=round(avg_trade_return, 6),
            calmar_ratio=round(calmar_ratio, 4),
        )
