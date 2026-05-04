"""
QuantCore 新功能API路由模块
资讯、选股器、资金流向、筹码分布、板块轮动
"""
import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, Path, Query, Request

from api.utils import sanitize, json_response as _json_response, safe_error

logger = logging.getLogger(__name__)

feature_router = APIRouter()


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


@feature_router.get("/news/latest")
async def get_latest_news(request: Request, count: int = Query(40)):
    count = _clamp(count, 1, 200)
    try:
        from core.news_engine import get_news_engine
        engine = get_news_engine()
        news = await engine.fetch_latest_news(count)
        return _json_response(True, data=news)
    except Exception as e:
        logger.error(f"News latest error: {e}")
        return _json_response(False, error=safe_error(e))


@feature_router.get("/news/stock/{symbol}")
async def get_stock_news(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"), count: int = Query(20)):
    count = _clamp(count, 1, 100)
    try:
        from core.news_engine import get_news_engine
        engine = get_news_engine()
        news = await engine.fetch_stock_news(symbol, count)
        return _json_response(True, data=news)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@feature_router.get("/news/sentiment")
async def get_market_sentiment(request: Request):
    try:
        from core.news_engine import get_news_engine
        from core.market_data import fetch_all_a_stocks_async
        engine = get_news_engine()
        news = await engine.fetch_latest_news(60)
        try:
            stocks = await fetch_all_a_stocks_async()
        except Exception:
            stocks = None
        indices_data = None
        try:
            fetcher = request.app.state.fetcher
            overview = await fetcher.get_market_overview()
            indices_data = {**overview.get("cn_indices", {}), **overview.get("hk_indices", {}), **overview.get("us_indices", {})}
        except Exception:
            pass
        sentiment = engine.compute_market_sentiment(news, stocks, indices_data)
        summary = engine.get_news_summary(news)
        return _json_response(True, data={
            "sentiment": {
                "fear_greed_index": sentiment.fear_greed_index,
                "label": sentiment.label,
                "news_sentiment": sentiment.news_sentiment,
                "volume_sentiment": sentiment.volume_sentiment,
                "momentum_sentiment": sentiment.momentum_sentiment,
                "breadth_sentiment": sentiment.breadth_sentiment,
                "timestamp": sentiment.timestamp,
            },
            "summary": summary,
        })
    except Exception as e:
        logger.error(f"Sentiment error: {e}")
        return _json_response(False, error=safe_error(e))


@feature_router.get("/screener/presets")
async def get_screener_presets(request: Request):
    try:
        from core.stock_screener import get_stock_screener
        screener = get_stock_screener()
        return _json_response(True, data=screener.list_presets())
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@feature_router.get("/screener/run")
async def run_stock_screener(
    request: Request,
    preset: Optional[str] = Query(None),
    sort_by: str = Query("change_pct"),
    sort_desc: bool = Query(True),
    limit: int = Query(50),
):
    limit = _clamp(limit, 1, 200)
    try:
        from core.stock_screener import get_stock_screener
        from core.market_data import fetch_all_a_stocks_async
        screener = get_stock_screener()
        stocks = await fetch_all_a_stocks_async()
        if not stocks:
            return _json_response(False, error="无法获取股票数据")
        results = await screener.screen_with_enrichment(
            stocks,
            preset_id=preset,
            sort_by=sort_by,
            sort_desc=sort_desc,
            limit=limit,
        )
        return _json_response(True, data={"total": len(results), "stocks": results})
    except Exception as e:
        logger.error(f"Screener run error: {e}")
        return _json_response(False, error=safe_error(e))


_VALID_SORT_FIELDS = {"change_pct", "volume_ratio", "turnover_rate", "pe", "pb", "market_cap", "price"}
_VALID_SCREENER_FIELDS = {
    "change_pct", "volume_ratio", "turnover_rate", "pe", "pb", "market_cap",
    "price", "pct_5d", "pct_20d", "high_60d_ratio", "roe", "dividend_yield",
    "revenue_yoy", "amount", "volume",
}

@feature_router.post("/screener/custom")
async def run_custom_screener(request: Request):
    try:
        body = await request.json()
        conditions = body.get("conditions", [])
        if not isinstance(conditions, list) or len(conditions) > 20:
            return _json_response(False, error="筛选条件格式无效")
        for cond in conditions:
            if not isinstance(cond, dict) or "field" not in cond:
                return _json_response(False, error="筛选条件缺少field字段")
            if cond["field"] not in _VALID_SCREENER_FIELDS:
                return _json_response(False, error=f"不支持的字段: {cond['field']}")
        sort_by = body.get("sort_by", "change_pct")
        if sort_by not in _VALID_SORT_FIELDS:
            sort_by = "change_pct"
        sort_desc = bool(body.get("sort_desc", True))
        limit = _clamp(int(body.get("limit", 50)), 1, 200)

        from core.stock_screener import get_stock_screener
        from core.market_data import fetch_all_a_stocks_async
        screener = get_stock_screener()
        stocks = await fetch_all_a_stocks_async()
        if not stocks:
            return _json_response(False, error="无法获取股票数据")
        results = await screener.screen_with_enrichment(
            stocks,
            custom_conditions=conditions,
            sort_by=sort_by,
            sort_desc=sort_desc,
            limit=limit,
        )
        return _json_response(True, data={"total": len(results), "stocks": results})
    except Exception as e:
        logger.error(f"Custom screener error: {e}")
        return _json_response(False, error=safe_error(e))


@feature_router.get("/moneyflow/stock/{symbol}")
async def get_stock_money_flow(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    days: int = Query(10),
):
    days = _clamp(days, 1, 60)
    try:
        from core.money_flow import get_money_flow_analyzer
        analyzer = get_money_flow_analyzer()
        data = await analyzer.get_stock_flow(symbol, days)
        if data.get("history"):
            pattern = analyzer.analyze_flow_pattern(data["history"])
            data["pattern"] = pattern
        return _json_response(True, data=data)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@feature_router.get("/market/snapshot")
async def get_market_snapshot(request: Request):
    try:
        from datetime import datetime
        from core.news_engine import get_market_sentiment
        from core.market_hours import MarketHours

        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "market_status": MarketHours.get_market_status("A"),
        }

        try:
            from core.data_fetcher import get_fetcher
            from core.market_data import _SH_INDICES

            fetcher = get_fetcher()
            indices = {}
            for code in ["000001", "399001", "399006", "000688"]:
                try:
                    data = await fetcher.fetch_realtime(code)
                    if data:
                        name = _SH_INDICES.get(code, code)
                        indices[name] = {
                            "code": code,
                            "price": round(data.get("price", 0), 2),
                            "change_pct": round(data.get("change_pct", 0), 2),
                        }
                except Exception:
                    pass
            snapshot["indices"] = indices
        except Exception:
            snapshot["indices"] = {}

        try:
            sentiment = await get_market_sentiment()
            snapshot["sentiment"] = {
                "score": round(sentiment.breadth_sentiment, 4),
                "label": "偏多" if sentiment.breadth_sentiment > 0 else "偏空",
            }
        except Exception:
            snapshot["sentiment"] = {"score": 0, "label": "中性"}

        return _json_response(True, data=snapshot)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@feature_router.get("/moneyflow/ranking")
