from __future__ import annotations

import asyncio
import logging
import time

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from api.dependencies import FetcherDep
from api.utils import json_response as _json_response
from api.utils import safe_error

logger = logging.getLogger(__name__)
router = APIRouter()


class SmartStoplossRequest(BaseModel):
    symbol: str = Field(..., max_length=20)
    entry_price: float = Field(..., gt=0)
    entry_date: str = Field("", max_length=20)
    current_price: float = Field(0, ge=0)
    strategy_name: str = Field("", max_length=50)


@router.get("/market/sentiment-radar")
async def get_sentiment_radar(fetcher: FetcherDep):
    try:
        signals = {}

        try:
            breadth = await fetcher.get_market_breadth()
            up = breadth.get("up", 0)
            down = breadth.get("down", 1)
            signals["advance_decline_ratio"] = round(up / max(down, 1), 2)
        except Exception as e:
            logger.warning("Sentiment radar breadth failed: %s", e)
            signals["advance_decline_ratio"] = 1.0

        try:
            nb = await fetcher.fetch_north_bound_flow()
            if nb:
                total_net = nb.get("total_net", 0)
                signals["northbound_net_flow"] = round(total_net / 1e8, 2)
            else:
                signals["northbound_net_flow"] = 0.0
        except Exception as e:
            logger.warning("Sentiment radar northbound failed: %s", e)
            signals["northbound_net_flow"] = 0.0

        try:
            limit_up = await fetcher.fetch_limit_up_pool()
            signals["limit_up_count"] = len(limit_up)
        except Exception as e:
            logger.warning("Sentiment radar limit_up failed: %s", e)
            signals["limit_up_count"] = 0

        try:
            overview = await fetcher.get_market_overview()
            temperature = overview.get("temperature", 50.0)
            signals["market_temperature"] = round(temperature, 1)
        except Exception as e:
            logger.warning("Sentiment radar overview failed: %s", e)
            signals["market_temperature"] = 50.0

        try:
            dt = await fetcher.fetch_dragon_tiger_list()
            inst_buy = sum(
                1 for item in dt
                if "机构" in str(item.get("institutions", ""))
            )
            signals["dragon_tiger_inst_buy"] = inst_buy
        except Exception as e:
            logger.warning("Sentiment radar dragon_tiger failed: %s", e)
            signals["dragon_tiger_inst_buy"] = 0

        weights = {
            "advance_decline_ratio": 0.25,
            "northbound_net_flow": 0.20,
            "limit_up_count": 0.15,
            "market_temperature": 0.20,
            "dragon_tiger_inst_buy": 0.10,
        }
        score = 50.0
        adr = signals.get("advance_decline_ratio", 1.0)
        score += (adr - 1.0) * 25 * weights["advance_decline_ratio"]
        nb_flow = signals.get("northbound_net_flow", 0)
        score += min(max(nb_flow / 50, -1), 1) * 25 * weights["northbound_net_flow"]
        temp = signals.get("market_temperature", 50)
        score += (temp - 50) / 50 * 25 * weights["market_temperature"]
        lu = signals.get("limit_up_count", 0)
        score += min(lu / 50, 1) * 25 * weights["limit_up_count"]
        score = max(0, min(100, round(score, 1)))

        return _json_response(True, data={
            "score": score,
            "label": "贪婪" if score > 70 else ("恐惧" if score < 30 else "中性"),
            "signals": signals,
            "timestamp": time.time(),
        })
    except Exception as e:
        logger.error("Sentiment radar error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/strategy/health-check")
async def strategy_health_check(
    fetcher: FetcherDep,
    symbol: str = Query(..., max_length=20),
    days: int = Query(30, ge=7, le=90),
):
    try:
        from core.backtest import BacktestEngine
        from core.strategies import STRATEGY_REGISTRY

        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 60:
            return _json_response(False, error="数据不足")

        df = df.tail(max(days + 60, 120))
        results = []

        for name, cls in list(STRATEGY_REGISTRY.items())[:8]:
            try:
                engine = BacktestEngine(initial_capital=1_000_000)
                bt_result = await asyncio.to_thread(engine.run, cls(), df, symbol)
                sell_trades = [t for t in bt_result.trades if t.get("action") == "sell"]
                signal_freq = len(sell_trades) / max(days, 1)
                results.append({
                    "strategy": name,
                    "recent_return": round(bt_result.total_return, 4),
                    "recent_sharpe": round(bt_result.sharpe_ratio, 2),
                    "signal_frequency": round(signal_freq, 3),
                    "is_degraded": bt_result.sharpe_ratio < 0,
                    "degradation_reason": "sharpe_negative" if bt_result.sharpe_ratio < 0 else None,
                })
            except Exception as e:
                logger.debug("Strategy health check error for %s: %s", name, e)

        return _json_response(True, data={
            "symbol": symbol,
            "days": days,
            "strategies": results,
            "timestamp": time.time(),
        })
    except Exception as e:
        logger.error("Strategy health check error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/risk/smart-stoploss")
