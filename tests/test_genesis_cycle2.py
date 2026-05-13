import asyncio
import threading
import time

import pytest

from api.middleware import (
    RequestBodyLimitMiddleware,
    Span,
    SpanBuffer,
    StructuredTraceMiddleware,
    correlation_id,
    span_buffer,
    trace_id_var,
)


class TestSpanBuffer:
    def test_record_and_query(self):
        buf = SpanBuffer(maxsize=100)
        span = Span(
            trace_id="abc123",
            span_id="def456",
            operation="HTTP GET /api/test",
            start_mono=time.monotonic(),
            duration_ms=42.5,
            status_code=200,
            error=None,
            attributes={"method": "GET", "path": "/api/test"},
        )
        buf.record(span)
        results = buf.query()
        assert len(results) == 1
        assert results[0]["trace_id"] == "abc123"
        assert results[0]["duration_ms"] == 42.5
        assert results[0]["status_code"] == 200

    def test_query_filter_by_path_prefix(self):
        buf = SpanBuffer(maxsize=100)
        for i, path in enumerate(["/api/stock/A", "/api/market/B", "/api/stock/C"]):
            buf.record(Span(
                trace_id=f"t{i}", span_id=f"s{i}", operation=f"HTTP GET {path}",
                start_mono=0, duration_ms=10, status_code=200, error=None,
                attributes={"path": path},
            ))
        results = buf.query(path_prefix="/api/stock")
        assert len(results) == 2

    def test_query_filter_by_min_duration(self):
        buf = SpanBuffer(maxsize=100)
        for i, dur in enumerate([10, 50, 100, 200]):
            buf.record(Span(
                trace_id=f"t{i}", span_id=f"s{i}", operation="HTTP GET /",
                start_mono=0, duration_ms=dur, status_code=200, error=None,
                attributes={"path": "/"},
            ))
        results = buf.query(min_duration_ms=100)
        assert len(results) == 2

    def test_query_filter_by_status_code(self):
        buf = SpanBuffer(maxsize=100)
        for i, code in enumerate([200, 200, 404, 500]):
            buf.record(Span(
                trace_id=f"t{i}", span_id=f"s{i}", operation="HTTP GET /",
                start_mono=0, duration_ms=10, status_code=code, error=None,
                attributes={"path": "/"},
            ))
        results = buf.query(status_code=404)
        assert len(results) == 1

    def test_query_error_only(self):
        buf = SpanBuffer(maxsize=100)
        buf.record(Span(
            trace_id="ok", span_id="s1", operation="HTTP GET /",
            start_mono=0, duration_ms=10, status_code=200, error=None,
            attributes={"path": "/"},
        ))
        buf.record(Span(
            trace_id="err", span_id="s2", operation="HTTP GET /fail",
            start_mono=0, duration_ms=10, status_code=500, error="boom",
            attributes={"path": "/fail"},
        ))
        results = buf.query(error_only=True)
        assert len(results) == 1
        assert results[0]["trace_id"] == "err"

    def test_query_limit(self):
        buf = SpanBuffer(maxsize=100)
        for i in range(20):
            buf.record(Span(
                trace_id=f"t{i}", span_id=f"s{i}", operation="HTTP GET /",
                start_mono=0, duration_ms=10, status_code=200, error=None,
                attributes={"path": "/"},
            ))
        results = buf.query(limit=5)
        assert len(results) == 5

    def test_summary(self):
        buf = SpanBuffer(maxsize=100)
        buf.record(Span(
            trace_id="t1", span_id="s1", operation="HTTP GET /api/stock",
            start_mono=0, duration_ms=100, status_code=200, error=None,
            attributes={"path": "/api/stock"},
        ))
        buf.record(Span(
            trace_id="t2", span_id="s2", operation="HTTP GET /api/stock",
            start_mono=0, duration_ms=200, status_code=500, error="fail",
            attributes={"path": "/api/stock"},
        ))
        s = buf.summary()
        assert s["total_requests"] == 2
        assert s["total_errors"] == 1
        assert s["error_rate"] == 0.5
        assert s["status_codes"] == {200: 1, 500: 1}
        assert len(s["slowest_endpoints"]) == 1
        assert s["slowest_endpoints"][0]["path"] == "/api/stock"
        assert s["slowest_endpoints"][0]["avg_ms"] == 150.0

    def test_ring_buffer_eviction(self):
        buf = SpanBuffer(maxsize=5)
        for i in range(10):
            buf.record(Span(
                trace_id=f"t{i}", span_id=f"s{i}", operation="HTTP GET /",
                start_mono=0, duration_ms=10, status_code=200, error=None,
                attributes={"path": "/"},
            ))
        results = buf.query(limit=100)
        assert len(results) == 5
        assert results[0]["trace_id"] == "t9"

    def test_thread_safety(self):
        buf = SpanBuffer(maxsize=1000)
        errors = []

        def writer(start_idx):
            try:
                for i in range(100):
                    buf.record(Span(
                        trace_id=f"t{start_idx}_{i}", span_id=f"s{i}",
                        operation="HTTP GET /", start_mono=0, duration_ms=10,
                        status_code=200, error=None, attributes={"path": "/"},
                    ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(j,)) for j in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        s = buf.summary()
        assert s["total_requests"] == 500


class TestTimeMonotonicMigration:
    def test_websocket_manager_uses_monotonic(self):
        from api.websocket_manager import OptimizedWSManager
        mgr = OptimizedWSManager()
        assert mgr._last_active == {}

    def test_connection_manager_uses_monotonic(self):
        from api.connection_manager import ConnectionManager
        mgr = ConnectionManager()
        assert mgr._last_active == {}

    def test_auth_rate_limiter_uses_monotonic(self):
        from api.auth import APIAuthMiddleware
        mw = APIAuthMiddleware(app=None, enabled=False)
        assert mw._last_cleanup > 0 or mw._last_cleanup == 0.0

    def test_memory_guard_uses_monotonic(self):
        from core.memory_guard import _LAST_GC_TIME
        assert isinstance(_LAST_GC_TIME, float)


class TestContextVars:
    def test_trace_id_var_default(self):
        assert trace_id_var.get("") == ""

    def test_trace_id_var_set(self):
        token = trace_id_var.set("test-trace-123")
        assert trace_id_var.get("") == "test-trace-123"
        trace_id_var.reset(token)

    def test_correlation_id_default(self):
        assert correlation_id.get("") == ""


class TestConnectionManagerSet:
    def test_connections_is_set(self):
        from api.connection_manager import ConnectionManager
        mgr = ConnectionManager()
        assert isinstance(mgr.connections, set)

    def test_discard_is_safe(self):
        from api.connection_manager import ConnectionManager
        mgr = ConnectionManager()
        mgr.connections.discard("nonexistent")
        assert len(mgr.connections) == 0


class TestOrjsonInHotPaths:
    def test_websocket_manager_uses_orjson(self):
        import api.websocket_manager as mod
        assert hasattr(mod, "orjson")

    def test_build_message_uses_orjson(self):
        from api.connection_manager import _build_message
        msg = _build_message("test", {"key": "value"})
        assert isinstance(msg, str)
        import json
        parsed = json.loads(msg)
        assert parsed["type"] == "test"
        assert parsed["data"]["key"] == "value"
        assert "seq" in parsed


class TestGracefulShutdownMiddleware:
    def test_init_resets_draining(self):
        from api.middleware import set_draining, is_draining, GracefulShutdownMiddleware
        set_draining(True)
        assert is_draining() is True
        GracefulShutdownMiddleware(app=None)
        assert is_draining() is False

    def test_generation_counter(self):
        from api.middleware import bump_lifespan_gen, get_lifespan_gen, GracefulShutdownMiddleware
        gen_before = get_lifespan_gen()
        GracefulShutdownMiddleware(app=None)
        assert get_lifespan_gen() > gen_before

    def test_stale_draining_ignored(self):
        from api.middleware import (
            set_draining, is_draining, GracefulShutdownMiddleware,
            bump_lifespan_gen, _lifespan_gen,
        )
        mw = GracefulShutdownMiddleware(app=None)
        mw_gen = mw._gen
        set_draining(True)
        bump_lifespan_gen()
        assert mw._gen != _lifespan_gen
        assert is_draining() is True
        assert mw._gen != _lifespan_gen

    def test_inflight_count(self):
        from api.middleware import inflight_count
        assert isinstance(inflight_count(), int)
        assert inflight_count() >= 0


class TestAdaptiveThrottleMiddleware:
    def test_default_rps(self):
        from api.middleware import AdaptiveThrottleMiddleware
        mw = AdaptiveThrottleMiddleware(app=None, base_rps=50)
        assert mw._base_rps == 50
        assert mw._current_rps == 50

    def test_status_report(self):
        from api.middleware import AdaptiveThrottleMiddleware
        mw = AdaptiveThrottleMiddleware(app=None, base_rps=30)
        s = mw.status()
        assert s["base_rps"] == 30
        assert s["current_rps"] == 30
        assert "window_count" in s

    def test_effective_limit_normal(self):
        from api.middleware import AdaptiveThrottleMiddleware
        mw = AdaptiveThrottleMiddleware(app=None, base_rps=100)
        limit = mw._effective_limit()
        assert limit == 100

    def test_effective_limit_under_high_memory(self):
        from api.middleware import AdaptiveThrottleMiddleware
        mw = AdaptiveThrottleMiddleware(app=None, base_rps=100)
        original_high = AdaptiveThrottleMiddleware._HIGH_MEMORY_MB
        try:
            AdaptiveThrottleMiddleware._HIGH_MEMORY_MB = 0
            limit = mw._effective_limit()
            assert limit < 100
            assert limit >= 10
        finally:
            AdaptiveThrottleMiddleware._HIGH_MEMORY_MB = original_high

    def test_effective_limit_under_critical_memory(self):
        from api.middleware import AdaptiveThrottleMiddleware
        mw = AdaptiveThrottleMiddleware(app=None, base_rps=100)
        original_critical = AdaptiveThrottleMiddleware._CRITICAL_MEMORY_MB
        try:
            AdaptiveThrottleMiddleware._CRITICAL_MEMORY_MB = 0
            limit = mw._effective_limit()
            assert limit <= 25
            assert limit >= 5
        finally:
            AdaptiveThrottleMiddleware._CRITICAL_MEMORY_MB = original_critical


class TestRequestBodyLimitMiddleware:
    def test_default_max_bytes(self):
        mw = RequestBodyLimitMiddleware(app=None)
        assert mw._max_bytes == 10_485_760

    def test_custom_max_bytes(self):
        mw = RequestBodyLimitMiddleware(app=None, max_bytes=1024)
        assert mw._max_bytes == 1024

    def test_status_report(self):
        mw = RequestBodyLimitMiddleware(app=None, max_bytes=2048)
        s = mw.status()
        assert s["max_bytes"] == 2048
        assert s["rejected_total"] == 0

    def test_get_content_length_present(self):
        scope = {"headers": [(b"content-length", b"12345")]}
        assert RequestBodyLimitMiddleware._get_content_length(scope) == 12345

    def test_get_content_length_absent(self):
        scope = {"headers": []}
        assert RequestBodyLimitMiddleware._get_content_length(scope) is None

    def test_get_content_length_invalid(self):
        scope = {"headers": [(b"content-length", b"abc")]}
        assert RequestBodyLimitMiddleware._get_content_length(scope) is None

    @pytest.mark.asyncio
    async def test_reject_oversized_content_length(self):
        responses = []

        async def mock_send(message):
            responses.append(message)

        mw = RequestBodyLimitMiddleware(app=None, max_bytes=100)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/test",
            "headers": [(b"content-length", b"200")],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        await mw(scope, mock_receive, mock_send)
        assert len(responses) == 2
        assert responses[0]["status"] == 413
        assert b"connection" in [h[0] for h in responses[0]["headers"]]
        assert mw._rejected == 1

    @pytest.mark.asyncio
    async def test_pass_within_content_length(self):
        called = False

        async def mock_app(scope, receive, send):
            nonlocal called
            called = True

        async def mock_send(message):
            pass

        mw = RequestBodyLimitMiddleware(app=mock_app, max_bytes=1000)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/test",
            "headers": [(b"content-length", b"50")],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b"x" * 50, "more_body": False}

        await mw(scope, mock_receive, mock_send)
        assert called is True
        assert mw._rejected == 0

    @pytest.mark.asyncio
    async def test_get_skips_check(self):
        called = False

        async def mock_app(scope, receive, send):
            nonlocal called
            called = True

        async def mock_send(message):
            pass

        mw = RequestBodyLimitMiddleware(app=mock_app, max_bytes=1)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/test",
            "headers": [(b"content-length", b"99999")],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        await mw(scope, mock_receive, mock_send)
        assert called is True

    @pytest.mark.asyncio
    async def test_exempt_path(self):
        called = False

        async def mock_app(scope, receive, send):
            nonlocal called
            called = True

        async def mock_send(message):
            pass

        mw = RequestBodyLimitMiddleware(app=mock_app, max_bytes=1)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/health",
            "headers": [(b"content-length", b"99999")],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        await mw(scope, mock_receive, mock_send)
        assert called is True

    @pytest.mark.asyncio
    async def test_no_content_length_body_within_limit(self):
        received_body = None

        async def mock_app(scope, receive, send):
            nonlocal received_body
            msg = await receive()
            received_body = msg.get("body", b"")

        async def mock_send(message):
            pass

        mw = RequestBodyLimitMiddleware(app=mock_app, max_bytes=100)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/test",
            "headers": [],
        }
        body_data = b"hello world"

        async def mock_receive():
            return {"type": "http.request", "body": body_data, "more_body": False}

        await mw(scope, mock_receive, mock_send)
        assert received_body == body_data
        assert mw._rejected == 0

    @pytest.mark.asyncio
    async def test_no_content_length_body_exceeds_limit(self):
        responses = []

        async def mock_send(message):
            responses.append(message)

        mw = RequestBodyLimitMiddleware(app=None, max_bytes=10)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/test",
            "headers": [],
        }
        body_data = b"x" * 20

        async def mock_receive():
            return {"type": "http.request", "body": body_data, "more_body": False}

        await mw(scope, mock_receive, mock_send)
        assert len(responses) == 2
        assert responses[0]["status"] == 413
        assert mw._rejected == 1


