import pytest


class TestSimulatedTradingBuySell:
    def test_buy_and_sell_same_day_fails_t1(self):
        from core.simulated_trading import SimulatedTrading

        st = SimulatedTrading(initial_capital=100000)
        result = st.execute_buy("000001", "平安银行", "A", 10.0, 1000)
        assert result["success"] is True

        sell_result = st.execute_sell("000001", 10.5)
        assert sell_result["success"] is False
        assert "T+1" in sell_result["error"]

    def test_buy_sets_available_shares_to_zero(self):
        from core.simulated_trading import SimulatedTrading

        st = SimulatedTrading(initial_capital=100000)
        st.execute_buy("000001", "平安银行", "A", 10.0, 1000)
        pos = st._positions["000001"]
        assert pos.available_shares == 0

    def test_settle_makes_shares_available(self):
        from core.simulated_trading import SimulatedTrading

        st = SimulatedTrading(initial_capital=100000)
        st.execute_buy("000001", "平安银行", "A", 10.0, 1000)
        st.daily_settlement()
        pos = st._positions["000001"]
        assert pos.available_shares == 1000

    def test_sell_after_settlement_succeeds(self):
        from core.simulated_trading import SimulatedTrading
        from datetime import datetime, timedelta

        st = SimulatedTrading(initial_capital=100000)
        st.execute_buy("000001", "平安银行", "A", 10.0, 1000)
        st._positions["000001"].buy_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        st.daily_settlement()
        result = st.execute_sell("000001", 10.5)
        assert result["success"] is True

    def test_sell_partial_after_settlement(self):
        from core.simulated_trading import SimulatedTrading
        from datetime import datetime, timedelta

        st = SimulatedTrading(initial_capital=100000)
        st.execute_buy("000001", "平安银行", "A", 10.0, 1000)
        st._positions["000001"].buy_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        st.daily_settlement()
        result = st.execute_sell("000001", 10.5, shares=500)
        assert result["success"] is True
        assert st._positions["000001"].shares == 500
        assert st._positions["000001"].available_shares == 500

    def test_sell_more_than_available_fails(self):
        from core.simulated_trading import SimulatedTrading
        from datetime import datetime, timedelta

        st = SimulatedTrading(initial_capital=100000)
        st.execute_buy("000001", "平安银行", "A", 10.0, 1000)
        st._positions["000001"].buy_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        st.daily_settlement()
        st.execute_sell("000001", 10.5, shares=500)
        result = st.execute_sell("000001", 10.5, shares=600)
        assert result["success"] is False
        assert "可卖数量不足" in result["error"]

    def test_insufficient_funds_buy(self):
        from core.simulated_trading import SimulatedTrading

        st = SimulatedTrading(initial_capital=1000)
        result = st.execute_buy("000001", "平安银行", "A", 10.0, 1000)
        assert result["success"] is False
        assert "资金不足" in result["error"]

    def test_invalid_lot_size_buy(self):
        from core.simulated_trading import SimulatedTrading

        st = SimulatedTrading(initial_capital=100000)
        result = st.execute_buy("000001", "平安银行", "A", 10.0, 50)
        assert result["success"] is False
        assert "最小买入" in result["error"]

    def test_duplicate_order_id_rejected(self):
        from core.simulated_trading import SimulatedTrading

        st = SimulatedTrading(initial_capital=100000)
        result1 = st.execute_buy("000001", "平安银行", "A", 10.0, 1000, order_id="order-1")
        assert result1["success"] is True
        result2 = st.execute_buy("000001", "平安银行", "A", 10.0, 1000, order_id="order-1")
        assert result2["success"] is False
        assert "重复订单" in result2["error"]

    def test_cash_consistency_check_rolls_back_on_buy(self):
        from core.simulated_trading import SimulatedTrading

        st = SimulatedTrading(initial_capital=100000)
        st._cash = 5.0
        result = st.execute_buy("000001", "平安银行", "A", 10.0, 1000)
        assert result["success"] is False
        assert "资金不足" in result["error"]
