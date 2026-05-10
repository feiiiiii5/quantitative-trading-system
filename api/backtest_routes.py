import asyncio
import io
import logging
import time
import uuid
import zlib

import numpy as np
from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.utils import json_response as _json_response
from api.utils import safe_error
from core.json_utils import json_dumps

logger = logging.getLogger(__name__)
backtest_router = APIRouter()

_perf_overview_cache: dict[str, tuple[float, dict]] = {}
_PERF_CACHE_TTL = 600.0
_PERF_CACHE_MAX = 500

_COMPRESS_THRESHOLD = 50_000

_backtest_result_cache: dict[str, tuple[float, dict]] = {}
_BACKTEST_CACHE_TTL = 300.0
_BACKTEST_CACHE_MAX = 1000


def _sanitize_numpy(obj):
    if isinstance(obj, dict):
        return {k: _sanitize_numpy(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_numpy(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return _sanitize_numpy(obj.tolist())
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def _compressed_response(data: dict) -> Response:
    data = _sanitize_numpy(data)
    json_bytes = json_dumps(data).encode("utf-8")
    if len(json_bytes) > _COMPRESS_THRESHOLD:
        compressed = zlib.compress(json_bytes, level=6)
        return Response(
            content=compressed,
            media_type="application/json",
            headers={
                "Content-Encoding": "deflate",
                "X-Original-Size": str(len(json_bytes)),
                "X-Compressed-Size": str(len(compressed)),
            },
        )
    return Response(content=json_bytes, media_type="application/json")


class BacktestRunRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")
    strategy_type: str = Field("adaptive", max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    start_date: str = Field("2024-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field("2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$")
    initial_capital: float = 1000000
    commission: float = 0.0003

    @field_validator("initial_capital")
    @classmethod
    def validate_capital(cls, v: float) -> float:
        if v < 10000 or v > 1e9:
            raise ValueError("初始资金范围: 1万-10亿")
        return v

    @field_validator("commission")
    @classmethod
    def validate_commission(cls, v: float) -> float:
        if v < 0 or v > 0.01:
            raise ValueError("佣金费率范围: 0-1%")
        return v


class BacktestAdvancedRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")
    strategy_type: str = Field("adaptive", max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    strategy_name: str | None = Field(None, max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    start_date: str = Field("2022-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field("2024-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$")
    initial_capital: float = 1000000
    enable_short: bool = False
    leverage: float = 1.0
    monte_carlo: bool = False
    n_simulations: int = 500
    sensitivity: bool = False
    walk_forward: bool = False

    @field_validator("initial_capital")
    @classmethod
    def validate_capital(cls, v: float) -> float:
        if v < 10000 or v > 1e9:
            raise ValueError("初始资金范围: 1万-10亿")
        return v

    @field_validator("leverage")
    @classmethod
    def validate_leverage(cls, v: float) -> float:
        if v < 0.1 or v > 5.0:
            raise ValueError("杠杆范围: 0.1-5.0")
        return v

    @field_validator("n_simulations")
    @classmethod
    def validate_simulations(cls, v: int) -> int:
        if v < 10 or v > 5000:
            raise ValueError("模拟次数范围: 10-5000")
        return v


@backtest_router.get("/backtest/strategies")
async def get_backtest_strategies(request: Request):
    try:
        from core.strategies import STRATEGY_REGISTRY
        strategy_info = {}
        seen = set()
        for _alias, cls in STRATEGY_REGISTRY.items():
            real_name = cls.__name__
            if real_name in seen:
                continue
            seen.add(real_name)
            try:
                inst = cls()
                info = inst.get_info()
                info["param_space"] = cls.get_param_space()
                strategy_info[real_name] = info
            except Exception as e:
                logger.warning("Strategy introspection failed for %s: %s", real_name, e)
                strategy_info[real_name] = {"name": real_name, "type": "unknown"}
        strategy_info["AdaptiveEngine"] = {
            "name": "自适应量化策略引擎",
            "type": "adaptive",
            "param_space": {},
        }
        return _json_response(True, data=strategy_info)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@backtest_router.post("/backtest/heatmap")
async def strategy_performance_heatmap(request: Request):
    try:
        body = await request.json()
        symbol = body.get("symbol", "000001.SZ")
        strategies = body.get("strategies", [])
        metrics_list = body.get(
            "metrics",
            ["sharpe_ratio", "total_return", "max_drawdown", "win_rate", "profit_loss_ratio"],
        )
        start_date = body.get("start_date", "2024-01-01")
        end_date = body.get("end_date", "2025-12-31")

        if not strategies or len(strategies) < 2:
            return _json_response(False, error="At least 2 strategies required")

        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="数据不足")

        import pandas as pd
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].reset_index(drop=True)

        if len(df) < 30:
            return _json_response(False, error="数据不足，至少需要30个交易日")

        engine = BacktestEngine()
        heatmap_data = {}

        async def _run_strategy(sname: str) -> tuple[str, dict | None]:
            if sname not in STRATEGY_REGISTRY:
                return sname, None
            try:
                strategy = STRATEGY_REGISTRY[sname]()
                result = await asyncio.to_thread(engine.run, strategy, df, symbol)
                if result and result.total_trades > 0:
                    sd = result.summary_dict()
                    return sname, {m: sd.get(m, 0.0) for m in metrics_list}
            except Exception as e:
                logger.debug("Heatmap strategy %s failed: %s", sname, e)
            return sname, None

        pairs = await asyncio.gather(*[_run_strategy(s) for s in strategies])
        for sname, data in pairs:
            if data is not None:
                heatmap_data[sname] = data

        if len(heatmap_data) < 2:
            return _json_response(False, error="至少需要2个有效策略")

        strategy_names = list(heatmap_data.keys())
        matrix = []
        for m in metrics_list:
            row = []
            for sname in strategy_names:
                row.append(heatmap_data[sname].get(m, 0.0))
            matrix.append(row)

        return _json_response(True, data={
            "strategies": strategy_names,
            "metrics": metrics_list,
            "matrix": matrix,
            "data": heatmap_data,
        })
    except Exception as e:
        logger.error("Strategy heatmap error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


@backtest_router.get("/backtest/strategies/categorized")
async def get_strategies_categorized(
    request: Request,
    category: str | None = Query(None, max_length=30),
):
    """分类策略列表，支持按类别过滤"""
    try:
        from core.strategies import get_strategy_registry
        registry = get_strategy_registry()
        strategies = registry.list_strategies(category=category)
        categories = registry.list_categories()
        return _json_response(True, data={
            "strategies": strategies,
            "categories": categories,
            "total": len(strategies),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))
@backtest_router.post("/backtest/run")
async def run_backtest(
    request: Request,
    body: BacktestRunRequest,
):
    cache_key = "%s:%s:%s:%s" % (body.symbol, body.strategy_type, body.start_date, body.end_date)
    cached_entry = _backtest_result_cache.get(cache_key)
    if cached_entry is not None:
        ts, cached_data = cached_entry
        if time.monotonic() - ts < _BACKTEST_CACHE_TTL:
            return _compressed_response({"success": True, "data": cached_data, "cached": True})

    from core.async_utils import backtest_result_cache, CACHE_TTL
    bt_cached = await backtest_result_cache.get(cache_key)
    if bt_cached is not None:
        return _compressed_response({"success": True, "data": bt_cached, "cached": True})

    fetcher = request.app.state.fetcher
    df = await fetcher.get_history(body.symbol, period="all", kline_type="daily", adjust="qfq")
    if df is None or df.empty:
        return _json_response(False, error=f"无法获取 {body.symbol} 的历史数据")

    result = await _run_single_or_adaptive(body.strategy_type, body.symbol, body.start_date, body.end_date, body.initial_capital, df)

    if isinstance(result, dict) and "error" in result:
        return _json_response(False, error=result["error"])

    if len(_backtest_result_cache) >= _BACKTEST_CACHE_MAX:
        oldest_key = min(_backtest_result_cache, key=lambda k: _backtest_result_cache[k][0])
        del _backtest_result_cache[oldest_key]
    _backtest_result_cache[cache_key] = (time.monotonic(), result)
    await backtest_result_cache.set(cache_key, result, CACHE_TTL["backtest_result"])

    return _compressed_response({"success": True, "data": result})


@backtest_router.post("/backtest/run/stream")
async def run_backtest_stream(
    request: Request,
    body: BacktestRunRequest,
):
    async def generate():
        cache_key = "%s:%s:%s:%s" % (body.symbol, body.strategy_type, body.start_date, body.end_date)
        from core.async_utils import backtest_result_cache, CACHE_TTL
        bt_cached = await backtest_result_cache.get(cache_key)
        if bt_cached is not None:
            yield f"data: {json_dumps({'type': 'result', 'data': bt_cached, 'cached': True})}\n\n"
            return

        yield f"data: {json_dumps({'type': 'log', 'message': 'Fetching historical data...'})}\n\n"

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            yield f"data: {json_dumps({'type': 'error', 'message': f'无法获取 {body.symbol} 的历史数据'})}\n\n"
            return

        yield f"data: {json_dumps({'type': 'log', 'message': f'Loaded {len(df)} bars, running backtest...'})}\n\n"

        loop = asyncio.get_running_loop()
        result_queue: asyncio.Queue = asyncio.Queue()

        def progress_callback(msg: str):
            loop.call_soon_threadsafe(result_queue.put_nowait, {"type": "log", "message": msg})

        def run_backtest_sync():
            try:
                import pandas as pd
                from core.backtest import run_backtest as run_bt
                work_df = df.copy()
                if "date" in work_df.columns:
                    work_df["date"] = pd.to_datetime(work_df["date"], errors="coerce")
                    work_df = work_df.dropna(subset=["date"])
                    work_df = work_df[(work_df["date"] >= body.start_date) & (work_df["date"] <= body.end_date)].reset_index(drop=True)
                result = run_bt(body.symbol, body.strategy_type, body.start_date, body.end_date, body.initial_capital, None, work_df)
                loop.call_soon_threadsafe(result_queue.put_nowait, {"type": "result", "data": result})
            except Exception as e:
                loop.call_soon_threadsafe(result_queue.put_nowait, {"type": "error", "message": str(e)})

        future = loop.run_in_executor(None, run_backtest_sync)

        while True:
            try:
                msg = await asyncio.wait_for(result_queue.get(), timeout=120.0)
                yield f"data: {json_dumps(msg)}\n\n"
                if msg.get("type") in ("result", "error"):
                    break
            except asyncio.TimeoutError:
                yield f"data: {json_dumps({'type': 'error', 'message': 'Backtest timeout'})}\n\n"
                break

        await future

        try:
            result_data = msg.get("data", {})
            if msg.get("type") == "result" and result_data:
                await backtest_result_cache.set(cache_key, _sanitize_numpy(result_data), CACHE_TTL["backtest_result"])
        except Exception:
            pass

    return StreamingResponse(generate(), media_type="text/event-stream")


@backtest_router.get("/backtest/result/{task_id}")
async def get_backtest_result(request: Request, task_id: str):
    return _json_response(False, error="回测结果查询暂不支持")


_compare_cache: dict[str, tuple[float, dict]] = {}
_COMPARE_CACHE_TTL = 360.0
_COMPARE_CACHE_MAX = 600


@backtest_router.get("/backtest/compare")
async def compare_strategies(
    request: Request,
    symbol: str = Query(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    start_date: str = Query("2024-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query("2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    period: str = Query("1y", max_length=5),
):
    try:
        cache_key = "cmp:%s:%s:%s" % (symbol, start_date, end_date)
        cached_entry = _compare_cache.get(cache_key)
        if cached_entry is not None:
            ts, cached_data = cached_entry
            if time.monotonic() - ts < _COMPARE_CACHE_TTL:
                return _compressed_response({"success": True, "data": cached_data, "cached": True})

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="数据不足")

        import pandas as pd
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])

        work_df = df.copy()
        if "date" in work_df.columns:
            work_df = work_df[(work_df["date"] >= start_date) & (work_df["date"] <= end_date)].reset_index(drop=True)

        if len(work_df) < 30:
            work_df = df.tail(252).reset_index(drop=True)
            if len(work_df) < 30:
                return _json_response(False, error="数据不足，请更换股票代码或时间范围")

        engine = request.app.state.backtest_engine
        strategies = request.app.state.composite_strategy.strategies
        results = engine.run_multi(strategies, work_df)

        from core.backtest import compare_results
        result_list = list(results.values())
        comparison_data = compare_results(result_list)

        if len(_compare_cache) >= _COMPARE_CACHE_MAX:
            oldest_key = min(_compare_cache, key=lambda k: _compare_cache[k][0])
            del _compare_cache[oldest_key]
        _compare_cache[cache_key] = (time.monotonic(), comparison_data)

        return _json_response(True, data=comparison_data)
    except Exception as e:
        logger.error("compare strategies error: %s", e,  exc_info=True)
        return _json_response(False, error=safe_error(e))


@backtest_router.get("/backtest/recommend")
async def recommend_strategy(
    request: Request,
    symbol: str = Query(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    start_date: str = Query("2024-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query("2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    try:
        import numpy as np
        import pandas as pd

        from core.adaptive_strategy import REGIME_LABELS, STRATEGY_ALLOCATION, MarketRegime, classify_market_regime
        from core.indicators import calc_adx, calc_atr
        from core.strategies import STRATEGY_REGISTRY

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="无法获取历史数据")

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])

        work_df = df.copy()
        if "date" in work_df.columns:
            work_df = work_df[(work_df["date"] >= start_date) & (work_df["date"] <= end_date)].reset_index(drop=True)

        if len(work_df) < 30:
            work_df = df.tail(252).reset_index(drop=True)
            if len(work_df) < 30:
                return _json_response(False, error="数据不足，请更换股票代码或时间范围")

        c = work_df["close"].values.astype(float)
        h = work_df["high"].values.astype(float)
        low_arr = work_df["low"].values.astype(float)
        v = work_df["volume"].values.astype(float) if "volume" in work_df.columns else np.ones(len(c))

        returns = np.diff(c) / np.where(c[:-1] > 0, c[:-1], 1)
        returns = np.where(np.isfinite(returns), returns, 0)

        hist_vol = float(np.std(returns) * np.sqrt(252))
        trend = float((c[-1] - c[0]) / c[0] * 100) if c[0] > 0 else 0

        adx_arr = calc_adx(h, low_arr, c, period=14)
        last_adx = float(adx_arr[-1]) if not np.isnan(adx_arr[-1]) else 20.0

        atr_arr = calc_atr(h, low_arr, c, period=14)
        avg_atr_pct = float(np.nanmean(atr_arr[-20:]) / np.mean(c[-20:]) * 100) if len(c) >= 20 else 2.0

        ma5 = float(np.mean(c[-5:]))
        ma20 = float(np.mean(c[-20:])) if len(c) >= 20 else ma5
        ma60 = float(np.mean(c[-60:])) if len(c) >= 60 else ma20
        ma_alignment = "bullish" if ma5 > ma20 > ma60 else ("bearish" if ma5 < ma20 < ma60 else "neutral")

        rsi_period = 14
        if len(returns) >= rsi_period:
            delta = np.diff(c)
            gain = np.where(delta > 0, delta, 0)
            loss_arr = np.where(delta < 0, -delta, 0)
            avg_gain = np.mean(gain[-rsi_period:])
            avg_loss = np.mean(loss_arr[-rsi_period:])
            rs = avg_gain / max(avg_loss, 1e-9)
            rsi = 100 - 100 / (1 + rs)
        else:
            rsi = 50.0

        vol_ma20 = float(np.mean(v[-20:])) if len(v) >= 20 else 1
        vol_ratio = float(v[-1]) / max(vol_ma20, 1) if vol_ma20 > 0 else 1.0

        bb_mid = float(np.mean(c[-20:])) if len(c) >= 20 else float(c[-1])
        bb_std = float(np.std(c[-20:])) if len(c) >= 20 else 0
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_position = (float(c[-1]) - bb_lower) / max(bb_upper - bb_lower, 1e-9)

        regimes = classify_market_regime(work_df)
        current_regime = regimes[-1] if regimes else MarketRegime.LOW_VOLATILITY_CONSOLIDATION
        regime_name = REGIME_LABELS.get(current_regime, "未知")

        regime_counts = {}
        for r in regimes[-60:]:
            label = REGIME_LABELS.get(r, "未知")
            regime_counts[label] = regime_counts.get(label, 0) + 1
        dominant_regime = max(regime_counts, key=regime_counts.get) if regime_counts else "未知"

        analysis = {
            "trend": round(trend, 2),
            "volatility": round(hist_vol, 4),
            "adx": round(last_adx, 2),
            "atr_pct": round(avg_atr_pct, 4),
            "rsi": round(rsi, 2),
            "ma_alignment": ma_alignment,
            "volume_ratio": round(vol_ratio, 2),
            "bb_position": round(bb_position, 4),
            "regime": regime_name,
            "dominant_regime": dominant_regime,
        }

        recommendations = []
        regime_alloc = STRATEGY_ALLOCATION.get(current_regime, {})
        regime_strategies = regime_alloc.get("strategies", [])
        regime_weights = regime_alloc.get("weights", [])

        for idx, strategy_cls in enumerate(regime_strategies):
            w = regime_weights[idx] if idx < len(regime_weights) else 0.1
            name = strategy_cls.__name__
            display_name = name
            for alias, cls in STRATEGY_REGISTRY.items():
                if cls == strategy_cls:
                    display_name = alias
                    break

            reasons = []
            if current_regime in (MarketRegime.STRONG_TREND_UP, MarketRegime.MILD_TREND_UP):
                reasons.append(f"当前市场处于{regime_name}，趋势策略表现更优")
            elif current_regime in (MarketRegime.HIGH_VOLATILITY_RANGE, MarketRegime.LOW_VOLATILITY_CONSOLIDATION):
                reasons.append(f"当前市场处于{regime_name}，震荡策略表现更优")
            elif current_regime in (MarketRegime.MILD_TREND_DOWN, MarketRegime.STRONG_TREND_DOWN):
                reasons.append(f"当前市场处于{regime_name}，防御策略表现更优")
            elif current_regime == MarketRegime.BEAR_TRAP:
                reasons.append("检测到空头陷阱，反转策略表现更优")
            elif current_regime == MarketRegime.DISTRIBUTION_TOP:
                reasons.append("检测到派发顶部信号，减仓策略表现更优")

            if last_adx > 30:
                reasons.append(f"ADX={last_adx:.1f}趋势较强")
            elif last_adx < 20:
                reasons.append(f"ADX={last_adx:.1f}趋势较弱，适合均值回归")

            if hist_vol > 0.30:
                reasons.append(f"波动率{hist_vol:.1%}偏高，注意风险控制")
            elif hist_vol < 0.15:
                reasons.append(f"波动率{hist_vol:.1%}偏低，适合布局突破")

            if rsi < 30:
                reasons.append(f"RSI={rsi:.0f}超卖区间")
            elif rsi > 70:
                reasons.append(f"RSI={rsi:.0f}超买区间")

            recommendations.append({
                "strategy": display_name,
                "strategy_class": name,
                "score": round(w, 4),
                "reasons": reasons,
            })

        recommendations.sort(key=lambda x: x["score"], reverse=True)

        adaptive_reason = "当前市场环境复杂，自适应引擎可根据市场状态自动切换策略组合"
        recommendations.insert(0, {
            "strategy": "adaptive",
            "strategy_class": "AdaptiveEngine",
            "score": 1.0,
            "reasons": [adaptive_reason, f"当前市场状态: {regime_name}", f"近期主导状态: {dominant_regime}"],
        })

        return _json_response(True, data={
            "analysis": analysis,
            "recommendations": recommendations[:6],
        })
    except Exception as e:
        logger.error("recommend strategy error: %s", e,  exc_info=True)
        return _json_response(False, error=safe_error(e))


async def _run_single_or_adaptive(strategy_type, symbol, start_date, end_date, initial_capital, df):
    import asyncio

    from core.backtest import run_backtest as run_bt

    if strategy_type == "composite" or strategy_type == "all":
        from core.backtest import BacktestEngine
        from core.strategies import CompositeStrategy
        engine = BacktestEngine(initial_capital=initial_capital)
        strategies = CompositeStrategy().strategies
        import pandas as pd
        work_df = df.copy()
        if "date" in work_df.columns:
            work_df["date"] = pd.to_datetime(work_df["date"], errors="coerce")
            work_df = work_df.dropna(subset=["date"])
            work_df = work_df[(work_df["date"] >= start_date) & (work_df["date"] <= end_date)].reset_index(drop=True)
        results = engine.run_multi(strategies, work_df)
        output = {}
        for name, result in results.items():
            output[name] = _serialize_result(result, initial_capital, df)
        return output

    result = await asyncio.to_thread(
        run_bt,
        symbol,
        strategy_type,
        start_date,
        end_date,
        initial_capital,
        None,
        df,
    )
    return result


def _serialize_result(result, initial_capital, df):
    return result.to_dict(max_equity=500, max_trades=100)


@backtest_router.post("/backtest/export")
async def export_backtest(
    request: Request,
    body: BacktestRunRequest,
    format: str = Query("json", pattern=r"^(json|csv)$"),
):
    try:
        import json as json_lib

        import pandas as pd
        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error=f"无法获取 {body.symbol} 的历史数据")

        result = await _run_single_or_adaptive(
            body.strategy_type, body.symbol, body.start_date,
            body.end_date, body.initial_capital, df,
        )
        if "error" in result:
            return _json_response(False, error=result["error"])

        if format == "csv":
            output = io.StringIO()
            if isinstance(result, dict) and "equity_curve" in result:
                ec = result.get("equity_curve", [])
                if ec:
                    ec_df = pd.DataFrame(ec)
                    ec_df.to_csv(output, index=False)
                trades = result.get("trades", [])
                if trades:
                    output.write("\n--- Trades ---\n")
                    td = pd.DataFrame(trades)
                    td.to_csv(output, index=False)
                summary = {k: v for k, v in result.items() if k not in ("equity_curve", "trades") and not isinstance(v, (list, dict))}
                output.write("\n--- Summary ---\n")
                pd.DataFrame([summary]).to_csv(output, index=False)
            else:
                pd.DataFrame([{"result": str(result)}]).to_csv(output, index=False)
            output.seek(0)
            filename = f"backtest_{body.symbol}_{body.strategy_type}_{body.start_date}_{body.end_date}.csv"
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )

        filename = f"backtest_{body.symbol}_{body.strategy_type}_{body.start_date}_{body.end_date}.json"
        return StreamingResponse(
            iter([json_lib.dumps(result, ensure_ascii=False, default=str)]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.error("backtest export error: %s", e,  exc_info=True)
        return _json_response(False, error=safe_error(e))


@backtest_router.get("/backtest/performance_overview")
async def performance_overview(
    request: Request,
    symbol: str = Query("600000", min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
):
    cache_key = f"{symbol}:{period}"
    now = time.time()
    if cache_key in _perf_overview_cache:
        cached_ts, cached_data = _perf_overview_cache[cache_key]
        if now - cached_ts < _PERF_CACHE_TTL:
            return _json_response(True, data=cached_data)

    try:
        import numpy as np

        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period=period, kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="无法获取历史数据")

        if len(df) < 30:
            return _json_response(False, error="数据不足，至少需要30个交易日")

        seen_classes = {}
        for _name, cls in STRATEGY_REGISTRY.items():
            base_name = cls.__name__
            if base_name not in seen_classes:
                seen_classes[base_name] = cls

        strategy_results = []
        for base_name, cls in seen_classes.items():
            try:
                strategy = cls()
                engine = BacktestEngine()
                result = engine.run(strategy, df)
                if result:
                    sd = result.summary_dict()
                    sd["strategy"] = base_name
                    sd["trade_count"] = sd.pop("total_trades", 0)
                    strategy_results.append(sd)
            except Exception as e:
                logger.debug("策略 %s 回测失败: %s", base_name, e)

        strategy_results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)

        c = df["close"].values.astype(float)
        bh_return = round((c[-1] - c[0]) / c[0], 4) if len(c) > 1 and c[0] > 0 else 0
        returns = np.diff(c) / np.where(c[:-1] > 0, c[:-1], 1)
        returns = np.where(np.isfinite(returns), returns, 0)
        bh_sharpe = round(float(np.mean(returns) / np.std(returns) * np.sqrt(252)), 2) if np.std(returns) > 0 else 0

        best_strategy = strategy_results[0] if strategy_results else None
        avg_return = round(float(np.mean([s["total_return"] for s in strategy_results])), 4) if strategy_results else 0
        avg_sharpe = round(float(np.mean([s["sharpe_ratio"] for s in strategy_results])), 2) if strategy_results else 0

        overview = {
            "symbol": symbol,
            "period": period,
            "data_points": len(df),
            "benchmark": {
                "name": "买入持有",
                "total_return": bh_return,
                "sharpe_ratio": bh_sharpe,
            },
            "best_strategy": best_strategy,
            "average_return": avg_return,
            "average_sharpe": avg_sharpe,
            "strategy_count": len(strategy_results),
            "strategies": strategy_results,
        }

        _perf_overview_cache[cache_key] = (now, overview)

        if len(_perf_overview_cache) > _PERF_CACHE_MAX:
            expired_keys = [k for k, (ts, _) in _perf_overview_cache.items() if now - ts > _PERF_CACHE_TTL]
            for k in expired_keys:
                del _perf_overview_cache[k]
            if len(_perf_overview_cache) > _PERF_CACHE_MAX:
                oldest_key = min(_perf_overview_cache, key=lambda k: _perf_overview_cache[k][0])
                del _perf_overview_cache[oldest_key]

        return _json_response(True, data=overview)
    except Exception as e:
        logger.error("performance overview error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


class StrategyCompareRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")
    strategies: list[str] = Field(..., min_length=2, max_length=10)
    start_date: str = Field("2024-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field("2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$")
    initial_capital: float = 1000000


@backtest_router.post("/backtest/strategy_compare")
async def strategy_compare(request: Request, body: StrategyCompareRequest):
    """多策略深度比较：收益曲线叠加、统计显著性检验、风险指标对比"""
    try:
        from scipy import stats as sp_stats

        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="数据不足")

        import pandas as pd
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df[(df["date"] >= body.start_date) & (df["date"] <= body.end_date)].reset_index(drop=True)

        if len(df) < 30:
            return _json_response(False, error="数据不足，至少需要30个交易日")

        engine = BacktestEngine(initial_capital=body.initial_capital)
        strategy_results = []
        all_equity_returns = {}

        async def _compare_strategy(sname: str) -> tuple[dict | None, str, np.ndarray | None]:
            if sname not in STRATEGY_REGISTRY:
                return None, sname, None
            try:
                strategy = STRATEGY_REGISTRY[sname]()
                result = await asyncio.to_thread(engine.run, strategy, df)
                if result and result.total_trades > 0:
                    sd = result.summary_dict()
                    sd["equity_curve"] = [
                        {"date": result.dates[i], "value": float(result.equity_curve[i])}
                        for i in range(min(len(result.dates), len(result.equity_curve)))
                    ][-200:]
                    rets = None
                    if result.equity_curve and len(result.equity_curve) > 1:
                        eq = np.array(result.equity_curve, dtype=float)
                        rets = np.diff(eq) / np.where(eq[:-1] > 0, eq[:-1], 1)
                        rets = np.where(np.isfinite(rets), rets, 0)
                    return sd, sname, rets
            except Exception as e:
                logger.debug("策略 %s 比较失败: %s", sname, e)
            return None, sname, None

        pairs = await asyncio.gather(*[_compare_strategy(s) for s in body.strategies])
        for sd, sname, rets in pairs:
            if sd is not None:
                strategy_results.append(sd)
                if rets is not None:
                    all_equity_returns[sname] = rets

        if len(strategy_results) < 2:
            return _json_response(False, error="至少需要2个有效策略才能比较")

        strategy_results.sort(key=lambda x: x.get("sharpe_ratio", 0), reverse=True)

        significance_tests = []
        sname_list = list(all_equity_returns.keys())
        for i in range(len(sname_list)):
            for j in range(i + 1, len(sname_list)):
                r1 = all_equity_returns[sname_list[i]]
                r2 = all_equity_returns[sname_list[j]]
                min_len = min(len(r1), len(r2))
                if min_len < 10:
                    continue
                r1_trimmed = r1[-min_len:]
                r2_trimmed = r2[-min_len:]
                diff = r1_trimmed - r2_trimmed
                if np.std(diff) < 1e-12:
                    continue
                t_stat, p_value = sp_stats.ttest_rel(r1_trimmed, r2_trimmed)
                significance_tests.append({
                    "strategy_a": sname_list[i],
                    "strategy_b": sname_list[j],
                    "t_statistic": round(float(t_stat), 4),
                    "p_value": round(float(p_value), 6),
                    "significant_5pct": bool(p_value < 0.05),
                    "mean_diff_annualized": round(float(np.mean(diff) * 252 * 100), 4),
                })

        return _json_response(True, data={
            "symbol": body.symbol,
            "period": f"{body.start_date} ~ {body.end_date}",
            "strategies": strategy_results,
            "significance_tests": significance_tests,
            "best_by_sharpe": strategy_results[0].get("strategy_name") if strategy_results else None,
        })
    except Exception as e:
        logger.error("strategy compare error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


class ParamGridRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")
    strategy: str = Field(..., min_length=1, max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    param_x: str = Field(..., min_length=1, max_length=30)
    param_y: str = Field(..., min_length=1, max_length=30)
    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    grid_size: int = Field(7, ge=3, le=15)
    start_date: str = Field("2024-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field("2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$")
    metric: str = Field("sharpe_ratio", pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")


@backtest_router.post("/backtest/param_grid")
async def param_grid_scan(request: Request, body: ParamGridRequest):
    """二维参数网格扫描，生成热图数据用于前端可视化"""
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY

        if body.strategy not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"未知策略: {body.strategy}")

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="数据不足")

        import pandas as pd
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df[(df["date"] >= body.start_date) & (df["date"] <= body.end_date)].reset_index(drop=True)

        if len(df) < 30:
            return _json_response(False, error="数据不足，至少需要30个交易日")

        strategy_cls = STRATEGY_REGISTRY[body.strategy]
        engine = BacktestEngine(initial_capital=1000000)

        x_range = (body.x_min, body.x_max) if body.x_min is not None and body.x_max is not None else None
        y_range = (body.y_min, body.y_max) if body.y_min is not None and body.y_max is not None else None

        result = await asyncio.to_thread(
            engine.parameter_grid_scan,
            strategy_cls, df, body.param_x, body.param_y,
            x_range, y_range, body.grid_size, {}, body.metric,
        )

        return _json_response(True, data=result)
    except Exception as e:
        logger.error("param grid scan error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


class ParamSensitivityRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")
    strategy: str = Field(..., min_length=1, max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    param_name: str = Field(..., min_length=1, max_length=30)
    p_min: float | None = None
    p_max: float | None = None
    num_points: int = Field(11, ge=3, le=31)
    start_date: str = Field("2024-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field("2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$")


@backtest_router.post("/backtest/param_sensitivity")
async def param_sensitivity_analysis(request: Request, body: ParamSensitivityRequest):
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY

        if body.strategy not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"未知策略: {body.strategy}")

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="数据不足")

        import pandas as pd
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df[(df["date"] >= body.start_date) & (df["date"] <= body.end_date)].reset_index(drop=True)

        if len(df) < 30:
            return _json_response(False, error="数据不足，至少需要30个交易日")

        strategy_cls = STRATEGY_REGISTRY[body.strategy]
        engine = BacktestEngine(initial_capital=1000000)

        p_range = (body.p_min, body.p_max) if body.p_min is not None and body.p_max is not None else None

        result = await asyncio.to_thread(
            engine.parameter_sensitivity,
            strategy_cls, df, body.param_name,
            p_range, body.num_points,
        )

        return _json_response(True, data=result)
    except Exception as e:
        logger.error("param sensitivity error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


class EfficientFrontierRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=2, max_length=20)
    period: int = Field(120, ge=60, le=500)
    n_points: int = Field(20, ge=5, le=50)


@backtest_router.post("/portfolio/efficient_frontier")
async def compute_efficient_frontier(request: Request, body: EfficientFrontierRequest):
    try:
        from core.portfolio_optimizer import PortfolioOptimizer

        fetcher = request.app.state.fetcher
        returns_list = []
        valid_symbols = []

        async def _fetch_returns(sym: str) -> tuple[str, np.ndarray | None]:
            try:
                df = await fetcher.get_history(sym, period="all", kline_type="daily", adjust="qfq")
                if df is None or len(df) < body.period:
                    return sym, None
                df = df.tail(body.period)
                if "close" not in df.columns:
                    return sym, None
                closes = df["close"].values.astype(float)
                rets = np.diff(closes) / np.where(closes[:-1] > 0, closes[:-1], 1)
                rets = np.where(np.isfinite(rets), rets, 0)
                return sym, rets
            except Exception as e:
                logger.debug("Return calc failed for %s: %s", sym, e)
                return sym, None

        pairs = await asyncio.gather(*[_fetch_returns(s) for s in body.symbols])
        for sym, rets in pairs:
            if rets is not None:
                valid_symbols.append(sym)
                returns_list.append(rets)

        if len(valid_symbols) < 2:
            return _json_response(False, error="至少需要2个有效股票代码")

        min_len = min(len(r) for r in returns_list)
        aligned = np.column_stack([r[-min_len:] for r in returns_list])

        expected_returns = np.mean(aligned, axis=0)
        cov_matrix = np.cov(aligned, rowvar=False)

        optimizer = PortfolioOptimizer()
        frontier = await asyncio.to_thread(
            optimizer.efficient_frontier, expected_returns, cov_matrix, body.n_points,
        )

        return _json_response(True, data={
            "symbols": valid_symbols,
            "frontier": frontier,
            "n_points": len(frontier),
        })
    except Exception as e:
        logger.error("efficient frontier error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


class WalkForwardOOSRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")
    strategy: str = Field(..., min_length=1, max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    train_days: int = Field(252, ge=60, le=504)
    test_days: int = Field(63, ge=20, le=126)
    start_date: str = Field("2023-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field("2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$")
    param_grid: dict | None = None


@backtest_router.post("/backtest/walk_forward_oos")
async def walk_forward_oos(request: Request, body: WalkForwardOOSRequest):
    """Walk-Forward Out-of-Sample验证：过拟合检测、参数稳定性分析"""
    try:
        from core.backtest import walk_forward_oos_validation
        from core.strategies import STRATEGY_REGISTRY

        if body.strategy not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"未知策略: {body.strategy}")

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="数据不足")

        import pandas as pd
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df[(df["date"] >= body.start_date) & (df["date"] <= body.end_date)].reset_index(drop=True)

        if len(df) < body.train_days + body.test_days:
            return _json_response(False, error=f"数据不足：至少需要{body.train_days + body.test_days}个交易日")

        strategy_cls = STRATEGY_REGISTRY[body.strategy]

        result = await asyncio.to_thread(
            walk_forward_oos_validation,
            strategy_cls, df, body.train_days, body.test_days,
            1000000, body.param_grid,
        )

        return _json_response(True, data=result)
    except Exception as e:
        logger.error("walk forward OOS error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


class SignalQualityRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")
    strategy: str = Field(..., min_length=1, max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    period: str = Field("1y", max_length=10)
    forward_period: int = Field(5, ge=1, le=30)
    min_return_threshold: float = Field(0.005, ge=0, le=0.1)


@backtest_router.post("/backtest/signal_quality")
async def signal_quality(request: Request, body: SignalQualityRequest):
    try:
        from core.signal_quality import evaluate_signal_quality
        from core.strategies import STRATEGY_REGISTRY

        if body.strategy not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"未知策略: {body.strategy}")

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, period=body.period, kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="数据不足")

        strategy_cls = STRATEGY_REGISTRY[body.strategy]
        strategy = strategy_cls()

        report = await asyncio.to_thread(
            evaluate_signal_quality,
            strategy, df, body.symbol,
            body.forward_period, body.min_return_threshold,
        )

        return _json_response(True, data=report.to_dict())
    except Exception as e:
        logger.error("signal quality error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


class WalkForwardAnalysisRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")
    strategy: str = Field(..., min_length=1, max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    train_period: int = Field(252, ge=60, le=504)
    test_period: int = Field(63, ge=20, le=126)
    n_splits: int = Field(5, ge=2, le=20)
    initial_capital: float = Field(100000, ge=10000, le=1e9)
    start_date: str = Field("2023-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field("2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$")


@backtest_router.post("/backtest/walk_forward_analysis")
async def walk_forward_analysis_endpoint(request: Request, body: WalkForwardAnalysisRequest):
    try:
        from core.strategies import STRATEGY_REGISTRY
        from core.walk_forward import walk_forward_analysis

        if body.strategy not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"未知策略: {body.strategy}")

        fetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="数据不足")

        import pandas as pd
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df[(df["date"] >= body.start_date) & (df["date"] <= body.end_date)].reset_index(drop=True)

        strategy_cls = STRATEGY_REGISTRY[body.strategy]
        strategy = strategy_cls()

        result = await asyncio.to_thread(
            walk_forward_analysis,
            strategy, df, body.symbol,
            body.train_period, body.test_period,
            body.n_splits, body.initial_capital,
        )

        return _json_response(True, data=result.to_dict())
    except Exception as e:
        logger.error("walk forward analysis error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


_optimization_tasks: dict[str, dict] = {}


class AutoOptimizeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")
    strategy_name: str = Field(..., min_length=1, max_length=30, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    start_date: str = Field("2022-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field("2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$")
    metric: str = Field("sharpe_ratio", pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    max_iterations: int = Field(50, ge=5, le=200)


@backtest_router.post("/backtest/auto_optimize")
async def auto_optimize(
    request: Request,
    body: AutoOptimizeRequest,
    background_tasks: BackgroundTasks,
):
    try:
        from core.strategies import STRATEGY_REGISTRY

        if body.strategy_name not in STRATEGY_REGISTRY:
            return _json_response(False, error=f"未知策略: {body.strategy_name}")

        task_id = uuid.uuid4().hex[:16]
        _optimization_tasks[task_id] = {"status": "pending", "progress": 0, "result": None, "error": None}

        async def _run_optimization() -> None:
            _optimization_tasks[task_id]["status"] = "running"
            try:
                from core.backtest import BatchStrategyRunner

                strategy_cls = STRATEGY_REGISTRY[body.strategy_name]
                runner = BatchStrategyRunner()
                fetcher = request.app.state.fetcher
                df = await fetcher.get_history(body.symbol, period="all", kline_type="daily", adjust="qfq")
                if df is None or df.empty:
                    _optimization_tasks[task_id].update({"status": "error", "error": "无法获取数据"})
                    return

                import pandas as pd
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"], errors="coerce")
                    df = df.dropna(subset=["date"])
                    df = df[(df["date"] >= body.start_date) & (df["date"] <= body.end_date)].reset_index(drop=True)

                if len(df) < 30:
                    _optimization_tasks[task_id].update({"status": "error", "error": "数据不足"})
                    return

                result = await asyncio.to_thread(
                    runner.auto_optimize,
                    [strategy_cls], df, None, body.max_iterations, body.metric,
                )
                _optimization_tasks[task_id].update({"status": "completed", "progress": 100, "result": result})
            except Exception as e:
                logger.error("Auto-optimize task %s failed: %s", task_id, e, exc_info=True)
                _optimization_tasks[task_id].update({"status": "error", "error": str(e)})

        background_tasks.add_task(_run_optimization)
        return _json_response(True, data={
            "task_id": task_id,
            "message": "优化任务已启动，通过 GET /backtest/auto_optimize/{task_id} 查询进度",
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@backtest_router.get("/backtest/auto_optimize/{task_id}")
async def get_optimization_status(task_id: str):
    task_info = _optimization_tasks.get(task_id)
    if not task_info:
        return _json_response(False, error="任务不存在")
    return _json_response(True, data=task_info)


@backtest_router.post("/backtest/result/save")
async def save_backtest_result(request: Request):
    try:
        from core.backtest import BacktestResultStore

        body = await request.json()
        symbol = body.get("symbol", "")
        strategy_name = body.get("strategy_name", "")
        params = body.get("params", {})
        result_data = body.get("result", {})

        if not symbol or not strategy_name:
            return _json_response(False, error="缺少 symbol 或 strategy_name")

        from core.backtest.result import BacktestResult
        result = BacktestResult(strategy_name=strategy_name)
        for key in ("total_return", "annual_return", "sharpe_ratio", "max_drawdown",
                     "calmar_ratio", "win_rate", "profit_factor", "total_trades",
                     "win_trades", "loss_trades", "avg_profit", "avg_loss",
                     "avg_hold_days", "benchmark_return", "alpha", "beta"):
            if key in result_data:
                setattr(result, key, result_data[key])

        store = BacktestResultStore()
        result_id = store.save(result, symbol, strategy_name, params)
        return _json_response(True, data={"result_id": result_id})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@backtest_router.get("/backtest/result/history")
async def get_backtest_history(
    symbol: str = Query("", max_length=20),
    limit: int = Query(20, ge=1, le=100),
):
    try:
        from core.backtest import BacktestResultStore
        store = BacktestResultStore()
        history = store.get_history(symbol=symbol, limit=limit)
        return _json_response(True, data=history)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@backtest_router.post("/backtest/result/compare")
async def compare_saved_results(request: Request):
    try:
        body = await request.json()
        result_ids = body.get("result_ids", [])
        if len(result_ids) < 2:
            return _json_response(False, error="至少需要2个结果ID进行对比")

        from core.backtest import BacktestResultStore
        store = BacktestResultStore()
        comparison = store.compare(result_ids)
        return _json_response(True, data=comparison)
    except Exception as e:
        return _json_response(False, error=safe_error(e))
