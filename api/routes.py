"""
QuantCore API路由模块
提供REST API和WebSocket实时推送
"""
import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Optional, Set

from fastapi import APIRouter, Path, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from api.utils import sanitize, json_response as _json_response, safe_error
from api.backtest_routes import BacktestAdvancedRequest
import numpy as np
import pandas as pd
import re

from core.data_fetcher import SmartDataFetcher
from core.database import ThreadSafeLRU, get_db
from core.market_detector import MarketDetector
from core.market_hours import MarketHours
from core.indicators import (
    IndicatorAnalysis,
    KLinePatternRecognizer,
    TechnicalIndicators,
    calc_all_indicators,
)
from core.strategies import STRATEGY_REGISTRY, CompositeStrategy

logger = logging.getLogger(__name__)

router = APIRouter()

_start_time = time.time()


@router.get("/readiness")
async def readiness_check(request: Request):
    checks = {}
    try:
        db = get_db()
        db.fetchone("SELECT 1")
        checks["database"] = "ready"
    except Exception as e:
        checks["database"] = f"error: {e}"
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
        checks["data_fetcher"] = f"error: {e}"

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
            "active_connections": len(_manager.connections),
            "max_connections": ConnectionManager.MAX_CONNECTIONS,
        },
    }


CHINA_HOLIDAYS_2026 = {
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
}

# 调休工作日（周六或周日但补班）
CHINA_WORKDAYS_2026 = {
    "2026-01-03": "元旦调休",
    "2026-02-15": "春节调休",
    "2026-02-23": "春节调休",
    "2026-04-12": "清明调休",
    "2026-04-26": "劳动节调休",
    "2026-06-07": "端午调休",
    "2026-09-20": "中秋调休",
    "2026-10-10": "国庆调休",
}


def _is_cn_trading_day(date_obj: date) -> tuple:
    date_str = date_obj.strftime("%Y-%m-%d")
    if date_str in CHINA_WORKDAYS_2026:
        return True, CHINA_WORKDAYS_2026[date_str]
    if date_str in CHINA_HOLIDAYS_2026:
        return False, CHINA_HOLIDAYS_2026[date_str]
    if date_obj.weekday() >= 5:
        return False, "周末"
    return True, "交易日"


@router.get("/calendar/check")
async def check_trading_day(d: str = None):
    if d:
        try:
            date_obj = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            return {"error": "日期格式错误，请使用 YYYY-MM-DD"}
    else:
        date_obj = datetime.now().date()

    is_trading, reason = _is_cn_trading_day(date_obj)
    return {
        "date": date_obj.isoformat(),
        "is_trading_day": is_trading,
        "reason": reason,
        "weekday": date_obj.strftime("%A"),
    }


@router.get("/calendar/next")
async def next_trading_day(d: str = None, count: int = 1):
    try:
        from_date = datetime.strptime(d, "%Y-%m-%d").date() if d else datetime.now().date()
    except ValueError:
        return {"error": "日期格式错误，请使用 YYYY-MM-DD"}

    result = []
    current = from_date + timedelta(days=1)
    while len(result) < count:
        is_trading, _ = _is_cn_trading_day(current)
        if is_trading:
            result.append({"date": current.isoformat(), "weekday": current.strftime("%A")})
        current += timedelta(days=1)

    return {"from": from_date.isoformat(), "count": count, "next_trading_days": result}


@router.get("/calendar/holidays")
async def list_holidays(month: int = None):
    now = datetime.now()
    year = now.year if month else None
    holidays = []
    for date_str, name in sorted(CHINA_HOLIDAYS_2026.items()):
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
    except Exception:
        memory_mb = 0
        cpu_percent = 0

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": round(process_time, 1),
        "memory_mb": memory_mb,
        "cpu_percent": cpu_percent,
        "database": pool_status,
    }

_SYMBOL_RE = re.compile(r"^[0-9a-zA-Z\.]{1,20}$")


