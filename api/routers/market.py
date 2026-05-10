import asyncio
import json
import logging
import time
from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import APIRouter, Path, Query, Request

from api.connection_manager import _is_trading_hours, cache_response
from api.routers.models import FactorPipelineRequest
from api.utils import json_response as _json_response
from api.utils import rate_limiter, safe_error, validate_symbol
from core.data_fetcher import SmartDataFetcher, get_fetcher
from core.market_detector import MarketDetector
from core.market_hours import MarketHours

logger = logging.getLogger(__name__)
router = APIRouter()


BREADTH_INDICES = {
    "sh000001": "上证综指",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000688": "科创50",
    "sh000300": "沪深300",
    "sh000016": "上证50",
    "sz399005": "中小100",
}


def _period_to_history(period: str) -> str:
    period = (period or "1y").lower()
    if period in {"3m", "6m"}:
        return "1y"
    if period in {"3y", "5y", "all"}:
        return "all"
    return "1y"


def _regime_recommendation(regime) -> str:
    from core.regime_detector import MarketRegime
    recommendations = {
        MarketRegime.TRENDING_UP: "趋势上行，适合趋势跟踪策略",
        MarketRegime.TRENDING_DOWN: "趋势下行，建议减仓或对冲",
        MarketRegime.MEAN_REVERTING: "均值回归状态，适合反转策略",
        MarketRegime.HIGH_VOLATILITY: "高波动环境，注意风控，缩小仓位",
        MarketRegime.LOW_VOLATILITY: "低波动环境，可考虑突破策略",
        MarketRegime.SIDEWAYS: "横盘震荡，适合网格或区间交易",
        MarketRegime.UNKNOWN: "市场状态不明确，建议观望",
    }
    return recommendations.get(regime, "无建议")


@router.get("/market/overview")
@cache_response(15)
async def get_market_overview(request: Request):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        data = await fetcher.get_market_overview()
        try:
            breadth = await fetcher.get_market_breadth()
            data["market_breadth"] = breadth
        except Exception:
            data["market_breadth"] = None
        return _json_response(True, data=data)
    except Exception as e:
        logger.error("Market overview error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/market/status")
@cache_response(60)
async def get_market_status(request: Request):
    try:
        statuses = {}
        for market in ["A", "HK", "US"]:
            statuses[market] = MarketHours.get_market_status(market)
        return _json_response(True, data=statuses)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/market/regime/dashboard")
