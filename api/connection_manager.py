import asyncio
import contextlib
import hashlib
import inspect
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from datetime import datetime
from functools import wraps
from typing import Any

import orjson
from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse, Response

from api.auth import decode_token
from core.data_fetcher import SmartDataFetcher
from core.database import OptimizedTTLCache
from core.market_hours import MarketHours
from core.smart_alerts import get_smart_alert_engine

logger = logging.getLogger(__name__)

_start_time = time.monotonic()


class _TTLCache:
    __slots__ = ("_cache", "_ttl", "_maxsize", "_hits", "_misses")

    def __init__(self, ttl: float = 3.0, maxsize: int = 5000) -> None:
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._ttl = ttl
        self._maxsize = maxsize
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any:
        entry = self._cache.get(key)
        if entry is not None:
            ts, val = entry
            if time.monotonic() - ts < self._ttl:
                self._cache.move_to_end(key)
                self._hits += 1
                return val
            del self._cache[key]
        self._misses += 1
        return None

    def set(self, key: str, val: Any) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        elif len(self._cache) >= self._maxsize:
            self._cache.popitem(last=False)
        self._cache[key] = (time.monotonic(), val)

    def clear(self) -> None:
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "maxsize": self._maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total else 0,
        }


_rt_cache = _TTLCache(ttl=8.0, maxsize=15000)
_kline_cache = _TTLCache(ttl=60.0, maxsize=6000)
_strategy_list_cache = _TTLCache(ttl=120.0, maxsize=200)

_api_response_cache = OptimizedTTLCache(maxsize=10000, ttl=90, cleanup_interval=120)


class ConnectionManager:
    """WebSocket连接管理器"""

    MAX_CONNECTIONS = 200
    STALE_TIMEOUT = 300

    def __init__(self):
        self.connections: set[WebSocket] = set()
        self._subscriptions: dict[WebSocket, set[str]] = {}
        self._last_active: dict[WebSocket, float] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        async with self._lock:
            if len(self.connections) >= self.MAX_CONNECTIONS:
                await ws.close(code=1013, reason="Max connections reached")
                return False
            await ws.accept()
            self.connections.add(ws)
            self._subscriptions[ws] = set()
            self._last_active[ws] = time.monotonic()
            return True

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            unsubscribed_symbols = self._subscriptions.pop(ws, set())
            self._last_active.pop(ws, None)
            self.connections.discard(ws)
        if unsubscribed_symbols:
            await _evict_stale_push_state(unsubscribed_symbols)

    async def subscribe(self, ws: WebSocket, symbols: list[str]):
        async with self._lock:
            if ws in self._subscriptions:
                self._subscriptions[ws].update(symbols)
                self._last_active[ws] = time.monotonic()

    async def unsubscribe(self, ws: WebSocket, symbols: list[str]):
        async with self._lock:
            if ws in self._subscriptions:
                self._subscriptions[ws] -= set(symbols)
                self._last_active[ws] = time.monotonic()

    async def touch(self, ws: WebSocket) -> None:
        async with self._lock:
            self._last_active[ws] = time.monotonic()

    async def sweep_stale_connections(self) -> int:
        now = time.monotonic()
        stale_ws = []
        async with self._lock:
            for ws in list(self._last_active):
                if now - self._last_active.get(ws, 0) > self.STALE_TIMEOUT:
                    stale_ws.append(ws)
        for ws in stale_ws:
            try:
                await ws.close(code=1000, reason="Idle timeout")
            except Exception as e:
                logger.warning("WebSocket sweep stale connection failed: %s", e)
            await self.disconnect(ws)
        return len(stale_ws)

    async def get_all_subscribed_symbols(self) -> set[str]:
        async with self._lock:
            all_symbols: set[str] = set()
            for symbols in self._subscriptions.values():
                all_symbols.update(symbols)
            return all_symbols

    async def get_subscriptions(self, ws: WebSocket) -> set[str]:
        async with self._lock:
            return set(self._subscriptions.get(ws, set()))

    async def get_connections_snapshot(self) -> list[WebSocket]:
        async with self._lock:
            return list(self.connections)

    async def connection_count(self) -> int:
        async with self._lock:
            return len(self.connections)

    async def broadcast(self, message: dict) -> int:
        msg_str = orjson.dumps(message, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS).decode("utf-8")
        async with self._lock:
            count = 0
            for ws in list(self.connections):
                try:
                    await _safe_ws_send(ws, msg_str)
                    count += 1
                except Exception as e:
                    logger.debug("WebSocket send failed during broadcast: %s", e)
            return count