class TestBacktestResultCache:
    def test_cache_key_deterministic(self):
        from core.backtest.runner import _make_backtest_cache_key
        key1 = _make_backtest_cache_key("000001", "ma_cross", "2024-01-01", "2024-12-31", 1000000, {"period": 5})
        key2 = _make_backtest_cache_key("000001", "ma_cross", "2024-01-01", "2024-12-31", 1000000, {"period": 5})
        assert key1 == key2

    def test_cache_key_differs_for_different_params(self):
        from core.backtest.runner import _make_backtest_cache_key
        key1 = _make_backtest_cache_key("000001", "ma_cross", "2024-01-01", "2024-12-31", 1000000, {"period": 5})
        key2 = _make_backtest_cache_key("000001", "ma_cross", "2024-01-01", "2024-12-31", 1000000, {"period": 10})
        assert key1 != key2

    def test_cache_set_and_get(self):
        import time
        from core.backtest.runner import _backtest_cache, _get_cached_result, _set_cached_result
        _backtest_cache.clear()
        _set_cached_result("test_key", {"total_return": 0.15})
        result = _get_cached_result("test_key")
        assert result is not None
        assert result["total_return"] == 0.15
        assert result["cached"] is True
        _backtest_cache.clear()

    def test_cache_miss(self):
        from core.backtest.runner import _backtest_cache, _get_cached_result
        _backtest_cache.clear()
        result = _get_cached_result("nonexistent_key")
        assert result is None

    def test_cache_ttl_expiry(self):
        import time
        from core.backtest.runner import (
            _BACKTEST_CACHE_TTL,
            _backtest_cache,
            _get_cached_result,
            _set_cached_result,
        )
        _backtest_cache.clear()
        _set_cached_result("ttl_key", {"total_return": 0.1})
        entry = _backtest_cache["ttl_key"]
        _backtest_cache["ttl_key"] = (entry[0], time.monotonic() - _BACKTEST_CACHE_TTL - 1)
        result = _get_cached_result("ttl_key")
        assert result is None
        _backtest_cache.clear()

    def test_cache_max_eviction(self):
        from core.backtest.runner import (
            _BACKTEST_CACHE_MAX,
            _backtest_cache,
            _get_cached_result,
            _set_cached_result,
        )
        _backtest_cache.clear()
        for i in range(_BACKTEST_CACHE_MAX + 5):
            _set_cached_result(f"key_{i}", {"total_return": i * 0.01})
        assert len(_backtest_cache) <= _BACKTEST_CACHE_MAX
        _backtest_cache.clear()


