import asyncio
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import orjson

    _HAS_ORJSON = True
except ImportError:
    _HAS_ORJSON = False

from fastapi.responses import JSONResponse

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="data_fetch")


async def run_sync(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, lambda: func(*args, **kwargs))


async def run_sync_timeout(func, timeout: float, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(_executor, lambda: func(*args, **kwargs)),
        timeout=timeout,
    )


@dataclass
class CacheEntry:
    value: Any
    expires_at: float
    created_at: float = field(default_factory=time.monotonic)
    hit_count: int = 0


class TTLCache:
    __slots__ = ("_store", "_lock", "_maxsize", "_hits", "_misses")

    def __init__(self, maxsize: int = 1000):
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._maxsize = maxsize
        self._hits = 0
        self._misses = 0

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if time.monotonic() > entry.expires_at:
                del self._store[key]
                self._misses += 1
                return None
            self._store.move_to_end(key)
            entry.hit_count += 1
            self._hits += 1
            return entry.value

    def get_sync(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            del self._store[key]
            return None
        entry.hit_count += 1
        return entry.value

    async def set(self, key: str, value: Any, ttl: float):
        async with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            elif len(self._store) >= self._maxsize:
                self._store.popitem(last=False)
            self._store[key] = CacheEntry(
                value=value,
                expires_at=time.monotonic() + ttl,
            )

    def set_sync(self, key: str, value: Any, ttl: float):
        if key in self._store:
            self._store.move_to_end(key)
        elif len(self._store) >= self._maxsize:
            self._store.popitem(last=False)
        self._store[key] = CacheEntry(
            value=value,
            expires_at=time.monotonic() + ttl,
        )

    async def delete(self, key: str):
        async with self._lock:
            self._store.pop(key, None)

    async def delete_prefix(self, prefix: str) -> int:
        async with self._lock:
            keys_to_delete = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_delete:
                del self._store[k]
            return len(keys_to_delete)

    async def clear(self):
        async with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def __len__(self) -> int:
        return len(self._store)

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "maxsize": self._maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0,
        }


rt_cache = TTLCache(maxsize=30000)
kline_cache = TTLCache(maxsize=2000)
sector_cache = TTLCache(maxsize=200)
search_cache = TTLCache(maxsize=500)
overview_cache = TTLCache(maxsize=20)
breadth_cache = TTLCache(maxsize=20)
backtest_result_cache = TTLCache(maxsize=1000)
fundamental_cache = TTLCache(maxsize=1000)
index_cache = TTLCache(maxsize=200)
northbound_cache = TTLCache(maxsize=100)
alert_cache = TTLCache(maxsize=500)

CACHE_TTL = {
    "realtime": 3.0,
    "realtime_hot": 8.0,
    "realtime_batch": 5.0,
    "kline_daily": 300.0,
    "kline_intraday": 60.0,
    "market_overview": 10.0,
    "sector_heatmap": 60.0,
    "search_index": 3600.0,
    "fundamental": 3600.0,
    "market_breadth": 5.0,
    "backtest_result": float("inf"),
    "northbound": 180.0,
    "limit_up": 45.0,
    "dragon_tiger": 600.0,
    "index_quote": 15.0,
    "alert_signal": 30.0,
    "portfolio_summary": 10.0,
    "hot_symbols": 60.0,
}


class FastJSONResponse(JSONResponse):
    media_type = "application/json"

    def render(self, content) -> bytes:
        if _HAS_ORJSON:
            content = _convert_numpy(content)
            return orjson.dumps(content, option=orjson.OPT_NON_STR_KEYS)
        content = _convert_numpy(content)
        return super().render(content)


def _convert_numpy(obj):
    if isinstance(obj, dict):
        return {k: _convert_numpy(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_convert_numpy(v) for v in obj]
    try:
        import numpy as np
        if isinstance(obj, np.datetime64):
            return str(obj)
        if isinstance(obj, np.timedelta64):
            return str(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return _convert_numpy(obj.tolist())
        if isinstance(obj, np.void):
            return None
    except ImportError:
        pass
    return obj