_manager = ConnectionManager()


class TopicConnectionManager:
    TOPICS = frozenset({"quotes", "pnl", "signals", "regime", "alerts"})

    def __init__(self) -> None:
        self._topic_subs: dict[str, dict[WebSocket, set[str]]] = {t: {} for t in self.TOPICS}
        self._lock = asyncio.Lock()

    async def subscribe(self, ws: WebSocket, topics: set[str], symbols: set[str] | None = None) -> None:
        async with self._lock:
            for topic in topics & self.TOPICS:
                self._topic_subs[topic][ws] = symbols or set()

    async def unsubscribe(self, ws: WebSocket, topics: set[str] | None = None) -> None:
        async with self._lock:
            for topic in (topics or self.TOPICS):
                self._topic_subs.get(topic, {}).pop(ws, None)

    async def publish(self, topic: str, data: str, symbol: str | None = None) -> int:
        if topic not in self.TOPICS:
            return 0
        async with self._lock:
            subs = dict(self._topic_subs.get(topic, {}))
        count = 0
        for ws, syms in subs.items():
            if symbol and syms and symbol not in syms:
                continue
            try:
                await _safe_ws_send(ws, data)
                count += 1
            except Exception as e:
                logger.debug("Broadcast send failed, unsubscribing: %s", e)
                await self.unsubscribe(ws, {topic})
        return count

    async def get_subscribers(self, topic: str, symbol: str | None = None) -> list[WebSocket]:
        async with self._lock:
            subs = self._topic_subs.get(topic, {})
            if symbol:
                return [ws for ws, syms in subs.items() if not syms or symbol in syms]
            return list(subs.keys())

    async def disconnect(self, ws: WebSocket) -> None:
        await self.unsubscribe(ws)


_topic_manager = TopicConnectionManager()

_WS_SEND_TIMEOUT = 1.0


async def _safe_ws_send(ws: WebSocket, msg: str) -> None:
    await asyncio.wait_for(ws.send_text(msg), timeout=_WS_SEND_TIMEOUT)

_MAX_PUSH_SYMBOLS = 30

_PRIORITY_POSITION = "position"
_PRIORITY_WATCHLIST = "watchlist"
_PRIORITY_INDEX = "index"
_PRIORITY_NORMAL = "normal"
_PRIORITY_INTERVALS = {
    _PRIORITY_POSITION: 3,
    _PRIORITY_WATCHLIST: 5,
    _PRIORITY_INDEX: 5,
    _PRIORITY_NORMAL: 10,
}
_symbol_priority: dict[str, str] = {}
_symbol_last_push: dict[str, float] = {}
_symbol_state_lock = asyncio.Lock()
_index_symbols = {
    "sh000001", "sz399001", "sz399006",
    "hk00001", "hk00700",
    "us_dji", "us_ixic", "us_spx",
}


def _classify_symbol_priority(symbol: str) -> str:
    priority = _symbol_priority.get(symbol)
    if priority:
        return priority
    is_index_symbol = (
        symbol.lower().replace(".", "") in _index_symbols
        or symbol.startswith("sh")
        or symbol.startswith("sz")
    )
    has_index_code = any(idx in symbol for idx in ["000001", "399001", "399006"])
    if is_index_symbol and has_index_code:
        return _PRIORITY_INDEX
    return _PRIORITY_NORMAL


async def set_symbol_priority(symbol: str, priority: str) -> None:
    async with _symbol_state_lock:
        _symbol_priority[symbol] = priority


async def clear_symbol_priority(symbol: str) -> None:
    async with _symbol_state_lock:
        _symbol_priority.pop(symbol, None)


_trading_hours_cache: tuple[bool, float] = (False, 0.0)
_trading_hours_lock = threading.Lock()


def _is_trading_hours() -> bool:
    global _trading_hours_cache
    with _trading_hours_lock:
        cached_val, cached_ts = _trading_hours_cache
    if time.monotonic() - cached_ts < 30.0:
        return cached_val
    try:
        result = any(
            MarketHours.get_market_status(m).get("is_open")
            for m in ["A", "HK", "US"]
        )
        with _trading_hours_lock:
            _trading_hours_cache = (result, time.monotonic())
        return result
    except Exception as e:
        logger.debug("Market hours check failed: %s", e)
        return False



