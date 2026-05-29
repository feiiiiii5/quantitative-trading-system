import asyncio
import json
import logging
import time
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from starlette.responses import StreamingResponse

from api.connection_manager import (
    _MAX_SUBSCRIBE_SYMBOLS,
    _PNL_MAX_CONNECTIONS,
    _PORTFOLIO_MAX_CONNECTIONS,
    _REGIME_MAX_CONNECTIONS,
    _SIGNAL_MAX_CONNECTIONS,
    _SSE_KEEPALIVE_INTERVAL,
    _SSE_MAX_SYMBOLS,
    _manager,
    _pnl_connections,
    _pnl_last_active,
    _pnl_lock,
    _portfolio_cache_timestamps,
    _portfolio_connections,
    _portfolio_lock,
    _portfolio_metrics_cache,
    _regime_connections,
    _regime_last_active,
    _regime_lock,
    _signal_connections,
    _signal_last_active,
    _signal_lock,
    _ws_authenticate,
)
from api.utils import json_response as _json_response
from api.utils import safe_error
from core.data_fetcher import SmartDataFetcher

logger = logging.getLogger(__name__)
router = APIRouter()

_WS_SEND_TIMEOUT = 2.0


async def _safe_send_json(ws: WebSocket, data: dict) -> None:
    await asyncio.wait_for(ws.send_json(data), timeout=_WS_SEND_TIMEOUT)


@router.websocket("/ws/realtime")
async def websocket_realtime(ws: WebSocket):
    if not await _ws_authenticate(ws):
        return
    accepted = await _manager.connect(ws)
    if not accepted:
        return
    try:
        while True:
            data = await ws.receive_text()
            await _manager.touch(ws)
            try:
                msg = json.loads(data)
                msg_type = msg.get("type", msg.get("action", ""))
                symbols = msg.get("symbols", [])
                if msg_type == "subscribe" and symbols:
                    await _manager.subscribe(ws, symbols[:_MAX_SUBSCRIBE_SYMBOLS])
                elif msg_type == "unsubscribe" and symbols:
                    await _manager.unsubscribe(ws, symbols[:_MAX_SUBSCRIBE_SYMBOLS])
                elif msg_type == "ping":
                    await _safe_send_json(ws, {"type": "pong", "ts": time.time()})
            except json.JSONDecodeError:
                logger.debug("WebSocket received non-JSON message")
    except WebSocketDisconnect:
        await _manager.disconnect(ws)
    except Exception as e:
        logger.warning("WebSocket实时连接异常: %s", e)
        await _manager.disconnect(ws)


@router.websocket("/ws/pnl")
async def websocket_pnl(ws: WebSocket):
    if not await _ws_authenticate(ws):
        return
    """实时盈亏推送WebSocket"""
    async with _pnl_lock:
        if len(_pnl_connections) >= _PNL_MAX_CONNECTIONS:
            await ws.close(code=1013, reason="Max PnL connections reached")
            return
        await ws.accept()
        _pnl_connections.append(ws)
        _pnl_last_active[ws] = time.monotonic()
    try:
        while True:
            data = await ws.receive_text()
            async with _pnl_lock:
                _pnl_last_active[ws] = time.monotonic()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await _safe_send_json(ws, {"type": "pong", "ts": time.time()})
                elif msg.get("type") == "get_pnl":
                    positions = msg.get("positions", [])
                    if not positions:
                        await _safe_send_json(ws, {"type": "pnl", "data": []})
                        continue
                    fetcher: SmartDataFetcher = ws.app.state.fetcher
                    pnl_data = []
                    for pos in positions[:20]:
                        sym = pos.get("symbol", "")
                        entry_price = float(pos.get("entry_price", 0))
                        shares = int(pos.get("shares", 0))
                        if not sym or entry_price <= 0 or shares <= 0:
                            continue
                        try:
                            rt = await fetcher.get_realtime(sym)
                            if rt and rt.get("price", 0) > 0:
                                current_price = float(rt["price"])
                                market_value = current_price * shares
                                cost = entry_price * shares
                                pnl = market_value - cost
                                pnl_pct = (current_price / entry_price - 1) * 100
                                pnl_data.append({
                                    "symbol": sym,
                                    "current_price": current_price,
                                    "entry_price": entry_price,
                                    "shares": shares,
                                    "market_value": round(market_value, 2),
                                    "cost": round(cost, 2),
                                    "pnl": round(pnl, 2),
                                    "pnl_pct": round(pnl_pct, 2),
                                    "change_pct": float(rt.get("change_pct", 0)),
                                })
                        except Exception as e:
                            logger.debug("WebSocket PnL calc error for %s: %s", sym, e)
                            continue
                    total_pnl = sum(p["pnl"] for p in pnl_data)
                    total_cost = sum(p["cost"] for p in pnl_data)
                    total_mv = sum(p["market_value"] for p in pnl_data)
                    await _safe_send_json(ws, {
                        "type": "pnl",
                        "data": pnl_data,
                        "summary": {
                            "total_pnl": round(total_pnl, 2),
                            "total_cost": round(total_cost, 2),
                            "total_market_value": round(total_mv, 2),
                            "total_pnl_pct": round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0,
                            "position_count": len(pnl_data),
                        },
                        "ts": time.time(),
                    })
            except json.JSONDecodeError:
                logger.debug("WebSocket received non-JSON message")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WebSocket PnL连接异常: %s", e)
    finally:
        async with _pnl_lock:
            if ws in _pnl_connections:
                _pnl_connections.remove(ws)
            _pnl_last_active.pop(ws, None)


