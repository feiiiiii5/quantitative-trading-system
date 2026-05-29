import asyncio
import sys
from collections.abc import Generator
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))


@pytest.fixture(scope="session", autouse=True)
def _enable_per_ip_rate_limit_testing():
    from api.middleware import PerIPRateLimitMiddleware
    PerIPRateLimitMiddleware._testing = True
    yield
    PerIPRateLimitMiddleware._testing = False


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_ohlcv():
    np.random.seed(42)
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    base = 10.0
    returns = np.random.randn(n) * 0.02 + 0.0003
    close = base * np.cumprod(1 + returns)
    high = close * (1 + np.abs(np.random.randn(n)) * 0.01)
    low = close * (1 - np.abs(np.random.randn(n)) * 0.01)
    open_p = close * (1 + np.random.randn(n) * 0.005)
    volume = np.random.randint(500000, 5000000, n).astype(float)
    amount = close * volume

    return pd.DataFrame({
        "date": dates,
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": amount,
    }).reset_index(drop=True)


@pytest.fixture
def trending_up_ohlcv():
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.linspace(10, 20, n)
    high = close * 1.01
    low = close * 0.99
    open_p = close * 0.998
    volume = np.ones(n) * 1000000
    return pd.DataFrame({
        "date": dates, "open": open_p, "high": high, "low": low,
        "close": close, "volume": volume, "amount": close * volume,
    }).reset_index(drop=True)


@pytest.fixture
def trending_down_ohlcv():
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.linspace(20, 10, n)
    high = close * 1.01
    low = close * 0.99
    open_p = close * 1.002
    volume = np.ones(n) * 1000000
    return pd.DataFrame({
        "date": dates, "open": open_p, "high": high, "low": low,
        "close": close, "volume": volume, "amount": close * volume,
    }).reset_index(drop=True)


@pytest.fixture
def sideways_ohlcv():
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    np.random.seed(42)
    close = 15 + np.random.randn(n) * 0.3
    high = close + 0.2
    low = close - 0.2
    open_p = close + np.random.randn(n) * 0.1
    volume = np.ones(n) * 1000000
    return pd.DataFrame({
        "date": dates, "open": open_p, "high": high, "low": low,
        "close": close, "volume": volume, "amount": close * volume,
    }).reset_index(drop=True)


@pytest.fixture
def event_bus():
    from core.events import EventBus
    return EventBus()


@pytest.fixture
def risk_manager():
    from core.risk_manager import EnhancedRiskManager
    return EnhancedRiskManager(initial_capital=1000000)


@pytest.fixture
def sample_kline_data():
    return [
        {"date": "2024-01-01", "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 1000000, "amount": 102000000.0},
        {"date": "2024-01-02", "open": 103.0, "high": 108.0, "low": 102.0, "close": 106.0, "volume": 1200000, "amount": 125000000.0},
        {"date": "2024-01-03", "open": 106.0, "high": 110.0, "low": 105.0, "close": 108.0, "volume": 1500000, "amount": 160000000.0},
        {"date": "2024-01-04", "open": 108.0, "high": 112.0, "low": 107.0, "close": 110.0, "volume": 1800000, "amount": 195000000.0},
        {"date": "2024-01-05", "open": 110.0, "high": 108.0, "low": 104.0, "close": 105.0, "volume": 2000000, "amount": 210000000.0},
    ]


@pytest.fixture
def sample_equity_curve():
    return [100000.0, 101000.0, 102500.0, 104000.0, 103000.0]


@pytest.fixture
def sample_returns():
    dates = pd.date_range("2024-01-01", periods=20, freq="D")
    return pd.Series(np.random.randn(20) * 0.02 + 0.001, index=dates)