def cache_response(ttl_seconds: int):
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            cache_key = f"api:{request.method}:{func.__name__}:{request.url.path}:{request.url.query}"
            cached = _api_response_cache.get(cache_key)
            if cached is not None:
                etag = hashlib.md5(
                    orjson.dumps(cached, option=orjson.OPT_SORT_KEYS)
                ).hexdigest()[:16]
                if_none_match = request.headers.get("if-none-match", "")
                if if_none_match == etag:
                    return Response(status_code=304, headers={
                        "ETag": f'"{etag}"',
                        "Cache-Control": f"max-age={ttl_seconds}",
                        "X-Cache": "HIT",
                    })
                return JSONResponse(
                    content=cached,
                    status_code=200,
                    headers={
                        "X-Cache": "HIT",
                        "Cache-Control": f"max-age={ttl_seconds}",
                        "ETag": f'"{etag}"',
                    },
                )
            func_params = inspect.signature(func).parameters
            call_kwargs = dict(kwargs)
            if 'request' in func_params:
                call_kwargs['request'] = request
            result = await func(*args, **call_kwargs)
            if isinstance(result, Response):
                result.headers["Cache-Control"] = f"max-age={ttl_seconds}"
                result.headers["X-Cache"] = "MISS"
                try:
                    body = getattr(result, "body", b"")
                    if isinstance(body, bytes):
                        parsed = orjson.loads(body)
                    elif isinstance(body, dict):
                        parsed = body
                    else:
                        parsed = None
                    if parsed is not None:
                        _api_response_cache.set(cache_key, parsed, ttl=ttl_seconds)
                        etag = hashlib.md5(
                            orjson.dumps(parsed, option=orjson.OPT_SORT_KEYS)
                        ).hexdigest()[:16]
                        result.headers["ETag"] = f'"{etag}"'
                except Exception as e:
                    logger.debug("Cache serialization failed for %s: %s", cache_key, e)
                return result
            _api_response_cache.set(cache_key, result, ttl=ttl_seconds)
            if isinstance(result, dict):
                etag = hashlib.md5(
                    orjson.dumps(result, option=orjson.OPT_SORT_KEYS)
                ).hexdigest()[:16]
                return JSONResponse(
                    content=result,
                    status_code=200,
                    headers={
                        "Cache-Control": f"max-age={ttl_seconds}",
                        "X-Cache": "MISS",
                        "ETag": f'"{etag}"',
                    },
                )
            return result

        wrapper.__wrapped__ = func
        sig = inspect.signature(func)
        params = list(sig.parameters.values())
        has_request = any(p.name == 'request' for p in params)
        if not has_request:
            params.insert(0, inspect.Parameter('request', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request))
        wrapper.__signature__ = sig.replace(parameters=params)
        return wrapper
    return decorator


_MAX_SUBSCRIBE_SYMBOLS = 50

_WS_AUTH_ENABLED = os.environ.get("WS_AUTH_ENABLED", "false").lower() not in ("0", "false", "no")


async def _ws_authenticate(ws: WebSocket) -> bool:
    if not _WS_AUTH_ENABLED:
        return True
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001, reason="Authentication required")
        return False
    payload = decode_token(token)
    if payload is None:
        await ws.close(code=4001, reason="Invalid or expired token")
        return False
    return True


_pnl_connections: list[WebSocket] = []
_pnl_last_active: dict[WebSocket, float] = {}
_pnl_lock = asyncio.Lock()
_PNL_MAX_CONNECTIONS = 100
_PNL_STALE_TIMEOUT = 300

_signal_connections: list[WebSocket] = []
_signal_last_active: dict[WebSocket, float] = {}
_signal_lock = asyncio.Lock()
_SIGNAL_MAX_CONNECTIONS = 50
_SIGNAL_STALE_TIMEOUT = 300

_regime_connections: list[WebSocket] = []
_regime_last_active: dict[WebSocket, float] = {}
_regime_lock = asyncio.Lock()
_REGIME_MAX_CONNECTIONS = 50
_REGIME_STALE_TIMEOUT = 300
_REGIME_PUSH_INTERVAL = 30

_last_regimes: dict[str, str] = {}

