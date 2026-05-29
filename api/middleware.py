from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
import uuid
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

_draining: bool = False
_inflight: int = 0
_inflight_lock = threading.Lock()
_drain_event: asyncio.Event | None = None
_lifespan_gen: int = 0


def is_draining() -> bool:
    return _draining


def set_draining(value: bool) -> None:
    global _draining, _drain_event
    _draining = value
    if not value:
        _drain_event = None


def bump_lifespan_gen() -> int:
    global _lifespan_gen
    _lifespan_gen += 1
    return _lifespan_gen


def get_lifespan_gen() -> int:
    return _lifespan_gen


def inflight_count() -> int:
    return _inflight


def get_drain_event() -> asyncio.Event:
    global _drain_event
    if _drain_event is None:
        _drain_event = asyncio.Event()
    return _drain_event

logger = logging.getLogger(__name__)

SLOW_THRESHOLD_MS = 500

_DEDUP_PATHS = frozenset({
    "/api/backtest/run",
    "/api/backtest/optimize",
    "/api/backtest/walk-forward",
    "/api/market/realtime-batch",
    "/api/portfolio/risk-dashboard",
})
_DEDUP_TTL = 30.0
_pending: dict[str, asyncio.Future] = {}


@dataclass(slots=True)
class Span:
    trace_id: str
    span_id: str
    operation: str
    start_mono: float
    duration_ms: float
    status_code: int
    error: str | None
    attributes: dict = field(default_factory=dict)


class SpanBuffer:
    _MAX_SPANS = 4096

    def __init__(self, maxsize: int = 4096) -> None:
        self._maxsize = maxsize
        self._spans: deque[Span] = deque(maxlen=maxsize)
        self._lock = threading.Lock()
        self._total_requests = 0
        self._total_errors = 0
        self._status_counts: dict[int, int] = {}
        self._path_latency_sum: dict[str, float] = {}
        self._path_latency_count: dict[str, int] = {}

    def record(self, span: Span) -> None:
        with self._lock:
            self._spans.append(span)
            self._total_requests += 1
            if span.status_code >= 400:
                self._total_errors += 1
            self._status_counts[span.status_code] = self._status_counts.get(span.status_code, 0) + 1
            path = span.attributes.get("path", "")
            if path:
                self._path_latency_sum[path] = self._path_latency_sum.get(path, 0.0) + span.duration_ms
                self._path_latency_count[path] = self._path_latency_count.get(path, 0) + 1

    def query(
        self,
        limit: int = 100,
        path_prefix: str = "",
        min_duration_ms: float = 0,
        status_code: int | None = None,
        error_only: bool = False,
    ) -> list[dict]:
        with self._lock:
            results = []
            for span in reversed(self._spans):
                if error_only and span.error is None and span.status_code < 400:
                    continue
                if path_prefix and not span.attributes.get("path", "").startswith(path_prefix):
                    continue
                if min_duration_ms > 0 and span.duration_ms < min_duration_ms:
                    continue
                if status_code is not None and span.status_code != status_code:
                    continue
                results.append({
                    "trace_id": span.trace_id,
                    "span_id": span.span_id,
                    "operation": span.operation,
                    "duration_ms": round(span.duration_ms, 2),
                    "status_code": span.status_code,
                    "error": span.error,
                    "attributes": span.attributes,
                })
                if len(results) >= limit:
                    break
            return results

    def summary(self) -> dict:
        with self._lock:
            top_paths = sorted(
                (
                    (p, self._path_latency_sum[p] / c)
                    for p, c in self._path_latency_count.items()
                    if c > 0
                ),
                key=lambda x: x[1],
                reverse=True,
            )[:10]
            return {
                "total_requests": self._total_requests,
                "total_errors": self._total_errors,
                "error_rate": round(self._total_errors / self._total_requests, 4) if self._total_requests else 0,
                "status_codes": dict(self._status_counts),
                "slowest_endpoints": [
                    {"path": p, "avg_ms": round(avg, 2)}
                    for p, avg in top_paths
                ],
                "buffer_size": len(self._spans),
                "buffer_capacity": self._maxsize,
            }


span_buffer = SpanBuffer()


