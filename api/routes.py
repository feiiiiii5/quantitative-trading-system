"""
QuantCore API路由模块
提供REST API、WebSocket实时推送和SSE流式回测进度

此文件为薄封装层，所有路由已拆分至 api/routers/ 子模块，
共享基础设施移至 api/connection_manager.py。
"""
import threading
from api.connection_manager import (
    _ALLOWED_CONFIG_KEYS,
    _MAX_PUSH_SYMBOLS,
    _MAX_SUBSCRIBE_SYMBOLS,
    _PNL_MAX_CONNECTIONS,
    _PNL_STALE_TIMEOUT,
    _PRIORITY_INDEX,
    _PRIORITY_INTERVALS,
    _PRIORITY_NORMAL,
    _PRIORITY_POSITION,
    _PRIORITY_WATCHLIST,
    _PORTFOLIO_CACHE_TTL,
    _PORTFOLIO_MAX_CONNECTIONS,
    _PORTFOLIO_PUSH_INTERVAL,
    _REGIME_MAX_CONNECTIONS,
    _REGIME_PUSH_INTERVAL,
    _REGIME_STALE_TIMEOUT,
    _SIGNAL_MAX_CONNECTIONS,
    _SIGNAL_STALE_TIMEOUT,
    _SSE_KEEPALIVE_INTERVAL,
    _SSE_MAX_SYMBOLS,
    _WS_AUTH_ENABLED,
    _WS_SEND_TIMEOUT,
    _api_response_cache,
    _build_message,
    _check_price_alerts,
    _classify_symbol_priority,
    _diff_push,
    _evict_stale_push_state,
    _index_symbols,
    _is_trading_hours,
    _kline_cache,
    _last_indices_hash,
    _last_push_state,
    _last_quote_hash,
    _manager,
    _pnl_connections,
    _pnl_last_active,
    _pnl_lock,
    _portfolio_cache_timestamps,
    _portfolio_connections,
    _portfolio_lock,
    _portfolio_metrics_cache,
    _push_seq,
    _push_seq_lock,
    _push_state_lock,
    _regime_connections,
    _regime_last_active,
    _regime_lock,
    _rt_cache,
    _safe_ws_send,
    _signal_connections,
    _signal_last_active,
    _signal_lock,
    _start_time,
    _strategy_list_cache,
    _symbol_last_push,
    _symbol_priority,
    _topic_manager,
    _ws_authenticate,
    cache_response,
    push_alert_event,
    push_market_event,
    push_portfolio_metrics,
    push_realtime_data,
    push_regime_updates,
    push_signal_event,
    set_symbol_priority,
    sweep_stale_pnl_connections,
    sweep_stale_regime_connections,
    sweep_stale_signal_connections,
    ConnectionManager,
    TopicConnectionManager,
    _TTLCache,
)
from api.routers.models import (
    AlertAddRequest,
    AlertRemoveRequest,
    AlphaEvolveRequest,
    AuditStrategyRequest,
    BacktestOptimizeRequest,
    BacktestRequest,
    BlackLittermanRequest,
    BuyOrderRequest,
    CointegrationTestRequest,
    ConfigSetRequest,
    FactorPipelineRequest,
    FeatureFlagRegisterRequest,
    FeatureFlagUpdateRequest,
    LoginRequest,
    MonteCarloVaRRequest,
    MultiSymbolBacktestRequest,
    PairMiningRequest,
    PortfolioImportRequest,
    PriceAlertRequest,
    RebalanceScheduleRequest,
    RegisterRequest,
    SeasonalityRequest,
    SellOrderRequest,
    TCAAnalyzeRequest,
    TCABatchRequest,
    TCAExecutionRecommendRequest,
    TradingBuyRequest,
    TradingSellRequest,
    TWAPSimulationRequest,
    WatchlistAddRemoveRequest,
    WatchlistAddRequest,
    WatchlistReorderRequest,
)
from api.routers.auth import router as _auth_router
from api.routers.backtest import router as _backtest_router
from api.routers.market import router as _market_router
from api.routers.portfolio import router as _portfolio_router
from api.routers.stock import router as _stock_router
from api.routers.strategy import router as _strategy_router
from api.routers.system import router as _system_router
from api.routers.trading import router as _trading_router
from api.routers.watchlist import router as _watchlist_router
from api.routers.websocket import router as _websocket_router

from fastapi import APIRouter

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
