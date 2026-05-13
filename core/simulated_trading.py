import json
import logging
import random
import threading
import uuid
from bisect import insort
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_AUDIT_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "audit.log"


@dataclass
class SimPosition:
    """模拟交易持仓（与core.models.Position区分以避免导入冲突）"""
    symbol: str
    name: str
    market: str
    shares: int
    available_shares: int
    avg_cost: float
    current_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    buy_date: str = ""
    buy_fees: float = 0.0
    first_buy_date: str = ""

    def __post_init__(self):
        if not self.first_buy_date and self.buy_date:
            self.first_buy_date = self.buy_date

    @property
    def market_value(self) -> float:
        return self.current_price * self.shares

    @property
    def profit(self) -> float:
        return (self.current_price - self.avg_cost) * self.shares - self.buy_fees

    @property
    def profit_pct(self) -> float:
        cost = self.avg_cost * self.shares + self.buy_fees
        return (self.profit / cost * 100) if cost > 0 else 0


@dataclass
class Order:
    id: str
    symbol: str
    name: str
    market: str
    action: str
    order_type: str
    price: float
    shares: int
    strategy: str
    status: str = "pending"
    created_at: str = ""
    filled_at: str = ""
    filled_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""


@dataclass
class TradeRecord:
    id: str
    symbol: str
    name: str
    market: str
    action: str
    price: float
    shares: int
    amount: float
    fee: float
    stamp_tax: float
    time: str
    strategy: str
    order_id: str = ""
    reason: str = ""
    entry_price: float = 0.0


class OrderBook:
    def __init__(self):
        self._bid_orders: list[dict] = []
        self._ask_orders: list[dict] = []

    def add_bid(self, price: float, shares: int):
        entry = {"price": price, "shares": shares}
        insort(self._bid_orders, entry, key=lambda x: -x["price"])

    def add_ask(self, price: float, shares: int):
        entry = {"price": price, "shares": shares}
        insort(self._ask_orders, entry, key=lambda x: x["price"])

    def get_best_bid(self) -> float | None:
        return self._bid_orders[0]["price"] if self._bid_orders else None

    def get_best_ask(self) -> float | None:
        return self._ask_orders[0]["price"] if self._ask_orders else None

    def get_spread(self) -> float:
        bid = self.get_best_bid()
        ask = self.get_best_ask()
        if bid and ask:
            return ask - bid
        return 0.0

    def simulate_market_depth(self, current_price: float, market: str = "A"):
        self._bid_orders.clear()
        self._ask_orders.clear()

        if current_price <= 0:
            return

        if market == "A":
            tick = max(0.01, current_price * 0.001)
        elif market == "HK":
            tick = max(0.01, current_price * 0.002)
        else:
            tick = max(0.01, current_price * 0.001)

        for i in range(5):
            bid_price = current_price - tick * (i + 1)
            ask_price = current_price + tick * (i + 1)
            if bid_price > 0:
                self.add_bid(round(bid_price, 3), random.randint(50, 500) * 100)
            self.add_ask(round(ask_price, 3), random.randint(50, 500) * 100)


