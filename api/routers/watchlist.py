import asyncio
import logging
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Form, Path, Query, Request

from api.connection_manager import set_symbol_priority, clear_symbol_priority, _PRIORITY_WATCHLIST
from api.routers.models import (
    AlertAddRequest,
    AlertRemoveRequest,
    WatchlistAddRemoveRequest,
    WatchlistReorderRequest,
)
from api.utils import json_response as _json_response
from api.utils import safe_error, validate_symbol
from core.data_fetcher import SmartDataFetcher
from core.database import get_db
from core.market_detector import MarketDetector
from core.smart_alerts import get_smart_alert_engine

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/watchlist")
async def get_watchlist(request: Request):
    try:
        db = get_db()
        watchlist = db.get_config("watchlist", [])
        if not isinstance(watchlist, list):
            watchlist = []

        fetcher: SmartDataFetcher = request.app.state.fetcher

        a_symbols = []
        other_symbols = []
        for symbol in watchlist:
            market = MarketDetector.detect(symbol)
            if market == "A":
                a_symbols.append(symbol)
            else:
                other_symbols.append(symbol)

        results = {}
        if a_symbols:
            batch_results = await fetcher.get_realtime_batch(a_symbols)
            results.update(batch_results)

        if other_symbols:
            tasks = [fetcher.get_realtime(s) for s in other_symbols]
            other_results = await asyncio.gather(*tasks, return_exceptions=True)
            for symbol, result in zip(other_symbols, other_results, strict=False):
                if isinstance(result, dict):
                    results[symbol] = result

        return _json_response(True, data={"symbols": watchlist, "quotes": results})
    except Exception as e:
        logger.error("Watchlist error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/watchlist/add")
async def add_to_watchlist(request: Request, body: WatchlistAddRemoveRequest):
    try:
        db = get_db()
        watchlist = db.get_config("watchlist", [])
        if not isinstance(watchlist, list):
            watchlist = []
        if body.symbol not in watchlist:
            watchlist.append(body.symbol)
            db.set_config("watchlist", watchlist)
        await set_symbol_priority(body.symbol, _PRIORITY_WATCHLIST)
        return _json_response(True, data=watchlist)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/watchlist/remove")
async def remove_from_watchlist(request: Request, body: WatchlistAddRemoveRequest):
    try:
        db = get_db()
        watchlist = db.get_config("watchlist", [])
        if not isinstance(watchlist, list):
            watchlist = []
        if body.symbol in watchlist:
            watchlist.remove(body.symbol)
            db.set_config("watchlist", watchlist)
        await clear_symbol_priority(body.symbol)
        return _json_response(True, data=watchlist)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/watchlist/reorder")
async def reorder_watchlist(request: Request, body: WatchlistReorderRequest):
    """重新排序自选股列表"""
    try:
        db = get_db()
        watchlist = db.get_config("watchlist", [])
        if not isinstance(watchlist, list):
            watchlist = []
        new_order = [s.strip() for s in body.symbols.split(",") if s.strip()]
        reordered = [s for s in new_order if s in watchlist]
        remaining = [s for s in watchlist if s not in set(new_order)]
        watchlist = reordered + remaining
        db.set_config("watchlist", watchlist)
        return _json_response(True, data=watchlist)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/watchlist/alert/add")
