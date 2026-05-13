
from core.paper_engine import (
    OrderSide,
    OrderStatus,
    PaperConfig,
    PaperEngine,
    SimulationMode,
    get_paper_engine,
)


class TestPaperEngineBasics:
    def test_engine_creation(self):
        engine = PaperEngine()
        assert engine._cash == 1_000_000.0
        assert engine._initial_capital == 1_000_000.0

    def test_engine_custom_config(self):
        cfg = PaperConfig(initial_capital=500_000, slippage_bps=10)
        engine = PaperEngine(cfg)
        assert engine._cash == 500_000

    def test_order_rejected_no_cash(self):
        cfg = PaperConfig(initial_capital=10_000, max_single_order_pct=3.0, max_position_pct=3.0)
        engine = PaperEngine(cfg)
        order = engine.submit_order("AAPL", OrderSide.BUY, 100, 200.0)
        assert order.status == OrderStatus.REJECTED
        assert "Insufficient" in order.reason

    def test_order_rejected_exceeds_single_limit(self):
        engine = PaperEngine(PaperConfig(initial_capital=1_000_000))
        order = engine.submit_order("AAPL", OrderSide.BUY, 10000, 200.0)
        assert order.status == OrderStatus.REJECTED
        assert "Single order" in order.reason


class TestPaperEngineExecution:
    def test_market_buy_fills(self):
        engine = PaperEngine()
        order = engine.submit_order("AAPL", OrderSide.BUY, 100, 150.0)
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 100
        assert engine._cash < 1_000_000.0

    def test_market_sell_fills(self):
        engine = PaperEngine()
        engine.submit_order("AAPL", OrderSide.BUY, 100, 150.0)
        order = engine.submit_order("AAPL", OrderSide.SELL, 50, 155.0)
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 50

    def test_position_accumulates(self):
        engine = PaperEngine()
        engine.submit_order("AAPL", OrderSide.BUY, 100, 150.0)
        engine.submit_order("AAPL", OrderSide.BUY, 50, 155.0)
        pos = engine.get_position("AAPL")
        assert pos.quantity == 150

    def test_commission_charged(self):
        engine = PaperEngine(PaperConfig(commission_rate=0.001, min_commission=5.0))
        order = engine.submit_order("AAPL", OrderSide.BUY, 10000, 10.0)
        assert order.status == OrderStatus.FILLED
        assert order.commission > 0

    def test_slippage_tracked(self):
        engine = PaperEngine(PaperConfig(slippage_bps=10))
        order = engine.submit_order("AAPL", OrderSide.BUY, 100, 150.0)
        assert order.status == OrderStatus.FILLED
        assert order.slippage_bps >= 0

    def test_stamp_duty_on_sell(self):
        engine = PaperEngine(PaperConfig(commission_rate=0, stamp_duty_rate=0.001))
        engine.submit_order("AAPL", OrderSide.BUY, 100, 150.0)
        sell_order = engine.submit_order("AAPL", OrderSide.SELL, 100, 155.0)
        assert sell_order.commission > 0


class TestPaperEngineAccountStats:
    def test_stats_initial(self):
        engine = PaperEngine()
        stats = engine.get_account_stats()
        assert stats.total_value == 1_000_000.0
        assert stats.total_pnl == 0.0
        assert stats.n_trades == 0

    def test_stats_after_trades(self):
        engine = PaperEngine()
        engine.submit_order("AAPL", OrderSide.BUY, 100, 150.0)
        engine.submit_order("AAPL", OrderSide.SELL, 50, 155.0)
        stats = engine.get_account_stats()
        assert stats.n_trades == 2
        assert stats.total_commission > 0

    def test_stats_to_dict(self):
        engine = PaperEngine()
        stats = engine.get_account_stats()
        d = stats.to_dict()
        assert "total_value" in d
        assert "win_rate" in d
        assert isinstance(d["total_return"], str)

    def test_market_value_update(self):
        engine = PaperEngine()
        engine.submit_order("AAPL", OrderSide.BUY, 100, 100.0)
        engine.update_market_value({"AAPL": 110.0})
        stats = engine.get_account_stats()
        assert stats.market_value == 100 * 110.0
        pos = engine.get_position("AAPL")
        assert pos.unrealized_pnl == 100 * 10.0


class TestPaperEngineRiskChecks:
    def test_position_limit_rejected(self):
        cfg = PaperConfig(initial_capital=1_000_000, max_position_pct=0.1)
        engine = PaperEngine(cfg)
        order = engine.submit_order("AAPL", OrderSide.BUY, 700, 150.0)
        assert order.status == OrderStatus.REJECTED

    def test_risk_checks_disabled(self):
        cfg = PaperConfig(enable_risk_checks=False, initial_capital=10_000)
        engine = PaperEngine(cfg)
        order = engine.submit_order("AAPL", OrderSide.BUY, 100, 100.0)
        assert order.status == OrderStatus.FILLED


class TestPaperEngineSimulationModes:
    def test_close_mode_uses_exact_price(self):
        cfg = PaperConfig(mode=SimulationMode.CLOSE)
        engine = PaperEngine(cfg)
        order = engine.submit_order("AAPL", OrderSide.BUY, 100, 150.0)
        assert order.filled_price == 150.0

    def test_random_mode_varies_price(self):
        cfg = PaperConfig(mode=SimulationMode.RANDOM, slippage_bps=20)
        prices = []
        for _ in range(10):
            eng = PaperEngine(cfg)
            order = eng.submit_order("AAPL", OrderSide.BUY, 10, 100.0)
            prices.append(order.filled_price)
        assert len(set(prices)) > 1


class TestPaperEngineReset:
    def test_reset_clears_state(self):
        engine = PaperEngine()
        engine.submit_order("AAPL", OrderSide.BUY, 100, 150.0)
        engine.reset()
        stats = engine.get_account_stats()
        assert stats.n_trades == 0
        assert stats.current_capital == 1_000_000.0


class TestPaperEngineTradeHistory:
    def test_get_trade_history(self):
        engine = PaperEngine()
        engine.submit_order("AAPL", OrderSide.BUY, 100, 150.0)
        history = engine.get_trade_history()
        assert len(history) == 1
        assert history[0].symbol == "AAPL"

    def test_rejected_orders_not_in_history(self):
        engine = PaperEngine(PaperConfig(initial_capital=100))
        engine.submit_order("AAPL", OrderSide.BUY, 10000, 100.0)
        history = engine.get_trade_history()
        assert len(history) == 0


class TestPaperEngineSingleton:
    def test_singleton(self):
        e1 = get_paper_engine()
        e2 = get_paper_engine()
        assert e1 is e2