def _request_fingerprint(scope: dict) -> str | None:
    path = scope.get("path", "")
    if path not in _DEDUP_PATHS:
        return None
    method = scope.get("method", "")
    qs = scope.get("query_string", b"").decode("utf-8", errors="replace")
    headers = scope.get("headers", [])
    idempotency_key = None
    for k, v in headers:
        if k == b"x-idempotency-key":
            idempotency_key = v.decode("utf-8", errors="replace")
            break
    raw = f"{method}:{path}:{qs}"
    if idempotency_key:
        raw += f":ik={idempotency_key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class RequestDedupMiddleware:
    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        fp = _request_fingerprint(scope)
        if fp is None:
            await self._app(scope, receive, send)
            return

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        existing = _pending.get(fp)
        if existing is not None and not existing.done():
            logger.debug("Request dedup: waiting for in-flight %s", fp[:8])
            try:
                result = await asyncio.wait_for(asyncio.shield(existing), timeout=_DEDUP_TTL)
                if isinstance(result, dict) and "status" in result and "headers" in result and "body" in result:
                    await send(result["status"])
                    await send(result["body"])
                    return
            except TimeoutError:
                logger.warning("Request dedup timeout for %s, proceeding normally", fp[:8])
            except Exception:
                pass
            _pending.pop(fp, None)

        _pending[fp] = fut
        captured_status = None
        captured_body = None

        async def _capturing_send(message):
            nonlocal captured_status, captured_body
            if message["type"] == "http.response.start":
                captured_status = message
            elif message["type"] == "http.response.body":
                captured_body = message
            await send(message)

        try:
            await self._app(scope, receive, _capturing_send)
            if captured_status is not None and captured_body is not None:
                fut.set_result({
                    "status": captured_status,
                    "body": captured_body,
                })
            else:
                fut.set_result(None)
        except Exception as e:
            if not fut.done():
                fut.set_exception(e)
            raise
        finally:
            _pending.pop(fp, None)


class StructuredTraceMiddleware:
    def __init__(self, app, max_spans: int = 4096):
        self._app = app
        self._buffer = span_buffer

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in ("/api/health", "/favicon.ico", "/docs", "/openapi.json") or path.startswith("/api/ws/"):
            await self._app(scope, receive, send)
            return

        tid = None
        for k, v in scope.get("headers", []):
            if k == b"x-trace-id":
                tid = v.decode("utf-8", errors="replace")
                break
        if not tid:
            tid = uuid.uuid4().hex[:16]
        trace_id_var.set(tid)

        method = scope.get("method", "")
        operation = f"HTTP {method} {path}"
        span_id = uuid.uuid4().hex[:12]
        start = time.monotonic()

        response_status = 200
        error_msg = None

        async def _send(message):
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message.get("status", 200)
            await send(message)

        try:
            await self._app(scope, receive, _send)
        except Exception as e:
            error_msg = str(e)[:256]
            response_status = 500
            raise
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            qs = scope.get("query_string", b"").decode("utf-8", errors="replace")
            user_agent = ""
            for k, v in scope.get("headers", []):
                if k == b"user-agent":
                    user_agent = v.decode("utf-8", errors="replace")[:128]
                    break
            span = Span(
                trace_id=tid,
                span_id=span_id,
                operation=operation,
                start_mono=start,
                duration_ms=duration_ms,
                status_code=response_status,
                error=error_msg,
                attributes={
                    "method": method,
                    "path": path,
                    "query_string": qs[:256] if qs else "",
                    "user_agent": user_agent,
                    "correlation_id": correlation_id.get(""),
                },
            )
            self._buffer.record(span)

            if duration_ms > SLOW_THRESHOLD_MS:
                logger.warning(
                    "TRACE SLOW %s %s %.0fms [%s] status=%d",
                    method, path, duration_ms, tid, response_status,
                )
            elif response_status >= 500:
                logger.error(
                    "TRACE ERROR %s %s %.0fms [%s] status=%d err=%s",
                    method, path, duration_ms, tid, response_status,
                    error_msg or "",
                )


