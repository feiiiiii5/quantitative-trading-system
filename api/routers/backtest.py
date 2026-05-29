import asyncio
import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from api.backtest_routes import BacktestAdvancedRequest
from api.dependencies import FetcherDep
from api.routers.models import BacktestOptimizeRequest, MultiSymbolBacktestRequest
from api.utils import json_response as _json_response
from api.utils import rate_limiter, safe_error
from core.data_fetcher import SmartDataFetcher
from core.database import OptimizedTTLCache
from core.strategies import STRATEGY_REGISTRY

logger = logging.getLogger(__name__)
router = APIRouter()

_bt_result_cache = OptimizedTTLCache(maxsize=200, ttl=600, cleanup_interval=120)


@router.get("/backtest/attribution")
async def get_performance_attribution(
    fetcher: FetcherDep,
    symbol: str = Query(..., description="股票代码"),
    strategy: str = Query("dual_ma", description="策略名称"),
    period: int = Query(250, ge=120, le=500, description="数据天数"),
):
    """策略收益归因分析"""
    try:
        from core.backtest import BacktestEngine
        from core.performance_attribution import PerformanceAttribution
        from core.strategies import STRATEGY_REGISTRY

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
        bench_close = pd.to_numeric(df["close"], errors="coerce").fillna(0).values.astype(float)
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
    fetcher: FetcherDep,
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
        bench_close = pd.to_numeric(df["close"], errors="coerce").fillna(0).values.astype(float)
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
    fetcher: FetcherDep,
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


@router.post("/backtest/multi-symbol")
@rate_limiter(max_calls=5, time_window=60.0)
async def run_multi_symbol_backtest(
    fetcher: FetcherDep,
    body: MultiSymbolBacktestRequest,
):
    try:
        valid_methods = {"equal_weight", "sharpe_weighted", "inverse_vol", "correlation_adjusted"}
        if body.position_method not in valid_methods:
            return _json_response(False, error=f"position_method must be one of {valid_methods}")

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
@rate_limiter(max_calls=5, time_window=60.0)
async def run_advanced_backtest(
    request: Request,
    body: BacktestAdvancedRequest,
    fetcher: FetcherDep,
):
    try:
        from core.backtest import BacktestEngine, BacktestResult
        from core.backtest import run_backtest as run_bt
        effective_strategy = body.strategy_name or body.strategy_type
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
@rate_limiter(max_calls=5, time_window=60.0)
async def optimize_strategy(
    fetcher: FetcherDep,
    body: BacktestOptimizeRequest,
):
    try:
        from core.backtest import grid_search_params
        if body.strategy_name not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"未知策略: {body.strategy_name}")
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
    _lock = threading.Lock()
    _MAX_AGE_SECONDS = 3600
    _MAX_ENTRIES = 200

    @classmethod
    def _evict(cls) -> None:
        now = time.time()
        expired = [jid for jid, job in cls._state.items()
                   if now - job.get("updated_at", 0) > cls._MAX_AGE_SECONDS]
        for jid in expired:
            del cls._state[jid]
        if len(cls._state) > cls._MAX_ENTRIES:
            sorted_jobs = sorted(cls._state.items(), key=lambda x: x[1].get("updated_at", 0))
            for jid, _ in sorted_jobs[:len(cls._state) - cls._MAX_ENTRIES]:
                del cls._state[jid]

    @classmethod
    def submit(cls, job_id: str, progress: float, phase: str, message: str, result: dict | None = None, error: str | None = None) -> None:
        with cls._lock:
            cls._evict()
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
        with cls._lock:
            return cls._state.get(job_id)

    @classmethod
    def poll(cls, job_id: str) -> dict:
        with cls._lock:
            job = cls._state.get(job_id)
            if not job:
                return {"status": "not_found"}
            if job.get("result") is not None or job.get("error") is not None:
                return {"status": "completed", **job}
            return {"status": "running", **job}

    @classmethod
    def set_result(cls, job_id: str, result: dict) -> None:
        with cls._lock:
            if job_id in cls._state:
                cls._state[job_id]["result"] = result
                cls._state[job_id]["progress"] = 1.0
                cls._state[job_id]["phase"] = "completed"

    @classmethod
    def set_error(cls, job_id: str, error: str) -> None:
        with cls._lock:
            if job_id in cls._state:
                cls._state[job_id]["error"] = error
                cls._state[job_id]["phase"] = "error"

    @classmethod
    def cleanup(cls, job_id: str) -> None:
        with cls._lock:
            cls._state.pop(job_id, None)


@router.post("/backtest/stream")
async def submit_backtest_stream(request: Request, body: BacktestAdvancedRequest):
    cache_key_parts = f"{body.symbol}:{body.strategy_name or body.strategy_type}:{body.start_date}:{body.end_date}:{body.initial_capital}:{body.leverage}"
    cache_key = hashlib.sha256(cache_key_parts.encode()).hexdigest()[:16]
    cached = _bt_result_cache.get(cache_key)
    if cached is not None:
        return {"job_id": cached["job_id"], "status": "completed", "cached": True, "result": cached["result"]}
    job_id = str(uuid.uuid4())[:8]
    BacktestJobManager.submit(job_id, 0.0, "queued", f"任务 {job_id} 已加入队列，等待执行...")
    asyncio.create_task(_run_backtest_stream(job_id, request.app, body, cache_key))
    return {"job_id": job_id, "status": "queued"}


async def _run_backtest_stream(job_id: str, app, body: BacktestAdvancedRequest, cache_key: str = "") -> None:
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
        if cache_key:
            _bt_result_cache.set(cache_key, {"job_id": job_id, "result": result})

    except Exception as e:
        logger.error("Backtest stream job %s failed: %s", job_id, e, exc_info=True)
        BacktestJobManager.set_error(job_id, safe_error(e))


@router.get("/backtest/stream/{job_id}")
async def stream_backtest_result(job_id: str):
    async def event_generator():
        start_time = time.monotonic()
        last_progress = -1.0
        while time.monotonic() - start_time < 300:
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
        else:
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


@router.get("/backtest/walk-forward")
async def get_walk_forward_analysis(
    fetcher: FetcherDep,
    symbol: str = Query(..., description="股票代码"),
    strategy: str = Query("dual_ma", description="策略名称"),
    is_window: int = Query(120, ge=60, le=500, description="样本内窗口"),
    oos_window: int = Query(30, ge=10, le=120, description="样本外窗口"),
    anchored: bool = Query(False, description="是否锚定"),
):
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY

        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 120:
            return _json_response(False, error="数据不足，至少需要120个交易日")

        df = df.tail(is_window + oos_window)
        strategy_cls = STRATEGY_REGISTRY.get(strategy)
        if strategy_cls is None:
            available = list(set(STRATEGY_REGISTRY.keys()))[:10]
            return _json_response(False, error=f"未知策略: {strategy}，可用: {available}")

        from core.walk_forward import WalkForwardConfig, calc_overfitting_score, generate_walk_forward_splits

        n_splits = max(1, len(df) // (is_window + oos_window))
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


@router.get("/backtest/sensitivity")
async def get_strategy_sensitivity(
    fetcher: FetcherDep,
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