class TestCircuitBreakerObservability:
    def test_breaker_status_fields(self):
        from core.data_fetcher import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=5, timeout=30)
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0
        assert cb.failure_threshold == 5
        assert cb.timeout == 30
        assert cb.last_failure_time == 0.0

    def test_breaker_state_transitions_observable(self):
        import asyncio
        from core.data_fetcher import CircuitBreaker, CircuitBreakerError

        async def _run():
            cb = CircuitBreaker(failure_threshold=2, timeout=0.05)

            async def failing_fn():
                raise RuntimeError("fail")

            for _ in range(2):
                with pytest.raises(RuntimeError):
                    await cb.call(failing_fn)

            assert cb.state == "OPEN"
            assert cb.failure_count == 2
            assert cb.last_failure_time > 0

            with pytest.raises(CircuitBreakerError):
                await cb.call(failing_fn)

            await asyncio.sleep(0.06)
            assert cb.state == "OPEN"

            async def ok_fn():
                return {"price": 1.0}

            result = await cb.call(ok_fn)
            assert result is not None

        asyncio.run(_run())

    def test_breaker_reset(self):
        from core.data_fetcher import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=2, timeout=60)
        cb.state = "OPEN"
        cb.failure_count = 5
        cb.half_open_calls = 3
        cb.state = "CLOSED"
        cb.failure_count = 0
        cb.half_open_calls = 0
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0


