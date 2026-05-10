import asyncio
import logging
import time

from fastapi import APIRouter, Query, Request, WebSocket
from pydantic import BaseModel, Field

from api.utils import json_response as _json_response
from api.utils import safe_error

logger = logging.getLogger(__name__)

perf_router = APIRouter()


class KillSwitchConfirm(BaseModel):
    confirm: str = Field(..., min_length=1)


@perf_router.get("/market/heatmap")
async def get_sector_heatmap(request: Request):
    try:
        fetcher = request.app.state.fetcher
        data = await fetcher.get_sector_heatmap()
        return _json_response(True, data=data)
    except Exception as e:
        logger.error("Sector heatmap error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/market/breadth")
async def get_market_breadth(request: Request):
    try:
        fetcher = request.app.state.fetcher
        data = await fetcher.get_market_breadth()
        return _json_response(True, data=data)
    except Exception as e:
        logger.error("Market breadth error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/market/stocks")
async def get_market_stocks(
    request: Request,
    symbols: str = Query("", max_length=500, description="Comma-separated symbols"),
    limit: int = Query(50, ge=1, le=200),
):
    try:
        fetcher = request.app.state.fetcher
        if symbols:
            symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
            data = await fetcher.get_batch_realtime_optimized(symbol_list[:limit])
        else:
            from core.data_fetcher import _hot_symbols_cache, _get_hot_symbols_lock
            lock = _get_hot_symbols_lock()
            async with lock:
                hot = list(_hot_symbols_cache[:limit])
            if hot:
                data = await fetcher.get_batch_realtime_optimized(hot)
            else:
                data = {}
        return _json_response(True, data={"stocks": data, "count": len(data)})
    except Exception as e:
        logger.error("Market stocks error: %s", e)
        return _json_response(False, error=safe_error(e))


@perf_router.get("/risk/portfolio")
async def get_portfolio_risk(request: Request):
    try:
        import numpy as np
        fetcher = request.app.state.fetcher
        trading = getattr(request.app.state, "trading", None)
        if trading is None:
            return _json_response(False, error="Trading engine not available")
        positions = trading.get_positions() if hasattr(trading, "get_positions") else {}
        if not positions:
            return _json_response(True, data={"message": "No positions", "var": 0, "cvar": 0, "beta": 0})
        symbols = list(positions.keys())[:20]
        returns_list = []
        valid_symbols = []
        for sym in symbols:
            try:
                df = await fetcher.get_history(sym, period="1y", kline_type="daily", adjust="qfq")
                if df is not None and len(df) > 20 and "close" in df.columns:
                    closes = df["close"].values.astype(float)
                    rets = np.diff(closes) / np.where(closes[:-1] > 0, closes[:-1], 1)
                    rets = np.where(np.isfinite(rets), rets, 0)
                    returns_list.append(rets[-60:])
                    valid_symbols.append(sym)
            except Exception:
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
async def get_risk_exposure(request: Request):
    try:
        fetcher = request.app.state.fetcher
        trading = getattr(request.app.state, "trading", None)
        if trading is None:
            return _json_response(False, error="Trading engine not available")
        positions = trading.get_positions() if hasattr(trading, "get_positions") else {}
        if not positions:
            return _json_response(True, data={"sectors": {}, "concentration": 0})
        symbols = list(positions.keys())[:20]
        sector_map = {}
        for sym in symbols:
            try:
                fundamentals = await fetcher.get_fundamentals(sym)
                industry = ""
                if fundamentals and isinstance(fundamentals, dict):
                    industry = fundamentals.get("行业", fundamentals.get("industry", "Unknown"))
                if not industry:
                    industry = "Unknown"
                sector_map[industry] = sector_map.get(industry, 0) + 1
            except Exception:
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
                except Exception:
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
async def ai_market_summary(request: Request):
    try:
        fetcher = request.app.state.fetcher
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
        total_count = breadth.get("total", 1)
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
    except Exception:
        await manager.disconnect(websocket)
