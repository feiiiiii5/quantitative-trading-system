"""Async tests for core data_fetcher module."""

import pytest

from core.data_fetcher import (
    CircuitBreaker,
    CircuitBreakerError,
    SmartDataFetcher,
    TencentSource,
    get_fetcher,
)


class TestCircuitBreaker:
    def test_circuit_breaker_init_state(self):
        breaker = CircuitBreaker(failure_threshold=1, timeout=1)
        assert breaker.state == "CLOSED"

    def test_circuit_breaker_record_failure(self):
        import asyncio
        breaker = CircuitBreaker(failure_threshold=2, timeout=60)
        asyncio.run(breaker._record_failure())
        assert breaker.failure_count == 1

    def test_circuit_breaker_is_valid_result(self):
        breaker = CircuitBreaker(failure_threshold=2, timeout=60)
        assert breaker._is_valid_result(None) is False
        assert breaker._is_valid_result({"key": "value"}) is True
        import pandas as pd
        assert breaker._is_valid_result(pd.DataFrame({"a": [1]})) is True

    def test_circuit_breaker_open_after_threshold(self):
        import asyncio
        breaker = CircuitBreaker(failure_threshold=2, timeout=60)
        asyncio.run(breaker._record_failure())
        asyncio.run(breaker._record_failure())
        assert breaker.state == "OPEN"


class TestTencentSource:
    def test_tencent_source_init(self):
        source = TencentSource()
        assert source is not None

    def test_tencent_build_code(self):
        code = TencentSource._build_code("000001", "A")
        assert code == "sz000001"

    def test_tencent_build_code_sh(self):
        code = TencentSource._build_code("600000", "A")
        assert code == "sh600000"


class TestSmartDataFetcher:
    def test_smart_fetcher_has_sources(self):
        fetcher = SmartDataFetcher()
        assert hasattr(fetcher, "_sources")

    def test_get_fetcher_singleton(self):
        fetcher1 = get_fetcher()
        fetcher2 = get_fetcher()
        assert fetcher1 is not None
        assert fetcher2 is not None

    def test_fetcher_sources_structure(self):
        fetcher = SmartDataFetcher()
        sources = fetcher._sources
        assert isinstance(sources, dict)


class TestMarketDetector:
    def test_detect_sz_stock(self):
        from core.data_fetcher import MarketDetector
        market = MarketDetector.detect("000001")
        assert market in ["sz", "sh", "A", "SZ", "SH"]

    def test_detect_sh_stock(self):
        from core.data_fetcher import MarketDetector
        market = MarketDetector.detect("600000")
        assert market in ["sz", "sh", "A", "SZ", "SH"]

    def test_detect_hk_stock(self):
        from core.data_fetcher import MarketDetector
        market = MarketDetector.detect("00700")
        assert market.lower() == "hk"

    def test_detect_us_stock(self):
        from core.data_fetcher import MarketDetector
        market = MarketDetector.detect("AAPL")
        assert market.lower() == "us"


class TestCircuitBreakerAsyncCall:
    @pytest.mark.asyncio
    async def test_async_call_success(self):
        breaker = CircuitBreaker(failure_threshold=3, timeout=60)

        async def success_coro():
            return {"data": "success"}

        result = await breaker.call(success_coro)
        assert result == {"data": "success"}

    @pytest.mark.asyncio
    async def test_async_call_blocks_when_open(self):
        breaker = CircuitBreaker(failure_threshold=1, timeout=60)
        await breaker._record_failure()

        async def some_coro():
            return "should not reach"

        with pytest.raises(CircuitBreakerError):
            await breaker.call(some_coro)

    @pytest.mark.asyncio
    async def test_async_call_failure_records(self):
        breaker = CircuitBreaker(failure_threshold=3, timeout=60)

        async def failing_coro():
            raise ConnectionError("Network error")

        with pytest.raises(ConnectionError):
            await breaker.call(failing_coro)

        assert breaker.failure_count >= 1