_portfolio_connections: dict[WebSocket, dict[str, Any]] = {}
_portfolio_lock = asyncio.Lock()
_PORTFOLIO_MAX_CONNECTIONS = 50
_PORTFOLIO_PUSH_INTERVAL = 5.0
_PORTFOLIO_CACHE_TTL = 3600
_portfolio_metrics_cache: dict[str, Any] = {}
_portfolio_cache_timestamps: dict[str, float] = {}

_last_indices_hash = ""
_last_quote_hash: dict[str, str] = {}
_last_push_state: dict[str, dict] = {}
_push_seq = 0
_push_seq_lock = threading.Lock()
_push_state_lock = asyncio.Lock()


async def _evict_stale_push_state(stale_symbols: set[str]) -> None:
    if not stale_symbols:
        return
    all_subscribed = await _manager.get_all_subscribed_symbols()
    to_remove = stale_symbols - all_subscribed
    if not to_remove:
        return
    async with _push_state_lock:
        for sym in to_remove:
            _last_quote_hash.pop(sym, None)
            quotes_state = _last_push_state.get("quotes")
            if quotes_state and sym in quotes_state:
                del quotes_state[sym]


def _diff_push(old: dict, new: dict) -> dict:
    if not old:
        return dict(new)
    diff = {}
    for k, v in new.items():
        if k not in old or old[k] != v:
            diff[k] = v
    return diff


def _build_message(msg_type: str, data: dict) -> str:
    global _push_seq
    with _push_seq_lock:
        _push_seq += 1
        seq = _push_seq
    msg = {
        "type": msg_type,
        "ts": time.time(),
        "data": data,
        "seq": seq,
    }
    return orjson.dumps(msg, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS).decode("utf-8")


async def _check_price_alerts(quotes_data: dict):
    if not quotes_data:
        return
    try:
        try:
            import main as _main
            db = getattr(_main.app.state, 'db', None)
        except (ImportError, AttributeError):
            return

        if db is None:
            return

        active_alerts = db.fetch(
            "SELECT * FROM price_alerts WHERE enabled = 1 AND triggered = 0"
        )
        if not active_alerts:
            return

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        triggered_alerts = []

        for alert in active_alerts:
            sym = alert["symbol"]
            rt = quotes_data.get(sym)
            if not rt:
                continue
            current_price = rt.get("price", 0)
            if current_price <= 0:
                continue

            direction = alert["direction"]
            target = alert["target_price"]
            is_triggered = (direction == "above" and current_price >= target) or \
                           (direction == "below" and current_price <= target)

            if is_triggered:
                db.execute(
                    "UPDATE price_alerts SET triggered = 1, trigger_price = ?, trigger_time = ?, updated_at = ? WHERE id = ?",
                    (current_price, now_str, now_str, alert["id"])
                )
                triggered_alerts.append({
                    "id": alert["id"],
                    "symbol": sym,
                    "name": alert["name"],
                    "target_price": target,
                    "direction": direction,
                    "current_price": current_price,
                    "trigger_time": now_str,
                })

        if triggered_alerts:
            for alert_data in triggered_alerts:
                msg = _build_message("alert_triggered", alert_data)
                await _manager.broadcast(msg)
            logger.info("Triggered %d price alerts", len(triggered_alerts))
    except Exception as e:
        logger.debug("Alert check error: %s", e)



