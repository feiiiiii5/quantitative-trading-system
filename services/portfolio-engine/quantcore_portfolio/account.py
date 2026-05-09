import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    weight_pct: float
    timestamp_ns: int

    def recalculate(self, total_portfolio_value: float) -> None:
        self.market_value = self.quantity * self.current_price
        cost_basis = self.quantity * self.avg_cost
        self.unrealized_pnl = self.market_value - cost_basis
        self.unrealized_pnl_pct = (
            self.unrealized_pnl / cost_basis if cost_basis != 0 else 0.0
        )
        self.weight_pct = (
            self.market_value / total_portfolio_value * 100
            if total_portfolio_value != 0
            else 0.0
        )
        self.timestamp_ns = time.time_ns()


@dataclass
class Account:
    account_id: str
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    _realized_pnl_history: list[tuple[date, float]] = field(default_factory=list)

    @property
    def total_market_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def total_value(self) -> float:
        return self.cash + self.total_market_value

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions.values())

    def record_realized_pnl(self, pnl_amount: float, trade_date: date | None = None) -> None:
        entry_date = trade_date or date.today()
        self._realized_pnl_history.append((entry_date, pnl_amount))


@dataclass
class FillResult:
    symbol: str
    side: str
    quantity: int
    price: float
    commission: float
    realized_pnl: float
    new_quantity: int
    new_avg_cost: float
    cash_remaining: float


class AccountManager:
    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._lock = threading.RLock()

    def create_account(self, account_id: str, initial_cash: float) -> Account:
        with self._lock:
            if account_id in self._accounts:
                raise ValueError(f"Account {account_id} already exists")
            account = Account(account_id=account_id, cash=initial_cash)
            self._accounts[account_id] = account
            logger.info("Account created: %s with cash %.2f", account_id, initial_cash)
            return account

    def get_account(self, account_id: str) -> Optional[Account]:
        with self._lock:
            return self._accounts.get(account_id)

    def update_position(
        self, account_id: str, symbol: str, quantity_delta: int, price: float
    ) -> Position:
        with self._lock:
            account = self._accounts.get(account_id)
            if account is None:
                raise ValueError(f"Account {account_id} not found")

            existing = account.positions.get(symbol)
            if existing is None:
                if quantity_delta < 0:
                    raise ValueError(
                        f"Cannot short {symbol}: no existing position in account {account_id}"
                    )
                position = Position(
                    symbol=symbol,
                    quantity=quantity_delta,
                    avg_cost=price,
                    current_price=price,
                    market_value=quantity_delta * price,
                    unrealized_pnl=0.0,
                    unrealized_pnl_pct=0.0,
                    weight_pct=0.0,
                    timestamp_ns=time.time_ns(),
                )
                account.positions[symbol] = position
            else:
                new_quantity = existing.quantity + quantity_delta
                if new_quantity < 0:
                    raise ValueError(
                        f"Insufficient position: have {existing.quantity}, "
                        f"attempting to reduce by {abs(quantity_delta)}"
                    )
                if new_quantity == 0:
                    del account.positions[symbol]
                    logger.info(
                        "Position closed: %s in account %s", symbol, account_id
                    )
                    return existing

                if quantity_delta > 0:
                    old_cost_basis = existing.quantity * existing.avg_cost
                    added_cost_basis = quantity_delta * price
                    new_avg_cost = (old_cost_basis + added_cost_basis) / new_quantity
                    existing.avg_cost = new_avg_cost

                existing.quantity = new_quantity
                existing.current_price = price

            for pos in account.positions.values():
                pos.recalculate(account.total_value)

            result = account.positions.get(symbol)
            if result is None:
                return existing
            logger.info(
                "Position updated: %s in account %s, delta=%d, price=%.2f",
                symbol,
                account_id,
                quantity_delta,
                price,
            )
            return result

    def close_position(self, account_id: str, symbol: str) -> Optional[Position]:
        with self._lock:
            account = self._accounts.get(account_id)
            if account is None:
                raise ValueError(f"Account {account_id} not found")

            position = account.positions.pop(symbol, None)
            if position is None:
                logger.warning("No position to close: %s in account %s", symbol, account_id)
                return None

            proceeds = position.quantity * position.current_price
            cost_basis = position.quantity * position.avg_cost
            realized = proceeds - cost_basis
            account.cash += proceeds
            account.record_realized_pnl(realized)

            for pos in account.positions.values():
                pos.recalculate(account.total_value)

            logger.info(
                "Position closed: %s in account %s, realized PnL=%.2f",
                symbol,
                account_id,
                realized,
            )
            return position

    def get_total_value(self, account_id: str) -> float:
        with self._lock:
            account = self._accounts.get(account_id)
            if account is None:
                raise ValueError(f"Account {account_id} not found")
            return account.total_value

    def get_unrealized_pnl(self, account_id: str) -> float:
        with self._lock:
            account = self._accounts.get(account_id)
            if account is None:
                raise ValueError(f"Account {account_id} not found")
            return account.total_unrealized_pnl

    def get_realized_pnl(self, account_id: str, start_date: date, end_date: date) -> float:
        with self._lock:
            account = self._accounts.get(account_id)
            if account is None:
                raise ValueError(f"Account {account_id} not found")
            return sum(
                pnl
                for d, pnl in account._realized_pnl_history
                if start_date <= d <= end_date
            )

    def apply_fill(
        self,
        account_id: str,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        commission: float,
    ) -> FillResult:
        with self._lock:
            account = self._accounts.get(account_id)
            if account is None:
                raise ValueError(f"Account {account_id} not found")

            if side.upper() == "BUY":
                total_cost = quantity * price + commission
                if account.cash < total_cost:
                    raise ValueError(
                        f"Insufficient cash: have {account.cash:.2f}, need {total_cost:.2f}"
                    )
                account.cash -= total_cost
                quantity_delta = quantity
                realized_pnl = 0.0
            elif side.upper() == "SELL":
                existing = account.positions.get(symbol)
                if existing is None or existing.quantity < quantity:
                    available = existing.quantity if existing else 0
                    raise ValueError(
                        f"Insufficient position: have {available}, selling {quantity}"
                    )
                proceeds = quantity * price - commission
                account.cash += proceeds
                quantity_delta = -quantity
                cost_basis = quantity * existing.avg_cost
                realized_pnl = quantity * price - cost_basis - commission
                account.record_realized_pnl(realized_pnl)
            else:
                raise ValueError(f"Invalid side: {side}. Must be BUY or SELL")

            self.update_position(account_id, symbol, quantity_delta, price)

            pos = account.positions.get(symbol)
            new_quantity = pos.quantity if pos else 0
            new_avg_cost = pos.avg_cost if pos else 0.0

            logger.info(
                "Fill applied: account=%s symbol=%s side=%s qty=%d price=%.2f "
                "commission=%.2f realized_pnl=%.2f",
                account_id,
                symbol,
                side,
                quantity,
                price,
                commission,
                realized_pnl,
            )

            return FillResult(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                commission=commission,
                realized_pnl=realized_pnl,
                new_quantity=new_quantity,
                new_avg_cost=new_avg_cost,
                cash_remaining=account.cash,
            )