def _validate_symbol(symbol: str) -> str:
    if not _SYMBOL_RE.match(symbol):
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
    value: float = Field(..., gt=-1e8, lt=1e8)


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
    shares: Optional[int] = Field(None, gt=0, le=1000000)
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
        self._subscriptions: dict[WebSocket, Set[str]] = {}
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

    def touch(self, ws: WebSocket) -> None:
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
            except Exception:
                pass
            await self.disconnect(ws)
        return len(stale_ws)

    def get_all_subscribed_symbols(self) -> Set[str]:
        all_symbols: Set[str] = set()
        for symbols in self._subscriptions.values():
            all_symbols.update(symbols)
        return all_symbols

    def get_subscriptions(self, ws: WebSocket) -> Set[str]:
        return self._subscriptions.get(ws, set())

    def get_connections_snapshot(self) -> list[WebSocket]:
        return list(self.connections)


_manager = ConnectionManager()

_api_response_cache = ThreadSafeLRU(maxsize=600, ttl=30)

_MAX_PUSH_SYMBOLS = 30


def _is_trading_hours() -> bool:
    try:
        for market in ["A", "HK", "US"]:
            status = MarketHours.get_market_status(market)
            if status.get("is_open"):
                return True
    except Exception as e:
        logger.debug(f"Market hours check failed: {e}")
    return False



def cache_response(ttl_seconds: int):
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            cache_key = f"api:{func.__name__}:{request.url.path}:{request.url.query}"
            cached = _api_response_cache.get(cache_key)
            if cached is not None:
                return cached
            result = await func(request, *args, **kwargs)
            _api_response_cache.set(cache_key, result, ttl=ttl_seconds)
            return result
        return wrapper
    return decorator


@router.get("/market/overview")
@cache_response(5)
async def get_market_overview(request: Request):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        data = await fetcher.get_market_overview()
        return _json_response(True, data=data)
    except Exception as e:
        logger.error(f"Market overview error: {e}")
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


@router.get("/backtest/compare")
async def compare_backtests(request: Request, id1: str = Query(...), id2: str = Query(...)):
    try:
        db = getattr(request.app.state, "db", None)
        if not db or not hasattr(db, "get_backtest_by_id"):
            return _json_response(False, error="数据库不可用")

        r1 = db.get_backtest_by_id(id1)
        r2 = db.get_backtest_by_id(id2)
        if not r1 or not r2:
            return _json_response(False, error="未找到指定回测记录")

        numeric_keys = ["sharpe_ratio", "total_return", "max_drawdown"]
        diff = {}
        for key in numeric_keys:
            v1 = float(r1.get(key, 0) or 0)
            v2 = float(r2.get(key, 0) or 0)
            delta = v1 - v2
            diff[key] = {
                "r1": round(v1, 4),
                "r2": round(v2, 4),
                "delta": round(delta, 4),
                "winner": "r1" if v1 > v2 else ("r2" if v2 > v1 else "tie"),
            }

        return _json_response(
            True,
            data={
                "r1": {"id": id1, "strategy_name": r1.get("strategy_name"), "symbol": r1.get("symbol")},
                "r2": {"id": id2, "strategy_name": r2.get("strategy_name"), "symbol": r2.get("symbol")},
                "diff": diff,
            },
        )
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/backtest/export")
async def export_backtest_results(
    request: Request,
    format: str = Query("csv", description="导出格式：csv 或 json"),
    symbol: Optional[str] = None,
    limit: int = Query(100),
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

        import io
        import csv as csv_module
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
                "Content-Disposition": f"attachment; filename=backtest_export.csv"
            },
        )
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/stock/realtime/{symbol}")
async def get_stock_realtime(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        data = await fetcher.get_realtime(symbol)
        if data:
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
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period, kline_type, adjust)
        if df.empty:
            return _json_response(False, error="无历史数据")
        result = df.to_dict("records")
        return _json_response(True, data=result)
    except Exception as e:
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


@router.get("/stock/indicators/{symbol}")
async def get_stock_indicators(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
    kline_type: str = Query("daily"),
):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period, kline_type)
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")
        kline_data = df.to_dict("records")
        result = calc_all_indicators(kline_data)
        return _json_response(True, data=result)
    except Exception as e:
        logger.error(f"Indicators error: {e}")
        return _json_response(False, error=safe_error(e))


def _period_to_history(period: str) -> str:
    period = (period or "1y").lower()
    if period in {"3m", "6m"}:
        return "1y"
    if period in {"3y", "5y", "all"}:
        return "all"
    return "1y"


