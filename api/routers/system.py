import logging
import sqlite3
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Path, Query, Request

from api.connection_manager import (
    _ALLOWED_CONFIG_KEYS,
    _kline_cache,
    _manager,
    _rt_cache,
    _start_time,
    _strategy_list_cache,
    cache_response,
)
from api.dependencies import FetcherDep
from api.routers.models import ConfigSetRequest, FeatureFlagRegisterRequest, FeatureFlagUpdateRequest
from api.utils import json_response as _json_response
from api.utils import safe_error, validate_symbol
from core.async_utils import backtest_result_cache
from core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

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

CACHE_CLEAR_MAP = {
    "realtime": "_realtime_cache",
    "history": "_history_cache",
    "indicator": "_indicator_cache",
    "financial": "_financial_cache",
    "northbound": "_northbound_cache",
}


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

    try:
        from core.cache import _tick_cache
        checks["tick_cache"] = "ready" if _tick_cache is not None else "not_initialized"
    except Exception as e:
        checks["tick_cache"] = "error"
        logger.warning("Readiness tick cache check failed: %s", e)

    try:
        checks["request_coalescer"] = "ready"
    except Exception as e:
        checks["request_coalescer"] = "error"
        logger.warning("Readiness coalescer check failed: %s", e)

    all_ready = all(v == "ready" or v == "not_initialized" for v in checks.values())
    status = "ready" if all_ready else "degraded"
    return {"status": status, "checks": checks, "timestamp": datetime.now().isoformat()}


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
            "max_connections": _manager.MAX_CONNECTIONS,
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
async def system_status(request: Request, fetcher: FetcherDep):
    db = get_db()
    pool_status = db.get_pool_status()
    process_time = time.monotonic() - _start_time

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

    cache_stats = {}
    try:
        from core.data_fetcher import _history_cache, _indicator_cache, _realtime_cache
        cache_stats = {
            "realtime": _realtime_cache.stats(),
            "history": _history_cache.stats(),
            "indicator": _indicator_cache.stats(),
        }
    except Exception as e:
        logger.debug("Cache stats collection failed: %s", e)

    circuit_breaker_status = {}
    try:
        for name, breaker in fetcher._circuit_breakers.items():
            circuit_breaker_status[name] = {
                "state": breaker.state,
                "failure_count": breaker.failure_count,
                "failure_threshold": breaker.failure_threshold,
                "timeout_seconds": breaker.timeout,
                "last_failure_ago": round(time.monotonic() - breaker.last_failure_time, 1) if breaker.last_failure_time > 0 else None,
            }
    except Exception as e:
        logger.debug("Circuit breaker stats collection failed: %s", e)

    etag_cache_stats = {}
    try:
        from api.middleware import ETagCacheMiddleware
        inst = ETagCacheMiddleware._instance
        if inst is not None:
            etag_cache_stats = inst.status()
    except Exception as e:
        logger.debug("ETag cache stats collection failed: %s", e)

    per_ip_rate_limit_stats = {}
    try:
        from api.middleware import PerIPRateLimitMiddleware
        if PerIPRateLimitMiddleware._instance is not None:
            per_ip_rate_limit_stats = PerIPRateLimitMiddleware._instance.status()
    except Exception as e:
        logger.debug("Per-IP rate limit stats collection failed: %s", e)

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": round(process_time, 1),
        "memory_mb": memory_mb,
        "cpu_percent": cpu_percent,
        "database": pool_status,
        "cache": cache_stats,
        "etag_cache": etag_cache_stats,
        "per_ip_rate_limit": per_ip_rate_limit_stats,
        "circuit_breakers": circuit_breaker_status,
    }


@router.post("/circuit-breaker/{source}/reset")
async def reset_circuit_breaker(source: str, fetcher: FetcherDep):
    try:
        breaker = fetcher._circuit_breakers.get(source)
        if breaker is None:
            return _json_response(False, error=f"Unknown source: {source}")
        breaker.state = "CLOSED"
        breaker.failure_count = 0
        breaker.half_open_calls = 0
        logger.info("Circuit breaker reset for source %s", source)
        return _json_response(True, data={"source": source, "state": breaker.state})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/data/quality/{symbol}")
