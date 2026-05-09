import time

import numpy as np
import pandas as pd
import pytest

from core.adaptive_strategy import MarketRegime, classify_market_regime


def _make_test_data(n: int = 1000) -> pd.DataFrame:
    np.random.seed(42)
    dates = pd.date_range("2021-01-01", periods=n, freq="B")
    price = 10 * np.exp(np.cumsum(np.random.randn(n) * 0.01))
    return pd.DataFrame({
        "date": dates,
        "open": price * 0.999,
        "high": price * 1.005,
        "low": price * 0.995,
        "close": price,
        "volume": np.random.randint(1e6, 1e7, n).astype(float),
        "amount": np.random.randint(1e7, 1e8, n).astype(float),
    })


class TestClassifyMarketRegimeVectorized:
    def test_returns_correct_length(self) -> None:
        df = _make_test_data(100)
        result = classify_market_regime(df)
        assert len(result) == 100

    def test_returns_market_regime_enum(self) -> None:
        df = _make_test_data(100)
        result = classify_market_regime(df)
        for r in result:
            assert isinstance(r, MarketRegime)

    def test_short_df_returns_default(self) -> None:
        df = _make_test_data(10)
        result = classify_market_regime(df)
        assert len(result) == 10
        assert all(r == MarketRegime.LOW_VOLATILITY_CONSOLIDATION for r in result)

    def test_first_window_bars_are_default(self) -> None:
        df = _make_test_data(100)
        result = classify_market_regime(df, window=20)
        for r in result[:20]:
            assert r == MarketRegime.LOW_VOLATILITY_CONSOLIDATION

    def test_5000_bars_under_500ms(self) -> None:
        df = _make_test_data(5000)
        t0 = time.perf_counter()
        result = classify_market_regime(df)
        elapsed = time.perf_counter() - t0
        assert len(result) == 5000
        assert elapsed < 0.5, "classify_market_regime 5000 bars took %.2fs, exceeds 500ms" % elapsed

    def test_1000_bars_under_100ms(self) -> None:
        df = _make_test_data(1000)
        t0 = time.perf_counter()
        result = classify_market_regime(df)
        elapsed = time.perf_counter() - t0
        assert len(result) == 1000
        assert elapsed < 0.1, "classify_market_regime 1000 bars took %.2fs, exceeds 100ms" % elapsed

    def test_trending_data_produces_trend_regimes(self) -> None:
        np.random.seed(42)
        n = 500
        dates = pd.date_range("2021-01-01", periods=n, freq="B")
        price = 10 * np.exp(np.cumsum(np.random.randn(n) * 0.03 + 0.002))
        df = pd.DataFrame({
            "date": dates,
            "open": price * 0.999,
            "high": price * 1.005,
            "low": price * 0.995,
            "close": price,
            "volume": np.random.randint(1e6, 1e7, n).astype(float),
            "amount": np.random.randint(1e7, 1e8, n).astype(float),
        })
        result = classify_market_regime(df)
        trend_regimes = {MarketRegime.STRONG_TREND_UP, MarketRegime.MILD_TREND_UP,
                         MarketRegime.STRONG_TREND_DOWN, MarketRegime.MILD_TREND_DOWN}
        has_trend = any(r in trend_regimes for r in result)
        assert has_trend, "Trending data should produce at least one trend regime"

    def test_deterministic_with_same_seed(self) -> None:
        df1 = _make_test_data(200)
        df2 = _make_test_data(200)
        result1 = classify_market_regime(df1)
        result2 = classify_market_regime(df2)
        assert result1 == result2