class SimulatedTrading:
    def __init__(self, initial_capital: float = 1000000):
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._positions: dict[str, SimPosition] = {}
        self._pending_orders: list[Order] = []
        self._max_pending_orders = 1000
        self._trade_history: list[TradeRecord] = []
        self._max_trade_history = 10000
        self._commission_rate = 0.0003
        self._stamp_tax_rate = 0.001
        self._min_commission = 5.0
        self._prev_close_map: dict[str, float] = {}
        self._entry_price_map: dict[str, float] = {}
        self._order_books: dict[str, OrderBook] = {}
        self._slippage_rate = 0.001
        self._market_status_cache: dict[str, dict] = {}
        self._trade_lock = threading.RLock()
        self._order_ids: OrderedDict[str, None] = OrderedDict()
        self._max_order_ids = 10000
        self._audit_logger = self._init_audit_logger()
        from core.risk_manager import EnhancedRiskManager
        self._risk_manager = EnhancedRiskManager()
        self._daily_pnl: list[dict] = []
        self._max_daily_pnl = 365
        self._last_pnl_date = ""

    @staticmethod
    def _init_audit_logger() -> logging.Logger:
        audit_logger = logging.getLogger("quantcore.audit")
        if not audit_logger.handlers:
            try:
                _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                handler = logging.FileHandler(str(_AUDIT_LOG_PATH), encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
                audit_logger.addHandler(handler)
                audit_logger.setLevel(logging.INFO)
            except (OSError, ValueError) as e:  # pragma: no cover
                logger.warning("Audit logger init failed: %s", e)
        return audit_logger

    def _register_order_id(self, order_id: str) -> bool:
        if order_id in self._order_ids:
            return False
        self._order_ids[order_id] = None
        while len(self._order_ids) > self._max_order_ids:
            self._order_ids.popitem(last=False)
        return True

    def _write_audit(self, action: str, detail: dict) -> None:
        try:
            serialized = json.dumps(detail, ensure_ascii=False, default=str)
            self._audit_logger.info("%s | %s", action, serialized)
        except (OSError, ValueError, TypeError) as e:  # pragma: no cover
            logger.warning("Audit log write failed for %s: %s", action, e)

    def _get_order_book(self, symbol: str) -> OrderBook:
        if symbol not in self._order_books:
            self._order_books[symbol] = OrderBook()
        return self._order_books[symbol]

    def _simulate_slippage(self, price: float, action: str, market: str) -> float:
        slippage = price * self._slippage_rate
        filled_price = price + random.uniform(0, slippage) if action == "buy" else price - random.uniform(0, slippage)

        if market == "A" and price > 0:
            if price < 5 or price < 10:
                tick = 0.01
            elif price < 20:
                tick = 0.02
            elif price < 50:
                tick = 0.05
            elif price < 100:
                tick = 0.10
            elif price < 500:
                tick = 0.20
            else:
                tick = 0.50
            filled_price = round(filled_price / tick) * tick
        else:
            filled_price = round(filled_price, 3)

        return max(filled_price, 0.01)

    def _get_execution_price(self, symbol: str, action: str, order_price: float, market_price: float, market: str) -> float:
        ob = self._get_order_book(symbol)
        ob.simulate_market_depth(market_price, market)

        if action == "buy":
            best_ask = ob.get_best_ask()
            if best_ask and best_ask <= order_price:
                return self._simulate_slippage(best_ask, "buy", market)
            return self._simulate_slippage(market_price, "buy", market)
        else:
            best_bid = ob.get_best_bid()
            if best_bid and best_bid >= order_price:
                return self._simulate_slippage(best_bid, "sell", market)
            return self._simulate_slippage(market_price, "sell", market)

    def update_market_status(self, market: str, status: dict):
        self._market_status_cache[market] = status

    def is_market_open(self, market: str) -> bool:
        status = self._market_status_cache.get(market, {})
        return status.get("is_open", False)

    def get_market_session(self, market: str) -> str:
        status = self._market_status_cache.get(market, {})
        return status.get("session", "closed")

    def _calc_fee(self, amount: float, is_sell: bool = False, market: str = "A", shares: int = 0) -> tuple[float, float]:
        if market == "HK":
            commission = max(amount * 0.0005, 50.0)
            stamp_tax = amount * 0.001 if is_sell else 0
            levy = amount * 0.00002
            stamp_tax += levy
        elif market == "US":
            per_share = 0.005
            commission = max(per_share * max(shares, 1), 1.0)
            stamp_tax = 0
        else:
            commission = max(amount * self._commission_rate, self._min_commission)
            stamp_tax = amount * self._stamp_tax_rate if is_sell else 0
        return commission, stamp_tax

    @staticmethod
    def _get_board_limit(symbol: str) -> float:
        if symbol.startswith("8"):
            return 0.30
        if symbol.startswith(("3", "68")):
            return 0.20
        return 0.10

    @staticmethod
    def _is_st(name: str) -> bool:
        return name.startswith("ST") or name.startswith("*ST") or name.startswith("st")

    def _check_limit_up(self, symbol: str, name: str, price: float) -> bool:
        prev = self._prev_close_map.get(symbol)
        if not prev or prev <= 0:
            return False
        pct = 0.05 if self._is_st(name) else self._get_board_limit(symbol)
        limit_price = prev * (1 + pct)
        return price >= limit_price * 0.995

    def _check_limit_down(self, symbol: str, name: str, price: float) -> bool:
        prev = self._prev_close_map.get(symbol)
        if not prev or prev <= 0:
            return False
        pct = 0.05 if self._is_st(name) else self._get_board_limit(symbol)
        limit_price = prev * (1 - pct)
        return price <= limit_price * 1.005

    def _today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def daily_settlement(self) -> None:
        with self._trade_lock:
            for pos in self._positions.values():
                pos.available_shares = pos.shares

    def execute_buy(
        self,
        symbol: str,
        name: str,
        market: str,
        price: float,
        shares: int,
        stop_loss: float = 0,
        take_profit: float = 0,
        strategy: str = "manual",
        market_price: float = 0,
        order_id: str = "",
    ) -> dict:
        with self._trade_lock:
            if order_id and not self._register_order_id(order_id):
                return {"success": False, "error": "重复订单"}

            if not isinstance(price, (int, float)) or not isinstance(shares, (int, float)):
                return {"success": False, "error": "价格和数量必须为数字"}
            if not (np.isfinite(price) and np.isfinite(shares)):
                return {"success": False, "error": "价格和数量不能为NaN或无穷"}
            if price <= 0 or shares <= 0:
                return {"success": False, "error": "无效的价格或数量"}

            if market == "A":
                lot = 100
                if shares < lot:
                    return {"success": False, "error": f"A股最小买入1手({lot}股)"}
                if shares % lot != 0:
                    shares = (shares // lot) * lot
                if shares <= 0:
                    return {"success": False, "error": "买入数量必须为100的整数倍"}
            elif market == "HK":
                lot = 500
                if shares < lot:
                    return {"success": False, "error": f"港股最小买入单位为{lot}股"}

            effective_price = market_price if market_price > 0 else price
            filled_price = self._get_execution_price(symbol, "buy", price, effective_price, market)

            amount = filled_price * shares
            commission, stamp_tax = self._calc_fee(amount, is_sell=False, market=market, shares=shares)
            total_cost = amount + commission + stamp_tax

            if total_cost > self._cash:
                fee_rate = self._commission_rate + (self._stamp_tax_rate if market == "A" else 0.001 if market == "HK" else 0)
                denom = filled_price * (1 + fee_rate)
                max_shares = int(self._cash / denom) if denom > 0 else 0
                if market == "A":
                    max_shares = (max_shares // 100) * 100
                return {
                    "success": False,
                    "error": f"资金不足：需要{total_cost:.2f}，可用{self._cash:.2f}",
                    "max_affordable_shares": max_shares,
                }

            if market == "A" and self._check_limit_up(symbol, name, filled_price):
                return {"success": False, "error": "接近涨停价，买入可能无法成交", "warning": True}

            total_assets = self._cash + sum(p.market_value for p in self._positions.values())
            current_positions = {}
            for sym, pos in self._positions.items():
                current_positions[sym] = {"market_value": pos.market_value}
            risk_check = self._risk_manager.check_order_legacy(
                symbol=symbol, action="buy", shares=shares, price=filled_price,
                current_positions=current_positions, total_assets=total_assets,
            )
            if not risk_check["approved"]:
                return {"success": False, "error": risk_check["reason"]}

            cash_before = self._cash
            self._cash -= total_cost

            if self._cash < 0:
                self._cash = cash_before
                return {"success": False, "error": "余额一致性检查失败，交易已回滚"}

            today = self._today_str()

            if symbol in self._positions:
                pos = self._positions[symbol]
                prev_available = pos.available_shares
                total_shares = pos.shares + shares
                total_cost_basis = pos.avg_cost * pos.shares + amount
                pos.avg_cost = total_cost_basis / total_shares
                pos.shares = total_shares
                pos.buy_fees += commission
                pos.stop_loss = stop_loss if stop_loss > 0 else pos.stop_loss
                pos.take_profit = take_profit if take_profit > 0 else pos.take_profit
                pos.current_price = filled_price
                pos.buy_date = today
                pos.available_shares = prev_available
                self._entry_price_map[symbol] = pos.avg_cost
            else:
                self._positions[symbol] = SimPosition(
                    symbol=symbol,
                    name=name,
                    market=market,
                    shares=shares,
                    available_shares=0,
                    avg_cost=filled_price,
                    current_price=filled_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    buy_date=today,
                    buy_fees=commission,
                )
                self._entry_price_map[symbol] = filled_price

            trade = TradeRecord(
                id=str(uuid.uuid4())[:8],
                symbol=symbol,
                name=name,
                market=market,
                action="buy",
                price=round(filled_price, 3),
                shares=shares,
                amount=round(amount, 2),
                fee=round(commission, 2),
                stamp_tax=round(stamp_tax, 2),
                time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                strategy=strategy,
                reason="市价买入",
                entry_price=filled_price,
            )
            self._trade_history.append(trade)
            if len(self._trade_history) > self._max_trade_history:
                self._trade_history = self._trade_history[-self._max_trade_history:]

            self._write_audit("BUY", {
                "symbol": symbol, "name": name, "price": filled_price,
                "shares": shares, "amount": amount, "fee": commission,
                "strategy": strategy, "cash_after": self._cash,
            })

            return {
                "success": True, "trade": {
                    "id": trade.id, "action": "buy",
                    "symbol": symbol, "name": name, "order_price": price,
                    "filled_price": round(filled_price, 3), "shares": shares,
                    "amount": round(amount, 2), "fee": round(commission, 2),
                    "time": trade.time, "slippage": round(filled_price - price, 3),
                },
            }

    def execute_sell(
        self,
        symbol: str,
        price: float,
        reason: str = "manual",
        shares: int | None = None,
        market_price: float = 0,
        order_id: str = "",
    ) -> dict:
        with self._trade_lock:
            if order_id and not self._register_order_id(order_id):
                return {"success": False, "error": "重复订单"}

            if not isinstance(price, (int, float)) or not np.isfinite(price):
                return {"success": False, "error": "无效的卖出价格"}
            if price <= 0:
                return {"success": False, "error": "无效的卖出价格"}

            if symbol not in self._positions:
                return {"success": False, "error": f"未持有 {symbol}"}

            pos = self._positions[symbol]

            if pos.market == "A":
                today = self._today_str()
                if pos.buy_date == today and pos.available_shares == 0:
                    return {"success": False, "error": "T+1限制：当日买入的股票当日不可卖出", "t1_restricted": True}

            sell_shares = shares if shares and shares > 0 else pos.available_shares
            if sell_shares <= 0:
                return {"success": False, "error": f"无可卖股票（可用: {pos.available_shares}，冻结: {pos.shares - pos.available_shares})"}

            if sell_shares > pos.available_shares:
                return {"success": False, "error": f"可卖数量不足：请求{sell_shares}，可用{pos.available_shares}"}

            effective_price = market_price if market_price > 0 else price
            filled_price = self._get_execution_price(symbol, "sell", price, effective_price, pos.market)

            if pos.market == "A" and self._check_limit_down(symbol, pos.name, filled_price):
                return {"success": False, "error": "接近跌停价，卖出可能排队等候", "warning": True}

            amount = filled_price * sell_shares
            commission, stamp_tax = self._calc_fee(amount, is_sell=True, market=pos.market, shares=sell_shares)
            total_fee = commission + stamp_tax
            net_amount = amount - total_fee

            cash_before = self._cash
            self._cash += net_amount

            if self._cash < 0:
                self._cash = cash_before
                return {"success": False, "error": "余额一致性检查失败，交易已回滚"}

            pnl = (filled_price - pos.avg_cost) * sell_shares - total_fee

            pos.shares -= sell_shares
            pos.available_shares -= sell_shares

            if pos.shares <= 0:
                del self._positions[symbol]
                self._entry_price_map.pop(symbol, None)

            trade = TradeRecord(
                id=str(uuid.uuid4())[:8],
                symbol=symbol,
                name=pos.name,
                market=pos.market,
                action="sell",
                price=round(filled_price, 3),
                shares=sell_shares,
                amount=round(amount, 2),
                fee=round(commission, 2),
                stamp_tax=round(stamp_tax, 2),
                time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                strategy=reason,
                reason=reason,
                entry_price=pos.avg_cost,
            )
            self._trade_history.append(trade)
            if len(self._trade_history) > self._max_trade_history:
                self._trade_history = self._trade_history[-self._max_trade_history:]

            self._write_audit("SELL", {
                "symbol": symbol, "name": pos.name, "price": filled_price,
                "shares": sell_shares, "amount": amount, "fee": total_fee,
                "pnl": pnl, "reason": reason, "cash_after": self._cash,
            })

            return {
                "success": True, "trade": {
                    "id": trade.id, "action": "sell",
                    "symbol": symbol, "name": pos.name, "order_price": price,
                    "filled_price": round(filled_price, 3), "shares": sell_shares,
                    "amount": round(amount, 2), "fee": round(total_fee, 2),
                    "pnl": round(pnl, 2), "time": trade.time, "reason": reason,
                    "slippage": round(price - filled_price, 3),
                },
            }

    def place_order(
        self,
        symbol: str,
        name: str,
        market: str,
        action: str,
        order_type: str,
        price: float,
        shares: int,
        strategy: str = "manual",
        stop_loss: float = 0,
        take_profit: float = 0,
    ) -> dict:
        with self._trade_lock:
            if action == "sell" and symbol in self._positions:
                pos = self._positions[symbol]
                if pos.market == "A":
                    today = self._today_str()
                    if pos.buy_date == today and pos.available_shares == 0:
                        return {"success": False, "error": "T+1限制：当日买入的股票当日不可挂卖单", "t1_restricted": True}
                if shares > pos.available_shares:
                    return {"success": False, "error": f"可卖数量不足：可用{pos.available_shares}股"}

            if action == "buy":
                amount = price * shares
                commission, stamp_tax = self._calc_fee(amount, is_sell=False, market=market, shares=shares)
                total_cost = amount + commission + stamp_tax
                if total_cost > self._cash:
                    return {"success": False, "error": f"资金不足：需要{total_cost:.2f}，可用{self._cash:.2f}"}

            if len(self._pending_orders) >= self._max_pending_orders:
                return {"success": False, "error": f"挂单队列已满（上限{self._max_pending_orders}）"}

            order = Order(
                id=str(uuid.uuid4())[:8],
                symbol=symbol,
                name=name,
                market=market,
                action=action,
                order_type=order_type,
                price=price,
                shares=shares,
                strategy=strategy,
                status="pending",
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
            self._pending_orders.append(order)

            return {
                "success": True, "order": {
                    "id": order.id, "symbol": symbol,
                    "name": name, "action": action,
                    "order_type": order_type, "price": price,
                    "shares": shares, "status": "pending",
                    "created_at": order.created_at,
                },
            }

    def cancel_order(self, order_id: str) -> dict:
        with self._trade_lock:
            for i, order in enumerate(self._pending_orders):
                if order.id == order_id:
                    if order.status != "pending":
                        return {"success": False, "error": f"订单{order_id}状态为{order.status}，无法取消"}
                    self._pending_orders.pop(i)
                    return {"success": True, "order_id": order_id}
            return {"success": False, "error": f"未找到订单{order_id}"}

    def get_pending_orders(self) -> list[dict]:
        with self._trade_lock:
            return [
                {
                    "id": o.id,
                    "symbol": o.symbol,
                    "name": o.name,
                    "market": o.market,
                    "action": o.action,
                    "order_type": o.order_type,
                    "price": o.price,
                    "shares": o.shares,
                    "status": o.status,
                    "created_at": o.created_at,
                    "stop_loss": o.stop_loss,
                    "take_profit": o.take_profit,
                    "strategy": o.strategy,
                }
                for o in self._pending_orders if o.status == "pending"
            ]

    def check_pending_orders(self, price_map: dict[str, float]) -> list[dict]:
        with self._trade_lock:
            executed = []
            remaining = []

            for order in self._pending_orders:
                if order.status != "pending":
                    continue

                current_price = price_map.get(order.symbol, 0)
                if current_price <= 0:
                    remaining.append(order)
                    continue

                filled = False

                if order.action == "buy":
                    if (order.order_type == "limit" and current_price <= order.price) or order.order_type == "market":
                        result = self.execute_buy(
                            symbol=order.symbol,
                            name=order.name,
                            market=order.market,
                            price=order.price,
                            shares=order.shares,
                            stop_loss=order.stop_loss,
                            take_profit=order.take_profit,
                            strategy=order.strategy,
                            market_price=current_price,
                        )
                        if result.get("success"):
                            filled = True
                            order.status = "filled"
                            order.filled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            order.filled_price = current_price
                            executed.append({"order": self._order_to_dict(order), "result": result})

                elif order.action == "sell":
                    if (order.order_type == "limit" and current_price >= order.price) or order.order_type == "market":
                        result = self.execute_sell(
                            symbol=order.symbol,
                            price=order.price,
                            reason=order.strategy,
                            shares=order.shares,
                            market_price=current_price,
                        )
                        if result.get("success"):
                            filled = True
                            order.status = "filled"
                            order.filled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            order.filled_price = current_price
                            executed.append({"order": self._order_to_dict(order), "result": result})

                if not filled:
                    remaining.append(order)

            self._pending_orders = remaining
            return executed

    def _order_to_dict(self, order: Order) -> dict:
        return {
            "id": order.id, "symbol": order.symbol, "name": order.name,
            "action": order.action, "order_type": order.order_type,
            "price": order.price, "shares": order.shares,
            "status": order.status, "created_at": order.created_at,
            "filled_at": order.filled_at, "filled_price": order.filled_price,
        }

    def update_position_prices(self, price_map: dict[str, float]):
        with self._trade_lock:
            for symbol, price in price_map.items():
                if symbol in self._positions and price > 0:
                    self._positions[symbol].current_price = price
                    self._prev_close_map[symbol] = price

            today = self._today_str()
            for _symbol, pos in self._positions.items():
                if pos.buy_date != today:
                    pos.available_shares = pos.shares

            auto_sells = []
            for symbol, pos in list(self._positions.items()):
                if pos.market != "A":
                    continue
                if pos.stop_loss > 0 and pos.current_price <= pos.stop_loss:
                    auto_sells.append((symbol, pos.current_price, "止损"))
                elif pos.take_profit > 0 and pos.current_price >= pos.take_profit:
                    auto_sells.append((symbol, pos.current_price, "止盈"))

            for symbol, price, reason in auto_sells:
                result = self.execute_sell(symbol, price, reason=reason, market_price=price)
                if result.get("success"):
                    logger.info("Auto %s executed for %s at %s", reason, symbol, price)

    def get_account_info(self) -> dict:
        with self._trade_lock:
            total_market_value = sum(p.market_value for p in self._positions.values())
            total_profit = sum(p.profit for p in self._positions.values())
            total_assets = self._cash + total_market_value

            positions = []
            for _symbol, pos in self._positions.items():
                positions.append({
                    "symbol": pos.symbol, "name": pos.name, "market": pos.market,
                    "shares": pos.shares, "available_shares": pos.available_shares,
                    "frozen_shares": pos.shares - pos.available_shares,
                    "avg_cost": round(pos.avg_cost, 3),
                    "current_price": round(pos.current_price, 3),
                    "market_value": round(pos.market_value, 2),
                    "profit": round(pos.profit, 2),
                    "profit_pct": round(pos.profit_pct, 2),
                    "stop_loss": pos.stop_loss, "take_profit": pos.take_profit,
                    "buy_date": pos.buy_date,
                })

            return {
                "total_assets": round(total_assets, 2),
                "cash": round(self._cash, 2),
                "market_value": round(total_market_value, 2),
                "total_profit": round(total_profit, 2),
                "initial_capital": self._initial_capital,
                "return_pct": round((total_assets - self._initial_capital) / self._initial_capital * 100, 2) if self._initial_capital > 0 else 0,
                "positions": positions, "position_count": len(positions),
                "risk_report": self._risk_manager.get_risk_report(),
            }

    def get_trade_history(self, limit: int = 100) -> dict:
        with self._trade_lock:
            trades = sorted(self._trade_history, key=lambda t: t.time, reverse=True)[:limit]
        return {
            "trades": [
                {
                    "id": t.id, "symbol": t.symbol, "name": t.name,
                    "market": t.market, "action": t.action,
                    "price": t.price, "shares": t.shares,
                    "amount": t.amount, "fee": t.fee, "stamp_tax": t.stamp_tax,
                    "total_fee": round(t.fee + t.stamp_tax, 2),
                    "pnl": round((t.price - t.entry_price) * t.shares - (t.fee + t.stamp_tax), 2) if t.action == "sell" else None,
                    "time": t.time, "strategy": t.strategy, "reason": t.reason,
                }
                for t in trades
            ],
            "total": len(self._trade_history),
        }

    def get_positions(self) -> dict[str, SimPosition]:
        with self._trade_lock:
            return dict(self._positions)

    def record_daily_pnl(self) -> dict:
        with self._trade_lock:
            today = self._today_str()
            total_assets = self._cash + sum(p.market_value for p in self._positions.values())
            total_profit = total_assets - self._initial_capital
            daily = {
                "date": today,
                "total_assets": round(total_assets, 2),
                "cash": round(self._cash, 2),
                "market_value": round(total_assets - self._cash, 2),
                "total_profit": round(total_profit, 2),
                "return_pct": round(total_profit / self._initial_capital * 100, 4) if self._initial_capital > 0 else 0,
                "position_count": len(self._positions),
            }
            if self._last_pnl_date == today and self._daily_pnl:
                self._daily_pnl[-1] = daily
            else:
                self._daily_pnl.append(daily)
                self._last_pnl_date = today
            if len(self._daily_pnl) > self._max_daily_pnl:
                self._daily_pnl = self._daily_pnl[-self._max_daily_pnl:]
            return daily

    def get_daily_pnl(self, limit: int = 30) -> list[dict]:
        with self._trade_lock:
            return list(self._daily_pnl[-limit:])

    def _get_entry_price(self, symbol: str, action: str) -> float:
        if action == "sell":
            return self._entry_price_map.get(symbol, 0)
        return 0

    def reset_account(self) -> dict:
        with self._trade_lock:
            self._cash = self._initial_capital
            self._positions.clear()
            self._pending_orders.clear()
            self._trade_history.clear()
            self._prev_close_map.clear()
            self._entry_price_map.clear()
            self._order_books.clear()
            self._order_ids.clear()
            return {"success": True, "message": "Account reset"}

    def export_portfolio(self) -> dict:
        with self._trade_lock:
            positions = []
            for _symbol, pos in self._positions.items():
                positions.append({
                    "symbol": pos.symbol,
                    "name": pos.name,
                    "market": pos.market,
                    "shares": pos.shares,
                    "available_shares": pos.available_shares,
                    "avg_cost": pos.avg_cost,
                    "current_price": pos.current_price,
                    "stop_loss": pos.stop_loss,
                    "take_profit": pos.take_profit,
                    "buy_date": pos.buy_date,
                    "buy_fees": pos.buy_fees,
                    "first_buy_date": pos.first_buy_date,
                })

            pending_orders = []
            for order in self._pending_orders:
                pending_orders.append({
                    "id": order.id,
                    "symbol": order.symbol,
                    "name": order.name,
                    "market": order.market,
                    "action": order.action,
                    "order_type": order.order_type,
                    "price": order.price,
                    "shares": order.shares,
                    "strategy": order.strategy,
                    "status": order.status,
                    "created_at": order.created_at,
                    "filled_at": order.filled_at,
                    "filled_price": order.filled_price,
                    "stop_loss": order.stop_loss,
                    "take_profit": order.take_profit,
                })

            trade_history = []
            for t in self._trade_history:
                trade_history.append({
                    "id": t.id,
                    "symbol": t.symbol,
                    "name": t.name,
                    "market": t.market,
                    "action": t.action,
                    "price": t.price,
                    "shares": t.shares,
                    "amount": t.amount,
                    "fee": t.fee,
                    "stamp_tax": t.stamp_tax,
                    "time": t.time,
                    "strategy": t.strategy,
                    "reason": t.reason,
                    "entry_price": t.entry_price,
                })

            return {
                "version": "1.0",
                "initial_capital": self._initial_capital,
                "cash": self._cash,
                "positions": positions,
                "pending_orders": pending_orders,
                "trade_history": trade_history,
                "prev_close_map": self._prev_close_map,
                "entry_price_map": self._entry_price_map,
                "daily_pnl": self._daily_pnl,
                "export_time": datetime.now().isoformat(),
            }

    def import_portfolio(self, data: dict) -> dict:
        with self._trade_lock:
            try:
                if data.get("version") != "1.0":
                    return {"success": False, "error": "Invalid portfolio version"}

                self._initial_capital = data.get("initial_capital", 1000000)
                self._cash = data.get("cash", self._initial_capital)

                self._positions.clear()
                for pos_data in data.get("positions", []):
                    self._positions[pos_data["symbol"]] = SimPosition(
                        symbol=pos_data["symbol"],
                        name=pos_data["name"],
                        market=pos_data["market"],
                        shares=pos_data["shares"],
                        available_shares=pos_data["available_shares"],
                        avg_cost=pos_data["avg_cost"],
                        current_price=pos_data["current_price"],
                        stop_loss=pos_data["stop_loss"],
                        take_profit=pos_data["take_profit"],
                        buy_date=pos_data["buy_date"],
                        buy_fees=pos_data["buy_fees"],
                        first_buy_date=pos_data.get("first_buy_date", pos_data.get("buy_date", "")),
                    )

                self._pending_orders.clear()
                for order_data in data.get("pending_orders", []):
                    self._pending_orders.append(Order(
                        id=order_data["id"],
                        symbol=order_data["symbol"],
                        name=order_data["name"],
                        market=order_data["market"],
                        action=order_data["action"],
                        order_type=order_data["order_type"],
                        price=order_data["price"],
                        shares=order_data["shares"],
                        strategy=order_data["strategy"],
                        status=order_data.get("status", "pending"),
                        created_at=order_data.get("created_at", ""),
                        filled_at=order_data.get("filled_at", ""),
                        filled_price=order_data.get("filled_price", 0),
                        stop_loss=order_data.get("stop_loss", 0),
                        take_profit=order_data.get("take_profit", 0),
                    ))

                self._trade_history.clear()
                for t_data in data.get("trade_history", []):
                    self._trade_history.append(TradeRecord(
                        id=t_data["id"],
                        symbol=t_data["symbol"],
                        name=t_data["name"],
                        market=t_data["market"],
                        action=t_data["action"],
                        price=t_data["price"],
                        shares=t_data["shares"],
                        amount=t_data["amount"],
                        fee=t_data["fee"],
                        stamp_tax=t_data["stamp_tax"],
                        time=t_data["time"],
                        strategy=t_data["strategy"],
                        reason=t_data["reason"],
                        entry_price=t_data["entry_price"],
                    ))

                self._prev_close_map = data.get("prev_close_map", {})
                self._entry_price_map = data.get("entry_price_map", {})

                return {"success": True, "message": "Portfolio imported successfully"}

            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                logger.error("Portfolio import failed: %s", e)
                return {"success": False, "error": str(e)}
