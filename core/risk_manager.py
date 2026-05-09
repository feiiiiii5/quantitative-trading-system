__all__ = [
    "RiskFilter",
    "ConcentrationFilter",
    "DailyLossFilter",
    "MaxOpenTradesFilter",
    "CashSufficiencyFilter",
    "TrailingStopManager",
    "ROITable",
    "EnhancedRiskManager",
]

import datetime
import logging
from abc import ABC, abstractmethod
from collections import deque
from typing import Any

import numpy as np

from core.events import Event, EventBus, EventType
from core.orders import Order, OrderSide, OrderType

logger = logging.getLogger(__name__)


class RiskFilter(ABC):
    @abstractmethod
    def check(self, order: Order, context: dict) -> tuple[bool, str]:
        pass


class ConcentrationFilter(RiskFilter):
    def __init__(self, max_concentration: float = 0.3):
        self._max = max_concentration

    def check(self, order: Order, context: dict) -> tuple[bool, str]:
        if order.side != OrderSide.BUY:
            return True, ""
        total_assets = context.get("total_assets", 0)
        if total_assets <= 0:
            return False, "总资产为零或负值"
        current_value = context.get("current_positions", {}).get(order.symbol, {}).get("market_value", 0)
        if order.price is None or order.price <= 0:
            return False, "委托价格无效，无法计算集中度"
        order_value = order.quantity * order.price
        concentration = (current_value + order_value) / total_assets
        if concentration > self._max + 1e-9:
            return False, f"持仓集中度{concentration:.1%}超过上限{self._max:.1%}"
        return True, ""


class DailyLossFilter(RiskFilter):
    def __init__(self, max_daily_loss: float = 0.05, initial_capital: float = 1000000):
        self._max_daily_loss = max_daily_loss
        self._initial_capital = initial_capital
        self._daily_pnl: float = 0.0
        self._circuit_breaker_time: datetime.datetime | None = None
        self._daily_reset_date: str | None = None

    def _reset_if_needed(self):
        today = datetime.date.today().isoformat()
        if self._daily_reset_date != today:
            self._daily_pnl = 0.0
            self._daily_reset_date = today
            self._circuit_breaker_time = None

    def _try_auto_reset_circuit_breaker(self):
        if self._circuit_breaker_time is None:
            return
        recovery_threshold = -self._initial_capital * self._max_daily_loss * 0.5
        if self._daily_pnl >= recovery_threshold:
            self._circuit_breaker_time = None
            logger.info("日内熔断自动解除，当前亏损: %s", self)

    def check(self, order: Order, context: dict) -> tuple[bool, str]:
        self._reset_if_needed()
        self._try_auto_reset_circuit_breaker()
        if self._circuit_breaker_time is not None:
            return False, f"日内熔断中，熔断时间: {self._circuit_breaker_time.isoformat()}"
        effective_capital = context.get("total_assets", self._initial_capital)
        if effective_capital <= 0:
            effective_capital = self._initial_capital
        if self._daily_pnl < -effective_capital * self._max_daily_loss:
            self._circuit_breaker_time = datetime.datetime.now()
            logger.warning("日内亏损熔断触发，亏损: %s", self)
            return False, f"日内亏损超过{self._max_daily_loss * 100:.0f}%，触发熔断"
        return True, ""

    def update_daily_pnl(self, pnl: float, context: dict | None = None):
        self._reset_if_needed()
        self._daily_pnl += pnl
        effective_capital = self._initial_capital
        if context and context.get("total_assets", 0) > 0:
            effective_capital = context["total_assets"]
        if self._daily_pnl < -effective_capital * self._max_daily_loss and self._circuit_breaker_time is None:
            self._circuit_breaker_time = datetime.datetime.now()
            logger.warning("日内亏损熔断触发，亏损: %s", self)


class MaxOpenTradesFilter(RiskFilter):
    def __init__(self, max_open_trades: int = 10):
        self._max = max_open_trades

    def check(self, order: Order, context: dict) -> tuple[bool, str]:
        if order.side != OrderSide.BUY:
            return True, ""
        open_trades = context.get("open_trades", 0)
        if open_trades >= self._max:
            return False, f"持仓数量{open_trades}已达上限{self._max}"
        return True, ""


class CashSufficiencyFilter(RiskFilter):
    def check(self, order: Order, context: dict) -> tuple[bool, str]:
        if order.side != OrderSide.BUY:
            return True, ""
        cash = context.get("cash", 0)
        price = order.price or 0
        order_value = price * order.quantity
        if price <= 0:
            return True, ""
        if order_value > cash:
            max_shares = int(cash / price)
            return False, f"资金不足，需要{order_value:.0f}，可用{cash:.0f}，最多可买{max_shares}股"
        return True, ""