async def get_money_flow_ranking(
    request: Request,
    sort_by: str = Query("main_net"),
    count: int = Query(30),
):
    count = _clamp(count, 1, 100)
    try:
        from core.money_flow import get_money_flow_analyzer
        analyzer = get_money_flow_analyzer()
        data = await analyzer.get_flow_ranking(sort_by=sort_by, count=count)
        return _json_response(True, data=data)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@feature_router.get("/moneyflow/sector")
async def get_sector_money_flow(request: Request):
    try:
        from core.money_flow import get_money_flow_analyzer
        analyzer = get_money_flow_analyzer()
        data = await analyzer.get_sector_flow()
        return _json_response(True, data=data)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@feature_router.get("/chip/{symbol}")
async def get_chip_distribution(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
):
    try:
        from core.chip_distribution import get_chip_analyzer
        from core.data_fetcher import get_fetcher
        fetcher = get_fetcher()
        df = await fetcher.get_history(symbol, period, "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")

        import numpy as np
        close = df["close"].astype(float).values
        high = df["high"].astype(float).values
        low = df["low"].astype(float).values
        volume = df["volume"].astype(float).values

        analyzer = get_chip_analyzer()
        chip = analyzer.analyze(close, high, low, volume)
        fire = analyzer.compute_chip_fire(close, high, low, volume)

        return _json_response(True, data={
            "symbol": symbol,
            "current_price": round(float(close[-1]), 2),
            "avg_cost": chip.avg_cost,
            "profit_ratio": chip.profit_ratio,
            "concentration": chip.concentration,
            "support_price": chip.support_price,
            "resistance_price": chip.resistance_price,
            "peak_price": chip.peak_price,
            "prices": chip.prices,
            "distribution": chip.distribution,
            "chip_bands": chip.chip_bands,
            "fire": fire,
        })
    except Exception as e:
        logger.error(f"Chip distribution error for {symbol}: {e}")
        return _json_response(False, error=safe_error(e))


@feature_router.get("/sector/strength")
async def get_sector_strength(request: Request, top_n: int = Query(20)):
    top_n = _clamp(top_n, 1, 100)
    try:
        from core.sector_rotation import get_sector_rotation_analyzer
        analyzer = get_sector_rotation_analyzer()
        data = await analyzer.get_sector_strength(top_n)
        return _json_response(True, data=data)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@feature_router.get("/sector/rotation")
async def get_sector_rotation(request: Request):
    try:
        from core.sector_rotation import get_sector_rotation_analyzer
        analyzer = get_sector_rotation_analyzer()
        snapshot = await analyzer.get_rotation_snapshot()
        trend = analyzer.get_rotation_trend()
        current = await analyzer.get_sector_strength(10)
        signals = analyzer.detect_rotation_signal(current)
        return _json_response(True, data={
            "snapshot": snapshot,
            "trend": trend,
            "signals": signals,
        })
    except Exception as e:
        logger.error(f"Sector rotation error: {e}")
        return _json_response(False, error=safe_error(e))


@feature_router.get("/sector/{sector_code}/stocks")
async def get_sector_stocks(request: Request, sector_code: str, count: int = Query(20)):
    count = _clamp(count, 1, 100)
    try:
        from core.sector_rotation import get_sector_rotation_analyzer
        analyzer = get_sector_rotation_analyzer()
        data = await analyzer.get_sector_detail(sector_code)
        return _json_response(True, data=data)
    except Exception as e:
        return _json_response(False, error=safe_error(e))