async def smart_stoploss(fetcher: FetcherDep, body: SmartStoplossRequest):
    try:
        current_price = body.current_price
        if current_price <= 0:
            rt = await fetcher.get_realtime(body.symbol)
            if rt and rt.get("price", 0) > 0:
                current_price = float(rt["price"])
            else:
                return _json_response(False, error="无法获取当前价格")

        df = await fetcher.get_history(body.symbol, period="1y", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 30:
            return _json_response(False, error="历史数据不足")

        work_df = df.dropna(subset=["close", "high", "low"]).reset_index(drop=True) if all(c in df.columns for c in ["close", "high", "low"]) else df.dropna(subset=["close"]).reset_index(drop=True)
        close = pd.to_numeric(work_df["close"], errors="coerce").fillna(0).values.astype(float)
        high = pd.to_numeric(work_df["high"], errors="coerce").fillna(0).values.astype(float) if "high" in work_df.columns else close
        low = pd.to_numeric(work_df["low"], errors="coerce").fillna(0).values.astype(float) if "low" in work_df.columns else close

        tr = np.maximum(high[1:] - low[1:], np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ))
        atr14 = np.mean(tr[-14:]) if len(tr) >= 14 else np.mean(tr)

        recent_low = float(np.min(low[-20:]))
        support_level = recent_low

        atr_stop = body.entry_price - 2 * atr14
        support_stop = support_level * 0.98
        pct_stop = body.entry_price * 0.92

        recommended_stop = max(atr_stop, support_stop, pct_stop)
        if recommended_stop >= current_price:
            recommended_stop = current_price * 0.95

        risk_per_share = body.entry_price - recommended_stop
        reward_per_share = current_price - body.entry_price
        rr_ratio = reward_per_share / max(risk_per_share, 0.01) if risk_per_share > 0 else 0

        win_rate_est = 0.5
        if rr_ratio > 0:
            kelly = win_rate_est - (1 - win_rate_est) / rr_ratio
            kelly = max(0, min(kelly, 0.25))
        else:
            kelly = 0.0

        return _json_response(True, data={
            "symbol": body.symbol,
            "entry_price": body.entry_price,
            "current_price": round(current_price, 2),
            "recommended_stop": round(recommended_stop, 2),
            "stop_methods": {
                "atr_2x": round(atr_stop, 2),
                "support_level": round(support_stop, 2),
                "pct_8": round(pct_stop, 2),
            },
            "atr14": round(atr14, 2),
            "risk_reward_ratio": round(rr_ratio, 2),
            "kelly_position_pct": round(kelly * 100, 1),
            "support_level": round(support_level, 2),
        })
    except Exception as e:
        logger.error("Smart stoploss error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/market/push-frequency")
async def get_adaptive_push_frequency(request: Request):
    try:
        from core.market_hours import MarketHours
        status = MarketHours.get_market_status("A")
        now = status.get("current_time", "")
        hour_min = 0
        try:
            parts = now.split(":")
            hour_min = int(parts[0]) * 100 + int(parts[1]) if len(parts) >= 2 else 0
        except (ValueError, IndexError):
            pass

        if 915 <= hour_min <= 925:
            interval_ms = 1000
            phase = "开盘竞价"
        elif (930 <= hour_min <= 1130) or (1300 <= hour_min <= 1450):
            interval_ms = 3000
            phase = "正常交易"
        elif 1457 <= hour_min <= 1500:
            interval_ms = 1000
            phase = "尾盘竞价"
        else:
            interval_ms = 60000
            phase = "盘后/非交易时段"

        return _json_response(True, data={
            "interval_ms": interval_ms,
            "phase": phase,
            "is_trading": status.get("is_open", False),
            "market_status": status,
        })
    except Exception as e:
        logger.error("Adaptive push frequency error: %s", e)
        return _json_response(False, error=safe_error(e))