class RequestValidationMiddleware:
    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in ("/api/health", "/favicon.ico") or path.startswith("/api/ws/"):
            await self._app(scope, receive, send)
            return

        req_id = None
        for k, v in scope.get("headers", []):
            if k == b"x-request-id":
                req_id = v.decode("utf-8", errors="replace")
                break
        cid = req_id or uuid.uuid4().hex[:16]
        correlation_id.set(cid)

        start = time.monotonic()

        response_started = False
        response_status = 200

        async def _send(message):
            nonlocal response_started, response_status
            if message["type"] == "http.response.start":
                response_started = True
                response_status = message.get("status", 200)
            await send(message)

        try:
            await self._app(scope, receive, _send)
        except Exception as e:
            logger.error(
                "Unhandled: %s %s -> %s",
                scope.get("method", ""),
                path,
                e,
            )
            if not response_started:
                import orjson
                body = orjson.dumps({"success": False, "error": "Internal server error", "code": 500})
                await send({
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        [b"content-type", b"application/json"],
                    ],
                })
                await send({
                    "type": "http.response.body",
                    "body": body,
                })
            return

        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > SLOW_THRESHOLD_MS:
            logger.warning(
                "SLOW %s %s %.0fms [%s]",
                scope.get("method", ""),
                path,
                elapsed_ms,
                cid,
            )


class GracefulShutdownMiddleware:
    def __init__(self, app, drain_timeout: float = 30.0):
        self._app = app
        self._drain_timeout = drain_timeout
        self._gen = bump_lifespan_gen()
        set_draining(False)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        if _draining and self._gen == _lifespan_gen and scope["type"] == "http":
            path = scope.get("path", "")
            if path not in ("/api/health", "/api/system/metrics", "/api/system/drain-status", "/"):
                import orjson

                from api.errors import AppError, ErrorCode
                err = AppError(
                    error_code=ErrorCode.SYSTEM_SHUTTING_DOWN,
                    message="Server is shutting down",
                    retry_after=5,
                )
                body = orjson.dumps(err.to_response())
                await send({
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        [b"content-type", b"application/json"],
                        [b"retry-after", b"5"],
                    ],
                })
                await send({
                    "type": "http.response.body",
                    "body": body,
                })
                return

        with _inflight_lock:
            global _inflight
            _inflight += 1

        try:
            await self._app(scope, receive, send)
        finally:
            with _inflight_lock:
                _inflight -= 1
                if _draining and self._gen == _lifespan_gen and _inflight == 0:
                    evt = _drain_event
                    if evt is not None:
                        evt.set()


class RequestBodyLimitMiddleware:
    _BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
    _EXEMPT_PATHS = frozenset({
        "/api/health", "/health", "/", "/favicon.ico", "/docs",
        "/openapi.json", "/redoc",
    })
    _EXEMPT_PREFIXES = ("/api/ws/", "/static/", "/assets/")

    def __init__(self, app, max_bytes: int = 10_485_760):
        self._app = app
        self._max_bytes = max_bytes
        self._rejected = 0
        self._lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        method = scope.get("method", "")
        if method not in self._BODY_METHODS:
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self._EXEMPT_PATHS or any(path.startswith(p) for p in self._EXEMPT_PREFIXES):
            await self._app(scope, receive, send)
            return

        content_length = self._get_content_length(scope)
        if content_length is not None:
            if content_length > self._max_bytes:
                with self._lock:
                    self._rejected += 1
                await self._send_413(send)
                return
            await self._app(scope, receive, send)
            return

        body_parts: list[bytes] = []
        total_size = 0
        more_body = True

        while more_body:
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                total_size += len(chunk)
                body_parts.append(chunk)
                more_body = message.get("more_body", False)
                if total_size > self._max_bytes:
                    with self._lock:
                        self._rejected += 1
                    await self._send_413(send)
                    return

        full_body = b"".join(body_parts)
        received = False

        async def _replay_receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": full_body, "more_body": False}
            return await receive()

        await self._app(scope, _replay_receive, send)

    @staticmethod
    def _get_content_length(scope: dict) -> int | None:
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    return int(v)
                except ValueError:
                    return None
        return None

    async def _send_413(self, send) -> None:
        import orjson

        from api.errors import AppError, ErrorCode
        err = AppError(
            error_code=ErrorCode.VALIDATION_BODY_TOO_LARGE,
            message=f"Request body exceeds {self._max_bytes} byte limit",
            details={"max_bytes": self._max_bytes},
        )
        body = orjson.dumps(err.to_response())
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                [b"content-type", b"application/json"],
                [b"connection", b"close"],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })

    def status(self) -> dict:
        with self._lock:
            return {
                "max_bytes": self._max_bytes,
                "rejected_total": self._rejected,
            }


