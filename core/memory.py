# MODIFIED: User behavior memory system | VERSION: 2026-05-11
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from core.database import get_db

logger = logging.getLogger(__name__)

_MEMORY_KEY_PREFIX = "user_memory:"
_MAX_VIEW_HISTORY = 200
_MAX_SEARCH_HISTORY = 50
_MAX_BACKTEST_HISTORY = 10


class UserMemory:
    def __init__(self):
        self._lock: asyncio.Lock = asyncio.Lock()
        self._cache: dict[str, Any] = {}
        self._cache_ts: dict[str, float] = {}
        self._cache_ttl = 60.0

    def _get_db(self):
        return get_db()

    def _load(self, key: str) -> dict | None:
        now = time.monotonic()
        if key in self._cache and now - self._cache_ts.get(key, 0) < self._cache_ttl:
            return self._cache[key]
        try:
            db = self._get_db()
            row = db.fetchone(
                "SELECT value FROM config WHERE key = ?",
                (f"{_MEMORY_KEY_PREFIX}{key}",),
            )
            if row:
                data = json.loads(row[0])
                self._cache[key] = data
                self._cache_ts[key] = now
                return data
        except Exception as e:
            logger.debug("Memory load error for %s: %s", key, e)
        return None

    def _save(self, key: str, data: dict) -> None:
        self._cache[key] = data
        self._cache_ts[key] = time.monotonic()
        try:
            db = self._get_db()
            db.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (f"{_MEMORY_KEY_PREFIX}{key}", json.dumps(data, ensure_ascii=False)),
            )
        except Exception as e:
            logger.error("Memory save error for %s: %s", key, e)

    async def record_view(self, symbol: str) -> None:
        async with self._lock:
            data = self._load("frequently_viewed") or {"symbols": [], "counts": {}}
            symbols = data.get("symbols", [])
            counts = data.get("counts", {})
            counts[symbol] = counts.get(symbol, 0) + 1
            if symbol not in symbols:
                symbols.append(symbol)
            if len(symbols) > _MAX_VIEW_HISTORY:
                symbols = symbols[-_MAX_VIEW_HISTORY:]
            data = {"symbols": symbols, "counts": counts}
            self._save("frequently_viewed", data)

    async def record_search(self, query: str) -> None:
        async with self._lock:
            data = self._load("search_history") or {"queries": []}
            queries = data.get("queries", [])
            if query in queries:
                queries.remove(query)
            queries.insert(0, query)
            queries = queries[:_MAX_SEARCH_HISTORY]
            data = {"queries": queries}
            self._save("search_history", data)

    async def record_strategy_preference(self, strategy_name: str, params: dict | None = None) -> None:
        async with self._lock:
            data = self._load("strategy_preference") or {}
            data[strategy_name] = {
                "last_used": time.time(),
                "params": params or {},
                "use_count": data.get(strategy_name, {}).get("use_count", 0) + 1,
            }
            self._save("strategy_preference", data)

    async def record_backtest(self, params: dict) -> None:
        async with self._lock:
            data = self._load("backtest_history") or {"runs": []}
            runs = data.get("runs", [])
            entry = {"params": params, "timestamp": time.time()}
            runs.insert(0, entry)
            runs = runs[:_MAX_BACKTEST_HISTORY]
            data = {"runs": runs}
            self._save("backtest_history", data)

    async def get_recommended_symbols(self) -> list[str]:
        async with self._lock:
            data = self._load("frequently_viewed") or {"symbols": [], "counts": {}}
            counts = data.get("counts", {})
            sorted_syms = sorted(counts.items(), key=lambda x: x[1], reverse=True)
            return [s for s, _ in sorted_syms[:20]]

    async def get_memory_summary(self) -> dict:
        async with self._lock:
            viewed = self._load("frequently_viewed") or {"symbols": [], "counts": {}}
            searches = self._load("search_history") or {"queries": []}
            strategy = self._load("strategy_preference") or {}
            backtest = self._load("backtest_history") or {"runs": []}
            return {
                "frequently_viewed": list(viewed.get("counts", {}).keys())[:10],
                "search_history": searches.get("queries", [])[:10],
                "strategy_preference": {
                    k: {"use_count": v.get("use_count", 0)} for k, v in strategy.items()
                },
                "backtest_count": len(backtest.get("runs", [])),
            }

    async def clear_memory(self) -> None:
        async with self._lock:
            for key in ("frequently_viewed", "search_history", "strategy_preference", "backtest_history"):
                self._cache.pop(key, None)
                self._cache_ts.pop(key, None)
                try:
                    db = self._get_db()
                    db.execute("DELETE FROM config WHERE key = ?", (f"{_MEMORY_KEY_PREFIX}{key}",))
                except Exception as e:
                    logger.debug("Memory cache DB delete failed: %s", e)
                    pass


_user_memory: UserMemory | None = None


def get_user_memory() -> UserMemory:
    global _user_memory
    if _user_memory is None:
        _user_memory = UserMemory()
    return _user_memory
