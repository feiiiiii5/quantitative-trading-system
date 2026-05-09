import pytest
import numpy as np
import pandas as pd

from core.backtest.pit_db import PointInTimeDB, PITQuery, create_pit_db


class TestPointInTimeDB:

    def test_insert_and_query(self):
        pit = create_pit_db()
        pit.insert_financial("000001", "2024Q1", "2024-04-30", "revenue", 100.5)
        q = PITQuery(symbol="000001", metric="revenue", as_of_date="2024-05-01")
        result = pit.query_latest(q)
        assert result is not None
        assert result["value"] == 100.5

    def test_no_future_data(self):
        pit = create_pit_db()
        pit.insert_financial("000001", "2024Q2", "2024-08-30", "revenue", 120.0)
        q = PITQuery(symbol="000001", metric="revenue", as_of_date="2024-06-01")
        result = pit.query_latest(q)
        assert result is None

    def test_multiple_metrics(self):
        pit = create_pit_db()
        pit.insert_financial("000001", "2024Q1", "2024-04-30", "revenue", 100.0)
        pit.insert_financial("000001", "2024Q1", "2024-04-30", "net_profit", 10.0)
        metrics = pit.query_multiple_metrics("000001", ["revenue", "net_profit"], "2024-05-01")
        assert metrics["revenue"] is not None
        assert metrics["net_profit"] is not None

    def test_price_adjust(self):
        pit = create_pit_db()
        pit.insert_price_adjust("000001", "2024-01-01", 1.0, False)
        pit.insert_price_adjust("000001", "2024-06-01", 1.2, False)
        adj = pit.query_adjusted_price("000001", "2024-06-15", 10.0)
        assert adj == 12.0

    def test_suspension_check(self):
        pit = create_pit_db()
        pit.insert_price_adjust("000001", "2024-01-01", 1.0, True)
        assert pit.is_suspended("000001", "2024-01-01")

    def test_snapshot(self):
        pit = create_pit_db()
        pit.save_snapshot("000001", "2024-05-01", {"revenue": 100.0, "profit": 10.0})
        loaded = pit.load_snapshot("000001", "2024-05-01")
        assert loaded is not None
        assert loaded["revenue"] == 100.0

    def test_context_manager(self):
        with create_pit_db() as pit:
            pit.insert_financial("000001", "2024Q1", "2024-04-30", "revenue", 100.0)
            q = PITQuery(symbol="000001", metric="revenue", as_of_date="2024-05-01")
            assert pit.query_latest(q) is not None

    def test_batch_insert(self):
        pit = create_pit_db()
        records = [
            ("000001", "2024Q1", "2024-04-30", "revenue", 100.0, ""),
            ("000002", "2024Q1", "2024-04-30", "revenue", 200.0, ""),
        ]
        count = pit.insert_financial_batch(records)
        assert count == 2

    def test_cross_section(self):
        pit = create_pit_db()
        pit.insert_financial("000001", "2024Q1", "2024-04-30", "revenue", 100.0)
        pit.insert_financial("000002", "2024Q1", "2024-04-28", "revenue", 200.0)
        pit.commit()
        df = pit.query_cross_section("revenue", "2024-05-01")
        assert len(df) == 2
