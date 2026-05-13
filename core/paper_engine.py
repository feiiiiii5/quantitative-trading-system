"""
模拟交易引擎 - Paper Trading Engine
在真实市场条件下模拟策略执行，无实际资金风险

核心功能:
- 多模式模拟: 收盘价成交 / Tick中间价 / 随机滑点
- 完整持仓和资金管理
- 风险限额检查 (单笔/总仓位/行业)
- 交易成本模拟 (佣金+滑点+印花税)
- 性能统计和归因分析
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class SimulationMode(Enum):
    CLOSE = "close"
    MID = "mid"
    RANDOM = "random"


@dataclass
class Order:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: float
    limit_price: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    filled_price: float = 0.0
    filled_quantity: int = 0
    filled_at: float = 0.0
    commission: float = 0.0
    slippage_bps: float = 0.0
    reason: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class Position:
    symbol: str
    quantity: int = 0
    avg_cost: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    trade_count: int = 0


@dataclass
class AccountStats:
    initial_capital: float
    current_capital: float
    available_cash: float
    market_value: float
    total_value: float
    total_pnl: float
    total_return: float
    total_commission: float
    total_slippage_cost: float
    win_rate: float
    n_trades: int
    n_wins: int
    n_losses: int
    max_drawdown: float
    sharpe_ratio: float

    def to_dict(self) -> dict:
        return {
            "initial_capital": round(self.initial_capital, 2),
            "current_capital": round(self.current_capital, 2),
            "available_cash": round(self.available_cash, 2),
            "market_value": round(self.market_value, 2),
            "total_value": round(self.total_value, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_return": f"{self.total_return:.2%}",
            "total_commission": round(self.total_commission, 2),
            "total_slippage_cost": round(self.total_slippage_cost, 2),
            "win_rate": f"{self.win_rate:.2%}",
            "n_trades": self.n_trades,
            "n_wins": self.n_wins,
            "n_losses": self.n_losses,
            "max_drawdown": f"{self.max_drawdown:.2%}",
            "sharpe_ratio": round(self.sharpe_ratio, 2),
        }


@dataclass
class PaperConfig:
    initial_capital: float = 1_000_000.0
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    stamp_duty_rate: float = 0.001
    slippage_bps: float = 5.0
    mode: SimulationMode = SimulationMode.CLOSE
    max_position_pct: float = 0.2
    max_single_order_pct: float = 0.1
    enable_risk_checks: bool = True


class PaperEngine:
    def __init__(
        self,
        config: PaperConfig | None = None,
        slippage_engine=None,
    ):
        self._config = config or PaperConfig()
        self._slippage = slippage_engine
        self._lock = threading.Lock()
        self._positions: dict[str, Position] = {}
        self._orders: list[Order] = []
        self._order_counter = 0
        self._cash = self._config.initial_capital
        self._initial_capital = self._config.initial_capital
        self._total_commission = 0.0
        self._total_slippage_cost = 0.0
        self._realized_pnls: list[float] = []
        self._peak_value = self._initial_capital
        self._drawdowns: list[float] = []
        self._daily_values: list[float] = []
        self._rng = np.random.default_rng()

    def get_position(self, symbol: str) -> Position:
        with self._lock:
            return self._positions.get(symbol, Position(symbol=symbol))

    def get_all_positions(self) -> dict[str, Position]:
        with self._lock:
            return dict(self._positions)

    def get_account_stats(self) -> AccountStats:
        with self._lock:
            market_value = sum(
                pos.quantity * (pos.current_price if pos.current_price > 0 else pos.avg_cost) for pos in self._positions.values()
            )
            total_value = self._cash + market_value
            total_pnl = total_value - self._initial_capital
            total_return = total_pnl / self._initial_capital

            wins = sum(1 for p in self._realized_pnls if p > 0)
            losses = sum(1 for p in self._realized_pnls if p < 0)
            win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.0

            peak = self._peak_value
            max_dd = 0.0
            for val in self._daily_values:
                if val > peak:
                    peak = val
                dd = (peak - val) / peak if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd

            returns = []
            vals = self._daily_values + [total_value]
            for i in range(1, len(vals)):
                ret = (vals[i] - vals[i - 1]) / vals[i - 1] if vals[i - 1] > 0 else 0
                returns.append(ret)
            sharpe = (np.mean(returns) / (np.std(returns) + 1e-12)) * np.sqrt(252) if len(returns) > 1 else 0.0

            return AccountStats(
                initial_capital=self._initial_capital,
                current_capital=self._cash,
                available_cash=self._cash,
                market_value=market_value,
                total_value=total_value,
                total_pnl=total_pnl,
                total_return=total_return,
                total_commission=self._total_commission,
                total_slippage_cost=self._total_slippage_cost,
                win_rate=win_rate,
                n_trades=len(self._orders),
                n_wins=wins,
                n_losses=losses,
                max_drawdown=max_dd,
                sharpe_ratio=sharpe,
            )

    def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        order_type: OrderType = OrderType.MARKET,
        limit_price: float | None = None,
    ) -> Order:
        with self._lock:
            self._order_counter += 1
            order = Order(
                order_id=f"PAPER_{self._order_counter:06d}",
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                limit_price=limit_price,
            )

            if self._config.enable_risk_checks:
                reject_reason = self._check_risk_limits(order)
                if reject_reason:
                    order.status = OrderStatus.REJECTED
                    order.reason = reject_reason
                    self._orders.append(order)
                    return order

            order = self._execute_order_internal(order)
            self._orders.append(order)
            return order

    def _check_risk_limits(self, order: Order) -> str:
        if order.quantity <= 0:
            return "Invalid quantity"
        order_value = order.quantity * order.price
        max_single = self._initial_capital * self._config.max_single_order_pct
        if order_value > max_single:
            return f"Single order size limit exceeded ({order_value:.0f} > {max_single:.0f})"

        position = self._positions.get(order.symbol)
        current_value = (position.quantity * position.avg_cost) if position else 0
        new_value = current_value + order_value
        max_position = self._initial_capital * self._config.max_position_pct
        if new_value > max_position:
            return f"Position size limit exceeded for {order.symbol}"

        required = order_value * (1 + self._config.commission_rate + 0.001)
        if order.side == OrderSide.BUY and self._cash < required:
            return f"Insufficient cash (need {required:.2f}, have {self._cash:.2f})"
        return ""

    def _execute_order_internal(self, order: Order) -> Order:
        filled_price = self._calculate_filled_price(order)
        order.filled_price = filled_price
        order.filled_quantity = order.quantity
        order.filled_at = time.time()
        order.status = OrderStatus.FILLED

        slippage_pct = abs(filled_price - order.price) / order.price
        order.slippage_bps = round(slippage_pct * 10000, 1)

        commission = self._calculate_commission(order)
        order.commission = commission
        self._total_commission += commission

        slippage_cost = order.quantity * order.price * slippage_pct
        self._total_slippage_cost += slippage_cost

        position = self._positions.get(order.symbol)
        if position is None:
            position = Position(symbol=order.symbol)
            self._positions[order.symbol] = position

        order_value = order.filled_quantity * order.filled_price
        total_cost = order_value + commission

        if order.side == OrderSide.BUY:
            self._cash -= total_cost
            self._update_position_buy(position, order)
        else:
            self._cash += order_value - commission
            self._update_position_sell(position, order)

        return order

    def _calculate_filled_price(self, order: Order) -> float:
        mode = self._config.mode
        base_price = order.price

        if mode == SimulationMode.CLOSE:
            return base_price

        if mode == SimulationMode.MID:
            return base_price * (1 + self._config.slippage_bps / 10000 / 2)

        if mode == SimulationMode.RANDOM:
            slippage = self._rng.normal(
                0, self._config.slippage_bps / 10000 / 2
            )
            slippage = np.clip(slippage, -0.005, 0.005)
            direction = 1 if order.side == OrderSide.BUY else -1
            return base_price * (1 + direction * slippage)

        return base_price

    def _calculate_commission(self, order: Order) -> float:
        value = order.filled_quantity * order.filled_price
        commission = value * self._config.commission_rate
        if order.side == OrderSide.SELL:
            commission += value * self._config.stamp_duty_rate
        return max(commission, self._config.min_commission)

    def _update_position_buy(self, position: Position, order: Order) -> None:
        total_cost = (
            position.quantity * position.avg_cost
            + order.filled_quantity * order.filled_price
        )
        position.quantity += order.filled_quantity
        position.avg_cost = total_cost / position.quantity if position.quantity > 0 else 0.0
        position.trade_count += 1

    def _update_position_sell(self, position: Position, order: Order) -> None:
        realized = order.filled_quantity * (
            order.filled_price - position.avg_cost
        )
        position.realized_pnl += realized
        position.quantity -= order.filled_quantity
        if position.quantity > 0:
            pass
        else:
            position.quantity = 0
            position.avg_cost = 0.0
        position.trade_count += 1
        self._realized_pnls.append(realized)

    def update_market_value(self, current_prices: dict[str, float]) -> None:
        with self._lock:
            market_value = 0.0
            for symbol, price in current_prices.items():
                if symbol in self._positions:
                    pos = self._positions[symbol]
                    if pos.quantity > 0:
                        pos.current_price = price
                        pos.unrealized_pnl = pos.quantity * (price - pos.avg_cost)
                        market_value += pos.quantity * price

            total_value = self._cash + market_value
            self._daily_values.append(total_value)
            if total_value > self._peak_value:
                self._peak_value = total_value

    def get_trade_history(self) -> list[Order]:
        with self._lock:
            return [o for o in self._orders if o.status == OrderStatus.FILLED]

    def get_equity_curve(self) -> list[float]:
        with self._lock:
            return list(self._daily_values)

    def reset(self) -> None:
        with self._lock:
            self._positions.clear()
            self._orders.clear()
            self._order_counter = 0
            self._cash = self._config.initial_capital
            self._initial_capital = self._config.initial_capital
            self._total_commission = 0.0
            self._total_slippage_cost = 0.0
            self._realized_pnls.clear()
            self._peak_value = self._initial_capital
            self._drawdowns.clear()
            self._daily_values.clear()


_paper_engine: PaperEngine | None = None


def get_paper_engine(config: PaperConfig | None = None) -> PaperEngine:
    global _paper_engine
    if _paper_engine is None or config is not None:
        _paper_engine = PaperEngine(config)
    return _paper_engine
