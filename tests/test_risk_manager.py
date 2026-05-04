import pytest
import numpy as np
from core.risk_manager import (
    EnhancedRiskManager, ConcentrationFilter, DailyLossFilter,
    MaxOpenTradesFilter, CashSufficiencyFilter, TrailingStopManager, ROITable,
)
from core.orders import Order, OrderSide, OrderType


class TestConcentrationFilter:
    def test_buy_within_limit(self):
        f = ConcentrationFilter(max_concentration=0.3)
        order = Order(order_id="t", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=10.0)
        ctx = {"total_assets": 100000, "current_positions": {}}
        ok, _ = f.check(order, ctx)
        assert ok

    def test_buy_exceeds_limit(self):
        f = ConcentrationFilter(max_concentration=0.3)
        order = Order(order_id="t", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=5000, price=10.0)
        ctx = {"total_assets": 100000, "current_positions": {}}
        ok, reason = f.check(order, ctx)
        assert not ok
        assert "集中度" in reason

    def test_sell_always_passes(self):
        f = ConcentrationFilter(max_concentration=0.3)
        order = Order(order_id="t", symbol="000001", side=OrderSide.SELL, order_type=OrderType.MARKET, quantity=100, price=10.0)
        ctx = {"total_assets": 100000, "current_positions": {}}
        ok, _ = f.check(order, ctx)
        assert ok

    def test_none_price_rejected(self):
        f = ConcentrationFilter(max_concentration=0.3)
        order = Order(order_id="t", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=None)
        ctx = {"total_assets": 100000, "current_positions": {}}
        ok, reason = f.check(order, ctx)
        assert not ok
        assert "价格无效" in reason

    def test_zero_price_rejected(self):
        f = ConcentrationFilter(max_concentration=0.3)
        order = Order(order_id="t", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=0)
        ctx = {"total_assets": 100000, "current_positions": {}}
        ok, reason = f.check(order, ctx)
        assert not ok
        assert "价格无效" in reason


class TestDailyLossFilter:
    def test_normal_trading(self):
        f = DailyLossFilter(max_daily_loss=0.05, initial_capital=1000000)
        order = Order(order_id="t", symbol="s", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=10.0)
        ok, _ = f.check(order, {})
        assert ok

    def test_circuit_breaker(self):
        f = DailyLossFilter(max_daily_loss=0.05, initial_capital=1000000)
        f.update_daily_pnl(-60000)
        order = Order(order_id="t", symbol="s", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=10.0)
        ok, reason = f.check(order, {})
        assert not ok
        assert "熔断" in reason


class TestMaxOpenTradesFilter:
    def test_within_limit(self):
        f = MaxOpenTradesFilter(max_open_trades=10)
        order = Order(order_id="t", symbol="s", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=10.0)
        ok, _ = f.check(order, {"open_trades": 5})
        assert ok

    def test_at_limit(self):
        f = MaxOpenTradesFilter(max_open_trades=10)
        order = Order(order_id="t", symbol="s", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=10.0)
        ok, reason = f.check(order, {"open_trades": 10})
        assert not ok
        assert "上限" in reason


class TestCashSufficiencyFilter:
    def test_sufficient_cash(self):
        f = CashSufficiencyFilter()
        order = Order(order_id="t", symbol="s", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=10.0)
        ok, _ = f.check(order, {"cash": 100000})
        assert ok

    def test_insufficient_cash(self):
        f = CashSufficiencyFilter()
        order = Order(order_id="t", symbol="s", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10000, price=10.0)
        ok, reason = f.check(order, {"cash": 5000})
        assert not ok
        assert "资金不足" in reason

    def test_sell_always_passes(self):
        f = CashSufficiencyFilter()
        order = Order(order_id="t", symbol="s", side=OrderSide.SELL, order_type=OrderType.MARKET, quantity=100, price=10.0)
        ok, _ = f.check(order, {"cash": 0})
        assert ok