async def regime_dashboard(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    period: int = Query(120, ge=60, le=500, description="分析天数"),
):
    """市场状态仪表盘：批量扫描多标的市场状态，返回汇总统计和逐标的详情"""
    try:
        from core.regime_detector import RegimeDetector

        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            return _json_response(False, error="需要至少1个股票代码")
        if len(symbol_list) > 20:
            return _json_response(False, error="最多同时扫描20只股票")

        fetcher: SmartDataFetcher = request.app.state.fetcher
        detector = RegimeDetector()
        per_symbol: list[dict] = []
        regime_counts: dict[str, int] = {}

        _regime_sem = asyncio.Semaphore(4)

        async def _detect_one(sym: str) -> dict:
            async with _regime_sem:
                try:
                    df = await fetcher.get_history(sym, period="all", kline_type="daily", adjust="qfq")
                    if df is None or len(df) < 60:
                        return {"symbol": sym, "error": "数据不足"}
                    df = df.tail(period)
                    result = await asyncio.to_thread(detector.detect, df)
                    regime_val = result.current_regime.value
                    return {
                        "symbol": sym,
                        "regime": regime_val,
                        "confidence": round(result.confidence, 4),
                        "trend_strength": round(result.trend_strength, 4),
                        "volatility_level": round(result.volatility_level, 4),
                        "mean_reversion_score": round(result.mean_reversion_score, 4),
                        "recommended_strategy": detector._recommend_strategy(result),
                    }
                except (ValueError, KeyError, OSError) as e:
                    logger.debug("Regime detect failed for %s: %s", sym, e)
                    return {"symbol": sym, "error": str(e)}

        per_symbol = await asyncio.gather(*[_detect_one(sym) for sym in symbol_list])
        for entry in per_symbol:
            if "regime" in entry:
                regime_counts[entry["regime"]] = regime_counts.get(entry["regime"], 0) + 1

        total_scanned = sum(1 for s in per_symbol if "regime" in s)
        dominant_regime = max(regime_counts, key=regime_counts.get) if regime_counts else "unknown"
        avg_confidence = (
            sum(s["confidence"] for s in per_symbol if "confidence" in s) / total_scanned
            if total_scanned > 0 else 0.0
        )
        avg_volatility = (
            sum(s["volatility_level"] for s in per_symbol if "volatility_level" in s) / total_scanned
            if total_scanned > 0 else 0.0
        )

        return _json_response(True, data={
            "symbols_scanned": total_scanned,
            "dominant_regime": dominant_regime,
            "regime_distribution": regime_counts,
            "avg_confidence": round(avg_confidence, 4),
            "avg_volatility": round(avg_volatility, 4),
            "per_symbol": per_symbol,
            "period": period,
            "timestamp": time.time(),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/market/stocks")
@cache_response(30)
async def get_market_stocks(request: Request, market: str = Query("A"), limit: int = Query(5000, le=10000)):
    try:
        from core.market_data import fetch_all_a_stocks_async
        stocks = await fetch_all_a_stocks_async()
        if stocks:
            df_data = stocks
            if market == "sh":
                df_data = [s for s in df_data if s.get("symbol", "").startswith("6") and not s.get("symbol", "").startswith("688")]
            elif market == "sz":
                df_data = [s for s in df_data if s.get("symbol", "").startswith("0")]
            elif market == "cy":
                df_data = [s for s in df_data if s.get("symbol", "").startswith("3")]
            elif market == "kc":
                df_data = [s for s in df_data if s.get("symbol", "").startswith("688")]
            result = df_data[:limit]
            return _json_response(True, data=result)
    except Exception as e:
        logger.debug("Market stocks EastMoney error: %s", e)
    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
        if df is None or df.empty:
            return _json_response(True, data=[])
        col_map = {
            "代码": "symbol", "名称": "name", "最新价": "price",
            "涨跌额": "change", "涨跌幅": "change_pct", "成交量": "volume", "成交额": "amount",
            "换手率": "turnover_rate",
        }
        rename = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=rename)
        if "change" not in df.columns and "price" in df.columns and "change_pct" in df.columns:
            prev_close = df["price"] / (1 + df["change_pct"] / 100)
            df["change"] = (df["price"] - prev_close).round(2)
            df["change"] = df["change"].replace([np.inf, -np.inf], 0).fillna(0)
        if market == "sh":
            df = df[df["symbol"].str.startswith("6")]
        elif market == "sz":
            df = df[df["symbol"].str.startswith("0")]
        elif market == "cy":
            df = df[df["symbol"].str.startswith("3")]
        elif market == "kc":
            df = df[df["symbol"].str.startswith("688")]
        if "amount" in df.columns:
            df = df.sort_values("amount", ascending=False)
        df = df.head(limit)
        keep_cols = [c for c in ["symbol", "name", "price", "change", "change_pct", "volume", "amount", "turnover_rate"] if c in df.columns]
        result = df[keep_cols].fillna(0).to_dict("records")
        return _json_response(True, data=result)
    except Exception as e:
        logger.debug("Market stocks fallback: %s", e)
        return _json_response(True, data=[])


@router.get("/market/anomaly")
@cache_response(30)
async def get_market_anomaly(request: Request):
    try:
        from core.market_data import fetch_all_a_stocks_async
        stocks = await fetch_all_a_stocks_async()
        if not stocks:
            return _json_response(True, data=[])
        anomalies = []
        for s in stocks:
            change_pct = float(s.get("change_pct", 0) or 0)
            volume_ratio = float(s.get("volume_ratio", 0) or 0)
            reason = ""
            if change_pct > 9.8:
                reason = "涨停"
            elif change_pct < -9.8:
                reason = "跌停"
            elif change_pct > 8 and volume_ratio > 3:
                reason = "大涨放量"
            elif change_pct < -8 and volume_ratio > 3:
                reason = "大跌放量"
            elif change_pct > 5 and volume_ratio > 5:
                reason = "放量拉升"
            elif change_pct < -5 and volume_ratio > 5:
                reason = "放量下跌"
            if reason:
                anomalies.append({
                    "symbol": s.get("symbol", ""),
                    "name": s.get("name", ""),
                    "price": round(float(s.get("price", 0) or 0), 2),
                    "change_pct": round(change_pct, 2),
                    "volume_ratio": round(volume_ratio, 2),
                    "reason": reason,
                })
        anomalies.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        return _json_response(True, data=anomalies[:80])
    except Exception as e:
        logger.debug("Market anomaly error: %s", e)
        return _json_response(True, data=[])


@router.get("/market/heatmap")
@cache_response(30)
async def get_market_heatmap(request: Request, market: str = Query("A")):
    items = []
    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_board_industry_name_em)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                name = str(row.get("板块名称", row.get("名称", "")))
                pct = float(row.get("涨跌幅", 0) or 0)
                amount = float(row.get("成交额", row.get("总市值", 0)) or 0)
                lead = str(row.get("领涨股票", ""))
                items.append({
                    "name": name,
                    "change_pct": round(pct, 2),
                    "volume": 0,
                    "amount": amount,
                    "value": max(amount, 1),
                    "leading_stock": lead,
                })
    except Exception as e:
        logger.debug("Market heatmap akshare failed: %s", e)

    if not items:
        try:
            url = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
            import aiohttp

            from core.data_fetcher import get_aiohttp_session
            session = await get_aiohttp_session()
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    text = await resp.text()
            import re
            match = re.search(r'=\s*({.*})', text)
            if match:
                data = json.loads(match.group(1))
                for _key, val in data.items():
                    parts = val.split(',')
                    if len(parts) >= 6:
                        name = parts[1]
                        change_pct = float(parts[5]) if parts[5] else 0
                        amount = float(parts[7]) if len(parts) > 7 and parts[7] else 0
                        items.append({
                            "name": name,
                            "change_pct": round(change_pct, 2),
                            "volume": 0,
                            "amount": amount,
                            "value": max(amount, 1),
                            "leading_stock": parts[11] if len(parts) > 11 else "",
                        })
        except Exception as e2:
            logger.debug("Market heatmap sina fallback failed: %s", e2)

    if not items:
        items = [
            {"name": "银行", "change_pct": 0, "volume": 0, "amount": 1, "value": 1, "leading_stock": ""},
            {"name": "科技", "change_pct": 0, "volume": 0, "amount": 1, "value": 1, "leading_stock": ""},
        ]

    return _json_response(True, data={"market": market, "items": items, "timestamp": time.time()})


