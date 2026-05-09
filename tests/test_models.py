import pytest
from pydantic import ValidationError

from core.models import (
    TickData,
    BarData,
    TradeSignalV2,
    SignalTypeV2,
    PositionV2,
    OrderV2,
    OrderSide,
    OrderStatus,
    TradeRecordV2,
    BacktestConfigV2,
    BacktestResultV2,
    validate_signal_dict,
    convert_legacy_signal,
)


class TestTickData:

    def test_valid_tick(self):
        tick = TickData(symbol="000001", price=10.5, volume=1000)
        assert tick.symbol == "000001"
        assert tick.price == 10.5

    def test_negative_price_rejected(self):
        with pytest.raises(ValidationError):
            TickData(symbol="000001", price=-1.0)

    def test_zero_price_allowed(self):
        tick = TickData(symbol="000001", price=0.0)
        assert tick.price == 0.0

    def test_json_round_trip(self):
        tick = TickData(symbol="000001", price=10.5, bid=10.4, ask=10.6)
        data = tick.model_dump()
        restored = TickData(**data)
        assert restored.price == 10.5


class TestBarData:

    def test_valid_bar(self):
        bar = BarData(symbol="000001", date="2023-01-01", open=10, high=11, low=9, close=10.5, volume=5000)
        assert bar.close == 10.5

    def test_high_lt_low_rejected(self):
        with pytest.raises(ValidationError):
            BarData(symbol="000001", high=9, low=11)

    def test_defaults(self):
        bar = BarData()
        assert bar.symbol == ""
        assert bar.close == 0.0


class TestTradeSignalV2:

    def test_buy_signal(self):
        sig = TradeSignalV2(signal_type=SignalTypeV2.BUY, strength=0.8, price=10.5)
        assert sig.signal_type == SignalTypeV2.BUY
        assert sig.strength == 0.8

    def test_strength_out_of_range(self):
        with pytest.raises(ValidationError):
            TradeSignalV2(signal_type=SignalTypeV2.BUY, strength=1.5)

    def test_negative_bar_index_rejected(self):
        with pytest.raises(ValidationError):
            TradeSignalV2(signal_type=SignalTypeV2.BUY, bar_index=-2)

    def test_buy_stop_loss_above_price_rejected(self):
        with pytest.raises(ValidationError):
            TradeSignalV2(signal_type=SignalTypeV2.BUY, price=10.0, stop_loss=11.0)

    def test_sell_stop_loss_below_price_rejected(self):
        with pytest.raises(ValidationError):
            TradeSignalV2(signal_type=SignalTypeV2.SELL, price=10.0, stop_loss=9.0)

    def test_buy_take_profit_below_price_rejected(self):
        with pytest.raises(ValidationError):
            TradeSignalV2(signal_type=SignalTypeV2.BUY, price=10.0, take_profit=9.0)

    def test_sell_take_profit_above_price_rejected(self):
        with pytest.raises(ValidationError):
            TradeSignalV2(signal_type=SignalTypeV2.SELL, price=10.0, take_profit=11.0)

    def test_hold_signal_no_price_validation(self):
        sig = TradeSignalV2(signal_type=SignalTypeV2.HOLD)
        assert sig.signal_type == SignalTypeV2.HOLD


class TestPositionV2:

    def test_long_position(self):
        pos = PositionV2(symbol="000001", quantity=100, avg_cost=10.0)
        assert pos.is_long is True
        assert pos.is_short is False
        assert pos.is_flat is False

    def test_flat_position(self):
        pos = PositionV2(symbol="000001", quantity=0)
        assert pos.is_flat is True

    def test_negative_cost_rejected(self):
        with pytest.raises(ValidationError):
            PositionV2(symbol="000001", avg_cost=-1.0)


class TestOrderV2:

    def test_valid_order(self):
        order = OrderV2(symbol="000001", side=OrderSide.BUY, quantity=100)
        assert order.side == OrderSide.BUY
        assert order.status == OrderStatus.PENDING

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValidationError):
            OrderV2(symbol="000001", side=OrderSide.BUY, quantity=0)

    def test_negative_quantity_rejected(self):
        with pytest.raises(ValidationError):
            OrderV2(symbol="000001", side=OrderSide.BUY, quantity=-10)


class TestTradeRecordV2:

    def test_valid_trade(self):
        trade = TradeRecordV2(symbol="000001", side=OrderSide.BUY, quantity=100, price=10.5)
        assert trade.price == 10.5

    def test_zero_price_rejected(self):
        with pytest.raises(ValidationError):
            TradeRecordV2(symbol="000001", side=OrderSide.BUY, quantity=100, price=0)


class TestBacktestConfigV2:

    def test_valid_config(self):
        config = BacktestConfigV2(initial_capital=500000)
        assert config.initial_capital == 500000

    def test_zero_capital_rejected(self):
        with pytest.raises(ValidationError):
            BacktestConfigV2(initial_capital=0)

    def test_commission_out_of_range(self):
        with pytest.raises(ValidationError):
            BacktestConfigV2(commission_rate=0.1)


class TestBacktestResultV2:

    def test_valid_result(self):
        result = BacktestResultV2(strategy_name="test", total_return=0.15, sharpe_ratio=1.5)
        assert result.strategy_name == "test"

    def test_win_rate_out_of_range(self):
        with pytest.raises(ValidationError):
            BacktestResultV2(strategy_name="test", win_rate=1.5)

    def test_negative_trades_rejected(self):
        with pytest.raises(ValidationError):
            BacktestResultV2(strategy_name="test", total_trades=-1)


class TestLegacyConversion:

    def test_validate_signal_dict_buy(self):
        data = {"type": "buy", "strength": 0.8, "bar_index": 5, "price": 10.5}
        sig = validate_signal_dict(data)
        assert sig.signal_type == SignalTypeV2.BUY
        assert sig.strength == 0.8

    def test_validate_signal_dict_sell(self):
        data = {"type": "sell", "bar_index": 10, "price": 12.0}
        sig = validate_signal_dict(data)
        assert sig.signal_type == SignalTypeV2.SELL

    def test_convert_legacy_signal(self):
        sig = TradeSignalV2(signal_type=SignalTypeV2.BUY, strength=0.7, price=10.0)
        d = convert_legacy_signal(sig)
        assert d["type"] == "buy"
        assert d["strength"] == 0.7
        assert d["price"] == 10.0

    def test_round_trip(self):
        original = {"type": "buy", "strength": 0.6, "bar_index": 3, "price": 15.0, "stop_loss": 14.0}
        sig = validate_signal_dict(original)
        converted = convert_legacy_signal(sig)
        assert converted["type"] == original["type"]
        assert converted["strength"] == original["strength"]
        assert converted["bar_index"] == original["bar_index"]