async def push_realtime_data(fetcher: SmartDataFetcher):
    global _last_indices_hash, _last_quote_hash, _last_push_state

    while True:
        try:
            if not await _manager.connection_count():
                await asyncio.sleep(5)
                continue

            if not _is_trading_hours():
                await asyncio.sleep(30)
                continue

            indices_data = {}
            try:
                overview = await fetcher.get_market_overview()
                cn = overview.get("cn_indices", {})
                hk = overview.get("hk_indices", {})
                us = overview.get("us_indices", {})
                indices_data = {**cn, **hk, **us}
            except Exception as e:
                logger.debug("Push indices fetch failed: %s", e)

            async with _push_state_lock:
                last_quote_hash_snapshot = dict(_last_quote_hash)
                subscribed = await _manager.get_all_subscribed_symbols()

            async with _symbol_state_lock:
                now = time.monotonic()
                stale_symbols = [s for s, t in _symbol_last_push.items()
                                 if not s.startswith("__") and now - t > 300]
                for s in stale_symbols:
                    del _symbol_last_push[s]
                    _symbol_priority.pop(s, None)

            quotes_data = {}
            subscribed_list = list(subscribed)[:_MAX_PUSH_SYMBOLS]
            async with _symbol_state_lock:
                now = time.monotonic()
                fetch_tasks = []
                fetch_symbols = []
                for symbol in subscribed_list:
                    priority = _classify_symbol_priority(symbol)
                    interval = _PRIORITY_INTERVALS.get(priority, 10)
                    last_push = _symbol_last_push.get(symbol, 0)
                    if now - last_push < interval:
                        continue
                    fetch_tasks.append(fetcher.get_realtime(symbol))
                    fetch_symbols.append(symbol)
            if fetch_tasks:
                results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                for symbol, result in zip(fetch_symbols, results, strict=True):
                    if isinstance(result, Exception):
                        logger.debug("Push quote fetch failed for %s: %s", symbol, result)
                        continue
                    rt = result
                    if rt and rt.get("price", 0) > 0:
                        price_str = f"{rt.get('price', 0)}_{rt.get('change_pct', 0)}"
                        if price_str != last_quote_hash_snapshot.get(symbol, ""):
                            quotes_data[symbol] = rt
            async with _symbol_state_lock:
                push_now = time.monotonic()
                for symbol in quotes_data:
                    _symbol_last_push[symbol] = push_now

            await _check_price_alerts(quotes_data)

            alert_engine = get_smart_alert_engine()
            smart_alerts = []
            for symbol, rt in quotes_data.items():
                price = rt.get("price", 0)
                volume = rt.get("volume", 0)
                name = rt.get("name", symbol)
                if price > 0:
                    detected = alert_engine.update(symbol, name, price, volume)
                    smart_alerts.extend(detected)
            if smart_alerts:
                for sa in smart_alerts:
                    msg = _build_message("smart_alert", {
                        "symbol": sa.symbol,
                        "name": sa.name,
                        "alert_type": sa.alert_type,
                        "z_score": sa.z_score,
                        "current_value": sa.current_value,
                        "mean_value": sa.mean_value,
                        "std_value": sa.std_value,
                    })
                    connections = await _manager.get_connections_snapshot()
                    if connections:
                        tasks = [_safe_ws_send(ws, msg) for ws in connections]
                        await asyncio.gather(*tasks, return_exceptions=True)

            msg_data: dict = {}
            async with _symbol_state_lock:
                last_indices_push = _symbol_last_push.get("__indices__", 0)
            async with _push_state_lock:
                indices_hash = json.dumps(indices_data, sort_keys=True)[:64] if indices_data else ""
                should_push_indices = False
                if indices_data and indices_hash != _last_indices_hash:
                    indices_interval = _PRIORITY_INTERVALS.get(_PRIORITY_INDEX, 5)
                    if now - last_indices_push >= indices_interval:
                        should_push_indices = True
                if should_push_indices:
                    _last_indices_hash = indices_hash

                current_subscribed = await _manager.get_all_subscribed_symbols()
                confirmed_quotes = {}
                for symbol, rt in quotes_data.items():
                    if symbol not in current_subscribed:
                        continue
                    price_str = f"{rt.get('price', 0)}_{rt.get('change_pct', 0)}"
                    current_hash = _last_quote_hash.get(symbol, "")
                    if price_str != current_hash:
                        confirmed_quotes[symbol] = rt
                        _last_quote_hash[symbol] = price_str

                if should_push_indices or confirmed_quotes:
                    if should_push_indices:
                        old_indices = _last_push_state.get("indices", {})
                        diff = _diff_push(old_indices, indices_data)
                        if diff:
                            msg_data["indices"] = diff
                            _last_push_state["indices"] = dict(indices_data)
                    if confirmed_quotes:
                        old_quotes = _last_push_state.get("quotes", {})
                        diff = _diff_push(old_quotes, confirmed_quotes)
                        if diff:
                            msg_data["quotes"] = diff
                            _last_push_state["quotes"] = dict(confirmed_quotes)

            if should_push_indices:
                async with _symbol_state_lock:
                    _symbol_last_push["__indices__"] = time.monotonic()

            if msg_data:
                msg_str = _build_message("quote_update", msg_data)
                connections = await _manager.get_connections_snapshot()
                if connections:
                    send_tasks = []
                    for ws in connections:
                        send_tasks.append(_safe_ws_send(ws, msg_str))
                    results = await asyncio.gather(*send_tasks, return_exceptions=True)
                    dead = [ws for ws, r in zip(connections, results, strict=True) if isinstance(r, Exception)]
                    for ws in dead:
                        await _manager.disconnect(ws)

            await asyncio.sleep(2)
        except Exception as e:
            logger.warning("Push realtime error: %s", e)
            await asyncio.sleep(10)