async def get_data_quality(symbol: str, fetcher: FetcherDep):
    try:
        if not validate_symbol(symbol):
            return _json_response(False, error="股票代码格式无效")
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


@router.get("/metrics")
async def get_collected_metrics(request: Request):
    try:
        from core.metrics import get_metrics
        m = get_metrics()
        return _json_response(True, data=m.get_summary())
    except Exception as e:
        logger.error("Metrics endpoint error: %s", e)
        return _json_response(False, error=safe_error(e))


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
            "uptime_seconds": round(time.monotonic() - getattr(request.app.state, "start_time", time.monotonic())),
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
                "backtest_result": backtest_result_cache.stats(),
            },
        }
        return _json_response(True, data=metrics)
    except ImportError:
        req_count = getattr(request.app.state, "_request_count", 0)
        total_rt = getattr(request.app.state, "_total_response_time", 0.0)
        avg_rt = total_rt / max(req_count, 1)
        metrics = {
            "uptime_seconds": time.monotonic() - getattr(request.app.state, "start_time", time.monotonic()),
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


@router.get("/system/feature-flags")
async def get_feature_flags(request: Request, tags: str = Query(None, description="逗号分隔的标签过滤")):
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


@router.put("/system/feature-flags/{name}")
async def update_feature_flag(
    request: Request,
    name: str = Path(..., min_length=1, max_length=100),
    body: FeatureFlagUpdateRequest | None = None,
):
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
    try:
        from core.feature_flags import get_feature_flag_manager

        mgr = get_feature_flag_manager()
        mgr.reset_all()
        return _json_response(True, data={"message": "所有功能开关已重置"})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/system/feature-flags")
async def register_feature_flag(request: Request, body: FeatureFlagRegisterRequest):
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


@router.get("/system/traces")
async def query_traces(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    path_prefix: str = Query(default=""),
    min_duration_ms: float = Query(default=0, ge=0),
    status_code: int | None = Query(default=None),
    error_only: bool = Query(default=False),
):
    try:
        from api.middleware import span_buffer
        traces = span_buffer.query(
            limit=limit,
            path_prefix=path_prefix,
            min_duration_ms=min_duration_ms,
            status_code=status_code,
            error_only=error_only,
        )
        return _json_response(True, data={"traces": traces, "count": len(traces)})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/system/traces/summary")
async def traces_summary(request: Request):
    try:
        from api.middleware import span_buffer
        return _json_response(True, data=span_buffer.summary())
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/system/drain-status")
async def drain_status(request: Request):
    try:
        from api.middleware import inflight_count, is_draining
        return _json_response(True, data={
            "draining": is_draining(),
            "inflight_requests": inflight_count(),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/system/throttle-status")
async def throttle_status(request: Request):
    try:
        from api.middleware import AdaptiveThrottleMiddleware
        for mw in request.app.user_middleware:
            if isinstance(mw.cls, type) and issubclass(mw.cls, AdaptiveThrottleMiddleware):
                return _json_response(True, data=mw.kwargs)
        from main import app
        for mw in app.user_middleware:
            if isinstance(mw.cls, type) and issubclass(mw.cls, AdaptiveThrottleMiddleware):
                return _json_response(True, data=mw.kwargs)
        return _json_response(True, data={"base_rps": 100, "current_rps": 100})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/system/body-limit-status")
async def body_limit_status(request: Request):
    try:
        from api.middleware import RequestBodyLimitMiddleware
        for mw in request.app.user_middleware:
            if isinstance(mw.cls, type) and issubclass(mw.cls, RequestBodyLimitMiddleware):
                return _json_response(True, data={"max_bytes": mw.kwargs.get("max_bytes", 10_485_760)})
        return _json_response(True, data={"max_bytes": 10_485_760})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/system/error-codes")
async def error_codes_reference():
    try:
        from api.errors import ErrorCode
        codes = {}
        for ec in ErrorCode:
            codes[ec.code] = {
                "name": ec.name,
                "category": ec.category.value,
                "http_status": ec.http_status,
                "retryable": ec.retryable,
            }
        return _json_response(True, data={"error_codes": codes, "total": len(codes)})
    except Exception as e:
        return _json_response(False, error=safe_error(e))
