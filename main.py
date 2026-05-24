"""
QuantCore - 量化交易系统
简洁高效，一键启动
"""
import asyncio
import contextlib
import itertools
import logging
import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

try:
    import uvloop  # noqa: F401
    _has_uvloop = True
except ImportError:
    _has_uvloop = False

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.auth import APIAuthMiddleware
from api.backtest_routes import backtest_router
from api.duckdb_routes import duckdb_router
from api.feature_routes import feature_router
from api.middleware import RequestBodyLimitMiddleware, RequestDedupMiddleware, RequestValidationMiddleware, StructuredTraceMiddleware, GracefulShutdownMiddleware, AdaptiveThrottleMiddleware, correlation_id, span_buffer, trace_id_var, set_draining, is_draining, inflight_count, get_drain_event, bump_lifespan_gen
from api.perf_routes import perf_router
from api.routes import _manager, push_portfolio_metrics, push_realtime_data, router
from core.async_utils import FastJSONResponse
from core.config import get_config
from core.logger import setup_logger
from core.memory_guard import get_memory_usage, is_memory_critical, is_memory_pressure

try:
    if sys.platform == "darwin":
        multiprocessing.set_start_method("spawn")
    else:
        multiprocessing.set_start_method("fork")
except RuntimeError:
    pass