async def push_signal_event(symbol: str, strategy: str, signal_type: str, score: float, price: float):
    msg_str = _build_message("signal", {
        "symbol": symbol, "strategy": strategy,
        "signal_type": signal_type, "score": score, "price": price,
    })
    await _topic_manager.publish("signals", msg_str, symbol)


async def push_alert_event(symbol: str, alert_type: str, value: float, current_price: float):
    msg_str = _build_message("alert", {
        "symbol": symbol, "alert_type": alert_type,
        "value": value, "current_price": current_price,
    })
    await _topic_manager.publish("alerts", msg_str, symbol)


async def push_market_event(event_type: str, data: dict):
    msg_str = _build_message("market_event", data)
    await _topic_manager.publish("quotes", msg_str)


async def sweep_stale_pnl_connections() -> int:
    now = time.monotonic()
    stale = []
    async with _pnl_lock:
        for ws in list(_pnl_last_active):
            if now - _pnl_last_active.get(ws, 0) > _PNL_STALE_TIMEOUT:
                stale.append(ws)
    for ws in stale:
        with contextlib.suppress(Exception):
            await ws.close(code=1000, reason="Idle timeout")
        async with _pnl_lock:
            if ws in _pnl_connections:
                _pnl_connections.remove(ws)
            _pnl_last_active.pop(ws, None)
    return len(stale)


async def sweep_stale_signal_connections() -> int:
    now = time.monotonic()
    stale = []
    async with _signal_lock:
        for ws in list(_signal_last_active):
            if now - _signal_last_active.get(ws, 0) > _SIGNAL_STALE_TIMEOUT:
                stale.append(ws)
    for ws in stale:
        with contextlib.suppress(Exception):
            await ws.close(code=1000, reason="Idle timeout")
        async with _signal_lock:
            if ws in _signal_connections:
                _signal_connections.remove(ws)
            _signal_last_active.pop(ws, None)
    return len(stale)


