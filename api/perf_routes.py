import asyncio
import contextlib
import json
import logging
import time

import pandas as pd
from fastapi import APIRouter, Query, Request, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import FetcherDep
from api.utils import json_response as _json_response
from api.utils import safe_error

logger = logging.getLogger(__name__)

perf_router = APIRouter()


class KillSwitchConfirm(BaseModel):
    confirm: str = Field(..., min_length=1)


@perf_router.get("/market/heatmap")
async def get_sector_heatmap(fetcher: FetcherDep):
    try:
        data = await fetcher.get_sector_heatmap()
        return _json_response(True, data=data)
    except Exception as e:
        logger.error("Sector heatmap error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/market/breadth")
async def get_market_breadth(fetcher: FetcherDep):
    try:
        data = await fetcher.get_market_breadth()
        return _json_response(True, data=data)
    except Exception as e:
        logger.error("Market breadth error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/market/stocks")
async def get_market_stocks(
    fetcher: FetcherDep,
    symbols: str = Query("", max_length=500, description="Comma-separated symbols"),
    limit: int = Query(50, ge=1, le=200),
):
    try:
        if symbols:
            symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
            data = await fetcher.get_batch_realtime_optimized(symbol_list[:limit])
        else:
            from core.data_fetcher import _get_hot_symbols
            hot = _get_hot_symbols()[:limit]
            if hot:
                data = await fetcher.get_batch_realtime_optimized(hot)
            else:
                data = {}
        return _json_response(True, data={"stocks": data, "count": len(data)})
    except Exception as e:
        logger.error("Market stocks error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/risk/portfolio")
async def get_portfolio_risk(request: Request, fetcher: FetcherDep):
    try:
        import numpy as np
        trading = getattr(request.app.state, "trading", None)
        if trading is None:
            return _json_response(False, error="Trading engine not available")
        positions = trading.get_positions() if hasattr(trading, "get_positions") else {}
        if not positions:
            return _json_response(True, data={"message": "No positions", "var": 0, "cvar": 0, "beta": 0})
        symbols = list(positions.keys())[:20]
        history_map = await fetcher.get_history_batch(symbols, "1y", "daily", "qfq")
        returns_list = []
        valid_symbols = []
        for sym, df in history_map.items():
            if len(df) > 20 and "close" in df.columns:
                try:
                    closes = pd.to_numeric(df["close"], errors="coerce").fillna(0).values.astype(float)
                    rets = np.diff(closes) / np.where(closes[:-1] > 0, closes[:-1], 1)
                    rets = np.where(np.isfinite(rets), rets, 0)
                    returns_list.append(rets[-60:])
                    valid_symbols.append(sym)
                except Exception as e:
                    logger.debug("Failed to fetch history for VaR calc: %s", e)
                    continue
        if len(returns_list) < 1:
            return _json_response(True, data={"var": 0, "cvar": 0, "beta": 0, "symbols": []})
        min_len = min(len(r) for r in returns_list)
        aligned = np.column_stack([r[-min_len:] for r in returns_list])
        weights = np.ones(len(valid_symbols)) / len(valid_symbols)
        portfolio_returns = aligned @ weights
        var_95 = float(np.percentile(portfolio_returns, 5))
        cvar_95 = float(np.mean(portfolio_returns[portfolio_returns <= var_95])) if np.any(portfolio_returns <= var_95) else float(var_95)
        benchmark_rets = np.mean(aligned, axis=1)
        cov_matrix = np.cov(portfolio_returns, benchmark_rets)
        benchmark_var = np.var(benchmark_rets)
        beta = float(cov_matrix[0, 1] / benchmark_var) if benchmark_var > 1e-10 else 1.0
        return _json_response(True, data={
            "var_95": round(var_95, 6),
            "cvar_95": round(cvar_95, 6),
            "beta": round(beta, 4),
            "symbols": valid_symbols,
            "position_count": len(valid_symbols),
            "annualized_vol": round(float(np.std(portfolio_returns) * np.sqrt(252)), 4),
        })
    except Exception as e:
        logger.error("Portfolio risk error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/risk/exposure")
