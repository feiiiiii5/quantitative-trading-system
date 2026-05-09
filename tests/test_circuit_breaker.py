import asyncio
import pytest

from core.data_fetcher import CircuitBreaker, CircuitBreakerError


class TestCircuitBreaker:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker()
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_successful_call_stays_closed(self):
        cb = CircuitBreaker()
        async def ok_func():
            return {"data": 1}
        result = await cb.call(ok_func)
        assert result == {"data": 1}
        assert cb.state == "CLOSED"

    @pytest.mark.asyncio
    async def test_failures_open_circuit(self):
        cb = CircuitBreaker(failure_threshold=3, timeout=10)
        async def fail_func():
            raise RuntimeError("fail")
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(fail_func)
        assert cb.state == "OPEN"
        assert cb.failure_count >= 3

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_calls(self):
        cb = CircuitBreaker(failure_threshold=2, timeout=60)
        async def fail_func():
            raise RuntimeError("fail")
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail_func)
        assert cb.state == "OPEN"
        with pytest.raises(CircuitBreakerError):
            await cb.call(fail_func)

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, timeout=0.01)
        async def fail_func():
            raise RuntimeError("fail")
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail_func)
        assert cb.state == "OPEN"
        await asyncio.sleep(0.02)
        async def ok_func():
            return {"ok": True}
        result = await cb.call(ok_func)
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_none_result_counts_as_failure(self):
        cb = CircuitBreaker(failure_threshold=3, timeout=60)
        async def none_func():
            return None
        for _ in range(3):
            await cb.call(none_func)
        assert cb.state == "OPEN"

    @pytest.mark.asyncio
    async def test_valid_dict_result_resets_failures(self):
        cb = CircuitBreaker(failure_threshold=3, timeout=60)
        async def fail_func():
            raise RuntimeError("fail")
        with pytest.raises(RuntimeError):
            await cb.call(fail_func)
        assert cb.failure_count == 1
        async def ok_func():
            return {"data": 1}
        await cb.call(ok_func)
        assert cb.failure_count == 0
        assert cb.state == "CLOSED"
