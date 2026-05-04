import pytest
import pandas as pd
import numpy as np
from core.strategies import (
    BaseStrategy, DualMAStrategy, MACDStrategy, KDJStrategy,
    BollingerBreakoutStrategy, SignalType, KaufmanAdaptiveStrategy,
    SuperTrendStrategy, AdaptiveTrendFollowingStrategy,
    _safe_divide,
)


class TestSafeDivide:
    def test_normal_division(self):
        assert _safe_divide(10, 2) == 5.0

    def test_zero_denominator(self):
        assert _safe_divide(10, 0) == 0.0

    def test_near_zero_denominator(self):
        assert _safe_divide(10, 1e-15) == 0.0

    def test_custom_default(self):
        assert _safe_divide(10, 0, default=-1.0) == -1.0

    def test_numpy_array(self):
        result = _safe_divide(np.array([10, 20, 30]), np.array([2, 0, 3]))
        np.testing.assert_array_equal(result, [5.0, 0.0, 10.0])

    def test_pandas_series(self):
        result = _safe_divide(pd.Series([10, 20]), pd.Series([2, 0]))
        assert result.iloc[0] == 5.0
        assert result.iloc[1] == 0.0


class TestBaseStrategyVectorized:
    def test_populate_indicators_default(self, sample_ohlcv):
        s = BaseStrategy()
        result = s.populate_indicators(sample_ohlcv)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(sample_ohlcv)

    def test_populate_entry_exit_default(self, sample_ohlcv):
        s = BaseStrategy()
        result = s.populate_entry_exit(sample_ohlcv)
        assert "enter_signal" in result.columns
        assert "exit_signal" in result.columns

    def test_vectorized_fallback_to_iterative(self, sample_ohlcv):
        s = BaseStrategy()
        result = s.generate_signals_vectorized(sample_ohlcv)
        assert result.strategy_name == "BaseStrategy"


class TestDualMAStrategy:
    def test_generate_signal(self, sample_ohlcv):
        s = DualMAStrategy(short_period=5, long_period=20)
        signal = s.generate_signal(sample_ohlcv)
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]

    def test_populate_indicators(self, sample_ohlcv):
        s = DualMAStrategy(short_period=5, long_period=20)
        result = s.populate_indicators(sample_ohlcv)
        assert "ma_5" in result.columns
        assert "ma_20" in result.columns

    def test_populate_entry_exit(self, sample_ohlcv):
        s = DualMAStrategy(short_period=5, long_period=20)
        df = s.populate_indicators(sample_ohlcv)
        df = s.populate_entry_exit(df)
        assert "enter_signal" in df.columns
        assert "exit_signal" in df.columns
        assert df["enter_signal"].max() <= 1.0
        assert df["exit_signal"].max() <= 1.0

    def test_vectorized_signals(self, sample_ohlcv):
        s = DualMAStrategy(short_period=5, long_period=20)
        result = s.generate_signals_vectorized(sample_ohlcv)
        assert result.strategy_name == "DualMAStrategy"
        assert len(result.signals) > 0

    def test_trending_up_produces_buy(self, trending_up_ohlcv):
        s = DualMAStrategy(short_period=5, long_period=20)
        result = s.generate_signals(trending_up_ohlcv)
        buy_signals = [sig for sig in result.signals if sig.signal_type == SignalType.BUY]
        hold_signals = [sig for sig in result.signals if sig.signal_type == SignalType.HOLD]
        assert len(buy_signals) + len(hold_signals) == len(result.signals)

    def test_crossover_produces_buy(self):
        n = 60
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        close = np.concatenate([
            np.linspace(20, 10, n // 2),
            np.linspace(10, 20, n // 2),
        ])
        high = close * 1.01
        low = close * 0.99
        open_p = close * 0.998
        volume = np.ones(n) * 1000000
        df = pd.DataFrame({
            "date": dates, "open": open_p, "high": high, "low": low,
            "close": close, "volume": volume, "amount": close * volume,
        }).reset_index(drop=True)
        s = DualMAStrategy(short_period=5, long_period=20)
        result = s.generate_signals(df)
        buy_signals = [sig for sig in result.signals if sig.signal_type == SignalType.BUY]
        assert len(buy_signals) > 0

    def test_trending_down_produces_sell(self, trending_down_ohlcv):
        s = DualMAStrategy(short_period=5, long_period=20)
        result = s.generate_signals(trending_down_ohlcv)
        sell_signals = [sig for sig in result.signals if sig.signal_type == SignalType.SELL]
        hold_signals = [sig for sig in result.signals if sig.signal_type == SignalType.HOLD]
        assert len(sell_signals) + len(hold_signals) == len(result.signals)

    def test_crossover_produces_sell(self):
        n = 60
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        close = np.concatenate([
            np.linspace(10, 20, n // 2),
            np.linspace(20, 10, n // 2),
        ])
        high = close * 1.01
        low = close * 0.99
        open_p = close * 1.002
        volume = np.ones(n) * 1000000
        df = pd.DataFrame({
            "date": dates, "open": open_p, "high": high, "low": low,
            "close": close, "volume": volume, "amount": close * volume,
        }).reset_index(drop=True)
        s = DualMAStrategy(short_period=5, long_period=20)
        result = s.generate_signals(df)
        sell_signals = [sig for sig in result.signals if sig.signal_type == SignalType.SELL]
        assert len(sell_signals) > 0

    def test_insufficient_data(self):
        s = DualMAStrategy(short_period=5, long_period=20)
        small_df = pd.DataFrame({"close": [10, 11], "high": [11, 12], "low": [9, 10], "open": [10, 10.5], "volume": [1000, 1000]})
        signal = s.generate_signal(small_df)
        assert signal.signal_type == SignalType.HOLD


class TestMACDStrategy:
    def test_generate_signal(self, sample_ohlcv):
        s = MACDStrategy()
        signal = s.generate_signal(sample_ohlcv)
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]

    def test_populate_indicators(self, sample_ohlcv):
        s = MACDStrategy()
        result = s.populate_indicators(sample_ohlcv)
        assert "dif" in result.columns
        assert "dea" in result.columns
        assert "hist" in result.columns

    def test_vectorized_signals(self, sample_ohlcv):
        s = MACDStrategy()
        result = s.generate_signals_vectorized(sample_ohlcv)
        assert result.strategy_name == "MACDStrategy"
        assert len(result.signals) > 0


class TestKDJStrategy:
    def test_generate_signal(self, sample_ohlcv):
        s = KDJStrategy()
        signal = s.generate_signal(sample_ohlcv)
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]

    def test_populate_indicators(self, sample_ohlcv):
        s = KDJStrategy()
        result = s.populate_indicators(sample_ohlcv)
        assert "k" in result.columns
        assert "d" in result.columns
        assert "j" in result.columns

    def test_vectorized_signals(self, sample_ohlcv):
        s = KDJStrategy()
        result = s.generate_signals_vectorized(sample_ohlcv)
        assert result.strategy_name == "KDJStrategy"

    def test_constant_prices_no_inf(self):
        n = 30
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        price = 10.0
        df = pd.DataFrame({
            "date": dates, "open": price, "high": price, "low": price,
            "close": price, "volume": [1000000] * n, "amount": [price * 1000000] * n,
        })
        s = KDJStrategy()
        result = s.populate_indicators(df)
        assert not result["k"].isna().all()
        assert not np.isinf(result["k"]).any()
        signal = s.generate_signal(df)
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]


class TestBollingerBreakoutStrategy:
    def test_generate_signal(self, sample_ohlcv):
        s = BollingerBreakoutStrategy()
        signal = s.generate_signal(sample_ohlcv)
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]

    def test_populate_indicators(self, sample_ohlcv):
        s = BollingerBreakoutStrategy()
        result = s.populate_indicators(sample_ohlcv)
        assert "bb_mid" in result.columns
        assert "bb_upper" in result.columns
        assert "bb_lower" in result.columns

    def test_vectorized_signals(self, sample_ohlcv):
        s = BollingerBreakoutStrategy()
        result = s.generate_signals_vectorized(sample_ohlcv)
        assert result.strategy_name == "BollingerBreakoutStrategy"