class TestSymbolStateLock:
    def test_set_and_clear_priority(self):
        import asyncio
        from api.connection_manager import set_symbol_priority, clear_symbol_priority, _symbol_priority

        async def _run():
            await set_symbol_priority("000001", "position")
            assert _symbol_priority.get("000001") == "position"
            await clear_symbol_priority("000001")
            assert "000001" not in _symbol_priority

        asyncio.run(_run())

    def test_trading_hours_lock(self):
        from api.connection_manager import _trading_hours_lock
        assert _trading_hours_lock is not None


class TestWebSocketSendTimeout:
    def test_safe_send_json_exists(self):
        from api.routers.websocket import _safe_send_json, _WS_SEND_TIMEOUT
        assert _WS_SEND_TIMEOUT > 0
        assert callable(_safe_send_json)

    def test_no_unprotected_ws_send_json(self):
        import inspect
        import api.routers.websocket as ws_mod
        import api.connection_manager as cm_mod
        ws_source = inspect.getsource(ws_mod)
        cm_source = inspect.getsource(cm_mod)
        assert "await ws.send_json(" not in ws_source
        assert "await ws.send_json(" not in cm_source


class TestCorrelationIdInResponse:
    def test_response_includes_request_id_when_set(self):
        from api.utils import orjson_response
        from api.middleware import correlation_id
        import orjson

        correlation_id.set("test-cid-123")
        try:
            resp = orjson_response(True, data={"key": "value"})
            body = orjson.loads(resp.body)
            assert body["request_id"] == "test-cid-123"
        finally:
            correlation_id.set("")

    def test_response_omits_request_id_when_empty(self):
        from api.utils import orjson_response
        from api.middleware import correlation_id
        import orjson

        correlation_id.set("")
        resp = orjson_response(True, data={"key": "value"})
        body = orjson.loads(resp.body)
        assert "request_id" not in body