setup_logger(logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
try:
    from core.config import load_config
    cfg = load_config()
    PORT = int(cfg.get("server", {}).get("port", 8080))
    if not (1024 <= PORT <= 65535):
        PORT = 8080
except Exception as e:
    logger.debug(f"Config load error, using default port: {e}")
    PORT = 8080
_preload_done = threading.Event()
_PID_FILE = BASE_DIR / "data" / ".quantcore.pid"


def _kill_existing_process():
    """终结占用同一端口的旧进程，确保每次启动干净"""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", PORT))
        sock.close()
        if result != 0:
            try:
                _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
                _PID_FILE.write_text(str(os.getpid()))
            except Exception as e:
                logger.debug(f"PID file write error in kill check: {e}")
            return
    except Exception as e:
        logger.debug(f"Port check error: {e}")
        try:
            _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
            _PID_FILE.write_text(str(os.getpid()))
        except Exception as e:
            logger.debug(f"PID file write error: {e}")
        return

    try:
        if _PID_FILE.exists():
            old_pid = int(_PID_FILE.read_text().strip())
            if old_pid != os.getpid():
                try:
                    os.kill(old_pid, 0)
                except ProcessLookupError:
                    _PID_FILE.unlink(missing_ok=True)
                    logger.debug(f"Stale PID file (process {old_pid} gone), removing")
                else:
                    try:
                        cmdline_path = Path(f"/proc/{old_pid}/cmdline")
                        if cmdline_path.exists():
                            cmdline = cmdline_path.read_text()
                            if "quantitative-trading" not in cmdline and "uvicorn" not in cmdline:
                                logger.warning(f"PID {old_pid} is not our process, not killing")
                                _PID_FILE.unlink(missing_ok=True)
                                raise RuntimeError("PID mismatch")
                        try:
                            os.kill(old_pid, signal.SIGTERM)
                            logger.info(f"已发送 SIGTERM 到旧进程 PID={old_pid}")
                            time.sleep(1)
                            try:
                                os.kill(old_pid, 0)
                                os.kill(old_pid, signal.SIGKILL)
                                logger.info(f"旧进程未退出，已发送 SIGKILL PID={old_pid}")
                            except ProcessLookupError:
                                pass
                        except ProcessLookupError:
                            pass
                        except PermissionError:
                            pass
                    except RuntimeError:
                        pass
    except Exception as e:
        logger.debug(f"PID file cleanup error: {e}")

    try:
        if sys.platform == "darwin":
            proc = subprocess.run(
                ["lsof", "-ti", f":{PORT}"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.stdout.strip():
                for pid_str in proc.stdout.strip().split("\n"):
                    pid = int(pid_str.strip())
                    if pid != os.getpid():
                        try:
                            os.kill(pid, signal.SIGTERM)
                            logger.info(f"已终止占用端口 {PORT} 的进程 PID={pid}")
                        except ProcessLookupError:
                            pass
                        except PermissionError:
                            pass
                time.sleep(0.5)
        elif sys.platform.startswith("linux"):
            result = subprocess.run(
                ["fuser", f"{PORT}/tcp"],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip():
                for pid_str in result.stdout.strip().split():
                    pid = int(pid_str.strip())
                    if pid != os.getpid():
                        with contextlib.suppress(ProcessLookupError, PermissionError):
                            os.kill(pid, signal.SIGTERM)
                time.sleep(0.5)
    except Exception as e:
        logger.debug(f"Port cleanup error: {e}")

    try:
        _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PID_FILE.write_text(str(os.getpid()))
    except Exception as e:
        logger.debug(f"PID file write error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("QuantCore 启动中...")

    from core.backtest import BacktestEngine
    from core.data_fetcher import get_fetcher
    from core.database import get_cache_manager, get_db
    from core.simulated_trading import SimulatedTrading
    from core.strategies import CompositeStrategy

    app.state.db = get_db()
    app.state.fetcher = get_fetcher()
    app.state.composite_strategy = CompositeStrategy()
    app.state.backtest_engine = BacktestEngine()
    app.state.trading = SimulatedTrading()
    app.state.start_time = time.monotonic()

    from api.websocket_manager import OptimizedWSManager
    app.state.ws_manager = OptimizedWSManager()

    try:
        from api.auth import ensure_default_user
        ensure_default_user()
        logger.info("默认用户初始化完成")
    except Exception as e:
        logger.debug(f"Default user init skipped: {e}")

    try:
        db = get_db()
        saved = db.get_config("portfolio_snapshot")
        if isinstance(saved, dict) and saved.get("version"):
            app.state.trading.import_portfolio(saved)
            logger.info("已从快照恢复模拟交易组合")
    except Exception as e:
        logger.debug(f"Portfolio snapshot restore failed: {e}")
    app.state._request_count = 0
    app.state._total_response_time = 0.0
    app.state._latency_buckets = {
        "<10ms": 0, "10-50ms": 0, "50-100ms": 0, "100-500ms": 0,
        "500ms-1s": 0, "1s-5s": 0, ">5s": 0,
    }
    app.state._error_count = 0
    app.state._bg_tasks = []

    try:
        from core.data_fetcher import get_aiohttp_session
        await get_aiohttp_session()
        logger.info("aiohttp session 预创建完成")
    except Exception as e:
        logger.debug(f"aiohttp session pre-create failed: {e}")

    try:
        from core.stock_search import _STOCK_INDEX
        logger.info(f"股票搜索索引: {len(_STOCK_INDEX)} 条")
    except Exception as e:
        logger.debug(f"Stock search index load failed: {e}")

    try:
        from core.stock_search import build_search_index_async
        count = await build_search_index_async()
        logger.info(f"搜索倒排索引构建完成: {count} 只股票")
    except Exception as e:
        logger.warning(f"搜索索引构建失败: {e}")

    try:
        task = asyncio.create_task(_preload_data(app.state.fetcher))
        app.state._bg_tasks.append(task)
    except Exception as e:
        logger.warning(f"Preload task start failed: {e}")

    try:
        task = asyncio.create_task(push_realtime_data(app.state.fetcher))
        app.state._bg_tasks.append(task)

        task = asyncio.create_task(push_portfolio_metrics(app.state.fetcher))
        app.state._bg_tasks.append(task)

        async def _stale_ws_sweeper():
            while True:
                await asyncio.sleep(60)
                try:
                    swept = await _manager.sweep_stale_connections()
                    if swept:
                        logger.info(f"Swept {swept} stale WebSocket connections")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(f"Stale WS sweep error: {e}")
                try:
                    from api.routes import (
                        sweep_stale_pnl_connections,
                        sweep_stale_regime_connections,
                        sweep_stale_signal_connections,
                    )
                    pnl_swept = await sweep_stale_pnl_connections()
                    sig_swept = await sweep_stale_signal_connections()
                    reg_swept = await sweep_stale_regime_connections()
                    if pnl_swept or sig_swept or reg_swept:
                        logger.info(f"Swept {pnl_swept} stale PnL, {sig_swept} stale signal, {reg_swept} stale regime WS connections")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(f"Stale WS sweep error: {e}")

        task2 = asyncio.create_task(_stale_ws_sweeper())
        app.state._bg_tasks.append(task2)
    except Exception as e:
        logger.warning(f"WS push task start failed: {e}")

    try:
        from api.routes import push_regime_updates
        task3 = asyncio.create_task(push_regime_updates(app.state.fetcher))
        app.state._bg_tasks.append(task3)
    except Exception as e:
        logger.warning(f"Regime push task start failed: {e}")

    try:
        task = asyncio.create_task(_scheduler_loop(app))
        app.state._bg_tasks.append(task)
    except Exception as e:
        logger.warning(f"Scheduler task start failed: {e}")

    try:
        from core.data_fetcher import _cleanup_inflight_requests
        task = asyncio.create_task(_cleanup_inflight_requests())
        app.state._bg_tasks.append(task)
    except Exception as e:
        logger.warning(f"Inflight cleanup task start failed: {e}")

    try:
        from core.market_data import start_background_refresh
        start_background_refresh()
    except Exception as e:
        logger.debug(f"Market data background refresh start failed: {e}")

    try:
        from core.reactive_bus import DataChannel, get_data_bus
        bus = get_data_bus()
        fetcher = app.state.fetcher
        bus.register(DataChannel.MARKET_OVERVIEW, fetcher.get_market_overview, 10.0)
        bus.register(DataChannel.MARKET_BREADTH, fetcher.get_market_breadth, 5.0)
        bus.register(DataChannel.SECTOR_HEATMAP, fetcher.get_sector_heatmap, 60.0)
        bus.register(DataChannel.HOT_SYMBOLS, fetcher.refresh_hot_symbols_cache, 60.0)
        await bus.start()
        app.state.data_bus = bus
        logger.info("ReactiveDataBus started with %d channels", len(bus._fetchers))
    except Exception as e:
        logger.warning(f"ReactiveDataBus start failed: {e}")

    os.makedirs(BASE_DIR / "data", exist_ok=True)
    os.makedirs(BASE_DIR / "static", exist_ok=True)

    set_draining(False)
    bump_lifespan_gen()
    app.state.draining = False
    logger.info(f"QuantCore 启动完成 -> http://localhost:{PORT}")
    yield

    logger.info("QuantCore 正在关闭...")

    set_draining(True)
    app.state.draining = True
    logger.info("Drain mode activated — rejecting new requests, waiting for %d in-flight", inflight_count())

    try:
        drain_evt = get_drain_event()
        if inflight_count() > 0:
            try:
                await asyncio.wait_for(drain_evt.wait(), timeout=30.0)
                logger.info("All in-flight requests completed")
            except asyncio.TimeoutError:
                logger.warning("Drain timeout — %d requests still in-flight", inflight_count())
        else:
            logger.info("No in-flight requests — proceeding with shutdown")
    except Exception as e:
        logger.warning("Drain phase error: %s", e)

    try:
        for task in app.state._bg_tasks:
            if not task.done():
                task.cancel()
        if app.state._bg_tasks:
            await asyncio.gather(*app.state._bg_tasks, return_exceptions=True)
        logger.info("后台异步任务已取消")
    except Exception as e:
        logger.error("Failed to cancel background tasks: %s", e)

    try:
        bus = getattr(app.state, "data_bus", None)
        if bus is not None:
            await bus.stop()
            logger.info("ReactiveDataBus stopped")
    except Exception as e:
        logger.warning(f"ReactiveDataBus stop failed: {e}")

    try:
        from core.data_fetcher import close_aiohttp_session
        await close_aiohttp_session()
        logger.info("aiohttp session 已关闭")
    except Exception as e:
        logger.warning(f"aiohttp session close failed: {e}")

    try:
        trading: SimulatedTrading = app.state.trading
        db = get_db()
        db.set_config("portfolio_snapshot", trading.export_portfolio())
        logger.info("Portfolio snapshot saved")
    except Exception as e:
        logger.error("Failed to save portfolio snapshot: %s", e)

    try:
        from core.market_data import stop_background_refresh
        stop_background_refresh()
    except Exception as e:
        logger.debug(f"Market data background refresh stop failed: {e}")

    try:
        cm = get_cache_manager()
        cm.flush()
    except Exception as e:
        logger.warning(f"Cache flush on shutdown failed: {e}")

    try:
        db = get_db()
        db._flush_buffer()
        db.close()
        logger.info("数据库连接已关闭")
    except Exception as e:
        logger.error("Failed to close database: %s", e)

    logger.info("QuantCore 已关闭")


async def _preload_data(fetcher):
    await asyncio.sleep(2)
    try:
        await fetcher.preload_all()
        logger.info("预加载数据完成")
    except Exception as e:
        logger.debug(f"Preload data failed: {e}")
    finally:
        _preload_done.set()


async def _scheduler_loop(app):
    await asyncio.sleep(5)
    from api.routes import _is_trading_hours, _manager
    from core.database import get_db
    from core.market_detector import MarketDetector

    ws_rt_interval = 5
    hot_refresh_interval = 60
    temperature_interval = 300
    fundamental_interval = 3600
    alert_check_interval = 30
    cleanup_hour = 2

    last_ws_rt = 0
    last_hot = 0
    last_temp = 0
    last_fundamental = 0
    last_alert_check = 0
    last_cleanup_date = ""

    while True:
        try:
            now = time.time()
            fetcher = app.state.fetcher

            # 定期检查内存状态，压力时自动回收
            try:
                from core.memory_guard import check_and_reclaim_if_needed
                check_and_reclaim_if_needed()
            except (ImportError, RuntimeError) as e:
                logger.debug(f"Memory guard check skipped: {e}")

            if now - last_ws_rt >= ws_rt_interval:
                try:
                    if _is_trading_hours() and _manager.connections:
                        subscribed = _manager.get_all_subscribed_symbols()
                        for symbol in list(subscribed)[:30]:
                            with contextlib.suppress(TimeoutError, Exception):
                                await asyncio.wait_for(fetcher.get_realtime(symbol), timeout=3)
                    last_ws_rt = now
                except Exception as e:
                    logger.warning("WS realtime refresh error: %s", e, exc_info=True)

            if now - last_hot >= hot_refresh_interval:
                try:
                    await fetcher.refresh_hot_symbols_cache()
                    last_hot = now
                except Exception as e:
                    logger.warning("Hot symbols refresh error: %s", e, exc_info=True)

            if now - last_temp >= temperature_interval:
                try:
                    await fetcher.get_market_temperature()
                    last_temp = now
                except Exception as e:
                    logger.warning("Temperature refresh error: %s", e, exc_info=True)

            if now - last_fundamental >= fundamental_interval:
                try:
                    db = get_db()
                    watchlist = db.get_config("watchlist", [])
                    if isinstance(watchlist, list):
                        for symbol in watchlist[:10]:
                            try:
                                market = MarketDetector.detect(symbol)
                                await fetcher.get_fundamentals(symbol, market)
                            except Exception as e:
                                logger.debug(f"Fundamental prefetch failed for {symbol}: {e}")
                    last_fundamental = now
                except Exception as e:
                    logger.warning("Fundamental refresh error: %s", e, exc_info=True)

            if now - last_alert_check >= alert_check_interval:
                try:
                    if _is_trading_hours() and _manager.connections:
                        from api.routes import push_alert_event
                        db = get_db()
                        alerts = db.get_config("price_alerts", [])
                        if isinstance(alerts, list):
                            for alert in alerts[:20]:
                                if not alert.get("active", True):
                                    continue
                                symbol = alert.get("symbol", "")
                                threshold = float(alert.get("threshold", 0))
                                direction = alert.get("direction", "above")
                                if not symbol or threshold <= 0:
                                    continue
                                try:
                                    rt = await asyncio.wait_for(fetcher.get_realtime(symbol), timeout=3)
                                    if rt and rt.get("price", 0) > 0:
                                        price = float(rt["price"])
                                        triggered = (direction == "above" and price >= threshold) or \
                                                    (direction == "below" and price <= threshold)
                                        if triggered:
                                            await push_alert_event(
                                                symbol, f"price_{direction}", threshold, price
                                            )
                                            alert["active"] = False
                                            alert["triggered_at"] = datetime.now().isoformat()
                                            alert["triggered_price"] = price
                                            db.set_config("price_alerts", alerts)
                                except (TimeoutError, Exception):
                                    pass
                    last_alert_check = now
                except Exception as e:
                    logger.warning("Alert check error: %s", e, exc_info=True)

            try:
                current_hour = datetime.now().hour
                current_date = datetime.now().strftime("%Y-%m-%d")
                if current_hour == cleanup_hour and current_date != last_cleanup_date:
                    try:
                        db = get_db()
                        result = db.cleanup_stale_data(days=30)
                        logger.info(f"DB cleanup: {result}")
                        last_cleanup_date = current_date
                    except Exception as e:
                        logger.warning("DB cleanup error: %s", e, exc_info=True)
            except Exception as e:
                logger.warning("Cleanup check error: %s", e, exc_info=True)

            await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("Scheduler loop cancelled, exiting")
            raise
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
            await asyncio.sleep(10)


app = FastAPI(
    title="QuantCore",
    version="3.0.0",
    lifespan=lifespan,
    default_response_class=FastJSONResponse,
    description="""
## QuantCore - Quantitative Trading System

A comprehensive quantitative trading platform with:
- Real-time market data fetching
- Advanced technical analysis
- Strategy backtesting
- Risk management
- Portfolio optimization
- API endpoints for integration
- WebSocket for real-time updates

### Key Features:
- **Multiple Data Sources**: AkShare, BaoStock, etc.
- **Vectorized Backtesting**: High-performance strategy testing
- **Risk Management**: Stop-loss, take-profit, VaR, drawdown limits
- **Strategy Engine**: Pre-built strategies with customization
- **WebSocket API**: Real-time market data and alerts
    """,
    contact={
        "name": "QuantCore Team",
        "url": "https://github.com/quantcore",
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT",
    },
    openapi_tags=[
        {
            "name": "system",
            "description": "System health, metrics, and configuration endpoints",
        },
        {
            "name": "market",
            "description": "Market data and stock information endpoints",
        },
        {
            "name": "strategy",
            "description": "Trading strategy generation and execution",
        },
        {
            "name": "backtest",
            "description": "Historical backtesting and analysis",
        },
        {
            "name": "portfolio",
            "description": "Portfolio management and risk analysis",
        },
        {
            "name": "auth",
            "description": "Authentication and authorization endpoints",
        },
    ],
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    from api.errors import AppError
    if isinstance(exc, AppError):
        resp = exc.to_response()
        return JSONResponse(status_code=exc.http_status, content=resp)
    logger.error(f"Unhandled exception: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "服务器内部错误，请稍后重试"},
    )

_config = get_config()
_api_config = _config.get("api", {})
_cors_origins = _config.get("server", {}).get("cors_origins", [])
_default_origins = [
    "http://localhost:8080",
    "http://localhost:8081",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8081",
]
app.add_middleware(APIAuthMiddleware,
    api_key=_api_config.get("api_key", ""),
    enabled=_api_config.get("auth_enabled", False),
)


class _RequestTimingMiddleware:
    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        start = time.monotonic()
        await self._app(scope, receive, send)
        elapsed = time.monotonic() - start
        path = scope.get("path", "")
        if elapsed > 2.0:
            logger.warning("Slow request: %s %.3fs", path, elapsed)
        elif elapsed > 0.5:
            logger.info("Request: %s %.3fs", path, elapsed)


class _SecurityHeadersMiddleware:
    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def _send(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                security_headers = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"x-xss-protection": b"1; mode=block",
                    b"referrer-policy": b"strict-origin-when-cross-origin",
                    b"cache-control": b"no-store",
                }
                for k, v in security_headers.items():
                    if k not in headers:
                        headers[k] = v
                message["headers"] = list(headers.items())
            await send(message)

        await self._app(scope, receive, _send)


app.add_middleware(RequestBodyLimitMiddleware, max_bytes=10_485_760)
app.add_middleware(RequestDedupMiddleware)
app.add_middleware(StructuredTraceMiddleware)
app.add_middleware(GracefulShutdownMiddleware)
app.add_middleware(AdaptiveThrottleMiddleware, base_rps=100)
app.add_middleware(_SecurityHeadersMiddleware)
app.add_middleware(_RequestTimingMiddleware)
app.add_middleware(RequestValidationMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins if _cors_origins else _default_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)


app.include_router(router, prefix="/api")
app.include_router(backtest_router, prefix="/api")
app.include_router(feature_router, prefix="/api")
app.include_router(duckdb_router, prefix="/api")
app.include_router(perf_router, prefix="/api")

try:
    from api.routers.memory import router as memory_router
    app.include_router(memory_router, prefix="/api")
except ImportError as e:
    logger.debug("Memory router import skipped: %s", e)

try:
    from api.routers.innovation import router as innovation_router
    app.include_router(innovation_router, prefix="/api")
except ImportError as e:
    logger.debug("Innovation router import skipped: %s", e)

try:
    import core.strategies_advanced as _strategies_advanced  # noqa: F401
except ImportError as e:
    logger.debug("Advanced strategies import skipped: %s", e)

try:
    from api.routers.quantlab import router as quantlab_router
    app.include_router(quantlab_router, prefix="/api")
except ImportError as e:
    logger.debug("QuantLab router import skipped: %s", e)


@app.get("/api/health")
async def health_check():
    checks: dict[str, str] = {}
    db_ok = False
    try:
        db = getattr(app.state, "db", None)
        if db is not None:
            db.fetch("SELECT 1")
            db_ok = True
    except Exception:
        pass
    checks["database"] = "ok" if db_ok else "unavailable"
    trading_ok = getattr(app.state, "trading", None) is not None
    checks["trading"] = "ok" if trading_ok else "unavailable"

    fetcher_ok = False
    data_sources: dict[str, object] = {}
    try:
        fetcher = getattr(app.state, "fetcher", None)
        if fetcher is not None:
            fetcher_ok = True
            for name, breaker in fetcher._circuit_breakers.items():
                data_sources[name] = {
                    "circuit_state": breaker.state,
                    "failure_count": breaker.failure_count,
                }
            health_stats = getattr(fetcher._health, "_memory_stats", {})
            for (src, req_type), stats in health_stats.items():
                total = stats["success_count"] + stats["fail_count"]
                data_sources.setdefault(src, {})
                data_sources[src][f"{req_type}_success_rate"] = round(
                    stats["success_count"] / total, 4
                ) if total > 0 else 0.0
                data_sources[src][f"{req_type}_avg_latency"] = round(
                    stats["latency_sum"] / stats["success_count"], 4
                ) if stats["success_count"] > 0 else None
    except Exception as e:
        logger.debug("Health check data source error: %s", e)
    checks["data_fetcher"] = "ok" if fetcher_ok else "unavailable"

    cache_info: dict[str, object] = {}
    try:
        from core.async_utils import (
            rt_cache,
            kline_cache,
            sector_cache,
            overview_cache,
            breadth_cache,
            backtest_result_cache,
            fundamental_cache,
            index_cache,
            northbound_cache,
            alert_cache,
        )
        cache_info["rt_cache"] = rt_cache.stats()
        cache_info["kline_cache"] = kline_cache.stats()
        cache_info["sector_cache"] = sector_cache.stats()
        cache_info["overview_cache"] = overview_cache.stats()
        cache_info["breadth_cache"] = breadth_cache.stats()
        cache_info["backtest_result_cache"] = backtest_result_cache.stats()
        cache_info["fundamental_cache"] = fundamental_cache.stats()
        cache_info["index_cache"] = index_cache.stats()
        cache_info["northbound_cache"] = northbound_cache.stats()
        cache_info["alert_cache"] = alert_cache.stats()
    except Exception:
        pass

    uptime = time.monotonic() - getattr(app.state, "start_time", time.monotonic())

    all_ok = db_ok and trading_ok and fetcher_ok
    overall = "healthy" if all_ok else "degraded"
    return {
        "status": overall,
        "checks": checks,
        "data_sources": data_sources,
        "cache_info": cache_info,
        "uptime_seconds": round(uptime, 1),
        "version": "3.0.0",
        "request_id": correlation_id.get(),
    }


_request_counter = itertools.count(1)


@app.middleware("http")
async def unified_metrics_middleware(request: Request, call_next):
    start = time.monotonic()
    path = request.url.path
    request_id = request.headers.get("X-Request-ID", f"srv-{next(_request_counter):08x}")
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Request-ID"] = request_id
    if path.startswith("/api"):
        response.headers["X-API-Version"] = "3.0.0"
    elapsed = time.monotonic() - start
    elapsed_ms = elapsed * 1000
    try:
        app.state._request_count = getattr(app.state, "_request_count", 0) + 1
        app.state._total_response_time = getattr(app.state, "_total_response_time", 0.0) + elapsed_ms
        buckets = getattr(app.state, "_latency_buckets", None)
        if buckets is not None:
            if elapsed_ms < 10:
                buckets["<10ms"] += 1
            elif elapsed_ms < 50:
                buckets["10-50ms"] += 1
            elif elapsed_ms < 100:
                buckets["50-100ms"] += 1
            elif elapsed_ms < 500:
                buckets["100-500ms"] += 1
            elif elapsed_ms < 1000:
                buckets["500ms-1s"] += 1
            elif elapsed_ms < 5000:
                buckets["1s-5s"] += 1
            else:
                buckets[">5s"] += 1
        if response.status_code >= 400:
            app.state._error_count = getattr(app.state, "_error_count", 0) + 1
    except Exception as e:
        logger.debug(f"Metrics middleware error: {e}")
    if path.startswith("/api"):
        try:
            from core.metrics import metrics
            path_seg = path.split("/")[2] if len(path.split("/")) > 2 else "other"
            metrics.increment("api_requests_total", tags={"path": path_seg})
            metrics.histogram("api_request_duration", elapsed_ms, tags={"path": path_seg})
        except Exception as e:
            logger.debug(f"Metrics reporting error: {e}")
    return response


@app.get("/", tags=["system"], summary="Application root endpoint")
def index():
    """
    Get the root endpoint which either serves the frontend application
    or returns system status information.
    """
    index_file = BASE_DIR / "static" / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"name": "QuantCore", "version": "3.0.0", "status": "running", "docs": "/docs"}


@app.get("/health", tags=["system"], summary="Health check endpoint")
async def health_check(request: Request):
    """
    Comprehensive health check that verifies all system components:
    - Database connection
    - Network connectivity
    - Memory usage
    - Cache status
    - Data sources availability
    - Configuration status

    Returns overall system health status with detailed component checks.
    """
    checks = {}
    try:
        db = request.app.state.db
        db.fetchone("SELECT 1")
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "error", "message": str(e)}

    try:
        from core.data_fetcher import get_aiohttp_session
        session = await get_aiohttp_session()
        checks["network"] = {"status": "ok" if session and not session.closed else "error"}
    except Exception as e:
        checks["network"] = {"status": "error", "message": str(e)}

    try:
        import psutil
        process = psutil.Process()
        cpu_pct = process.cpu_percent(interval=0.1)
        mem_info = get_memory_usage()
        checks["memory"] = {
            "rss_mb": mem_info.get("rss_mb", 0),
            "vms_mb": mem_info.get("vms_mb", 0),
            "cpu_percent": round(cpu_pct, 1),
            "status": "ok" if not is_memory_pressure() else ("warning" if not is_memory_critical() else "critical"),
            "system_used_pct": mem_info.get("system_used_pct", 0),
            "process_pct": mem_info.get("process_pct", 0),
        }
    except Exception as e:
        checks["memory"] = {"status": "warning", "message": str(e)}

    try:
        from core.data_fetcher import _history_cache, _realtime_cache
        checks["cache"] = {
            "status": "ok",
            "realtime_entries": str(len(_realtime_cache)),
            "history_entries": str(len(_history_cache)),
        }
    except Exception as e:
        checks["cache"] = {"status": "warning", "message": str(e)}

    try:
        fetcher = getattr(request.app.state, "fetcher", None)
        checks["data_sources"] = {"status": "ok" if fetcher else "unknown"}
    except Exception as e:
        checks["data_sources"] = {"status": "warning", "message": str(e)}

    try:
        config = get_config()
        checks["config"] = {
            "status": "ok",
            "auth_enabled": config.get("api", {}).get("auth_enabled", False),
            "vectorized_backtest": config.get("backtest", {}).get("use_vectorized", True),
        }
    except Exception as e:
        checks["config"] = {"status": "warning", "message": str(e)}

    uptime = time.monotonic() - getattr(request.app.state, "start_time", time.monotonic())
    request_count = getattr(request.app.state, "_request_count", 0)
    total_response_time = getattr(request.app.state, "_total_response_time", 0.0)
    all_ok = all(v.get("status") == "ok" for v in checks.values())
    has_warning = any(v.get("status") == "warning" for v in checks.values())
    has_critical = any(v.get("status") == "critical" for v in checks.values())
    return {
        "status": "healthy" if all_ok else ("degraded" if has_warning else ("critical" if has_critical else "unhealthy")),
        "uptime_seconds": round(uptime),
        "checks": checks,
        "version": "3.0.0",
        "request_count": request_count,
        "avg_response_ms": round(
            total_response_time / request_count if request_count > 0 else 0,
            2,
        ),
    }


@app.get("/api/system/memory", tags=["system"], summary="Get memory usage information")
async def system_memory():
    """
    Get detailed memory usage statistics:
    - Process memory (RSS, VMS)
    - System memory usage
    - Memory pressure status
    - Critical memory warning status
    """
    mem_info = get_memory_usage()
    return {
        "success": True,
        "data": {
            "memory": mem_info,
            "is_pressure": is_memory_pressure(),
            "is_critical": is_memory_critical(),
        },
    }


@app.get("/api/system/stats", tags=["system"], summary="Get system performance statistics")
async def system_stats(request: Request):
    """
    Get comprehensive system performance metrics:
    - Total request count
    - Response time statistics
    - Latency distribution buckets
    - Error count
    - System uptime
    """
    return {
        "success": True,
        "data": {
            "request_count": getattr(request.app.state, "_request_count", 0),
            "total_response_time_ms": getattr(request.app.state, "_total_response_time", 0),
            "latency_buckets": getattr(request.app.state, "_latency_buckets", {}),
            "error_count": getattr(request.app.state, "_error_count", 0),
            "uptime_seconds": round(time.monotonic() - getattr(request.app.state, "start_time", time.monotonic())),
        },
    }


assets_dir = BASE_DIR / "static" / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


@app.middleware("http")
async def spa_fallback(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if response.status_code == 404 and not path.startswith("/api") and not path.startswith("/docs") and "text/html" in request.headers.get("accept", ""):
        index_file = BASE_DIR / "static" / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
    return response


def _build_frontend():
    frontend_dir = BASE_DIR / "frontend"
    if not frontend_dir.exists():
        logger.warning("未找到 frontend 目录，跳过前端构建")
        return False
    static_dir = BASE_DIR / "static"
    build_marker = static_dir / ".frontend-built"

    if static_dir.exists() and not build_marker.exists():
        import shutil
        shutil.rmtree(static_dir, ignore_errors=True)
        logger.info("检测到旧版前端构建，已清理")

    if (static_dir / "index.html").exists() and build_marker.exists():
        logger.info("前端已构建，跳过重复构建")
        return True

    import shutil
    npm_path = shutil.which("npm")
    if not npm_path:
        logger.warning("未找到 npm，请先安装 Node.js: https://nodejs.org/")
        return False

    node_modules = frontend_dir / "node_modules"
    if not node_modules.exists():
        logger.info("安装前端依赖...")
        try:
            result = subprocess.run(
                [npm_path, "install"],
                cwd=str(frontend_dir),
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                logger.warning(f"npm install 失败: {result.stderr[:200]}")
                return False
            logger.info("前端依赖安装完成")
        except Exception as e:
            logger.warning(f"npm install 异常: {e}")
            return False

    logger.info("构建前端...")
    try:
        npx_path = shutil.which("npx") or "npx"
        result = subprocess.run(
            [npx_path, "vite", "build", "--outDir", str(static_dir)],
            cwd=str(frontend_dir),
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            static_dir.mkdir(parents=True, exist_ok=True)
            build_marker.touch()
            logger.info("前端构建完成")
            return True
        logger.warning(f"前端构建失败: {result.stderr[:300]}")
    except Exception as e:
        logger.warning(f"前端构建异常: {e}")
    return False


if __name__ == "__main__":
    os.environ.setdefault("WS_AUTH_ENABLED", "false")
    _kill_existing_process()
    _build_frontend()

    def open_browser():
        _preload_done.wait(timeout=60)
        import urllib.request
        import urllib.error
        for attempt in range(30):
            try:
                req = urllib.request.Request(f"http://localhost:{PORT}/api/health")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    if resp.status == 200:
                        body = resp.read()
                        if b"healthy" in body or b"ok" in body:
                            break
            except (urllib.error.URLError, ConnectionRefusedError, OSError):
                pass
            time.sleep(1)
        webbrowser.open(f"http://localhost:{PORT}")

    threading.Thread(target=open_browser, daemon=True).start()

    logger.info(f"QuantCore 启动 -> http://localhost:{PORT}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="warning",
        workers=1,
        loop="uvloop" if _has_uvloop else "asyncio",
        http="httptools",
        limit_concurrency=200,
        limit_max_requests=10000,
        backlog=2048,
        timeout_keep_alive=30,
        access_log=False,
    )