@router.get("/market/northbound/detail")
@cache_response(60)
async def get_northbound_detail(request: Request):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        data = await fetcher.fetch_north_bound_flow()
        if data:
            sh_buy = data.get("sh_buy", 0)
            sh_sell = data.get("sh_sell", 0)
            sz_buy = data.get("sz_buy", 0)
            sz_sell = data.get("sz_sell", 0)
            sh_inflow = sh_buy - sh_sell
            sz_inflow = sz_buy - sz_sell
            data["sh_inflow"] = sh_inflow
            data["sz_inflow"] = sz_inflow
            data["net_inflow"] = data.get("total_net", sh_inflow + sz_inflow)
        return _json_response(True, data=data)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/market/limit_up")
@cache_response(60)
async def get_limit_up_pool(request: Request):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        return _json_response(True, data=await fetcher.fetch_limit_up_pool())
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/market/dragon_tiger")
@cache_response(300)
async def get_dragon_tiger(request: Request, date: str | None = None):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        return _json_response(True, data=await fetcher.fetch_dragon_tiger_list(date))
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/factor/analysis/{symbol}")
async def get_factor_analysis(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"), period: str = Query("1y", max_length=5)):
    try:
        from core.indicators import (
            calc_composite_score,
            calc_factor_efficiency_ratio,
            calc_factor_momentum_quality,
            calc_factor_money_flow_index,
            calc_factor_relative_volume,
            calc_factor_volume_price_trend,
        )
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 80:
            return _json_response(False, error="数据不足")
        h = df["high"].astype(float).values
        low = df["low"].astype(float).values
        c = df["close"].astype(float).values
        v = df["volume"].astype(float).values
        factors = {
            "momentum_quality": calc_factor_momentum_quality(c, v),
            "efficiency_ratio": calc_factor_efficiency_ratio(c),
            "relative_volume": calc_factor_relative_volume(v),
            "money_flow_index": calc_factor_money_flow_index(h, low, c, v),
            "volume_price_trend": calc_factor_volume_price_trend(c, v),
        }
        composite = calc_composite_score(factors)
        current = {}
        for name, arr in factors.items():
            valid = arr[np.isfinite(arr)]
            value = float(valid[-1]) if len(valid) else 0.0
            pct_rank = float((valid < value).mean()) if len(valid) else 0.5
            current[name] = {"value": round(value, 4), "percentile": round(pct_rank, 4), "direction": "bullish" if pct_rank >= 0.55 else "bearish" if pct_rank <= 0.45 else "neutral"}
        return _json_response(True, data={
            "factors": current,
            "composite_score": round(float(composite[-1]), 4) if len(composite) else 0,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.post("/factor/pipeline")
async def run_factor_pipeline(request: Request, body: FactorPipelineRequest):
    try:
        from core.factor_pipeline import full_factor_pipeline
        from core.indicators import (
            calc_factor_efficiency_ratio,
            calc_factor_momentum_quality,
            calc_factor_money_flow_index,
            calc_factor_relative_volume,
            calc_factor_volume_price_trend,
        )

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(body.symbol, _period_to_history(body.period), "daily", "qfq")
        if df.empty or len(df) < 80:
            return _json_response(False, error="数据不足")

        h = df["high"].astype(float).values
        low = df["low"].astype(float).values
        c = df["close"].astype(float).values
        v = df["volume"].astype(float).values

        factor_df = pd.DataFrame({
            "momentum_quality": calc_factor_momentum_quality(c, v),
            "efficiency_ratio": calc_factor_efficiency_ratio(c),
            "relative_volume": calc_factor_relative_volume(v),
            "money_flow_index": calc_factor_money_flow_index(h, low, c, v),
            "volume_price_trend": calc_factor_volume_price_trend(c, v),
        })

        industry_labels = None
        market_cap = None

        processed = full_factor_pipeline(
            factor_df,
            industry_labels=industry_labels,
            market_cap=market_cap,
            winsorize_bounds=(body.winsorize_lower, body.winsorize_upper),
            neutralize_method=body.neutralize_method,
        )

        latest_row = processed.iloc[-1] if len(processed) > 0 else {}
        result_factors = {}
        for col in processed.columns:
            val = float(latest_row[col]) if col in latest_row.index else 0.0
            result_factors[col] = round(val, 6) if np.isfinite(val) else 0.0

        return _json_response(True, data={
            "symbol": body.symbol,
            "factors_raw": {col: round(float(factor_df[col].iloc[-1]), 6) if len(factor_df) > 0 and np.isfinite(factor_df[col].iloc[-1]) else 0.0 for col in factor_df.columns},
            "factors_processed": result_factors,
            "pipeline_config": {
                "winsorize_bounds": [body.winsorize_lower, body.winsorize_upper],
                "neutralize_method": body.neutralize_method,
                "industry_neutralize": body.industry_neutralize,
                "market_cap_neutralize": body.market_cap_neutralize,
                "orthogonalize": body.orthogonalize,
            },
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/market/breadth")
async def get_market_breadth(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码"),
    period: str = Query("1y", max_length=5),
    ma_period: int = Query(50, ge=5, le=200, description="均线周期"),
):
    """市场宽度分析：涨跌家数、站上均线占比、麦克莱伦振荡器"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if len(symbol_list) < 5:
            return _json_response(False, error="至少需要5个股票代码进行宽度分析")
        symbol_list = symbol_list[:50]
        history_map = await fetcher.get_history_batch(
            symbol_list, _period_to_history(period), "daily", "qfq"
        )
        price_changes = {}
        price_data = {}
        for sym, df in history_map.items():
            if len(df) < 2:
                continue
            close = df["close"].astype(float)
            change_pct = (close.iloc[-1] / close.iloc[-2] - 1) * 100
            price_changes[sym] = float(change_pct)
            price_data[sym] = close
        if len(price_changes) < 5:
            return _json_response(False, error="有效数据不足")
        from core.market_breadth import get_market_breadth_analyzer
        analyzer = get_market_breadth_analyzer()
        ad_result = analyzer.compute_advance_decline(price_changes)
        pct_above_result = analyzer.compute_percent_above_ma(price_data, ma_period)
        return _json_response(True, data={
            "advance_decline": ad_result,
            "percent_above_ma": pct_above_result,
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/market/regime")
async def get_market_regime(
    request: Request,
    symbol: str = Query(..., description="股票代码"),
    period: int = Query(120, ge=60, le=500, description="分析天数"),
):
    """市场状态检测"""
    try:
        from core.regime_detector import RegimeDetector

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period="all", kline_type="daily", adjust="qfq")
        if df is None or len(df) < 60:
            return _json_response(False, error="数据不足，至少需要60个交易日")

        df = df.tail(period)
        detector = RegimeDetector()
        result = await asyncio.to_thread(detector.detect, df)

        regime_history = [
            {"regime": r.value, "index": i}
            for i, r in enumerate(result.regime_history[-30:])
        ]

        return _json_response(True, data={
            "symbol": symbol,
            "current_regime": result.current_regime.value,
            "confidence": round(result.confidence, 4),
            "trend_strength": round(result.trend_strength, 4),
            "volatility_level": round(result.volatility_level, 4),
            "mean_reversion_score": round(result.mean_reversion_score, 4),
            "transition_probabilities": {
                k: round(v, 4) for k, v in result.transition_probabilities.items()
            },
            "regime_history": regime_history,
            "recommendation": _regime_recommendation(result.current_regime),
        })
    except Exception as e:
        logger.error("Market regime error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/market/events")
@cache_response(15)
async def get_market_events(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
):
    try:
        events = []

        try:
            from core.market_data import fetch_all_a_stocks_async
            stocks = await fetch_all_a_stocks_async()
            if stocks:
                limit_ups = [s for s in stocks if s.get("change_pct", 0) >= 9.5][:5]
                for s in limit_ups:
                    events.append({
                        "type": "limit_up",
                        "symbol": s.get("symbol", ""),
                        "name": s.get("name", ""),
                        "change_pct": round(s.get("change_pct", 0), 2),
                        "price": s.get("price", 0),
                        "volume": s.get("volume", 0),
                        "timestamp": time.time(),
                    })

                limit_downs = [s for s in stocks if s.get("change_pct", 0) <= -9.5][:5]
                for s in limit_downs:
                    events.append({
                        "type": "limit_down",
                        "symbol": s.get("symbol", ""),
                        "name": s.get("name", ""),
                        "change_pct": round(s.get("change_pct", 0), 2),
                        "price": s.get("price", 0),
                        "volume": s.get("volume", 0),
                        "timestamp": time.time(),
                    })

                volume_spikes = sorted(
                    [s for s in stocks if s.get("volume_ratio", 0) >= 3],
                    key=lambda x: x.get("volume_ratio", 0),
                    reverse=True,
                )[:5]
                for s in volume_spikes:
                    events.append({
                        "type": "volume_spike",
                        "symbol": s.get("symbol", ""),
                        "name": s.get("name", ""),
                        "change_pct": round(s.get("change_pct", 0), 2),
                        "volume_ratio": round(s.get("volume_ratio", 0), 1),
                        "price": s.get("price", 0),
                        "timestamp": time.time(),
                    })
        except Exception as e:
            logger.debug("获取市场事件数据失败: %s", e)

        events.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return _json_response(True, data=events[:limit])
    except Exception as e:
        logger.error("market events error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


@router.get("/market/breadth/indices")
async def get_market_breadth_indices(
    request: Request,
    period: str = Query("5d", max_length=5),
):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher

        breadth_data = {}
        advancing = 0
        declining = 0
        total_volume_up = 0.0
        total_volume_down = 0.0

        for code, name in BREADTH_INDICES.items():
            try:
                df = await fetcher.get_history(code, _period_to_history(period), "daily", "")
                if df.empty or len(df) < 2:
                    continue
                close = df["close"].astype(float)
                volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series([0])
                latest_close = close.iloc[-1]
                prev_close = close.iloc[-2]
                change_pct = (latest_close - prev_close) / prev_close * 100 if prev_close > 0 else 0

                breadth_data[code] = {
                    "name": name,
                    "close": round(float(latest_close), 2),
                    "change_pct": round(float(change_pct), 2),
                }

                if change_pct > 0:
                    advancing += 1
                    if "volume" in df.columns:
                        total_volume_up += float(volume.iloc[-1])
                elif change_pct < 0:
                    declining += 1
                    if "volume" in df.columns:
                        total_volume_down += float(volume.iloc[-1])
            except Exception as e:
                logger.debug("Breadth calc failed for %s: %s", code, e)
                continue

        total_idx = advancing + declining + (len(breadth_data) - advancing - declining)
        ad_ratio = advancing / max(declining, 1)
        breadth_pct = advancing / max(total_idx, 1) * 100
        breadth_signal = "bullish" if breadth_pct >= 60 else ("bearish" if breadth_pct <= 40 else "neutral")

        volume_ratio = total_volume_up / max(total_volume_down, 1.0) if total_volume_down > 0 else 1.0

        return _json_response(True, data={
            "indices": breadth_data,
            "breadth": {
                "advancing": advancing,
                "declining": declining,
                "ad_ratio": round(float(ad_ratio), 2),
                "breadth_pct": round(float(breadth_pct), 1),
                "signal": breadth_signal,
                "up_volume_ratio": round(float(volume_ratio), 2),
            },
            "period": period,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error("Market breadth error: %s", e)
        return _json_response(False, error=safe_error(e))