@router.websocket("/ws/signals")
async def websocket_signals(ws: WebSocket):
    if not await _ws_authenticate(ws):
        return
    """实时交易信号推送WebSocket"""
    async with _signal_lock:
        if len(_signal_connections) >= _SIGNAL_MAX_CONNECTIONS:
            await ws.close(code=1013, reason="Max signal connections reached")
            return
        await ws.accept()
        _signal_connections.append(ws)
        _signal_last_active[ws] = time.monotonic()
    try:
        while True:
            data = await ws.receive_text()
            async with _signal_lock:
                _signal_last_active[ws] = time.monotonic()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await _safe_send_json(ws, {"type": "pong", "ts": time.time()})
                elif msg.get("type") == "subscribe":
                    symbols = msg.get("symbols", [])[:10]
                    if not symbols:
                        await _safe_send_json(ws, {"type": "error", "message": "No symbols provided"})
                        continue
                    fetcher: SmartDataFetcher = ws.app.state.fetcher
                    from core.strategies import CompositeStrategy
                    composite = CompositeStrategy()
                    signal_data = []
                    for symbol in symbols:
                        try:
                            df = await fetcher.get_history(symbol, period="3mo", kline_type="daily", adjust="qfq")
                            if df is None or len(df) < 30:
                                continue
                            for s in composite.strategies:
                                s.reset()
                            latest_sigs = []
                            for i in range(max(0, len(df) - 30), len(df)):
                                row = df.iloc[i]
                                bar = {
                                    "open": float(row.get("open", 0)) if pd.notna(row.get("open")) else 0,
                                    "high": float(row.get("high", 0)) if pd.notna(row.get("high")) else 0,
                                    "low": float(row.get("low", 0)) if pd.notna(row.get("low")) else 0,
                                    "close": float(row.get("close", 0)) if pd.notna(row.get("close")) else 0,
                                    "volume": float(row.get("volume", 0)) if pd.notna(row.get("volume")) else 0,
                                    "date": str(row.get("date", ""))[:10] if "date" in df.columns else "",
                                    "symbol": symbol,
                                }
                                for s in composite.strategies:
                                    sigs = s.on_bar(bar, {})
                                    for sig in sigs:
                                        latest_sigs.append({
                                            "strategy": type(s).__name__,
                                            "signal": sig.get("action", "hold"),
                                            "confidence": sig.get("confidence", 0),
                                            "reason": sig.get("reason", ""),
                                        })
                            if latest_sigs:
                                rt = await fetcher.get_realtime(symbol)
                                price = float(rt.get("price", df["close"].iloc[-1])) if rt else float(df["close"].iloc[-1])
                                signal_data.append({
                                    "symbol": symbol,
                                    "signal": latest_sigs[-1]["signal"],
                                    "strength": latest_sigs[-1]["confidence"],
                                    "reason": latest_sigs[-1]["reason"],
                                    "price": price,
                                    "change_pct": float(rt.get("change_pct", 0)) if rt else 0,
                                    "all_signals": latest_sigs,
                                })
                        except Exception as e:
                            logger.debug("Signal WebSocket error for %s: %s", symbol, e)
                            continue
                    await _safe_send_json(ws, {
                        "type": "signals",
                        "data": signal_data,
                        "ts": time.time(),
                    })
            except json.JSONDecodeError:
                logger.debug("WebSocket received non-JSON message")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WebSocket Signal连接异常: %s", e)
    finally:
        async with _signal_lock:
            if ws in _signal_connections:
                _signal_connections.remove(ws)
            _signal_last_active.pop(ws, None)


