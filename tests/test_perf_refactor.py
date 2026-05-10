import asyncio
import time

import pytest


def test_hot_symbols_thread_safe_access():
    from core.data_fetcher import _get_hot_symbols, _set_hot_symbols

    _set_hot_symbols(["600519", "000858", "300750"])
    result = _get_hot_symbols()
    assert result == ["600519", "000858", "300750"]
    _set_hot_symbols([])
    assert _get_hot_symbols() == []


def test_hot_symbols_returns_copy():
    from core.data_fetcher import _get_hot_symbols, _set_hot_symbols

    _set_hot_symbols(["600519"])
    result = _get_hot_symbols()
    result.append("000858")
    assert _get_hot_symbols() == ["600519"]
    _set_hot_symbols([])


def test_convert_numpy_datetime64():
    import numpy as np
    from core.async_utils import _convert_numpy

    dt = np.datetime64("2024-01-15")
    assert isinstance(_convert_numpy(dt), str)
    td = np.timedelta64(1, "D")
    assert isinstance(_convert_numpy(td), str)


def test_convert_numpy_nested():
    import numpy as np
    from core.async_utils import _convert_numpy

    data = {
        "arr": np.array([1.0, 2.0, 3.0]),
        "val": np.float64(3.14),
        "int": np.int64(42),
        "nested": {"flag": np.bool_(True)},
    }
    result = _convert_numpy(data)
    assert result["arr"] == [1.0, 2.0, 3.0]
    assert isinstance(result["val"], float)
    assert isinstance(result["int"], int)
    assert isinstance(result["nested"]["flag"], bool)


def test_convert_numpy_void():
    import numpy as np
    from core.async_utils import _convert_numpy

    assert _convert_numpy(np.void(0)) is None


@pytest.mark.asyncio
async def test_ttl_cache_set_get():
    from core.async_utils import TTLCache

    cache = TTLCache(maxsize=10)
    await cache.set("key1", "value1", ttl=10.0)
    result = await cache.get("key1")
    assert result == "value1"


@pytest.mark.asyncio
async def test_ttl_cache_expiry():
    from core.async_utils import TTLCache

    cache = TTLCache(maxsize=10)
    await cache.set("key1", "value1", ttl=0.01)
    await asyncio.sleep(0.02)
    result = await cache.get("key1")
    assert result is None


@pytest.mark.asyncio
async def test_ttl_cache_lru_eviction():
    from core.async_utils import TTLCache

    cache = TTLCache(maxsize=3)
    await cache.set("a", 1, ttl=100)
    await cache.set("b", 2, ttl=100)
    await cache.set("c", 3, ttl=100)
    await cache.get("a")
    await cache.set("d", 4, ttl=100)
    assert await cache.get("a") == 1
    assert await cache.get("b") is None
    assert await cache.get("c") == 3
    assert await cache.get("d") == 4


@pytest.mark.asyncio
async def test_ttl_cache_stats():
    from core.async_utils import TTLCache

    cache = TTLCache(maxsize=10)
    await cache.set("k", "v", ttl=100)
    await cache.get("k")
    await cache.get("missing")
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["size"] == 1


@pytest.mark.asyncio
async def test_ttl_cache_delete_prefix():
    from core.async_utils import TTLCache

    cache = TTLCache(maxsize=100)
    await cache.set("rt:600519", "v1", ttl=100)
    await cache.set("rt:000858", "v2", ttl=100)
    await cache.set("kline:600519", "v3", ttl=100)
    deleted = await cache.delete_prefix("rt:")
    assert deleted == 2
    assert await cache.get("rt:600519") is None
    assert await cache.get("kline:600519") == "v3"


def test_sanitize_numpy_in_backtest():
    import numpy as np
    from api.backtest_routes import _sanitize_numpy

    data = {
        "returns": np.array([0.01, -0.02, 0.03]),
        "sharpe": np.float64(1.5),
        "trades": np.int64(42),
        "profitable": np.bool_(True),
    }
    result = _sanitize_numpy(data)
    assert result["returns"] == [0.01, -0.02, 0.03]
    assert isinstance(result["sharpe"], float)
    assert isinstance(result["trades"], int)
    assert isinstance(result["profitable"], bool)


