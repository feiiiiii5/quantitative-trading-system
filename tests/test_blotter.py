import pytest
import numpy as np
import pandas as pd

from core.backtest.blotter import (
    Blotter,
    PercentageSlippage,
    TieredCommission,
    PerShareCommission,
    FixedSlippage,
    VolumeShareSlippage,
    FillResult,
)


class TestBlotter:

    def test_a_share_blotter_buy(self):
        blotter = Blotter.create_a_share_blotter()
        fill = blotter.execute_order(price=10.0, shares=1000, is_buy=True)
        assert fill.fill_price > 10.0
        assert fill.commission >= 5.0
        assert fill.is_buy

    def test_a_share_blotter_sell(self):
        blotter = Blotter.create_a_share_blotter()
        fill = blotter.execute_order(price=10.0, shares=1000, is_buy=False)
        assert fill.fill_price < 10.0
        assert fill.commission >= 5.0
        assert not fill.is_buy

    def test_total_commission(self):
        blotter = Blotter.create_a_share_blotter()
        blotter.execute_order(price=10.0, shares=1000, is_buy=True)
        blotter.execute_order(price=11.0, shares=1000, is_buy=False)
        assert blotter.total_commission() > 0

    def test_total_slippage(self):
        blotter = Blotter.create_a_share_blotter()
        blotter.execute_order(price=10.0, shares=1000, is_buy=True)
        assert blotter.total_slippage() > 0

    def test_clear(self):
        blotter = Blotter.create_a_share_blotter()
        blotter.execute_order(price=10.0, shares=1000, is_buy=True)
        blotter.clear()
        assert blotter.total_trades() == 0

    def test_volume_share_slippage(self):
        blotter = Blotter(
            slippage_model=VolumeShareSlippage(volume_limit=0.25, price_impact=0.1),
            commission_model=PerShareCommission(cost_per_share=0.0003),
        )
        fill = blotter.execute_order(price=10.0, shares=1000, volume=10000, is_buy=True)
        assert fill.fill_price > 10.0

    def test_fixed_slippage(self):
        model = FixedSlippage(slippage_amount=0.05)
        buy_price = model.simulate_fill(10.0, 100, is_buy=True)
        sell_price = model.simulate_fill(10.0, 100, is_buy=False)
        assert buy_price == 10.05
        assert sell_price == 9.95