class AdaptiveThrottleMiddleware:
    _HIGH_MEMORY_MB = 1200
    _CRITICAL_MEMORY_MB = 1600
    _HIGH_INFLIGHT = 50
    _CRITICAL_INFLIGHT = 100
    _SLOW_P95_MS = 3000

    def __init__(self, app, base_rps: int = 100):
        self._app = app
        self._base_rps = base_rps
        self._current_rps = base_rps
        self._lock = threading.Lock()
        self._window_start = time.monotonic()
        self._window_count = 0
        self._last_adjust = time.monotonic()
        self._adjust_interval = 5.0

    def _effective_limit(self) -> int:
        from core.memory_guard import get_memory_usage
        try:
            mem = get_memory_usage()
            rss_mb = mem.get("rss_mb", 0)
        except Exception:
            rss_mb = 0

        inflight = inflight_count()
        limit = self._base_rps

        if rss_mb > self._CRITICAL_MEMORY_MB or inflight > self._CRITICAL_INFLIGHT:
            limit = max(self._base_rps // 4, 5)
        elif rss_mb > self._HIGH_MEMORY_MB or inflight > self._HIGH_INFLIGHT:
            limit = max(self._base_rps // 2, 10)

        buf_summary = span_buffer.summary()
        error_rate = buf_summary.get("error_rate", 0)
        if error_rate > 0.2:
            limit = max(limit // 2, 5)

        return limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in ("/api/health", "/api/system/metrics", "/api/system/drain-status", "/",
                     "/favicon.ico", "/docs", "/openapi.json"):
            await self._app(scope, receive, send)
            return

        now = time.monotonic()
        with self._lock:
            if now - self._window_start >= 1.0:
                self._window_start = now
                self._window_count = 0

            if now - self._last_adjust >= self._adjust_interval:
                self._current_rps = self._effective_limit()
                self._last_adjust = now

            if self._window_count >= self._current_rps:
                import orjson

                from api.errors import AppError, ErrorCode
                err = AppError(
                    error_code=ErrorCode.RATE_LIMIT_SERVER_LOAD,
                    message="Server load high, please retry",
                    retry_after=2,
                    details={"current_rps": self._current_rps},
                )
                body = orjson.dumps(err.to_response())
                await send({
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        [b"content-type", b"application/json"],
                        [b"retry-after", b"2"],
                    ],
                })
                await send({
                    "type": "http.response.body",
                    "body": body,
                })
                return

            self._window_count += 1

        await self._app(scope, receive, send)

    def status(self) -> dict:
        with self._lock:
            return {
                "base_rps": self._base_rps,
                "current_rps": self._current_rps,
                "window_count": self._window_count,
                "effective_limit": self._current_rps,
            }


class ETagCacheMiddleware:
    _CACHEABLE_PREFIXES = ("/api/market/", "/api/stock/", "/api/perf/", "/api/portfolio/summary", "/api/strategy/list")
    _DEFAULT_TTL = 5.0
    _MAX_ENTRIES = 256
    _instance: ETagCacheMiddleware | None = None

    def __init__(self, app, ttl: float | None = None):
        self._app = app
        self._ttl = ttl or self._DEFAULT_TTL
        self._cache: dict[str, tuple[str, bytes, dict[bytes, bytes], float]] = {}
        self._lock = threading.Lock()
        ETagCacheMiddleware._instance = self

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method", "") != "GET":
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not any(path.startswith(p) for p in self._CACHEABLE_PREFIXES):
            await self._app(scope, receive, send)
            return

        cache_key = path + "?" + scope.get("query_string", b"").decode("utf-8", errors="replace")

        headers_list = scope.get("headers", [])
        if_none_match = ""
        for k, v in headers_list:
            if k == b"if-none-match":
                if_none_match = v.decode("utf-8", errors="replace")
                break

        with self._lock:
            entry = self._cache.get(cache_key)
            if entry is not None:
                etag, body, resp_headers, ts = entry
                if time.monotonic() - ts < self._ttl:
                    if if_none_match and if_none_match == etag:
                        await _send_304(send, etag)
                        return
                    await _send_cached(send, body, resp_headers, etag)
                    return
                del self._cache[cache_key]

        captured_body = bytearray()
        captured_status = 200
        captured_headers: list[tuple[bytes, bytes]] = []

        async def capturing_send(msg):
            nonlocal captured_status, captured_headers
            if msg["type"] == "http.response.start":
                captured_status = msg.get("status", 200)
                captured_headers = list(msg.get("headers", []))
            elif msg["type"] == "http.response.body":
                captured_body.extend(msg.get("body", b""))
            await send(msg)

        await self._app(scope, receive, capturing_send)

        if captured_status == 200 and len(captured_body) > 0:
            etag = '"' + hashlib.md5(captured_body).hexdigest()[:16] + '"'
            with self._lock:
                if len(self._cache) >= self._MAX_ENTRIES:
                    oldest = min(self._cache, key=lambda k: self._cache[k][3])
                    del self._cache[oldest]
                self._cache[cache_key] = (etag, bytes(captured_body), dict(captured_headers), time.monotonic())

    def status(self) -> dict:
        with self._lock:
            entries = len(self._cache)
            total_bytes = sum(len(v[1]) for v in self._cache.values())
            ages = [time.monotonic() - v[3] for v in self._cache.values()] if entries else [0]
            return {
                "entries": entries,
                "max_entries": self._MAX_ENTRIES,
                "total_bytes": total_bytes,
                "ttl_seconds": self._ttl,
                "avg_age_seconds": round(sum(ages) / len(ages), 2),
                "oldest_age_seconds": round(max(ages), 2),
            }


async def _send_304(send, etag: str):
    await send({
        "type": "http.response.start",
        "status": 304,
        "headers": [
            [b"etag", etag.encode()],
            [b"cache-control", b"max-age=5"],
        ],
    })
    await send({"type": "http.response.body", "body": b""})


async def _send_cached(send, body: bytes, headers: dict[bytes, bytes], etag: str):
    hdrs = [[k, v] for k, v in headers.items()]
    hdrs.append([b"etag", etag.encode()])
    hdrs.append([b"cache-control", b"max-age=5"])
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": hdrs,
    })
    await send({"type": "http.response.body", "body": body})


