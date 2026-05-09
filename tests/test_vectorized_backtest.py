import pytest
import numpy as np
import pandas as pd

from core.backtest.vectorized import vectorized_backtest, vectorized_equity_curve


class TestVectorizedEquityCurve:

    def test_no_signals_returns_initial_capital(self):
        closes = np.linspace(10, 12, 100)
        entries = np.zeros(100, dtype=bool)
        exits = np.zeros(100, dtype=bool)
        eq, trades = vectorized_equity_curve(closes, entries, exits)
        assert len(eq) == 100
        assert np.allclose(eq, 1_000_000)
        assert trades == []

    def test_single_round_trip(self):
        closes = np.ones(50) * 10.0
        entries = np.zeros(50, dtype=bool)
        exits = np.zeros(50, dtype=bool)
        entries[5] = True
        exits[20] = True
        eq, trades = vectorized_equity_curve(closes, entries, exits, initial_capital=1_000_000)
        assert len(eq) == 50
        assert eq[0] == 1_000_000
        buy_trades = [t for t in trades if t["action"] == "buy"]
        sell_trades = [t for t in trades if t["action"] == "sell"]
        assert len(buy_trades) >= 1
        assert len(sell_trades) >= 1

    def test_equity_starts_at_initial_capital(self):
        np.random.seed(42)
        closes = np.cumsum(np.random.randn(200) * 0.5) + 100
        entries = np.zeros(200, dtype=bool)
        exits = np.zeros(200, dtype=bool)
        for i in range(10, 200, 30):
            entries[i] = True
        for i in range(25, 200, 30):
            exits[i] = True
        eq, trades = vectorized_equity_curve(closes, entries, exits)
        assert abs(eq[0] - 1_000_000) < 1.0

    def test_equity_never_negative(self):
        np.random.seed(42)
        closes = np.cumsum(np.random.randn(200) * 0.5) + 100
        entries = np.zeros(200, dtype=bool)
        exits = np.zeros(200, dtype=bool)
        for i in range(10, 200, 30):
            entries[i] = True
        for i in range(25, 200, 30):
            exits[i] = True
        eq, _ = vectorized_equity_curve(closes, entries, exits)
        assert np.all(eq >= 0)


class TestVectorizedBacktest:

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        signals = pd.Series(dtype=bool)
        result = vectorized_backtest(df, signals, signals)
        assert len(result["equity_curve"]) == 0

    def test_basic_backtest(self):
        np.random.seed(42)
        n = 200
        closes = np.cumsum(np.random.randn(n) * 0.5) + 100
        df = pd.DataFrame({"close": closes})
        entries = pd.Series(np.zeros(n, dtype=bool))
        exits = pd.Series(np.zeros(n, dtype=bool))
        for i in range(10, n, 30):
            entries.iloc[i] = True
        for i in range(25, n, 30):
            exits.iloc[i] = True
        result = vectorized_backtest(df, entries, exits)
        assert len(result["equity_curve"]) == n
        assert len(result["trades"]) > 0
        assert abs(result["equity_curve"][0] - 1_000_000) < 1.0

    def test_signal_length_mismatch(self):
        df = pd.DataFrame({"close": [1, 2, 3]})
        entries = pd.Series([True, False])
        exits = pd.Series([False, True])
        result = vectorized_backtest(df, entries, exits)
        assert len(result["equity_curve"]) == 3
