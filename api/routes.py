"""
QuantCore API路由模块
提供REST API、WebSocket实时推送和SSE流式回测进度
"""
import asyncio
import contextlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from functools import wraps
from itertools import combinations
from typing import Any

import numpy as np
import orjson
import pandas as pd
from fastapi import APIRouter, Form, Path, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.auth import authenticate_user, create_token, create_user, decode_token, require_auth
from api.backtest_routes import BacktestAdvancedRequest
from api.utils import json_response as _json_response
from api.utils import get_trading, rate_limiter, safe_error, validate_symbol
from core.data_fetcher import SmartDataFetcher, get_fetcher
from core.database import SQLiteStore, ThreadSafeLRU, get_db
from core.indicators import (
    IndicatorAnalysis,
    KLinePatternRecognizer,
    TechnicalIndicators,
    calc_all_indicators,
)
from core.market_detector import MarketDetector
from core.market_hours import MarketHours
from core.smart_alerts import get_smart_alert_engine
from core.strategies import STRATEGY_REGISTRY, CompositeStrategy

logger = logging.getLogger(__name__)

router = APIRouter()

_start_time = time.time()


class _TTLCache:
    __slots__ = ("_cache", "_ttl", "_maxsize", "_freq")

    def __init__(self, ttl: float = 3.0, maxsize: int = 5000) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._freq: dict[str, int] = {}
        self._ttl = ttl
        self._maxsize = maxsize

    def get(self, key: str) -> Any:
        entry = self._cache.get(key)
        if entry is not None:
            ts, val = entry
            if time.monotonic() - ts < self._ttl:
                self._freq[key] = self._freq.get(key, 0) + 1
                return val
            del self._cache[key]
            self._freq.pop(key, None)
        return None

    def set(self, key: str, val: Any) -> None:
        if len(self._cache) >= self._maxsize:
            self._evict()
        self._cache[key] = (time.monotonic(), val)
        self._freq[key] = 1

    def _evict(self) -> None:
        if not self._cache:
            return
        stale = [k for k in self._freq if k not in self._cache]
        for k in stale:
            del self._freq[k]
        if not self._freq:
            return
        min_freq = min(self._freq.values())
        candidates = [k for k, f in self._freq.items() if f == min_freq]
        oldest_key = min(candidates, key=lambda k: self._cache[k][0])
        del self._cache[oldest_key]
        del self._freq[oldest_key]

    def clear(self) -> None:
        self._cache.clear()
        self._freq.clear()

    def __len__(self) -> int:
        return len(self._cache)

    def stats(self) -> dict[str, int]:
        return {"size": len(self._cache), "freq_entries": len(self._freq), "maxsize": self._maxsize}


_rt_cache = _TTLCache(ttl=8.0, maxsize=15000)
_kline_cache = _TTLCache(ttl=60.0, maxsize=6000)
_strategy_list_cache = _TTLCache(ttl=120.0, maxsize=200)


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)


@router.post("/auth/login")
@rate_limiter(max_calls=10, time_window=60.0)
async def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        return _json_response(False, error="用户名或密码错误")
    token = create_token(user)
    return _json_response(True, data={
        "token": token,
        "username": user["username"],
        "role": user["role"],
    })


@router.post("/auth/register")
@rate_limiter(max_calls=5, time_window=60.0)
async def register(req: RegisterRequest, current_user: dict | None = None):
    if current_user is None:
        current_user = await require_auth()
    if current_user.get("role") != "admin":
        return _json_response(False, error="仅管理员可创建用户")
    ok = create_user(req.username, req.password)
    if not ok:
        return _json_response(False, error="注册失败：用户名已存在或密码不符合要求")
    return _json_response(True, data={"username": req.username})


@router.get("/auth/me")
async def me(user: dict | None = None):
    if user is None:
        user = await require_auth()
    return _json_response(True, data={
        "username": user.get("sub"),
        "role": user.get("role"),
    })


@router.get("/readiness")
async def readiness_check(request: Request):
    checks = {}
    try:
        db = get_db()
        db.fetchone("SELECT 1")
        checks["database"] = "ready"
    except Exception as e:
        checks["database"] = "error"
        logger.warning("Readiness DB check failed: %s", e)
        return {
            "status": "not_ready",
            "checks": checks,
            "timestamp": datetime.now().isoformat(),
        }

    try:
        fetcher = getattr(request.app.state, "fetcher", None)
        if fetcher is not None:
            checks["data_fetcher"] = "ready"
        else:
            checks["data_fetcher"] = "not_initialized"
    except Exception as e:
        checks["data_fetcher"] = "error"
        logger.warning("Readiness fetcher check failed: %s", e)

    return {"status": "ready", "checks": checks, "timestamp": datetime.now().isoformat()}


@router.get("/api-info")
async def api_info(request: Request):
    routes_info = []
    for route in request.app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                if method in ("GET", "POST", "PUT", "DELETE"):
                    routes_info.append({"method": method, "path": route.path})
                    break

    return {
        "version": "2.1.0",
        "name": "QuantCore API",
        "description": "量化交易系统 REST API",
        "endpoint_count": len(routes_info),
        "endpoints": sorted(routes_info, key=lambda r: r["path"]),
    }


@router.get("/performance")
async def performance_metrics(request: Request):
    app = request.app
    request_count = getattr(app.state, "_request_count", 0)
    total_rt = getattr(app.state, "_total_response_time", 0.0)
    error_count = getattr(app.state, "_error_count", 0)
    buckets = getattr(app.state, "_latency_buckets", {})
    start_time = getattr(app.state, "start_time", time.time())
    uptime = time.time() - start_time
    avg_rt = total_rt / request_count if request_count > 0 else 0
    rps = request_count / uptime if uptime > 0 else 0
    p50_bucket = p95_bucket = "N/A"
    cumulative = 0
    for bucket_name in ["<10ms", "10-50ms", "50-100ms", "100-500ms", "500ms-1s", "1s-5s", ">5s"]:
        cumulative += buckets.get(bucket_name, 0)
        if p50_bucket == "N/A" and cumulative >= request_count * 0.5:
            p50_bucket = bucket_name
        if p95_bucket == "N/A" and cumulative >= request_count * 0.95:
            p95_bucket = bucket_name
    return {
        "uptime_seconds": round(uptime, 1),
        "uptime_human": f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m",
        "requests": {
            "total": request_count,
            "errors": error_count,
            "error_rate": round(error_count / request_count * 100, 2) if request_count > 0 else 0,
            "rps": round(rps, 2),
        },
        "latency": {
            "avg_ms": round(avg_rt, 2),
            "p50_bucket": p50_bucket,
            "p95_bucket": p95_bucket,
            "histogram": dict(buckets),
        },
        "websocket": {
            "active_connections": await _manager.connection_count(),
            "max_connections": ConnectionManager.MAX_CONNECTIONS,
        },
    }


CHINA_HOLIDAYS: dict[int, dict[str, str]] = {
    2026: {
        "2026-01-01": "元旦",
        "2026-01-02": "元旦假期",
        "2026-02-16": "春节",
        "2026-02-17": "春节",
        "2026-02-18": "春节",
        "2026-02-19": "春节",
        "2026-02-20": "春节假期",
        "2026-02-21": "春节假期",
        "2026-02-22": "春节假期",
        "2026-04-03": "清明节",
        "2026-04-04": "清明节",
        "2026-04-05": "清明节假期",
        "2026-05-01": "劳动节",
        "2026-05-02": "劳动节",
        "2026-05-03": "劳动节假期",
        "2026-06-19": "端午节",
        "2026-06-20": "端午节假期",
        "2026-06-21": "端午节假期",
        "2026-09-24": "中秋节",
        "2026-09-25": "中秋节假期",
        "2026-09-26": "中秋节假期",
        "2026-10-01": "国庆节",
        "2026-10-02": "国庆节",
        "2026-10-03": "国庆节",
        "2026-10-04": "国庆节假期",
        "2026-10-05": "国庆节假期",
        "2026-10-06": "国庆节假期",
        "2026-10-07": "国庆节假期",
    },
    2025: {
        "2025-01-01": "元旦",
        "2025-01-28": "春节",
        "2025-01-29": "春节",
        "2025-01-30": "春节",
        "2025-01-31": "春节",
        "2025-02-01": "春节假期",
        "2025-02-02": "春节假期",
        "2025-02-03": "春节假期",
        "2025-04-04": "清明节",
        "2025-04-05": "清明节假期",
        "2025-04-06": "清明节假期",
        "2025-05-01": "劳动节",
        "2025-05-02": "劳动节",
        "2025-05-03": "劳动节假期",
        "2025-05-31": "端午节",
        "2025-06-01": "端午节假期",
        "2025-06-02": "端午节假期",
        "2025-09-06": "中秋节",
        "2025-09-07": "中秋节假期",
        "2025-09-08": "中秋节假期",
        "2025-10-01": "国庆节",
        "2025-10-02": "国庆节",
        "2025-10-03": "国庆节",
        "2025-10-04": "国庆节假期",
        "2025-10-05": "国庆节假期",
        "2025-10-06": "国庆节假期",
        "2025-10-07": "国庆节假期",
        "2025-10-08": "国庆节假期",
    },
}

CHINA_WORKDAYS: dict[int, dict[str, str]] = {
    2026: {
        "2026-01-03": "元旦调休",
        "2026-02-15": "春节调休",
        "2026-02-23": "春节调休",
        "2026-04-12": "清明调休",
        "2026-04-26": "劳动节调休",
        "2026-06-07": "端午调休",
        "2026-09-20": "中秋调休",
        "2026-10-10": "国庆调休",
    },
    2025: {
        "2025-01-26": "春节调休",
        "2025-02-08": "春节调休",
        "2025-04-27": "劳动节调休",
        "2025-09-28": "中秋调休",
        "2025-09-30": "国庆调休",
    },
}


def _is_cn_trading_day(date_obj: date) -> tuple:
    year = date_obj.year
    date_str = date_obj.strftime("%Y-%m-%d")
    year_workdays = CHINA_WORKDAYS.get(year, {})
    year_holidays = CHINA_HOLIDAYS.get(year, {})
    if date_str in year_workdays:
        return True, year_workdays[date_str]
    if date_str in year_holidays:
        return False, year_holidays[date_str]
    if date_obj.weekday() >= 5:
        return False, "周末"
    return True, "交易日"


@router.get("/calendar/check")
async def check_trading_day(d: str = None):
    if d:
        try:
            date_obj = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            return _json_response(False, error="日期格式错误，请使用 YYYY-MM-DD")
    else:
        date_obj = datetime.now().date()

    is_trading, reason = _is_cn_trading_day(date_obj)
    return _json_response(True, data={
        "date": date_obj.isoformat(),
        "is_trading_day": is_trading,
        "reason": reason,
        "weekday": date_obj.strftime("%A"),
    })


@router.get("/calendar/next")
async def next_trading_day(d: str | None = Query(None, pattern=r'^\d{4}-\d{2}-\d{2}$'), count: int = Query(1, ge=1, le=60)):
    try:
        from_date = datetime.strptime(d, "%Y-%m-%d").date() if d else datetime.now().date()
    except ValueError:
        return _json_response(False, error="日期格式错误，请使用 YYYY-MM-DD")

    result = []
    current = from_date + timedelta(days=1)
    while len(result) < count:
        is_trading, _ = _is_cn_trading_day(current)
        if is_trading:
            result.append({"date": current.isoformat(), "weekday": current.strftime("%A")})
        current += timedelta(days=1)

    return {"from": from_date.isoformat(), "count": count, "next_trading_days": result}


@router.get("/calendar/holidays")
async def list_holidays(month: int | None = Query(None, ge=1, le=12)):
    now = datetime.now()
    holidays = []
    for date_str, name in sorted(d for year_holidays in CHINA_HOLIDAYS.values() for d in year_holidays.items()):
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        if month and d.month != month:
            continue
        if d >= now.date() or month:
            holidays.append({"date": date_str, "name": name})
    return {"holidays": holidays, "total": len(holidays)}


@router.get("/status")
async def system_status(request: Request):
    db = get_db()
    pool_status = db.get_pool_status()
    process_time = time.time() - _start_time

    try:
        import os

        import psutil
        process = psutil.Process(os.getpid())
        memory_mb = round(process.memory_info().rss / (1024 * 1024), 1)
        cpu_percent = round(process.cpu_percent(interval=0.1), 1)
    except Exception as e:
        memory_mb = 0
        cpu_percent = 0
        logger.debug("psutil metrics failed: %s", e)

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": round(process_time, 1),
        "memory_mb": memory_mb,
        "cpu_percent": cpu_percent,
        "database": pool_status,
    }


@router.get("/data/quality/{symbol}")
async def get_data_quality(symbol: str, request: Request):
    try:
        _validate_symbol(symbol)
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="1y", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="无法获取数据")

        from core.data_governance import AnomalyDetector, DataQualityPipeline
        pipeline = DataQualityPipeline()
        processed_df = pipeline.process(df, symbol)

        detector = AnomalyDetector()
        anomalies = detector.detect_all(df, symbol)

        total_cells = len(df) * len(df.columns)
        null_count = int(df.isnull().sum().sum())
        completeness = round(1 - null_count / max(total_cells, 1), 4)

        suspension_days = 0
        if "is_suspended" in processed_df.columns:
            suspension_days = int(processed_df["is_suspended"].sum())

        anomaly_days = 0
        if "is_anomaly" in processed_df.columns:
            anomaly_days = int(processed_df["is_anomaly"].sum())

        anomaly_list = [
            {
                "date": a.date,
                "type": a.anomaly_type,
                "severity": a.severity,
                "detail": a.details if hasattr(a, "details") else "",
            }
            for a in anomalies[:20]
        ]

        return _json_response(True, data={
            "symbol": symbol,
            "total_bars": len(df),
            "suspension_days": suspension_days,
            "anomaly_days": anomaly_days,
            "anomalies": anomaly_list,
            "data_completeness": completeness,
        })
    except ValueError as e:
        return _json_response(False, error=str(e))
    except Exception as e:
        logger.error("data quality check error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))

def _validate_symbol(symbol: str) -> str:
    if not validate_symbol(symbol):
        raise ValueError("股票代码格式无效")
    return symbol


class BuyOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10, pattern=r'^[0-9a-zA-Z]{1,10}$')
    price: float = Field(..., gt=0, description="委托价格")
    shares: int = Field(..., gt=0, le=1000000, description="买入数量")
    name: str = Field("", max_length=20)
    market: str = Field("A", pattern=r'^[AHU]$')

    @field_validator('shares')
    @classmethod
    def validate_shares(cls, v):
        if v % 100 != 0:
            raise ValueError('A股买入数量必须为100的整数倍')
        return v


class SellOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10, pattern=r'^[0-9a-zA-Z]{1,10}$')
    price: float = Field(..., gt=0, description="委托价格")
    shares: int = Field(..., gt=0, le=1000000, description="卖出数量")


class BacktestRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    strategy_type: str = Field("adaptive", max_length=50, pattern=r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    start_date: str = Field("2024-01-01", pattern=r'^\d{4}-\d{2}-\d{2}$')
    end_date: str = Field("2025-12-31", pattern=r'^\d{4}-\d{2}-\d{2}$')
    initial_capital: float = Field(1000000, gt=0, le=100000000)


class BacktestOptimizeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    strategy_name: str = Field("ma_cross", max_length=50, pattern=r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    start_date: str = Field("2023-01-01", pattern=r'^\d{4}-\d{2}-\d{2}$')
    end_date: str = Field("2024-12-31", pattern=r'^\d{4}-\d{2}-\d{2}$')
    metric: str = Field("sharpe_ratio", max_length=30)
    max_combinations: int = Field(100, gt=0, le=1000)


class WatchlistAddRemoveRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')


class WatchlistReorderRequest(BaseModel):
    symbols: str = Field(..., min_length=1, max_length=500)


class AlertAddRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    alert_type: str = Field(..., pattern=r'^(price_above|price_below|change_pct_above|change_pct_below|volume_above)$')
    value: float = Field(..., gt=0, lt=1e8)


class AlertRemoveRequest(BaseModel):
    alert_id: str = Field(..., min_length=1, max_length=50)


class TradingBuyRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    name: str = Field("", max_length=20)
    market: str = Field("", max_length=2)
    price: float = Field(..., gt=0)
    shares: int = Field(..., gt=0, le=1000000)
    stop_loss: float = Field(0, ge=0)
    take_profit: float = Field(0, ge=0)
    strategy: str = Field("manual", max_length=50)


class TradingSellRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    price: float = Field(..., gt=0)
    shares: int | None = Field(None, gt=0, le=1000000)
    reason: str = Field("manual", max_length=50)


class ConfigSetRequest(BaseModel):
    value: str = Field(..., max_length=10000)


class AlphaEvolveRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    max_iterations: int = Field(3, gt=0, le=20)
    period: str = Field("1y", max_length=5)


class AuditStrategyRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    strategy_name: str = Field("adaptive", max_length=50, pattern=r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    period: str = Field("1y", max_length=5)


class WatchlistAddRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')


class PriceAlertRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r'^[0-9a-zA-Z\.]{1,20}$')
    target_price: float = Field(..., gt=0)
    direction: str = Field("above", pattern=r'^(above|below)$')


class ConnectionManager:
    """WebSocket连接管理器"""

    MAX_CONNECTIONS = 200
    STALE_TIMEOUT = 300

    def __init__(self):
        self.connections: list[WebSocket] = []
        self._subscriptions: dict[WebSocket, set[str]] = {}
        self._last_active: dict[WebSocket, float] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        async with self._lock:
            if len(self.connections) >= self.MAX_CONNECTIONS:
                await ws.close(code=1013, reason="Max connections reached")
                return False
            await ws.accept()
            self.connections.append(ws)
            self._subscriptions[ws] = set()
            self._last_active[ws] = time.time()
            return True

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            unsubscribed_symbols = self._subscriptions.pop(ws, set())
            self._last_active.pop(ws, None)
            if ws in self.connections:
                self.connections.remove(ws)
        if unsubscribed_symbols:
            await _evict_stale_push_state(unsubscribed_symbols)

    async def subscribe(self, ws: WebSocket, symbols: list[str]):
        async with self._lock:
            if ws in self._subscriptions:
                self._subscriptions[ws].update(symbols)
                self._last_active[ws] = time.time()

    async def unsubscribe(self, ws: WebSocket, symbols: list[str]):
        async with self._lock:
            if ws in self._subscriptions:
                self._subscriptions[ws] -= set(symbols)
                self._last_active[ws] = time.time()

    async def touch(self, ws: WebSocket) -> None:
        async with self._lock:
            self._last_active[ws] = time.time()

    async def sweep_stale_connections(self) -> int:
        now = time.time()
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
                pass
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
        async with self._lock:
            count = 0
            for ws in list(self.connections):
                try:
                    await ws.send_json(message)
                    count += 1
                except Exception as e:
                    logger.debug("WebSocket send failed during broadcast: %s", e)
            return count


_manager = ConnectionManager()

_api_response_cache = ThreadSafeLRU(maxsize=10000, ttl=90)

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


def set_symbol_priority(symbol: str, priority: str) -> None:
    _symbol_priority[symbol] = priority


def _is_trading_hours() -> bool:
    try:
        for market in ["A", "HK", "US"]:
            status = MarketHours.get_market_status(market)
            if status.get("is_open"):
                return True
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
                return JSONResponse(
                    content=cached,
                    status_code=200,
                    headers={"X-Cache": "HIT", "Cache-Control": f"max-age={ttl_seconds}"},
                )
            result = await func(request, *args, **kwargs)
            if isinstance(result, Response):
                result.headers["Cache-Control"] = f"max-age={ttl_seconds}"
                result.headers["X-Cache"] = "MISS"
                try:
                    import json as _json
                    body = getattr(result, "body", b"")
                    if isinstance(body, bytes):
                        parsed = _json.loads(body)
                    elif isinstance(body, dict):
                        parsed = body
                    else:
                        parsed = None
                    if parsed is not None:
                        _api_response_cache.set(cache_key, parsed, ttl=ttl_seconds)
                except Exception as e:
                    logger.debug("Cache serialization failed for %s: %s", cache_key, e)
                return result
            _api_response_cache.set(cache_key, result, ttl=ttl_seconds)
            if isinstance(result, dict):
                return JSONResponse(
                    content=result,
                    status_code=200,
                    headers={"Cache-Control": f"max-age={ttl_seconds}", "X-Cache": "MISS"},
                )
            return result
        return wrapper
    return decorator


@router.get("/market/overview")
@cache_response(15)
async def get_market_overview(request: Request):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        data = await fetcher.get_market_overview()
        return _json_response(True, data=data)
    except Exception as e:
        logger.error("Market overview error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/backtest/attribution")
async def get_performance_attribution(
    request: Request,
    symbol: str = Query(..., description="股票代码"),
    strategy: str = Query("dual_ma", description="策略名称"),
    period: int = Query(250, ge=120, le=500, description="数据天数"),
):
    """策略收益归因分析"""
    try:
        from core.backtest import BacktestEngine
        from core.performance_attribution import PerformanceAttribution
        from core.strategies import STRATEGY_REGISTRY

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 60:
            return _json_response(False, error="数据不足")

        df = df.tail(period)
        strategy_cls = STRATEGY_REGISTRY.get(strategy)
        if strategy_cls is None:
            return _json_response(False, error=f"未知策略: {strategy}")

        engine = BacktestEngine()
        bt_result = await asyncio.to_thread(engine.run, strategy_cls(), df, symbol)

        strategy_returns = np.array(bt_result.equity_curve, dtype=float)
        if len(strategy_returns) < 2:
            return _json_response(False, error="回测结果不足")

        strat_rets = np.diff(strategy_returns) / np.where(strategy_returns[:-1] > 1e-9, strategy_returns[:-1], 1.0)
        strat_rets = np.where(np.isfinite(strat_rets), strat_rets, 0)
        bench_close = df["close"].values.astype(float)
        if len(bench_close) < 2:
            return _json_response(False, error="基准数据不足")
        bench_rets = np.diff(bench_close) / np.where(bench_close[:-1] > 1e-9, bench_close[:-1], 1.0)
        bench_rets = np.where(np.isfinite(bench_rets), bench_rets, 0)

        min_len = min(len(strat_rets), len(bench_rets))
        attr = PerformanceAttribution()
        result = attr.analyze(strat_rets[-min_len:], bench_rets[-min_len:])

        return _json_response(True, data={
            "total_return": result.total_return,
            "factor_contributions": result.factor_contributions,
            "factor_weights": result.factor_weights,
            "residual": result.residual,
            "r_squared": result.r_squared,
        })
    except Exception as e:
        logger.error("Attribution analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/backtest/rolling-attribution")
async def get_rolling_attribution(
    request: Request,
    symbol: str = Query(..., description="股票代码"),
    strategy: str = Query("dual_ma", description="策略名称"),
    period: int = Query(250, ge=120, le=500, description="数据天数"),
    window: int = Query(60, ge=30, le=120, description="滚动窗口"),
    step: int = Query(5, ge=1, le=20, description="滚动步长"),
):
    try:
        from core.backtest import BacktestEngine
        from core.performance_attribution import PerformanceAttribution
        from core.strategies import STRATEGY_REGISTRY

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 60:
            return _json_response(False, error="数据不足")

        df = df.tail(period)
        strategy_cls = STRATEGY_REGISTRY.get(strategy)
        if strategy_cls is None:
            return _json_response(False, error=f"未知策略: {strategy}")

        engine = BacktestEngine()
        bt_result = await asyncio.to_thread(engine.run, strategy_cls(), df, symbol)

        strategy_returns = np.array(bt_result.equity_curve)
        if len(strategy_returns) < 2:
            return _json_response(False, error="回测结果不足")

        strat_rets = np.diff(strategy_returns) / np.where(strategy_returns[:-1] > 0, strategy_returns[:-1], 1)
        strat_rets = np.where(np.isfinite(strat_rets), strat_rets, 0)
        bench_close = df["close"].values.astype(float)
        if len(bench_close) < 2:
            return _json_response(False, error="基准数据不足")
        bench_rets = np.diff(bench_close) / np.where(bench_close[:-1] > 0, bench_close[:-1], 1)
        bench_rets = np.where(np.isfinite(bench_rets), bench_rets, 0)

        attr = PerformanceAttribution()
        rolling = attr.rolling_attribution(strat_rets, bench_rets, window=window, step=step)

        return _json_response(True, data={
            "symbol": symbol,
            "strategy": strategy,
            "window": window,
            "step": step,
            "segments": rolling,
        })
    except Exception as e:
        logger.error("Rolling attribution error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/backtest/rolling-metrics")
async def get_rolling_risk_metrics(
    request: Request,
    symbol: str = Query(..., description="股票代码"),
    strategy: str = Query("dual_ma", description="策略名称"),
    period: int = Query(250, ge=120, le=500, description="数据天数"),
    window: int = Query(60, ge=30, le=120, description="滚动窗口"),
    step: int = Query(5, ge=1, le=20, description="滚动步长"),
    risk_free_rate: float = Query(0.0, ge=0, le=0.1, description="无风险利率(年化)"),
):
    try:
        from core.backtest import BacktestEngine
        from core.performance_attribution import PerformanceAttribution
        from core.strategies import STRATEGY_REGISTRY

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 60:
            return _json_response(False, error="数据不足")

        df = df.tail(period)
        strategy_cls = STRATEGY_REGISTRY.get(strategy)
        if strategy_cls is None:
            return _json_response(False, error=f"未知策略: {strategy}")

        engine = BacktestEngine()
        bt_result = await asyncio.to_thread(engine.run, strategy_cls(), df, symbol)

        strategy_returns = np.array(bt_result.equity_curve)
        if len(strategy_returns) < 2:
            return _json_response(False, error="回测结果不足")

        strat_rets = np.diff(strategy_returns) / np.where(strategy_returns[:-1] > 0, strategy_returns[:-1], 1)
        strat_rets = np.where(np.isfinite(strat_rets), strat_rets, 0)

        rolling = PerformanceAttribution.rolling_sharpe_sortino(
            strat_rets, window=window, step=step, risk_free_rate=risk_free_rate,
        )

        return _json_response(True, data={
            "symbol": symbol,
            "strategy": strategy,
            "window": window,
            "step": step,
            "risk_free_rate": risk_free_rate,
            "segments": rolling,
        })
    except Exception as e:
        logger.error("Rolling metrics error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/metrics")
async def get_collected_metrics(request: Request):
    try:
        from core.metrics import get_metrics
        m = get_metrics()
        return _json_response(True, data=m.get_summary())
    except Exception as e:
        logger.error("Metrics endpoint error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/market/status")
@cache_response(60)
async def get_market_status(request: Request):
    try:
        statuses = {}
        for market in ["A", "HK", "US"]:
            statuses[market] = MarketHours.get_market_status(market)
        return _json_response(True, data=statuses)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/market/regime/dashboard")
async def regime_dashboard(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    period: int = Query(120, ge=60, le=500, description="分析天数"),
):
    """市场状态仪表盘：批量扫描多标的市场状态，返回汇总统计和逐标的详情"""
    try:
        from core.regime_detector import RegimeDetector

        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            return _json_response(False, error="需要至少1个股票代码")
        if len(symbol_list) > 20:
            return _json_response(False, error="最多同时扫描20只股票")

        fetcher: SmartDataFetcher = request.app.state.fetcher
        detector = RegimeDetector()
        per_symbol: list[dict] = []
        regime_counts: dict[str, int] = {}

        for sym in symbol_list:
            try:
                df = await fetcher.get_history(sym, period="all", kline_type="daily", adjust="qfq")
                if df is None or len(df) < 60:
                    per_symbol.append({"symbol": sym, "error": "数据不足"})
                    continue
                df = df.tail(period)
                result = await asyncio.to_thread(detector.detect, df)
                regime_val = result.current_regime.value
                regime_counts[regime_val] = regime_counts.get(regime_val, 0) + 1
                per_symbol.append({
                    "symbol": sym,
                    "regime": regime_val,
                    "confidence": round(result.confidence, 4),
                    "trend_strength": round(result.trend_strength, 4),
                    "volatility_level": round(result.volatility_level, 4),
                    "mean_reversion_score": round(result.mean_reversion_score, 4),
                    "recommended_strategy": detector._recommend_strategy(result),
                })
            except (ValueError, KeyError, OSError) as e:
                logger.debug("Regime detect failed for %s: %s", sym, e)
                per_symbol.append({"symbol": sym, "error": str(e)})

        total_scanned = sum(1 for s in per_symbol if "regime" in s)
        dominant_regime = max(regime_counts, key=regime_counts.get) if regime_counts else "unknown"
        avg_confidence = (
            sum(s["confidence"] for s in per_symbol if "confidence" in s) / total_scanned
            if total_scanned > 0 else 0.0
        )
        avg_volatility = (
            sum(s["volatility_level"] for s in per_symbol if "volatility_level" in s) / total_scanned
            if total_scanned > 0 else 0.0
        )

        return _json_response(True, data={
            "symbols_scanned": total_scanned,
            "dominant_regime": dominant_regime,
            "regime_distribution": regime_counts,
            "avg_confidence": round(avg_confidence, 4),
            "avg_volatility": round(avg_volatility, 4),
            "per_symbol": per_symbol,
            "period": period,
            "timestamp": time.time(),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


class RebalanceScheduleRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="调度名称")
    symbols: str = Field(..., min_length=3, description="逗号分隔的股票代码")
    frequency: str = Field("weekly", pattern=r"^(daily|weekly|monthly)$", description="检查频率")
    drift_threshold: float = Field(0.05, ge=0.01, le=0.20, description="偏离阈值")
    turnover_cap: float = Field(0.30, ge=0.05, le=1.0, description="换手上限")
    capital: float = Field(100000, ge=10000, le=10000000, description="总资金")
    period: str = Field("1y", max_length=5, description="回看周期")


@router.post("/portfolio/rebalance/schedule")
async def create_rebalance_schedule(body: RebalanceScheduleRequest, request: Request):
    """创建再平衡调度计划"""
    try:
        symbol_list = [s.strip() for s in body.symbols.split(",") if s.strip()]
        if len(symbol_list) < 2:
            return _json_response(False, error="至少需要2只股票")

        schedule_id = str(uuid.uuid4())[:8]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        db = get_db()
        with db._get_conn() as conn:
            conn.execute(
                """INSERT INTO rebalance_schedules
                   (id, name, symbols, frequency, drift_threshold,
                    turnover_cap, capital, period, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (schedule_id, body.name, body.symbols, body.frequency,
                 body.drift_threshold, body.turnover_cap, body.capital, body.period,
                 now, now),
            )
            conn.commit()

        return _json_response(True, data={
            "schedule_id": schedule_id,
            "name": body.name,
            "symbols": symbol_list,
            "frequency": body.frequency,
            "drift_threshold": body.drift_threshold,
            "created_at": now,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/rebalance/schedules")
async def list_rebalance_schedules(request: Request):
    """列出所有再平衡调度计划"""
    try:
        db = get_db()
        rows = db._get_conn().execute(
            """SELECT id, name, symbols, frequency, drift_threshold,
                      turnover_cap, capital, period, enabled, last_check_at, created_at
               FROM rebalance_schedules ORDER BY created_at DESC"""
        ).fetchall()

        schedules = []
        for row in rows:
            schedules.append({
                "schedule_id": row[0],
                "name": row[1],
                "symbols": row[2],
                "frequency": row[3],
                "drift_threshold": row[4],
                "turnover_cap": row[5],
                "capital": row[6],
                "period": row[7],
                "enabled": bool(row[8]),
                "last_check_at": row[9],
                "created_at": row[10],
            })

        return _json_response(True, data={"schedules": schedules, "total": len(schedules)})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.delete("/portfolio/rebalance/schedule/{schedule_id}")
async def delete_rebalance_schedule(
    request: Request,
    schedule_id: str = Path(..., min_length=1, max_length=20),
):
    """删除再平衡调度计划"""
    try:
        db = get_db()
        with db._get_conn() as conn:
            cursor = conn.execute("DELETE FROM rebalance_schedules WHERE id = ?", (schedule_id,))
            conn.commit()
            if cursor.rowcount == 0:
                return _json_response(False, error="调度计划不存在")

        return _json_response(True, data={"deleted": schedule_id})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/portfolio/rebalance/schedule/{schedule_id}/check")
async def execute_rebalance_check(
    request: Request,
    schedule_id: str = Path(..., min_length=1, max_length=20),
):
    """手动触发再平衡检查"""
    try:
        db = get_db()
        row = db._get_conn().execute(
            """SELECT symbols, drift_threshold, turnover_cap, capital, period
               FROM rebalance_schedules WHERE id = ? AND enabled = 1""",
            (schedule_id,),
        ).fetchone()

        if not row:
            return _json_response(False, error="调度计划不存在或已禁用")

        symbols_str, drift_threshold, turnover_cap, capital, period = row
        symbol_list = [s.strip() for s in symbols_str.split(",") if s.strip()]

        from core.risk_parity_rebalancer import RiskParityRebalancer

        fetcher: SmartDataFetcher = request.app.state.fetcher
        all_returns: dict[str, np.ndarray] = {}
        prices: dict[str, float] = {}

        for sym in symbol_list[:10]:
            try:
                df = await fetcher.get_history(sym, _period_to_history(period), "daily", "qfq")
                if df is None or len(df) < 30:
                    continue
                c = df["close"].astype(float)
                prices[sym] = float(c.iloc[-1])
                ret = c.pct_change().dropna()
                ret = ret[np.isfinite(ret)]
                all_returns[sym] = ret.values[-120:]
            except (ValueError, KeyError, OSError) as e:
                logger.debug("Return calc failed for %s: %s", sym, e)
                continue

        if len(all_returns) < 2:
            return _json_response(False, error="有效数据不足，无法执行再平衡检查")

        min_len = min(len(v) for v in all_returns.values())
        ret_matrix = np.column_stack([v[-min_len:] for v in all_returns.values()])
        cov_matrix = np.cov(ret_matrix.T)

        sym_list = list(all_returns.keys())
        positions = [{"symbol": sym, "name": sym, "weight": 1.0 / len(sym_list)} for sym in sym_list]

        rebalancer = RiskParityRebalancer(drift_threshold=drift_threshold, turnover_cap=turnover_cap)
        result = rebalancer.analyze(positions, cov_matrix, prices, capital)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result_json = json.dumps({
            "needs_rebalance": result.needs_rebalance,
            "max_drift": result.max_drift,
            "total_turnover": result.total_turnover,
            "reason": result.reason,
            "trades": [
                {"symbol": t.symbol, "action": t.action, "weight_delta": t.weight_delta,
                 "shares": t.shares, "price": t.price}
                for t in result.trades
            ],
        }, ensure_ascii=False)

        with db._get_conn() as conn:
            conn.execute(
                "UPDATE rebalance_schedules SET last_check_at = ?, last_result_json = ?, updated_at = ? WHERE id = ?",
                (now, result_json, now, schedule_id),
            )
            conn.commit()

        return _json_response(True, data={
            "schedule_id": schedule_id,
            "checked_at": now,
            "needs_rebalance": result.needs_rebalance,
            "reason": result.reason,
            "max_drift": result.max_drift,
            "total_turnover": result.total_turnover,
            "trades": [
                {"symbol": t.symbol, "name": t.name, "action": t.action,
                 "current_weight": t.current_weight, "target_weight": t.target_weight,
                 "weight_delta": t.weight_delta, "shares": t.shares, "price": t.price}
                for t in result.trades
            ],
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/stream")
async def stream_portfolio_metrics(request: Request):
    """Server-Sent Events endpoint for real-time portfolio metrics streaming.

    Streams rolling risk metrics and system health data as SSE events.
    Clients connect via EventSource and receive updates at configurable intervals.
    """
    async def event_stream():
        interval = 5
        reconnect_delay = 2
        max_empty = 3
        empty_count = 0

        try:
            while True:
                try:
                    from core.metrics import get_metrics

                    mc = get_metrics()
                    metrics_summary = mc.get_summary()

                    now = datetime.now()
                    market_status = {}
                    try:
                        for market in ["A", "HK", "US"]:
                            status = MarketHours.get_market_status(market)
                            market_status[market] = {
                                "is_open": status.get("is_open", False),
                                "session": status.get("session", "unknown"),
                            }
                    except Exception as e:
                        logger.debug("Market status parse failed: %s", e)

                    push_data = {
                        "timestamp": now.isoformat(),
                        "markets": market_status,
                        "metrics": metrics_summary,
                        "server_uptime": round(time.time() - _start_time, 1),
                    }

                    if market_status and not any(m.get("is_open") for m in market_status.values()):
                        empty_count += 1
                    else:
                        empty_count = 0

                    payload = orjson.dumps(push_data).decode()
                    yield f"data: {payload}\n\n"

                    if empty_count >= max_empty:
                        yield f"data: {orjson.dumps({'event': 'market_closed', 'timestamp': now.isoformat()}).decode()}\n\n"
                        break

                    await asyncio.sleep(interval)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug("SSE stream error: %s", e)
                    yield f"data: {orjson.dumps({'event': 'error', 'message': safe_error(e)}).decode()}\n\n"
                    await asyncio.sleep(reconnect_delay)
        except asyncio.CancelledError:
            pass
        finally:
            yield f"data: {orjson.dumps({'event': 'disconnect', 'timestamp': datetime.now().isoformat()}).decode()}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/backtest/export")
async def export_backtest_results(
    request: Request,
    format: str = Query("csv", description="导出格式：csv 或 json", pattern=r"^(csv|json)$"),
    symbol: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
):
    try:
        db = getattr(request.app.state, "db", None)
        if not db or not hasattr(db, "get_backtest_history"):
            return _json_response(False, error="数据库不可用")

        results = db.get_backtest_history(symbol=symbol, limit=limit)
        if not results:
            return _json_response(False, error="无回测记录可导出")

        if format == "json":
            return _json_response(True, data=results)

        import csv as csv_module
        import io
        output = io.StringIO()
        if results:
            writer = csv_module.DictWriter(output, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)

        csv_bytes = output.getvalue().encode("utf-8-sig")
        return Response(
            content=csv_bytes,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=backtest_export.csv"
            },
        )
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/stock/realtime/{symbol}")
async def get_stock_realtime(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")):
    try:
        cached = _rt_cache.get(symbol)
        if cached is not None:
            return _json_response(True, data=cached, cached=True)
        fetcher: SmartDataFetcher = request.app.state.fetcher
        data = await fetcher.get_realtime(symbol)
        if data:
            _rt_cache.set(symbol, data)
            return _json_response(True, data=data)
        return _json_response(False, error="未获取到数据")
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/stock/history/{symbol}")
async def get_stock_history(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
    kline_type: str = Query("daily", max_length=10, pattern=r"^(daily|weekly|monthly)$"),
    adjust: str = Query("", max_length=5),
):
    try:
        cache_key = "%s:%s:%s:%s" % (symbol, period, kline_type, adjust)
        cached = _kline_cache.get(cache_key)
        if cached is not None:
            return _json_response(True, data=cached, cached=True)
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period, kline_type, adjust)
        if df.empty:
            return _json_response(False, error="无历史数据")
        result = df.to_dict("records")
        _kline_cache.set(cache_key, result)
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/stock/history/export/{symbol}")
async def export_stock_history(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
    kline_type: str = Query("daily", max_length=10, pattern=r"^(daily|weekly|monthly)$"),
    adjust: str = Query("", max_length=5),
    format: str = Query("csv", pattern=r"^(csv|json)$"),
):
    try:
        import io
        import json as json_lib

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period, kline_type, adjust)
        if df.empty:
            return _json_response(False, error="无历史数据")

        filename = f"{symbol}_{period}_{kline_type}_{adjust if adjust else 'none'}.{format}"

        if format == "csv":
            output = io.StringIO()
            df.to_csv(output, index=False, encoding="utf-8")
            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        else:
            result = df.to_dict("records")
            return StreamingResponse(
                iter([json_lib.dumps(result, ensure_ascii=False, default=str)]),
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
    except Exception as e:
        logger.error("Export history error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


@router.get("/stock/fundamentals/{symbol}")
@cache_response(3600)
async def get_stock_fundamentals(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        market = MarketDetector.detect(symbol)
        data = await fetcher.get_fundamentals(symbol, market)
        if data:
            return _json_response(True, data=data)
        return _json_response(False, error="无基本面数据")
    except Exception as e:
        return _json_response(False, error=safe_error(e))


_indicator_api_cache = _TTLCache(ttl=60.0, maxsize=3000)


@router.get("/stock/indicators/{symbol}")
async def get_stock_indicators(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
    kline_type: str = Query("daily"),
):
    try:
        cache_key = "ind:%s:%s:%s" % (symbol, period, kline_type)
        cached = _indicator_api_cache.get(cache_key)
        if cached is not None:
            return _json_response(True, data=cached, cached=True)
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period, kline_type)
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")
        kline_data = df.to_dict("records")
        result = calc_all_indicators(kline_data)
        _indicator_api_cache.set(cache_key, result)
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Indicators error: %s", e)
        return _json_response(False, error=safe_error(e))


def _period_to_history(period: str) -> str:
    period = (period or "1y").lower()
    if period in {"3m", "6m"}:
        return "1y"
    if period in {"3y", "5y", "all"}:
        return "all"
    return "1y"


_analysis_cache = _TTLCache(ttl=60.0, maxsize=4000)


@router.get("/stock/analysis/{symbol}")
async def get_deep_analysis(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"), period: str = Query("1y", max_length=5)):
    try:
        cache_key = "analysis:%s:%s" % (symbol, period)
        cached = _analysis_cache.get(cache_key)
        if cached is not None:
            return _json_response(True, data=cached, cached=True)
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="数据不足，至少需要60个交易日")

        df = df.tail(260).copy().reset_index(drop=True)
        c = df["close"].astype(float)
        h = df["high"].astype(float)
        low = df["low"].astype(float)
        df["volume"].astype(float) if "volume" in df.columns else None
        indicators = TechnicalIndicators.compute_all(df, symbol=symbol, period=period)
        ma = indicators.get("ma", {})
        ma20 = ma.get(20, [])
        ma.get(60, [])
        last_close = float(c.iloc[-1])
        trend_slope = 0.0
        if len(ma20) >= 20:
            trend_slope = float(ma20[-1] - ma20[-20]) / max(abs(float(ma20[-20])), 1e-9)
        direction = "up" if trend_slope > 0.02 else "down" if trend_slope < -0.02 else "sideways"
        strength = min(100, abs(trend_slope) * 1200 + abs(indicators.get("trend_score", 0)) * 0.5)
        support_resistance = IndicatorAnalysis.support_resistance(df)
        volume_analysis = IndicatorAnalysis.volume_price_analysis(df)
        patterns = KLinePatternRecognizer.recognize(df.tail(80))

        rsi_data = indicators.get("rsi", {}).get(12, [])
        rsi_val = float(rsi_data[-1]) if rsi_data else 50.0
        macd = indicators.get("macd", {})
        dif = macd.get("dif", [0])[-1] if macd.get("dif") else 0
        dea = macd.get("dea", [0])[-1] if macd.get("dea") else 0
        kdj = indicators.get("kdj", {})
        k_val = kdj.get("k", [50])[-1] if kdj.get("k") else 50
        d_val = kdj.get("d", [50])[-1] if kdj.get("d") else 50

        low_120 = float(low.tail(120).min())
        high_120 = float(h.tail(120).max())
        fib_ratios = [0.236, 0.382, 0.5, 0.618, 0.786]
        fib = [round(high_120 - (high_120 - low_120) * r, 4) for r in fib_ratios]
        composite_score = float(indicators.get("trend_score", 0))
        signal = indicators.get("signal", "neutral")
        confidence = min(100, abs(composite_score) + 35)

        result = {
            "trend": {
                "direction": direction,
                "strength": round(float(strength), 2),
                "duration_days": int(min(len(df), 260)),
                "key_levels": {
                    "support": support_resistance.get("supports", []),
                    "resistance": support_resistance.get("resistances", []),
                },
            },
            "momentum": {
                "rsi_signal": "overbought" if rsi_val > 70 else "oversold" if rsi_val < 30 else "neutral",
                "macd_signal": "bullish" if dif > dea else "bearish" if dif < dea else "neutral",
                "kdj_signal": "bullish" if k_val > d_val else "bearish" if k_val < d_val else "neutral",
                "composite_momentum": round(float(composite_score / 100), 4),
            },
            "volume": {
                "trend": "accumulation" if volume_analysis.get("obv_trend", 0) > 0 else "distribution" if volume_analysis.get("obv_trend", 0) < 0 else "neutral",
                "obv_divergence": bool(indicators.get("rsi_divergence", {}).get("top_divergence")),
                "volume_ratio_5d": volume_analysis.get("volume_ratio", 0),
            },
            "patterns": patterns[-10:],
            "ichimoku": indicators.get("ichimoku", {}),
            "fibonacci_levels": [{"ratio": r, "price": p} for r, p in zip(fib_ratios, fib, strict=False)],
            "composite_score": round(composite_score, 2),
            "signal": signal,
            "signal_confidence": round(float(confidence), 2),
            "last_price": round(last_close, 4),
        }
        _analysis_cache.set(cache_key, result)
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Deep analysis error for %s: %s", symbol, e, exc_info=True)
        return _json_response(False, error=safe_error(e))


# ============================================================================
# PORTFOLIO & RISK
# ============================================================================
@router.get("/stock/correlation/{symbol}")
async def get_correlation_analysis(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    benchmark: str = Query("sh000300", max_length=20),
    period: str = Query("1y"),
):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        bench_df = await fetcher.get_history(benchmark, _period_to_history(period), "daily", "qfq")
        if bench_df is None or bench_df.empty:
            try:
                import baostock as bs
                bench_code = benchmark.replace("sh", "sh.", 1).replace("sz", "sz.", 1)
                if not bench_code.startswith("sh.") and not bench_code.startswith("sz."):
                    bench_code = f"sh.{benchmark.removeprefix('sh').removeprefix('sz')}"
                bs.login()
                try:
                    rs = bs.query_history_k_data_plus(bench_code, "date,close", start_date="2023-01-01", end_date=datetime.now().strftime("%Y-%m-%d"), frequency="d")
                    rows = []
                    while rs.next():
                        rows.append(rs.get_row_data())
                    if rows:
                        bench_df = pd.DataFrame(rows, columns=["date", "close"])
                        bench_df["close"] = pd.to_numeric(bench_df["close"], errors="coerce")
                        bench_df["date"] = pd.to_datetime(bench_df["date"], errors="coerce")
                        bench_df = bench_df.dropna(subset=["date", "close"])
                finally:
                    bs.logout()
            except Exception as e:
                logger.debug("BaoStock cleanup failed: %s", e)
        if df is None or df.empty or bench_df is None or bench_df.empty:
            return _json_response(False, error="数据不足")
        left = df[["date", "close"]].rename(columns={"close": "asset_close"})
        right = bench_df[["date", "close"]].rename(columns={"close": "benchmark_close"})
        left["date"] = pd.to_datetime(left["date"], errors="coerce")
        right["date"] = pd.to_datetime(right["date"], errors="coerce")
        merged = left.merge(right, on="date", how="inner").tail(260)
        if len(merged) < 30:
            return _json_response(False, error="重叠数据不足")
        ar = merged["asset_close"].astype(float).pct_change()
        br = merged["benchmark_close"].astype(float).pct_change()
        rolling_corr = ar.rolling(60).corr(br).fillna(0)
        br_var = np.var(br.dropna().tail(120))
        beta = float(np.cov(ar.dropna().tail(120), br.dropna().tail(120))[0][1] / br_var) if br_var > 0 else 1.0
        asset_first = float(merged["asset_close"].iloc[0])
        bench_first = float(merged["benchmark_close"].iloc[0])
        asset_ret = (float(merged["asset_close"].iloc[-1]) / asset_first - 1) if asset_first > 1e-9 else 0.0
        bench_ret = (float(merged["benchmark_close"].iloc[-1]) / bench_first - 1) if bench_first > 1e-9 else 0.0
        rolling_corr_data = [
            {"date": str(d)[:10], "value": round(float(v), 4)}
            for d, v in zip(merged["date"], rolling_corr, strict=False)
        ]
        return _json_response(True, data={
            "rolling_correlation": rolling_corr_data,
            "beta": round(beta, 4),
            "alpha": round(float(asset_ret - beta * bench_ret), 4),
            "relative_strength": round(float(asset_ret - bench_ret), 4),
            "stability_score": round(float(100 - rolling_corr.tail(120).std() * 100), 2),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/stock/prediction/{symbol}")
@cache_response(120)
async def get_stock_prediction(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"), period: str = Query("1y", max_length=5)):
    """AI预测接口 - 基于技术指标和统计模型"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="数据不足")
        df = df.tail(260).copy().reset_index(drop=True)
        c = df["close"].astype(float).values
        _ = df["high"].astype(float).values
        _ = df["low"].astype(float).values
        _ = df["volume"].astype(float).values

        indicators = TechnicalIndicators.compute_all(df, symbol=symbol, period=period)
        trend_score = indicators.get("trend_score", 0)
        signal = indicators.get("signal", "neutral")

        # 简单统计预测：基于近期趋势+波动率
        returns = np.diff(c) / np.where(c[:-1] > 0, c[:-1], 1)
        returns = returns[np.isfinite(returns)]
        if len(returns) < 20:
            return _json_response(False, error="数据不足")
        recent_ret = returns[-20:]
        avg_ret = float(np.mean(recent_ret))
        std_ret = float(np.std(recent_ret))
        last_price = float(c[-1])

        # 5日/10日/20日预测
        predictions = {}
        for days, label in [(5, "5d"), (10, "10d"), (20, "20d")]:
            drift = avg_ret * days
            vol = std_ret * np.sqrt(days)
            pred_price = last_price * (1 + drift)
            pred_upper = last_price * (1 + drift + 1.96 * vol)
            pred_lower = last_price * (1 + drift - 1.96 * vol)
            confidence = max(0.1, min(0.9, 1.0 - vol / max(abs(drift), 0.01)))
            predictions[label] = {
                "price": round(pred_price, 2),
                "upper": round(pred_upper, 2),
                "lower": round(pred_lower, 2),
                "confidence": round(confidence, 2),
                "direction": "up" if drift > 0 else "down",
            }

        # 综合信号
        composite_signal = "bullish" if trend_score > 20 else "bearish" if trend_score < -20 else "neutral"
        composite_confidence = min(0.95, abs(trend_score) / 100 + 0.3)

        return _json_response(True, data={
            "symbol": symbol,
            "last_price": round(last_price, 2),
            "predictions": predictions,
            "composite_signal": composite_signal,
            "composite_confidence": round(composite_confidence, 2),
            "trend_score": round(float(trend_score), 2),
            "technical_signal": signal,
            "volatility_annual": round(float(std_ret * np.sqrt(252)), 4),
            "timestamp": time.time(),
        })
    except Exception as e:
        logger.error("Prediction error for %s: %s", symbol, e)
        return _json_response(False, error=safe_error(e))


@router.get("/stock/signals/{symbol}")
async def get_stock_signals(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
    strategy: str = Query("all", max_length=30),
):
    """获取股票策略信号历史 — 通过 on_bar() 统一入口"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")

        from core.data_governance import DataQualityPipeline
        dq = DataQualityPipeline(enable_anomaly_detect=True, enable_adjust=False)
        df = dq.process(df, symbol)
        suspended_mask = df.get("is_suspended", pd.Series(False, index=df.index))
        df = df[~suspended_mask].reset_index(drop=True) if suspended_mask.any() else df
        if len(df) < 30:
            return _json_response(False, error="有效数据不足（停牌日过滤后）")

        composite = CompositeStrategy()
        signals = []
        step = max(1, len(df) // 50)
        signal_timeout = 10.0
        max_signals = 100
        start_time = time.time()

        for s in composite.strategies:
            s.reset()

        for i in range(30, len(df), step):
            if time.time() - start_time > signal_timeout:
                logger.warning("Signal generation timed out for %s after %d signals", symbol, len(signals))
                break
            if len(signals) >= max_signals:
                break
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
            for j in range(max(0, i - step + 1), i):
                fill_row = df.iloc[j]
                fill_bar = {
                    "open": float(fill_row.get("open", 0)) if pd.notna(fill_row.get("open")) else 0,
                    "high": float(fill_row.get("high", 0)) if pd.notna(fill_row.get("high")) else 0,
                    "low": float(fill_row.get("low", 0)) if pd.notna(fill_row.get("low")) else 0,
                    "close": float(fill_row.get("close", 0)) if pd.notna(fill_row.get("close")) else 0,
                    "volume": float(fill_row.get("volume", 0)) if pd.notna(fill_row.get("volume")) else 0,
                    "date": str(fill_row.get("date", ""))[:10] if "date" in df.columns else "",
                    "symbol": symbol,
                }
                for s in composite.strategies:
                    if strategy != "all" and type(s).__name__ != strategy:
                        continue
                    s.on_bar(fill_bar, {})

            date_str = str(df["date"].iloc[i])[:10] if "date" in df.columns else ""
            bar_signals = []
            for s in composite.strategies:
                if strategy != "all" and type(s).__name__ != strategy:
                    continue
                try:
                    sigs = s.on_bar(bar, {})
                    for sig in sigs:
                        bar_signals.append({
                            "strategy": type(s).__name__,
                            "signal": sig.get("action", "hold"),
                            "confidence": sig.get("confidence", 0),
                            "reason": sig.get("reason", ""),
                        })
                except Exception as e:
                    logger.debug("Signal generation failed for strategy: %s", e)
                    continue
            if bar_signals:
                signals.append({
                    "date": date_str,
                    "price": round(float(df["close"].iloc[i]), 2),
                    "signals": bar_signals,
                })

        return _json_response(True, data={"symbol": symbol, "signals": signals, "truncated": time.time() - start_time > signal_timeout})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/summary")
async def get_portfolio_summary(request: Request):
    try:
        db = request.app.state.db
        watchlist = db.get_config("watchlist", [])
        if not isinstance(watchlist, list):
            watchlist = []
        fetcher: SmartDataFetcher = request.app.state.fetcher
        positions = []
        total_value = 0.0
        total_pnl = 0.0
        for symbol in watchlist[:20]:
            try:
                from core.market_detector import MarketDetector
                market = MarketDetector.detect(symbol)
                rt = await fetcher.get_realtime(symbol, market)
                if not rt:
                    continue
                price = float(rt.get("price", 0))
                change_pct = float(rt.get("change_pct", 0))
                name = rt.get("name", symbol)
                positions.append({
                    "symbol": symbol,
                    "name": name,
                    "price": price,
                    "change_pct": change_pct,
                })
                total_value += price
                total_pnl += change_pct
            except Exception as e:
                logger.debug("Portfolio summary skip %s: %s", symbol, e)
        avg_change = total_pnl / len(positions) if positions else 0
        return _json_response(True, data={
            "total_positions": len(positions),
            "total_value": round(total_value, 2),
            "avg_change_pct": round(avg_change, 4),
            "positions": positions,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/risk_analysis")
async def get_portfolio_risk_analysis(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    period: str = Query("1y"),
):
    """组合风险分析 - CVaR/VaR/相关性矩阵"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            return _json_response(False, error="请提供股票代码")

        all_returns = {}
        for sym in symbol_list[:10]:
            try:
                df = await fetcher.get_history(sym, _period_to_history(period), "daily", "qfq")
                if df.empty or len(df) < 30:
                    continue
                c = df["close"].astype(float)
                ret = c.pct_change().dropna()
                ret = ret[np.isfinite(ret)]
                all_returns[sym] = ret.values[-120:]
            except Exception as e:
                logger.debug("Return calc failed for %s: %s", sym, e)
                continue

        if len(all_returns) < 2:
            return _json_response(False, error="有效数据不足")

        min_len = min(len(v) for v in all_returns.values())
        ret_matrix = np.column_stack([v[-min_len:] for v in all_returns.values()])
        sym_list = list(all_returns.keys())

        # 相关性矩阵
        corr_matrix = np.corrcoef(ret_matrix.T)
        correlation = {}
        for i, s1 in enumerate(sym_list):
            correlation[s1] = {}
            for j, s2 in enumerate(sym_list):
                correlation[s1][s2] = round(float(corr_matrix[i][j]), 4)

        # 等权组合VaR/CVaR
        weights = np.ones(len(sym_list)) / len(sym_list)
        port_returns = ret_matrix @ weights
        var_95 = float(np.percentile(port_returns, 5))
        cvar_95 = float(np.mean(port_returns[port_returns <= var_95]))
        port_vol = float(np.std(port_returns) * np.sqrt(252))
        port_sharpe = float(np.mean(port_returns) * 252 / (port_vol)) if port_vol > 0 else 0

        # 个股风险贡献
        risk_contribution = {}
        for i, sym in enumerate(sym_list):
            marginal = float(np.cov(ret_matrix[:, i], port_returns)[0][1] / np.var(port_returns)) if np.var(port_returns) > 0 else 0
            risk_contribution[sym] = round(float(weights[i] * marginal * port_vol), 4)

        return _json_response(True, data={
            "symbols": sym_list,
            "correlation_matrix": correlation,
            "portfolio_var_95": round(var_95, 4),
            "portfolio_cvar_95": round(cvar_95, 4),
            "portfolio_volatility": round(port_vol, 4),
            "portfolio_sharpe": round(port_sharpe, 2),
            "risk_contribution": risk_contribution,
        })
    except Exception as e:
        logger.error("Portfolio risk analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/risk/dashboard")
@rate_limiter(max_calls=20, time_window=60.0)
async def get_portfolio_risk_dashboard(
    request: Request,
    period: str = Query("1y", description="数据周期"),
):
    """组合风险仪表盘 — 聚合风险指标、集中度、回撤、压力测试于单一端点"""
    try:
        db: SQLiteStore = request.app.state.db
        fetcher: SmartDataFetcher = request.app.state.fetcher

        watchlist = db.get_config("watchlist", [])
        if not isinstance(watchlist, list) or not watchlist:
            return _json_response(True, data={
                "positions": [],
                "risk_metrics": {},
                "concentration": {},
                "drawdown": {},
                "stress_summary": [],
                "message": "观察列表为空",
            })

        positions = []
        all_returns = {}
        total_value = 0.0
        daily_pnl = 0.0

        for symbol in watchlist[:20]:
            try:
                market = MarketDetector.detect(symbol)
                rt = await fetcher.get_realtime(symbol, market)
                if not rt:
                    continue
                price = float(rt.get("price", 0))
                change_pct = float(rt.get("change_pct", 0))
                name = rt.get("name", symbol)
                positions.append({
                    "symbol": symbol,
                    "name": name,
                    "price": price,
                    "change_pct": change_pct,
                    "market": market,
                })
                total_value += price
                daily_pnl += change_pct

                df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
                if df is not None and len(df) >= 30:
                    c = df["close"].astype(float)
                    ret = c.pct_change().dropna()
                    ret = ret[np.isfinite(ret)]
                    if len(ret) >= 20:
                        all_returns[symbol] = ret.values[-120:]
            except Exception as e:
                logger.debug("Return calc failed for %s: %s", symbol, e)
                continue

        concentration = {}
        if total_value > 0 and positions:
            for p in positions:
                weight = p["price"] / total_value
                concentration[p["symbol"]] = round(weight, 4)
            sorted_by_weight = sorted(concentration.items(), key=lambda x: x[1], reverse=True)
            top_n = min(5, len(sorted_by_weight))
            top_weight = sum(w for _, w in sorted_by_weight[:top_n])
            concentration["_top5_weight"] = round(top_weight, 4)
            concentration["_top5_symbols"] = [s for s, _ in sorted_by_weight[:top_n]]
            max_weight = sorted_by_weight[0][1] if sorted_by_weight else 0
            concentration["_max_single_weight"] = round(max_weight, 4)
            concentration["_is_concentrated"] = max_weight > 0.20

        risk_metrics = {}
        if len(all_returns) >= 2:
            min_len = min(len(v) for v in all_returns.values())
            ret_matrix = np.column_stack([v[-min_len:] for v in all_returns.values()])
            sym_list = list(all_returns.keys())
            n_assets = len(sym_list)
            weights = np.ones(n_assets) / n_assets

            port_returns = ret_matrix @ weights
            port_vol = float(np.std(port_returns) * np.sqrt(252))
            port_mean = float(np.mean(port_returns) * 252)
            sharpe = port_mean / port_vol if port_vol > 1e-12 else 0.0

            var_95 = float(np.percentile(port_returns, 5))
            cvar_95 = float(np.mean(port_returns[port_returns <= var_95])) if np.any(port_returns <= var_95) else var_95

            downside = port_returns[port_returns < 0]
            downside_dev = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(252)) if len(downside) > 0 else 0.0
            sortino = port_mean / downside_dev if downside_dev > 1e-12 else 0.0

            cum_returns = np.cumsum(port_returns)
            running_max = np.maximum.accumulate(cum_returns)
            drawdowns = cum_returns - running_max
            max_dd = float(np.min(drawdowns))

            risk_metrics = {
                "portfolio_volatility": round(port_vol, 4),
                "portfolio_sharpe": round(sharpe, 2),
                "portfolio_sortino": round(sortino, 2),
                "var_95": round(var_95, 4),
                "cvar_95": round(cvar_95, 4),
                "max_drawdown": round(max_dd, 4),
                "annual_return": round(port_mean, 4),
            }

        drawdown_info = {}
        if len(all_returns) >= 2 and risk_metrics:
            drawdown_info = {
                "current_drawdown": 0.0,
                "max_drawdown": risk_metrics.get("max_drawdown", 0.0),
                "drawdown_status": "normal",
            }
            if risk_metrics.get("max_drawdown", 0) < -0.10:
                drawdown_info["drawdown_status"] = "warning"
            if risk_metrics.get("max_drawdown", 0) < -0.20:
                drawdown_info["drawdown_status"] = "critical"

        stress_summary = []
        if positions and total_value > 0:
            from core.portfolio_risk_engine import STRESS_SCENARIOS
            for scenario in STRESS_SCENARIOS:
                projected_loss = total_value * scenario.market_shock
                stress_summary.append({
                    "scenario": scenario.name,
                    "description": scenario.description,
                    "projected_loss_pct": round(scenario.market_shock, 4),
                    "projected_loss_amount": round(projected_loss, 2),
                })

        return _json_response(True, data={
            "positions": positions,
            "total_value": round(total_value, 2),
            "daily_pnl_pct": round(daily_pnl / len(positions), 4) if positions else 0.0,
            "position_count": len(positions),
            "risk_metrics": risk_metrics,
            "concentration": concentration,
            "drawdown": drawdown_info,
            "stress_summary": stress_summary,
        })
    except Exception as e:
        logger.error("Risk dashboard error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/attribution")
async def get_portfolio_attribution(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    benchmark: str = Query("sh000300"),
    period: str = Query("1y"),
):
    """组合收益归因分析"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            return _json_response(False, error="请提供股票代码")

        bench_df = await fetcher.get_history(benchmark, _period_to_history(period), "daily", "qfq")
        if bench_df.empty:
            return _json_response(False, error="基准数据不足")
        bench_ret = bench_df["close"].astype(float).pct_change().dropna().values[-120:]

        attribution = {}
        for sym in symbol_list[:10]:
            try:
                df = await fetcher.get_history(sym, _period_to_history(period), "daily", "qfq")
                if df.empty or len(df) < 30:
                    continue
                c = df["close"].astype(float)
                ret = c.pct_change().dropna().values[-120:]
                min_len = min(len(ret), len(bench_ret))
                if min_len < 20:
                    continue
                r = ret[-min_len:]
                b = bench_ret[-min_len:]
                total_ret = float(np.prod(1 + r) - 1)
                bench_total = float(np.prod(1 + b) - 1)
                beta = float(np.cov(r, b)[0][1] / np.var(b)) if np.var(b) > 0 else 1.0
                alpha = total_ret - beta * bench_total
                systematic = beta * bench_total
                idiosyncratic = total_ret - systematic
                attribution[sym] = {
                    "total_return": round(total_ret, 4),
                    "systematic_return": round(systematic, 4),
                    "idiosyncratic_return": round(idiosyncratic, 4),
                    "alpha": round(alpha, 4),
                    "beta": round(beta, 4),
                }
            except Exception as e:
                logger.debug("Risk attribution failed: %s", e)
                continue

        return _json_response(True, data={
            "benchmark": benchmark,
            "benchmark_return": round(float(np.prod(1 + bench_ret) - 1), 4),
            "attribution": attribution,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/rebalance")
async def get_risk_parity_rebalance(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    capital: float = Query(100000, ge=10000, description="总资金"),
    drift_threshold: float = Query(0.05, ge=0.01, le=0.20, description="偏离阈值"),
    period: str = Query("1y"),
):
    """风险平价再平衡建议"""
    try:
        from core.risk_parity_rebalancer import RiskParityRebalancer

        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if len(symbol_list) < 2:
            return _json_response(False, error="至少需要2只股票")

        all_returns = {}
        prices = {}
        for sym in symbol_list[:10]:
            try:
                df = await fetcher.get_history(sym, _period_to_history(period), "daily", "qfq")
                if df is None or len(df) < 30:
                    continue
                c = df["close"].astype(float)
                prices[sym] = float(c.iloc[-1])
                ret = c.pct_change().dropna()
                ret = ret[np.isfinite(ret)]
                all_returns[sym] = ret.values[-120:]
            except Exception as e:
                logger.debug("Return calc failed for %s: %s", sym, e)
                continue

        if len(all_returns) < 2:
            return _json_response(False, error="有效数据不足")

        min_len = min(len(v) for v in all_returns.values())
        ret_matrix = np.column_stack([v[-min_len:] for v in all_returns.values()])
        cov_matrix = np.cov(ret_matrix.T)

        positions = []
        sym_list = list(all_returns.keys())
        for _i, sym in enumerate(sym_list):
            positions.append({
                "symbol": sym,
                "name": sym,
                "weight": 1.0 / len(sym_list),
            })

        rebalancer = RiskParityRebalancer(drift_threshold=drift_threshold)
        result = rebalancer.analyze(positions, cov_matrix, prices, capital)

        return _json_response(True, data={
            "needs_rebalance": result.needs_rebalance,
            "reason": result.reason,
            "total_turnover": result.total_turnover,
            "max_drift": result.max_drift,
            "trades": [
                {
                    "symbol": t.symbol,
                    "name": t.name,
                    "current_weight": t.current_weight,
                    "target_weight": t.target_weight,
                    "weight_delta": t.weight_delta,
                    "action": t.action,
                    "shares": t.shares,
                    "price": t.price,
                }
                for t in result.trades
            ],
        })
    except Exception as e:
        logger.error("Rebalance analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/stress/scenarios")
async def get_stress_scenarios(request: Request):
    """获取预定义压力测试情景列表"""
    from core.stress_test import PREDEFINED_SCENARIOS
    scenarios = []
    for s in PREDEFINED_SCENARIOS:
        scenarios.append({
            "name": s.name,
            "description": s.description,
            "equity_shock": s.equity_shock,
            "bond_shock": s.bond_shock,
            "commodity_shock": s.commodity_shock,
            "volatility_mult": s.volatility_mult,
        })
    return _json_response(True, data=scenarios)


@router.post("/portfolio/stress/run")
async def run_stress_test(request: Request):
    """运行组合压力测试"""
    try:
        from core.stress_test import PortfolioStressTester
        body = await request.json()
        positions = body.get("positions", [])
        if not positions:
            return _json_response(False, error="请提供持仓数据")
        try:
            values = [float(p.get("value", 0)) for p in positions]
        except (ValueError, TypeError):
            return _json_response(False, error="持仓价值必须为数字")

        tester = PortfolioStressTester()
        scenario_results = tester.run_all_scenarios(positions)

        monte_carlo_result = None
        if body.get("run_monte_carlo", False):
            fetcher: SmartDataFetcher = request.app.state.fetcher
            symbols = [p.get("symbol", "") for p in positions if p.get("symbol")]
            total_value = sum(values)
            weights = np.array([v / total_value for v in values]) if total_value > 0 else np.ones(len(positions)) / len(positions)

            all_returns = {}
            for sym in symbols[:10]:
                try:
                    df = await fetcher.get_history(sym, "1y", "daily", "qfq")
                    if df is not None and len(df) >= 30:
                        ret = df["close"].astype(float).pct_change().dropna()
                        ret = ret[np.isfinite(ret)]
                        all_returns[sym] = ret.values[-120:]
                except Exception as e:
                    logger.debug("Return calc failed for %s: %s", sym, e)
                    continue

            if len(all_returns) >= 2:
                min_len = min(len(v) for v in all_returns.values())
                ret_matrix = np.column_stack([v[-min_len:] for v in all_returns.values()])
                mc = tester.monte_carlo(
                    returns=ret_matrix,
                    weights=weights[:ret_matrix.shape[1]],
                    portfolio_value=total_value,
                    horizon_days=max(1, min(int(body.get("horizon_days", 20)), 252)),
                    n_simulations=min(max(int(body.get("n_simulations", 5000)), 100), 10000),
                )
                monte_carlo_result = mc.summary()

        return _json_response(True, data={
            "scenarios": scenario_results,
            "monte_carlo": monte_carlo_result,
        })
    except Exception as e:
        logger.error("Stress test error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/report/weekly")
@cache_response(3600)
async def get_weekly_report(request: Request):
    """周报生成接口"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        overview = await fetcher.get_market_overview()
        cn = overview.get("cn_indices", {})

        # 市场概况
        market_summary = {}
        for name, info in cn.items():
            if isinstance(info, dict):
                market_summary[name] = {
                    "price": info.get("price", 0),
                    "change_pct": info.get("change_pct", 0),
                }

        # 板块表现
        heatmap_data = {}
        try:
            import akshare as ak
            df = await asyncio.to_thread(ak.stock_board_industry_name_em)
            if df is not None and not df.empty:
                top_gainers = []
                top_losers = []
                for _, row in df.iterrows():
                    name = str(row.get("板块名称", row.get("名称", "")))
                    pct = float(row.get("涨跌幅", 0) or 0)
                    if pct > 0:
                        top_gainers.append({"name": name, "change_pct": round(pct, 2)})
                    else:
                        top_losers.append({"name": name, "change_pct": round(pct, 2)})
                top_gainers.sort(key=lambda x: x["change_pct"], reverse=True)
                top_losers.sort(key=lambda x: x["change_pct"])
                heatmap_data = {
                    "top_gainers": top_gainers[:5],
                    "top_losers": top_losers[:5],
                }
        except Exception as e:
            logger.debug("Heatmap data failed: %s", e)

        if not heatmap_data:
            try:
                url = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
                import re

                import aiohttp

                from core.data_fetcher import get_aiohttp_session
                session = await get_aiohttp_session()
                async with session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        text = await resp.text()
                match = re.search(r'=\s*({.*})', text)
                if match:
                    data = json.loads(match.group(1))
                    top_gainers = []
                    top_losers = []
                    for _key, val in data.items():
                        parts = val.split(',')
                        if len(parts) >= 6:
                            name = parts[1]
                            pct = float(parts[5]) if parts[5] else 0
                            if pct > 0:
                                top_gainers.append({"name": name, "change_pct": round(pct, 2)})
                            else:
                                top_losers.append({"name": name, "change_pct": round(pct, 2)})
                    top_gainers.sort(key=lambda x: x["change_pct"], reverse=True)
                    top_losers.sort(key=lambda x: x["change_pct"])
                    heatmap_data = {"top_gainers": top_gainers[:5], "top_losers": top_losers[:5]}
            except Exception as e:
                logger.debug("Heatmap gainers/losers failed: %s", e)
                heatmap_data = {"top_gainers": [], "top_losers": []}

        # 北向资金
        northbound = {}
        try:
            northbound = await fetcher.fetch_north_bound_flow()
        except Exception as e:
            logger.debug("Northbound flow fetch failed: %s", e)

        report_date = datetime.now().strftime("%Y-%m-%d")
        return _json_response(True, data={
            "report_date": report_date,
            "market_summary": market_summary,
            "sector_performance": heatmap_data,
            "northbound_flow": northbound,
            "generated_at": time.time(),
        })
    except Exception as e:
        logger.error("Weekly report error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/market/stocks")
@cache_response(30)
async def get_market_stocks(request: Request, market: str = Query("A"), limit: int = Query(5000, le=10000)):
    try:
        from core.market_data import fetch_all_a_stocks_async
        stocks = await fetch_all_a_stocks_async()
        if stocks:
            df_data = stocks
            if market == "sh":
                df_data = [s for s in df_data if s.get("symbol", "").startswith("6") and not s.get("symbol", "").startswith("688")]
            elif market == "sz":
                df_data = [s for s in df_data if s.get("symbol", "").startswith("0")]
            elif market == "cy":
                df_data = [s for s in df_data if s.get("symbol", "").startswith("3")]
            elif market == "kc":
                df_data = [s for s in df_data if s.get("symbol", "").startswith("688")]
            result = df_data[:limit]
            return _json_response(True, data=result)
    except Exception as e:
        logger.debug("Market stocks EastMoney error: %s", e)
    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
        if df is None or df.empty:
            return _json_response(True, data=[])
        col_map = {
            "代码": "symbol", "名称": "name", "最新价": "price",
            "涨跌幅": "change_pct", "成交量": "volume", "成交额": "amount",
            "换手率": "turnover_rate",
        }
        rename = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=rename)
        if market == "sh":
            df = df[df["symbol"].str.startswith("6")]
        elif market == "sz":
            df = df[df["symbol"].str.startswith("0")]
        elif market == "cy":
            df = df[df["symbol"].str.startswith("3")]
        elif market == "kc":
            df = df[df["symbol"].str.startswith("688")]
        if "amount" in df.columns:
            df = df.sort_values("amount", ascending=False)
        df = df.head(limit)
        keep_cols = [c for c in ["symbol", "name", "price", "change_pct", "volume", "amount", "turnover_rate"] if c in df.columns]
        result = df[keep_cols].fillna(0).to_dict("records")
        return _json_response(True, data=result)
    except Exception as e:
        logger.debug("Market stocks fallback: %s", e)
        return _json_response(True, data=[])


@router.get("/market/anomaly")
@cache_response(30)
async def get_market_anomaly(request: Request):
    try:
        from core.market_data import fetch_all_a_stocks_async
        stocks = await fetch_all_a_stocks_async()
        if not stocks:
            return _json_response(True, data=[])
        anomalies = []
        for s in stocks:
            change_pct = float(s.get("change_pct", 0) or 0)
            volume_ratio = float(s.get("volume_ratio", 0) or 0)
            reason = ""
            if change_pct > 9.8:
                reason = "涨停"
            elif change_pct < -9.8:
                reason = "跌停"
            elif change_pct > 8 and volume_ratio > 3:
                reason = "大涨放量"
            elif change_pct < -8 and volume_ratio > 3:
                reason = "大跌放量"
            elif change_pct > 5 and volume_ratio > 5:
                reason = "放量拉升"
            elif change_pct < -5 and volume_ratio > 5:
                reason = "放量下跌"
            if reason:
                anomalies.append({
                    "symbol": s.get("symbol", ""),
                    "name": s.get("name", ""),
                    "price": round(float(s.get("price", 0) or 0), 2),
                    "change_pct": round(change_pct, 2),
                    "volume_ratio": round(volume_ratio, 2),
                    "reason": reason,
                })
        anomalies.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        return _json_response(True, data=anomalies[:80])
    except Exception as e:
        logger.debug("Market anomaly error: %s", e)
        return _json_response(True, data=[])


@router.get("/market/heatmap")
@cache_response(30)
async def get_market_heatmap(request: Request, market: str = Query("A")):
    items = []
    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_board_industry_name_em)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                name = str(row.get("板块名称", row.get("名称", "")))
                pct = float(row.get("涨跌幅", 0) or 0)
                amount = float(row.get("成交额", row.get("总市值", 0)) or 0)
                lead = str(row.get("领涨股票", ""))
                items.append({
                    "name": name,
                    "change_pct": round(pct, 2),
                    "amount": amount,
                    "value": max(amount, 1),
                    "leader": lead,
                })
    except Exception as e:
        logger.debug("Market heatmap akshare failed: %s", e)

    if not items:
        try:
            url = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
            import aiohttp

            from core.data_fetcher import get_aiohttp_session
            session = await get_aiohttp_session()
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    text = await resp.text()
            import re
            match = re.search(r'=\s*({.*})', text)
            if match:
                data = json.loads(match.group(1))
                for _key, val in data.items():
                    parts = val.split(',')
                    if len(parts) >= 6:
                        name = parts[1]
                        change_pct = float(parts[5]) if parts[5] else 0
                        amount = float(parts[7]) if len(parts) > 7 and parts[7] else 0
                        items.append({
                            "name": name,
                            "change_pct": round(change_pct, 2),
                            "amount": amount,
                            "value": max(amount, 1),
                            "leader": parts[11] if len(parts) > 11 else "",
                        })
        except Exception as e2:
            logger.debug("Market heatmap sina fallback failed: %s", e2)

    if not items:
        items = [
            {"name": "银行", "change_pct": 0, "amount": 1, "value": 1, "leader": ""},
            {"name": "科技", "change_pct": 0, "amount": 1, "value": 1, "leader": ""},
        ]

    return _json_response(True, data={"market": market, "items": items, "timestamp": time.time()})


@router.get("/market/northbound/detail")
@cache_response(60)
async def get_northbound_detail(request: Request):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        data = await fetcher.fetch_north_bound_flow()
        if data:
            sh_buy = data.get("sh_buy", 0)
            sh_sell = data.get("sh_sell", 0)
            sz_buy = data.get("sz_buy", 0)
            sz_sell = data.get("sz_sell", 0)
            sh_inflow = sh_buy - sh_sell
            sz_inflow = sz_buy - sz_sell
            data["sh_inflow"] = sh_inflow
            data["sz_inflow"] = sz_inflow
            data["net_inflow"] = data.get("total_net", sh_inflow + sz_inflow)
        return _json_response(True, data=data)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/market/limit_up")
@cache_response(60)
async def get_limit_up_pool(request: Request):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        return _json_response(True, data=await fetcher.fetch_limit_up_pool())
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/market/dragon_tiger")
@cache_response(300)
async def get_dragon_tiger(request: Request, date: str | None = None):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        return _json_response(True, data=await fetcher.fetch_dragon_tiger_list(date))
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/factor/analysis/{symbol}")
async def get_factor_analysis(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"), period: str = Query("1y", max_length=5)):
    try:
        from core.indicators import (
            calc_composite_score,
            calc_factor_efficiency_ratio,
            calc_factor_momentum_quality,
            calc_factor_money_flow_index,
            calc_factor_relative_volume,
            calc_factor_volume_price_trend,
        )
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 80:
            return _json_response(False, error="数据不足")
        h = df["high"].astype(float).values
        low = df["low"].astype(float).values
        c = df["close"].astype(float).values
        v = df["volume"].astype(float).values
        factors = {
            "momentum_quality": calc_factor_momentum_quality(c, v),
            "efficiency_ratio": calc_factor_efficiency_ratio(c),
            "relative_volume": calc_factor_relative_volume(v),
            "money_flow_index": calc_factor_money_flow_index(h, low, c, v),
            "volume_price_trend": calc_factor_volume_price_trend(c, v),
        }
        composite = calc_composite_score(factors)
        current = {}
        for name, arr in factors.items():
            valid = arr[np.isfinite(arr)]
            value = float(valid[-1]) if len(valid) else 0.0
            pct_rank = float((valid < value).mean()) if len(valid) else 0.5
            current[name] = {"value": round(value, 4), "percentile": round(pct_rank, 4), "direction": "bullish" if pct_rank >= 0.55 else "bearish" if pct_rank <= 0.45 else "neutral"}
        return _json_response(True, data={
            "factors": current,
            "composite_score": round(float(composite[-1]), 4) if len(composite) else 0,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


class FactorPipelineRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    period: str = Field(default="1y", max_length=5)
    winsorize_lower: float = Field(default=0.025, ge=0.0, le=0.5)
    winsorize_upper: float = Field(default=0.975, ge=0.5, le=1.0)
    neutralize_method: str = Field(default="zscore", pattern=r"^(zscore|rank)$")
    industry_neutralize: bool = Field(default=False)
    market_cap_neutralize: bool = Field(default=False)
    orthogonalize: bool = Field(default=True)


@router.post("/factor/pipeline")
async def run_factor_pipeline(request: Request, body: FactorPipelineRequest):
    try:
        from core.factor_pipeline import full_factor_pipeline
        from core.indicators import (
            calc_factor_efficiency_ratio,
            calc_factor_momentum_quality,
            calc_factor_money_flow_index,
            calc_factor_relative_volume,
            calc_factor_volume_price_trend,
        )

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, _period_to_history(body.period), "daily", "qfq")
        if df.empty or len(df) < 80:
            return _json_response(False, error="数据不足")

        h = df["high"].astype(float).values
        low = df["low"].astype(float).values
        c = df["close"].astype(float).values
        v = df["volume"].astype(float).values

        factor_df = pd.DataFrame({
            "momentum_quality": calc_factor_momentum_quality(c, v),
            "efficiency_ratio": calc_factor_efficiency_ratio(c),
            "relative_volume": calc_factor_relative_volume(v),
            "money_flow_index": calc_factor_money_flow_index(h, low, c, v),
            "volume_price_trend": calc_factor_volume_price_trend(c, v),
        })

        industry_labels = None
        market_cap = None

        processed = full_factor_pipeline(
            factor_df,
            industry_labels=industry_labels,
            market_cap=market_cap,
            winsorize_bounds=(body.winsorize_lower, body.winsorize_upper),
            neutralize_method=body.neutralize_method,
        )

        latest_row = processed.iloc[-1] if len(processed) > 0 else {}
        result_factors = {}
        for col in processed.columns:
            val = float(latest_row[col]) if col in latest_row.index else 0.0
            result_factors[col] = round(val, 6) if np.isfinite(val) else 0.0

        return _json_response(True, data={
            "symbol": body.symbol,
            "factors_raw": {col: round(float(factor_df[col].iloc[-1]), 6) if len(factor_df) > 0 and np.isfinite(factor_df[col].iloc[-1]) else 0.0 for col in factor_df.columns},
            "factors_processed": result_factors,
            "pipeline_config": {
                "winsorize_bounds": [body.winsorize_lower, body.winsorize_upper],
                "neutralize_method": body.neutralize_method,
                "industry_neutralize": body.industry_neutralize,
                "market_cap_neutralize": body.market_cap_neutralize,
                "orthogonalize": body.orthogonalize,
            },
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


class MultiSymbolBacktestRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=2, max_length=20)
    strategy_name: str = Field(default="DualMAStrategy", max_length=50)
    initial_capital: float = Field(default=1_000_000.0, gt=0)
    position_method: str = Field(default="equal_weight")
    correlation_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    max_positions: int = Field(default=5, ge=1, le=50)
    max_workers: int = Field(default=4, ge=1, le=16)
    parallel: bool = Field(default=True)


@router.post("/backtest/multi-symbol")
async def run_multi_symbol_backtest(
    request: Request,
    body: MultiSymbolBacktestRequest,
):
    try:
        valid_methods = {"equal_weight", "sharpe_weighted", "inverse_vol", "correlation_adjusted"}
        if body.position_method not in valid_methods:
            return _json_response(False, error=f"position_method must be one of {valid_methods}")

        fetcher: SmartDataFetcher = request.app.state.fetcher
        data_by_symbol: dict[str, Any] = {}
        for sym in body.symbols:
            df = await fetcher.get_history(sym, "3mo", "daily", "qfq")
            if df is not None and len(df) > 30:
                data_by_symbol[sym] = df

        if len(data_by_symbol) < 2:
            return _json_response(False, error="Need at least 2 symbols with sufficient data")

        from core.multi_symbol_backtest import MultiSymbolBacktest, MultiSymbolConfig

        config = MultiSymbolConfig(
            strategy_name=body.strategy_name,
            symbols=list(data_by_symbol.keys()),
            initial_capital=body.initial_capital,
            max_positions=body.max_positions,
            correlation_threshold=body.correlation_threshold,
            position_method=body.position_method,
            parallel=body.parallel,
            max_workers=body.max_workers,
        )
        engine = MultiSymbolBacktest(config)
        report = await asyncio.to_thread(engine.run, data_by_symbol)

        return _json_response(True, data=report.to_dict())
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/backtest/advanced")
async def run_advanced_backtest(
    request: Request,
    body: BacktestAdvancedRequest,
):
    try:
        from core.backtest import BacktestEngine, BacktestResult
        from core.backtest import run_backtest as run_bt
        effective_strategy = body.strategy_name or body.strategy_type
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, period="all", kline_type="daily", adjust="qfq")
        result = await asyncio.to_thread(
            run_bt,
            body.symbol,
            effective_strategy,
            body.start_date,
            body.end_date,
            body.initial_capital * max(body.leverage, 0.1),
            None,
            df,
        )
        if "error" in result:
            return _json_response(False, error=result["error"])
        result["enable_short"] = body.enable_short
        result["leverage"] = body.leverage
        if body.monte_carlo or body.sensitivity:
            engine = BacktestEngine(initial_capital=body.initial_capital)
        if body.monte_carlo:
            bt_result = BacktestResult(
                strategy_name=result.get("strategy_name", effective_strategy),
                total_return=result.get("total_return", 0),
                annual_return=result.get("annual_return", 0),
                sharpe_ratio=result.get("sharpe_ratio", 0),
                max_drawdown=result.get("max_drawdown", 0),
                win_rate=result.get("win_rate", 0),
                profit_factor=result.get("profit_factor", 0),
                total_trades=result.get("total_trades", 0),
                trades=result.get("trades", []),
                equity_curve=result.get("equity_curve", []),
                dates=[e.get("date", "") for e in result.get("equity_curve", [])],
            )
            result["monte_carlo"] = engine.monte_carlo_analysis(bt_result, n_simulations=body.n_simulations)
        if body.sensitivity and effective_strategy != "adaptive":
            strategy_cls = STRATEGY_REGISTRY.get(effective_strategy)
            if strategy_cls:
                df = await fetcher.get_history(body.symbol, "all", "daily", "qfq")
                if df is not None and not df.empty:
                    df["date"] = pd.to_datetime(df["date"], errors="coerce")
                    df = df.dropna(subset=["date"])
                    df = df[(df["date"] >= body.start_date) & (df["date"] <= body.end_date)].reset_index(drop=True)
                    sens_raw = engine.sensitivity_analysis(strategy_cls, df, {})
                    sens_items = []
                    for pname, pdata in sens_raw.get("parameters", {}).items():
                        points = pdata.get("points", [])
                        if not points:
                            continue
                        best_pt = max(points, key=lambda p: p.get("sharpe_ratio", 0))
                        values = [p["value"] for p in points]
                        sens_items.append({
                            "param": pname,
                            "value": best_pt.get("value", 0),
                            "sharpe_ratio": best_pt.get("sharpe_ratio", 0),
                            "total_return": result.get("total_return", 0),
                            "max_drawdown": result.get("max_drawdown", 0),
                            "min": min(values) if values else None,
                            "max": max(values) if values else None,
                            "impact": pdata.get("elasticity", 0),
                        })
                    result["sensitivity"] = sens_items
        if body.walk_forward:
            from core.backtest import run_walk_forward
            wf_result = await asyncio.to_thread(
                run_walk_forward, body.symbol, effective_strategy, body.start_date, body.end_date,
                252, 63, body.initial_capital, None,
            )
            if "error" not in wf_result:
                result["walk_forward"] = wf_result
        db = getattr(request.app.state, "db", None)
        if db and hasattr(db, "save_backtest_result"):
            result["id"] = db.save_backtest_result(effective_strategy, body.symbol, body.start_date, body.end_date, {}, result)
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Advanced backtest error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


@router.post("/backtest/optimize")
async def optimize_strategy(
    request: Request,
    body: BacktestOptimizeRequest,
):
    try:
        from core.backtest import grid_search_params
        if body.strategy_name not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"未知策略: {body.strategy_name}")
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, "all", "daily", "qfq")
        if df.empty:
            return _json_response(False, error="无历史数据")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df[(df["date"] >= body.start_date) & (df["date"] <= body.end_date)].reset_index(drop=True)
        if len(df) < 60:
            return _json_response(False, error="优化数据不足")
        results = await asyncio.to_thread(grid_search_params, STRATEGY_REGISTRY[body.strategy_name], df, body.max_combinations)
        results.sort(key=lambda x: x.get(body.metric, 0), reverse=True)
        return _json_response(True, data={"metric": body.metric, "top": results[:10]})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/backtest/history")
async def get_backtest_history(request: Request, symbol: str | None = None, limit: int = Query(20)):
    try:
        db = getattr(request.app.state, "db", None)
        if db and hasattr(db, "get_backtest_history"):
            return _json_response(True, data=db.get_backtest_history(symbol=symbol, limit=limit))
        return _json_response(True, data=[])
    except Exception as e:
        return _json_response(False, error=safe_error(e))


_backtest_job_state: dict[str, dict] = {}
_job_lock = threading.Lock()


class BacktestJobManager:
    _state: dict[str, dict] = {}

    @classmethod
    def submit(cls, job_id: str, progress: float, phase: str, message: str, result: dict | None = None, error: str | None = None) -> None:
        cls._state[job_id] = {
            "progress": progress,
            "phase": phase,
            "message": message,
            "result": result,
            "error": error,
            "updated_at": time.time(),
        }

    @classmethod
    def get(cls, job_id: str) -> dict | None:
        return cls._state.get(job_id)

    @classmethod
    def poll(cls, job_id: str) -> dict:
        job = cls._state.get(job_id)
        if not job:
            return {"status": "not_found"}
        if job.get("result") is not None or job.get("error") is not None:
            return {"status": "completed", **job}
        return {"status": "running", **job}

    @classmethod
    def set_result(cls, job_id: str, result: dict) -> None:
        if job_id in cls._state:
            cls._state[job_id]["result"] = result
            cls._state[job_id]["progress"] = 1.0
            cls._state[job_id]["phase"] = "completed"

    @classmethod
    def set_error(cls, job_id: str, error: str) -> None:
        if job_id in cls._state:
            cls._state[job_id]["error"] = error
            cls._state[job_id]["phase"] = "error"

    @classmethod
    def cleanup(cls, job_id: str) -> None:
        cls._state.pop(job_id, None)


@router.post("/backtest/stream")
async def submit_backtest_stream(request: Request, body: BacktestAdvancedRequest):
    job_id = str(uuid.uuid4())[:8]
    BacktestJobManager.submit(job_id, 0.0, "queued", f"任务 {job_id} 已加入队列，等待执行...")
    asyncio.create_task(_run_backtest_stream(job_id, request.app, body))
    return {"job_id": job_id, "status": "queued"}


async def _run_backtest_stream(job_id: str, app, body: BacktestAdvancedRequest) -> None:
    try:
        BacktestJobManager.submit(job_id, 0.05, "data_fetch", "正在获取历史数据...")
        fetcher: SmartDataFetcher = app.state.fetcher
        df = await fetcher.get_history(body.symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 60:
            BacktestJobManager.set_error(job_id, f"无法获取 {body.symbol} 的数据")
            return

        BacktestJobManager.submit(job_id, 0.15, "backtesting", "回测执行中...")
        effective_strategy = body.strategy_name or body.strategy_type

        def run_bt():
            from core.backtest import run_backtest
            return run_backtest(body.symbol, effective_strategy, body.start_date, body.end_date,
                                body.initial_capital * max(body.leverage, 0.1), None, df)

        result = await asyncio.to_thread(run_bt)

        if "error" in result:
            BacktestJobManager.set_error(job_id, result["error"])
            return

        result["enable_short"] = body.enable_short
        result["leverage"] = body.leverage
        BacktestJobManager.submit(job_id, 0.85, "analysis", "分析回测结果...")

        if body.monte_carlo or body.sensitivity:
            from core.backtest import BacktestEngine, BacktestResult
            engine = BacktestEngine(initial_capital=body.initial_capital)
            bt_result = BacktestResult(
                strategy_name=result.get("strategy_name", effective_strategy),
                total_return=result.get("total_return", 0),
                annual_return=result.get("annual_return", 0),
                sharpe_ratio=result.get("sharpe_ratio", 0),
                max_drawdown=result.get("max_drawdown", 0),
                win_rate=result.get("win_rate", 0),
                profit_factor=result.get("profit_factor", 0),
                total_trades=result.get("total_trades", 0),
                trades=result.get("trades", []),
                equity_curve=result.get("equity_curve", []),
                dates=[e.get("date", "") for e in result.get("equity_curve", [])],
            )
            if body.monte_carlo:
                BacktestJobManager.submit(job_id, 0.90, "monte_carlo", "蒙特卡洛模拟中...")
                result["monte_carlo"] = engine.monte_carlo_analysis(bt_result, n_simulations=body.n_simulations)
            if body.sensitivity and effective_strategy != "adaptive":
                BacktestJobManager.submit(job_id, 0.90, "sensitivity", "敏感性分析中...")
                from core.strategies import STRATEGY_REGISTRY
                strategy_cls = STRATEGY_REGISTRY.get(effective_strategy)
                if strategy_cls:
                    df2 = await fetcher.get_history(body.symbol, "all", "daily", "qfq")
                    df2["date"] = pd.to_datetime(df2["date"], errors="coerce")
                    df2 = df2.dropna(subset=["date"])
                    df2 = df2[(df2["date"] >= body.start_date) & (df2["date"] <= body.end_date)].reset_index(drop=True)
                    if len(df2) >= 60:
                        from core.backtest import grid_search_params
                        wf_result = await asyncio.to_thread(grid_search_params, strategy_cls, df2, body.max_combinations)
                        wf_result.sort(key=lambda x: x.get("sharpe_ratio", 0), reverse=True)
                        result["sensitivity"] = wf_result[:5]

        BacktestJobManager.submit(job_id, 0.95, "saving", "保存结果...")
        db = getattr(app.state, "db", None)
        if db and hasattr(db, "save_backtest_result"):
            result["id"] = db.save_backtest_result(effective_strategy, body.symbol, body.start_date, body.end_date, {}, result)

        BacktestJobManager.set_result(job_id, result)

    except Exception as e:
        logger.error("Backtest stream job %s failed: %s", job_id, e, exc_info=True)
        BacktestJobManager.set_error(job_id, safe_error(e))


@router.get("/backtest/stream/{job_id}")
async def stream_backtest_result(job_id: str):
    async def event_generator():
        start_time = time.time()
        last_progress = -1.0
        while time.time() - start_time < 300:
            job = BacktestJobManager.poll(job_id)
            status = job.get("status", "not_found")

            if status == "not_found":
                yield f"data: {json.dumps({'event': 'error', 'message': 'Job not found'})}\n\n"
                break

            progress = job.get("progress", 0.0)
            if progress != last_progress:
                yield f"data: {json.dumps({'event': 'progress', **job})}\n\n"
                last_progress = progress

            if status == "completed":
                yield f"data: {json.dumps({'event': 'done', 'job_id': job_id, **job})}\n\n"
                BacktestJobManager.cleanup(job_id)
                break

            if job.get("error"):
                yield f"data: {json.dumps({'event': 'error', 'message': job['error']})}\n\n"
                BacktestJobManager.cleanup(job_id)
                break

            await asyncio.sleep(0.5)

        yield f"data: {json.dumps({'event': 'timeout'})}\n\n"

    from starlette.responses import StreamingResponse
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/strategy/performance")
async def get_strategy_performance(
    request: Request,
    symbol: str = Query(..., description="股票代码"),
    period: int = Query(120, description="回测天数", ge=30, le=500),
):
    try:
        from core.backtest import run_parallel_backtest
        from core.strategies import CompositeStrategy

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 50:
            return _json_response(False, error="数据不足")

        df = df.tail(period + 60)
        if len(df) < 50:
            return _json_response(False, error="数据不足")

        composite = CompositeStrategy()
        strategy_specs = [
            {"name": s.name, "class_name": type(s).__name__}
            for s in composite.strategies
        ]

        parallel_results = await asyncio.to_thread(
            run_parallel_backtest, strategy_specs, df, symbol, 1000000
        )

        strategy_results = []
        for r in parallel_results:
            if "error" in r:
                strategy_results.append({
                    "name": r["strategy"],
                    "total_return": 0.0, "sharpe_ratio": 0.0, "max_drawdown": 0.0,
                    "win_rate": 0.0, "avg_pnl": 0.0, "total_trades": 0, "profit_factor": 0.0,
                })
            else:
                strategy_results.append({
                    "name": r["strategy"],
                    "total_return": r["total_return"],
                    "sharpe_ratio": r["sharpe_ratio"],
                    "max_drawdown": r["max_drawdown"],
                    "win_rate": r["win_rate"],
                    "avg_pnl": 0.0,
                    "total_trades": r["total_trades"],
                    "profit_factor": 0.0,
                })

        strategy_results.sort(key=lambda x: x["total_return"], reverse=True)
        best = strategy_results[0] if strategy_results else None
        return _json_response(True, data={
            "symbol": symbol,
            "period": period,
            "strategies": strategy_results,
            "best_strategy": best,
            "timestamp": time.time(),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/equity")
async def get_portfolio_equity(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    period: str = Query("1y"),
):
    """组合权益曲线"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            return _json_response(False, error="请提供股票代码")

        history_map = await fetcher.get_history_batch(symbol_list[:10], _period_to_history(period), "daily", "qfq")
        all_close = {}
        for sym, df in history_map.items():
            if len(df) >= 30:
                all_close[sym] = df[["date", "close"]].copy()

        if not all_close:
            return _json_response(False, error="有效数据不足")

        all_close_items = list(all_close.items())
        if not all_close_items:
            return _json_response(False, error="有效数据不足")

        merged = all_close_items[0][1].rename(columns={"close": all_close_items[0][0]})
        for sym, sdf in all_close_items[1:]:
            sdf = sdf.rename(columns={"close": sym})
            merged = merged.merge(sdf, on="date", how="inner")

        if merged is None or len(merged) < 10:
            return _json_response(False, error="重叠数据不足")

        merged = merged.tail(260).reset_index(drop=True)
        sym_cols = [c for c in merged.columns if c != "date"]
        weights = np.ones(len(sym_cols)) / len(sym_cols)
        prices = merged[sym_cols].astype(float)
        norm = prices / prices.iloc[0]
        port_equity = (norm * weights).sum(axis=1)
        port_returns = port_equity.pct_change().dropna()

        equity_curve = []
        for i, row in merged.iterrows():
            equity_curve.append({
                "date": str(row["date"])[:10],
                "equity": round(float(port_equity.iloc[i]), 4),
            })

        cumulative_return = float(port_equity.iloc[-1] / port_equity.iloc[0] - 1)
        max_drawdown = float((port_equity / port_equity.cummax() - 1).min())
        annual_return = float(port_returns.mean() * 252)
        annual_vol = float(port_returns.std() * np.sqrt(252))
        sharpe = annual_return / annual_vol if annual_vol > 0 else 0

        return _json_response(True, data={
            "symbols": sym_cols,
            "weights": {s: round(float(w), 4) for s, w in zip(sym_cols, weights, strict=False)},
            "equity_curve": equity_curve,
            "cumulative_return": round(cumulative_return, 4),
            "max_drawdown": round(max_drawdown, 4),
            "annual_return": round(annual_return, 4),
            "annual_volatility": round(annual_vol, 4),
            "sharpe_ratio": round(sharpe, 2),
        })
    except Exception as e:
        logger.error("Portfolio equity error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/correlation")
async def get_portfolio_correlation(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    period: str = Query("1y", description="时间范围"),
):
    """组合相关性热力图数据"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if len(symbol_list) < 2:
            return _json_response(False, error="至少需要2个股票代码")

        symbol_list = symbol_list[:15]

        history_map = await fetcher.get_history_batch(symbol_list, _period_to_history(period), "daily", "qfq")
        all_close = {}
        for sym, df in history_map.items():
            if len(df) >= 30:
                all_close[sym] = df["close"].astype(float).values

        if len(all_close) < 2:
            return _json_response(False, error="有效数据不足，至少需要2只有数据的股票")

        min_len = min(len(v) for v in all_close.values())
        for sym in all_close:
            all_close[sym] = all_close[sym][-min_len:]

        valid_symbols = list(all_close.keys())
        n = len(valid_symbols)
        returns_matrix = np.column_stack([
            np.diff(all_close[sym]) / all_close[sym][:-1] for sym in valid_symbols
        ])
        corr_matrix = np.corrcoef(returns_matrix.T)

        heatmap = []
        for i in range(n):
            for j in range(n):
                heatmap.append({
                    "x": valid_symbols[j],
                    "y": valid_symbols[i],
                    "value": round(float(corr_matrix[i, j]), 4),
                })

        avg_corr = float(np.mean(corr_matrix[np.triu_indices(n, k=1)]))
        highly_correlated = []
        for i in range(n):
            for j in range(i + 1, n):
                if abs(corr_matrix[i, j]) > 0.7:
                    highly_correlated.append({
                        "pair": f"{valid_symbols[i]}-{valid_symbols[j]}",
                        "correlation": round(float(corr_matrix[i, j]), 4),
                    })

        return _json_response(True, data={
            "symbols": valid_symbols,
            "heatmap": heatmap,
            "matrix": [[round(float(corr_matrix[i, j]), 4) for j in range(n)] for i in range(n)],
            "avg_correlation": round(avg_corr, 4),
            "highly_correlated_pairs": highly_correlated,
            "diversification_score": round(max(0, 1 - avg_corr), 4),
        })
    except Exception as e:
        logger.error("Portfolio correlation error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/correlation/rolling")
async def get_rolling_correlation(
    request: Request,
    symbol_a: str = Query(..., max_length=20, description="股票A代码"),
    symbol_b: str = Query(..., max_length=20, description="股票B代码"),
    window: int = Query(60, ge=20, le=252, description="滚动窗口"),
    period: str = Query("1y", max_length=5),
):
    """两只股票的滚动相关系数分析"""
    try:
        if not validate_symbol(symbol_a) or not validate_symbol(symbol_b):
            return _json_response(False, error="Invalid symbol")
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df_a = await fetcher.get_history(symbol_a, _period_to_history(period), "daily", "qfq")
        df_b = await fetcher.get_history(symbol_b, _period_to_history(period), "daily", "qfq")
        if df_a is None or df_a.empty or df_b is None or df_b.empty:
            return _json_response(False, error="数据不足")
        from core.correlation import get_correlation_analyzer
        analyzer = get_correlation_analyzer()
        result = analyzer.compute_rolling_correlation(
            pd.Series(df_a["close"].astype(float).values, index=pd.to_datetime(df_a["date"])),
            pd.Series(df_b["close"].astype(float).values, index=pd.to_datetime(df_b["date"])),
            window=window,
        )
        if "error" in result:
            return _json_response(False, error=result["error"])
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/correlation/analysis")
async def correlation_deep_analysis(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    period: str = Query("1y", max_length=5, description="时间范围"),
    method: str = Query("pearson", pattern=r"^(pearson|spearman)$", description="相关系数方法"),
):
    """组合相关性深度分析：矩阵、高/低相关对、分散化评分、最优配对"""
    try:
        from core.correlation_analysis import CorrelationAnalyzer

        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if len(symbol_list) < 2:
            return _json_response(False, error="至少需要2个股票代码")
        symbol_list = symbol_list[:15]

        history_map = await fetcher.get_history_batch(
            symbol_list, _period_to_history(period), "daily", "qfq"
        )

        prices_dict: dict[str, pd.Series] = {}
        for sym, df in history_map.items():
            if df is not None and len(df) >= 30:
                prices_dict[sym] = df["close"].astype(float)

        if len(prices_dict) < 2:
            return _json_response(False, error="有效数据不足，至少需要2只有数据的股票")

        min_len = min(len(v) for v in prices_dict.values())
        price_data = {sym: s.iloc[-min_len:].reset_index(drop=True) for sym, s in prices_dict.items()}
        prices_df = pd.DataFrame(price_data)

        analyzer = CorrelationAnalyzer()
        result = analyzer.analyze(prices_df, method=method)

        optimal_pairs = analyzer.find_optimal_pairs(prices_df, target_corr=0.0)

        return _json_response(True, data={
            "is_valid": result.is_valid,
            "message": result.message,
            "n_assets": result.n_assets,
            "correlation_matrix": result.correlation_matrix,
            "highly_correlated_pairs": [
                {"symbol_a": p[0], "symbol_b": p[1], "correlation": round(p[2], 4)}
                for p in result.highly_correlated_pairs
            ],
            "low_correlated_pairs": [
                {"symbol_a": p[0], "symbol_b": p[1], "correlation": round(p[2], 4)}
                for p in result.low_correlated_pairs
            ],
            "average_correlation": round(result.average_correlation, 4),
            "diversification_score": round(result.diversification_score, 4),
            "optimal_pairs_for_trading": [
                {"symbol_a": p[0], "symbol_b": p[1], "correlation": round(p[2], 4)}
                for p in optimal_pairs
            ],
            "method": method,
            "period": period,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/correlation/beta")
async def get_beta_analysis(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    benchmark: str = Query("sh000300", max_length=20, description="基准指数"),
    period: str = Query("1y", max_length=5),
):
    """多股票Beta矩阵分析，含系统性/特质风险分解"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if len(symbol_list) < 1:
            return _json_response(False, error="至少需要1个股票代码")
        symbol_list = symbol_list[:15]
        if not validate_symbol(benchmark):
            return _json_response(False, error="Invalid benchmark symbol")
        history_map = await fetcher.get_history_batch(
            symbol_list + [benchmark], _period_to_history(period), "daily", "qfq"
        )
        bench_df = history_map.pop(benchmark, None)
        if bench_df is None or bench_df.empty:
            return _json_response(False, error="基准数据不足")
        bench_prices = pd.Series(
            bench_df["close"].astype(float).values,
            index=pd.to_datetime(bench_df["date"]),
        )
        price_data = {}
        for sym, df in history_map.items():
            if len(df) >= 30:
                price_data[sym] = pd.Series(
                    df["close"].astype(float).values,
                    index=pd.to_datetime(df["date"]),
                )
        if not price_data:
            return _json_response(False, error="有效股票数据不足")
        from core.correlation import get_correlation_analyzer
        analyzer = get_correlation_analyzer()
        result = analyzer.compute_beta_matrix(price_data, bench_prices)
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/diversification")
async def get_diversification_score(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    period: str = Query("1y", max_length=5),
):
    """组合分散度深度评估：ENB、条件分散收益、PCA方差贡献"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if len(symbol_list) < 2:
            return _json_response(False, error="至少需要2个股票代码")
        symbol_list = symbol_list[:15]
        history_map = await fetcher.get_history_batch(
            symbol_list, _period_to_history(period), "daily", "qfq"
        )
        price_data = {}
        for sym, df in history_map.items():
            if len(df) >= 30:
                price_data[sym] = pd.Series(
                    df["close"].astype(float).values,
                    index=pd.to_datetime(df["date"]),
                )
        if len(price_data) < 2:
            return _json_response(False, error="有效股票数据不足，至少需要2只")
        from core.correlation import get_correlation_analyzer
        analyzer = get_correlation_analyzer()
        result = analyzer.compute_diversification_score(price_data)
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/position/kelly")
async def get_kelly_position(
    win_rate: float = Query(..., ge=0.01, le=0.99, description="胜率"),
    avg_win: float = Query(..., gt=0, description="平均盈利比例"),
    avg_loss: float = Query(..., gt=0, description="平均亏损比例"),
    fraction: float = Query(0.5, ge=0.1, le=1.0, description="凯利分数"),
):
    """凯利公式仓位计算"""
    try:
        from core.position_sizer import get_position_sizer
        sizer = get_position_sizer()
        result = sizer.kelly_fraction(win_rate, avg_win, avg_loss, fraction)
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/position/atr")
async def get_atr_position(
    request: Request,
    symbol: str = Query(..., max_length=20, description="股票代码"),
    capital: float = Query(1000000, gt=10000, description="总资金"),
    risk_pct: float = Query(0.02, gt=0.001, le=0.1, description="单笔风险比例"),
    atr_mult: float = Query(2.0, gt=0.5, le=5.0, description="ATR止损倍数"),
):
    """基于ATR止损的仓位计算"""
    try:
        if not validate_symbol(symbol):
            return _json_response(False, error="Invalid symbol")
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="1y", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 20:
            return _json_response(False, error="数据不足")
        from core.indicators import TechnicalIndicators
        indicators = TechnicalIndicators.compute_all(df)
        atr_val = indicators.get("atr", 0)
        entry_price = float(df["close"].iloc[-1])
        if atr_val <= 0 or entry_price <= 0:
            return _json_response(False, error="ATR或价格数据无效")
        from core.position_sizer import get_position_sizer
        sizer = get_position_sizer()
        result = sizer.atr_position_size(capital, entry_price, atr_val, risk_pct, atr_mult)
        result["symbol"] = symbol
        result["entry_price"] = round(entry_price, 2)
        result["atr"] = round(atr_val, 4)
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/position/risk-parity")
async def get_risk_parity_position(
    request: Request,
):
    """风险平价仓位分配"""
    try:
        body = await request.json()
        capital = float(body.get("capital", 1000000))
        positions = body.get("positions", [])
        if capital <= 0:
            return _json_response(False, error="资金必须为正数")
        if not positions or not isinstance(positions, list):
            return _json_response(False, error="需要提供positions列表")
        from core.position_sizer import get_position_sizer
        sizer = get_position_sizer()
        result = sizer.risk_parity_size(capital, positions)
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/strategy/rolling-metrics")
async def get_rolling_strategy_metrics(
    request: Request,
    symbol: str = Query(..., max_length=20, description="股票代码"),
    strategy_name: str = Query("adaptive", max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$"),
    period: str = Query("1y", max_length=5),
    window: int = Query(60, ge=20, le=252),
):
    """滚动策略绩效指标（Sharpe/Sortino/Calmar/IR）"""
    try:
        if not validate_symbol(symbol):
            return _json_response(False, error="Invalid symbol")
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df is None or len(df) < 80:
            return _json_response(False, error="数据不足，至少需要80个交易日")
        from core.backtest import run_backtest
        bt_result = await asyncio.to_thread(
            run_backtest, symbol, strategy_name, "2020-01-01", "2025-12-31", 1000000, None, df
        )
        if bt_result is None or "error" in bt_result:
            return _json_response(False, error=bt_result.get("error", "回测失败") if bt_result else "回测失败")
        # 从权益曲线构建收益率
        equity_data = bt_result.get("equity_curve", [])
        if len(equity_data) < 30:
            return _json_response(False, error="权益曲线数据不足")
        equity_values = [e["value"] for e in equity_data]
        equity_series = pd.Series(equity_values)
        returns = equity_series.pct_change().dropna()
        from core.rolling_metrics import get_rolling_metrics_tracker
        tracker = get_rolling_metrics_tracker()
        result = tracker.compute_all_rolling_metrics(returns, equity_curve=equity_series)
        result["symbol"] = symbol
        result["strategy"] = strategy_name
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/backtest/walk-forward")
async def get_walk_forward_analysis(
    request: Request,
    symbol: str = Query(..., description="股票代码"),
    strategy: str = Query("dual_ma", description="策略名称"),
    n_splits: int = Query(5, ge=3, le=10, description="分割数"),
    period: int = Query(250, ge=120, le=500, description="数据天数"),
):
    """Walk-Forward滚动优化分析"""
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY
        from core.walk_forward import (
            WalkForwardConfig,
            calc_overfitting_score,
            generate_walk_forward_splits,
        )

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 120:
            return _json_response(False, error="数据不足，至少需要120个交易日")

        df = df.tail(period)
        strategy_cls = STRATEGY_REGISTRY.get(strategy)
        if strategy_cls is None:
            available = list(set(STRATEGY_REGISTRY.keys()))[:10]
            return _json_response(False, error=f"未知策略: {strategy}，可用: {available}")

        config = WalkForwardConfig(n_splits=n_splits)
        splits = generate_walk_forward_splits(len(df), config)
        engine = BacktestEngine(initial_capital=1000000)

        results = []
        for idx, split in enumerate(splits):
            try:
                train_df = df.iloc[split.train_start:split.train_end]
                val_df = df.iloc[split.val_start:split.val_end]
                test_df = df.iloc[split.test_start:split.test_end]

                train_result = engine.run(strategy_cls(), train_df, symbol=symbol)
                val_result = engine.run(strategy_cls(), val_df, symbol=symbol)
                test_result = engine.run(strategy_cls(), test_df, symbol=symbol)

                train_metrics = {
                    "total_return": train_result.total_return,
                    "sharpe_ratio": train_result.sharpe_ratio,
                    "max_drawdown": train_result.max_drawdown,
                }
                val_metrics = {
                    "total_return": val_result.total_return,
                    "sharpe_ratio": val_result.sharpe_ratio,
                    "max_drawdown": val_result.max_drawdown,
                }
                test_metrics = {
                    "total_return": test_result.total_return,
                    "sharpe_ratio": test_result.sharpe_ratio,
                    "max_drawdown": test_result.max_drawdown,
                }

                overfitting = calc_overfitting_score(train_metrics, val_metrics, test_metrics)
                results.append({
                    "split_index": idx,
                    "train": train_metrics,
                    "validation": val_metrics,
                    "test": test_metrics,
                    "overfitting_score": overfitting,
                    "data_range": {
                        "train": f"{str(df.index[split.train_start])[:10]}~{str(df.index[split.train_end - 1])[:10]}",
                        "validation": f"{str(df.index[split.val_start])[:10]}~{str(df.index[split.val_end - 1])[:10]}",
                        "test": f"{str(df.index[split.test_start])[:10]}~{str(df.index[min(split.test_end - 1, len(df) - 1)])[:10]}",
                    },
                })
            except Exception as e:
                logger.debug("Walk-forward split %s error: %s", idx, e)
                continue

        if not results:
            return _json_response(False, error="Walk-Forward分析失败")

        avg_overfitting = sum(r["overfitting_score"] for r in results) / len(results)
        avg_test_return = sum(r["test"]["total_return"] for r in results) / len(results)
        avg_test_sharpe = sum(r["test"]["sharpe_ratio"] for r in results) / len(results)

        return _json_response(True, data={
            "symbol": symbol,
            "strategy": strategy,
            "n_splits": len(results),
            "results": results,
            "summary": {
                "avg_overfitting_score": round(avg_overfitting, 4),
                "avg_test_return": round(avg_test_return, 4),
                "avg_test_sharpe": round(avg_test_sharpe, 4),
                "robustness": "high" if avg_overfitting < 0.3 else "medium" if avg_overfitting < 0.6 else "low",
            },
        })
    except Exception as e:
        logger.error("Walk-forward analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/market/breadth")
async def get_market_breadth(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    period: str = Query("1y", max_length=5),
    ma_period: int = Query(50, ge=5, le=200, description="均线周期"),
):
    """市场宽度分析：涨跌家数、站上均线占比、麦克莱伦振荡器"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if len(symbol_list) < 5:
            return _json_response(False, error="至少需要5个股票代码进行宽度分析")
        symbol_list = symbol_list[:50]
        history_map = await fetcher.get_history_batch(
            symbol_list, _period_to_history(period), "daily", "qfq"
        )
        # 计算涨跌
        price_changes = {}
        price_data = {}
        for sym, df in history_map.items():
            if len(df) < 2:
                continue
            close = df["close"].astype(float)
            change_pct = (close.iloc[-1] / close.iloc[-2] - 1) * 100
            price_changes[sym] = float(change_pct)
            price_data[sym] = close
        if len(price_changes) < 5:
            return _json_response(False, error="有效数据不足")
        from core.market_breadth import get_market_breadth_analyzer
        analyzer = get_market_breadth_analyzer()
        ad_result = analyzer.compute_advance_decline(price_changes)
        pct_above_result = analyzer.compute_percent_above_ma(price_data, ma_period)
        return _json_response(True, data={
            "advance_decline": ad_result,
            "percent_above_ma": pct_above_result,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/market/regime")
async def get_market_regime(
    request: Request,
    symbol: str = Query(..., description="股票代码"),
    period: int = Query(120, ge=60, le=500, description="分析天数"),
):
    """市场状态检测"""
    try:
        from core.regime_detector import RegimeDetector

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 60:
            return _json_response(False, error="数据不足，至少需要60个交易日")

        df = df.tail(period)
        detector = RegimeDetector()
        result = await asyncio.to_thread(detector.detect, df)

        regime_history = [
            {"regime": r.value, "index": i}
            for i, r in enumerate(result.regime_history[-30:])
        ]

        return _json_response(True, data={
            "symbol": symbol,
            "current_regime": result.current_regime.value,
            "confidence": round(result.confidence, 4),
            "trend_strength": round(result.trend_strength, 4),
            "volatility_level": round(result.volatility_level, 4),
            "mean_reversion_score": round(result.mean_reversion_score, 4),
            "transition_probabilities": {
                k: round(v, 4) for k, v in result.transition_probabilities.items()
            },
            "regime_history": regime_history,
            "recommendation": _regime_recommendation(result.current_regime),
        })
    except Exception as e:
        logger.error("Market regime error: %s", e)
        return _json_response(False, error=safe_error(e))


def _regime_recommendation(regime) -> str:
    from core.regime_detector import MarketRegime
    recommendations = {
        MarketRegime.TRENDING_UP: "趋势上行，适合趋势跟踪策略",
        MarketRegime.TRENDING_DOWN: "趋势下行，建议减仓或对冲",
        MarketRegime.MEAN_REVERTING: "均值回归状态，适合反转策略",
        MarketRegime.HIGH_VOLATILITY: "高波动环境，注意风控，缩小仓位",
        MarketRegime.LOW_VOLATILITY: "低波动环境，可考虑突破策略",
        MarketRegime.SIDEWAYS: "横盘震荡，适合网格或区间交易",
        MarketRegime.UNKNOWN: "市场状态不明确，建议观望",
    }
    return recommendations.get(regime, "无建议")


@router.get("/backtest/sensitivity")
async def get_strategy_sensitivity(
    request: Request,
    symbol: str = Query(..., description="股票代码"),
    strategy: str = Query("dual_ma", description="策略名称"),
    param: str = Query("short_window", description="参数名"),
    values: str = Query("5,10,15,20", description="逗号分隔的参数值"),
    period: int = Query(250, ge=120, le=500, description="数据天数"),
):
    """策略参数敏感性分析"""
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 60:
            return _json_response(False, error="数据不足")

        df = df.tail(period)
        strategy_cls = STRATEGY_REGISTRY.get(strategy)
        if strategy_cls is None:
            return _json_response(False, error=f"未知策略: {strategy}")

        param_values = []
        for v in values.split(","):
            try:
                param_values.append(int(v.strip()))
            except ValueError:
                try:
                    param_values.append(float(v.strip()))
                except ValueError:
                    continue

        if not param_values:
            return _json_response(False, error="无效参数值")

        engine = BacktestEngine(initial_capital=1000000)
        results = []
        for pv in param_values:
            try:
                strat = strategy_cls(**{param: pv})
                bt_result = await asyncio.to_thread(engine.run, strat, df, symbol)
                results.append({
                    "param_value": pv,
                    "total_return": round(bt_result.total_return, 4),
                    "sharpe_ratio": round(bt_result.sharpe_ratio, 4),
                    "max_drawdown": round(bt_result.max_drawdown, 4),
                    "win_rate": round(bt_result.win_rate, 4),
                    "total_trades": bt_result.total_trades,
                })
            except Exception as e:
                logger.debug("Sensitivity param %s=%s error: %s", param, pv, e)
                results.append({
                    "param_value": pv,
                    "total_return": 0.0, "sharpe_ratio": 0.0,
                    "max_drawdown": 0.0, "win_rate": 0.0, "total_trades": 0,
                })

        best = max(results, key=lambda x: x["sharpe_ratio"]) if results else None
        return _json_response(True, data={
            "symbol": symbol,
            "strategy": strategy,
            "param": param,
            "results": results,
            "best_value": best["param_value"] if best else None,
            "sensitivity": round(
                max(r["sharpe_ratio"] for r in results) - min(r["sharpe_ratio"] for r in results), 4
            ) if len(results) > 1 else 0.0,
        })
    except Exception as e:
        logger.error("Sensitivity analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


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
        set_symbol_priority(body.symbol, _PRIORITY_WATCHLIST)
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
        _symbol_priority.pop(body.symbol, None)
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


# ============================================================================
# SEARCH
# ============================================================================
@router.get("/search")
@cache_response(30)
async def search_stocks(request: Request, q: str = Query(..., min_length=1, max_length=100), limit: int = Query(10, ge=1, le=100)):
    try:
        from core.stock_search import search_stocks as do_search
        results = do_search(q, limit=limit)
        return _json_response(True, data=results)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


# ============================================================================
# TRADING
# ============================================================================
@router.get("/trading/account")
async def get_trading_account(request: Request):
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        return _json_response(True, data=trading.get_account_info())
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/trading/buy")
async def trading_buy(
    request: Request,
    body: TradingBuyRequest,
):
    try:
        validated = BuyOrderRequest(symbol=body.symbol, price=body.price, shares=body.shares, name=body.name, market=body.market)
        symbol = validated.symbol
        price = validated.price
        shares = validated.shares
        name = validated.name
        market = validated.market
        if not market:
            market = MarketDetector.detect(symbol)
        if not name:
            from core.stock_search import get_stock_name
            name = get_stock_name(symbol) or symbol
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        fetcher: SmartDataFetcher = request.app.state.fetcher
        rt = await fetcher.get_realtime(symbol, market)
        market_price = rt.get("price", 0) if rt else 0

        from core.orders import Order, OrderSide, OrderType
        from core.risk_manager import EnhancedRiskManager

        account = trading.get_account_info() if hasattr(trading, "get_account_info") else {}
        total_assets = account.get("total_assets", 0)
        available_cash = account.get("cash", 0)
        positions = trading.get_positions() if hasattr(trading, "get_positions") else {}
        pos_dict = {}
        if isinstance(positions, dict):
            for sym, pos in positions.items():
                mv = getattr(pos, "market_value", 0) if not isinstance(pos, dict) else pos.get("market_value", 0)
                pos_dict[sym] = {"market_value": mv}

        order_value = shares * (market_price if market_price > 0 else price)
        effective_total = max(total_assets, order_value * 5)
        effective_cash = max(available_cash, order_value * 2)

        risk_order = Order(
            order_id=f"pre_trade_{symbol}_{int(time.time())}",
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=shares,
            price=market_price if market_price > 0 else price,
        )
        risk_ctx = {
            "total_assets": effective_total,
            "cash": effective_cash,
            "current_positions": pos_dict,
        }
        risk_manager = getattr(request.app.state, "risk_manager", None)
        if risk_manager is None:
            risk_manager = EnhancedRiskManager(initial_capital=total_assets if total_assets > 0 else 1000000)
            request.app.state.risk_manager = risk_manager

        risk_ok, risk_reason = risk_manager.check_order(risk_order, risk_ctx)
        if not risk_ok:
            ws_manager = getattr(request.app.state, "ws_manager", None)
            if ws_manager:
                import asyncio
                asyncio.create_task(ws_manager.broadcast({
                    "type": "risk_alert",
                    "data": {"symbol": symbol, "action": "buy", "reasons": [risk_reason]},
                    "ts": int(time.time() * 1000),
                }))
            return _json_response(False, error=f"风控拦截: {risk_reason}")

        result = trading.execute_buy(
            symbol=symbol, name=name, market=market, price=price,
            shares=shares, stop_loss=body.stop_loss, take_profit=body.take_profit,
            strategy=body.strategy, market_price=market_price,
        )
        if result.get("success"):
            set_symbol_priority(symbol, _PRIORITY_POSITION)
        return _json_response(result.get("success", False), data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/trading/reset")
async def trading_reset(request: Request):
    try:
        trading = get_trading(request)
        if trading is None:
            return _json_response(False, error="交易引擎未初始化")
        if hasattr(trading, "reset_account"):
            trading.reset_account()
        elif hasattr(trading, "reset"):
            trading.reset()
        risk_manager = getattr(request.app.state, "risk_manager", None)
        if risk_manager is not None and hasattr(risk_manager, "reset"):
            risk_manager.reset()
        return _json_response(True, data={"message": "交易账户已重置"})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/trading/sell")
async def trading_sell(
    request: Request,
    body: TradingSellRequest,
):
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        symbol = body.symbol
        price = body.price
        sell_shares = body.shares
        if sell_shares is None:
            positions = trading.get_positions()
            pos = positions.get(symbol)
            sell_shares = pos.shares if pos else 0
        if sell_shares <= 0:
            return _json_response(False, error="无持仓或卖出数量无效")
        fetcher: SmartDataFetcher = request.app.state.fetcher
        market = MarketDetector.detect(symbol)
        rt = await fetcher.get_realtime(symbol, market)
        market_price = rt.get("price", 0) if rt else 0

        from core.orders import Order, OrderSide, OrderType
        from core.risk_manager import EnhancedRiskManager

        account = trading.get_account_info() if hasattr(trading, "get_account_info") else {}
        total_assets = account.get("total_assets", 0)
        sell_available_cash = account.get("cash", 0)
        positions_map = trading.get_positions() if hasattr(trading, "get_positions") else {}
        pos_dict = {}
        if isinstance(positions_map, dict):
            for sym, pos in positions_map.items():
                mv = getattr(pos, "market_value", 0) if not isinstance(pos, dict) else pos.get("market_value", 0)
                pos_dict[sym] = {"market_value": mv}

        sell_order_value = sell_shares * (market_price if market_price > 0 else price)
        sell_effective_total = max(total_assets, sell_order_value * 5)
        sell_effective_cash = max(sell_available_cash, sell_order_value * 2)

        risk_order = Order(
            order_id=f"pre_trade_{symbol}_sell_{int(time.time())}",
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=sell_shares,
            price=market_price if market_price > 0 else price,
        )
        risk_ctx = {
            "total_assets": sell_effective_total,
            "cash": sell_effective_cash,
            "current_positions": pos_dict,
        }
        risk_manager = getattr(request.app.state, "risk_manager", None)
        if risk_manager is None:
            risk_manager = EnhancedRiskManager(initial_capital=sell_effective_total if sell_effective_total > 0 else 1000000)
            request.app.state.risk_manager = risk_manager

        risk_ok, risk_reason = risk_manager.check_order(risk_order, risk_ctx)
        if not risk_ok:
            ws_manager = getattr(request.app.state, "ws_manager", None)
            if ws_manager:
                import asyncio
                asyncio.create_task(ws_manager.broadcast({
                    "type": "risk_alert",
                    "data": {"symbol": symbol, "action": "sell", "reasons": [risk_reason]},
                    "ts": int(time.time() * 1000),
                }))
            return _json_response(False, error=f"风控拦截: {risk_reason}")

        result = trading.execute_sell(
            symbol=symbol, price=price, reason=body.reason,
            shares=sell_shares, market_price=market_price,
        )
        if result.get("success"):
            positions = trading.get_positions()
            if symbol not in positions:
                set_symbol_priority(symbol, _PRIORITY_WATCHLIST)
        return _json_response(result.get("success", False), data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/trading/history")
async def get_trading_history(request: Request, limit: int = Query(100)):
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        return _json_response(True, data=trading.get_trade_history(limit))
    except Exception as e:
        return _json_response(False, error=safe_error(e))


class PortfolioImportRequest(BaseModel):
    data: dict


@router.get("/trading/export")
async def export_trading_portfolio(request: Request):
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        portfolio = trading.export_portfolio()
        return _json_response(True, data=portfolio)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/trading/import")
async def import_trading_portfolio(request: Request, body: PortfolioImportRequest):
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        result = trading.import_portfolio(body.data)
        return _json_response(result.get("success", False), data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/trading/daily-pnl")
async def get_daily_pnl(request: Request, limit: int = Query(30)):
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        return _json_response(True, data=trading.get_daily_pnl(limit))
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/trading/record-pnl")
async def record_daily_pnl(request: Request):
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        daily = trading.record_daily_pnl()
        return _json_response(True, data=daily)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/trading/analytics")
@rate_limiter(max_calls=20, time_window=60.0)
async def get_trading_analytics(request: Request):
    """交易绩效分析 — 从交易历史计算关键绩效指标"""
    try:
        trading = get_trading(request)

        if trading is None:

            return _json_response(False, error="交易引擎未初始化")
        history = trading.get_history()
        if not history:
            return _json_response(True, data={
                "total_trades": 0,
                "message": "暂无交易记录",
            })

        sells = [t for t in history if t.get("action") == "sell" and "pnl" in t]
        buys = [t for t in history if t.get("action") == "buy"]

        total_trades = len(sells)
        if total_trades == 0:
            return _json_response(True, data={
                "total_trades": len(history),
                "buy_count": len(buys),
                "sell_count": 0,
                "message": "暂无已平仓交易",
            })

        pnls = [float(t.get("pnl", 0)) for t in sells]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        total_pnl = sum(pnls)
        win_rate = len(wins) / total_trades if total_trades > 0 else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf") if wins else 0.0
        expectancy = (win_rate * avg_win + (1 - win_rate) * avg_loss) if total_trades > 0 else 0.0

        max_consec_wins = 0
        max_consec_losses = 0
        current_wins = 0
        current_losses = 0
        for p in pnls:
            if p > 0:
                current_wins += 1
                current_losses = 0
                max_consec_wins = max(max_consec_wins, current_wins)
            elif p < 0:
                current_losses += 1
                current_wins = 0
                max_consec_losses = max(max_consec_losses, current_losses)
            else:
                current_wins = 0
                current_losses = 0

        cumulative_pnl = np.cumsum(pnls)
        peak = np.maximum.accumulate(cumulative_pnl)
        drawdown = cumulative_pnl - peak
        max_dd = float(np.min(drawdown)) if len(drawdown) > 0 else 0.0

        pnl_std = float(np.std(pnls)) if len(pnls) > 1 else 0.0
        sharpe = float(np.mean(pnls) / pnl_std * np.sqrt(252)) if pnl_std > 1e-12 else 0.0

        best_trade = max(sells, key=lambda t: float(t.get("pnl", 0))) if sells else {}
        worst_trade = min(sells, key=lambda t: float(t.get("pnl", 0))) if sells else {}

        symbol_pnl = {}
        for t in sells:
            sym = t.get("symbol", "unknown")
            symbol_pnl[sym] = symbol_pnl.get(sym, 0.0) + float(t.get("pnl", 0))

        top_winners = sorted(symbol_pnl.items(), key=lambda x: x[1], reverse=True)[:5]
        top_losers = sorted(symbol_pnl.items(), key=lambda x: x[1])[:5]

        return _json_response(True, data={
            "total_trades": total_trades,
            "buy_count": len(buys),
            "sell_count": total_trades,
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 4),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(min(profit_factor, 999.0), 2),
            "expectancy": round(expectancy, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd, 2),
            "max_consecutive_wins": max_consec_wins,
            "max_consecutive_losses": max_consec_losses,
            "best_trade": {
                "symbol": best_trade.get("symbol", ""),
                "pnl": round(float(best_trade.get("pnl", 0)), 2),
            },
            "worst_trade": {
                "symbol": worst_trade.get("symbol", ""),
                "pnl": round(float(worst_trade.get("pnl", 0)), 2),
            },
            "top_winners": [{"symbol": s, "pnl": round(p, 2)} for s, p in top_winners],
            "top_losers": [{"symbol": s, "pnl": round(p, 2)} for s, p in top_losers],
        })
    except Exception as e:
        logger.error("Trading analytics error: %s", e)
        return _json_response(False, error=safe_error(e))


# ============================================================================
# TRANSACTION COST ANALYSIS (TCA)
# ============================================================================
class TCAAnalyzeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    strategy_name: str = Field(default="default", max_length=50)
    side: str = Field(default="buy", pattern=r"^(buy|sell)$")
    decision_price: float = Field(..., gt=0)
    arrival_price: float = Field(..., gt=0)
    execution_price: float = Field(..., gt=0)
    vwap_benchmark: float = Field(default=0, ge=0)
    twap_benchmark: float = Field(default=0, ge=0)
    quantity: int = Field(..., gt=0)
    execution_timestamp: str = Field(default="")


class TCABatchRequest(BaseModel):
    trades: list[TCAAnalyzeRequest] = Field(..., min_length=1, max_length=100)


class TCAExecutionRecommendRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)


@router.post("/tca/analyze")
async def tca_analyze_trade(request: Request, body: TCAAnalyzeRequest):
    try:
        from core.tca import Side, TCAEngine, TradeAnalysis

        side = Side.BUY if body.side == "buy" else Side.SELL
        trade = TradeAnalysis(
            symbol=body.symbol,
            strategy_name=body.strategy_name,
            side=side,
            decision_price=body.decision_price,
            arrival_price=body.arrival_price,
            execution_price=body.execution_price,
            vwap_benchmark=body.vwap_benchmark or body.arrival_price,
            twap_benchmark=body.twap_benchmark or body.arrival_price,
            quantity=body.quantity,
            execution_timestamp=body.execution_timestamp,
        )
        engine = TCAEngine()
        analysis = engine.analyze_trade(trade)
        return _json_response(True, data={
            "symbol": body.symbol,
            "side": body.side,
            "cost_metrics": {k: round(v, 8) for k, v in analysis.items()},
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/tca/batch")
async def tca_analyze_batch(request: Request, body: TCABatchRequest):
    try:
        from core.tca import Side, TCAEngine, TradeAnalysis

        engine = TCAEngine()
        trades = []
        for t in body.trades:
            side = Side.BUY if t.side == "buy" else Side.SELL
            trades.append(TradeAnalysis(
                symbol=t.symbol,
                strategy_name=t.strategy_name,
                side=side,
                decision_price=t.decision_price,
                arrival_price=t.arrival_price,
                execution_price=t.execution_price,
                vwap_benchmark=t.vwap_benchmark or t.arrival_price,
                twap_benchmark=t.twap_benchmark or t.arrival_price,
                quantity=t.quantity,
                execution_timestamp=t.execution_timestamp,
            ))

        batch_result = engine.analyze_batch(trades)
        strategy_attr = engine.attribute_by_strategy(trades)
        time_attr = engine.attribute_by_time_period(trades)

        return _json_response(True, data={
            "summary": {
                "total_trades": batch_result.total_trades,
                "total_cost": batch_result.total_cost,
                "avg_implementation_shortfall": batch_result.avg_implementation_shortfall,
                "avg_market_impact": batch_result.avg_market_impact,
                "avg_vwap_slippage": batch_result.avg_vwap_slippage,
                "cost_breakdown": batch_result.cost_breakdown,
            },
            "strategy_attribution": [
                {
                    "strategy": a.bucket,
                    "avg_is": a.avg_implementation_shortfall,
                    "avg_mi": a.avg_market_impact,
                    "avg_vwap_slippage": a.avg_vwap_slippage,
                    "trade_count": a.trade_count,
                    "total_cost": a.total_cost,
                }
                for a in strategy_attr
            ],
            "time_attribution": [
                {
                    "period": a.bucket,
                    "avg_is": a.avg_implementation_shortfall,
                    "avg_mi": a.avg_market_impact,
                    "trade_count": a.trade_count,
                }
                for a in time_attr
            ],
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/tca/recommend")
async def tca_execution_recommendation(request: Request, body: TCAExecutionRecommendRequest):
    try:
        from core.tca import Side, TCAEngine, TradeAnalysis

        trading = getattr(request.app.state, "trading", None)
        if trading is None:
            return _json_response(True, data={
                "symbol": body.symbol,
                "recommended_algorithm": "VWAP",
                "recommended_time_window": "09:30-15:00",
                "recommended_slice_count": 6,
                "estimated_cost_bps": 0.0,
                "note": "Trading engine not available",
            })

        history = trading.get_trade_history()
        if not history or not history.get("trades"):
            return _json_response(True, data={
                "symbol": body.symbol,
                "recommended_algorithm": "VWAP",
                "recommended_time_window": "09:30-15:00",
                "recommended_slice_count": 6,
                "estimated_cost_bps": 0.0,
                "note": "No trade history available",
            })

        engine = TCAEngine()
        historical_trades = []
        for t in history["trades"]:
            if t.get("symbol") != body.symbol:
                continue
            side = Side.BUY if t.get("action") == "buy" else Side.SELL
            price = float(t.get("price", 0))
            if price <= 0:
                continue
            historical_trades.append(TradeAnalysis(
                symbol=body.symbol,
                strategy_name=t.get("strategy", "default"),
                side=side,
                decision_price=price,
                arrival_price=price,
                execution_price=price,
                vwap_benchmark=price,
                twap_benchmark=price,
                quantity=int(t.get("shares", 0)),
                execution_timestamp=t.get("time", ""),
            ))

        rec = engine.recommend_optimal_execution(body.symbol, historical_trades)
        return _json_response(True, data={
            "symbol": rec.symbol,
            "recommended_algorithm": rec.recommended_algorithm,
            "recommended_time_window": rec.recommended_time_window,
            "recommended_slice_count": rec.recommended_slice_count,
            "estimated_cost_bps": rec.estimated_cost_bps,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


# ============================================================================
# TRADE JOURNAL
# ============================================================================
@router.post("/journal")
async def add_journal_entry(request: Request):
    try:
        from core.trade_journal import JournalEntry, TradeJournal
        body = await request.json()
        entry = JournalEntry(
            symbol=body.get("symbol", ""),
            name=body.get("name", ""),
            trade_type=body.get("trade_type", "buy"),
            price=float(body.get("price", 0)),
            quantity=int(body.get("quantity", 0)),
            notes=body.get("notes", ""),
            tags=body.get("tags", []),
            emotion=body.get("emotion", ""),
            rating=int(body.get("rating", 0)),
        )
        if not entry.symbol:
            return _json_response(False, error="股票代码不能为空")
        journal = TradeJournal()
        entry_id = journal.add_entry(entry)
        return _json_response(True, data={"id": entry_id})
    except Exception as e:
        logger.error("Journal add error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/journal")
async def get_journal_entries(
    symbol: str | None = Query(None),
    tag: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    try:
        from core.trade_journal import TradeJournal
        journal = TradeJournal()
        entries = journal.get_entries(symbol=symbol, tag=tag, limit=limit, offset=offset)
        return _json_response(True, data={
            "entries": [
                {
                    "id": e.id,
                    "symbol": e.symbol,
                    "name": e.name,
                    "trade_type": e.trade_type,
                    "price": e.price,
                    "quantity": e.quantity,
                    "notes": e.notes,
                    "tags": e.tags,
                    "emotion": e.emotion,
                    "rating": e.rating,
                    "timestamp": e.timestamp,
                }
                for e in entries
            ],
            "count": len(entries),
        })
    except Exception as e:
        logger.error("Journal get error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.put("/journal/{entry_id}")
async def update_journal_entry(entry_id: int, request: Request):
    try:
        from core.trade_journal import TradeJournal
        body = await request.json()
        journal = TradeJournal()
        ok = journal.update_entry(entry_id, body)
        return _json_response(ok, data={"id": entry_id} if ok else None, error="更新失败" if not ok else None)
    except Exception as e:
        logger.error("Journal update error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.delete("/journal/{entry_id}")
async def delete_journal_entry(entry_id: int):
    try:
        from core.trade_journal import TradeJournal
        journal = TradeJournal()
        ok = journal.delete_entry(entry_id)
        return _json_response(ok, data={"id": entry_id} if ok else None, error="删除失败" if not ok else None)
    except Exception as e:
        logger.error("Journal delete error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/journal/stats")
async def get_journal_stats():
    try:
        from core.trade_journal import TradeJournal
        journal = TradeJournal()
        stats = journal.get_stats()
        return _json_response(True, data=stats)
    except Exception as e:
        logger.error("Journal stats error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/journal/analytics")
async def get_journal_analytics():
    try:
        from core.journal_analytics import analyze_journal
        from core.trade_journal import TradeJournal
        journal = TradeJournal()
        entries = journal.get_entries(limit=500)
        if not entries:
            return _json_response(True, data={"total_entries": 0})
        entry_dicts = []
        for e in entries:
            if isinstance(e, dict):
                entry_dicts.append(e)
            elif hasattr(e, "__dict__"):
                entry_dicts.append(e.__dict__)
            else:
                entry_dicts.append({"pnl": 0, "emotion": "neutral", "rating": 0, "timestamp": 0})
        report = analyze_journal(entry_dicts)
        return _json_response(True, data=report.to_dict())
    except Exception as e:
        logger.error("Journal analytics error: %s", e)
        return _json_response(False, error=safe_error(e))


# ============================================================================
# PRICE ALERTS
# ============================================================================
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
        db.execute(f"UPDATE price_alerts SET {', '.join(updates)} WHERE id = ?", tuple(params))
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


# ============================================================================
# SYSTEM
# ============================================================================
@router.get("/system/metrics")
@cache_response(5)
async def get_system_metrics(request: Request):
    try:
        import os

        import psutil
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        req_count = getattr(request.app.state, "_request_count", 0)
        total_rt = getattr(request.app.state, "_total_response_time", 0.0)
        avg_rt = total_rt / max(req_count, 1)
        error_count = getattr(request.app.state, "_error_count", 0)
        buckets = getattr(request.app.state, "_latency_buckets", None)
        latency_dist = dict(buckets) if buckets else {}
        db = request.app.state.db
        db_metrics = {}
        try:
            pool_status = db.get_pool_status()
            db_metrics = {
                "pool_size": pool_status.get("pool_size", 0),
                "pool_max": pool_status.get("pool_max", 0),
                "buffer_size": pool_status.get("buffer_size", 0),
                "dropped_writes": pool_status.get("dropped_writes", 0),
            }
        except sqlite3.Error as e:
            logger.warning("获取数据库连接池状态失败: %s", e)
        metrics = {
            "uptime_seconds": round(time.time() - getattr(request.app.state, "start_time", time.time())),
            "memory_mb": round(mem_info.rss / 1024 / 1024, 1),
            "cpu_percent": process.cpu_percent(interval=0.1),
            "threads": process.num_threads(),
            "api_requests_total": req_count,
            "api_errors_total": error_count,
            "avg_response_time_ms": round(avg_rt, 1),
            "latency_distribution": latency_dist,
            "ws_connections": await _manager.connection_count(),
            "cache_size": request.app.state.db.cache_size if hasattr(request.app.state.db, 'cache_size') else 0,
            "database": db_metrics,
            "api_caches": {
                "rt": _rt_cache.stats(),
                "kline": _kline_cache.stats(),
                "strategy_list": _strategy_list_cache.stats(),
                "indicator_api": _indicator_api_cache.stats(),
                "analysis": _analysis_cache.stats(),
                "api_response": {"size": len(_api_response_cache), "maxsize": _api_response_cache._maxsize},
            },
        }
        return _json_response(True, data=metrics)
    except ImportError:
        req_count = getattr(request.app.state, "_request_count", 0)
        total_rt = getattr(request.app.state, "_total_response_time", 0.0)
        avg_rt = total_rt / max(req_count, 1)
        metrics = {
            "uptime_seconds": time.time() - getattr(request.app.state, "start_time", time.time()),
            "api_requests_total": req_count,
            "avg_response_time_ms": round(avg_rt, 1),
            "ws_connections": await _manager.connection_count(),
            "cache_size": request.app.state.db.cache_size if hasattr(request.app.state.db, 'cache_size') else 0,
            "memory_mb": 0,
            "cpu_percent": 0,
            "threads": 0,
            "api_errors_total": 0,
        }
        return _json_response(True, data=metrics)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


_ALLOWED_CONFIG_KEYS = {"watchlist", "portfolio_snapshot", "backtest_settings", "ui_settings", "alert_rules"}


@router.get("/config/{key}")
async def get_config(request: Request, key: str):
    try:
        if key not in _ALLOWED_CONFIG_KEYS:
            return _json_response(False, error=f"配置键 '{key}' 不允许访问")
        db = get_db()
        value = db.get_config(key)
        return _json_response(True, data=value)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/config/{key}")
async def set_config(request: Request, key: str, body: ConfigSetRequest):
    try:
        if key not in _ALLOWED_CONFIG_KEYS:
            return _json_response(False, error=f"配置键 '{key}' 不允许修改")
        db = get_db()
        db.set_config(key, body.value)
        return _json_response(True)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/stock/ai_summary/{symbol}")
@cache_response(300)
async def get_stock_ai_summary(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"), period: str = Query("1y", max_length=5)):
    """AI分析摘要 - 基于规则引擎生成综合分析"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df is None or df.empty:
            return _json_response(False, error="无数据")

        close = df["close"].values
        _ = df["high"].values
        _ = df["low"].values
        volume = df["volume"].values if "volume" in df.columns else None

        summary_points = []

        pct_5d = ((close[-1] / close[-6]) - 1) * 100 if len(close) > 5 else 0
        pct_20d = ((close[-1] / close[-21]) - 1) * 100 if len(close) > 20 else 0
        pct_60d = ((close[-1] / close[-61]) - 1) * 100 if len(close) > 60 else 0

        if pct_5d > 5:
            summary_points.append(f"近5日涨幅{pct_5d:.1f}%，短期强势")
        elif pct_5d < -5:
            summary_points.append(f"近5日跌幅{pct_5d:.1f}%，短期承压")
        else:
            summary_points.append(f"近5日变动{pct_5d:.1f}%，短期震荡")

        if pct_20d > 15:
            summary_points.append("月线级别强势上涨趋势")
        elif pct_20d < -15:
            summary_points.append("月线级别下跌趋势明显")

        close_series = pd.Series(close)
        ma5 = close_series.rolling(5).mean().values
        ma20 = close_series.rolling(20).mean().values
        ma60 = close_series.rolling(60).mean().values
        if not np.isnan(ma5[-1]) and not np.isnan(ma20[-1]):
            if ma5[-1] > ma20[-1] > (ma60[-1] if not np.isnan(ma60[-1]) else 0):
                summary_points.append("均线多头排列，趋势向好")
            elif ma5[-1] < ma20[-1]:
                summary_points.append("短期均线下穿中期均线，注意风险")

        if volume is not None and len(volume) > 10:
            avg_vol = np.mean(volume[-20:])
            recent_vol = np.mean(volume[-5:])
            if recent_vol > avg_vol * 1.5:
                summary_points.append("近期放量明显，关注资金动向")
            elif recent_vol < avg_vol * 0.5:
                summary_points.append("近期缩量，市场观望情绪浓厚")

        try:
            composite = CompositeStrategy()
            signal = composite.generate_signal(df)
            signal_map = {"buy": "买入", "sell": "卖出", "hold": "中性"}
            summary_points.append(f"综合策略信号：{signal_map.get(signal.signal_type.value, '中性')}（强度{signal.strength:.2f}）")
        except Exception as e:
            logger.debug("AI summary composite signal failed: %s", e)

        try:
            analysis = IndicatorAnalysis.comprehensive_analysis(df)
            if analysis.get("volatility", {}).get("current") == "high":
                summary_points.append("当前波动率较高，注意风险控制")
            if analysis.get("volume_price", {}).get("divergence"):
                summary_points.append("量价出现背离信号")
        except Exception as e:
            logger.debug("AI summary indicator analysis failed: %s", e)

        overall = "中性"
        bullish_count = sum(1 for p in summary_points if any(k in p for k in ["强势", "上涨", "向好", "买入"]))
        bearish_count = sum(1 for p in summary_points if any(k in p for k in ["承压", "下跌", "风险", "卖出"]))
        if bullish_count >= 3:
            overall = "偏多"
        elif bearish_count >= 3:
            overall = "偏空"

        return _json_response(True, data={
            "symbol": symbol,
            "overall": overall,
            "points": summary_points,
            "price_change": {"5d": round(pct_5d, 2), "20d": round(pct_20d, 2), "60d": round(pct_60d, 2)},
            "generated_at": time.time(),
        })
    except Exception as e:
        logger.error("AI summary error: %s", e)
        return _json_response(False, error=safe_error(e))


_MAX_SUBSCRIBE_SYMBOLS = 50

_WS_AUTH_ENABLED = os.environ.get("WS_AUTH_ENABLED", "").lower() in ("1", "true", "yes")


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
                    await ws.send_json({"type": "pong", "ts": time.time()})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        await _manager.disconnect(ws)
    except Exception as e:
        logger.warning("WebSocket实时连接异常: %s", e)
        await _manager.disconnect(ws)


_pnl_connections: list[WebSocket] = []
_pnl_last_active: dict[WebSocket, float] = {}
_pnl_lock = asyncio.Lock()
_PNL_MAX_CONNECTIONS = 100
_PNL_STALE_TIMEOUT = 300


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
            _pnl_last_active[ws] = time.monotonic()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong", "ts": time.time()})
                elif msg.get("type") == "get_pnl":
                    positions = msg.get("positions", [])
                    if not positions:
                        await ws.send_json({"type": "pnl", "data": []})
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
                    await ws.send_json({
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
                pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WebSocket PnL连接异常: %s", e)
    finally:
        async with _pnl_lock:
            if ws in _pnl_connections:
                _pnl_connections.remove(ws)
            _pnl_last_active.pop(ws, None)


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
            _signal_last_active[ws] = time.monotonic()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong", "ts": time.time()})
                elif msg.get("type") == "subscribe":
                    symbols = msg.get("symbols", [])[:10]
                    if not symbols:
                        await ws.send_json({"type": "error", "message": "No symbols provided"})
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
                    await ws.send_json({
                        "type": "signals",
                        "data": signal_data,
                        "ts": time.time(),
                    })
            except json.JSONDecodeError:
                pass
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
        await ws.send_json({
            "type": "connected",
            "message": "Subscribed to market regime stream",
            "ts": time.time(),
        })
        while True:
            data = await ws.receive_text()
            _regime_last_active[ws] = time.monotonic()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong", "ts": time.time()})
                elif msg.get("type") == "subscribe":
                    symbols = msg.get("symbols", [])[:20]
                    if not symbols:
                        await ws.send_json({"type": "error", "message": "No symbols provided"})
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
                    await ws.send_json({
                        "type": "regime_data",
                        "data": regime_data,
                        "ts": time.time(),
                    })
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WebSocket Regime连接异常: %s", e)
    finally:
        async with _regime_lock:
            if ws in _regime_connections:
                _regime_connections.remove(ws)
            _regime_last_active.pop(ws, None)


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
                                await ws.send_json(msg)
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


def _build_message(msg_type: str, data: dict) -> dict[str, Any]:
    global _push_seq
    with _push_seq_lock:
        _push_seq += 1
        seq = _push_seq
    return {
        "type": msg_type,
        "ts": time.time(),
        "data": data,
        "seq": seq,
    }


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
            logger.info("Triggered %s price alerts", len)
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

            now = time.time()
            stale_symbols = [s for s, t in _symbol_last_push.items()
                             if not s.startswith("__") and now - t > 300]
            for s in stale_symbols:
                del _symbol_last_push[s]
                _symbol_priority.pop(s, None)

            quotes_data = {}
            subscribed_list = list(subscribed)[:_MAX_PUSH_SYMBOLS]
            now = time.time()
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
                for symbol, result in zip(fetch_symbols, results):
                    if isinstance(result, Exception):
                        logger.debug("Push quote fetch failed for %s: %s", symbol, result)
                        continue
                    rt = result
                    if rt:
                        price_str = f"{rt.get('price', 0)}_{rt.get('change_pct', 0)}"
                        if price_str != last_quote_hash_snapshot.get(symbol, ""):
                            quotes_data[symbol] = rt
                            _symbol_last_push[symbol] = now

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
            async with _push_state_lock:
                indices_hash = json.dumps(indices_data, sort_keys=True)[:64] if indices_data else ""
                should_push_indices = False
                if indices_data and indices_hash != _last_indices_hash:
                    indices_interval = _PRIORITY_INTERVALS.get(_PRIORITY_INDEX, 5)
                    last_indices_push = _symbol_last_push.get("__indices__", 0)
                    if now - last_indices_push >= indices_interval:
                        should_push_indices = True
                if should_push_indices:
                    _last_indices_hash = indices_hash
                    _symbol_last_push["__indices__"] = now

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

            if msg_data:
                msg_str = _build_message("quote_update", msg_data)
                connections = await _manager.get_connections_snapshot()
                if connections:
                    send_tasks = []
                    for ws in connections:
                        send_tasks.append(_safe_ws_send(ws, msg_str))
                    results = await asyncio.gather(*send_tasks, return_exceptions=True)
                    dead = [ws for ws, r in zip(connections, results) if isinstance(r, Exception)]
                    for ws in dead:
                        await _manager.disconnect(ws)

            await asyncio.sleep(2)
        except Exception as e:
            logger.warning("Push realtime error: %s", e)
            await asyncio.sleep(10)


async def push_signal_event(symbol: str, strategy: str, signal_type: str, score: float, price: float):
    if not await _manager.connection_count():
        return
    msg_str = _build_message("signal", {
        "symbol": symbol, "strategy": strategy,
        "signal_type": signal_type, "score": score, "price": price,
    })
    disconnected = []
    for ws in (await _manager.get_connections_snapshot()):
        subs = await _manager.get_subscriptions(ws)
        if not subs or symbol in subs:
            try:
                await ws.send_text(msg_str)
            except Exception as e:
                logger.debug("Signal push send failed: %s", e)
                disconnected.append(ws)
    for ws in disconnected:
        await _manager.disconnect(ws)


async def push_alert_event(symbol: str, alert_type: str, value: float, current_price: float):
    if not await _manager.connection_count():
        return
    msg_str = _build_message("alert", {
        "symbol": symbol, "alert_type": alert_type,
        "value": value, "current_price": current_price,
    })
    disconnected = []
    for ws in (await _manager.get_connections_snapshot()):
        subs = await _manager.get_subscriptions(ws)
        if not subs or symbol in subs:
            try:
                await ws.send_text(msg_str)
            except Exception as e:
                logger.debug("Alert push send failed: %s", e)
                disconnected.append(ws)
    for ws in disconnected:
        await _manager.disconnect(ws)


async def push_market_event(event_type: str, data: dict):
    if not await _manager.connection_count():
        return
    msg_str = _build_message("market_event", data)
    disconnected = []
    for ws in (await _manager.get_connections_snapshot()):
        try:
            await ws.send_text(msg_str)
        except Exception as e:
            logger.debug("市场事件推送失败: %s", e)
            disconnected.append(ws)
    for ws in disconnected:
        await _manager.disconnect(ws)


@router.get("/alpha/list")
async def list_alpha_factors(request: Request):
    try:
        from core.alpha_engine import AlphaGenerator
        gen = AlphaGenerator()
        alphas = gen.list_alphas()
        result = []
        for a in alphas:
            result.append({
                "name": a.name,
                "expression": a.expression,
                "category": a.category,
                "description": a.description,
            })
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


_portfolio_connections: dict[WebSocket, dict[str, Any]] = {}
_portfolio_lock = asyncio.Lock()
_PORTFOLIO_MAX_CONNECTIONS = 50
_PORTFOLIO_PUSH_INTERVAL = 5.0
_PORTFOLIO_CACHE_TTL = 3600
_portfolio_metrics_cache: dict[str, Any] = {}
_portfolio_cache_timestamps: dict[str, float] = {}


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
                    await ws.send_json({"type": "pong", "ts": time.time()})
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
                    await ws.send_json({
                        "type": "configured",
                        "symbol_count": len(symbols),
                        "base_value": base_value,
                        "ts": time.time(),
                    })
            except TimeoutError:
                await ws.send_json({"type": "keepalive", "ts": time.time()})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WebSocket portfolio连接异常: %s", e)
    finally:
        async with _portfolio_lock:
            _portfolio_connections.pop(ws, None)


async def push_portfolio_metrics(fetcher: SmartDataFetcher):
    global _portfolio_metrics_cache
    while True:
        try:
            await asyncio.sleep(_PORTFOLIO_PUSH_INTERVAL)

            now = time.time()
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

                    await ws.send_json({
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
                    })
                except Exception as e:
                    logger.debug("Portfolio metrics推送失败: %s", e)
        except Exception as e:
            logger.warning("Portfolio metrics pusher异常: %s", e)
            await asyncio.sleep(5)


@router.get("/market/events")
@cache_response(15)
async def get_market_events(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
):
    try:
        events = []

        try:
            from core.market_data import fetch_all_a_stocks_async
            stocks = await fetch_all_a_stocks_async()
            if stocks:
                limit_ups = [s for s in stocks if s.get("change_pct", 0) >= 9.5][:5]
                for s in limit_ups:
                    events.append({
                        "type": "limit_up",
                        "symbol": s.get("symbol", ""),
                        "name": s.get("name", ""),
                        "change_pct": round(s.get("change_pct", 0), 2),
                        "price": s.get("price", 0),
                        "volume": s.get("volume", 0),
                        "timestamp": time.time(),
                    })

                limit_downs = [s for s in stocks if s.get("change_pct", 0) <= -9.5][:5]
                for s in limit_downs:
                    events.append({
                        "type": "limit_down",
                        "symbol": s.get("symbol", ""),
                        "name": s.get("name", ""),
                        "change_pct": round(s.get("change_pct", 0), 2),
                        "price": s.get("price", 0),
                        "volume": s.get("volume", 0),
                        "timestamp": time.time(),
                    })

                volume_spikes = sorted(
                    [s for s in stocks if s.get("volume_ratio", 0) >= 3],
                    key=lambda x: x.get("volume_ratio", 0),
                    reverse=True,
                )[:5]
                for s in volume_spikes:
                    events.append({
                        "type": "volume_spike",
                        "symbol": s.get("symbol", ""),
                        "name": s.get("name", ""),
                        "change_pct": round(s.get("change_pct", 0), 2),
                        "volume_ratio": round(s.get("volume_ratio", 0), 1),
                        "price": s.get("price", 0),
                        "timestamp": time.time(),
                    })
        except Exception as e:
            logger.debug("获取市场事件数据失败: %s", e)

        events.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return _json_response(True, data=events[:limit])
    except Exception as e:
        logger.error("market events error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


@router.get("/alpha/compute/{symbol}")
async def compute_alpha_factors(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
):
    try:
        from core.alpha_engine import AlphaGenerator
        from core.alpha_screener import AlphaScreener, AlphaScreeningConfig
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="数据不足")

        gen = AlphaGenerator()
        alpha_values = gen.compute_all_alphas(df)

        screener = AlphaScreener(AlphaScreeningConfig(ic_threshold=0.01, ic_ir_threshold=0.1))
        screened = screener.screen_all(alpha_values, df["close"])

        result = []
        for name, r in screened.items():
            result.append({
                "name": name,
                "ic": r.ic,
                "ic_ir": r.ic_ir,
                "turnover": r.turnover,
                "decay": r.decay,
                "passed": r.passed,
                "category": r.category,
            })
        result.sort(key=lambda x: abs(x["ic_ir"]), reverse=True)
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/regime/detect/{symbol}")
async def detect_market_regime(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
):
    try:
        from core.regime_detector import RegimeDetector
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")

        detector = RegimeDetector()
        result = detector.detect(df)
        summary = detector.get_regime_summary(result)
        return _json_response(True, data=summary)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/risk/monitor/{symbol}")
async def get_risk_monitor(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
):
    try:
        from core.risk_monitor import EnhancedRiskMonitor
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")

        monitor = EnhancedRiskMonitor()
        close = df["close"].astype(float)
        for price in close:
            monitor.update_equity(float(price))

        returns = close.pct_change().dropna()
        metrics = monitor.get_risk_metrics(returns=returns)
        should_liquidate, liq_reason = monitor.should_force_liquidate(metrics)
        should_reduce, reduce_scale, reduce_reason = monitor.should_reduce_position(metrics)

        return _json_response(True, data={
            "risk_level": metrics.risk_level.value,
            "volatility": metrics.volatility,
            "max_drawdown": metrics.max_drawdown,
            "current_drawdown": metrics.current_drawdown,
            "var_95": metrics.var_95,
            "cvar_95": metrics.cvar_95,
            "sharpe_ratio": metrics.sharpe_ratio,
            "sortino_ratio": metrics.sortino_ratio,
            "warnings": metrics.warnings,
            "should_force_liquidate": should_liquidate,
            "should_reduce_position": should_reduce,
            "reduce_scale": reduce_scale,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/metrics/institutional/{symbol}")
async def get_institutional_metrics(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    benchmark: str = Query("sh000300", max_length=20),
    period: str = Query("1y", max_length=5),
):
    try:
        from core.metrics import calc_all_metrics, metrics_to_dict
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")

        close = df["close"].astype(float)
        equity_curve = list(close / close.iloc[0] * 100000)
        returns = close.pct_change().dropna()

        benchmark_returns = None
        try:
            bench_df = await fetcher.get_history(benchmark, _period_to_history(period), "daily", "qfq")
            if not bench_df.empty:
                benchmark_returns = bench_df["close"].astype(float).pct_change().dropna()
        except Exception as e:
            logger.debug("Benchmark fetch failed: %s", e)

        metrics = calc_all_metrics(equity_curve, returns, benchmark_returns)
        return _json_response(True, data=metrics_to_dict(metrics))
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/alpha/evolve")
async def run_alpha_evolution(
    request: Request,
    body: AlphaEvolveRequest,
):
    try:
        from core.self_evolver import EvolutionConfig, SelfEvolver
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, _period_to_history(body.period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="数据不足")

        config = EvolutionConfig(max_iterations=body.max_iterations)
        evolver = SelfEvolver(config=config)
        result = await asyncio.to_thread(evolver.evolve, df)
        report = evolver.get_evolution_report(result)
        return _json_response(True, data=report)
    except Exception as e:
        logger.error("Alpha evolution error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/audit/strategy")
async def audit_strategy(
    request: Request,
    body: AuditStrategyRequest,
):
    try:
        from core.auto_auditor import AutoAuditor
        from core.backtest import BacktestEngine
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, _period_to_history(body.period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="数据不足")

        strategy_cls = STRATEGY_REGISTRY.get(body.strategy_name)
        if not strategy_cls:
            return _json_response(False, error=f"未知策略: {body.strategy_name}")

        strategy = strategy_cls()
        engine = BacktestEngine(initial_capital=1000000)
        await asyncio.to_thread(engine.run, strategy, df)

        n = len(df)
        train_end = int(n * 0.7)
        train_df = df.iloc[:train_end]
        test_df = df.iloc[train_end:]

        train_result = engine.run(strategy, train_df)
        test_result = engine.run(strategy, test_df)

        from core.walk_forward import calc_strategy_metrics
        train_metrics = calc_strategy_metrics(train_result.equity_curve)
        test_metrics = calc_strategy_metrics(test_result.equity_curve)

        returns = df["close"].astype(float).pct_change().dropna()
        auditor = AutoAuditor()
        audit_report = auditor.audit(train_metrics, test_metrics, returns)

        return _json_response(True, data={
            "passed": audit_report.passed,
            "overall_score": audit_report.overall_score,
            "overfitting": {
                "is_overfitted": audit_report.overfitting.is_overfitted,
                "score": audit_report.overfitting.overfitting_score,
                "sharpe_gap": audit_report.overfitting.train_test_sharpe_gap,
            },
            "return_anomaly": {
                "has_anomaly": audit_report.return_anomaly.has_anomaly,
                "score": audit_report.return_anomaly.anomaly_score,
                "types": audit_report.return_anomaly.anomaly_types,
            },
            "recommendations": audit_report.recommendations,
        })
    except Exception as e:
        logger.error("Audit error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/data/cache-status")
async def get_data_cache_status(request: Request):
    try:
        import os

        import psutil

        from core.data_fetcher import (
            _financial_cache,
            _history_cache,
            _indicator_cache,
            _northbound_cache,
            _realtime_cache,
        )

        caches = {
            "realtime": {"size": len(_realtime_cache), "maxsize": _realtime_cache._maxsize, "ttl_sec": _realtime_cache._ttl},
            "history": {"size": len(_history_cache), "maxsize": _history_cache._maxsize, "ttl_sec": _history_cache._ttl},
            "indicator": {"size": len(_indicator_cache), "maxsize": _indicator_cache._maxsize, "ttl_sec": _indicator_cache._ttl},
            "financial": {"size": len(_financial_cache), "maxsize": _financial_cache._maxsize, "ttl_sec": _financial_cache._ttl},
            "northbound": {"size": len(_northbound_cache), "maxsize": _northbound_cache._maxsize, "ttl_sec": _northbound_cache._ttl},
        }

        total_entries = sum(c["size"] for c in caches.values())
        total_capacity = sum(c["maxsize"] for c in caches.values())

        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()

        return _json_response(True, data={
            "caches": caches,
            "summary": {
                "total_entries": total_entries,
                "total_capacity": total_capacity,
                "utilization_pct": round(total_entries / max(total_capacity, 1) * 100, 1),
            },
            "memory": {
                "rss_mb": round(mem_info.rss / 1024 / 1024, 1),
                "vms_mb": round(mem_info.vms / 1024 / 1024, 1),
            },
            "timestamp": datetime.now().isoformat(),
        })
    except ImportError:
        from core.data_fetcher import (
            _financial_cache,
            _history_cache,
            _indicator_cache,
            _northbound_cache,
            _realtime_cache,
        )
        return _json_response(True, data={
            "caches": {
                "realtime": {"size": len(_realtime_cache), "ttl_sec": _realtime_cache._ttl},
                "history": {"size": len(_history_cache), "ttl_sec": _history_cache._ttl},
                "indicator": {"size": len(_indicator_cache), "ttl_sec": _indicator_cache._ttl},
                "financial": {"size": len(_financial_cache), "ttl_sec": _financial_cache._ttl},
                "northbound": {"size": len(_northbound_cache), "ttl_sec": _northbound_cache._ttl},
            },
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


BREADTH_INDICES = {
    "sh000001": "上证综指",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000688": "科创50",
    "sh000300": "沪深300",
    "sh000016": "上证50",
    "sz399005": "中小100",
}


@router.get("/market/breadth/indices")
async def get_market_breadth_indices(
    request: Request,
    period: str = Query("5d", max_length=5),
):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher

        breadth_data = {}
        advancing = 0
        declining = 0
        total_volume_up = 0.0
        total_volume_down = 0.0

        for code, name in BREADTH_INDICES.items():
            try:
                df = await fetcher.get_history(code, _period_to_history(period), "daily", "")
                if df.empty or len(df) < 2:
                    continue
                close = df["close"].astype(float)
                volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series([0])
                latest_close = close.iloc[-1]
                prev_close = close.iloc[-2]
                change_pct = (latest_close - prev_close) / prev_close * 100 if prev_close > 0 else 0

                breadth_data[code] = {
                    "name": name,
                    "close": round(float(latest_close), 2),
                    "change_pct": round(float(change_pct), 2),
                }

                if change_pct > 0:
                    advancing += 1
                    if "volume" in df.columns:
                        total_volume_up += float(volume.iloc[-1])
                elif change_pct < 0:
                    declining += 1
                    if "volume" in df.columns:
                        total_volume_down += float(volume.iloc[-1])
            except Exception as e:
                logger.debug("Breadth calc failed for %s: %s", code, e)
                continue

        total_idx = advancing + declining + (len(breadth_data) - advancing - declining)
        ad_ratio = advancing / max(declining, 1)
        breadth_pct = advancing / max(total_idx, 1) * 100
        breadth_signal = "bullish" if breadth_pct >= 60 else ("bearish" if breadth_pct <= 40 else "neutral")

        volume_ratio = total_volume_up / max(total_volume_down, 1.0) if total_volume_down > 0 else 1.0

        return _json_response(True, data={
            "indices": breadth_data,
            "breadth": {
                "advancing": advancing,
                "declining": declining,
                "ad_ratio": round(float(ad_ratio), 2),
                "breadth_pct": round(float(breadth_pct), 1),
                "signal": breadth_signal,
                "up_volume_ratio": round(float(volume_ratio), 2),
            },
            "period": period,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error("Market breadth error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/optimize")
async def optimize_portfolio(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    method: str = Query("max_sharpe", max_length=20),
    risk_free_rate: float = Query(0.03),
    period: str = Query("1y", max_length=5),
):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if len(symbol_list) < 2:
            return _json_response(False, error="至少需要2只股票")
        if len(symbol_list) > 30:
            return _json_response(False, error="最多支持30只股票")

        from core.portfolio_optimizer import (
            ic_weighted_optimize,
            mean_variance_optimize,
            risk_parity_optimize,
        )

        history_map = await fetcher.get_history_batch(symbol_list[:30], _period_to_history(period), "daily", "qfq")
        all_returns = {}
        for sym, df in history_map.items():
            if len(df) >= 30:
                c = df["close"].astype(float)
                ret = c.pct_change().dropna()
                ret = ret[np.isfinite(ret)]
                all_returns[sym] = ret.values[-252:]

        if len(all_returns) < 2:
            return _json_response(False, error="有效数据不足")

        symbols_valid = list(all_returns.keys())
        min_len = min(len(v) for v in all_returns.values())
        ret_matrix = np.column_stack([all_returns[s][-min_len:] for s in symbols_valid])
        expected_returns = ret_matrix.mean(axis=0) * 252
        cov_matrix = np.cov(ret_matrix.T)

        n = len(symbols_valid)
        if method == "max_sharpe":
            weights = mean_variance_optimize(expected_returns, cov_matrix, risk_free_rate)
        elif method == "risk_parity":
            weights = risk_parity_optimize(cov_matrix)
        elif method == "ic_weighted":
            returns_df = pd.DataFrame({s: all_returns[s][-min_len:] for s in symbols_valid})
            ics = np.array([returns_df[s].corr(returns_df.mean(axis=1)) for s in symbols_valid])
            vols = returns_df.std().values
            weights = ic_weighted_optimize(ics, vols)
        elif method == "equal":
            weights = np.ones(n) / n
        elif method == "min_variance":
            try:
                inv_cov = np.linalg.inv(cov_matrix)
                ones = np.ones(n)
                weights = inv_cov @ ones / (ones @ inv_cov @ ones)
                weights = np.clip(weights, 0, 0.3)
                weights = weights / weights.sum()
            except np.linalg.LinAlgError:
                weights = np.ones(n) / n
        else:
            return _json_response(False, error=f"不支持的优化方法: {method}")

        weights = np.array(weights)
        if weights.sum() > 0:
            weights = weights / weights.sum()

        allocations = []
        for i, sym in enumerate(symbols_valid):
            w = float(weights[i]) if i < len(weights) else 0.0
            allocations.append({
                "symbol": sym,
                "weight": round(w, 4),
                "weight_pct": round(w * 100, 1),
            })

        port_ret = float(weights @ expected_returns) if len(weights) == len(expected_returns) else 0
        port_vol = float(np.sqrt(weights @ cov_matrix @ weights)) if len(weights) == len(expected_returns) else 0
        port_sharpe = (port_ret - risk_free_rate) / max(port_vol, 1e-10)

        return _json_response(True, data={
            "method": method,
            "allocations": allocations,
            "metrics": {
                "expected_annual_return": round(port_ret, 4),
                "expected_volatility": round(port_vol, 4),
                "sharpe_ratio": round(port_sharpe, 2),
                "risk_free_rate": risk_free_rate,
            },
            "symbols": symbols_valid,
            "period": period,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error("Portfolio optimization error: %s", e)
        return _json_response(False, error=safe_error(e))


class BlackLittermanRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=2, max_length=20)
    views: list[dict[str, Any]] = Field(default_factory=list)
    market_weights: dict[str, float] | None = Field(None)
    view_confidences: list[float] | None = Field(None)
    risk_free_rate: float = Field(0.03, ge=0.0, le=0.2)
    tau: float = Field(0.05, ge=0.001, le=1.0)
    risk_aversion: float = Field(2.5, ge=0.1, le=10.0)
    period: str = Field("1y", max_length=5)


@router.post("/portfolio/black-litterman")
async def black_litterman_optimize(request: Request, body: BlackLittermanRequest):
    try:
        from core.black_litterman import BlackLittermanModel

        fetcher: SmartDataFetcher = request.app.state.fetcher
        history_map = await fetcher.get_history_batch(
            body.symbols, _period_to_history(body.period), "daily", "qfq"
        )
        price_data = {}
        for sym, df in history_map.items():
            if df is not None and len(df) >= 30:
                price_data[sym] = df["close"].astype(float).values

        if len(price_data) < 2:
            return _json_response(False, error="有效数据不足，至少需要2只股票")

        min_len = min(len(v) for v in price_data.values())
        prices_df = pd.DataFrame({sym: v[-min_len:] for sym, v in price_data.items()})

        model = BlackLittermanModel(
            risk_free_rate=body.risk_free_rate,
            tau=body.tau,
            risk_aversion=body.risk_aversion,
        )
        result = model.optimize(
            prices_df,
            views=body.views,
            market_weights=body.market_weights,
            view_confidences=body.view_confidences,
        )

        return _json_response(result.is_valid, data={
            "posterior_returns": result.posterior_returns,
            "weights": result.weights,
            "expected_return": round(result.expected_return, 4),
            "expected_volatility": round(result.expected_volatility, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "message": result.message,
        })
    except Exception as e:
        logger.error("Black-Litterman optimization error: %s", e)
        return _json_response(False, error=safe_error(e))


class MonteCarloVaRRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1, max_length=20)
    weights: dict[str, float] | None = Field(None)
    n_simulations: int = Field(10000, ge=1000, le=100000)
    time_horizon: int = Field(1, ge=1, le=252)
    method: str = Field("parametric", pattern=r"^(parametric|historical)$")
    period: str = Field("1y", max_length=5)


@router.post("/portfolio/monte-carlo-var")
async def monte_carlo_var(request: Request, body: MonteCarloVaRRequest):
    try:
        from core.monte_carlo_var import MonteCarloVaR

        fetcher: SmartDataFetcher = request.app.state.fetcher
        history_map = await fetcher.get_history_batch(
            body.symbols, _period_to_history(body.period), "daily", "qfq"
        )
        price_data = {}
        for sym, df in history_map.items():
            if df is not None and len(df) >= 30:
                price_data[sym] = df["close"].astype(float).values

        if len(price_data) < 1:
            return _json_response(False, error="有效数据不足")

        min_len = min(len(v) for v in price_data.values())
        prices_df = pd.DataFrame({sym: v[-min_len:] for sym, v in price_data.items()})

        engine = MonteCarloVaR(
            n_simulations=body.n_simulations,
            time_horizon=body.time_horizon,
        )

        if body.method == "historical":
            result = engine.simulate_historical(prices_df, body.weights)
        else:
            result = engine.simulate(prices_df, body.weights)

        return _json_response(result.is_valid, data={
            "var_95": round(result.var_95, 6),
            "var_99": round(result.var_99, 6),
            "cvar_95": round(result.cvar_95, 6),
            "cvar_99": round(result.cvar_99, 6),
            "mean_portfolio_return": round(result.mean_portfolio_return, 6),
            "std_portfolio_return": round(result.std_portfolio_return, 6),
            "n_simulations": result.n_simulations,
            "confidence_levels": result.confidence_levels,
            "method": body.method,
            "message": result.message,
        })
    except Exception as e:
        logger.error("Monte Carlo VaR error: %s", e)
        return _json_response(False, error=safe_error(e))


class SeasonalityRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    period: str = Field("3y", max_length=5)


@router.post("/seasonality/analyze")
async def analyze_seasonality_endpoint(request: Request, body: SeasonalityRequest):
    try:
        from core.seasonality import analyze_seasonality

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, _period_to_history(body.period), "daily", "qfq")

        if df is None or len(df) < 30:
            return _json_response(False, error="数据不足，至少需要30个交易日")

        report = analyze_seasonality(df, symbol=body.symbol, period=body.period)
        return _json_response(True, data=report.to_dict())
    except Exception as e:
        logger.error("Seasonality analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


class CointegrationTestRequest(BaseModel):
    symbol_y: str = Field(..., min_length=1, max_length=20)
    symbol_x: str = Field(..., min_length=1, max_length=20)
    method: str = Field("engle_granger", pattern=r"^(engle_granger|johansen)$")
    significance: float = Field(0.05, ge=0.01, le=0.20)
    period: str = Field("1y", max_length=5)


class PairMiningRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=2, max_length=30)
    method: str = Field("engle_granger", pattern=r"^(engle_granger|johansen)$")
    pvalue_threshold: float = Field(0.05, ge=0.01, le=0.20)
    period: str = Field("1y", max_length=5)


@router.post("/statistical-arbitrage/cointegration")
async def cointegration_test(request: Request, body: CointegrationTestRequest):
    try:
        from core.statistical_arbitrage import engle_granger_test, johansen_test

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df_y = await fetcher.get_history(body.symbol_y, _period_to_history(body.period), "daily", "qfq")
        df_x = await fetcher.get_history(body.symbol_x, _period_to_history(body.period), "daily", "qfq")

        if df_y is None or df_x is None or len(df_y) < 30 or len(df_x) < 30:
            return _json_response(False, error="数据不足，至少需要30个交易日")

        y = df_y["close"].astype(float)
        x = df_x["close"].astype(float)
        y.name = body.symbol_y
        x.name = body.symbol_x

        if body.method == "johansen":
            pair_df = pd.DataFrame({body.symbol_y: y.values, body.symbol_x: x.values})
            results = johansen_test(pair_df, significance=body.significance)
            if not results:
                return _json_response(True, data={"cointegrated": False, "results": []})
            return _json_response(True, data={
                "cointegrated": results[0].is_cointegrated,
                "results": [r.to_dict() for r in results],
            })
        else:
            result = engle_granger_test(y, x, significance=body.significance)
            return _json_response(True, data={
                "cointegrated": result.is_cointegrated,
                "results": [result.to_dict()],
            })
    except Exception as e:
        logger.error("Cointegration test error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/statistical-arbitrage/pair-mining")
async def pair_mining(request: Request, body: PairMiningRequest):
    try:
        from core.statistical_arbitrage import PairMiningEngine

        fetcher: SmartDataFetcher = request.app.state.fetcher
        history_map = await fetcher.get_history_batch(
            body.symbols, _period_to_history(body.period), "daily", "qfq"
        )
        price_data = {}
        for sym, df in history_map.items():
            if df is not None and len(df) >= 30:
                price_data[sym] = df["close"].astype(float).values

        if len(price_data) < 2:
            return _json_response(False, error="有效数据不足，至少需要2只股票")

        min_len = min(len(v) for v in price_data.values())
        prices_df = pd.DataFrame({sym: v[-min_len:] for sym, v in price_data.items()})

        engine = PairMiningEngine(
            pvalue_threshold=body.pvalue_threshold,
            method=body.method,
        )
        results = engine.find_cointegrated_pairs(prices_df, list(prices_df.columns))

        return _json_response(True, data={
            "n_pairs_tested": len(list(combinations(list(prices_df.columns), 2))),
            "n_cointegrated": len(results),
            "pairs": [r.to_dict() for r in results[:20]],
        })
    except Exception as e:
        logger.error("Pair mining error: %s", e)
        return _json_response(False, error=safe_error(e))


class TWAPSimulationRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    total_qty: int = Field(..., gt=0, le=10000000)
    n_slices: int = Field(10, ge=1, le=100)
    duration_minutes: int = Field(60, ge=1, le=480)
    jitter_pct: float = Field(0.0, ge=0.0, le=0.5)


@router.post("/execution/twap-simulate")
async def twap_simulation(request: Request, body: TWAPSimulationRequest):
    try:
        from core.execution_algorithms import MarketState, TWAPAlgorithm

        fetcher: SmartDataFetcher = request.app.state.fetcher
        market = MarketDetector.detect(body.symbol)
        rt = await fetcher.get_realtime(body.symbol, market)
        current_price = rt.get("price", 0) if rt else 0

        if current_price <= 0:
            df = await fetcher.get_history(body.symbol, "1mo", "daily", "qfq")
            if df is not None and len(df) > 0:
                current_price = float(df["close"].iloc[-1])
        if current_price <= 0:
            return _json_response(False, error="无法获取当前价格")

        now = datetime.now()
        end_time = now + timedelta(minutes=body.duration_minutes)

        algo = TWAPAlgorithm(
            total_qty=body.total_qty,
            start_time=now,
            end_time=end_time,
            n_slices=body.n_slices,
            jitter_pct=body.jitter_pct,
        )

        slices = []
        sim_time = now
        market_state = MarketState(
            current_price=current_price,
            current_volume=0,
            vwap=current_price,
            time_in_session_pct=0.5,
            adv_20d=0,
            bid_ask_spread=0.001,
        )

        while not algo.is_complete():
            order_slice = algo.next_slice(sim_time, market_state)
            if order_slice is None:
                sim_time += timedelta(seconds=body.duration_minutes * 60 / body.n_slices)
                continue
            slices.append({
                "quantity": order_slice.quantity,
                "limit_price": order_slice.limit_price,
                "time_offset_seconds": round(order_slice.time_offset_seconds, 1),
                "estimated_value": round(order_slice.quantity * current_price, 2),
            })
            sim_time += timedelta(seconds=body.duration_minutes * 60 / body.n_slices)

        total_value = sum(s["estimated_value"] for s in slices)
        return _json_response(True, data={
            "symbol": body.symbol,
            "current_price": current_price,
            "total_qty": body.total_qty,
            "n_slices": len(slices),
            "duration_minutes": body.duration_minutes,
            "slices": slices,
            "total_estimated_value": round(total_value, 2),
            "avg_slice_qty": round(body.total_qty / max(len(slices), 1), 1),
        })
    except Exception as e:
        logger.error("TWAP simulation error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/data/quality/{symbol}")
async def check_data_quality(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("90d", max_length=5),
):
    try:
        from core.data_fetcher import DataQualityChecker
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df is None or df.empty:
            return _json_response(False, error="无数据")

        cleaned_df, warnings = DataQualityChecker.check_kline(df)
        events = DataQualityChecker.detect_corporate_actions(df)

        quality_score = max(0, 100 - len(warnings) * 5 - (0 if len(cleaned_df) > 0 else 50))
        quality_grade = "A" if quality_score >= 90 else ("B" if quality_score >= 70 else ("C" if quality_score >= 50 else "D"))

        return _json_response(True, data={
            "symbol": symbol,
            "quality": {
                "score": quality_score,
                "grade": quality_grade,
                "warnings": warnings,
                "original_rows": len(df),
                "cleaned_rows": len(cleaned_df),
                "rows_removed": len(df) - len(cleaned_df),
            },
            "corporate_events": events[:20],
            "period": period,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error("Data quality check error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/strategies/list")
async def list_strategies():
    try:
        seen_classes = {}
        for name, cls in STRATEGY_REGISTRY.items():
            base_name = cls.__name__
            if base_name in seen_classes:
                continue
            seen_classes[base_name] = {
                "name": base_name,
                "aliases": [name],
            }
        for name, cls in STRATEGY_REGISTRY.items():
            base_name = cls.__name__
            if name not in seen_classes[base_name]["aliases"]:
                seen_classes[base_name]["aliases"].append(name)

        strategies = []
        strategy_descriptions = {
            "DualMAStrategy": "双均线交叉策略，快速均线上穿慢速均线买入",
            "MACDStrategy": "MACD金叉死叉策略，DIF上穿DEA买入",
            "KDJStrategy": "KDJ超买超卖策略，J线下穿低频买入",
            "BollingerBreakoutStrategy": "布林带突破策略，价格突破上轨做多",
            "MomentumStrategy": "动量策略，多周期动量确认",
            "MultiFactorConfluenceStrategy": "多因子共振策略，量化因子打分",
            "AdaptiveTrendFollowingStrategy": "自适应趋势策略，动态调整均线参数",
            "MeanReversionProStrategy": "均值回归策略，RSI+布林带+成交量确认",
            "VolatilitySqueezeBreakoutStrategy": "波动率压缩突破，BB宽度+ATR综合",
            "PatternTradingStrategy": "形态交易策略，识别经典K线形态",
            "OrderFlowOBVStrategy": "订单流OBV策略，成交量验证价格",
            "PriceVolumeTrend": "价量趋势策略，价量背离检测",
        }

        for base_name, info in sorted(seen_classes.items()):
            strategies.append({
                "name": base_name,
                "aliases": info["aliases"],
                "description": strategy_descriptions.get(base_name, "自定义策略"),
            })

        return _json_response(True, data={
            "total": len(strategies),
            "strategies": strategies,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/strategies/plugin-health")
async def plugin_health():
    try:
        from core.plugin_manager import PluginManager
        pm = PluginManager.get_instance()
        pm.register_from_registry(STRATEGY_REGISTRY)
        health = pm.get_health_report()
        return _json_response(True, data={
            "total": health.total_plugins,
            "healthy": health.healthy,
            "degraded": health.degraded,
            "failed": health.failed,
            "plugins": health.plugins,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error("Plugin health check failed: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/strategies/reload/{strategy_name}")
async def reload_strategy(strategy_name: str):
    try:
        from core.plugin_manager import PluginManager
        pm = PluginManager.get_instance()
        success = pm.reload_plugin(strategy_name)
        if success:
            return _json_response(True, data={"reloaded": strategy_name})
        return _json_response(False, error=f"Strategy '{strategy_name}' not reloadable or not found")
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/strategies/ranking")
async def strategy_ranking(
    symbol: str = Query("600519", max_length=10),
    period: str = Query("6mo", max_length=5),
):
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY
        get_db()
        fetcher = get_fetcher()
        kline = await fetcher.get_history(symbol, period=period)
        if kline is None or kline.empty:
            return _json_response(False, error="No kline data available")

        seen_classes = {}
        for _name, cls in STRATEGY_REGISTRY.items():
            base_name = cls.__name__
            if base_name not in seen_classes:
                seen_classes[base_name] = cls

        results = []
        for base_name, cls in seen_classes.items():
            try:
                strategy = cls()
                engine = BacktestEngine()
                result = engine.run(strategy, kline)
                if result:
                    sd = result.summary_dict()
                    sd["strategy"] = base_name
                    sd["trade_count"] = sd.pop("total_trades", 0)
                    results.append(sd)
            except Exception as e:
                logger.debug("策略排名-跳过股票 %s: %s", symbol, e)
                continue

        results.sort(key=lambda x: x.get("sharpe_ratio", float("-inf")), reverse=True)
        for i, r in enumerate(results):
            r["rank"] = i + 1

        return _json_response(True, data={
            "symbol": symbol,
            "period": period,
            "ranking": results[:15],
            "evaluated": len(results),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


CACHE_CLEAR_MAP = {
    "realtime": "_realtime_cache",
    "history": "_history_cache",
    "indicator": "_indicator_cache",
    "financial": "_financial_cache",
    "northbound": "_northbound_cache",
}


@router.post("/system/cache/clear")
async def clear_cache(
    request: Request,
    cache_name: str = Query("all", max_length=20),
):
    try:
        import importlib
        module = importlib.import_module("core.data_fetcher")

        if cache_name == "all":
            cleared = {}
            for name, attr in CACHE_CLEAR_MAP.items():
                cache = getattr(module, attr, None)
                if cache is not None:
                    prev_size = len(cache)
                    cache.clear()
                    cleared[name] = prev_size
            return _json_response(True, data={
                "action": "clear_all",
                "cleared": cleared,
                "timestamp": datetime.now().isoformat(),
            })
        else:
            attr = CACHE_CLEAR_MAP.get(cache_name)
            if not attr:
                return _json_response(False, error=f"不支持的缓存类型: {cache_name}，可选: {list(CACHE_CLEAR_MAP.keys())}")
            cache = getattr(module, attr, None)
            if cache is None:
                return _json_response(False, error="缓存模块不可用")
            prev_size = len(cache)
            cache.clear()
            return _json_response(True, data={
                "cache_name": cache_name,
                "cleared_entries": prev_size,
                "timestamp": datetime.now().isoformat(),
            })
    except Exception as e:
        logger.error("Cache clear error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/fusion/methods")
async def fusion_methods():
    methods = [
        {"id": "ic_vol", "name": "IC-波动率加权", "description": "按IC绝对值/信号波动率分配权重，兼顾预测力和稳定性"},
        {"id": "equal", "name": "等权融合", "description": "所有策略等权重，简单稳健"},
        {"id": "ic", "name": "IC加权", "description": "按IC绝对值分配权重，偏向预测力强的因子"},
        {"id": "sharpe", "name": "Sharpe加权", "description": "按历史Sharpe比率分配权重"},
        {"id": "rank", "name": "Rank加权", "description": "按IC排名分配权重，减少极端值影响"},
    ]
    return _json_response(True, data={"methods": methods})


@router.post("/fusion/signal")
async def fusion_signal(
    request: Request,
    symbol: str = Query(..., max_length=10),
    method: str = Query("ic_vol", max_length=10),
    min_ic: float = Query(0.02, ge=0),
    max_strategies: int = Query(10, ge=1, le=20),
    period: str = Query("6mo", max_length=5),
):
    try:
        from core.alpha_engine import AlphaEngine
        from core.strategy_fusion import FusionConfig, StrategyFusion
        fetcher = get_fetcher()
        kline = await fetcher.get_history(symbol, period=period)
        if kline is None or kline.empty:
            return _json_response(False, error="No kline data available")

        alpha_engine = AlphaEngine()
        alpha_results = alpha_engine.compute_all(kline)

        config = FusionConfig(
            method=method, min_ic=min_ic, max_strategies=max_strategies,
        )
        fusion = StrategyFusion(config)
        result = fusion.fuse(alpha_results, method=method)

        signal_stats = {}
        if len(result.combined_signal) > 0:
            cs = result.combined_signal
            signal_stats = {
                "mean": round(float(cs.mean()), 6),
                "std": round(float(cs.std()), 6),
                "min": round(float(cs.min()), 6),
                "max": round(float(cs.max()), 6),
                "latest": round(float(cs.iloc[-1]), 6),
            }

        return _json_response(True, data={
            "symbol": symbol,
            "method": result.method,
            "n_strategies": result.n_strategies,
            "weights": result.strategy_weights,
            "contribution": result.contribution,
            "signal_stats": signal_stats,
            "latest_signal": "bullish" if signal_stats.get("latest", 0) > 0.5 else (
                "bearish" if signal_stats.get("latest", 0) < -0.5 else "neutral"
            ),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/execution/methods")
async def execution_methods():
    methods = [
        {"id": "market", "name": "市价单", "description": "立即以当前价格成交，含滑点模拟"},
        {"id": "twap", "name": "TWAP时间加权", "description": "将订单均匀分拆到N个时间bar执行"},
        {"id": "vwap", "name": "VWAP成交量加权", "description": "按历史成交量分布分拆订单执行"},
    ]
    return _json_response(True, data={"methods": methods})


@router.post("/execution/simulate")
async def execution_simulate(
    request: Request,
    symbol: str = Query(..., max_length=10),
    side: str = Query("buy", max_length=4),
    quantity: int = Query(..., gt=0),
    method: str = Query("market", max_length=10),
    n_bars: int = Query(6, ge=1, le=20),
):
    try:
        from core.execution_engine import ExecutionEngine
        if side not in ("buy", "sell"):
            return _json_response(False, error="side must be 'buy' or 'sell'")
        if method not in ("market", "twap", "vwap"):
            return _json_response(False, error="method must be 'market', 'twap', or 'vwap'")

        fetcher = get_fetcher()
        rt = fetcher.get_realtime(symbol)
        if not rt or rt.get("price", 0) <= 0:
            return _json_response(False, error="No realtime price available")

        current_price = float(rt["price"])
        engine = ExecutionEngine()

        if method == "market":
            result = engine.execute_market_order(side, quantity, current_price)
        elif method == "twap":
            kline = await fetcher.get_history(symbol, period="1mo")
            if kline is None or kline.empty:
                return _json_response(False, error="No history data for TWAP")
            result = engine.execute_twap_order(side, quantity, kline, n_bars=n_bars)
        else:
            kline = await fetcher.get_history(symbol, period="1mo")
            if kline is None or kline.empty:
                return _json_response(False, error="No history data for VWAP")
            result = engine.execute_vwap_order(side, quantity, kline, n_bars=n_bars)

        return _json_response(True, data={
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "method": result.execution_method,
            "filled_quantity": result.filled_quantity,
            "avg_fill_price": round(result.avg_fill_price, 4),
            "total_cost": round(result.total_cost, 2),
            "slippage": round(result.slippage, 2),
            "commission": round(result.commission, 2),
            "stamp_tax": round(result.stamp_tax, 2),
            "cost_bps": round(result.total_cost / (current_price * quantity) * 10000, 2) if quantity > 0 else 0,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/alpha/screen")
async def alpha_screen(
    request: Request,
    symbol: str = Query(..., max_length=10),
    ic_threshold: float = Query(0.02, ge=0),
    ic_ir_threshold: float = Query(0.3, ge=0),
    period: str = Query("1y", max_length=5),
):
    try:
        from core.alpha_engine import AlphaEngine
        from core.alpha_screener import AlphaScreener
        fetcher = get_fetcher()
        kline = await fetcher.get_history(symbol, period=period)
        if kline is None or kline.empty:
            return _json_response(False, error="No kline data available")

        alpha_engine = AlphaEngine()
        alpha_results = alpha_engine.compute_all(kline)

        screener = AlphaScreener()
        screener.screen(
            alpha_results,
            ic_threshold=ic_threshold,
            ic_ir_threshold=ic_ir_threshold,
        )

        screened = []
        for name, result in alpha_results.items():
            screened.append({
                "name": name,
                "ic": round(result.ic, 6),
                "ic_ir": round(result.ic_ir, 6),
                "turnover": round(result.turnover, 4) if hasattr(result, "turnover") else None,
                "pass": abs(result.ic) >= ic_threshold and abs(result.ic_ir) >= ic_ir_threshold,
            })
        screened.sort(key=lambda x: abs(x.get("ic_ir", 0)), reverse=True)

        passed = [s for s in screened if s["pass"]]
        return _json_response(True, data={
            "symbol": symbol,
            "total_factors": len(screened),
            "passed": len(passed),
            "pass_rate": round(len(passed) / len(screened) * 100, 1) if screened else 0,
            "factors": screened[:20],
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))




@router.post("/stock/batch/analysis")
@rate_limiter(max_calls=10, time_window=60.0)
async def batch_stock_analysis(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码，最多20个"),
    period: str = Query("6m", max_length=5, description="分析周期"),
):
    """批量股票分析 — 一次调用返回多只股票的关键指标摘要"""
    try:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            return _json_response(False, error="请提供股票代码")
        symbol_list = symbol_list[:20]

        fetcher: SmartDataFetcher = request.app.state.fetcher
        history_map = await fetcher.get_history_batch(
            symbol_list, _period_to_history(period), "daily", "qfq"
        )

        results = []
        for sym in symbol_list:
            try:
                df = history_map.get(sym)
                if df is None or len(df) < 20:
                    results.append({"symbol": sym, "error": "数据不足"})
                    continue

                close = df["close"].astype(float)
                volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series(dtype=float)

                returns = close.pct_change().dropna()
                if len(returns) < 10:
                    results.append({"symbol": sym, "error": "收益率数据不足"})
                    continue

                total_return = float(close.iloc[-1] / close.iloc[0] - 1)
                annual_vol = float(returns.std() * np.sqrt(252))
                annual_return = float(returns.mean() * 252)
                sharpe = annual_return / annual_vol if annual_vol > 1e-12 else 0.0

                downside = returns[returns < 0]
                downside_dev = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(252)) if len(downside) > 0 else 0.0
                sortino = annual_return / downside_dev if downside_dev > 1e-12 else 0.0

                cummax = close.cummax()
                drawdown = (close - cummax) / cummax
                max_dd = float(drawdown.min())

                current_price = float(close.iloc[-1])
                ma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else current_price
                ma60 = float(close.rolling(60).mean().iloc[-1]) if len(close) >= 60 else current_price

                avg_vol_20d = float(volume.iloc[-20:].mean()) if len(volume) >= 20 else 0.0

                from core.regime_detector import RegimeDetector
                detector = RegimeDetector()
                regime_result = detector.detect(df)

                results.append({
                    "symbol": sym,
                    "current_price": round(current_price, 2),
                    "total_return": round(total_return, 4),
                    "annual_return": round(annual_return, 4),
                    "annual_volatility": round(annual_vol, 4),
                    "sharpe_ratio": round(sharpe, 2),
                    "sortino_ratio": round(sortino, 2),
                    "max_drawdown": round(max_dd, 4),
                    "ma20": round(ma20, 2),
                    "ma60": round(ma60, 2),
                    "price_vs_ma20": round((current_price / ma20 - 1) * 100, 2),
                    "price_vs_ma60": round((current_price / ma60 - 1) * 100, 2),
                    "avg_volume_20d": float(round(avg_vol_20d, 0)),
                    "regime": regime_result.current_regime.value,
                    "regime_confidence": regime_result.confidence,
                })
            except Exception as e:
                logger.debug("Batch analysis failed for %s: %s", sym, e)
                results.append({"symbol": sym, "error": safe_error(e)})

        valid = [r for r in results if "error" not in r]
        summary = {}
        if valid:
            summary = {
                "n_analyzed": len(valid),
                "avg_return": round(float(np.mean([r["total_return"] for r in valid])), 4),
                "avg_sharpe": round(float(np.mean([r["sharpe_ratio"] for r in valid])), 2),
                "avg_max_drawdown": round(float(np.mean([r["max_drawdown"] for r in valid])), 4),
                "best_return": max(valid, key=lambda x: x["total_return"])["symbol"],
                "worst_return": min(valid, key=lambda x: x["total_return"])["symbol"],
                "best_sharpe": max(valid, key=lambda x: x["sharpe_ratio"])["symbol"],
            }

        return _json_response(True, data={
            "period": period,
            "results": results,
            "summary": summary,
        })
    except Exception as e:
        logger.error("Batch analysis error: %s", e)
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


@router.get("/strategy/param-specs")
async def get_strategy_param_specs():
    try:
        from core.param_optimizer import get_param_specs
        specs = get_param_specs()
        return _json_response(True, data={"strategies": specs})
    except Exception as e:
        logger.error("Param specs error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/strategy/optimize-params")
async def optimize_strategy_params(
    request: Request,
    strategy_name: str = Query(..., max_length=50),
    symbol: str = Query(..., max_length=20),
    metric: str = Query("sharpe_ratio", max_length=20),
    period: str = Query("1y", max_length=5),
    max_combos: int = Query(200, ge=10, le=500),
):
    try:
        if not validate_symbol(symbol):
            return _json_response(False, error="Invalid symbol")
        if metric not in ("sharpe_ratio", "total_return", "annual_return", "max_drawdown", "win_rate"):
            return _json_response(False, error="Invalid metric")

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="Insufficient data (need at least 60 bars)")

        from core.param_optimizer import run_param_optimization
        result = run_param_optimization(
            strategy_name=strategy_name,
            df=df,
            metric=metric,
            max_combos=max_combos,
            timeout_seconds=30.0,
        )
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Param optimization error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/strategy/bayesian-optimize")
async def bayesian_optimize_strategy(
    request: Request,
    strategy_name: str = Query(..., max_length=50),
    symbol: str = Query(..., max_length=20),
    metric: str = Query("sharpe_ratio", max_length=20),
    period: str = Query("1y", max_length=5),
    n_trials: int = Query(30, ge=10, le=100),
):
    """使用差分进化算法进行智能参数优化"""
    try:
        if not validate_symbol(symbol):
            return _json_response(False, error="Invalid symbol")
        if metric not in ("sharpe_ratio", "total_return", "annual_return", "max_drawdown", "win_rate"):
            return _json_response(False, error="Invalid metric")

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="Insufficient data (need at least 60 bars)")

        from core.param_optimizer import run_bayesian_optimization
        result = await asyncio.to_thread(
            run_bayesian_optimization,
            strategy_name=strategy_name,
            df=df,
            metric=metric,
            n_trials=n_trials,
            timeout_seconds=45.0,
        )
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Bayesian optimization error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/single-stock/stress-test")
async def run_single_stock_stress_test(
    request: Request,
    symbol: str = Query(..., max_length=20),
    period: str = Query("1y", max_length=5),
    scenarios: str = Query("", max_length=200),
):
    try:
        if not validate_symbol(symbol):
            return _json_response(False, error="Invalid symbol")

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error="Insufficient data")

        from core.param_optimizer import run_stress_test
        scenario_list = [s.strip() for s in scenarios.split(",") if s.strip()] if scenarios else None
        result = run_stress_test(df, scenarios=scenario_list)
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Stress test error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/volatility/garch/{symbol}")
async def garch_volatility_forecast(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="Insufficient data (need 60+ bars)")

        from core.volatility import fit_garch
        returns = df["close"].astype(float).pct_change().dropna().values
        returns = np.clip(returns, -0.15, 0.15)
        result = fit_garch(returns)
        result["symbol"] = symbol
        result["period"] = period
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("GARCH forecast error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/regime/hmm/{symbol}")
async def hmm_regime_detection(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
    n_states: int = Query(3, ge=2, le=5),
):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="Insufficient data (need 60+ bars)")

        from core.volatility import detect_regime_hmm
        returns = df["close"].astype(float).pct_change().dropna().values
        result = detect_regime_hmm(returns, n_states=n_states)
        result["symbol"] = symbol
        result["period"] = period
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("HMM regime detection error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/strategy/performance_heatmap")
async def get_strategy_performance_heatmap(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码，最多10个"),
    period: int = Query(120, description="回测天数", ge=30, le=500),
):
    """策略性能热力图：多股票×多策略的Sharpe比率矩阵"""
    try:
        from core.backtest import run_parallel_backtest
        from core.strategies import CompositeStrategy

        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()][:10]
        if not symbol_list:
            return _json_response(False, error="请提供股票代码")

        composite = CompositeStrategy()
        strategy_names = [s.name for s in composite.strategies]

        heatmap_data = []
        strategy_stats = {name: {"sharpe_sum": 0.0, "count": 0} for name in strategy_names}

        for symbol in symbol_list:
            try:
                df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
                if df is None or len(df) < 50:
                    continue
                df = df.tail(period + 60)
                if len(df) < 50:
                    continue

                strategy_specs = [{"name": s.name, "class_name": type(s).__name__} for s in composite.strategies]
                parallel_results = await asyncio.to_thread(
                    run_parallel_backtest, strategy_specs, df, symbol, 1000000
                )

                row = {"symbol": symbol}
                for r in parallel_results:
                    name = r.get("strategy", "unknown")
                    sharpe = r.get("sharpe_ratio", 0.0) if "error" not in r else 0.0
                    row[name] = round(sharpe, 3)
                    if name in strategy_stats:
                        strategy_stats[name]["sharpe_sum"] += sharpe
                        strategy_stats[name]["count"] += 1
                heatmap_data.append(row)
            except Exception as e:
                logger.debug("Heatmap symbol %s failed: %s", symbol, e)
                continue

        strategy_ranking = [
            {"name": name, "avg_sharpe": round(stats["sharpe_sum"] / max(stats["count"], 1), 3)}
            for name, stats in strategy_stats.items()
        ]
        strategy_ranking.sort(key=lambda x: x["avg_sharpe"], reverse=True)

        return _json_response(True, data={
            "heatmap": heatmap_data,
            "strategies": strategy_names,
            "strategy_ranking": strategy_ranking,
            "period": period,
            "timestamp": time.time(),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/strategy/compare")
async def compare_strategies(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    strategies: str = Query(..., description="逗号分隔的策略名称"),
    period: str = Query("6m", max_length=5, description="回测周期"),
    capital: float = Query(100000, ge=10000, le=10000000, description="初始资金"),
):
    """多策略性能对比：同标的、同周期下并排比较多个策略的回测结果"""
    try:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        strategy_names = [s.strip() for s in strategies.split(",") if s.strip()]
        if not symbol_list or not strategy_names:
            return _json_response(False, error="需要至少1个股票和1个策略")
        if len(strategy_names) > 6:
            return _json_response(False, error="最多同时比较6个策略")

        from core.backtest import BacktestEngine
        from core.strategies import get_strategy_registry

        fetcher: SmartDataFetcher = request.app.state.fetcher
        registry = get_strategy_registry()
        results: list[dict] = []
        metrics_keys = [
            "total_return", "annual_return", "sharpe_ratio", "max_drawdown",
            "win_rate", "profit_factor", "total_trades", "sortino_ratio",
            "calmar_ratio", "omega_ratio",
        ]
        comparison_matrix: dict[str, dict[str, float | int]] = {}

        for strat_name in strategy_names:
            cls = registry.get(strat_name)
            if cls is None:
                results.append({"strategy": strat_name, "error": f"未知策略: {strat_name}"})
                continue

            all_summaries = []
            for sym in symbol_list[:5]:
                try:
                    df = await fetcher.get_history(sym, _period_to_history(period), "daily", "qfq")
                    if df is None or len(df) < 30:
                        continue
                    bt = BacktestEngine(initial_capital=capital)
                    r = bt.run(cls(), df, symbol=sym)
                    all_summaries.append(r.summary_dict())
                except Exception as e:
                    logger.debug("Compare backtest failed: %s/%s: %s", strat_name, sym, e)
                    continue

            if not all_summaries:
                results.append({"strategy": strat_name, "error": "无有效回测数据"})
                continue

            avg_metrics: dict[str, float] = {}
            for key in metrics_keys:
                vals = [s.get(key, 0) for s in all_summaries if isinstance(s.get(key), (int, float))]
                avg_metrics[key] = round(sum(vals) / len(vals), 4) if vals else 0.0
            comparison_matrix[strat_name] = avg_metrics

            best = max(all_summaries, key=lambda s: s.get("sharpe_ratio", -999))
            worst = min(all_summaries, key=lambda s: s.get("sharpe_ratio", -999))

            results.append({
                "strategy": strat_name,
                "n_symbols_tested": len(all_summaries),
                "average": avg_metrics,
                "best_symbol": {
                    "strategy_name": best.get("strategy_name", ""),
                    "sharpe_ratio": best.get("sharpe_ratio", 0),
                    "total_return": best.get("total_return", 0),
                    "max_drawdown": best.get("max_drawdown", 0),
                },
                "worst_symbol": {
                    "strategy_name": worst.get("strategy_name", ""),
                    "sharpe_ratio": worst.get("sharpe_ratio", 0),
                    "total_return": worst.get("total_return", 0),
                    "max_drawdown": worst.get("max_drawdown", 0),
                },
            })

        ranking = sorted(
            comparison_matrix.items(),
            key=lambda x: x[1].get("sharpe_ratio", -999),
            reverse=True,
        )

        return _json_response(True, data={
            "strategies": results,
            "ranking": [
                {"strategy": name, "avg_sharpe": metrics.get("sharpe_ratio", 0)}
                for name, metrics in ranking
            ],
            "comparison_matrix": comparison_matrix,
            "period": period,
            "symbols": symbol_list[:5],
            "timestamp": time.time(),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/system/feature-flags")
async def get_feature_flags(request: Request, tags: str = Query(None, description="逗号分隔的标签过滤")):
    """获取所有功能开关状态"""
    try:
        from core.feature_flags import get_feature_flag_manager

        mgr = get_feature_flag_manager()
        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        flags = mgr.list_flags(tags=tag_list)
        result = {
            flag.name: {
                "description": flag.description,
                "enabled": flag.enabled,
                "rollout_percentage": flag.rollout_percentage,
                "tags": flag.tags,
                "metadata": flag.metadata,
            }
            for flag in flags
        }
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/system/feature-flags/{name}")
async def get_feature_flag(request: Request, name: str = Path(..., min_length=1, max_length=100)):
    """获取单个功能开关状态"""
    try:
        from core.feature_flags import get_feature_flag_manager

        mgr = get_feature_flag_manager()
        flag = mgr.get_flag(name)
        if not flag:
            return _json_response(False, error=f"功能开关 '{name}' 不存在")
        return _json_response(True, data={
            "name": flag.name,
            "description": flag.description,
            "enabled": flag.enabled,
            "rollout_percentage": flag.rollout_percentage,
            "tags": flag.tags,
            "metadata": flag.metadata,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


class FeatureFlagUpdateRequest(BaseModel):
    enabled: bool = Field(..., description="功能开关状态")
    rollout_percentage: float | None = Field(None, ge=0.0, le=100.0, description="灰度发布百分比")


@router.put("/system/feature-flags/{name}")
async def update_feature_flag(
    request: Request,
    name: str = Path(..., min_length=1, max_length=100),
    body: FeatureFlagUpdateRequest | None = None,
):
    """更新功能开关状态"""
    try:
        from core.feature_flags import get_feature_flag_manager

        mgr = get_feature_flag_manager()
        if not mgr.get_flag(name):
            return _json_response(False, error=f"功能开关 '{name}' 不存在")

        if body.enabled is not None:
            mgr.set_enabled(name, body.enabled)
        if body.rollout_percentage is not None:
            flag = mgr.get_flag(name)
            if flag:
                flag.rollout_percentage = body.rollout_percentage

        flag = mgr.get_flag(name)
        return _json_response(True, data={
            "name": flag.name,
            "description": flag.description,
            "enabled": flag.enabled,
            "rollout_percentage": flag.rollout_percentage,
            "tags": flag.tags,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/system/feature-flags/{name}/toggle")
async def toggle_feature_flag(request: Request, name: str = Path(..., min_length=1, max_length=100)):
    """切换功能开关状态"""
    try:
        from core.feature_flags import get_feature_flag_manager

        mgr = get_feature_flag_manager()
        new_state = mgr.toggle(name)
        return _json_response(True, data={"name": name, "enabled": new_state})
    except ValueError as e:
        return _json_response(False, error=str(e))
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/system/feature-flags/reset")
async def reset_all_feature_flags(request: Request):
    """重置所有功能开关到默认状态"""
    try:
        from core.feature_flags import get_feature_flag_manager

        mgr = get_feature_flag_manager()
        mgr.reset_all()
        return _json_response(True, data={"message": "所有功能开关已重置"})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


class FeatureFlagRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="功能开关名称")
    description: str = Field(..., description="功能开关描述")
    enabled: bool = Field(True, description="初始状态")
    tags: list[str] = Field([], description="标签列表")


@router.post("/system/feature-flags")
async def register_feature_flag(request: Request, body: FeatureFlagRegisterRequest):
    """注册新的功能开关"""
    try:
        from core.feature_flags import get_feature_flag_manager

        mgr = get_feature_flag_manager()
        mgr.register_flag(
            name=body.name,
            description=body.description,
            enabled=body.enabled,
            tags=body.tags,
        )
        return _json_response(True, data={"name": body.name, "enabled": body.enabled})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


_SSE_MAX_SYMBOLS = 10
_SSE_KEEPALIVE_INTERVAL = 15


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


@router.get("/strategy/dashboard")
async def get_strategy_dashboard(
    request: Request,
    symbol: str = Query(..., description="股票代码"),
    period: int = Query(120, description="回测天数", ge=30, le=500),
):
    """综合策略性能仪表盘：回测结果 + IC监控 + 市场状态权重 + 风险平价"""
    try:
        from core.backtest import run_parallel_backtest
        from core.factor_validity import FactorValidityMonitor
        from core.regime_weight_tracker import RegimeWeightTracker
        from core.risk_parity_portfolio import RiskParityPortfolio
        from core.strategies import CompositeStrategy

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 50:
            return _json_response(False, error="数据不足")

        df = df.tail(period + 60)
        if len(df) < 50:
            return _json_response(False, error="数据不足")

        composite = CompositeStrategy()
        strategy_specs = [
            {"name": s.name, "class_name": type(s).__name__}
            for s in composite.strategies
        ]
        strategy_names = [s["name"] for s in strategy_specs]

        parallel_results = await asyncio.to_thread(
            run_parallel_backtest, strategy_specs, df, symbol, 1000000
        )

        strategy_results = []
        for r in parallel_results:
            if "error" in r:
                strategy_results.append({
                    "name": r["strategy"],
                    "total_return": 0.0, "sharpe_ratio": 0.0, "max_drawdown": 0.0,
                    "win_rate": 0.0, "total_trades": 0,
                })
            else:
                strategy_results.append({
                    "name": r["strategy"],
                    "total_return": r.get("total_return", 0.0),
                    "sharpe_ratio": r.get("sharpe_ratio", 0.0),
                    "max_drawdown": r.get("max_drawdown", 0.0),
                    "win_rate": r.get("win_rate", 0.0),
                    "total_trades": r.get("total_trades", 0),
                })

        strategy_results.sort(key=lambda x: x["total_return"], reverse=True)

        regime_tracker = RegimeWeightTracker(strategy_names=strategy_names)
        regime_snap = regime_tracker.update(df)
        regime_data = {
            "current_regime": regime_snap.regime,
            "confidence": regime_snap.regime_confidence,
            "strategy_weights": regime_snap.strategy_weights,
            "indicators": regime_snap.indicators,
        }

        ic_data = {}
        factor_monitor = FactorValidityMonitor(lookback=60, ic_threshold=0.03)
        for sr in strategy_results[:5]:
            name = sr["name"]
            ic_data[name] = {
                "ic_mean": factor_monitor.get_ic_mean(name),
                "ic_ir": factor_monitor.get_ic_ir(name),
                "is_valid": factor_monitor.is_valid(name),
                "weight_adjustment": factor_monitor.get_weight_adjustment(name),
            }

        risk_data = {}
        try:
            if len(strategy_names) >= 2:
                portfolio = RiskParityPortfolio(symbols=strategy_names[:5])
                rng = np.random.default_rng(42)
                n_assets = min(5, len(strategy_names))
                for _ in range(30):
                    portfolio.update_returns(rng.normal(0.001, 0.02, n_assets))
                state = portfolio.compute_target_weights()
                risk_data = {
                    "weights": state.weights,
                    "risk_contributions": state.risk_contributions,
                    "portfolio_volatility": state.portfolio_volatility,
                    "ic_adjustments": state.ic_adjustments,
                }
        except Exception as e:
            logger.debug("Risk parity computation skipped: %s", e)

        return _json_response(True, data={
            "symbol": symbol,
            "period": period,
            "strategies": strategy_results,
            "best_strategy": strategy_results[0] if strategy_results else None,
            "regime": regime_data,
            "factor_validity": ic_data,
            "risk_parity": risk_data,
            "timestamp": time.time(),
        })
    except Exception as e:
        logger.error("Strategy dashboard error: %s", e)
        return _json_response(False, error=safe_error(e))
