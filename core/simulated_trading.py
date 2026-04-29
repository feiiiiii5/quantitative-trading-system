import json
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Position:
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
        self._bid_orders.append({"price": price, "shares": shares})
        self._bid_orders.sort(key=lambda x: -x["price"])

    def add_ask(self, price: float, shares: int):
        self._ask_orders.append({"price": price, "shares": shares})
        self._ask_orders.sort(key=lambda x: x["price"])

    def get_best_bid(self) -> Optional[float]:
        return self._bid_orders[0]["price"] if self._bid_orders else None

    def get_best_ask(self) -> Optional[float]:
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
        self._positions: dict[str, Position] = {}
        self._pending_orders: list[Order] = []
        self._trade_history: list[TradeRecord] = []
        self._commission_rate = 0.0003
        self._stamp_tax_rate = 0.001
        self._min_commission = 5.0
        self._limit_up_pct = 0.10
        self._limit_down_pct = 0.10
        self._st_limit_up_pct = 0.05
        self._st_limit_down_pct = 0.05
        self._prev_close_map: dict[str, float] = {}
        self._entry_price_map: dict[str, float] = {}
        self._order_books: dict[str, OrderBook] = {}
        self._slippage_rate = 0.001
        self._market_status_cache: dict[str, dict] = {}
        from core.risk_manager import RiskManager
        self._risk_manager = RiskManager()

    def _get_order_book(self, symbol: str) -> OrderBook:
        if symbol not in self._order_books:
            self._order_books[symbol] = OrderBook()
        return self._order_books[symbol]

    def _simulate_slippage(self, price: float, action: str, market: str) -> float:
        slippage = price * self._slippage_rate
        if action == "buy":
            filled_price = price + random.uniform(0, slippage)
        else:
            filled_price = price - random.uniform(0, slippage)

        if market == "A" and price > 0:
            if price < 5:
                tick = 0.01
            elif price < 10:
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

    def _calc_fee(self, amount: float, is_sell: bool = False, market: str = "A") -> tuple[float, float]:
        if market == "HK":
            commission = max(amount * 0.0005, 50.0)
            stamp_tax = amount * 0.001 if is_sell else 0
            levy = amount * 0.00002 if is_sell else 0
            stamp_tax += levy
        elif market == "US":
            commission = max(0.005 * 100, 1.0)
            per_share = 0.005
            commission = max(per_share * 100, 1.0)
            stamp_tax = 0
        else:
            commission = max(amount * self._commission_rate, self._min_commission)
            stamp_tax = amount * self._stamp_tax_rate if is_sell else 0
        return commission, stamp_tax

    def _is_st(self, name: str) -> bool:
        return name.startswith("ST") or name.startswith("*ST") or name.startswith("st")

    def _check_limit_up(self, symbol: str, name: str, price: float) -> bool:
        prev = self._prev_close_map.get(symbol)
        if not prev or prev <= 0:
            return False
        pct = self._st_limit_up_pct if self._is_st(name) else self._limit_up_pct
        limit_price = prev * (1 + pct)
        return price >= limit_price * 0.995

    def _check_limit_down(self, symbol: str, name: str, price: float) -> bool:
        prev = self._prev_close_map.get(symbol)
        if not prev or prev <= 0:
            return False
        pct = self._st_limit_down_pct if self._is_st(name) else self._limit_down_pct
        limit_price = prev * (1 - pct)
        return price <= limit_price * 1.005

    def _today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

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
    ) -> dict:
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
            lot_sizes = {"1": 100, "2": 500, "3": 1000, "4": 2000, "5": 5000}
            lot = 500
            if shares < lot:
                return {"success": False, "error": f"港股最小买入单位为{lot}股"}

        effective_price = market_price if market_price > 0 else price
        filled_price = self._get_execution_price(symbol, "buy", price, effective_price, market)

        amount = filled_price * shares
        commission, stamp_tax = self._calc_fee(amount, is_sell=False, market=market)
        total_cost = amount + commission + stamp_tax

        if total_cost > self._cash:
            max_shares = int(self._cash / (filled_price * (1 + self._commission_rate + 0.001)))
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
        risk_check = self._risk_manager.check_order(
            symbol=symbol, action="buy", shares=shares, price=filled_price,
            current_positions=current_positions, total_assets=total_assets,
        )
        if not risk_check["approved"]:
            return {"success": False, "error": risk_check["reason"]}

        self._cash -= total_cost

        today = self._today_str()

        if symbol in self._positions:
            pos = self._positions[symbol]
            total_shares = pos.shares + shares
            total_cost_basis = pos.avg_cost * pos.shares + amount
            pos.avg_cost = total_cost_basis / total_shares
            pos.shares = total_shares
            pos.buy_fees += commission
            pos.stop_loss = stop_loss if stop_loss > 0 else pos.stop_loss
            pos.take_profit = take_profit if take_profit > 0 else pos.take_profit
            pos.current_price = filled_price
            self._entry_price_map[symbol] = pos.avg_cost
        else:
            self._positions[symbol] = Position(
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

        return {
            "success": True,
            "trade": {
                "id": trade.id,
                "action": "buy",
                "symbol": symbol,
                "name": name,
                "order_price": price,
                "filled_price": round(filled_price, 3),
                "shares": shares,
                "amount": round(amount, 2),
                "fee": round(commission, 2),
                "time": trade.time,
                "slippage": round(filled_price - price, 3),
            },
        }

    def execute_sell(
        self,
        symbol: str,
        price: float,
        reason: str = "manual",
        shares: Optional[int] = None,
        market_price: float = 0,
    ) -> dict:
        if symbol not in self._positions:
            return {"success": False, "error": f"未持有 {symbol}"}

        pos = self._positions[symbol]

        if pos.market == "A":
            today = self._today_str()
            if pos.buy_date == today:
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
        commission, stamp_tax = self._calc_fee(amount, is_sell=True, market=pos.market)
        total_fee = commission + stamp_tax
        net_amount = amount - total_fee

        self._cash += net_amount

        pnl = (filled_price - pos.avg_cost) * sell_shares - total_fee

        pos.shares -= sell_shares
        pos.available_shares = min(pos.available_shares, pos.shares)

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

        return {
            "success": True,
            "trade": {
                "id": trade.id,
                "action": "sell",
                "symbol": symbol,
                "name": pos.name,
                "order_price": price,
                "filled_price": round(filled_price, 3),
                "shares": sell_shares,
                "amount": round(amount, 2),
                "fee": round(total_fee, 2),
                "pnl": round(pnl, 2),
                "time": trade.time,
                "reason": reason,
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
        if action == "sell" and symbol in self._positions:
            pos = self._positions[symbol]
            if pos.market == "A":
                today = self._today_str()
                if pos.buy_date == today:
                    return {"success": False, "error": "T+1限制：当日买入的股票当日不可挂卖单", "t1_restricted": True}
            if shares > pos.available_shares:
                return {"success": False, "error": f"可卖数量不足：可用{pos.available_shares}股"}

        if action == "buy":
            amount = price * shares
            commission, stamp_tax = self._calc_fee(amount, is_sell=False, market=market)
            total_cost = amount + commission + stamp_tax
            if total_cost > self._cash:
                return {"success": False, "error": f"资金不足：需要{total_cost:.2f}，可用{self._cash:.2f}"}

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
            "success": True,
            "order": {
                "id": order.id,
                "symbol": symbol,
                "name": name,
                "action": action,
                "order_type": order_type,
                "price": price,
                "shares": shares,
                "status": "pending",
                "created_at": order.created_at,
            },
        }

    def cancel_order(self, order_id: str) -> dict:
        for i, order in enumerate(self._pending_orders):
            if order.id == order_id:
                if order.status != "pending":
                    return {"success": False, "error": f"订单{order_id}状态为{order.status}，无法取消"}
                self._pending_orders.pop(i)
                return {"success": True, "order_id": order_id}
        return {"success": False, "error": f"未找到订单{order_id}"}

    def get_pending_orders(self) -> list[dict]:
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
            for o in self._pending_orders
            if o.status == "pending"
        ]

    def check_pending_orders(self, price_map: dict[str, float]) -> list[dict]:
        executed = []
        remaining = []

        for order in self._pending_orders:
            if order.status != "pending":
                remaining.append(order)
                continue

            current_price = price_map.get(order.symbol, 0)
            if current_price <= 0:
                remaining.append(order)
                continue

            filled = False

            if order.action == "buy":
                if order.order_type == "limit" and current_price <= order.price:
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
                    filled = True
                    order.status = "filled"
                    order.filled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    order.filled_price = current_price
                    executed.append({"order": self._order_to_dict(order), "result": result})
                elif order.order_type == "market":
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
                    filled = True
                    order.status = "filled"
                    order.filled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    order.filled_price = current_price
                    executed.append({"order": self._order_to_dict(order), "result": result})

            elif order.action == "sell":
                if order.order_type == "limit" and current_price >= order.price:
                    result = self.execute_sell(
                        symbol=order.symbol,
                        price=order.price,
                        reason=order.strategy,
                        shares=order.shares,
                        market_price=current_price,
                    )
                    filled = True
                    order.status = "filled"
                    order.filled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    order.filled_price = current_price
                    executed.append({"order": self._order_to_dict(order), "result": result})
                elif order.order_type == "market":
                    result = self.execute_sell(
                        symbol=order.symbol,
                        price=order.price,
                        reason=order.strategy,
                        shares=order.shares,
                        market_price=current_price,
                    )
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
            "id": order.id,
            "symbol": order.symbol,
            "name": order.name,
            "action": order.action,
            "order_type": order.order_type,
            "price": order.price,
            "shares": order.shares,
            "status": order.status,
            "created_at": order.created_at,
            "filled_at": order.filled_at,
            "filled_price": order.filled_price,
        }

    def update_position_prices(self, price_map: dict[str, float]):
        for symbol, price in price_map.items():
            if symbol in self._positions and price > 0:
                self._positions[symbol].current_price = price
                self._prev_close_map[symbol] = price

        today = self._today_str()
        for symbol, pos in self._positions.items():
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

        for symbol, price, reason in list(auto_sells):
            result = self.execute_sell(symbol, price, reason=reason, market_price=price)
            if result.get("success"):
                logger.info(f"Auto {reason} executed for {symbol} at {price}")

    def get_account_info(self) -> dict:
        total_market_value = sum(p.market_value for p in self._positions.values())
        total_profit = sum(p.profit for p in self._positions.values())
        total_assets = self._cash + total_market_value

        positions = []
        for symbol, pos in self._positions.items():
            positions.append({
                "symbol": pos.symbol,
                "name": pos.name,
                "market": pos.market,
                "shares": pos.shares,
                "available_shares": pos.available_shares,
                "frozen_shares": pos.shares - pos.available_shares,
                "avg_cost": round(pos.avg_cost, 3),
                "current_price": round(pos.current_price, 3),
                "market_value": round(pos.market_value, 2),
                "profit": round(pos.profit, 2),
                "profit_pct": round(pos.profit_pct, 2),
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
                "buy_date": pos.buy_date,
            })

        return {
            "total_assets": round(total_assets, 2),
            "cash": round(self._cash, 2),
            "market_value": round(total_market_value, 2),
            "total_profit": round(total_profit, 2),
            "initial_capital": self._initial_capital,
            "return_pct": round((total_assets - self._initial_capital) / self._initial_capital * 100, 2) if self._initial_capital > 0 else 0,
            "positions": positions,
            "position_count": len(positions),
            "risk_report": self._risk_manager.get_risk_report(),
        }

    def get_trade_history(self, limit: int = 100) -> dict:
        trades = sorted(self._trade_history, key=lambda t: t.time, reverse=True)[:limit]
        return {
            "trades": [
                {
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
                    "total_fee": round(t.fee + t.stamp_tax, 2),
                    "pnl": round((t.price - t.entry_price) * t.shares - (t.fee + t.stamp_tax), 2) if t.action == "sell" else None,
                    "time": t.time,
                    "strategy": t.strategy,
                    "reason": t.reason,
                }
                for t in trades
            ],
            "total": len(self._trade_history),
        }

    def _get_entry_price(self, symbol: str, action: str) -> float:
        if action == "sell":
            return self._entry_price_map.get(symbol, 0)
        return 0

    def reset_account(self) -> dict:
        self._cash = self._initial_capital
        self._positions.clear()
        self._pending_orders.clear()
        self._trade_history.clear()
        self._prev_close_map.clear()
        self._entry_price_map.clear()
        self._order_books.clear()
        return {"success": True, "message": "Account reset"}