async def push_regime_updates(fetcher: SmartDataFetcher):
    global _last_regimes
    while True:
        try:
            await asyncio.sleep(_REGIME_PUSH_INTERVAL)
            async with _regime_lock:
                conn_snapshot = list(_regime_connections)
            if not conn_snapshot:
                continue
            if not _is_trading_hours():
                continue
            try:
                overview = await fetcher.get_market_overview()
                indices = overview.get("cn_indices", {})
                symbols = list(indices.keys())[:10]
            except Exception as exc:
                logger.debug("Market overview fetch failed in regime push: %s", exc)
                symbols = ["000001", "399001", "399006"]
            for symbol in symbols:
                try:
                    df = await fetcher.get_history(symbol, period="3mo", kline_type="daily", adjust="qfq")
                    if df is None or len(df) < 30:
                        continue
                    from core.regime_detector import RegimeAdapter
                    adapter = RegimeAdapter(symbol)
                    regime = adapter.detect(df)
                    regime_str = regime.current_regime.value if hasattr(regime, "current_regime") else str(regime) if isinstance(regime, str) else "unknown"
                    prev = _last_regimes.get(symbol)
                    if prev is None or prev != regime_str:
                        _last_regimes[symbol] = regime_str
                        msg = {
                            "type": "regime_change",
                            "symbol": symbol,
                            "regime": regime_str,
                            "trend_strength": round(float(getattr(regime, "trend_strength", 0)), 3),
                            "volatility_level": round(float(getattr(regime, "volatility_level", 0)), 3),
                            "confidence": round(float(getattr(regime, "confidence", 0)), 3),
                            "timestamp": datetime.now().isoformat(),
                        }
                        for ws in conn_snapshot:
                            with contextlib.suppress(Exception):
                                await _safe_ws_send(ws, orjson.dumps(msg, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS).decode("utf-8"))
                except Exception as exc:
                    logger.debug("WebSocket send failed in regime push: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("Regime push error: %s", e)


async def sweep_stale_regime_connections() -> int:
    now = time.monotonic()
    stale = []
    async with _regime_lock:
        for ws in list(_regime_last_active):
            if now - _regime_last_active.get(ws, 0) > _REGIME_STALE_TIMEOUT:
                stale.append(ws)
        for ws in stale:
            _regime_connections.remove(ws)
            _regime_last_active.pop(ws, None)
    return len(stale)


async def push_portfolio_metrics(fetcher: SmartDataFetcher):
    global _portfolio_metrics_cache
    while True:
        try:
            await asyncio.sleep(_PORTFOLIO_PUSH_INTERVAL)

            now = time.monotonic()
            stale_keys = [
                k for k, ts in _portfolio_cache_timestamps.items()
                if now - ts > _PORTFOLIO_CACHE_TTL
            ]
            for k in stale_keys:
                _portfolio_metrics_cache.pop(k, None)
                _portfolio_cache_timestamps.pop(k, None)

            async with _portfolio_lock:
                conn_snapshot = dict(_portfolio_connections)

            if not conn_snapshot:
                continue

            all_symbols = set()
            for conn_info in conn_snapshot.values():
                all_symbols.update(conn_info["symbols"])

            if not all_symbols:
                continue

            price_map: dict[str, float] = {}
            change_map: dict[str, float] = {}

            for symbol in list(all_symbols)[:100]:
                try:
                    rt = await fetcher.get_realtime(symbol)
                    if rt and rt.get("price", 0) > 0:
                        price_map[symbol] = float(rt["price"])
                        change_map[symbol] = float(rt.get("change_pct", 0))
                except Exception as e:
                    logger.debug("Realtime fetch failed for %s in broadcast: %s", symbol, e)

            for ws, conn_info in conn_snapshot.items():
                try:
                    positions = conn_info["symbols"]
                    base_value = conn_info["base_value"]

                    positions_data = []
                    total_mv = 0.0
                    total_cost = 0.0
                    winners = 0
                    losers = 0

                    for symbol in positions:
                        if symbol not in price_map:
                            continue
                        entry_price = _portfolio_metrics_cache.get(f"{symbol}_entry", 0.0)
                        if entry_price <= 0:
                            entry_price = price_map[symbol]
                        shares = _portfolio_metrics_cache.get(f"{symbol}_shares", 0)
                        if shares <= 0:
                            shares = 100
                        current_price = price_map[symbol]
                        mv = current_price * shares
                        cost = entry_price * shares
                        pnl = mv - cost
                        pnl_pct = (current_price / entry_price - 1) * 100 if entry_price > 0 else 0
                        positions_data.append({
                            "symbol": symbol,
                            "current_price": round(current_price, 2),
                            "entry_price": round(entry_price, 2),
                            "shares": shares,
                            "market_value": round(mv, 2),
                            "cost": round(cost, 2),
                            "pnl": round(pnl, 2),
                            "pnl_pct": round(pnl_pct, 2),
                            "change_pct": round(change_map.get(symbol, 0), 2),
                        })
                        total_mv += mv
                        total_cost += cost
                        if pnl > 0:
                            winners += 1
                        elif pnl < 0:
                            losers += 1

                    total_pnl = total_mv - total_cost
                    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
                    day_return = (total_mv / base_value * 100 - 100) if base_value > 0 else 0

                    portfolio_msg = orjson.dumps({
                        "type": "portfolio_metrics",
                        "positions": positions_data,
                        "summary": {
                            "total_market_value": round(total_mv, 2),
                            "total_cost": round(total_cost, 2),
                            "total_pnl": round(total_pnl, 2),
                            "total_pnl_pct": round(total_pnl_pct, 2),
                            "day_return": round(day_return, 2),
                            "win_rate": round(winners / max(winners + losers, 1) * 100, 2),
                            "position_count": len(positions_data),
                        },
                        "ts": time.time(),
                    }, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS).decode("utf-8")
                    await _safe_ws_send(ws, portfolio_msg)
                except Exception as e:
                    logger.debug("Portfolio metrics推送失败: %s", e)
        except Exception as e:
            logger.warning("Portfolio metrics pusher异常: %s", e)
            await asyncio.sleep(5)


_SSE_MAX_SYMBOLS = 10
_SSE_KEEPALIVE_INTERVAL = 15

_ALLOWED_CONFIG_KEYS = {"watchlist", "portfolio_snapshot", "backtest_settings", "ui_settings", "alert_rules"}
