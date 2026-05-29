"""
QuantCore API路由模块
提供REST API、WebSocket实时推送和SSE流式回测进度

此文件为薄封装层，所有路由已拆分至 api/routers/ 子模块，
共享基础设施移至 api/connection_manager.py。
"""
import threading  # noqa: F401 – expected by tests

from fastapi import APIRouter

from api.connection_manager import (  # noqa: F401 – re-exported for main.py & tests
    _WS_AUTH_ENABLED,
    ConnectionManager,
    _is_trading_hours,
    _manager,
    _TTLCache,
    _ws_authenticate,
    push_alert_event,
    push_portfolio_metrics,
    push_realtime_data,
    push_regime_updates,
    sweep_stale_pnl_connections,
    sweep_stale_regime_connections,
    sweep_stale_signal_connections,
)
from api.routers.auth import router as _auth_router
from api.routers.backtest import router as _backtest_router
from api.routers.market import router as _market_router
from api.routers.models import (  # noqa: F401 – re-exported for tests
    AlertAddRequest,
    ConfigSetRequest,
    RegisterRequest,
    TradingBuyRequest,
    WatchlistAddRemoveRequest,
)
from api.routers.portfolio import router as _portfolio_router
from api.routers.stock import router as _stock_router
from api.routers.strategy import router as _strategy_router
from api.routers.system import router as _system_router
from api.routers.trading import router as _trading_router
from api.routers.watchlist import router as _watchlist_router
from api.routers.websocket import router as _websocket_router

router = APIRouter()

router.include_router(_auth_router)
router.include_router(_system_router)
router.include_router(_market_router)
router.include_router(_stock_router)
router.include_router(_portfolio_router)
router.include_router(_trading_router)
router.include_router(_watchlist_router)
router.include_router(_backtest_router)
router.include_router(_strategy_router)
router.include_router(_websocket_router)