class TrailingStopManager:
    def __init__(
        self,
        trailing_stop: float = -0.05,
        trailing_stop_positive: float = 0.02,
        trailing_stop_positive_offset: float = 0.05,
        trailing_only_offset_is_reached: bool = True,
    ):
        self._trailing_stop = trailing_stop
        self._trailing_stop_positive = trailing_stop_positive
        self._trailing_stop_positive_offset = trailing_stop_positive_offset
        self._trailing_only_offset = trailing_only_offset_is_reached
        self._positions: dict[str, dict] = {}

    def register(self, symbol: str, entry_price: float, side: str = "long"):
        is_short = side == "short"
        self._positions[symbol] = {
            "entry_price": entry_price,
            "highest_price": entry_price,
            "lowest_price": entry_price,
            "stop_price": entry_price * (1 - self._trailing_stop) if is_short else entry_price * (1 + self._trailing_stop),
            "side": side,
        }

    def unregister(self, symbol: str):
        self._positions.pop(symbol, None)

    def update(self, symbol: str, current_price: float) -> str | None:
        pos = self._positions.get(symbol)
        if pos is None:
            return None

        is_short = pos.get("side", "long") == "short"

        if current_price > pos["highest_price"]:
            pos["highest_price"] = current_price
        if "lowest_price" not in pos:
            pos["lowest_price"] = current_price
        if current_price < pos["lowest_price"]:
            pos["lowest_price"] = current_price

        if is_short:
            profit_pct = (pos["entry_price"] - current_price) / pos["entry_price"]
            if self._trailing_only_offset and profit_pct < self._trailing_stop_positive_offset:
                stop_price = pos["entry_price"] * (1 - self._trailing_stop)
            else:
                stop_price = pos["lowest_price"] * (1 + self._trailing_stop_positive)
            pos["stop_price"] = min(pos["stop_price"], stop_price)
            if current_price >= pos["stop_price"]:
                return "trailing_stop"
        else:
            profit_pct = (current_price - pos["entry_price"]) / pos["entry_price"]
            if self._trailing_only_offset and profit_pct < self._trailing_stop_positive_offset:
                stop_price = pos["entry_price"] * (1 + self._trailing_stop)
            else:
                stop_price = pos["highest_price"] * (1 - self._trailing_stop_positive)
            pos["stop_price"] = max(pos["stop_price"], stop_price)
            if current_price <= pos["stop_price"]:
                return "trailing_stop"

        return None

    def get_stop_price(self, symbol: str) -> float | None:
        pos = self._positions.get(symbol)
        return pos["stop_price"] if pos else None


class ROITable:
    def __init__(self, roi_table: dict[str, float] | None = None):
        self._roi = roi_table or {"0": 0.10, "30": 0.05, "60": 0.02, "120": 0.01}
        self._sorted_minutes: list[tuple[int, float]] = sorted(
            [(int(k), v) for k, v in self._roi.items()],
            key=lambda x: x[0],
        )

    def should_take_profit(self, profit_pct: float, holding_minutes: int) -> bool:
        threshold = self._get_threshold(holding_minutes)
        return profit_pct >= threshold

    def _get_threshold(self, holding_minutes: int) -> float:
        result = 999999.0
        for minutes, roi in self._sorted_minutes:
            if holding_minutes >= minutes:
                result = roi
            else:
                break
        return result