class TestKaufmanAdaptiveStrategy:
    def test_generate_signal_returns_valid_type(self, sample_ohlcv):
        s = KaufmanAdaptiveStrategy()
        signal = s.generate_signal(sample_ohlcv)
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]

    def test_insufficient_data_returns_hold(self):
        s = KaufmanAdaptiveStrategy()
        small_df = pd.DataFrame({
            "close": [10, 11, 12], "high": [11, 12, 13],
            "low": [9, 10, 11], "open": [10, 10.5, 11.5], "volume": [1000, 1000, 1000],
        })
        signal = s.generate_signal(small_df)
        assert signal.signal_type == SignalType.HOLD

    def test_per_bar_er_adaptation(self, sample_ohlcv):
        s = KaufmanAdaptiveStrategy()
        signal = s.generate_signal(sample_ohlcv)
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
        assert 0 <= signal.strength <= 1.0


class TestSuperTrendStrategy:
    def test_generate_signal_returns_valid_type(self, sample_ohlcv):
        s = SuperTrendStrategy()
        signal = s.generate_signal(sample_ohlcv)
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]

    def test_insufficient_data_returns_hold(self):
        s = SuperTrendStrategy()
        small_df = pd.DataFrame({
            "close": [10, 11], "high": [11, 12],
            "low": [9, 10], "open": [10, 10.5], "volume": [1000, 1000],
        })
        signal = s.generate_signal(small_df)
        assert signal.signal_type == SignalType.HOLD


class TestAdaptiveTrendFollowingStrategy:
    def test_generate_signal_returns_valid_type(self, sample_ohlcv):
        s = AdaptiveTrendFollowingStrategy()
        signal = s.generate_signal(sample_ohlcv)
        assert signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]

    def test_insufficient_data_returns_hold(self):
        s = AdaptiveTrendFollowingStrategy()
        small_df = pd.DataFrame({
            "close": [10, 11], "high": [11, 12],
            "low": [9, 10], "open": [10, 10.5], "volume": [1000, 1000],
        })
        signal = s.generate_signal(small_df)
        assert signal.signal_type == SignalType.HOLD