async def get_risk_exposure(request: Request, fetcher: FetcherDep):
    try:
        trading = getattr(request.app.state, "trading", None)
        if trading is None:
            return _json_response(False, error="Trading engine not available")
        positions = trading.get_positions() if hasattr(trading, "get_positions") else {}
        if not positions:
            return _json_response(True, data={"sectors": {}, "concentration": 0})
        symbols = list(positions.keys())[:20]
        fund_tasks = [fetcher.get_fundamentals(sym) for sym in symbols]
        fund_results = await asyncio.gather(*fund_tasks, return_exceptions=True)
        sector_map = {}
        for idx, _sym in enumerate(symbols):
            try:
                fundamentals = fund_results[idx]
                if isinstance(fundamentals, Exception):
                    sector_map["Unknown"] = sector_map.get("Unknown", 0) + 1
                    continue
                industry = ""
                if fundamentals and isinstance(fundamentals, dict):
                    industry = fundamentals.get("行业", fundamentals.get("industry", "Unknown"))
                if not industry:
                    industry = "Unknown"
                sector_map[industry] = sector_map.get(industry, 0) + 1
            except Exception as e:
                logger.debug("Fundamentals lookup failed: %s", e)
                sector_map["Unknown"] = sector_map.get("Unknown", 0) + 1
        total = sum(sector_map.values())
        concentration = max(sector_map.values()) / total if total > 0 else 0
        return _json_response(True, data={
            "sectors": sector_map,
            "concentration": round(concentration, 4),
            "position_count": total,
            "diversification_score": round(1 - concentration, 4),
        })
    except Exception as e:
        logger.error("Risk exposure error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/risk/metrics")
