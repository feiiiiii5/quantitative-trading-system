"""
QuantCore - 量化交易系统
简洁高效，一键启动
"""
import asyncio
import gc
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
    import uvloop
    uvloop.install()
    _has_uvloop = True
except ImportError:
    _has_uvloop = False

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router, push_realtime_data, _manager
from api.auth import APIAuthMiddleware
from core.logger import setup_logger
from core.config import get_config

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
except Exception:
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
            except Exception:
                pass
            return
    except Exception:
        try:
            _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
            _PID_FILE.write_text(str(os.getpid()))
        except Exception:
            pass
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
            result = subprocess.run(
                ["lsof", "-ti", f":{PORT}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip():
                for pid_str in result.stdout.strip().split("\n"):
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
                        try:
                            os.kill(pid, signal.SIGTERM)
                        except (ProcessLookupError, PermissionError):
                            pass
                time.sleep(0.5)
    except Exception as e:
        logger.debug(f"Port cleanup error: {e}")

    try:
        _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PID_FILE.write_text(str(os.getpid()))
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("QuantCore 启动中...")

    from core.database import get_db, get_cache_manager
    from core.data_fetcher import SmartDataFetcher, get_fetcher
    from core.backtest import BacktestEngine
    from core.strategies import CompositeStrategy
    from core.simulated_trading import SimulatedTrading

    app.state.db = get_db()
    app.state.fetcher = get_fetcher()
    app.state.composite_strategy = CompositeStrategy()
    app.state.backtest_engine = BacktestEngine()
    app.state.trading = SimulatedTrading()
    app.state.start_time = time.time()
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
    except Exception:
        pass

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

        task2 = asyncio.create_task(_stale_ws_sweeper())
        app.state._bg_tasks.append(task2)
    except Exception as e:
        logger.warning(f"WS push task start failed: {e}")

    try:
        task = asyncio.create_task(_scheduler_loop(app))
        app.state._bg_tasks.append(task)
    except Exception as e:
        logger.warning(f"Scheduler task start failed: {e}")

    try:
        from core.market_data import start_background_refresh
        start_background_refresh()
    except Exception:
        pass

    os.makedirs(BASE_DIR / "data", exist_ok=True)
    os.makedirs(BASE_DIR / "static", exist_ok=True)

    logger.info(f"QuantCore 启动完成 -> http://localhost:{PORT}")
    yield

    logger.info("QuantCore 正在关闭...")

    try:
        for task in app.state._bg_tasks:
            if not task.done():
                task.cancel()
        if app.state._bg_tasks:
            await asyncio.gather(*app.state._bg_tasks, return_exceptions=True)
        logger.info("后台异步任务已取消")
    except Exception as e:
        logger.warning(f"Task cancellation failed: {e}")

    try:
        from core.data_fetcher import close_aiohttp_session
        await close_aiohttp_session()
        logger.info("aiohttp session 已关闭")
    except Exception as e:
        logger.warning(f"aiohttp session close failed: {e}")

    try:
        db = get_db()
        db._flush_buffer()
        logger.info("数据库写缓冲已刷入磁盘")
    except Exception as e:
        logger.warning(f"DB buffer flush on shutdown failed: {e}")

    try:
        from core.market_data import stop_background_refresh
        stop_background_refresh()
    except Exception:
        pass

    try:
        cm = get_cache_manager()
        cm.flush()
    except Exception as e:
        logger.warning(f"Cache flush on shutdown failed: {e}")

    try:
        trading: SimulatedTrading = app.state.trading
        db = get_db()
        db.set_config("portfolio_snapshot", trading.get_account_info())
        logger.info("Portfolio snapshot saved")
    except Exception as e:
        logger.warning(f"Portfolio snapshot failed: {e}")

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
    from api.routes import _manager, _is_trading_hours
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

            if now - last_ws_rt >= ws_rt_interval:
                try:
                    if _is_trading_hours() and _manager.connections:
                        subscribed = _manager.get_all_subscribed_symbols()
                        for symbol in list(subscribed)[:30]:
                            try:
                                await asyncio.wait_for(fetcher.get_realtime(symbol), timeout=3)
                            except (asyncio.TimeoutError, Exception):
                                pass
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
                            except Exception:
                                pass
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
                                except (asyncio.TimeoutError, Exception):
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


try:
    from fastapi.responses import ORJSONResponse
    _default_response_class = ORJSONResponse
except ImportError:
    _default_response_class = None

app = FastAPI(
    title="QuantCore", version="3.0.0", lifespan=lifespan,
    **({"default_response_class": _default_response_class} if _default_response_class else {}),
)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "服务器内部错误，请稍后重试"},
    )

