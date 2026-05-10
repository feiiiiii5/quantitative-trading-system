import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from itertools import combinations

import numpy as np
import orjson
import pandas as pd
from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import StreamingResponse

from api.connection_manager import cache_response
from api.routers.models import (
    BlackLittermanRequest, MonteCarloVaRRequest, RebalanceScheduleRequest,
)
from api.utils import json_response as _json_response
from api.utils import get_trading, rate_limiter, safe_error, validate_symbol
from core.data_fetcher import SmartDataFetcher
from core.database import SQLiteStore, get_db
from core.market_detector import MarketDetector
from core.market_hours import MarketHours

logger = logging.getLogger(__name__)

router = APIRouter()

_start_time = time.time()


def _period_to_history(period: str) -> str:
    period = (period or "1y").lower()
    if period in {"3m", "6m"}:
        return "1y"
    if period in {"3y", "5y", "all"}:
        return "all"
    return "1y"


@router.post("/portfolio/rebalance/schedule")
async def create_rebalance_schedule(body: RebalanceScheduleRequest, request: Request):
    """创建再平衡调度计划"""
    try:
        symbol_list = [s.strip() for s in body.symbols.split(",") if s.strip()]
        if len(symbol_list) < 2:
            return _json_response(False, error="至少需要2只股票")

        schedule_id = str(uuid.uuid4())[:8]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        db = get_db()
        with db._get_conn() as conn:
            conn.execute(
                """INSERT INTO rebalance_schedules
                   (id, name, symbols, frequency, drift_threshold,
                    turnover_cap, capital, period, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (schedule_id, body.name, body.symbols, body.frequency,
                 body.drift_threshold, body.turnover_cap, body.capital, body.period,
                 now, now),
            )
            conn.commit()

        return _json_response(True, data={
            "schedule_id": schedule_id,
            "name": body.name,
            "symbols": symbol_list,
            "frequency": body.frequency,
            "drift_threshold": body.drift_threshold,
            "created_at": now,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/rebalance/schedules")
async def list_rebalance_schedules(request: Request):
    """列出所有再平衡调度计划"""
    try:
        db = get_db()
        rows = db._get_conn().execute(
            """SELECT id, name, symbols, frequency, drift_threshold,
                      turnover_cap, capital, period, enabled, last_check_at, created_at
               FROM rebalance_schedules ORDER BY created_at DESC"""
        ).fetchall()

        schedules = []
        for row in rows:
            schedules.append({
                "schedule_id": row[0],
                "name": row[1],
                "symbols": row[2],
                "frequency": row[3],
                "drift_threshold": row[4],
                "turnover_cap": row[5],
                "capital": row[6],
                "period": row[7],
                "enabled": bool(row[8]),
                "last_check_at": row[9],
                "created_at": row[10],
            })

        return _json_response(True, data={"schedules": schedules, "total": len(schedules)})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.delete("/portfolio/rebalance/schedule/{schedule_id}")
async def delete_rebalance_schedule(
    request: Request,
    schedule_id: str = Path(..., min_length=1, max_length=20),
):
    """删除再平衡调度计划"""
    try:
        db = get_db()
        with db._get_conn() as conn:
            cursor = conn.execute("DELETE FROM rebalance_schedules WHERE id = ?", (schedule_id,))
            conn.commit()
            if cursor.rowcount == 0:
                return _json_response(False, error="调度计划不存在")

        return _json_response(True, data={"deleted": schedule_id})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/portfolio/rebalance/schedule/{schedule_id}/check")
async def execute_rebalance_check(
    request: Request,
    schedule_id: str = Path(..., min_length=1, max_length=20),
):
    """手动触发再平衡检查"""
    try:
        db = get_db()
        row = db._get_conn().execute(
            """SELECT symbols, drift_threshold, turnover_cap, capital, period
               FROM rebalance_schedules WHERE id = ? AND enabled = 1""",
            (schedule_id,),
        ).fetchone()

        if not row:
            return _json_response(False, error="调度计划不存在或已禁用")

        symbols_str, drift_threshold, turnover_cap, capital, period = row
        symbol_list = [s.strip() for s in symbols_str.split(",") if s.strip()]

        from core.risk_parity_rebalancer import RiskParityRebalancer

        fetcher: SmartDataFetcher = request.app.state.fetcher
        all_returns: dict[str, np.ndarray] = {}
        prices: dict[str, float] = {}

        for sym in symbol_list[:10]:
            try:
                df = await fetcher.get_history(sym, _period_to_history(period), "daily", "qfq")
                if df is None or len(df) < 30:
                    continue
                c = df["close"].astype(float)
                prices[sym] = float(c.iloc[-1])
                ret = c.pct_change().dropna()
                ret = ret[np.isfinite(ret)]
                all_returns[sym] = ret.values[-120:]
            except (ValueError, KeyError, OSError) as e:
                logger.debug("Return calc failed for %s: %s", sym, e)
                continue

        if len(all_returns) < 2:
            return _json_response(False, error="有效数据不足，无法执行再平衡检查")

        min_len = min(len(v) for v in all_returns.values())
        ret_matrix = np.column_stack([v[-min_len:] for v in all_returns.values()])
        cov_matrix = np.cov(ret_matrix.T)

        sym_list = list(all_returns.keys())
        positions = [{"symbol": sym, "name": sym, "weight": 1.0 / len(sym_list)} for sym in sym_list]

        rebalancer = RiskParityRebalancer(drift_threshold=drift_threshold, turnover_cap=turnover_cap)
        result = rebalancer.analyze(positions, cov_matrix, prices, capital)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result_json = json.dumps({
            "needs_rebalance": result.needs_rebalance,
            "max_drift": result.max_drift,
            "total_turnover": result.total_turnover,
            "reason": result.reason,
            "trades": [
                {"symbol": t.symbol, "action": t.action, "weight_delta": t.weight_delta,
                 "shares": t.shares, "price": t.price}
                for t in result.trades
            ],
        }, ensure_ascii=False)

        with db._get_conn() as conn:
            conn.execute(
                "UPDATE rebalance_schedules SET last_check_at = ?, last_result_json = ?, updated_at = ? WHERE id = ?",
                (now, result_json, now, schedule_id),
            )
            conn.commit()

        return _json_response(True, data={
            "schedule_id": schedule_id,
            "checked_at": now,
            "needs_rebalance": result.needs_rebalance,
            "reason": result.reason,
            "max_drift": result.max_drift,
            "total_turnover": result.total_turnover,
            "trades": [
                {"symbol": t.symbol, "name": t.name, "action": t.action,
                 "current_weight": t.current_weight, "target_weight": t.target_weight,
                 "weight_delta": t.weight_delta, "shares": t.shares, "price": t.price}
                for t in result.trades
            ],
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/stream")
async def stream_portfolio_metrics(request: Request):
    """Server-Sent Events endpoint for real-time portfolio metrics streaming.

    Streams rolling risk metrics and system health data as SSE events.
    Clients connect via EventSource and receive updates at configurable intervals.
    """
    async def event_stream():
        interval = 5
        reconnect_delay = 2
        max_empty = 3
        empty_count = 0

        try:
            while True:
                try:
                    from core.metrics import get_metrics

                    mc = get_metrics()
                    metrics_summary = mc.get_summary()

                    now = datetime.now()
                    market_status = {}
                    try:
                        for market in ["A", "HK", "US"]:
                            status = MarketHours.get_market_status(market)
                            market_status[market] = {
                                "is_open": status.get("is_open", False),
                                "session": status.get("session", "unknown"),
                            }
                    except Exception as e:
                        logger.debug("Market status parse failed: %s", e)

                    push_data = {
                        "timestamp": now.isoformat(),
                        "markets": market_status,
                        "metrics": metrics_summary,
                        "server_uptime": round(time.time() - _start_time, 1),
                    }

                    if market_status and not any(m.get("is_open") for m in market_status.values()):
                        empty_count += 1
                    else:
                        empty_count = 0

                    payload = orjson.dumps(push_data).decode()
                    yield f"data: {payload}\n\n"

                    if empty_count >= max_empty:
                        yield f"data: {orjson.dumps({'event': 'market_closed', 'timestamp': now.isoformat()}).decode()}\n\n"
                        break

                    await asyncio.sleep(interval)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug("SSE stream error: %s", e)
                    yield f"data: {orjson.dumps({'event': 'error', 'message': safe_error(e)}).decode()}\n\n"
                    await asyncio.sleep(reconnect_delay)
        except asyncio.CancelledError:
            pass
        finally:
            yield f"data: {orjson.dumps({'event': 'disconnect', 'timestamp': datetime.now().isoformat()}).decode()}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/portfolio/summary")
async def get_portfolio_summary(request: Request):
    try:
        from core.async_utils import rt_cache, CACHE_TTL
        cache_key = "portfolio_summary_v2"
        cached = await rt_cache.get(cache_key)
        if cached is not None:
            return _json_response(True, data=cached, cached=True)

        db = request.app.state.db
        watchlist = db.get_config("watchlist", [])
        if not isinstance(watchlist, list):
            watchlist = []
        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbols = watchlist[:20]
        positions = []
        total_value = 0.0
        total_pnl = 0.0

        if symbols:
            from core.market_detector import MarketDetector
            tasks = []
            for symbol in symbols:
                market = MarketDetector.detect(symbol)
                tasks.append(fetcher.get_realtime(symbol, market))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for symbol, result in zip(symbols, results, strict=True):
                if isinstance(result, Exception) or not result:
                    continue
                try:
                    price = float(result.get("price", 0))
                    change_pct = float(result.get("change_pct", 0))
                    name = result.get("name", symbol)
                    positions.append({
                        "symbol": symbol,
                        "name": name,
                        "price": price,
                        "change_pct": change_pct,
                    })
                    total_value += price
                    total_pnl += change_pct
                except (TypeError, ValueError):
                    continue

        avg_change = total_pnl / len(positions) if positions else 0
        data = {
            "total_positions": len(positions),
            "total_value": round(total_value, 2),
            "avg_change_pct": round(avg_change, 4),
            "positions": positions,
        }
        await rt_cache.set(cache_key, data, CACHE_TTL["portfolio_summary"])
        return _json_response(True, data=data)
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
                logger.debug("Return calc failed for %s: %s", sym, e)
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
        logger.error("Portfolio risk analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/risk/dashboard")
@rate_limiter(max_calls=20, time_window=60.0)
async def get_portfolio_risk_dashboard(
    request: Request,
    period: str = Query("1y", description="数据周期"),
):
    """组合风险仪表盘 — 聚合风险指标、集中度、回撤、压力测试于单一端点"""
    try:
        db: SQLiteStore = request.app.state.db
        fetcher: SmartDataFetcher = request.app.state.fetcher

        watchlist = db.get_config("watchlist", [])
        if not isinstance(watchlist, list) or not watchlist:
            return _json_response(True, data={
                "positions": [],
                "risk_metrics": {},
                "concentration": {},
                "drawdown": {},
                "stress_summary": [],
                "message": "观察列表为空",
            })

        positions = []
        all_returns = {}
        total_value = 0.0
        daily_pnl = 0.0

        for symbol in watchlist[:20]:
            try:
                market = MarketDetector.detect(symbol)
                rt = await fetcher.get_realtime(symbol, market)
                if not rt:
                    continue
                price = float(rt.get("price", 0))
                change_pct = float(rt.get("change_pct", 0))
                name = rt.get("name", symbol)
                positions.append({
                    "symbol": symbol,
                    "name": name,
                    "price": price,
                    "change_pct": change_pct,
                    "market": market,
                })
                total_value += price
                daily_pnl += change_pct

                df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
                if df is not None and len(df) >= 30:
                    c = df["close"].astype(float)
                    ret = c.pct_change().dropna()
                    ret = ret[np.isfinite(ret)]
                    if len(ret) >= 20:
                        all_returns[symbol] = ret.values[-120:]
            except Exception as e:
                logger.debug("Return calc failed for %s: %s", symbol, e)
                continue

        concentration = {}
        if total_value > 0 and positions:
            for p in positions:
                weight = p["price"] / total_value
                concentration[p["symbol"]] = round(weight, 4)
            sorted_by_weight = sorted(concentration.items(), key=lambda x: x[1], reverse=True)
            top_n = min(5, len(sorted_by_weight))
            top_weight = sum(w for _, w in sorted_by_weight[:top_n])
            concentration["_top5_weight"] = round(top_weight, 4)
            concentration["_top5_symbols"] = [s for s, _ in sorted_by_weight[:top_n]]
            max_weight = sorted_by_weight[0][1] if sorted_by_weight else 0
            concentration["_max_single_weight"] = round(max_weight, 4)
            concentration["_is_concentrated"] = max_weight > 0.20

        risk_metrics = {}
        if len(all_returns) >= 2:
            min_len = min(len(v) for v in all_returns.values())
            ret_matrix = np.column_stack([v[-min_len:] for v in all_returns.values()])
            sym_list = list(all_returns.keys())
            n_assets = len(sym_list)
            weights = np.ones(n_assets) / n_assets

            port_returns = ret_matrix @ weights
            port_vol = float(np.std(port_returns) * np.sqrt(252))
            port_mean = float(np.mean(port_returns) * 252)
            sharpe = port_mean / port_vol if port_vol > 1e-12 else 0.0

            var_95 = float(np.percentile(port_returns, 5))
            cvar_95 = float(np.mean(port_returns[port_returns <= var_95])) if np.any(port_returns <= var_95) else var_95

            downside = port_returns[port_returns < 0]
            downside_dev = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(252)) if len(downside) > 0 else 0.0
            sortino = port_mean / downside_dev if downside_dev > 1e-12 else 0.0

            cum_returns = np.cumsum(port_returns)
            running_max = np.maximum.accumulate(cum_returns)
            drawdowns = cum_returns - running_max
            max_dd = float(np.min(drawdowns))

            risk_metrics = {
                "portfolio_volatility": round(port_vol, 4),
                "portfolio_sharpe": round(sharpe, 2),
                "portfolio_sortino": round(sortino, 2),
                "var_95": round(var_95, 4),
                "cvar_95": round(cvar_95, 4),
                "max_drawdown": round(max_dd, 4),
                "annual_return": round(port_mean, 4),
            }

        drawdown_info = {}
        if len(all_returns) >= 2 and risk_metrics:
            drawdown_info = {
                "current_drawdown": 0.0,
                "max_drawdown": risk_metrics.get("max_drawdown", 0.0),
                "drawdown_status": "normal",
            }
            if risk_metrics.get("max_drawdown", 0) < -0.10:
                drawdown_info["drawdown_status"] = "warning"
            if risk_metrics.get("max_drawdown", 0) < -0.20:
                drawdown_info["drawdown_status"] = "critical"

        stress_summary = []
        if positions and total_value > 0:
            from core.portfolio_risk_engine import STRESS_SCENARIOS
            for scenario in STRESS_SCENARIOS:
                projected_loss = total_value * scenario.market_shock
                stress_summary.append({
                    "scenario": scenario.name,
                    "description": scenario.description,
                    "projected_loss_pct": round(scenario.market_shock, 4),
                    "projected_loss_amount": round(projected_loss, 2),
                })

        return _json_response(True, data={
            "positions": positions,
            "total_value": round(total_value, 2),
            "daily_pnl_pct": round(daily_pnl / len(positions), 4) if positions else 0.0,
            "position_count": len(positions),
            "risk_metrics": risk_metrics,
            "concentration": concentration,
            "drawdown": drawdown_info,
            "stress_summary": stress_summary,
        })
    except Exception as e:
        logger.error("Risk dashboard error: %s", e)
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
                logger.debug("Risk attribution failed: %s", e)
                continue

        return _json_response(True, data={
            "benchmark": benchmark,
            "benchmark_return": round(float(np.prod(1 + bench_ret) - 1), 4),
            "attribution": attribution,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/rebalance")
async def get_risk_parity_rebalance(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    capital: float = Query(100000, ge=10000, description="总资金"),
    drift_threshold: float = Query(0.05, ge=0.01, le=0.20, description="偏离阈值"),
    period: str = Query("1y"),
):
    """风险平价再平衡建议"""
    try:
        from core.risk_parity_rebalancer import RiskParityRebalancer

        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if len(symbol_list) < 2:
            return _json_response(False, error="至少需要2只股票")

        all_returns = {}
        prices = {}
        for sym in symbol_list[:10]:
            try:
                df = await fetcher.get_history(sym, _period_to_history(period), "daily", "qfq")
                if df is None or len(df) < 30:
                    continue
                c = df["close"].astype(float)
                prices[sym] = float(c.iloc[-1])
                ret = c.pct_change().dropna()
                ret = ret[np.isfinite(ret)]
                all_returns[sym] = ret.values[-120:]
            except Exception as e:
                logger.debug("Return calc failed for %s: %s", sym, e)
                continue

        if len(all_returns) < 2:
            return _json_response(False, error="有效数据不足")

        min_len = min(len(v) for v in all_returns.values())
        ret_matrix = np.column_stack([v[-min_len:] for v in all_returns.values()])
        cov_matrix = np.cov(ret_matrix.T)

        positions = []
        sym_list = list(all_returns.keys())
        for _i, sym in enumerate(sym_list):
            positions.append({
                "symbol": sym,
                "name": sym,
                "weight": 1.0 / len(sym_list),
            })

        rebalancer = RiskParityRebalancer(drift_threshold=drift_threshold)
        result = rebalancer.analyze(positions, cov_matrix, prices, capital)

        return _json_response(True, data={
            "needs_rebalance": result.needs_rebalance,
            "reason": result.reason,
            "total_turnover": result.total_turnover,
            "max_drift": result.max_drift,
            "trades": [
                {
                    "symbol": t.symbol,
                    "name": t.name,
                    "current_weight": t.current_weight,
                    "target_weight": t.target_weight,
                    "weight_delta": t.weight_delta,
                    "action": t.action,
                    "shares": t.shares,
                    "price": t.price,
                }
                for t in result.trades
            ],
        })
    except Exception as e:
        logger.error("Rebalance analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/stress/scenarios")
async def get_stress_scenarios(request: Request):
    """获取预定义压力测试情景列表"""
    from core.stress_test import PREDEFINED_SCENARIOS
    scenarios = []
    for s in PREDEFINED_SCENARIOS:
        scenarios.append({
            "name": s.name,
            "description": s.description,
            "equity_shock": s.equity_shock,
            "bond_shock": s.bond_shock,
            "commodity_shock": s.commodity_shock,
            "volatility_mult": s.volatility_mult,
        })
    return _json_response(True, data=scenarios)


@router.post("/portfolio/stress/run")
async def run_stress_test(request: Request):
    """运行组合压力测试"""
    try:
        from core.stress_test import PortfolioStressTester
        body = await request.json()
        positions = body.get("positions", [])
        if not positions:
            return _json_response(False, error="请提供持仓数据")
        try:
            values = [float(p.get("value", 0)) for p in positions]
        except (ValueError, TypeError):
            return _json_response(False, error="持仓价值必须为数字")

        tester = PortfolioStressTester()
        scenario_results = tester.run_all_scenarios(positions)

        monte_carlo_result = None
        if body.get("run_monte_carlo", False):
            fetcher: SmartDataFetcher = request.app.state.fetcher
            symbols = [p.get("symbol", "") for p in positions if p.get("symbol")]
            total_value = sum(values)
            weights = np.array([v / total_value for v in values]) if total_value > 0 else np.ones(len(positions)) / len(positions)

            all_returns = {}
            for sym in symbols[:10]:
                try:
                    df = await fetcher.get_history(sym, "1y", "daily", "qfq")
                    if df is not None and len(df) >= 30:
                        ret = df["close"].astype(float).pct_change().dropna()
                        ret = ret[np.isfinite(ret)]
                        all_returns[sym] = ret.values[-120:]
                except Exception as e:
                    logger.debug("Return calc failed for %s: %s", sym, e)
                    continue

            if len(all_returns) >= 2:
                min_len = min(len(v) for v in all_returns.values())
                ret_matrix = np.column_stack([v[-min_len:] for v in all_returns.values()])
                mc = tester.monte_carlo(
                    returns=ret_matrix,
                    weights=weights[:ret_matrix.shape[1]],
                    portfolio_value=total_value,
                    horizon_days=max(1, min(int(body.get("horizon_days", 20)), 252)),
                    n_simulations=min(max(int(body.get("n_simulations", 5000)), 100), 10000),
                )
                monte_carlo_result = mc.summary()

        return _json_response(True, data={
            "scenarios": scenario_results,
            "monte_carlo": monte_carlo_result,
        })
    except Exception as e:
        logger.error("Stress test error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/report/weekly")
@cache_response(3600)
async def get_weekly_report(request: Request):
    """周报生成接口"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        overview = await fetcher.get_market_overview()
        cn = overview.get("cn_indices", {})

        market_summary = {}
        for name, info in cn.items():
            if isinstance(info, dict):
                market_summary[name] = {
                    "price": info.get("price", 0),
                    "change_pct": info.get("change_pct", 0),
                }

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
            logger.debug("Heatmap data failed: %s", e)

        if not heatmap_data:
            try:
                url = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
                import re

                import aiohttp

                from core.data_fetcher import get_aiohttp_session
                session = await get_aiohttp_session()
                async with session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        text = await resp.text()
                match = re.search(r'=\s*({.*})', text)
                if match:
                    data = json.loads(match.group(1))
                    top_gainers = []
                    top_losers = []
                    for _key, val in data.items():
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
                logger.debug("Heatmap gainers/losers failed: %s", e)
                heatmap_data = {"top_gainers": [], "top_losers": []}

        northbound = {}
        try:
            northbound = await fetcher.fetch_north_bound_flow()
        except Exception as e:
            logger.debug("Northbound flow fetch failed: %s", e)

        report_date = datetime.now().strftime("%Y-%m-%d")
        return _json_response(True, data={
            "report_date": report_date,
            "market_summary": market_summary,
            "sector_performance": heatmap_data,
            "northbound_flow": northbound,
            "generated_at": time.time(),
        })
    except Exception as e:
        logger.error("Weekly report error: %s", e)
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

        history_map = await fetcher.get_history_batch(symbol_list[:10], _period_to_history(period), "daily", "qfq")
        all_close = {}
        for sym, df in history_map.items():
            if len(df) >= 30:
                all_close[sym] = df[["date", "close"]].copy()

        if not all_close:
            return _json_response(False, error="有效数据不足")

        all_close_items = list(all_close.items())
        if not all_close_items:
            return _json_response(False, error="有效数据不足")

        merged = all_close_items[0][1].rename(columns={"close": all_close_items[0][0]})
        for sym, sdf in all_close_items[1:]:
            sdf = sdf.rename(columns={"close": sym})
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
            "weights": {s: round(float(w), 4) for s, w in zip(sym_cols, weights, strict=False)},
            "equity_curve": equity_curve,
            "cumulative_return": round(cumulative_return, 4),
            "max_drawdown": round(max_drawdown, 4),
            "annual_return": round(annual_return, 4),
            "annual_volatility": round(annual_vol, 4),
            "sharpe_ratio": round(sharpe, 2),
        })
    except Exception as e:
        logger.error("Portfolio equity error: %s", e)
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

        history_map = await fetcher.get_history_batch(symbol_list, _period_to_history(period), "daily", "qfq")
        all_close = {}
        for sym, df in history_map.items():
            if len(df) >= 30:
                all_close[sym] = df["close"].astype(float).values

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
        logger.error("Portfolio correlation error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/correlation/rolling")
