"""Tests for core risk_manager module."""
from core.orders import Order, OrderSide, OrderType
from core.risk_manager import (
    CashSufficiencyFilter,
    ConcentrationFilter,
    DailyLossFilter,
    EnhancedRiskManager,
    MaxOpenTradesFilter,
    ROITable,
    TrailingStopManager,
)


class TestConcentrationFilter:
    def test_within_limit(self):
        filter = ConcentrationFilter(max_concentration=0.3)
        order = Order(order_id="test", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=1000, price=10.0)
        context = {
            "total_assets": 100000.0,
            "current_positions": {"000001": {"market_value": 5000.0}},
        }
        approved, _ = filter.check(order, context)
        assert approved

    def test_exceeds_limit(self):
        filter = ConcentrationFilter(max_concentration=0.3)
        order = Order(order_id="test", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10000, price=10.0)
        context = {
            "total_assets": 100000.0,
            "current_positions": {"000001": {"market_value": 20000.0}},
        }
        approved, reason = filter.check(order, context)
        assert not approved
        assert "集中度" in reason


class TestDailyLossFilter:
    def test_circuit_breaker_triggered(self):
        filter = DailyLossFilter(max_daily_loss=0.05, initial_capital=1000000)
        context = {"total_assets": 1000000}
        filter.update_daily_pnl(-60000, context)
        order = Order(order_id="test", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=10.0)
        approved, reason = filter.check(order, context)
        assert not approved
        assert "熔断" in reason

    def test_normal_operation(self):
        filter = DailyLossFilter(max_daily_loss=0.05, initial_capital=1000000)
        context = {"total_assets": 1000000}
        filter.update_daily_pnl(-10000, context)
        order = Order(order_id="test", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=10.0)
        approved, _ = filter.check(order, context)
        assert approved


class TestMaxOpenTradesFilter:
    def test_within_limit(self):
        filter = MaxOpenTradesFilter(max_open_trades=10)
        order = Order(order_id="test", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=10.0)
        context = {"open_trades": 5}
        approved, _ = filter.check(order, context)
        assert approved

    def test_at_limit(self):
        filter = MaxOpenTradesFilter(max_open_trades=10)
        order = Order(order_id="test", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=10.0)
        context = {"open_trades": 10}
        approved, reason = filter.check(order, context)
        assert not approved


class TestCashSufficiencyFilter:
    def test_sufficient_cash(self):
        filter = CashSufficiencyFilter()
        order = Order(order_id="test", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=10.0)
        context = {"cash": 10000.0}
        approved, _ = filter.check(order, context)
        assert approved

    def test_insufficient_cash(self):
        filter = CashSufficiencyFilter()
        order = Order(order_id="test", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=1000, price=10.0)
        context = {"cash": 5000.0}
        approved, reason = filter.check(order, context)
        assert not approved
        assert "资金不足" in reason

    def test_sell_ignores_cash(self):
        filter = CashSufficiencyFilter()
        order = Order(order_id="test", symbol="000001", side=OrderSide.SELL, order_type=OrderType.MARKET, quantity=100, price=10.0)
        context = {"cash": 0.0}
        approved, _ = filter.check(order, context)
        assert approved


class TestTrailingStopManager:
    def test_register_unregister(self):
        manager = TrailingStopManager()
        manager.register("000001", 100.0, side="long")
        assert "000001" in manager._positions
        manager.unregister("000001")
        assert "000001" not in manager._positions

    def test_trailing_stop_trigger_long(self):
        manager = TrailingStopManager(trailing_stop=-0.05)
        manager.register("000001", 100.0, side="long")
        assert manager.update("000001", 105.0) is None
        assert manager.update("000001", 100.0) == "trailing_stop"

    def test_trailing_stop_trigger_short(self):
        manager = TrailingStopManager(trailing_stop=-0.05)
        manager.register("000001", 100.0, side="short")
        assert manager.update("000001", 95.0) is None
        assert manager.update("000001", 105.0) == "trailing_stop"


class TestROITable:
    def test_take_profit_threshold(self):
        table = ROITable({"0": 0.10, "30": 0.05, "60": 0.02})
        assert table.should_take_profit(0.15, 0)
        assert not table.should_take_profit(0.05, 0)
        assert table.should_take_profit(0.08, 30)
        assert not table.should_take_profit(0.01, 30)
        assert table.should_take_profit(0.05, 60)
        assert not table.should_take_profit(0.005, 60)


class TestEnhancedRiskManager:
    def test_enhanced_risk_manager_creation(self):
        manager = EnhancedRiskManager(
            max_concentration=0.3,
            max_daily_loss=0.05,
            initial_capital=1000000,
            max_open_trades=10,
        )
        assert manager._initial_capital == 1000000
        assert len(manager._filters) >= 4

    def test_order_rejected_by_concentration(self):
        manager = EnhancedRiskManager(max_concentration=0.2, initial_capital=100000)
        order = Order(order_id="test", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=5000, price=10.0)
        context = {
            "total_assets": 100000.0,
            "current_positions": {},
            "cash": 100000.0,
            "open_trades": 0,
        }
        approved, reason = manager.check_order(order, context)
        assert not approved
        assert "集中度" in reason

    def test_var_calculation(self):
        manager = EnhancedRiskManager()
        returns = [0.01, -0.02, 0.015, -0.01, 0.02] * 5
        var = manager.calc_var(returns, 100000.0)
        assert isinstance(var, float)
        assert var >= 0

    def test_reset_clears_state(self):
        manager = EnhancedRiskManager(max_concentration=0.3, initial_capital=100000)
        manager.update_daily_pnl(-5000)
        manager.register_position("000001", 10.0)
        manager.update_position_returns("000001", -0.01)
        manager.reset()
        report = manager.get_risk_report()
        assert report["current_daily_pnl"] == 0.0
        assert report["circuit_breaker_active"] is False

    def test_concentration_at_exact_boundary(self):
        filter = ConcentrationFilter(max_concentration=0.3)
        order = Order(order_id="test", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=100, price=10.0)
        context = {
            "total_assets": 10000.0,
            "current_positions": {"000001": {"market_value": 2000.0}},
            "cash": 8000.0,
        }
        approved, reason = filter.check(order, context)
        assert not approved
        assert "集中度" in reason

    def test_concentration_below_boundary_with_slippage_buffer(self):
        filter = ConcentrationFilter(max_concentration=0.3)
        order = Order(order_id="test", symbol="000001", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=90, price=10.0)
        context = {
            "total_assets": 10000.0,
            "current_positions": {"000001": {"market_value": 2000.0}},
            "cash": 8000.0,
        }
        approved, reason = filter.check(order, context)
        assert approved
