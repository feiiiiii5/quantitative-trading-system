__all__ = [
    "RealisticCostModel",
]

import logging

import numpy as np

logger = logging.getLogger(__name__)


class RealisticCostModel:
    def __init__(
        self,
        commission: float = 0.0002,
        stamp_tax: float = 0.001,
        transfer_fee_sh: float = 0.00001,
        market_impact_pct: float = 0.0005,
        financing_rate: float = 0.045,
        min_commission: float = 5.0,
    ):
        self.commission = commission
        self.stamp_tax = stamp_tax
        self.transfer_fee_sh = transfer_fee_sh
        self.market_impact_pct = market_impact_pct
        self.financing_rate = financing_rate / 365
        self.min_commission = min_commission

    def calc_buy_cost(self, price: float, shares: int, amount: float = 0,
                      daily_amount: float = 0, is_sh: bool = False) -> dict:
        if amount <= 0:
            amount = price * shares
        fee = max(amount * self.commission, self.min_commission)
        transfer = shares * self.transfer_fee_sh if is_sh else 0.0
        impact = 0.0
        if daily_amount > 0:
            participation = amount / daily_amount
            impact = amount * self.market_impact_pct * np.sqrt(participation)
        total = fee + transfer + impact
        return {"commission": round(fee, 2), "transfer_fee": round(transfer, 2),
                "market_impact": round(impact, 2), "total": round(total, 2)}

    def calc_sell_cost(self, price: float, shares: int, amount: float = 0,
                       daily_amount: float = 0, is_sh: bool = False) -> dict:
        if amount <= 0:
            amount = price * shares
        fee = max(amount * self.commission, self.min_commission)
        stamp = amount * self.stamp_tax
        transfer = shares * self.transfer_fee_sh if is_sh else 0.0
        impact = 0.0
        if daily_amount > 0:
            participation = amount / daily_amount
            impact = amount * self.market_impact_pct * np.sqrt(participation)
        total = fee + stamp + transfer + impact
        return {"commission": round(fee, 2), "stamp_tax": round(stamp, 2),
                "transfer_fee": round(transfer, 2), "market_impact": round(impact, 2),
                "total": round(total, 2)}

    def calc_financing_cost(self, borrowed: float, days: int) -> float:
        return round(borrowed * self.financing_rate * days, 2)
