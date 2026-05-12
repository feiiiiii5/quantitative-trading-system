import asyncio
import json
import logging
import time
from typing import Dict, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class OptimizedWSManager:
    MAX_CONNECTIONS = 200
    STALE_TIMEOUT = 300
    SEND_TIMEOUT = 1.0

    def __init__(self):
        self._channels: Dict[str, Set[WebSocket]] = {}
        self._ws_channels: Dict[WebSocket, Set[str]] = {}
        self._connections: Set[WebSocket] = set()
        self._last_active: Dict[WebSocket, float] = {}
        self._last_sent: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, channels: list[str] | None = None) -> bool:
        async with self._lock:
            if len(self._connections) >= self.MAX_CONNECTIONS:
                await ws.close(code=1013, reason="Max connections reached")
                return False
            await ws.accept()
            self._connections.add(ws)
            self._ws_channels[ws] = set()
            self._last_active[ws] = time.time()
            if channels:
                for ch in channels:
                    self._channels.setdefault(ch, set()).add(ws)
                    self._ws_channels[ws].add(ch)
            return True

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            self._connections.discard(ws)
            channels = self._ws_channels.pop(ws, set())
            self._last_active.pop(ws, None)
            for ch in channels:
                subs = self._channels.get(ch)
                if subs:
                    subs.discard(ws)
                    if not subs:
                        del self._channels[ch]
                        self._last_sent.pop(ch, None)

    async def subscribe(self, ws: WebSocket, channels: list[str]):
        async with self._lock:
            self._last_active[ws] = time.time()
            for ch in channels:
                self._channels.setdefault(ch, set()).add(ws)
                self._ws_channels.setdefault(ws, set()).add(ch)

    async def unsubscribe(self, ws: WebSocket, channels: list[str]):
        async with self._lock:
            self._last_active[ws] = time.time()
            for ch in channels:
                subs = self._channels.get(ch)
                if subs:
                    subs.discard(ws)
                    if not subs:
                        del self._channels[ch]
                        self._last_sent.pop(ch, None)
                ws_chs = self._ws_channels.get(ws)
                if ws_chs:
                    ws_chs.discard(ch)

    async def touch(self, ws: WebSocket):
        async with self._lock:
            self._last_active[ws] = time.time()

    async def broadcast_to_channel(self, channel: str, data: dict):
        subscribers = self._channels.get(channel)
        if not subscribers:
            return 0
        subscribers = subscribers.copy()
        last = self._last_sent.get(channel, {})
        diff = {k: v for k, v in data.items() if last.get(k) != v}
        if not diff:
            return 0
        self._last_sent[channel] = {**last, **diff}
        payload = json.dumps({
            "channel": channel,
            "data": diff,
            "ts": int(time.time() * 1000),
        })
        dead: Set[WebSocket] = set()
        tasks = [self._safe_send(ws, payload) for ws in subscribers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for ws, result in zip(subscribers, results, strict=True):
            if isinstance(result, Exception):
                dead.add(ws)
        if dead:
            for ws in dead:
                await self.disconnect(ws)
        return len(subscribers) - len(dead)

    async def broadcast_full(self, channel: str, data: dict):
        subscribers = self._channels.get(channel)
        if not subscribers:
            return 0
        subscribers = subscribers.copy()
        self._last_sent[channel] = data
        payload = json.dumps({
            "channel": channel,
            "data": data,
            "ts": int(time.time() * 1000),
        })
        dead: Set[WebSocket] = set()
        tasks = [self._safe_send(ws, payload) for ws in subscribers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for ws, result in zip(subscribers, results, strict=True):
            if isinstance(result, Exception):
                dead.add(ws)
        if dead:
            for ws in dead:
                await self.disconnect(ws)
        return len(subscribers) - len(dead)

    async def send_to(self, ws: WebSocket, data: dict):
        payload = json.dumps(data)
        try:
            await asyncio.wait_for(ws.send_text(payload), timeout=self.SEND_TIMEOUT)
        except Exception as e:
            logger.debug("WebSocket send failed, disconnecting: %s", e)
            await self.disconnect(ws)

    async def _safe_send(self, ws: WebSocket, payload: str) -> None:
        await asyncio.wait_for(ws.send_text(payload), timeout=self.SEND_TIMEOUT)

    async def sweep_stale_connections(self) -> int:
        now = time.time()
        stale = []
        async with self._lock:
            for ws in list(self._last_active):
                if now - self._last_active.get(ws, 0) > self.STALE_TIMEOUT:
                    stale.append(ws)
        for ws in stale:
            try:
                await ws.close(code=1000, reason="Idle timeout")
            except Exception as e:
                logger.debug("Failed to close stale WebSocket: %s", e)
                pass
            await self.disconnect(ws)
        return len(stale)

    async def get_all_subscribed_symbols(self) -> set[str]:
        async with self._lock:
            symbols = set()
            for ch in self._channels:
                if ch.startswith("stock."):
                    symbols.add(ch.split(".", 1)[1])
            return symbols

    async def connection_count(self) -> int:
        return len(self._connections)

    async def get_connections_snapshot(self) -> list[WebSocket]:
        return list(self._connections)

    def get_channel_subscribers(self, channel: str) -> int:
        return len(self._channels.get(channel, set()))

    def stats(self) -> dict:
        return {
            "connections": len(self._connections),
            "channels": {ch: len(subs) for ch, subs in self._channels.items()},
            "max_connections": self.MAX_CONNECTIONS,
        }