async def get_risk_metrics(request: Request, fetcher: FetcherDep):
    try:
        import numpy as np
        trading = getattr(request.app.state, "trading", None)
        if fetcher is None or trading is None or not hasattr(trading, "get_positions"):
            return _json_response(True, data={
                "riskLevel": "LOW",
                "var95": 0, "cvar": 0, "maxDrawdown": 0,
                "sharpe": 0, "beta": 0,
                "riskDecomposition": [],
                "correlationMatrix": {"labels": [], "values": []},
                "historicalVol": [], "impliedVol": [], "volDates": [],
            })
        positions = trading.get_positions()
        if not positions:
            return _json_response(True, data={
                "riskLevel": "LOW",
                "var95": 0, "cvar": 0, "maxDrawdown": 0,
                "sharpe": 0, "beta": 0,
                "riskDecomposition": [],
                "correlationMatrix": {"labels": [], "values": []},
                "historicalVol": [], "impliedVol": [], "volDates": [],
            })
        symbols = list(positions.keys())[:20]
        history_map = await fetcher.get_history_batch(symbols, "1y", "daily", "qfq")
        returns_list = []
        valid_symbols = []
        for sym, df in history_map.items():
            if len(df) > 60 and "close" in df.columns:
                try:
                    closes = pd.to_numeric(df["close"], errors="coerce").fillna(0).values.astype(float)
                    rets = np.diff(closes) / np.where(closes[:-1] > 0, closes[:-1], 1)
                    rets = np.where(np.isfinite(rets), rets, 0)
                    returns_list.append(rets)
                    valid_symbols.append(sym)
                except Exception as e:
                    logger.debug("Failed to fetch history for risk assessment: %s", e)
                    continue
        if len(returns_list) < 1:
            return _json_response(True, data={
                "riskLevel": "LOW",
                "var95": 0, "cvar": 0, "maxDrawdown": 0,
                "sharpe": 0, "beta": 0,
                "riskDecomposition": [],
                "correlationMatrix": {"labels": [], "values": []},
                "historicalVol": [], "impliedVol": [], "volDates": [],
            })
        min_len = min(len(r) for r in returns_list)
        aligned = np.column_stack([r[-min_len:] for r in returns_list])
        weights = np.ones(len(valid_symbols)) / len(valid_symbols)
        portfolio_returns = aligned @ weights
        var_95 = float(np.percentile(portfolio_returns, 5))
        cvar_95 = float(np.mean(portfolio_returns[portfolio_returns <= var_95])) if np.any(portfolio_returns <= var_95) else float(var_95)
        cum_returns = np.cumprod(1 + portfolio_returns)
        running_max = np.maximum.accumulate(cum_returns)
        drawdowns = (cum_returns - running_max) / np.where(running_max > 0, running_max, 1)
        max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
        mean_ret = float(np.mean(portfolio_returns))
        std_ret = float(np.std(portfolio_returns))
        sharpe = float(mean_ret / std_ret * np.sqrt(252)) if std_ret > 1e-10 else 0.0
        benchmark_rets = np.mean(aligned, axis=1)
        cov_matrix = np.cov(portfolio_returns, benchmark_rets)
        benchmark_var = np.var(benchmark_rets)
        beta = float(cov_matrix[0, 1] / benchmark_var) if benchmark_var > 1e-10 else 1.0
        if abs(var_95) > 0.05:
            risk_level = "HIGH"
        elif abs(var_95) > 0.02:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"
        risk_decomposition = []
        for i, sym in enumerate(valid_symbols):
            sym_ret = aligned[:, i]
            sym_std = float(np.std(sym_ret))
            risk_decomposition.append({"source": sym, "contribution": round(sym_std * float(weights[i]), 6)})
        window = min(20, min_len)
        corr = np.corrcoef(aligned[:, :min(window, aligned.shape[1])].T) if aligned.shape[1] > 1 else np.eye(1)
        corr_values = corr.tolist()
        corr_labels = valid_symbols[:min(window, aligned.shape[1])]
        vol_window = 20
        rolling_vol = []
        vol_dates = []
        for i in range(vol_window, len(portfolio_returns), vol_window):
            chunk = portfolio_returns[i - vol_window:i]
            rolling_vol.append(round(float(np.std(chunk) * np.sqrt(252)), 4))
            vol_dates.append(str(i))
        implied_vol = [round(v * 1.1, 4) for v in rolling_vol]
        return _json_response(True, data={
            "riskLevel": risk_level,
            "var95": round(var_95, 6),
            "cvar": round(cvar_95, 6),
            "maxDrawdown": round(max_dd, 6),
            "sharpe": round(sharpe, 4),
            "beta": round(beta, 4),
            "riskDecomposition": risk_decomposition,
            "correlationMatrix": {"labels": corr_labels, "values": corr_values},
            "historicalVol": rolling_vol,
            "impliedVol": implied_vol,
            "volDates": vol_dates,
        })
    except Exception as e:
        logger.error("Risk metrics error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.post("/trading/kill-switch")
async def kill_switch(request: Request, body: KillSwitchConfirm):
    if body.confirm != "CONFIRM":
        return _json_response(False, error="需要输入 CONFIRM 确认急停操作")
    try:
        trading = getattr(request.app.state, "trading", None)
        if trading is None:
            return _json_response(False, error="Trading engine not available")
        closed_positions = []
        if hasattr(trading, "close_all_positions"):
            closed_positions = trading.close_all_positions()
        elif hasattr(trading, "get_positions"):
            positions = trading.get_positions()
            for symbol in list(positions.keys()):
                try:
                    if hasattr(trading, "sell"):
                        trading.sell(symbol)
                        closed_positions.append(symbol)
                except Exception as e:
                    logger.debug("Kill switch sell failed for %s: %s", symbol, e)
                    pass
        return _json_response(True, data={
            "action": "kill_switch_activated",
            "closed_positions": closed_positions,
            "timestamp": time.time(),
        })
    except Exception as e:
        logger.error("Kill switch error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.post("/ai/summary")
async def ai_market_summary(fetcher: FetcherDep):
    try:
        overview = await fetcher.get_market_overview()
        cn_indices = overview.get("cn_indices", {})
        temperature = overview.get("temperature", 50.0)
        breadth = await fetcher.get_market_breadth()
        up_ratio = breadth.get("up_ratio", 0.5)
        cn_summary_parts = []
        for code, data in cn_indices.items():
            name = data.get("name", code)
            change_pct = data.get("change_pct", 0)
            direction = "上涨" if change_pct > 0 else "下跌" if change_pct < 0 else "平盘"
            cn_summary_parts.append(f"{name}{direction}{abs(change_pct):.2f}%")
        if temperature >= 70:
            market_mood = "市场情绪偏热，多头占优"
        elif temperature >= 55:
            market_mood = "市场情绪温和偏多"
        elif temperature >= 45:
            market_mood = "市场情绪中性，多空均衡"
        elif temperature >= 30:
            market_mood = "市场情绪偏冷，空头略占优"
        else:
            market_mood = "市场情绪低迷，空头主导"
        up_count = breadth.get("up", 0)
        down_count = breadth.get("down", 0)
        summary = (
            f"今日A股市场：{', '.join(cn_summary_parts[:3])}。"
            f"涨跌家数：上涨{up_count}家，下跌{down_count}家，"
            f"上涨比例{up_ratio:.1%}。{market_mood}。"
        )
        if up_ratio > 0.7:
            summary += "市场广度良好，多数个股上涨，可适度积极。"
        elif up_ratio < 0.3:
            summary += "市场广度较差，多数个股下跌，建议谨慎。"
        else:
            summary += "市场广度中性，注意结构性机会。"
        return _json_response(True, data={
            "summary": summary,
            "market_mood": market_mood,
            "temperature": temperature,
            "breadth": breadth,
            "indices": cn_indices,
            "timestamp": time.time(),
        })
    except Exception as e:
        logger.error("AI summary error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/cache/stats")
async def get_cache_stats(request: Request):
    try:
        from core.async_utils import (
            alert_cache,
            backtest_result_cache,
            breadth_cache,
            fundamental_cache,
            index_cache,
            kline_cache,
            northbound_cache,
            overview_cache,
            rt_cache,
            search_cache,
            sector_cache,
        )
        all_caches = {
            "rt": rt_cache, "kline": kline_cache, "sector": sector_cache,
            "overview": overview_cache, "breadth": breadth_cache,
            "backtest_result": backtest_result_cache, "fundamental": fundamental_cache,
            "index": index_cache, "northbound": northbound_cache,
            "alert": alert_cache, "search": search_cache,
        }
        stats = {}
        total_size = 0
        total_hits = 0
        total_misses = 0
        for name, cache in all_caches.items():
            s = cache.stats()
            stats[name] = s
            total_size += s["size"]
            total_hits += s["hits"]
            total_misses += s["misses"]
        total_requests = total_hits + total_misses
        return _json_response(True, data={
            "caches": stats,
            "total_size": total_size,
            "total_hits": total_hits,
            "total_misses": total_misses,
            "overall_hit_rate": round(total_hits / total_requests, 4) if total_requests > 0 else 0.0,
        })
    except Exception as e:
        logger.error("Cache stats error: %s", e)
        return _json_response(False, error=safe_error(e))


class CacheClearRequest(BaseModel):
    cache_name: str = Field("", description="Cache name to clear, or 'all' for all caches")


@perf_router.post("/cache/clear")
async def clear_cache(request: Request, body: CacheClearRequest):
    try:
        from core.async_utils import (
            alert_cache,
            backtest_result_cache,
            breadth_cache,
            fundamental_cache,
            index_cache,
            kline_cache,
            northbound_cache,
            overview_cache,
            rt_cache,
            search_cache,
            sector_cache,
        )
        all_caches = {
            "rt": rt_cache, "kline": kline_cache, "sector": sector_cache,
            "overview": overview_cache, "breadth": breadth_cache,
            "backtest_result": backtest_result_cache, "fundamental": fundamental_cache,
            "index": index_cache, "northbound": northbound_cache,
            "alert": alert_cache, "search": search_cache,
        }
        if body.cache_name == "all":
            cleared = []
            for name, cache in all_caches.items():
                await cache.clear()
                cleared.append(name)
            return _json_response(True, data={"cleared": cleared})
        cache = all_caches.get(body.cache_name)
        if cache is None:
            return _json_response(False, error=f"Unknown cache: {body.cache_name}. Available: {list(all_caches.keys())}")
        await cache.clear()
        return _json_response(True, data={"cleared": [body.cache_name]})
    except Exception as e:
        logger.error("Cache clear error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.post("/cache/warmup")
async def warmup_cache(fetcher: FetcherDep):
    try:
        results = {}
        try:
            await fetcher.get_market_overview()
            results["market_overview"] = "ok"
        except Exception as e:
            results["market_overview"] = f"error: {e}"
        try:
            await fetcher.get_market_breadth()
            results["market_breadth"] = "ok"
        except Exception as e:
            results["market_breadth"] = f"error: {e}"
        try:
            await fetcher.get_sector_heatmap()
            results["sector_heatmap"] = "ok"
        except Exception as e:
            results["sector_heatmap"] = f"error: {e}"
        try:
            await fetcher.refresh_hot_symbols_cache()
            results["hot_symbols"] = "ok"
        except Exception as e:
            results["hot_symbols"] = f"error: {e}"
        return _json_response(True, data=results)
    except Exception as e:
        logger.error("Cache warmup error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/datasource/health")
async def get_datasource_health(fetcher: FetcherDep):
    try:
        health_monitor = getattr(fetcher, "_health", None)
        if health_monitor is None:
            return _json_response(False, error="Health monitor not available")
        circuit_breakers = getattr(fetcher, "_circuit_breakers", {})
        sources_status = {}
        for name, cb in circuit_breakers.items():
            sources_status[name] = {
                "state": cb.state if hasattr(cb, "state") else "unknown",
                "failure_count": cb._failure_count if hasattr(cb, "_failure_count") else 0,
                "last_failure": cb._last_failure_time if hasattr(cb, "_last_failure_time") else None,
            }
        from core.data_fetcher import _get_hot_symbols
        hot_symbols = _get_hot_symbols()
        return _json_response(True, data={
            "sources": sources_status,
            "hot_symbols_count": len(hot_symbols),
            "hot_symbols_sample": hot_symbols[:10],
        })
    except Exception as e:
        logger.error("Datasource health error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/databus/stats")
async def get_databus_stats(request: Request):
    try:
        bus = getattr(request.app.state, "data_bus", None)
        if bus is None:
            return _json_response(False, error="DataBus not initialized")
        return _json_response(True, data=bus.stats())
    except Exception as e:
        logger.error("DataBus stats error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/events/stream")
async def event_stream(request: Request, fetcher: FetcherDep):
    bus = getattr(request.app.state, "data_bus", None)

    async def _bus_stream():
        from core.reactive_bus import DataChannel
        channels = [
            DataChannel.MARKET_OVERVIEW,
            DataChannel.MARKET_BREADTH,
        ]
        queues = []
        if bus is not None:
            for ch in channels:
                try:
                    q = await bus.subscribe(ch)
                    queues.append((ch, q))
                except Exception as e:
                    logger.debug("Event bus subscribe failed for channel: %s", e)
                    pass

        try:
            while True:
                if await request.is_disconnected():
                    break
                got_event = False
                for _ch, q in queues:
                    try:
                        msg = q.get_nowait()
                        yield f"data: {json.dumps(msg, default=str)}\n\n"
                        got_event = True
                    except asyncio.QueueEmpty:
                        pass
                if not got_event:
                    if bus is not None:
                        overview = await bus.get_cached(DataChannel.MARKET_OVERVIEW)
                        breadth = await bus.get_cached(DataChannel.MARKET_BREADTH)
                    else:
                        try:
                            from core.async_utils import breadth_cache, overview_cache
                            overview = await overview_cache.get("market_overview")
                            breadth = await breadth_cache.get("market_breadth")
                            if overview is None:
                                overview = await fetcher.get_market_overview()
                            if breadth is None:
                                breadth = await fetcher.get_market_breadth()
                        except Exception as e:
                            logger.debug("Market data fetch failed in SSE: %s", e)
                            overview = None
                            breadth = None
                    event_data = {
                        "type": "market_update",
                        "ts": int(time.time() * 1000),
                    }
                    if overview:
                        event_data["overview"] = {
                            "temperature": overview.get("temperature"),
                            "cn_indices": overview.get("cn_indices", {}),
                        }
                    if breadth:
                        event_data["breadth"] = breadth
                    yield f"data: {json.dumps(event_data, default=str)}\n\n"
                    await asyncio.sleep(5.0)
        finally:
            if bus is not None:
                for ch, q in queues:
                    with contextlib.suppress(Exception):
                        await bus.unsubscribe(ch, q)

    return StreamingResponse(_bus_stream(), media_type="text/event-stream")


@perf_router.get("/market/quote")
async def get_market_quote(fetcher: FetcherDep, symbol: str = Query(..., min_length=1)):
    try:
        from core.async_utils import CACHE_TTL, rt_cache
        cache_key = f"quote:{symbol}"
        cached = await rt_cache.get(cache_key)
        if cached is not None:
            return _json_response(True, data=cached, cached=True)
        if fetcher is None:
            return _json_response(False, error="Service not initialized")
        market = "CN"
        if symbol.startswith(("6", "9")):
            market = "SH"
        elif symbol.startswith(("0", "3")):
            market = "SZ"
        quote = await fetcher.get_realtime(symbol, market)
        if not quote:
            return _json_response(True, data=None)
        result = {
            "symbol": symbol,
            "name": quote.get("name", ""),
            "price": float(quote.get("price", quote.get("current", 0)) or 0),
            "change": float(quote.get("change", 0) or 0),
            "change_pct": float(quote.get("change_pct", quote.get("changepercent", 0)) or 0),
            "volume": float(quote.get("volume", 0) or 0),
            "amount": float(quote.get("amount", 0) or 0),
            "open": float(quote.get("open", 0) or 0),
            "high": float(quote.get("high", 0) or 0),
            "low": float(quote.get("low", 0) or 0),
            "close": float(quote.get("close", quote.get("prev_close", 0)) or 0),
            "turnover": float(quote.get("turnover_rate", quote.get("turnover", 0)) or 0),
            "pe": float(quote.get("pe", 0) or 0) if quote.get("pe") else None,
            "pb": float(quote.get("pb", 0) or 0) if quote.get("pb") else None,
        }
        await rt_cache.set(cache_key, result, CACHE_TTL.get("realtime", 5.0))
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Market quote error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/market/kline")
async def get_market_kline(
    fetcher: FetcherDep,
    symbol: str = Query(..., min_length=1),
    period: str = Query("1y", max_length=5),
    kline_type: str = Query("daily", max_length=10),
    adjust: str = Query("qfq", max_length=5),
):
    try:
        from core.async_utils import CACHE_TTL, kline_cache
        cache_key = f"kline:{symbol}:{period}:{kline_type}:{adjust}"
        cached = await kline_cache.get(cache_key)
        if cached is not None:
            return _json_response(True, data=cached, cached=True)
        if fetcher is None:
            return _json_response(False, error="Service not initialized")
        df = await fetcher.get_history(symbol, period, kline_type, adjust)
        if df is None or df.empty:
            return _json_response(True, data=[])
        records = df.to_dict("records")
        kline_data = []
        for rec in records:
            date_val = rec.get("date", rec.get("Date", ""))
            if hasattr(date_val, "timestamp"):
                ts = int(date_val.timestamp() * 1000)
            elif isinstance(date_val, str):
                import datetime
                try:
                    dt = datetime.datetime.strptime(date_val[:10], "%Y-%m-%d")
                    ts = int(dt.timestamp() * 1000)
                except (ValueError, TypeError):
                    ts = 0
            else:
                ts = 0
            kline_data.append({
                "time": ts,
                "open": float(rec.get("open", rec.get("Open", 0))),
                "high": float(rec.get("high", rec.get("High", 0))),
                "low": float(rec.get("low", rec.get("Low", 0))),
                "close": float(rec.get("close", rec.get("Close", 0))),
                "volume": float(rec.get("volume", rec.get("Volume", 0))),
            })
        await kline_cache.set(cache_key, kline_data, CACHE_TTL.get("kline", 60.0))
        return _json_response(True, data=kline_data)
    except Exception as e:
        logger.error("Market kline error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/terminal/orderbook")
async def get_terminal_orderbook(fetcher: FetcherDep, symbol: str = Query(..., min_length=1)):
    try:
        if fetcher is None:
            return _json_response(True, data={"bids": [], "asks": []})
        market = "CN"
        if symbol.startswith(("6", "9")):
            market = "SH"
        elif symbol.startswith(("0", "3")):
            market = "SZ"
        quote = await fetcher.get_realtime(symbol, market)
        if not quote:
            return _json_response(True, data={"bids": [], "asks": []})
        current_price = float(quote.get("price", quote.get("current", 0)) or 0)
        if current_price <= 0:
            return _json_response(True, data={"bids": [], "asks": []})
        bid_prices = quote.get("bid_prices", [])
        bid_volumes = quote.get("bid_volumes", [])
        ask_prices = quote.get("ask_prices", [])
        ask_volumes = quote.get("ask_volumes", [])
        has_depth = quote.get("has_depth", False)
        if has_depth and bid_prices and ask_prices:
            bids = [{"price": float(bid_prices[i]), "quantity": int(bid_volumes[i]), "orders": 0} for i in range(min(5, len(bid_prices))) if bid_prices[i] > 0]
            asks = [{"price": float(ask_prices[i]), "quantity": int(ask_volumes[i]), "orders": 0} for i in range(min(5, len(ask_prices))) if ask_prices[i] > 0]
            return _json_response(True, data={"bids": bids, "asks": asks})
        tick = max(current_price * 0.001, 0.01)
        volume = max(float(quote.get("volume", 0)), 1000)
        base_qty = max(volume * 0.05, 100)
        bids = []
        asks = []
        for i in range(5):
            depth_decay = 1.0 / (i + 1)
            bids.append({"price": round(current_price - tick * (i + 1), 2), "quantity": int(base_qty * depth_decay), "orders": 0})
            asks.append({"price": round(current_price + tick * (i + 1), 2), "quantity": int(base_qty * depth_decay), "orders": 0})
        return _json_response(True, data={"bids": bids, "asks": asks})
    except Exception as e:
        logger.error("Terminal orderbook error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/terminal/trades")
async def get_terminal_trades(request: Request, fetcher: FetcherDep, symbol: str = Query(..., min_length=1)):
    try:
        trading = getattr(request.app.state, "trading", None)
        trades = []
        if trading is not None and hasattr(trading, "get_trades"):
            all_trades = trading.get_trades()
            if isinstance(all_trades, list):
                for t in all_trades:
                    if isinstance(t, dict) and t.get("symbol") == symbol:
                        direction = "BUY" if t.get("side", t.get("direction", "")) in ("buy", "BUY") else "SELL"
                        trades.append({
                            "id": str(t.get("id", t.get("order_id", ""))),
                            "price": float(t.get("price", 0)),
                            "quantity": int(t.get("shares", t.get("quantity", 0))),
                            "amount": float(t.get("amount", 0)),
                            "direction": direction,
                            "time": str(t.get("time", t.get("timestamp", ""))),
                        })
        if not trades and fetcher is not None:
            if symbol.startswith(("6", "9")) or symbol.startswith(("0", "3")):
                pass
            try:
                df = await fetcher.get_history(symbol, period="1d", kline_type="1min", adjust="qfq")
                if df is not None and not df.empty and len(df) > 0:
                    recent = df.tail(30)
                    for idx, row in recent.iterrows():
                        close_p = float(row.get("close", row.get("Close", 0)))
                        vol = int(row.get("volume", row.get("Volume", 0)))
                        if close_p <= 0:
                            continue
                        open_p = float(row.get("open", row.get("Open", close_p)))
                        direction = "BUY" if close_p >= open_p else "SELL"
                        ts_val = row.get("date", row.get("time", row.name, None))
                        ts_str = str(ts_val) if ts_val is not None else ""
                        trades.append({
                            "id": f"M{idx}",
                            "price": close_p,
                            "quantity": vol,
                            "amount": round(close_p * vol, 2),
                            "direction": direction,
                            "time": ts_str,
                        })
            except Exception as e:
                logger.debug("Trade history fallback failed for %s: %s", symbol, e)
        return _json_response(True, data=trades[:50])
    except Exception as e:
        logger.error("Terminal trades error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.websocket("/ws/market")
async def ws_market(websocket: WebSocket, request: Request):
    from api.websocket_manager import OptimizedWSManager
    manager = getattr(request.app.state, "ws_manager", None)
    if manager is None:
        manager = OptimizedWSManager()
        request.app.state.ws_manager = manager
    connected = await manager.connect(websocket, channels=["market.indices"])
    if not connected:
        return
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")
            if msg_type == "subscribe":
                channels = data.get("channels", [])
                symbols = data.get("symbols", [])
                all_channels = list(channels)
                for s in symbols:
                    all_channels.append(f"stock.{s}")
                if all_channels:
                    await manager.subscribe(websocket, all_channels)
            elif msg_type == "unsubscribe":
                channels = data.get("channels", [])
                symbols = data.get("symbols", [])
                all_channels = list(channels)
                for s in symbols:
                    all_channels.append(f"stock.{s}")
                if all_channels:
                    await manager.unsubscribe(websocket, all_channels)
            elif msg_type == "ping":
                await manager.touch(websocket)
                await manager.send_to(websocket, {"type": "pong"})
    except Exception as e:
        logger.debug("WebSocket handler error: %s", e)
        await manager.disconnect(websocket)