_config = get_config()
_api_config = _config.get("api", {})
_cors_origins = _config.get("server", {}).get("cors_origins", [])
_default_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
app.add_middleware(APIAuthMiddleware,
    api_key=_api_config.get("api_key", ""),
    enabled=_api_config.get("auth_enabled", False),
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins if _cors_origins else _default_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)


app.include_router(router, prefix="/api")

from api.backtest_routes import backtest_router
app.include_router(backtest_router, prefix="/api")

from api.feature_routes import feature_router
app.include_router(feature_router, prefix="/api")


@app.middleware("http")
async def unified_metrics_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
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
    except Exception:
        pass
    path = request.url.path
    if path.startswith("/api"):
        try:
            from core.metrics import metrics
            path_seg = path.split("/")[2] if len(path.split("/")) > 2 else "other"
            metrics.increment("api_requests_total", tags={"path": path_seg})
            metrics.timer("api_request_duration", elapsed, tags={"path": path_seg})
        except Exception:
            pass
    return response


@app.get("/")
def index():
    index_file = BASE_DIR / "static" / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"name": "QuantCore", "version": "3.0.0", "status": "running", "docs": "/docs"}


@app.get("/health")
async def health_check(request: Request):
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
        mem = process.memory_info()
        cpu_pct = process.cpu_percent(interval=0.1)
        checks["memory"] = {
            "rss_mb": round(mem.rss / 1024 ** 2, 1),
            "vms_mb": round(mem.vms / 1024 ** 2, 1),
            "cpu_percent": round(cpu_pct, 1),
            "status": "ok" if mem.rss < 512 * 1024 * 1024 else "warning",
        }
    except Exception as e:
        checks["memory"] = {"status": "warning", "message": str(e)}

    try:
        from core.data_fetcher import _history_cache, _realtime_cache
        checks["cache"] = {
            "status": "ok",
            "realtime_entries": len(_realtime_cache),
            "history_entries": len(_history_cache),
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

    uptime = time.time() - getattr(request.app.state, "start_time", time.time())
    all_ok = all(v.get("status") == "ok" for v in checks.values())
    has_warning = any(v.get("status") == "warning" for v in checks.values())
    return {
        "status": "healthy" if all_ok else ("degraded" if has_warning else "unhealthy"),
        "uptime_seconds": round(uptime),
        "checks": checks,
        "version": "3.0.0",
        "request_count": getattr(request.app.state, "_request_count", 0),
        "avg_response_ms": round(
            getattr(request.app.state, "_total_response_time", 0) / max(getattr(request.app.state, "_request_count", 1), 1),
            2,
        ),
    }


assets_dir = BASE_DIR / "static" / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


@app.middleware("http")
async def spa_fallback(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if response.status_code == 404 and not path.startswith("/api") and not path.startswith("/docs"):
        if "text/html" in request.headers.get("accept", ""):
            index_file = BASE_DIR / "static" / "index.html"
            if index_file.exists():
                return FileResponse(str(index_file))
    return response


def _build_frontend():
    frontend_dir = BASE_DIR / "frontend"
    if not frontend_dir.exists():
        return False
    static_dir = BASE_DIR / "static"
    if (static_dir / "index.html").exists():
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
            logger.info("前端构建完成")
            return True
        logger.warning(f"前端构建失败: {result.stderr[:200]}")
    except Exception as e:
        logger.warning(f"前端构建异常: {e}")
    return False


if __name__ == "__main__":
    _kill_existing_process()
    _build_frontend()

    def open_browser():
        _preload_done.wait(timeout=30)
        webbrowser.open(f"http://localhost:{PORT}")

    threading.Thread(target=open_browser, daemon=True).start()

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