async def add_price_alert(
    request: Request,
    body: AlertAddRequest,
):
    """添加价格预警"""
    try:
        if not validate_symbol(body.symbol):
            return _json_response(False, error="Invalid symbol")
        if body.value <= 0:
            return _json_response(False, error="Value must be a positive number")
        db = get_db()
        alerts = db.get_config("price_alerts", [])
        if not isinstance(alerts, list):
            alerts = []

        alert = {
            "id": str(uuid.uuid4())[:8],
            "symbol": body.symbol,
            "alert_type": body.alert_type,
            "value": body.value,
            "triggered": False,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        alerts.append(alert)
        db.set_config("price_alerts", alerts)
        return _json_response(True, data=alert)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/watchlist/alert/list")
async def get_price_alerts(request: Request, symbol: str = Query(None)):
    """获取价格预警列表"""
    try:
        db = get_db()
        alerts = db.get_config("price_alerts", [])
        if not isinstance(alerts, list):
            alerts = []
        if symbol:
            alerts = [a for a in alerts if a.get("symbol") == symbol]
        return _json_response(True, data=alerts)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/watchlist/alert/remove")
async def remove_price_alert(request: Request, body: AlertRemoveRequest):
    """删除价格预警"""
    try:
        db = get_db()
        alerts = db.get_config("price_alerts", [])
        if not isinstance(alerts, list):
            alerts = []
        alerts = [a for a in alerts if a.get("id") != body.alert_id]
        db.set_config("price_alerts", alerts)
        return _json_response(True, data={"removed": body.alert_id})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/alerts")
async def get_alerts(request: Request, enabled: str | None = Query(None)):
    try:
        db = request.app.state.db
        if enabled == "true":
            rows = db.fetch("SELECT * FROM price_alerts WHERE enabled = 1 ORDER BY created_at DESC LIMIT 1000")
        elif enabled == "false":
            rows = db.fetch("SELECT * FROM price_alerts WHERE enabled = 0 ORDER BY created_at DESC LIMIT 1000")
        else:
            rows = db.fetch("SELECT * FROM price_alerts ORDER BY created_at DESC LIMIT 1000")
        return _json_response(True, data=rows)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/alerts")
async def create_alert(request: Request,
                       symbol: str = Form(...),
                       target_price: float = Form(...),
                       direction: str = Form("above"),
                       name: str = Form("")):
    try:
        if not validate_symbol(symbol):
            return _json_response(False, error="Invalid symbol")
        if target_price <= 0:
            return _json_response(False, error="Target price must be positive")
        if direction not in ("above", "below"):
            return _json_response(False, error="Direction must be 'above' or 'below'")

        db = request.app.state.db
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alert_id = db.insert(
            "INSERT INTO price_alerts (symbol, name, target_price, direction, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (symbol, (name or symbol), target_price, direction, now, now)
        )
        return _json_response(True, data={"id": alert_id})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.put("/alerts/{alert_id}")
async def update_alert(request: Request, alert_id: int,
                       target_price: float = Form(None),
                       direction: str = Form(None),
                       enabled: bool = Form(None),
                       name: str = Form(None)):
    try:
        db = request.app.state.db
        existing = db.fetch("SELECT * FROM price_alerts WHERE id = ? LIMIT 1", (alert_id,))
        if not existing:
            return _json_response(False, error="Alert not found")

        updates = []
        params = []
        if target_price is not None:
            if target_price <= 0:
                return _json_response(False, error="Target price must be positive")
            updates.append("target_price = ?")
            params.append(target_price)
        if direction is not None:
            if direction not in ("above", "below"):
                return _json_response(False, error="Direction must be 'above' or 'below'")
            updates.append("direction = ?")
            params.append(direction)
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if not updates:
            return _json_response(False, error="No fields to update")

        updates.append("updated_at = ?")
        params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        params.append(alert_id)
        set_clause = ", ".join(updates)
        db.execute(f"UPDATE price_alerts SET {set_clause} WHERE id = ?", tuple(params))
        return _json_response(True, data={"id": alert_id})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.delete("/alerts/{alert_id}")
async def delete_alert(request: Request, alert_id: int):
    try:
        db = request.app.state.db
        existing = db.fetch("SELECT id FROM price_alerts WHERE id = ? LIMIT 1", (alert_id,))
        if not existing:
            return _json_response(False, error="Alert not found")
        db.execute("DELETE FROM price_alerts WHERE id = ?", (alert_id,))
        return _json_response(True, data={"id": alert_id})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/alerts/history")
async def get_alert_history(request: Request, limit: int = Query(50)):
    try:
        db = request.app.state.db
        rows = db.fetch(
            "SELECT * FROM price_alerts WHERE triggered = 1 ORDER BY trigger_time DESC LIMIT ?",
            (min(limit, 200),)
        )
        return _json_response(True, data=rows)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/smart-alerts/history")
async def get_smart_alert_history(limit: int = Query(50, ge=1, le=200)):
    engine = get_smart_alert_engine()
    history = engine.get_alert_history(limit=limit)
    return _json_response(True, data={"alerts": history, "count": len(history)})


@router.get("/smart-alerts/stats/{symbol}")
async def get_smart_alert_stats(symbol: str = Path(..., min_length=1, max_length=10)):
    engine = get_smart_alert_engine()
    stats = engine.get_stats(symbol)
    if stats is None:
        return _json_response(False, error=f"无统计数据: {symbol}")
    return _json_response(True, data=stats)