async def get_rolling_correlation(
    request: Request,
    symbol_a: str = Query(..., max_length=20, description="股票A代码"),
    symbol_b: str = Query(..., max_length=20, description="股票B代码"),
    window: int = Query(60, ge=20, le=252, description="滚动窗口"),
    period: str = Query("1y", max_length=5),
):
    """两只股票的滚动相关系数分析"""
    try:
        if not validate_symbol(symbol_a) or not validate_symbol(symbol_b):
            return _json_response(False, error="Invalid symbol")
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df_a = await fetcher.get_history(symbol_a, _period_to_history(period), "daily", "qfq")
        df_b = await fetcher.get_history(symbol_b, _period_to_history(period), "daily", "qfq")
        if df_a is None or df_a.empty or df_b is None or df_b.empty:
            return _json_response(False, error="数据不足")
        from core.correlation import get_correlation_analyzer
        analyzer = get_correlation_analyzer()
        result = analyzer.compute_rolling_correlation(
            pd.Series(df_a["close"].astype(float).values, index=pd.to_datetime(df_a["date"])),
            pd.Series(df_b["close"].astype(float).values, index=pd.to_datetime(df_b["date"])),
            window=window,
        )
        if "error" in result:
            return _json_response(False, error=result["error"])
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/correlation/analysis")
async def correlation_deep_analysis(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    period: str = Query("1y", max_length=5, description="时间范围"),
    method: str = Query("pearson", pattern=r"^(pearson|spearman)$", description="相关系数方法"),
):
    """组合相关性深度分析：矩阵、高/低相关对、分散化评分、最优配对"""
    try:
        from core.correlation_analysis import CorrelationAnalyzer

        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if len(symbol_list) < 2:
            return _json_response(False, error="至少需要2个股票代码")
        symbol_list = symbol_list[:15]

        history_map = await fetcher.get_history_batch(
            symbol_list, _period_to_history(period), "daily", "qfq"
        )

        prices_dict: dict[str, pd.Series] = {}
        for sym, df in history_map.items():
            if df is not None and len(df) >= 30:
                prices_dict[sym] = df["close"].astype(float)

        if len(prices_dict) < 2:
            return _json_response(False, error="有效数据不足，至少需要2只有数据的股票")

        min_len = min(len(v) for v in prices_dict.values())
        price_data = {sym: s.iloc[-min_len:].reset_index(drop=True) for sym, s in prices_dict.items()}
        prices_df = pd.DataFrame(price_data)

        analyzer = CorrelationAnalyzer()
        result = analyzer.analyze(prices_df, method=method)

        optimal_pairs = analyzer.find_optimal_pairs(prices_df, target_corr=0.0)

        return _json_response(True, data={
            "is_valid": result.is_valid,
            "message": result.message,
            "n_assets": result.n_assets,
            "correlation_matrix": result.correlation_matrix,
            "highly_correlated_pairs": [
                {"symbol_a": p[0], "symbol_b": p[1], "correlation": round(p[2], 4)}
                for p in result.highly_correlated_pairs
            ],
            "low_correlated_pairs": [
                {"symbol_a": p[0], "symbol_b": p[1], "correlation": round(p[2], 4)}
                for p in result.low_correlated_pairs
            ],
            "average_correlation": round(result.average_correlation, 4),
            "diversification_score": round(result.diversification_score, 4),
            "optimal_pairs_for_trading": [
                {"symbol_a": p[0], "symbol_b": p[1], "correlation": round(p[2], 4)}
                for p in optimal_pairs
            ],
            "method": method,
            "period": period,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/correlation/beta")
async def get_beta_analysis(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    benchmark: str = Query("sh000300", max_length=20, description="基准指数"),
    period: str = Query("1y", max_length=5),
):
    """多股票Beta矩阵分析，含系统性/特质风险分解"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if len(symbol_list) < 1:
            return _json_response(False, error="至少需要1个股票代码")
        symbol_list = symbol_list[:15]
        if not validate_symbol(benchmark):
            return _json_response(False, error="Invalid benchmark symbol")
        history_map = await fetcher.get_history_batch(
            symbol_list + [benchmark], _period_to_history(period), "daily", "qfq"
        )
        bench_df = history_map.pop(benchmark, None)
        if bench_df is None or bench_df.empty:
            return _json_response(False, error="基准数据不足")
        bench_prices = pd.Series(
            bench_df["close"].astype(float).values,
            index=pd.to_datetime(bench_df["date"]),
        )
        price_data = {}
        for sym, df in history_map.items():
            if len(df) >= 30:
                price_data[sym] = pd.Series(
                    df["close"].astype(float).values,
                    index=pd.to_datetime(df["date"]),
                )
        if not price_data:
            return _json_response(False, error="有效股票数据不足")
        from core.correlation import get_correlation_analyzer
        analyzer = get_correlation_analyzer()
        result = analyzer.compute_beta_matrix(price_data, bench_prices)
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/portfolio/diversification")
async def get_diversification_score(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    period: str = Query("1y", max_length=5),
):
    """组合分散度深度评估：ENB、条件分散收益、PCA方差贡献"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if len(symbol_list) < 2:
            return _json_response(False, error="至少需要2个股票代码")
        symbol_list = symbol_list[:15]
        history_map = await fetcher.get_history_batch(
            symbol_list, _period_to_history(period), "daily", "qfq"
        )
        price_data = {}
        for sym, df in history_map.items():
            if len(df) >= 30:
                price_data[sym] = pd.Series(
                    df["close"].astype(float).values,
                    index=pd.to_datetime(df["date"]),
                )
        if len(price_data) < 2:
            return _json_response(False, error="有效股票数据不足，至少需要2只")
        from core.correlation import get_correlation_analyzer
        analyzer = get_correlation_analyzer()
        result = analyzer.compute_diversification_score(price_data)
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/position/kelly")
async def get_kelly_position(
    win_rate: float = Query(..., ge=0.01, le=0.99, description="胜率"),
    avg_win: float = Query(..., gt=0, description="平均盈利比例"),
    avg_loss: float = Query(..., gt=0, description="平均亏损比例"),
    fraction: float = Query(0.5, ge=0.1, le=1.0, description="凯利分数"),
):
    """凯利公式仓位计算"""
    try:
        from core.position_sizer import get_position_sizer
        sizer = get_position_sizer()
        result = sizer.kelly_fraction(win_rate, avg_win, avg_loss, fraction)
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/position/atr")
async def get_atr_position(
    request: Request,
    symbol: str = Query(..., max_length=20, description="股票代码"),
    capital: float = Query(1000000, gt=10000, description="总资金"),
    risk_pct: float = Query(0.02, gt=0.001, le=0.1, description="单笔风险比例"),
    atr_mult: float = Query(2.0, gt=0.5, le=5.0, description="ATR止损倍数"),
):
    """基于ATR止损的仓位计算"""
    try:
        if not validate_symbol(symbol):
            return _json_response(False, error="Invalid symbol")
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="1y", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 20:
            return _json_response(False, error="数据不足")
        from core.indicators import TechnicalIndicators
        indicators = TechnicalIndicators.compute_all(df)
        atr_val = indicators.get("atr", 0)
        entry_price = float(df["close"].iloc[-1])
        if atr_val <= 0 or entry_price <= 0:
            return _json_response(False, error="ATR或价格数据无效")
        from core.position_sizer import get_position_sizer
        sizer = get_position_sizer()
        result = sizer.atr_position_size(capital, entry_price, atr_val, risk_pct, atr_mult)
        result["symbol"] = symbol
        result["entry_price"] = round(entry_price, 2)
        result["atr"] = round(atr_val, 4)
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/position/risk-parity")
async def get_risk_parity_position(
    request: Request,
):
    """风险平价仓位分配"""
    try:
        body = await request.json()
        capital = float(body.get("capital", 1000000))
        positions = body.get("positions", [])
        if capital <= 0:
            return _json_response(False, error="资金必须为正数")
        if not positions or not isinstance(positions, list):
            return _json_response(False, error="需要提供positions列表")
        from core.position_sizer import get_position_sizer
        sizer = get_position_sizer()
        result = sizer.risk_parity_size(capital, positions)
        return _json_response(True, data=result)
    except Exception as e:
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
            ic_weighted_optimize,
            mean_variance_optimize,
            risk_parity_optimize,
        )

        history_map = await fetcher.get_history_batch(symbol_list[:30], _period_to_history(period), "daily", "qfq")
        all_returns = {}
        for sym, df in history_map.items():
            if len(df) >= 30:
                c = df["close"].astype(float)
                ret = c.pct_change().dropna()
                ret = ret[np.isfinite(ret)]
                all_returns[sym] = ret.values[-252:]

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
        logger.error("Portfolio optimization error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/portfolio/black-litterman")
async def black_litterman_optimize(request: Request, body: BlackLittermanRequest):
    try:
        from core.black_litterman import BlackLittermanModel

        fetcher: SmartDataFetcher = request.app.state.fetcher
        history_map = await fetcher.get_history_batch(
            body.symbols, _period_to_history(body.period), "daily", "qfq"
        )
        price_data = {}
        for sym, df in history_map.items():
            if df is not None and len(df) >= 30:
                price_data[sym] = df["close"].astype(float).values

        if len(price_data) < 2:
            return _json_response(False, error="有效数据不足，至少需要2只股票")

        min_len = min(len(v) for v in price_data.values())
        prices_df = pd.DataFrame({sym: v[-min_len:] for sym, v in price_data.items()})

        model = BlackLittermanModel(
            risk_free_rate=body.risk_free_rate,
            tau=body.tau,
            risk_aversion=body.risk_aversion,
        )
        result = model.optimize(
            prices_df,
            views=body.views,
            market_weights=body.market_weights,
            view_confidences=body.view_confidences,
        )

        return _json_response(result.is_valid, data={
            "posterior_returns": result.posterior_returns,
            "weights": result.weights,
            "expected_return": round(result.expected_return, 4),
            "expected_volatility": round(result.expected_volatility, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "message": result.message,
        })
    except Exception as e:
        logger.error("Black-Litterman optimization error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/portfolio/monte-carlo-var")
async def monte_carlo_var(request: Request, body: MonteCarloVaRRequest):
    try:
        from core.monte_carlo_var import MonteCarloVaR

        fetcher: SmartDataFetcher = request.app.state.fetcher
        history_map = await fetcher.get_history_batch(
            body.symbols, _period_to_history(body.period), "daily", "qfq"
        )
        price_data = {}
        for sym, df in history_map.items():
            if df is not None and len(df) >= 30:
                price_data[sym] = df["close"].astype(float).values

        if len(price_data) < 1:
            return _json_response(False, error="有效数据不足")

        min_len = min(len(v) for v in price_data.values())
        prices_df = pd.DataFrame({sym: v[-min_len:] for sym, v in price_data.items()})

        engine = MonteCarloVaR(
            n_simulations=body.n_simulations,
            time_horizon=body.time_horizon,
        )

        if body.method == "historical":
            result = engine.simulate_historical(prices_df, body.weights)
        else:
            result = engine.simulate(prices_df, body.weights)

        return _json_response(result.is_valid, data={
            "var_95": round(result.var_95, 6),
            "var_99": round(result.var_99, 6),
            "cvar_95": round(result.cvar_95, 6),
            "cvar_99": round(result.cvar_99, 6),
            "mean_portfolio_return": round(result.mean_portfolio_return, 6),
            "std_portfolio_return": round(result.std_portfolio_return, 6),
            "n_simulations": result.n_simulations,
            "confidence_levels": result.confidence_levels,
            "method": body.method,
            "message": result.message,
        })
    except Exception as e:
        logger.error("Monte Carlo VaR error: %s", e)
        return _json_response(False, error=safe_error(e))