class TestTrailingStopManager:
    def test_register_and_update(self):
        mgr = TrailingStopManager(trailing_stop=-0.05, trailing_stop_positive=0.02, trailing_stop_positive_offset=0.05)
        mgr.register("000001", 10.0)
        result = mgr.update("000001", 9.0)
        assert result == "trailing_stop"

    def test_no_stop_when_profit_small(self):
        mgr = TrailingStopManager(trailing_stop=-0.05, trailing_stop_positive=0.02, trailing_stop_positive_offset=0.05)
        mgr.register("000001", 10.0)
        result = mgr.update("000001", 10.3)
        assert result is None

    def test_trailing_stop_after_profit(self):
        mgr = TrailingStopManager(trailing_stop=-0.05, trailing_stop_positive=0.02, trailing_stop_positive_offset=0.05)
        mgr.register("000001", 10.0)
        mgr.update("000001", 11.0)
        result = mgr.update("000001", 10.5)
        assert result == "trailing_stop"

    def test_unregister(self):
        mgr = TrailingStopManager()
        mgr.register("000001", 10.0)
        mgr.unregister("000001")
        result = mgr.update("000001", 9.0)
        assert result is None

    def test_stop_price_only_goes_up(self):
        mgr = TrailingStopManager(trailing_stop=-0.05, trailing_stop_positive=0.02, trailing_stop_positive_offset=0.05)
        mgr.register("000001", 10.0)
        mgr.update("000001", 11.0)
        sp1 = mgr.get_stop_price("000001")
        mgr.update("000001", 10.8)
        sp2 = mgr.get_stop_price("000001")
        assert sp2 >= sp1

    def test_short_position_stop_price_only_goes_down(self):
        mgr = TrailingStopManager(trailing_stop=-0.05, trailing_stop_positive=0.02, trailing_stop_positive_offset=0.05)
        mgr.register("000001", 10.0, side="short")
        mgr.update("000001", 9.0)
        sp1 = mgr.get_stop_price("000001")
        mgr.update("000001", 9.2)
        sp2 = mgr.get_stop_price("000001")
        assert sp2 <= sp1

    def test_short_position_trailing_stop_triggered(self):
        mgr = TrailingStopManager(trailing_stop=-0.05, trailing_stop_positive=0.02, trailing_stop_positive_offset=0.05)
        mgr.register("000001", 10.0, side="short")
        result = mgr.update("000001", 11.0)
        assert result == "trailing_stop"

    def test_short_position_no_stop_when_profit_small(self):
        mgr = TrailingStopManager(trailing_stop=-0.05, trailing_stop_positive=0.02, trailing_stop_positive_offset=0.05)
        mgr.register("000001", 10.0, side="short")
        result = mgr.update("000001", 9.7)
        assert result is None


class TestROITable:
    def test_immediate_take_profit(self):
        roi = ROITable({"0": 0.10})
        assert roi.should_take_profit(0.12, 0)

    def test_no_take_profit_below_threshold(self):
        roi = ROITable({"0": 0.10})
        assert not roi.should_take_profit(0.05, 0)

    def test_time_based_threshold(self):
        roi = ROITable({"0": 0.10, "60": 0.05})
        assert not roi.should_take_profit(0.06, 0)
        assert roi.should_take_profit(0.06, 60)


class TestEnhancedRiskManager:
    def test_check_order_approved(self, risk_manager):
        order = Order(order_id="t", symbol="s", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=10.0)
        ctx = {"total_assets": 1000000, "current_positions": {}, "cash": 500000, "open_trades": 0}
        ok, _ = risk_manager.check_order(order, ctx)
        assert ok

    def test_check_order_rejected_concentration(self, risk_manager):
        order = Order(order_id="t", symbol="s", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=50000, price=10.0)
        ctx = {"total_assets": 1000000, "current_positions": {}, "cash": 500000, "open_trades": 0}
        ok, reason = risk_manager.check_order(order, ctx)
        assert not ok
        assert "集中度" in reason

    def test_legacy_interface(self, risk_manager):
        result = risk_manager.check_order_legacy("000001", "buy", 100, 10.0, {}, 1000000)
        assert result["approved"]

    def test_risk_report(self, risk_manager):
        report = risk_manager.get_risk_report()
        assert "active_filters" in report
        assert len(report["active_filters"]) > 0
        assert "trailing_stop_positions" in report

    def test_cvar_calculation(self, risk_manager):
        np.random.seed(42)
        returns = np.random.randn(100) * 0.02 - 0.01
        cvar = risk_manager.calc_cvar(returns.tolist(), 1000000)
        assert cvar > 0
