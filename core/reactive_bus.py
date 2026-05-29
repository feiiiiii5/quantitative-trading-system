import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from core.async_utils import TTLCache

logger = logging.getLogger(__name__)


class DataChannel(StrEnum):
    MARKET_OVERVIEW = "market.overview"
    MARKET_BREADTH = "market.breadth"
    SECTOR_HEATMAP = "sector.heatmap"
    HOT_SYMBOLS = "hot.symbols"
    STOCK_QUOTE = "stock.quote"
    PORTFOLIO_SUMMARY = "portfolio.summary"
    INDEX_QUOTE = "index.quote"
    DATASOURCE_HEALTH = "datasource.health"


class ReactiveDataBus:
    __slots__ = (
        "_cache",
        "_subscribers",
        "_fetchers",
        "_last_publish",
        "_running",
        "_tasks",
        "_lock",
    )

    def __init__(self):
        self._cache = TTLCache(maxsize=50000)
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._fetchers: dict[str, tuple[Callable, float]] = {}
        self._last_publish: dict[str, float] = {}
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._lock = asyncio.Lock()

    def register(self, channel: str, fetcher: Callable, interval: float):
        self._fetchers[channel] = (fetcher, interval)

    async def subscribe(self, channel: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers[channel].append(queue)
        return queue

    async def unsubscribe(self, channel: str, queue: asyncio.Queue):
        async with self._lock:
            subs = self._subscribers.get(channel, [])
            if queue in subs:
                subs.remove(queue)
            if not subs:
                self._subscribers.pop(channel, None)

    async def publish(self, channel: str, data: Any):
        now = time.monotonic()
        self._last_publish[channel] = now
        await self._cache.set(channel, data, ttl=3600.0)
        async with self._lock:
            subs = list(self._subscribers.get(channel, []))
        dead = []
        for queue in subs:
            try:
                queue.put_nowait({"channel": channel, "data": data, "ts": int(time.time() * 1000)})
            except asyncio.QueueFull:
                dead.append(queue)
        if dead:
            async with self._lock:
                for q in dead:
                    subs_list = self._subscribers.get(channel, [])
                    if q in subs_list:
                        subs_list.remove(q)

    async def get_cached(self, channel: str) -> Any:
        return await self._cache.get(channel)

    async def get_or_fetch(self, channel: str) -> Any:
        cached = await self._cache.get(channel)
        if cached is not None:
            return cached
        if channel in self._fetchers:
            fetcher, _ = self._fetchers[channel]
            try:
                data = await fetcher()
                await self.publish(channel, data)
                return data
            except Exception as e:
                logger.debug("ReactiveDataBus fetch error for %s: %s", channel, e)
        return None

    async def invalidate(self, channel: str):
        await self._cache.delete(channel)

    async def invalidate_prefix(self, prefix: str):
        await self._cache.delete_prefix(prefix)

    async def start(self):
        if self._running:
            return
        self._running = True
        for channel, (fetcher, interval) in self._fetchers.items():
            task = asyncio.create_task(self._poll_loop(channel, fetcher, interval))
            self._tasks.append(task)

    async def stop(self):
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _poll_loop(self, channel: str, fetcher: Callable, interval: float):
        while self._running:
            try:
                data = await fetcher()
                if data is not None:
                    await self.publish(channel, data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Poll loop error for %s: %s", channel, e)
            await asyncio.sleep(interval)

    def stats(self) -> dict:
        cache_stats = self._cache.stats()
        subscriber_counts = {ch: len(subs) for ch, subs in self._subscribers.items()}
        return {
            "cache": cache_stats,
            "subscribers": subscriber_counts,
            "channels": list(self._fetchers.keys()),
            "running": self._running,
            "last_publish": {ch: round(time.monotonic() - t, 1) for ch, t in self._last_publish.items()},
        }


_global_bus: ReactiveDataBus | None = None


def get_data_bus() -> ReactiveDataBus:
    global _global_bus
    if _global_bus is None:
        _global_bus = ReactiveDataBus()
    return _global_bus