class EnhancedRiskManager:
    def __init__(
        self,
        max_concentration: float = 0.3,
        max_daily_loss: float = 0.05,
        initial_capital: float = 1000000,
        max_open_trades: int = 10,
        trailing_stop: float = -0.05,
        trailing_stop_positive: float = 0.02,
        trailing_stop_positive_offset: float = 0.05,
        roi_table: dict[str, float] | None = None,
        event_bus: EventBus | None = None,
    ):
        self._initial_capital = initial_capital
        self._event_bus = event_bus

        self._filters: list[RiskFilter] = [
            DailyLossFilter(max_daily_loss, initial_capital),
            ConcentrationFilter(max_concentration),
            MaxOpenTradesFilter(max_open_trades),
            CashSufficiencyFilter(),
        ]

        self._trailing_stop = TrailingStopManager(
            trailing_stop=trailing_stop,
            trailing_stop_positive=trailing_stop_positive,
            trailing_stop_positive_offset=trailing_stop_positive_offset,
        )
        self._roi_table = ROITable(roi_table)
        self._position_returns: dict[str, deque] = {}

    def check_order(self, order: Order, context: dict) -> tuple[bool, str]:
        for f in self._filters:
            approved, reason = f.check(order, context)
            if not approved:
                if self._event_bus:
                    self._event_bus.publish(Event(EventType.ORDER_REJECTED, {"order": order, "reason": reason}))
                return False, reason
        return True, ""

    def check_order_legacy(
        self,
        symbol: str,
        action: str,
        shares: int,
        price: float,
        current_positions: dict,
        total_assets: float,
    ) -> dict[str, object]:
        from core.orders import OrderSide
        order = Order(
            order_id="legacy_check",
            symbol=symbol,
            side=OrderSide.BUY if action == "buy" else OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=shares,
            price=price,
        )
        context = {
            "current_positions": current_positions,
            "total_assets": total_assets,
            "cash": total_assets - sum(p.get("market_value", 0) for p in current_positions.values()),
            "open_trades": len(current_positions),
        }
        approved, reason = self.check_order(order, context)
        return {"approved": approved, "reason": reason}

    def register_position(self, symbol: str, entry_price: float):
        self._trailing_stop.register(symbol, entry_price)

    def unregister_position(self, symbol: str):
        self._trailing_stop.unregister(symbol)
        self._position_returns.pop(symbol, None)

    def check_trailing_stop(self, symbol: str, current_price: float) -> str | None:
        return self._trailing_stop.update(symbol, current_price)

    def check_roi_take_profit(self, symbol: str, profit_pct: float, holding_minutes: int) -> bool:
        return self._roi_table.should_take_profit(profit_pct, holding_minutes)

    def get_stop_price(self, symbol: str) -> float | None:
        return self._trailing_stop.get_stop_price(symbol)

    def update_daily_pnl(self, pnl: float):
        for f in self._filters:
            if isinstance(f, DailyLossFilter):
                f.update_daily_pnl(pnl)
                break

    def reset(self) -> None:
        for f in self._filters:
            if isinstance(f, DailyLossFilter):
                f._daily_pnl = 0.0
                f._circuit_breaker_time = None
                f._daily_reset_date = None
        self._trailing_stop._positions.clear()
        self._position_returns.clear()

    def calc_var(self, returns_history: list[float], portfolio_value: float) -> float:
        """计算VaR(95%)，返回正值表示可能的最大损失金额"""
        if len(returns_history) < 20:
            return 0.0
        arr = np.array(returns_history[-20:])
        var_5pct = np.percentile(arr, 5)
        return float(abs(var_5pct * portfolio_value))

    def calc_cvar(self, returns_history: list[float], portfolio_value: float) -> float:
        """计算CVaR/ES(95%)，返回正值表示尾部平均损失金额"""
        if len(returns_history) < 20:
            return 0.0
        arr = np.array(returns_history[-20:])
        var_5pct = np.percentile(arr, 5)
        tail = arr[arr <= var_5pct]
        if len(tail) == 0:
            return float(abs(var_5pct * portfolio_value))
        return float(abs(float(np.mean(tail)) * portfolio_value))

    def update_position_returns(self, symbol: str, daily_return: float):
        if symbol not in self._position_returns:
            self._position_returns[symbol] = deque(maxlen=252)
        self._position_returns[symbol].append(daily_return)
        if len(self._position_returns) > 500:
            oldest_symbol = next(iter(self._position_returns))
            del self._position_returns[oldest_symbol]

    def get_risk_report(self) -> dict[str, Any]:
        daily_loss_filter = None
        conc_filter_max = 0.3
        for f in self._filters:
            if isinstance(f, DailyLossFilter):
                daily_loss_filter = f
            if isinstance(f, ConcentrationFilter):
                conc_filter_max = f._max

        # 汇总所有持仓收益率计算组合VaR/CVaR
        all_returns: list[float] = []
        for rets in self._position_returns.values():
            all_returns.extend(rets)
        var_val = self.calc_var(all_returns, self._initial_capital) if len(all_returns) >= 20 else 0.0
        cvar_val = self.calc_cvar(all_returns, self._initial_capital) if len(all_returns) >= 20 else 0.0

        report = {
            "max_concentration": conc_filter_max,
            "current_daily_pnl": daily_loss_filter._daily_pnl if daily_loss_filter else 0.0,
            "daily_loss_limit": self._initial_capital * 0.05,
            "circuit_breaker_active": daily_loss_filter._circuit_breaker_time is not None if daily_loss_filter else False,
            "circuit_breaker_time": daily_loss_filter._circuit_breaker_time.isoformat() if daily_loss_filter and daily_loss_filter._circuit_breaker_time else None,
            "var": round(var_val, 2),
            "cvar": round(cvar_val, 2),
            "trailing_stop_positions": list(self._trailing_stop._positions.keys()),
            "active_filters": [f.__class__.__name__ for f in self._filters],
        }
        return report