class PerIPRateLimitMiddleware:
    _SKIP_PREFIXES = ("/api/health", "/api/system/metrics", "/api/system/drain-status",
                      "/docs", "/openapi.json", "/favicon.ico", "/")
    _DEFAULT_RPM = 120
    _MAX_CLIENTS = 1024
    _CLEANUP_INTERVAL = 60.0
    _instance: PerIPRateLimitMiddleware | None = None
    _testing: bool = False

    def __init__(self, app, rpm: int | None = None):
        self._app = app
        self._rpm = rpm or self._DEFAULT_RPM
        self._clients: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()
        PerIPRateLimitMiddleware._instance = self

    def _client_ip(self, scope: dict) -> str:
        for k, v in scope.get("headers", []):
            if k == b"x-forwarded-for":
                return v.decode("utf-8", errors="replace").split(",")[0].strip()
        client = scope.get("client")
        if client:
            return client[0]
        return "unknown"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        if self._testing:
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "")
        if any(path == p or path.startswith(p + "/") for p in self._SKIP_PREFIXES):
            await self._app(scope, receive, send)
            return

        ip = self._client_ip(scope)
        now = time.monotonic()

        with self._lock:
            if now - self._last_cleanup > self._CLEANUP_INTERVAL:
                stale = [c for c, ts in self._clients.items() if not ts or now - ts[-1] > 120]
                for c in stale:
                    del self._clients[c]
                self._last_cleanup = now

            if ip not in self._clients:
                if len(self._clients) >= self._MAX_CLIENTS:
                    oldest = min(self._clients, key=lambda c: self._clients[c][-1] if self._clients[c] else 0)
                    del self._clients[oldest]
                self._clients[ip] = deque()

            timestamps = self._clients[ip]
            while timestamps and now - timestamps[0] > 60.0:
                timestamps.popleft()

            if len(timestamps) >= self._rpm:
                import orjson
                body = orjson.dumps({"success": False, "error": "请求过于频繁，请稍后重试"})
                await send({
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        [b"content-type", b"application/json"],
                        [b"retry-after", b"5"],
                    ],
                })
                await send({"type": "http.response.body", "body": body})
                return

            timestamps.append(now)

        await self._app(scope, receive, send)

    def status(self) -> dict:
        with self._lock:
            return {
                "rpm_limit": self._rpm,
                "tracked_clients": len(self._clients),
                "max_clients": self._MAX_CLIENTS,
            }
