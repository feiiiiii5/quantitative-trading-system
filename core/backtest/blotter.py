__all__ = [
    "SlippageModel",
    "FixedSlippage",
    "PercentageSlippage",
    "VolumeShareSlippage",
    "CommissionModel",
    "FixedCommission",
    "PerShareCommission",
    "PerTradeCommission",
    "TieredCommission",
    "Blotter",
]

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


class SlippageModel(ABC):
    @abstractmethod
    def simulate_fill(
        self,
        price: float,
        shares: int,
        volume: float = 0.0,
        is_buy: bool = True,
    ) -> float:
        ...


class FixedSlippage(SlippageModel):
    def __init__(self, slippage_amount: float = 0.01):
        self._amount = slippage_amount

    def simulate_fill(
        self,
        price: float,
        shares: int,
        volume: float = 0.0,
        is_buy: bool = True,
    ) -> float:
        if is_buy:
            return price + self._amount
        return price - self._amount


class PercentageSlippage(SlippageModel):
    def __init__(self, slippage_pct: float = 0.001):
        self._pct = slippage_pct

    def simulate_fill(
        self,
        price: float,
        shares: int,
        volume: float = 0.0,
        is_buy: bool = True,
    ) -> float:
        if is_buy:
            return price * (1 + self._pct)
        return price * (1 - self._pct)


class VolumeShareSlippage(SlippageModel):
    def __init__(self, volume_limit: float = 0.25, price_impact: float = 0.1):
        self._volume_limit = volume_limit
        self._price_impact = price_impact

    def simulate_fill(
        self,
        price: float,
        shares: int,
        volume: float = 0.0,
        is_buy: bool = True,
    ) -> float:
        if volume <= 0:
            return price
        volume_share = min(shares / volume, self._volume_limit)
        impact = volume_share ** 2 * self._price_impact
        if is_buy:
            return price * (1 + impact)
        return price * (1 - impact)


class CommissionModel(ABC):
    @abstractmethod
    def calculate(
        self,
        shares: int,
        price: float,
        is_buy: bool = True,
    ) -> float:
        ...


class FixedCommission(CommissionModel):
    def __init__(self, cost: float = 5.0):
        self._cost = cost

    def calculate(
        self,
        shares: int,
        price: float,
        is_buy: bool = True,
    ) -> float:
        return self._cost


class PerShareCommission(CommissionModel):
    def __init__(self, cost_per_share: float = 0.0003, min_commission: float = 5.0):
        self._cost_per_share = cost_per_share
        self._min = min_commission

    def calculate(
        self,
        shares: int,
        price: float,
        is_buy: bool = True,
    ) -> float:
        commission = shares * price * self._cost_per_share
        return max(commission, self._min)


class PerTradeCommission(CommissionModel):
    def __init__(self, cost_per_trade: float = 5.0):
        self._cost_per_trade = cost_per_trade

    def calculate(
        self,
        shares: int,
        price: float,
        is_buy: bool = True,
    ) -> float:
        return self._cost_per_trade


class TieredCommission(CommissionModel):
    def __init__(
        self,
        commission_rate: float = 0.0003,
        stamp_tax_rate: float = 0.001,
        min_commission: float = 5.0,
        stamp_tax_on_sell_only: bool = True,
    ):
        self._commission_rate = commission_rate
        self._stamp_tax_rate = stamp_tax_rate
        self._min = min_commission
        self._stamp_tax_on_sell_only = stamp_tax_on_sell_only

    def calculate(
        self,
        shares: int,
        price: float,
        is_buy: bool = True,
    ) -> float:
        trade_value = shares * price
        commission = max(trade_value * self._commission_rate, self._min)
        stamp_tax = 0.0
        if not is_buy and self._stamp_tax_on_sell_only:
            stamp_tax = trade_value * self._stamp_tax_rate
        elif not self._stamp_tax_on_sell_only:
            stamp_tax = trade_value * self._stamp_tax_rate
        return commission + stamp_tax


@dataclass
class FillResult:
    fill_price: float
    shares: int
    commission: float
    slippage_cost: float
    total_cost: float
    is_buy: bool


class Blotter:
    def __init__(
        self,
        slippage_model: SlippageModel | None = None,
        commission_model: CommissionModel | None = None,
    ):
        self._slippage = slippage_model or PercentageSlippage(0.001)
        self._commission = commission_model or TieredCommission()
        self._fills: list[FillResult] = []

    def execute_order(
        self,
        price: float,
        shares: int,
        is_buy: bool = True,
        volume: float = 0.0,
    ) -> FillResult:
        fill_price = self._slippage.simulate_fill(price, shares, volume, is_buy)
        commission = self._commission.calculate(shares, fill_price, is_buy)
        slippage_cost = abs(fill_price - price) * shares
        trade_value = shares * fill_price
        total_cost = trade_value + commission if is_buy else trade_value - commission

        fill = FillResult(
            fill_price=round(fill_price, 4),
            shares=shares,
            commission=round(commission, 2),
            slippage_cost=round(slippage_cost, 2),
            total_cost=round(total_cost, 2),
            is_buy=is_buy,
        )
        self._fills.append(fill)
        return fill

    def total_commission(self) -> float:
        return sum(f.commission for f in self._fills)

    def total_slippage(self) -> float:
        return sum(f.slippage_cost for f in self._fills)

    def total_trades(self) -> int:
        return len(self._fills)

    def clear(self) -> None:
        self._fills.clear()

    @property
    def fills(self) -> list[FillResult]:
        return list(self._fills)

    @classmethod
    def create_a_share_blotter(cls) -> "Blotter":
        return cls(
            slippage_model=PercentageSlippage(0.001),
            commission_model=TieredCommission(
                commission_rate=0.0003,
                stamp_tax_rate=0.001,
                min_commission=5.0,
                stamp_tax_on_sell_only=True,
            ),
        )
