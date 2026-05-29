# MODIFIED: Multi-level memory cache architecture | VERSION: 2026-05-11
from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

CACHE_CONFIGS = {
    "realtime": {"maxsize": 50000, "ttl_trading": 8, "ttl_non_trading": 60},
    "history": {"maxsize": 30000, "ttl_trading": 1800, "ttl_non_trading": 3600},
    "indicator": {"maxsize": 6000, "ttl_trading": 900, "ttl_non_trading": 1800},
    "financial": {"maxsize": 3000, "ttl_trading": 10800, "ttl_non_trading": 10800},
    "northbound": {"maxsize": 1000, "ttl_trading": 180, "ttl_non_trading": 600},
    "tick": {"maxsize": 500, "ttl_trading": 2, "ttl_non_trading": 10},
}


def make_cache_key(data_type: str, symbol: str, market: str = "", params: str = "", **kwargs) -> str:
    if kwargs:
        sorted_params = "|".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        params_hash = hashlib.md5(sorted_params.encode()).hexdigest()[:8]
    elif params:
        params_hash = hashlib.md5(params.encode()).hexdigest()[:8]
    else:
        params_hash = ""
    parts = [data_type, symbol, market, params_hash]
    return ":".join(p for p in parts if p)


def get_adaptive_ttl(cache_name: str, is_trading: bool | None = None) -> int:
    config = CACHE_CONFIGS.get(cache_name, {"ttl_trading": 60, "ttl_non_trading": 300})
    if is_trading is not None:
        return config["ttl_trading"] if is_trading else config["ttl_non_trading"]
    from core.market_hours import MarketHours
    try:
        status = MarketHours.get_market_status("A")
        if status.get("is_open"):
            return config["ttl_trading"]
    except Exception as e:
        logger.debug("Market hours check failed: %s", e)
        pass
    return config["ttl_non_trading"]


class TickCache:
    __slots__ = ("_cache", "_maxsize", "_ttl", "_lock")

    def __init__(self, maxsize: int = 500, ttl: float = 2.0):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._maxsize = maxsize
        self._ttl = ttl
        self._lock = threading.Lock()

    def _schedule_eviction(self, key: str, delay: float, expire_at: float) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.call_later(delay, self._evict_key, key, expire_at)
        except RuntimeError:
            pass

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            value, expire_at = entry
            if time.monotonic() > expire_at:
                del self._cache[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        effective_ttl = ttl or self._ttl
        expire_at = time.monotonic() + effective_ttl
        with self._lock:
            if len(self._cache) >= self._maxsize and key not in self._cache:
                oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
            self._cache[key] = (value, expire_at)
        self._schedule_eviction(key, effective_ttl + 0.1, expire_at)

    def _evict_key(self, key: str, scheduled_expire_at: float) -> None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None and entry[1] == scheduled_expire_at:
                del self._cache[key]

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


_tick_cache = TickCache(maxsize=500, ttl=2.0)
