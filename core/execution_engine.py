import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class CostModel:
    commission_rate: float = 0.0003
    slippage_rate: float = 0.0001
    stamp_tax_rate: float = 0.001
    min_commission: float = 5.0

    def calc_buy_cost(self, price: float, quantity: int) -> float:
        value = price * quantity
        commission = max(value * self.commission_rate, self.min_commission)
        slippage = value * self.slippage_rate
        return commission + slippage

    def calc_sell_cost(self, price: float, quantity: int) -> float:
        value = price * quantity
        commission = max(value * self.commission_rate, self.min_commission)
        slippage = value * self.slippage_rate
        stamp_tax = value * self.stamp_tax_rate
        return commission + slippage + stamp_tax

    def calc_total_cost(self, buy_price: float, sell_price: float, quantity: int) -> float:
        return self.calc_buy_cost(buy_price, quantity) + self.calc_sell_cost(sell_price, quantity)

    def calc_cost_pct(self, buy_price: float, sell_price: float, quantity: int) -> float:
        total_value = buy_price * quantity + sell_price * quantity
        if total_value < 1e-10:
            return 0.0
        return self.calc_total_cost(buy_price, sell_price, quantity) / total_value


def execute_twap(
    total_quantity: int,
    bar_count: int = 6,
    current_bar: int = 0,
) -> int:
    if total_quantity <= 0 or bar_count <= 0:
        return 0
    base = total_quantity // bar_count
    remainder = total_quantity % bar_count
    if current_bar < remainder:
        return base + 1
    return base


def execute_vwap(
    total_quantity: int,
    volume_profile: list[float],
    current_bar: int = 0,
) -> int:
    if total_quantity <= 0 or not volume_profile:
        return 0
    total_vol = sum(volume_profile)
    if total_vol < 1e-10:
        return total_quantity // len(volume_profile)
    cumulative = sum(volume_profile[:current_bar + 1])
    target_shares = int(total_quantity * cumulative / total_vol)
    prev_target = int(total_quantity * sum(volume_profile[:current_bar]) / total_vol) if current_bar > 0 else 0
    return target_shares - prev_target


def generate_volume_profile(
    df: pd.DataFrame,
    n_bars: int = 6,
) -> list[float]:
    if "volume" not in df.columns or len(df) < n_bars:
        return [1.0 / n_bars] * n_bars
    recent_vol = df["volume"].iloc[-n_bars:].values
    total = np.sum(recent_vol)
    if total < 1e-10:
        return [1.0 / n_bars] * n_bars
    profile: np.ndarray = recent_vol / total
    while len(profile) < n_bars:
        profile = np.append(profile, profile[-1])
    return [float(x) for x in profile]


@dataclass
class ExecutionResult:
    filled_quantity: int
    avg_fill_price: float
    total_cost: float
    slippage: float
    commission: float
    execution_method: str
    bar_details: list[dict] = field(default_factory=list)


class ExecutionEngine:
    def __init__(self, cost_model: CostModel | None = None):
        self._cost_model = cost_model or CostModel()

    def execute_market_order(
        self,
        side: str,
        quantity: int,
        current_price: float,
    ) -> ExecutionResult:
        if side == "buy":
            cost = self._cost_model.calc_buy_cost(current_price, quantity)
            slippage = current_price * quantity * self._cost_model.slippage_rate
            commission = max(current_price * quantity * self._cost_model.commission_rate, self._cost_model.min_commission)
            fill_price = current_price * (1 + self._cost_model.slippage_rate)
        else:
            cost = self._cost_model.calc_sell_cost(current_price, quantity)
            slippage = current_price * quantity * self._cost_model.slippage_rate
            commission = max(current_price * quantity * self._cost_model.commission_rate, self._cost_model.min_commission)
            fill_price = current_price * (1 - self._cost_model.slippage_rate)

        return ExecutionResult(
            filled_quantity=quantity,
            avg_fill_price=round(fill_price, 4),
            total_cost=round(cost, 2),
            slippage=round(slippage, 2),
            commission=round(commission, 2),
            execution_method="market",
        )

    def execute_twap_order(
        self,
        side: str,
        total_quantity: int,
        price_data: pd.DataFrame,
        n_bars: int = 6,
    ) -> ExecutionResult:
        if total_quantity <= 0 or price_data.empty:
            return ExecutionResult(
                filled_quantity=0, avg_fill_price=0, total_cost=0,
                slippage=0, commission=0, execution_method="twap",
            )

        total_filled = 0
        total_value = 0.0
        total_cost = 0.0
        total_slippage = 0.0
        total_commission = 0.0
        bar_details = []

        available_bars = min(n_bars, len(price_data))
        for bar_idx in range(available_bars):
            bar_qty = execute_twap(total_quantity, available_bars, bar_idx)
            if bar_qty <= 0:
                continue
            price = float(price_data["close"].iloc[bar_idx])
            result = self.execute_market_order(side, bar_qty, price)
            total_filled += result.filled_quantity
            total_value += result.avg_fill_price * result.filled_quantity
            total_cost += result.total_cost
            total_slippage += result.slippage
            total_commission += result.commission
            bar_details.append({
                "bar": bar_idx,
                "quantity": bar_qty,
                "price": price,
                "fill_price": result.avg_fill_price,
            })

        avg_price = total_value / total_filled if total_filled > 0 else 0.0
        return ExecutionResult(
            filled_quantity=total_filled,
            avg_fill_price=round(avg_price, 4),
            total_cost=round(total_cost, 2),
            slippage=round(total_slippage, 2),
            commission=round(total_commission, 2),
            execution_method="twap",
            bar_details=bar_details,
        )

    def execute_vwap_order(
        self,
        side: str,
        total_quantity: int,
        price_data: pd.DataFrame,
        n_bars: int = 6,
    ) -> ExecutionResult:
        if total_quantity <= 0 or price_data.empty:
            return ExecutionResult(
                filled_quantity=0, avg_fill_price=0, total_cost=0,
                slippage=0, commission=0, execution_method="vwap",
            )

        vol_profile = generate_volume_profile(price_data, n_bars)
        total_filled = 0
        total_value = 0.0
        total_cost = 0.0
        total_slippage = 0.0
        total_commission = 0.0
        bar_details = []

        available_bars = min(n_bars, len(price_data))
        for bar_idx in range(available_bars):
            bar_qty = execute_vwap(total_quantity, vol_profile, bar_idx)
            if bar_qty <= 0:
                continue
            price = float(price_data["close"].iloc[bar_idx])
            result = self.execute_market_order(side, bar_qty, price)
            total_filled += result.filled_quantity
            total_value += result.avg_fill_price * result.filled_quantity
            total_cost += result.total_cost
            total_slippage += result.slippage
            total_commission += result.commission
            bar_details.append({
                "bar": bar_idx,
                "quantity": bar_qty,
                "price": price,
                "fill_price": result.avg_fill_price,
                "volume_weight": vol_profile[bar_idx] if bar_idx < len(vol_profile) else 0,
            })

        avg_price = total_value / total_filled if total_filled > 0 else 0.0
        return ExecutionResult(
            filled_quantity=total_filled,
            avg_fill_price=round(avg_price, 4),
            total_cost=round(total_cost, 2),
            slippage=round(total_slippage, 2),
            commission=round(total_commission, 2),
            execution_method="vwap",
            bar_details=bar_details,
        )
