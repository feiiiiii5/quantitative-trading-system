import numpy as np
import pandas as pd
import pytest


class TestExecuteTwap:
    def test_basic_distribution(self):
        from core.execution_engine import execute_twap
        assert execute_twap(100, 4, 0) == 25
        assert execute_twap(100, 4, 1) == 25
        assert execute_twap(100, 4, 2) == 25
        assert execute_twap(100, 4, 3) == 25

    def test_remainder_distribution(self):
        from core.execution_engine import execute_twap
        assert execute_twap(103, 4, 0) == 26
        assert execute_twap(103, 4, 1) == 26
        assert execute_twap(103, 4, 2) == 26
        assert execute_twap(103, 4, 3) == 25

    def test_invalid_input(self):
        from core.execution_engine import execute_twap
        assert execute_twap(0, 4, 0) == 0
        assert execute_twap(100, 0, 0) == 0


class TestExecutionEngineTwap:
    def test_twap_executes_all_bars(self):
        from core.execution_engine import ExecutionEngine

        engine = ExecutionEngine()
        df = pd.DataFrame({
            "close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        })
        result = engine.execute_twap_order("buy", 600, df, n_bars=6)
        assert result.filled_quantity == 600
        assert result.execution_method == "twap"
        assert len(result.bar_details) == 6

    def test_twap_price_order_is_newest_first(self):
        from core.execution_engine import ExecutionEngine

        engine = ExecutionEngine()
        df = pd.DataFrame({
            "close": [90.0, 95.0, 100.0, 105.0, 110.0, 115.0],
        })
        result = engine.execute_twap_order("buy", 600, df, n_bars=6)
        prices = [b["price"] for b in result.bar_details]
        assert prices[0] == 115.0
        assert prices[-1] == 90.0

    def test_twap_empty_data(self):
        from core.execution_engine import ExecutionEngine

        engine = ExecutionEngine()
        result = engine.execute_twap_order("buy", 100, pd.DataFrame(), n_bars=6)
        assert result.filled_quantity == 0


class TestExecutionEngineVwap:
    def test_vwap_executes_all_bars(self):
        from core.execution_engine import ExecutionEngine

        engine = ExecutionEngine()
        df = pd.DataFrame({
            "close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
            "volume": [1000, 2000, 3000, 4000, 5000, 6000],
        })
        result = engine.execute_vwap_order("buy", 600, df, n_bars=6)
        assert result.filled_quantity == 600
        assert result.execution_method == "vwap"

    def test_vwap_price_order_is_newest_first(self):
        from core.execution_engine import ExecutionEngine

        engine = ExecutionEngine()
        df = pd.DataFrame({
            "close": [90.0, 95.0, 100.0, 105.0, 110.0, 115.0],
            "volume": [1000, 1000, 1000, 1000, 1000, 1000],
        })
        result = engine.execute_vwap_order("buy", 600, df, n_bars=6)
        prices = [b["price"] for b in result.bar_details]
        assert prices[0] == 115.0
        assert prices[-1] == 90.0


class TestCostModel:
    def test_buy_cost_positive(self):
        from core.execution_engine import CostModel
        cm = CostModel()
        cost = cm.calc_buy_cost(100.0, 100)
        assert cost > 0

    def test_sell_cost_includes_stamp_tax(self):
        from core.execution_engine import CostModel
        cm = CostModel()
        buy_cost = cm.calc_buy_cost(100.0, 100)
        sell_cost = cm.calc_sell_cost(100.0, 100)
        assert sell_cost > buy_cost

    def test_total_cost(self):
        from core.execution_engine import CostModel
        cm = CostModel()
        total = cm.calc_total_cost(100.0, 105.0, 100)
        assert total > 0