def test_cache_stats_endpoint():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    resp = client.get("/api/cache/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "caches" in data["data"]
    assert "total_size" in data["data"]
    assert "overall_hit_rate" in data["data"]


def test_cache_clear_endpoint():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    resp = client.post("/api/cache/clear", json={"cache_name": "overview"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


def test_cache_clear_all_endpoint():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    resp = client.post("/api/cache/clear", json={"cache_name": "all"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]["cleared"]) > 0


def test_cache_clear_unknown_endpoint():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    resp = client.post("/api/cache/clear", json={"cache_name": "nonexistent"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False


def test_databus_channel_enum():
    from core.reactive_bus import DataChannel

    assert DataChannel.MARKET_OVERVIEW.value == "market.overview"
    assert DataChannel.MARKET_BREADTH.value == "market.breadth"
    assert DataChannel.SECTOR_HEATMAP.value == "sector.heatmap"
    assert DataChannel.HOT_SYMBOLS.value == "hot.symbols"


@pytest.mark.asyncio
async def test_databus_register_and_stats():
    from core.reactive_bus import ReactiveDataBus

    bus = ReactiveDataBus()
    call_count = 0

    async def mock_fetcher():
        nonlocal call_count
        call_count += 1
        return {"value": call_count}

    bus.register("test.channel", mock_fetcher, 1.0)
    stats = bus.stats()
    assert "test.channel" in stats["channels"]
    assert stats["running"] is False


@pytest.mark.asyncio
async def test_databus_publish_and_subscribe():
    from core.reactive_bus import ReactiveDataBus

    bus = ReactiveDataBus()
    queue = await bus.subscribe("test.ch")
    await bus.publish("test.ch", {"price": 100})
    msg = queue.get_nowait()
    assert msg["channel"] == "test.ch"
    assert msg["data"] == {"price": 100}
    assert "ts" in msg


@pytest.mark.asyncio
async def test_databus_get_cached():
    from core.reactive_bus import ReactiveDataBus

    bus = ReactiveDataBus()
    result = await bus.get_cached("nonexistent")
    assert result is None
    await bus.publish("test.ch", {"val": 42})
    cached = await bus.get_cached("test.ch")
    assert cached == {"val": 42}


@pytest.mark.asyncio
async def test_databus_unsubscribe():
    from core.reactive_bus import ReactiveDataBus

    bus = ReactiveDataBus()
    queue = await bus.subscribe("test.ch")
    await bus.unsubscribe("test.ch", queue)
    stats = bus.stats()
    assert "test.ch" not in stats["subscribers"] or stats["subscribers"].get("test.ch", 0) == 0


@pytest.mark.asyncio
async def test_databus_invalidate():
    from core.reactive_bus import ReactiveDataBus

    bus = ReactiveDataBus()
    await bus.publish("test.ch", {"val": 1})
    cached = await bus.get_cached("test.ch")
    assert cached == {"val": 1}
    await bus.invalidate("test.ch")
    cached = await bus.get_cached("test.ch")
    assert cached is None


@pytest.mark.asyncio
async def test_databus_poll_loop():
    from core.reactive_bus import ReactiveDataBus

    bus = ReactiveDataBus()
    call_count = 0

    async def mock_fetcher():
        nonlocal call_count
        call_count += 1
        return {"count": call_count}

    bus.register("poll.ch", mock_fetcher, 0.05)
    await bus.start()
    assert bus._running is True
    await asyncio.sleep(0.2)
    await bus.stop()
    assert bus._running is False
    assert call_count >= 2


@pytest.mark.asyncio
async def test_databus_get_or_fetch():
    from core.reactive_bus import ReactiveDataBus

    bus = ReactiveDataBus()
    fetch_count = 0

    async def mock_fetcher():
        nonlocal fetch_count
        fetch_count += 1
        return {"fetched": fetch_count}

    bus.register("lazy.ch", mock_fetcher, 60.0)
    result = await bus.get_or_fetch("lazy.ch")
    assert result == {"fetched": 1}
    result2 = await bus.get_or_fetch("lazy.ch")
    assert result2 == {"fetched": 1}
    assert fetch_count == 1


@pytest.mark.asyncio
async def test_databus_queue_full_eviction():
    from core.reactive_bus import ReactiveDataBus

    bus = ReactiveDataBus()
    queue = asyncio.Queue(maxsize=2)
    async with bus._lock:
        bus._subscribers["full.ch"] = [queue]
    await queue.put({"channel": "full.ch", "data": 1, "ts": 1})
    await queue.put({"channel": "full.ch", "data": 2, "ts": 2})
    await bus.publish("full.ch", {"data": 3})
    stats = bus.stats()
    assert "full.ch" not in stats["subscribers"] or len(bus._subscribers.get("full.ch", [])) == 0


def test_databus_stats_endpoint():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    resp = client.get("/api/databus/stats")
    assert resp.status_code == 200
    data = resp.json()
    bus = getattr(app.state, "data_bus", None)
    if bus is not None:
        assert data["success"] is True
        assert "cache" in data["data"]
        assert "channels" in data["data"]
        assert "running" in data["data"]
    else:
        assert data["success"] is False


def test_risk_metrics_endpoint_exists():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    resp = client.get("/api/risk/metrics")
    assert resp.status_code == 200
    result = resp.json()
    assert result["success"] is True
    data = result["data"]
    assert "riskLevel" in data
    assert data["riskLevel"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert "var95" in data
    assert "cvar" in data
    assert "maxDrawdown" in data
    assert "sharpe" in data
    assert "beta" in data
    assert "riskDecomposition" in data
    assert isinstance(data["riskDecomposition"], list)
    assert "correlationMatrix" in data
    cm = data["correlationMatrix"]
    assert "labels" in cm
    assert "values" in cm
    assert isinstance(cm["labels"], list)
    assert isinstance(cm["values"], list)
    assert "historicalVol" in data
    assert "impliedVol" in data
    assert "volDates" in data


def test_terminal_orderbook_endpoint_exists():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    resp = client.get("/api/terminal/orderbook", params={"symbol": "600519"})
    assert resp.status_code == 200
    result = resp.json()
    assert result["success"] is True
    data = result["data"]
    assert "bids" in data
    assert "asks" in data
    assert isinstance(data["bids"], list)
    assert isinstance(data["asks"], list)


def test_terminal_trades_endpoint_exists():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    resp = client.get("/api/terminal/trades", params={"symbol": "600519"})
    assert resp.status_code == 200
    result = resp.json()
    assert result["success"] is True
    data = result["data"]
    assert isinstance(data, list)


def test_market_kline_endpoint_exists():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    resp = client.get("/api/market/kline", params={"symbol": "600519", "period": "1mo"})
    assert resp.status_code == 200
    result = resp.json()
    has_fetcher = hasattr(app.state, "fetcher")
    if has_fetcher:
        assert result["success"] is True
        data = result["data"]
        assert isinstance(data, list)
        if len(data) > 0:
            bar = data[0]
            assert "time" in bar
            assert "open" in bar
            assert "high" in bar
            assert "low" in bar
            assert "close" in bar
            assert "volume" in bar
    else:
        assert result["success"] is False


def test_market_quote_endpoint_exists():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    resp = client.get("/api/market/quote", params={"symbol": "600519"})
    assert resp.status_code == 200
    result = resp.json()
    has_fetcher = hasattr(app.state, "fetcher")
    if has_fetcher:
        assert result["success"] is True
        data = result["data"]
        if data is not None:
            assert "symbol" in data
            assert "name" in data
            assert "price" in data
            assert "change" in data
            assert "change_pct" in data
            assert "volume" in data
            assert "amount" in data
            assert "open" in data
            assert "high" in data
            assert "low" in data
            assert "close" in data
            assert "turnover" in data
    else:
        assert result["success"] is False


def test_market_overview_includes_breadth():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    resp = client.get("/api/market/overview")
    assert resp.status_code == 200
    result = resp.json()
    if result["success"] is True:
        data = result["data"]
        assert "cn_indices" in data
        assert "market_breadth" in data
