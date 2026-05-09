import time

import numpy as np
import pandas as pd
import pytest

from core.adaptive_strategy import MarketRegime, classify_market_regime
from core.backtest import BacktestEngine


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


class TestBacktestEngineBenchmark:
    def test_backtest_1000_bars_under_5s(self) -> None:
        from core.strategies import DualMAStrategy
        df = _make_test_data(1000)
        engine = BacktestEngine()
        strategy = DualMAStrategy()
        t0 = time.perf_counter()
        result = engine.run(strategy, df)
        elapsed = time.perf_counter() - t0
        assert result is not None
        assert elapsed < 5.0, "Backtest 1000 bars took %.2fs, exceeds 5s threshold" % elapsed

    def test_backtest_500_bars_under_3s(self) -> None:
        from core.strategies import DualMAStrategy
        df = _make_test_data(500)
        engine = BacktestEngine()
        strategy = DualMAStrategy()
        t0 = time.perf_counter()
        result = engine.run(strategy, df)
        elapsed = time.perf_counter() - t0
        assert result is not None
        assert elapsed < 3.0, "Backtest 500 bars took %.2fs, exceeds 3s threshold" % elapsed

    def test_regime_classification_5000_bars_under_500ms(self) -> None:
        df = _make_test_data(5000)
        t0 = time.perf_counter()
        regimes = classify_market_regime(df)
        elapsed = time.perf_counter() - t0
        assert len(regimes) == 5000
        assert elapsed < 0.5, "classify_market_regime 5000 bars took %.2fs, exceeds 500ms" % elapsed

    def test_regime_classification_1000_bars_under_100ms(self) -> None:
        df = _make_test_data(1000)
        t0 = time.perf_counter()
        regimes = classify_market_regime(df)
        elapsed = time.perf_counter() - t0
        assert len(regimes) == 1000
        assert elapsed < 0.1, "classify_market_regime 1000 bars took %.2fs, exceeds 100ms" % elapsed

    def test_multi_strategy_backtest(self) -> None:
        from core.strategies import DualMAStrategy, MACDStrategy
        df = _make_test_data(500)
        engine = BacktestEngine()
        strategies = [DualMAStrategy(), MACDStrategy()]
        t0 = time.perf_counter()
        results = engine.run_multi(strategies, df)
        elapsed = time.perf_counter() - t0
        assert len(results) >= 1
        assert elapsed < 10.0, "Multi-strategy backtest took %.2fs, exceeds 10s" % elapsed

    def test_backtest_result_serialization_under_50ms(self) -> None:
        from core.strategies import DualMAStrategy
        df = _make_test_data(500)
        engine = BacktestEngine()
        result = engine.run(DualMAStrategy(), df)
        assert result is not None
        t0 = time.perf_counter()
        serialized = result.to_dict()
        elapsed = time.perf_counter() - t0
        assert isinstance(serialized, dict)
        assert elapsed < 0.05, "Result serialization took %.2fs, exceeds 50ms" % elapsed

    def test_backtest_result_summary_under_5ms(self) -> None:
        from core.strategies import DualMAStrategy
        df = _make_test_data(500)
        engine = BacktestEngine()
        result = engine.run(DualMAStrategy(), df)
        assert result is not None
        t0 = time.perf_counter()
        summary = result.summary_dict()
        elapsed = time.perf_counter() - t0
        assert isinstance(summary, dict)
        assert elapsed < 0.005, "Summary generation took %.2fs, exceeds 5ms" % elapsed

    def test_regime_deterministic(self) -> None:
        df1 = _make_test_data(200)
        df2 = _make_test_data(200)
        result1 = classify_market_regime(df1)
        result2 = classify_market_regime(df2)
        assert result1 == result2