@router.websocket("/ws/regime")
async def websocket_regime(ws: WebSocket):
    if not await _ws_authenticate(ws):
        return
    async with _regime_lock:
        if len(_regime_connections) >= _REGIME_MAX_CONNECTIONS:
            await ws.close(code=1013, reason="Max regime connections reached")
            return
        await ws.accept()
        _regime_connections.append(ws)
        _regime_last_active[ws] = time.monotonic()
    try:
        await _safe_send_json(ws, {
            "type": "connected",
            "message": "Subscribed to market regime stream",
            "ts": time.time(),
        })
        while True:
            data = await ws.receive_text()
            async with _regime_lock:
                _regime_last_active[ws] = time.monotonic()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await _safe_send_json(ws, {"type": "pong", "ts": time.time()})
                elif msg.get("type") == "subscribe":
                    symbols = msg.get("symbols", [])[:20]
                    if not symbols:
                        await _safe_send_json(ws, {"type": "error", "message": "No symbols provided"})
                        continue
                    fetcher: SmartDataFetcher = ws.app.state.fetcher
                    from core.regime_detector import RegimeAdapter
                    regime_data = []
                    for symbol in symbols:
                        try:
                            df = await fetcher.get_history(symbol, period="3mo", kline_type="daily", adjust="qfq")
                            if df is None or len(df) < 30:
                                continue
                            adapter = RegimeAdapter(symbol)
                            regime = adapter.detect(df)
                            regime_data.append({
                                "symbol": symbol,
                                "regime": regime.current_regime.value if hasattr(regime, "current_regime") else str(regime) if isinstance(regime, str) else "unknown",
                                "trend_strength": round(float(getattr(regime, "trend_strength", 0)), 3),
                                "volatility_level": round(float(getattr(regime, "volatility_level", 0)), 3),
                                "confidence": round(float(getattr(regime, "confidence", 0)), 3),
                                "timestamp": datetime.now().isoformat(),
                            })
                        except Exception as e:
                            logger.debug("Regime WebSocket error for %s: %s", symbol, e)
                            continue
                    await _safe_send_json(ws, {
                        "type": "regime_data",
                        "data": regime_data,
                        "ts": time.time(),
                    })
            except json.JSONDecodeError:
                logger.debug("WebSocket received non-JSON message")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WebSocket Regime连接异常: %s", e)
    finally:
        async with _regime_lock:
            if ws in _regime_connections:
                _regime_connections.remove(ws)
            _regime_last_active.pop(ws, None)


@router.websocket("/ws/portfolio/metrics")
async def websocket_portfolio_metrics(ws: WebSocket):
    if not await _ws_authenticate(ws):
        return
    async with _portfolio_lock:
        if len(_portfolio_connections) >= _PORTFOLIO_MAX_CONNECTIONS:
            await ws.close(code=1013, reason="Max portfolio connections reached")
            return
        await ws.accept()
        _portfolio_connections[ws] = {
            "symbols": set(),
            "base_value": 0.0,
            "last_pnl": 0.0,
        }
    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=60.0)
                msg = json.loads(raw)
                msg_type = msg.get("type", "")
                if msg_type == "ping":
                    await _safe_send_json(ws, {"type": "pong", "ts": time.time()})
                elif msg_type == "configure":
                    positions = msg.get("positions", [])
                    base_value = float(msg.get("base_value", 0))
                    symbols = [p.get("symbol") for p in positions if p.get("symbol")]
                    async with _portfolio_lock:
                        if ws in _portfolio_connections:
                            _portfolio_connections[ws]["symbols"] = set(symbols)
                            _portfolio_connections[ws]["base_value"] = base_value
                    for pos in positions:
                        sym = pos.get("symbol")
                        if sym:
                            entry_price = float(pos.get("entry_price", 0))
                            shares = int(pos.get("shares", 0))
                            key_entry = f"{sym}_entry"
                            key_shares = f"{sym}_shares"
                            _portfolio_metrics_cache[key_entry] = entry_price
                            _portfolio_metrics_cache[key_shares] = shares
                            now = time.time()
                            _portfolio_cache_timestamps[key_entry] = now
                            _portfolio_cache_timestamps[key_shares] = now
                    await _safe_send_json(ws, {
                        "type": "configured",
                        "symbol_count": len(symbols),
                        "base_value": base_value,
                        "ts": time.time(),
                    })
            except TimeoutError:
                await _safe_send_json(ws, {"type": "keepalive", "ts": time.time()})
            except json.JSONDecodeError:
                logger.debug("WebSocket received non-JSON message")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WebSocket portfolio连接异常: %s", e)
    finally:
        async with _portfolio_lock:
            _portfolio_connections.pop(ws, None)


@router.get("/sse/realtime")
async def sse_realtime(request: Request, symbols: str = Query("", max_length=500)):
    if not symbols:
        return _json_response(False, error="symbols参数不能为空，逗号分隔")

    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()][:_SSE_MAX_SYMBOLS]
    if not symbol_list:
        return _json_response(False, error="无效的股票代码")

    async def _event_stream():
        fetcher = getattr(request.app.state, "fetcher", None)
        if fetcher is None:
            yield f"data: {json.dumps({'error': '数据源未初始化'})}\n\n"
            return

        while True:
            if await request.is_disconnected():
                break
            try:
                results = await fetcher.get_realtime_batch(symbol_list)
                for sym, data in results.items():
                    event_data = {"symbol": sym, **data}
                    yield f"data: {json.dumps(event_data, default=str)}\n\n"
            except Exception as e:
                logger.debug("SSE realtime error: %s", e)
                yield f"data: {json.dumps({'error': safe_error(e)})}\n\n"

            try:
                await asyncio.wait_for(
                    asyncio.create_task(asyncio.sleep(_SSE_KEEPALIVE_INTERVAL)),
                    timeout=_SSE_KEEPALIVE_INTERVAL + 1,
                )
            except asyncio.CancelledError:
                break
            yield ": keepalive\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