@router.get("/stock/analysis/{symbol}")
async def get_deep_analysis(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"), period: str = Query("1y", max_length=5)):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="数据不足，至少需要60个交易日")

        df = df.tail(260).copy().reset_index(drop=True)
        c = df["close"].astype(float)
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        v = df["volume"].astype(float) if "volume" in df.columns else None
        indicators = TechnicalIndicators.compute_all(df, symbol=symbol, period=period)
        ma = indicators.get("ma", {})
        ma20 = ma.get(20, [])
        ma60 = ma.get(60, [])
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

        low_120 = float(l.tail(120).min())
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
            "fibonacci_levels": [{"ratio": r, "price": p} for r, p in zip(fib_ratios, fib)],
            "composite_score": round(composite_score, 2),
            "signal": signal,
            "signal_confidence": round(float(confidence), 2),
            "last_price": round(last_close, 4),
        }
        return _json_response(True, data=result)
    except Exception as e:
        logger.error(f"Deep analysis error for {symbol}: {e}", exc_info=True)
        return _json_response(False, error=safe_error(e))


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
                bench_code = benchmark.replace("sh", "sh.").replace("sz", "sz.")
                if not bench_code.startswith("sh.") and not bench_code.startswith("sz."):
                    bench_code = f"sh.{benchmark.lstrip('shsz')}"
                lg = bs.login()
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
                logger.debug(f"BaoStock cleanup failed: {e}")
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
        beta = float(np.cov(ar.dropna().tail(120), br.dropna().tail(120))[0][1] / np.var(br.dropna().tail(120))) if np.var(br.dropna().tail(120)) > 0 else 1.0
        asset_ret = merged["asset_close"].iloc[-1] / merged["asset_close"].iloc[0] - 1
        bench_ret = merged["benchmark_close"].iloc[-1] / merged["benchmark_close"].iloc[0] - 1
        return _json_response(True, data={
            "rolling_correlation": [{"date": str(d)[:10], "value": round(float(v), 4)} for d, v in zip(merged["date"], rolling_corr)],
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
        h = df["high"].astype(float).values
        l = df["low"].astype(float).values
        v = df["volume"].astype(float).values

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
        logger.error(f"Prediction error for {symbol}: {e}")
        return _json_response(False, error=safe_error(e))


@router.get("/stock/signals/{symbol}")
async def get_stock_signals(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
    strategy: str = Query("all", max_length=30),
):
    """获取股票策略信号历史"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")

        composite = CompositeStrategy()
        signals = []
        step = max(1, len(df) // 50)

        for i in range(30, len(df), step):
            segment = df.iloc[:i + 1]
            date_str = str(df["date"].iloc[i])[:10] if "date" in df.columns else ""
            bar_signals = []
            for s in composite.strategies:
                if strategy != "all" and type(s).__name__ != strategy:
                    continue
                try:
                    sig = s.generate_signal(segment)
                    if sig.signal_type.value != "hold":
                        bar_signals.append({
                            "strategy": type(s).__name__,
                            "signal": sig.signal_type.value,
                            "confidence": round(sig.strength, 2),
                            "reason": sig.reason,
                        })
                except Exception as e:
                    logger.debug(f"Signal generation failed for strategy: {e}")
                    continue
            if bar_signals:
                signals.append({
                    "date": date_str,
                    "price": round(float(df["close"].iloc[i]), 2),
                    "signals": bar_signals,
                })

        return _json_response(True, data={"symbol": symbol, "signals": signals})
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
                logger.debug(f"Return calc failed for {sym}: {e}")
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
        logger.error(f"Portfolio risk analysis error: {e}")
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
                logger.debug(f"Risk attribution failed: {e}")
                continue

        return _json_response(True, data={
            "benchmark": benchmark,
            "benchmark_return": round(float(np.prod(1 + bench_ret) - 1), 4),
            "attribution": attribution,
        })
    except Exception as e:
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
            logger.debug(f"Heatmap data failed: {e}")

        if not heatmap_data:
            try:
                url = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
                import aiohttp, re
                from core.data_fetcher import get_aiohttp_session
                session = await get_aiohttp_session()
                async with session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        text = await resp.text()
                match = re.search(r'=\s*({.*})', text)
                if match:
                    data = json.loads(match.group(1))
                    top_gainers = []
                    top_losers = []
                    for key, val in data.items():
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
                logger.debug(f"Heatmap gainers/losers failed: {e}")
                heatmap_data = {"top_gainers": [], "top_losers": []}

        # 北向资金
        northbound = {}
        try:
            northbound = await fetcher.fetch_north_bound_flow()
        except Exception as e:
            logger.debug(f"Northbound flow fetch failed: {e}")

        report_date = datetime.now().strftime("%Y-%m-%d")
        return _json_response(True, data={
            "report_date": report_date,
            "market_summary": market_summary,
            "sector_performance": heatmap_data,
            "northbound_flow": northbound,
            "generated_at": time.time(),
        })
    except Exception as e:
        logger.error(f"Weekly report error: {e}")
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
        logger.debug(f"Market stocks EastMoney error: {e}")
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
        logger.debug(f"Market stocks fallback: {e}")
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
        logger.debug(f"Market anomaly error: {e}")
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
        logger.debug(f"Market heatmap akshare failed: {e}")

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
                for key, val in data.items():
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
            logger.debug(f"Market heatmap sina fallback failed: {e2}")

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
async def get_dragon_tiger(request: Request, date: Optional[str] = None):
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
            calc_factor_money_flow_index,
            calc_factor_momentum_quality,
            calc_factor_relative_volume,
            calc_factor_volume_price_trend,
        )
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 80:
            return _json_response(False, error="数据不足")
        h = df["high"].astype(float).values
        l = df["low"].astype(float).values
        c = df["close"].astype(float).values
        v = df["volume"].astype(float).values
        factors = {
            "momentum_quality": calc_factor_momentum_quality(c, v),
            "efficiency_ratio": calc_factor_efficiency_ratio(c),
            "relative_volume": calc_factor_relative_volume(v),
            "money_flow_index": calc_factor_money_flow_index(h, l, c, v),
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


@router.post("/backtest/advanced")
async def run_advanced_backtest(
    request: Request,
    body: BacktestAdvancedRequest,
):
    try:
        from core.backtest import BacktestEngine, BacktestResult, run_backtest as run_bt
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
                trades=result.get("trades", []),
                sharpe_ratio=result.get("sharpe_ratio", 0),
            )
            result["monte_carlo"] = engine.monte_carlo_analysis(bt_result, n_simulations=body.n_simulations)
        if body.sensitivity and effective_strategy != "adaptive":
            strategy_cls = STRATEGY_REGISTRY.get(effective_strategy)
            if strategy_cls:
                fetcher: SmartDataFetcher = request.app.state.fetcher
                df = await fetcher.get_history(body.symbol, "all", "daily", "qfq")
                if df is not None and not df.empty:
                    df["date"] = pd.to_datetime(df["date"], errors="coerce")
                    df = df.dropna(subset=["date"])
                    df = df[(df["date"] >= body.start_date) & (df["date"] <= body.end_date)].reset_index(drop=True)
                    result["sensitivity"] = engine.sensitivity_analysis(strategy_cls, df, {})
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
        logger.error(f"Advanced backtest error: {e}", exc_info=True)
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
async def get_backtest_history(request: Request, symbol: Optional[str] = None, limit: int = Query(20)):
    try:
        db = getattr(request.app.state, "db", None)
        if db and hasattr(db, "get_backtest_history"):
            return _json_response(True, data=db.get_backtest_history(symbol=symbol, limit=limit))
        return _json_response(True, data=[])
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/strategy/performance")
async def get_strategy_performance(
    request: Request,
    symbol: str = Query(..., description="股票代码"),
    period: int = Query(120, description="回测天数", ge=30, le=500),
):
    try:
        from core.strategies import CompositeStrategy
        from core.backtest import BacktestEngine, run_parallel_backtest

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

        all_close = {}
        for sym in symbol_list[:10]:
            try:
                df = await fetcher.get_history(sym, _period_to_history(period), "daily", "qfq")
                if df.empty or len(df) < 30:
                    continue
                all_close[sym] = df[["date", "close"]].copy()
            except Exception as e:
                logger.debug(f"Portfolio equity history fetch failed for {sym}: {e}")
                continue

        if not all_close:
            return _json_response(False, error="有效数据不足")

        merged = None
        for sym, sdf in all_close.items():
            sdf = sdf.rename(columns={"close": sym})
            if merged is None:
                merged = sdf
            else:
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
            "weights": {s: round(float(w), 4) for s, w in zip(sym_cols, weights)},
            "equity_curve": equity_curve,
            "cumulative_return": round(cumulative_return, 4),
            "max_drawdown": round(max_drawdown, 4),
            "annual_return": round(annual_return, 4),
            "annual_volatility": round(annual_vol, 4),
            "sharpe_ratio": round(sharpe, 2),
        })
    except Exception as e:
        logger.error(f"Portfolio equity error: {e}")
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

        all_close = {}
        for sym in symbol_list:
            try:
                df = await fetcher.get_history(sym, _period_to_history(period), "daily", "qfq")
                if df is not None and len(df) >= 30:
                    all_close[sym] = df["close"].astype(float).values
            except Exception:
                continue

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
        logger.error(f"Portfolio correlation error: {e}")
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
        from core.walk_forward import (
            WalkForwardConfig, generate_walk_forward_splits,
            calc_overfitting_score, calc_strategy_metrics,
        )
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY

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
                logger.debug(f"Walk-forward split {idx} error: {e}")
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
        logger.error(f"Walk-forward analysis error: {e}")
        return _json_response(False, error=safe_error(e))


@router.get("/market/regime")
async def get_market_regime(
    request: Request,
    symbol: str = Query(..., description="股票代码"),
    period: int = Query(120, ge=60, le=500, description="分析天数"),
):
    """市场状态检测"""
    try:
        from core.regime_detector import RegimeDetector, MarketRegime

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
        logger.error(f"Market regime error: {e}")
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
                logger.debug(f"Sensitivity param {param}={pv} error: {e}")
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
        logger.error(f"Sensitivity analysis error: {e}")
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
            for symbol, result in zip(other_symbols, other_results):
                if isinstance(result, dict):
                    results[symbol] = result

        return _json_response(True, data={"symbols": watchlist, "quotes": results})
    except Exception as e:
        logger.error(f"Watchlist error: {e}")
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


@router.get("/search")
async def search_stocks(request: Request, q: str = Query(..., min_length=1, max_length=100), limit: int = Query(10, ge=1, le=100)):
    try:
        from core.stock_search import search_stocks as do_search
        results = do_search(q, limit=limit)
        return _json_response(True, data=results)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/trading/account")
async def get_trading_account(request: Request):
    try:
        trading = request.app.state.trading
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
        trading = request.app.state.trading
        fetcher: SmartDataFetcher = request.app.state.fetcher
        rt = await fetcher.get_realtime(symbol, market)
        market_price = rt.get("price", 0) if rt else 0
        result = trading.execute_buy(
            symbol=symbol, name=name, market=market, price=price,
            shares=shares, stop_loss=body.stop_loss, take_profit=body.take_profit,
            strategy=body.strategy, market_price=market_price,
        )
        return _json_response(result.get("success", False), data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/trading/sell")
async def trading_sell(
    request: Request,
    body: TradingSellRequest,
):
    try:
        trading = request.app.state.trading
        symbol = body.symbol
        price = body.price
        sell_shares = body.shares
        if sell_shares is None:
            positions = trading.get_positions()
            pos = positions.get(symbol)
            if pos:
                sell_shares = pos.shares
            else:
                sell_shares = 0
        if sell_shares <= 0:
            return _json_response(False, error="无持仓或卖出数量无效")
        fetcher: SmartDataFetcher = request.app.state.fetcher
        market = MarketDetector.detect(symbol)
        rt = await fetcher.get_realtime(symbol, market)
        market_price = rt.get("price", 0) if rt else 0
        result = trading.execute_sell(
            symbol=symbol, price=price, reason=body.reason,
            shares=sell_shares, market_price=market_price,
        )
        return _json_response(result.get("success", False), data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/trading/history")
async def get_trading_history(request: Request, limit: int = Query(100)):
    try:
        trading = request.app.state.trading
        return _json_response(True, data=trading.get_trade_history(limit))
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/system/metrics")
async def get_system_metrics(request: Request):
    try:
        import psutil
        import os
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        req_count = getattr(request.app.state, "_request_count", 0)
        total_rt = getattr(request.app.state, "_total_response_time", 0.0)
        avg_rt = total_rt / max(req_count, 1)
        metrics = {
            "uptime_seconds": time.time() - getattr(request.app.state, "start_time", time.time()),
            "memory_mb": round(mem_info.rss / 1024 / 1024, 1),
            "cpu_percent": process.cpu_percent(interval=0.1),
            "threads": process.num_threads(),
            "api_requests_total": req_count,
            "avg_response_time": round(avg_rt, 1),
            "ws_connections": len(_manager.connections),
            "cache_size": 0,
        }
        return _json_response(True, data=metrics)
    except ImportError:
        req_count = getattr(request.app.state, "_request_count", 0)
        total_rt = getattr(request.app.state, "_total_response_time", 0.0)
        avg_rt = total_rt / max(req_count, 1)
        metrics = {
            "uptime_seconds": time.time() - getattr(request.app.state, "start_time", time.time()),
            "api_requests_total": req_count,
            "avg_response_time": round(avg_rt, 1),
            "ws_connections": len(_manager.connections),
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
        high = df["high"].values
        low = df["low"].values
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
            logger.debug(f"AI summary composite signal failed: {e}")

        try:
            analysis = IndicatorAnalysis.comprehensive_analysis(df)
            if analysis.get("volatility", {}).get("current") == "high":
                summary_points.append("当前波动率较高，注意风险控制")
            if analysis.get("volume_price", {}).get("divergence"):
                summary_points.append("量价出现背离信号")
        except Exception as e:
            logger.debug(f"AI summary indicator analysis failed: {e}")

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
        logger.error(f"AI summary error: {e}")
        return _json_response(False, error=safe_error(e))


@router.websocket("/ws/realtime")
async def websocket_realtime(ws: WebSocket):
    accepted = await _manager.connect(ws)
    if not accepted:
        return
    try:
        while True:
            data = await ws.receive_text()
            _manager.touch(ws)
            try:
                msg = json.loads(data)
                msg_type = msg.get("type", msg.get("action", ""))
                symbols = msg.get("symbols", [])
                if msg_type == "subscribe" and symbols:
                    await _manager.subscribe(ws, symbols)
                elif msg_type == "unsubscribe" and symbols:
                    await _manager.unsubscribe(ws, symbols)
                elif msg_type == "ping":
                    await ws.send_json({"type": "pong", "ts": time.time()})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        await _manager.disconnect(ws)
    except Exception:
        await _manager.disconnect(ws)


_pnl_connections: list[WebSocket] = []
_pnl_lock = asyncio.Lock()


@router.websocket("/ws/pnl")
async def websocket_pnl(ws: WebSocket):
    """实时盈亏推送WebSocket"""
    await ws.accept()
    async with _pnl_lock:
        _pnl_connections.append(ws)
    try:
        while True:
            data = await ws.receive_text()
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
                        except Exception:
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
    except Exception:
        pass
    finally:
        async with _pnl_lock:
            if ws in _pnl_connections:
                _pnl_connections.remove(ws)


_last_indices_hash = ""
_last_quote_hash: dict[str, str] = {}
_last_push_state: dict[str, dict] = {}
_push_seq = 0
_push_seq_lock = threading.Lock()
_push_state_lock = asyncio.Lock()


async def _evict_stale_push_state(stale_symbols: Set[str]) -> None:
    if not stale_symbols:
        return
    all_subscribed = _manager.get_all_subscribed_symbols()
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
    return json.dumps({
        "type": msg_type,
        "ts": time.time(),
        "data": data,
        "seq": seq,
    }, ensure_ascii=False)


async def push_realtime_data(fetcher: SmartDataFetcher):
    global _last_indices_hash, _last_quote_hash, _last_push_state

    while True:
        try:
            if not _manager.connections:
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
                logger.debug(f"Push indices fetch failed: {e}")

            async with _push_state_lock:
                last_quote_hash_snapshot = dict(_last_quote_hash)
                last_indices_hash_snapshot = _last_indices_hash
                subscribed = _manager.get_all_subscribed_symbols()

            quotes_data = {}
            for symbol in list(subscribed)[:_MAX_PUSH_SYMBOLS]:
                try:
                    rt = await fetcher.get_realtime(symbol)
                    if rt:
                        price_str = f"{rt.get('price', 0)}_{rt.get('change_pct', 0)}"
                        if price_str != last_quote_hash_snapshot.get(symbol, ""):
                            quotes_data[symbol] = rt
                except Exception as e:
                    logger.debug(f"Push quote fetch failed for {symbol}: {e}")

            msg_data: dict = {}
            async with _push_state_lock:
                indices_hash = json.dumps(indices_data, sort_keys=True)[:64]
                should_push_indices = indices_hash != _last_indices_hash
                if should_push_indices:
                    _last_indices_hash = indices_hash

                current_subscribed = _manager.get_all_subscribed_symbols()
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
                disconnected = []
                for ws in _manager.get_connections_snapshot():
                    try:
                        await ws.send_text(msg_str)
                    except Exception:
                        disconnected.append(ws)
                for ws in disconnected:
                    await _manager.disconnect(ws)

            await asyncio.sleep(5)
        except Exception as e:
            logger.warning(f"Push realtime error: {e}")
            await asyncio.sleep(10)


async def push_signal_event(symbol: str, strategy: str, signal_type: str, score: float, price: float):
    if not _manager.connections:
        return
    msg_str = _build_message("signal", {
        "symbol": symbol, "strategy": strategy,
        "signal_type": signal_type, "score": score, "price": price,
    })
    disconnected = []
    for ws in _manager.get_connections_snapshot():
        subs = _manager.get_subscriptions(ws)
        if not subs or symbol in subs:
            try:
                await ws.send_text(msg_str)
            except Exception:
                disconnected.append(ws)
    for ws in disconnected:
        await _manager.disconnect(ws)


async def push_alert_event(symbol: str, alert_type: str, value: float, current_price: float):
    if not _manager.connections:
        return
    msg_str = _build_message("alert", {
        "symbol": symbol, "alert_type": alert_type,
        "value": value, "current_price": current_price,
    })
    disconnected = []
    for ws in _manager.get_connections_snapshot():
        subs = _manager.get_subscriptions(ws)
        if not subs or symbol in subs:
            try:
                await ws.send_text(msg_str)
            except Exception:
                disconnected.append(ws)
    for ws in disconnected:
        await _manager.disconnect(ws)


async def push_market_event(event_type: str, data: dict):
    if not _manager.connections:
        return
    msg_str = _build_message("market_event", data)
    disconnected = []
    for ws in _manager.get_connections_snapshot():
        try:
            await ws.send_text(msg_str)
        except Exception:
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
            logger.debug(f"Benchmark fetch failed: {e}")

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
        from core.self_evolver import SelfEvolver, EvolutionConfig
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
        logger.error(f"Alpha evolution error: {e}")
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
        bt_result = await asyncio.to_thread(engine.run, strategy, df)

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
        logger.error(f"Audit error: {e}")
        return _json_response(False, error=safe_error(e))


@router.get("/data/cache-status")
async def get_data_cache_status(request: Request):
    try:
        from core.data_fetcher import (
            _realtime_cache, _history_cache, _indicator_cache,
            _financial_cache, _northbound_cache,
        )
        import psutil, os

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
            _realtime_cache, _history_cache, _indicator_cache,
            _financial_cache, _northbound_cache,
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


@router.get("/market/breadth")
async def get_market_breadth(
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
                logger.debug(f"Breadth calc failed for {code}: {e}")
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
        logger.error(f"Market breadth error: {e}")
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
            mean_variance_optimize,
            risk_parity_optimize,
            ic_weighted_optimize,
        )

        all_returns = {}
        for sym in symbol_list[:30]:
            try:
                df = await fetcher.get_history(sym, _period_to_history(period), "daily", "qfq")
                if df.empty or len(df) < 30:
                    continue
                c = df["close"].astype(float)
                ret = c.pct_change().dropna()
                ret = ret[np.isfinite(ret)]
                all_returns[sym] = ret.values[-252:]
            except Exception:
                continue

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
        logger.error(f"Portfolio optimization error: {e}")
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
        logger.error(f"Data quality check error: {e}")
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


@router.get("/strategies/ranking")
async def strategy_ranking(
    symbol: str = Query("600519", max_length=10),
    period: str = Query("6mo", max_length=5),
):
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY
        db = get_db()
        fetcher = get_fetcher()
        market = MarketDetector.detect(symbol)
        kline = fetcher.get_history(symbol, period=period, market=market)
        if kline is None or kline.empty:
            return _json_response(False, error="No kline data available")

        seen_classes = {}
        for name, cls in STRATEGY_REGISTRY.items():
            base_name = cls.__name__
            if base_name not in seen_classes:
                seen_classes[base_name] = cls

        results = []
        for base_name, cls in seen_classes.items():
            try:
                strategy = cls()
                engine = BacktestEngine()
                result = engine.run(kline, strategy, commission_rate=0.001)
                if result:
                    results.append({
                        "strategy": base_name,
                        "total_return": round(result.get("total_return", 0), 4),
                        "sharpe_ratio": round(result.get("sharpe_ratio", 0), 4),
                        "max_drawdown": round(result.get("max_drawdown", 0), 4),
                        "win_rate": round(result.get("win_rate", 0), 4),
                        "trade_count": result.get("trade_count", 0),
                    })
            except Exception:
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
        logger.error(f"Cache clear error: {e}")
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
        from core.strategy_fusion import StrategyFusion, FusionConfig
        from core.alpha_engine import AlphaEngine
        from core.market_detector import MarketDetector
        fetcher = get_fetcher()
        market = MarketDetector.detect(symbol)
        kline = fetcher.get_history(symbol, period=period, market=market)
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
        from core.execution_engine import ExecutionEngine, CostModel
        from core.market_detector import MarketDetector
        if side not in ("buy", "sell"):
            return _json_response(False, error="side must be 'buy' or 'sell'")
        if method not in ("market", "twap", "vwap"):
            return _json_response(False, error="method must be 'market', 'twap', or 'vwap'")

        fetcher = get_fetcher()
        market = MarketDetector.detect(symbol)
        rt = fetcher.get_realtime(symbol)
        if not rt or rt.get("price", 0) <= 0:
            return _json_response(False, error="No realtime price available")

        current_price = float(rt["price"])
        engine = ExecutionEngine()

        if method == "market":
            result = engine.execute_market_order(side, quantity, current_price)
        elif method == "twap":
            kline = fetcher.get_history(symbol, period="1mo", market=market)
            if kline is None or kline.empty:
                return _json_response(False, error="No history data for TWAP")
            result = engine.execute_twap_order(side, quantity, kline, n_bars=n_bars)
        else:
            kline = fetcher.get_history(symbol, period="1mo", market=market)
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
        from core.alpha_screener import AlphaScreener
        from core.alpha_engine import AlphaEngine
        from core.market_detector import MarketDetector
        fetcher = get_fetcher()
        market = MarketDetector.detect(symbol)
        kline = fetcher.get_history(symbol, period=period, market=market)
        if kline is None or kline.empty:
            return _json_response(False, error="No kline data available")

        alpha_engine = AlphaEngine()
        alpha_results = alpha_engine.compute_all(kline)

        screener = AlphaScreener()
        report = screener.screen(
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


@router.get("/alerts")
async def list_alerts(request: Request):
    db = get_db()
    alerts = db.get_config("price_alerts", [])
    if not isinstance(alerts, list):
        alerts = []
    return _json_response(True, data={"alerts": alerts, "count": len(alerts)})


@router.post("/alerts")
async def create_alert(
    request: Request,
    symbol: str = Query(..., max_length=10),
    threshold: float = Query(..., gt=0),
    direction: str = Query("above", max_length=10),
):
    if direction not in ("above", "below"):
        return _json_response(False, error="direction must be 'above' or 'below'")
    db = get_db()
    alerts = db.get_config("price_alerts", [])
    if not isinstance(alerts, list):
        alerts = []
    alert = {
        "id": str(uuid.uuid4())[:8],
        "symbol": symbol,
        "threshold": threshold,
        "direction": direction,
        "active": True,
        "created_at": datetime.now().isoformat(),
    }
    alerts.append(alert)
    db.set_config("price_alerts", alerts)
    return _json_response(True, data={"alert": alert, "message": "Alert created"})


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str = Path(..., max_length=10)):
    db = get_db()
    alerts = db.get_config("price_alerts", [])
    if not isinstance(alerts, list):
        return _json_response(False, error="No alerts found")
    original_count = len(alerts)
    alerts = [a for a in alerts if a.get("id") != alert_id]
    if len(alerts) == original_count:
        return _json_response(False, error=f"Alert {alert_id} not found")
    db.set_config("price_alerts", alerts)
    return _json_response(True, data={"deleted": alert_id})
