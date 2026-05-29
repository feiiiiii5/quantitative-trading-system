from __future__ import annotations

import hashlib
import time
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.middleware import ETagCacheMiddleware


@pytest.fixture
def middleware():
    inner = AsyncMock()
    mw = ETagCacheMiddleware(inner, ttl=2.0)
    return mw, inner


def _make_scope(path: str = "/api/market/heatmap", method: str = "GET", query: str = ""):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query.encode(),
        "headers": [],
    }


async def _collect_response(mw, scope):
    sent = []

    async def mock_send(msg):
        sent.append(msg)

    await mw(scope, lambda: None, mock_send)
    return sent


@pytest.mark.asyncio
async def test_etag_cache_returns_cached_response(middleware):
    mw, inner = middleware
    inner.side_effect = None

    async def fake_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [[b"content-type", b"application/json"]]})
        await send({"type": "http.response.body", "body": b'{"data":1}'})

    inner.side_effect = fake_app

    scope1 = _make_scope()
    resp1 = await _collect_response(mw, scope1)
    assert any(m.get("status") == 200 for m in resp1 if m["type"] == "http.response.start")

    inner.side_effect = fake_app
    scope2 = _make_scope()
    resp2 = await _collect_response(mw, scope2)
    assert any(m.get("status") == 200 for m in resp2 if m["type"] == "http.response.start")

    assert inner.call_count == 1


@pytest.mark.asyncio
async def test_etag_304_when_if_none_match(middleware):
    mw, inner = middleware

    async def fake_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [[b"content-type", b"application/json"]]})
        await send({"type": "http.response.body", "body": b'{"data":1}'})

    inner.side_effect = fake_app

    scope1 = _make_scope()
    await _collect_response(mw, scope1)

    etag = '"' + hashlib.md5(b'{"data":1}').hexdigest()[:16] + '"'
    scope2 = _make_scope()
    scope2["headers"] = [(b"if-none-match", etag.encode())]
    resp = await _collect_response(mw, scope2)

    statuses = [m.get("status") for m in resp if m["type"] == "http.response.start"]
    assert 304 in statuses


@pytest.mark.asyncio
async def test_non_get_not_cached(middleware):
    mw, inner = middleware

    async def fake_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    inner.side_effect = fake_app

    scope = _make_scope(method="POST")
    await _collect_response(mw, scope)
    await _collect_response(mw, scope)

    assert inner.call_count == 2


@pytest.mark.asyncio
async def test_non_cacheable_path_not_cached(middleware):
    mw, inner = middleware

    async def fake_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    inner.side_effect = fake_app

    scope = _make_scope(path="/api/auth/login")
    await _collect_response(mw, scope)
    await _collect_response(mw, scope)

    assert inner.call_count == 2


@pytest.mark.asyncio
async def test_cache_expires_after_ttl(middleware):
    mw, inner = middleware
    mw._ttl = 0.01

    call_count = 0

    async def fake_app(scope, receive, send):
        nonlocal call_count
        call_count += 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    inner.side_effect = fake_app

    scope = _make_scope()
    await _collect_response(mw, scope)
    time.sleep(0.02)
    await _collect_response(mw, scope)

    assert call_count == 2


@pytest.mark.asyncio
async def test_max_entries_evicts_oldest():
    inner = AsyncMock()

    async def fake_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    inner.side_effect = fake_app
    mw = ETagCacheMiddleware(inner, ttl=60.0)
    mw._MAX_ENTRIES = 3

    for i in range(5):
        scope = _make_scope(path=f"/api/market/heatmap/{i}")
        await _collect_response(mw, scope)

    assert len(mw._cache) <= 3
