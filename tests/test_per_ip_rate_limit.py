from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock

import pytest

from api.middleware import PerIPRateLimitMiddleware


def _make_scope(path: str = "/api/stock/quote", client_ip: str = "127.0.0.1"):
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [],
        "client": (client_ip, 12345),
    }


async def _collect_response(mw, scope):
    sent = []

    async def mock_send(msg):
        sent.append(msg)

    await mw(scope, lambda: None, mock_send)
    return sent


@pytest.fixture
def middleware():
    inner = AsyncMock()

    async def fake_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    inner.side_effect = fake_app
    mw = PerIPRateLimitMiddleware(inner, rpm=5)
    mw._testing = False
    return mw, inner


@pytest.mark.asyncio
async def test_allows_requests_under_limit(middleware):
    mw, inner = middleware
    scope = _make_scope()
    resp = await _collect_response(mw, scope)
    statuses = [m.get("status") for m in resp if m["type"] == "http.response.start"]
    assert 200 in statuses


@pytest.mark.asyncio
async def test_blocks_requests_over_limit(middleware):
    mw, inner = middleware
    scope = _make_scope()
    for _ in range(5):
        await _collect_response(mw, scope)

    resp = await _collect_response(mw, scope)
    statuses = [m.get("status") for m in resp if m["type"] == "http.response.start"]
    assert 429 in statuses


@pytest.mark.asyncio
async def test_skips_health_endpoints(middleware):
    mw, inner = middleware
    for path in ("/api/health", "/api/system/metrics", "/docs", "/favicon.ico"):
        scope = _make_scope(path=path)
        resp = await _collect_response(mw, scope)
        statuses = [m.get("status") for m in resp if m["type"] == "http.response.start"]
        assert 200 in statuses, f"Expected 200 for {path}"


@pytest.mark.asyncio
async def test_per_ip_isolation(middleware):
    mw, inner = middleware
    scope_a = _make_scope(client_ip="10.0.0.1")
    for _ in range(5):
        await _collect_response(mw, scope_a)

    scope_b = _make_scope(client_ip="10.0.0.2")
    resp = await _collect_response(mw, scope_b)
    statuses = [m.get("status") for m in resp if m["type"] == "http.response.start"]
    assert 200 in statuses


@pytest.mark.asyncio
async def test_x_forwarded_for_header():
    inner = AsyncMock()

    async def fake_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    inner.side_effect = fake_app
    mw = PerIPRateLimitMiddleware(inner, rpm=5)
    mw._testing = False

    scope = _make_scope()
    scope["headers"] = [(b"x-forwarded-for", b"1.2.3.4, 5.6.7.8")]
    del scope["client"]

    resp = await _collect_response(mw, scope)
    statuses = [m.get("status") for m in resp if m["type"] == "http.response.start"]
    assert 200 in statuses


@pytest.mark.asyncio
async def test_status_returns_stats(middleware):
    mw, inner = middleware
    scope = _make_scope()
    await _collect_response(mw, scope)

    stats = mw.status()
    assert stats["rpm_limit"] == 5
    assert stats["tracked_clients"] == 1
    assert stats["max_clients"] == 1024


@pytest.mark.asyncio
async def test_testing_flag_bypasses_limit(middleware):
    mw, inner = middleware
    mw._testing = True
    scope = _make_scope()
    for _ in range(10):
        await _collect_response(mw, scope)

    resp = await _collect_response(mw, scope)
    statuses = [m.get("status") for m in resp if m["type"] == "http.response.start"]
    assert 200 in statuses
