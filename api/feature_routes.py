"""
QuantCore 新功能API路由模块
资讯、选股器、资金流向、筹码分布、板块轮动
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import APIRouter, Path, Query, Request, WebSocket, WebSocketDisconnect

from api.utils import json_response as _json_response
from api.utils import rate_limiter, safe_error

logger = logging.getLogger(__name__)

feature_router = APIRouter()


@dataclass(frozen=True)
class FeatureConfig:
    registry_cache_ttl: int = 300
    ic_analysis_rate_limit: int = 10
    optimize_rate_limit: int = 10
    ml_train_rate_limit: int = 5
    ml_meta_label_rate_limit: int = 5
    ml_drift_rate_limit: int = 10
    rate_limit_window: float = 60.0
    min_observations: int = 10
    min_prices: int = 3


_cfg = FeatureConfig()


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _has_nan_inf(series: pd.Series) -> bool:
    return bool(series.isna().any()) or bool(np.isinf(series.values).any())


@feature_router.get("/news/latest")
async def get_latest_news(request: Request, count: int = Query(40)):
    count = _clamp(count, 1, 200)
    try:
        from core.news_engine import get_news_engine
        engine = get_news_engine()
        news = await engine.fetch_latest_news(count)
        return _json_response(True, data=news)
    except Exception as e:
        logger.error("News latest error: %s", e)
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
        logger.error("Stock news error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.get("/news/sentiment")
async def get_market_sentiment(request: Request):
    try:
        from core.market_data import fetch_all_a_stocks_async
        from core.news_engine import get_news_engine
        engine = get_news_engine()
        news = await engine.fetch_latest_news(60)
        try:
            stocks = await fetch_all_a_stocks_async()
        except Exception as e:
            logger.warning("获取A股列表失败: %s", e)
            stocks = None
        indices_data = None
        try:
            fetcher = request.app.state.fetcher
            overview = await fetcher.get_market_overview()
            indices_data = {**overview.get("cn_indices", {}), **overview.get("hk_indices", {}), **overview.get("us_indices", {})}
        except Exception as e:
            logger.warning("获取指数数据失败: %s", e)
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
        logger.error("Sentiment error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.get("/screener/presets")
async def get_screener_presets(request: Request):
    try:
        from core.stock_screener import get_stock_screener
        screener = get_stock_screener()
        return _json_response(True, data=screener.list_presets())
    except Exception as e:
        logger.error("Screener presets error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.get("/screener/run")
async def run_stock_screener(
    request: Request,
    preset: str | None = Query(None),
    sort_by: str = Query("change_pct"),
    sort_desc: bool = Query(True),
    limit: int = Query(50),
):
    limit = _clamp(limit, 1, 200)
    try:
        from core.market_data import fetch_all_a_stocks_async
        from core.stock_screener import get_stock_screener
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
        logger.error("Screener run error: %s", e)
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

        from core.market_data import fetch_all_a_stocks_async
        from core.stock_screener import get_stock_screener
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
        logger.error("Custom screener error: %s", e)
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
        logger.error("Money flow stock error for %s: %s", symbol, e)
        return _json_response(False, error=safe_error(e))


@feature_router.get("/market/snapshot")
async def get_market_snapshot(request: Request):
    try:
        from datetime import datetime

        from core.market_hours import MarketHours
        from core.news_engine import get_market_sentiment

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
                except Exception as e:
                    logger.debug("获取指数实时数据失败 %s: %s", code, e)
            snapshot["indices"] = indices
        except Exception as e:
            logger.warning("获取市场快照指数失败: %s", e)
            snapshot["indices"] = {}

        try:
            sentiment = await get_market_sentiment()
            snapshot["sentiment"] = {
                "score": round(sentiment.breadth_sentiment, 4),
                "label": "偏多" if sentiment.breadth_sentiment > 0 else "偏空",
            }
        except Exception as e:
            logger.warning("获取市场情绪失败: %s", e)
            snapshot["sentiment"] = {"score": 0, "label": "中性"}

        return _json_response(True, data=snapshot)
    except Exception as e:
        logger.error("Market snapshot error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.get("/moneyflow/ranking")
async def get_money_flow_ranking(
    request: Request,
    sort_by: str = Query("main_net"),
    count: int = Query(30),
):
    count = _clamp(count, 1, 100)
    _valid_flow_sort = {"main_net", "super_large_net", "large_net", "medium_net", "small_net", "change_pct", "volume", "amount"}
    if sort_by not in _valid_flow_sort:
        sort_by = "main_net"
    try:
        from core.money_flow import get_money_flow_analyzer
        analyzer = get_money_flow_analyzer()
        data = await analyzer.get_flow_ranking(sort_by=sort_by, count=count)
        return _json_response(True, data=data)
    except Exception as e:
        logger.error("资金流向排名获取失败: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.get("/moneyflow/sector")
async def get_sector_money_flow(request: Request):
    try:
        from core.money_flow import get_money_flow_analyzer
        analyzer = get_money_flow_analyzer()
        data = await analyzer.get_sector_flow()
        return _json_response(True, data=data)
    except Exception as e:
        logger.error("Sector money flow error: %s", e)
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
        logger.error("Chip distribution error for %s: %s", symbol, e)
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
        logger.error("Sector strength error: %s", e)
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
        logger.error("Sector rotation error: %s", e)
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
        logger.error("Sector detail error for %s: %s", sector_code, e)
        return _json_response(False, error=safe_error(e))


# Strategy Optimization & Stress Test endpoints
@feature_router.get("/strategy/param-specs")
async def get_param_specs(request: Request):
    try:
        from core.param_optimizer import get_param_specs
        specs = get_param_specs()
        return _json_response(True, data={"strategies": specs})
    except Exception as e:
        logger.error("Param specs error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/strategy/optimize-params")
async def optimize_params(
    request: Request,
    strategy_name: str = Query(...),
    symbol: str = Query(...),
    metric: str = Query("sharpe_ratio"),
    period: str = Query("1y"),
    max_combos: int = Query(200),
):
    try:
        from core.data_fetcher import get_fetcher
        from core.param_optimizer import run_param_optimization
        fetcher = get_fetcher()
        df = await fetcher.get_history(symbol, period, "daily", "qfq")
        if df.empty:
            return _json_response(False, error=f"No data available for {symbol}")

        result = run_param_optimization(strategy_name, df, metric, max_combos)
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Optimize params error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/stress-test")
async def stress_test(
    request: Request,
    symbol: str = Query(...),
    period: str = Query("1y"),
    scenarios: str = Query(None),
):
    try:
        from core.data_fetcher import get_fetcher
        from core.param_optimizer import run_stress_test
        fetcher = get_fetcher()
        df = await fetcher.get_history(symbol, period, "daily", "qfq")
        if df.empty:
            return _json_response(False, error=f"No data available for {symbol}")

        scenario_list = scenarios.split(",") if scenarios else None
        result = run_stress_test(df, [symbol], scenario_list)
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Stress test error: %s", e)
        return _json_response(False, error=safe_error(e))


# Volatility endpoints
@feature_router.get("/volatility/garch/{symbol}")
async def get_garch(
    request: Request,
    symbol: str,
    period: str = Query("1y"),
):
    try:
        from core.data_fetcher import get_fetcher
        from core.volatility import fit_garch
        fetcher = get_fetcher()
        df = await fetcher.get_history(symbol, period, "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error=f"Insufficient data available for {symbol}")

        close_prices = df["close"].values
        returns = (close_prices[1:] / close_prices[:-1]) - 1
        result = fit_garch(returns)
        if "error" in result:
            return _json_response(False, error=result["error"])
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("GARCH error: %s", e)
        return _json_response(False, error=safe_error(e))


# Regime detection endpoints
@feature_router.get("/regime/hmm/{symbol}")
async def get_hmm(
    request: Request,
    symbol: str,
    period: str = Query("1y"),
    n_states: int = Query(3),
):
    try:
        from core.data_fetcher import get_fetcher
        from core.volatility import detect_regime_hmm
        fetcher = get_fetcher()
        df = await fetcher.get_history(symbol, period, "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error=f"Insufficient data available for {symbol}")

        close_prices = df["close"].values
        returns = (close_prices[1:] / close_prices[:-1]) - 1
        result = detect_regime_hmm(returns, n_states)
        if "error" in result:
            return _json_response(False, error=result["error"])
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("HMM error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.get("/rolling-risk/{symbol}")
async def get_rolling_risk(
    request: Request,
    symbol: str,
    period: str = Query("1y"),
    window: int = Query(60),
):
    try:
        from core.data_fetcher import get_fetcher
        from core.metrics import RollingRiskTracker
        fetcher = get_fetcher()
        df = await fetcher.get_history(symbol, period, "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error=f"Insufficient data for {symbol}")

        window = _clamp(window, 10, 252)
        tracker = RollingRiskTracker(window=window)
        snapshots = []
        for i in range(len(df)):
            equity = float(df["close"].iloc[i])
            snap = tracker.update(equity)
            if i >= window:
                snapshots.append({
                    "date": str(df["date"].iloc[i])[:10] if "date" in df.columns else i,
                    "sharpe": snap.sharpe,
                    "sortino": snap.sortino,
                    "calmar": snap.calmar,
                    "volatility": snap.volatility,
                    "max_drawdown": snap.max_drawdown,
                    "var_95": snap.var_95,
                    "cvar_95": snap.cvar_95,
                    "win_rate": snap.win_rate,
                })

        latest = tracker.snapshot()
        return _json_response(True, data={
            "symbol": symbol,
            "window": window,
            "latest": {
                "sharpe": latest.sharpe,
                "sortino": latest.sortino,
                "calmar": latest.calmar,
                "volatility": latest.volatility,
                "max_drawdown": latest.max_drawdown,
                "var_95": latest.var_95,
                "cvar_95": latest.cvar_95,
                "win_rate": latest.win_rate,
            },
            "history": snapshots[-60:] if len(snapshots) > 60 else snapshots,
        })
    except Exception as e:
        logger.error("Rolling risk error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.get("/seasonality/{symbol}")
async def get_seasonality(symbol: str, period: str = "1y"):
    try:
        from core.data_fetcher import get_fetcher
        from core.seasonality import analyze_seasonality

        fetcher = get_fetcher()
        df = await fetcher.get_history(symbol, period=period, kline_type="daily", adjust="qfq")
        if df is None or df.empty:
            return _json_response(False, error="数据不足")

        report = analyze_seasonality(df, symbol=symbol, period=period)
        return _json_response(True, data=report.to_dict())
    except Exception as e:
        logger.error("Seasonality analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/correlation/matrix")
async def get_correlation_matrix(request: Request):
    try:
        body = await request.json()
        symbols = body.get("symbols", [])
        period = body.get("period", "6m")
        window = body.get("window", 60)

        if not symbols or len(symbols) < 2:
            return _json_response(False, error="At least 2 symbols required")
        if len(symbols) > 50:
            symbols = symbols[:50]

        from core.data_fetcher import get_fetcher
        fetcher = get_fetcher()

        price_data = {}
        for sym in symbols:
            try:
                df = await fetcher.get_history(sym, period, "daily", "qfq")
                if df is not None and len(df) >= window:
                    price_data[sym] = df["close"].values.astype(float)
            except (ValueError, KeyError, TypeError) as e:
                logger.debug("Correlation data fetch failed for %s: %s", sym, e)
                continue

        if len(price_data) < 2:
            return _json_response(False, error="Insufficient data for correlation")

        min_len = min(len(v) for v in price_data.values())
        aligned = {sym: v[-min_len:] for sym, v in price_data.items()}
        names = list(aligned.keys())
        returns = np.array([np.diff(aligned[sym]) / np.where(aligned[sym][:-1] > 0, aligned[sym][:-1], 1) for sym in names])

        corr = np.corrcoef(returns)
        matrix = {}
        for i, sym_i in enumerate(names):
            matrix[sym_i] = {}
            for j, sym_j in enumerate(names):
                val = float(corr[i, j]) if np.isfinite(corr[i, j]) else 0.0
                matrix[sym_i][sym_j] = round(val, 4)

        rolling_corr = None
        if window > 0 and min_len > window:
            ret_window = returns[:, -window:]
            rc = np.corrcoef(ret_window)
            rolling_corr = {}
            for i, sym_i in enumerate(names):
                rolling_corr[sym_i] = {}
                for j, sym_j in enumerate(names):
                    val = float(rc[i, j]) if np.isfinite(rc[i, j]) else 0.0
                    rolling_corr[sym_i][sym_j] = round(val, 4)

        return _json_response(True, data={
            "symbols": names,
            "period": period,
            "full_correlation": matrix,
            "rolling_correlation": rolling_corr,
            "rolling_window": window if rolling_corr else None,
        })
    except Exception as e:
        logger.error("Correlation matrix error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/portfolio/risk-attribution")
async def portfolio_risk_attribution(request: Request):
    try:
        body = await request.json()
        holdings = body.get("holdings", [])
        period = body.get("period", "1y")

        if not holdings or len(holdings) < 1:
            return _json_response(False, error="At least 1 holding required")
        if len(holdings) > 30:
            holdings = holdings[:30]

        from core.data_fetcher import get_fetcher
        fetcher = get_fetcher()

        price_data = {}
        weights = {}
        total_weight = sum(h.get("weight", 0) for h in holdings)
        if total_weight <= 0:
            total_weight = 1.0

        for h in holdings:
            sym = h.get("symbol", "")
            w = h.get("weight", 1.0 / len(holdings))
            if not sym:
                continue
            try:
                df = await fetcher.get_history(sym, period, "daily", "qfq")
                if df is not None and len(df) >= 30:
                    price_data[sym] = df["close"].values.astype(float)
                    weights[sym] = w / total_weight
            except (ValueError, KeyError, TypeError) as e:
                logger.debug("Risk attribution data fetch failed for %s: %s", sym, e)
                continue

        if len(price_data) < 1:
            return _json_response(False, error="Insufficient data for risk attribution")

        min_len = min(len(v) for v in price_data.values())
        names = list(price_data.keys())
        aligned = {sym: price_data[sym][-min_len:] for sym in names}
        w_arr = np.array([weights.get(sym, 0) for sym in names])

        returns = np.array([
            np.diff(aligned[sym]) / np.where(aligned[sym][:-1] > 0, aligned[sym][:-1], 1)
            for sym in names
        ])

        port_ret = w_arr @ returns
        port_vol = float(np.std(port_ret) * np.sqrt(252))

        marginal_risk = []
        for i, sym in enumerate(names):
            sym_vol = float(np.std(returns[i]) * np.sqrt(252))
            if port_vol > 1e-12:
                corr = float(np.corrcoef(returns[i], port_ret)[0, 1]) if len(returns[i]) > 1 else 0.0
                if not np.isfinite(corr):
                    corr = 0.0
                marginal = corr * sym_vol / port_vol * float(w_arr[i])
            else:
                marginal = 0.0
            marginal_risk.append({
                "symbol": sym,
                "weight": round(float(w_arr[i]), 4),
                "individual_vol": round(sym_vol, 6),
                "correlation_to_portfolio": round(corr if port_vol > 1e-12 else 0.0, 4),
                "marginal_risk_contribution": round(marginal, 6),
            })

        marginal_risk.sort(key=lambda x: abs(x["marginal_risk_contribution"]), reverse=True)

        return _json_response(True, data={
            "portfolio_volatility": round(port_vol, 6),
            "n_holdings": len(names),
            "risk_decomposition": marginal_risk,
        })
    except Exception as e:
        logger.error("Risk attribution error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.get("/drawdown/analysis/{symbol}")
async def drawdown_analysis(
    request: Request,
    symbol: str,
    period: str = Query("1y"),
    top_n: int = Query(5),
):
    try:
        from core.data_fetcher import get_fetcher
        from core.metrics import analyze_drawdowns
        fetcher = get_fetcher()
        df = await fetcher.get_history(symbol, period, "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error=f"Insufficient data for {symbol}")

        top_n = _clamp(top_n, 1, 20)
        equity_curve = (df["close"] / df["close"].iloc[0] * 100000).tolist()
        result = analyze_drawdowns(equity_curve, top_n=top_n)

        return _json_response(True, data={
            "symbol": symbol,
            "period": period,
            **result,
        })
    except Exception as e:
        logger.error("Drawdown analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/pipeline/signal")
async def pipeline_signal(
    request: Request,
    symbol: str = Query(...),
    period: str = Query("6m"),
    fusion: str = Query("weighted_vote"),
):
    try:
        from core.data_fetcher import get_fetcher
        from core.strategies import CompositeStrategy
        from core.strategy_pipeline import StrategyPipeline

        fetcher = get_fetcher()
        df = await fetcher.get_history(symbol, period, "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error=f"Insufficient data for {symbol}")

        composite = CompositeStrategy()
        pipeline = StrategyPipeline.from_composite(composite)
        pipeline.set_fusion_method(fusion)

        result = pipeline.run(df)

        return _json_response(True, data={
            "symbol": symbol,
            "period": period,
            "fusion_method": fusion,
            "signal": {
                "type": result.final_signal.signal_type.value,
                "strength": result.final_signal.strength,
                "reason": result.final_signal.reason,
            },
            "indicators_computed": result.indicators_computed,
            "strategies_run": result.strategies_run,
            "stages_executed": result.stages_executed,
            "contributing_strategies": {
                name: {
                    "type": sig.signal_type.value,
                    "strength": sig.strength,
                }
                for name, sig in result.strategy_signals.items()
            },
        })
    except Exception as e:
        logger.error("Pipeline signal error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.get("/pipeline/registry")
async def pipeline_registry(request: Request):
    try:
        from core.strategy_pipeline import list_registered_strategies
        registry = list_registered_strategies()
        return _json_response(True, data={
            "registered_count": len(registry),
            "strategies": registry,
        })
    except Exception as e:
        logger.error("Pipeline registry error: %s", e)
        return _json_response(False, error=safe_error(e))


# Portfolio Optimization endpoints
@feature_router.post("/portfolio/optimize")
async def optimize_portfolio(request: Request):
    try:
        body = await request.json()
        symbols = body.get("symbols", [])
        optimization_method = body.get("method", "max_sharpe")
        risk_free_rate = float(body.get("risk_free_rate", 0.03))
        min_weight = float(body.get("min_weight", 0.0))
        max_weight = float(body.get("max_weight", 1.0))
        period = body.get("period", "1y")
        fixed_weights = body.get("fixed_weights", {})

        if not symbols or len(symbols) < 2:
            return _json_response(False, error="At least 2 symbols required")
        if len(symbols) > 50:
            symbols = symbols[:50]

        from core.data_fetcher import get_fetcher
        from core.portfolio_theory import ModernPortfolioTheory

        fetcher = get_fetcher()
        price_data = {}

        for sym in symbols:
            try:
                df = await fetcher.get_history(sym, period, "daily", "qfq")
                if df is not None and len(df) >= 10:
                    price_data[sym] = df["close"].values.astype(float)
            except (ValueError, KeyError, TypeError) as e:
                logger.debug("Portfolio data fetch failed for %s: %s", sym, e)
                continue

        if len(price_data) < 2:
            return _json_response(False, error="Insufficient data for portfolio optimization")

        min_len = min(len(v) for v in price_data.values())
        aligned_data = {sym: v[-min_len:] for sym, v in price_data.items()}

        import pandas as pd
        prices_df = pd.DataFrame(aligned_data)

        mpt = ModernPortfolioTheory(
            risk_free_rate=risk_free_rate,
            min_weight=min_weight,
            max_weight=max_weight,
        )

        if optimization_method == "max_sharpe":
            result = mpt.optimize_max_sharpe(prices_df, fixed_weights=fixed_weights)
        elif optimization_method == "min_volatility":
            result = mpt.optimize_min_volatility(prices_df, fixed_weights=fixed_weights)
        elif optimization_method == "risk_parity":
            result = mpt.optimize_risk_parity(prices_df, fixed_weights=fixed_weights)
        elif optimization_method == "equal_weight":
            result = mpt.optimize_equal_weight(prices_df)
        else:
            return _json_response(False, error=f"Unknown optimization method: {optimization_method}")

        if not result.is_valid:
            return _json_response(False, error=result.message)

        return _json_response(True, data={
            "method": optimization_method,
            "weights": {
                sym: round(w, 4) for sym, w in result.weights.items()
            },
            "expected_return": round(result.expected_return, 4),
            "expected_volatility": round(result.expected_volatility, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "diversification_ratio": round(result.diversification_ratio, 4),
        })
    except Exception as e:
        logger.error("Portfolio optimization error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/portfolio/efficient-frontier")
async def get_efficient_frontier(request: Request):
    try:
        body = await request.json()
        symbols = body.get("symbols", [])
        period = body.get("period", "1y")
        risk_free_rate = float(body.get("risk_free_rate", 0.03))
        n_points = int(body.get("n_points", 20))

        if not symbols or len(symbols) < 2:
            return _json_response(False, error="At least 2 symbols required")
        if len(symbols) > 50:
            symbols = symbols[:50]

        n_points = _clamp(n_points, 10, 100)

        from core.data_fetcher import get_fetcher
        from core.portfolio_theory import ModernPortfolioTheory

        fetcher = get_fetcher()
        price_data = {}

        for sym in symbols:
            try:
                df = await fetcher.get_history(sym, period, "daily", "qfq")
                if df is not None and len(df) >= 10:
                    price_data[sym] = df["close"].values.astype(float)
            except (ValueError, KeyError, TypeError) as e:
                logger.debug("Frontier data fetch failed for %s: %s", sym, e)
                continue

        if len(price_data) < 2:
            return _json_response(False, error="Insufficient data for efficient frontier")

        min_len = min(len(v) for v in price_data.values())
        aligned_data = {sym: v[-min_len:] for sym, v in price_data.items()}

        import pandas as pd
        prices_df = pd.DataFrame(aligned_data)

        mpt = ModernPortfolioTheory(risk_free_rate=risk_free_rate)
        frontier_points = mpt.generate_efficient_frontier(prices_df, n_points=n_points)

        # Get optimal portfolios
        max_sharpe = mpt.optimize_max_sharpe(prices_df)
        min_vol = mpt.optimize_min_volatility(prices_df)

        return _json_response(True, data={
            "symbols": list(price_data.keys()),
            "period": period,
            "risk_free_rate": risk_free_rate,
            "frontier": [
                {
                    "return": round(p["return"], 4),
                    "volatility": round(p["volatility"], 4),
                    "sharpe_ratio": round(p["sharpe_ratio"], 4),
                    "weights": {
                        sym: round(w, 4) for sym, w in p["weights"].items()
                    },
                }
                for p in frontier_points
            ],
            "optimal_portfolios": {
                "max_sharpe": {
                    "weights": {
                        sym: round(w, 4) for sym, w in max_sharpe.weights.items()
                    },
                    "return": round(max_sharpe.expected_return, 4),
                    "volatility": round(max_sharpe.expected_volatility, 4),
                    "sharpe_ratio": round(max_sharpe.sharpe_ratio, 4),
                } if max_sharpe.is_valid else None,
                "min_volatility": {
                    "weights": {
                        sym: round(w, 4) for sym, w in min_vol.weights.items()
                    },
                    "return": round(min_vol.expected_return, 4),
                    "volatility": round(min_vol.expected_volatility, 4),
                    "sharpe_ratio": round(min_vol.sharpe_ratio, 4),
                } if min_vol.is_valid else None,
            },
        })
    except Exception as e:
        logger.error("Efficient frontier error: %s", e)
        return _json_response(False, error=safe_error(e))


# Black-Litterman endpoints
@feature_router.post("/portfolio/black-litterman")
async def black_litterman_optimize(request: Request):
    try:
        body = await request.json()
        symbols = body.get("symbols", [])
        views = body.get("views", [])
        market_weights = body.get("market_weights", None)
        view_confidences = body.get("view_confidences", None)
        risk_free_rate = float(body.get("risk_free_rate", 0.03))
        tau = float(body.get("tau", 0.05))
        risk_aversion = float(body.get("risk_aversion", 2.5))
        period = body.get("period", "1y")

        if not symbols or len(symbols) < 2:
            return _json_response(False, error="At least 2 symbols required")
        if len(symbols) > 50:
            symbols = symbols[:50]

        from core.black_litterman import BlackLittermanModel
        from core.data_fetcher import get_fetcher

        fetcher = get_fetcher()
        price_data = {}

        for sym in symbols:
            try:
                df = await fetcher.get_history(sym, period, "daily", "qfq")
                if df is not None and len(df) >= 10:
                    price_data[sym] = df["close"].values.astype(float)
            except (ValueError, KeyError, TypeError) as e:
                logger.debug("BL data fetch failed for %s: %s", sym, e)
                continue

        if len(price_data) < 2:
            return _json_response(False, error="Insufficient data for Black-Litterman")

        min_len = min(len(v) for v in price_data.values())
        aligned_data = {sym: v[-min_len:] for sym, v in price_data.items()}

        import pandas as pd
        prices_df = pd.DataFrame(aligned_data)

        bl = BlackLittermanModel(
            risk_free_rate=risk_free_rate,
            tau=tau,
            risk_aversion=risk_aversion,
        )

        result = bl.optimize(
            prices=prices_df,
            views=views,
            market_weights=market_weights,
            view_confidences=view_confidences,
        )

        if not result.is_valid:
            return _json_response(False, error=result.message)

        return _json_response(True, data={
            "posterior_returns": {
                sym: round(ret, 6) for sym, ret in result.posterior_returns.items()
            },
            "weights": {
                sym: round(w, 4) for sym, w in result.weights.items()
            },
            "expected_return": round(result.expected_return, 4),
            "expected_volatility": round(result.expected_volatility, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
        })
    except Exception as e:
        logger.error("Black-Litterman error: %s", e)
        return _json_response(False, error=safe_error(e))


# Factor Analysis endpoints
@feature_router.post("/portfolio/factor-exposure")
async def factor_exposure_analysis(request: Request):
    try:
        body = await request.json()
        symbol = body.get("symbol", "")
        factor_data = body.get("factor_data", {})
        period = body.get("period", "1y")
        risk_free_rate = float(body.get("risk_free_rate", 0.03))

        if not symbol:
            return _json_response(False, error="Symbol is required")
        if not factor_data or len(factor_data) < 1:
            return _json_response(False, error="Factor data is required (dict of factor_name: [returns])")

        from core.data_fetcher import get_fetcher
        from core.factor_model import FactorModel

        fetcher = get_fetcher()
        try:
            df = await fetcher.get_history(symbol, period, "daily", "qfq")
            if df is None or len(df) < 30:
                return _json_response(False, error="Insufficient price data for factor analysis")
            asset_returns = np.log(df["close"] / df["close"].shift(1)).dropna()
        except (ValueError, KeyError, TypeError) as e:
            return _json_response(False, error=f"Failed to fetch data: {e}")

        factor_returns = pd.DataFrame(factor_data)
        min_len = min(len(asset_returns), len(factor_returns))
        asset_returns = asset_returns.iloc[:min_len]
        factor_returns = factor_returns.iloc[:min_len]

        fm = FactorModel(risk_free_rate=risk_free_rate)
        result = fm.estimate_factor_exposures(asset_returns, factor_returns)

        if not result.is_valid:
            return _json_response(False, error=result.message)

        return _json_response(True, data={
            "alpha": round(result.alpha, 6),
            "alpha_tstat": round(result.alpha_tstat, 4),
            "alpha_pvalue": round(result.alpha_pvalue, 4),
            "betas": {k: round(v, 4) for k, v in result.betas.items()},
            "beta_tstats": {k: round(v, 4) for k, v in result.beta_tstats.items()},
            "beta_pvalues": {k: round(v, 4) for k, v in result.beta_pvalues.items()},
            "r_squared": round(result.r_squared, 4),
            "adjusted_r_squared": round(result.adjusted_r_squared, 4),
            "residual_volatility": round(result.residual_volatility, 4),
            "factor_count": result.factor_count,
        })
    except Exception as e:
        logger.error("Factor exposure error: %s", e)
        return _json_response(False, error=safe_error(e))


# Monte Carlo VaR endpoint
@feature_router.post("/portfolio/monte-carlo-var")
async def monte_carlo_var(request: Request):
    try:
        body = await request.json()
        symbols = body.get("symbols", [])
        weights = body.get("weights", None)
        n_simulations = int(body.get("n_simulations", 10000))
        time_horizon = int(body.get("time_horizon", 1))
        method = body.get("method", "parametric")
        period = body.get("period", "1y")

        if not symbols or len(symbols) < 2:
            return _json_response(False, error="At least 2 symbols required")
        if len(symbols) > 50:
            symbols = symbols[:50]

        n_simulations = _clamp(n_simulations, 1000, 100000)
        time_horizon = _clamp(time_horizon, 1, 252)

        from core.data_fetcher import get_fetcher
        from core.monte_carlo_var import MonteCarloVaR

        fetcher = get_fetcher()
        price_data = {}

        for sym in symbols:
            try:
                df = await fetcher.get_history(sym, period, "daily", "qfq")
                if df is not None and len(df) >= 30:
                    price_data[sym] = df["close"].values.astype(float)
            except (ValueError, KeyError, TypeError) as e:
                logger.debug("VaR data fetch failed for %s: %s", sym, e)
                continue

        if len(price_data) < 2:
            return _json_response(False, error="Insufficient data for VaR simulation")

        min_len = min(len(v) for v in price_data.values())
        aligned_data = {sym: v[-min_len:] for sym, v in price_data.items()}

        import pandas as pd
        prices_df = pd.DataFrame(aligned_data)

        mc = MonteCarloVaR(
            n_simulations=n_simulations,
            time_horizon=time_horizon,
        )

        if method == "historical":
            result = mc.simulate_historical(prices_df, weights=weights)
        else:
            result = mc.simulate(prices_df, weights=weights)

        if not result.is_valid:
            return _json_response(False, error=result.message)

        return _json_response(True, data={
            "method": method,
            "var_95": round(result.var_95, 6),
            "var_99": round(result.var_99, 6),
            "cvar_95": round(result.cvar_95, 6),
            "cvar_99": round(result.cvar_99, 6),
            "mean_return": round(result.mean_portfolio_return, 6),
            "std_return": round(result.std_portfolio_return, 6),
            "n_simulations": result.n_simulations,
            "confidence_levels": result.confidence_levels,
        })
    except Exception as e:
        logger.error("Monte Carlo VaR error: %s", e)
        return _json_response(False, error=safe_error(e))


# Correlation Analysis endpoint
@feature_router.post("/portfolio/correlation")
async def correlation_analysis(request: Request):
    try:
        body = await request.json()
        symbols = body.get("symbols", [])
        method = body.get("method", "pearson")
        period = body.get("period", "1y")
        high_threshold = float(body.get("high_threshold", 0.7))
        low_threshold = float(body.get("low_threshold", 0.3))

        if not symbols or len(symbols) < 2:
            return _json_response(False, error="At least 2 symbols required")
        if len(symbols) > 50:
            symbols = symbols[:50]

        from core.correlation_analysis import CorrelationAnalyzer
        from core.data_fetcher import get_fetcher

        fetcher = get_fetcher()
        price_data = {}

        for sym in symbols:
            try:
                df = await fetcher.get_history(sym, period, "daily", "qfq")
                if df is not None and len(df) >= 20:
                    price_data[sym] = df["close"].values.astype(float)
            except (ValueError, KeyError, TypeError) as e:
                logger.debug("Correlation data fetch failed for %s: %s", sym, e)
                continue

        if len(price_data) < 2:
            return _json_response(False, error="Insufficient data for correlation analysis")

        min_len = min(len(v) for v in price_data.values())
        aligned_data = {sym: v[-min_len:] for sym, v in price_data.items()}

        import pandas as pd
        prices_df = pd.DataFrame(aligned_data)

        analyzer = CorrelationAnalyzer(
            high_correlation_threshold=high_threshold,
            low_correlation_threshold=low_threshold,
        )
        result = analyzer.analyze(prices_df, method=method)

        if not result.is_valid:
            return _json_response(False, error=result.message)

        return _json_response(True, data={
            "method": method,
            "correlation_matrix": result.correlation_matrix,
            "highly_correlated_pairs": [
                {"asset1": a, "asset2": b, "correlation": round(c, 4)}
                for a, b, c in result.highly_correlated_pairs
            ],
            "low_correlated_pairs": [
                {"asset1": a, "asset2": b, "correlation": round(c, 4)}
                for a, b, c in result.low_correlated_pairs
            ],
            "average_correlation": round(result.average_correlation, 4),
            "diversification_score": round(result.diversification_score, 4),
            "n_assets": result.n_assets,
        })
    except Exception as e:
        logger.error("Correlation analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


# Portfolio Monitoring WebSocket
@feature_router.websocket("/ws/portfolio-monitor")
async def portfolio_monitor_ws(websocket: WebSocket):
    """
    WebSocket endpoint for real-time portfolio monitoring.
    Client sends JSON messages with action field:
    - {"action": "subscribe", "symbols": ["SYM01", "SYM02"]}
    - {"action": "unsubscribe"}
    Server pushes portfolio updates every 5 seconds.
    """
    await websocket.accept()
    subscribed_symbols: list = []
    try:
        import asyncio

        from core.data_fetcher import get_fetcher

        fetcher = get_fetcher()

        async def send_updates():
            while subscribed_symbols:
                try:
                    price_data = {}
                    for sym in subscribed_symbols[:20]:
                        try:
                            df = await fetcher.get_history(sym, "5d", "daily", "qfq")
                            if df is not None and len(df) > 0:
                                latest = df.iloc[-1]
                                price_data[sym] = {
                                    "close": float(latest["close"]),
                                    "volume": float(latest.get("volume", 0)),
                                }
                        except (ValueError, KeyError, TypeError):
                            continue

                    if price_data:
                        await websocket.send_json({
                            "type": "portfolio_update",
                            "data": price_data,
                            "timestamp": datetime.now().isoformat(),
                        })
                except Exception as e:
                    logger.debug("Portfolio monitor update error: %s", e)
                await asyncio.sleep(5)

        update_task = None

        while True:
            try:
                data = await websocket.receive_json()
                action = data.get("action", "")

                if action == "subscribe":
                    symbols = data.get("symbols", [])
                    if symbols and len(symbols) <= 20:
                        subscribed_symbols = symbols
                        if update_task is None:
                            update_task = asyncio.create_task(send_updates())
                        await websocket.send_json({
                            "type": "subscribed",
                            "symbols": subscribed_symbols,
                        })
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Provide 1-20 symbols to subscribe",
                        })

                elif action == "unsubscribe":
                    subscribed_symbols = []
                    if update_task is not None:
                        update_task.cancel()
                        update_task = None
                    await websocket.send_json({"type": "unsubscribed"})

                elif action == "ping":
                    await websocket.send_json({"type": "pong"})

            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("Portfolio monitor WebSocket error: %s", e)
    finally:
        if subscribed_symbols:
            subscribed_symbols.clear()


_factor_registry_cache: dict | None = None
_factor_registry_cache_time: float = 0


@feature_router.get("/factor/registry")
async def factor_registry(request: Request):
    global _factor_registry_cache, _factor_registry_cache_time
    try:
        import time
        now = time.time()
        if _factor_registry_cache is not None and (now - _factor_registry_cache_time) < _cfg.registry_cache_ttl:
            return _json_response(True, data=_factor_registry_cache)
        from core.multi_factor_framework import FACTOR_REGISTRY, FactorCategory
        factors = []
        for _name, defn in FACTOR_REGISTRY.items():
            factors.append({
                "name": defn.name,
                "category": defn.category.value,
                "description": defn.description,
            })
        categories = {c.value for c in FactorCategory}
        data = {"factors": factors, "categories": sorted(categories)}
        _factor_registry_cache = data
        _factor_registry_cache_time = now
        return _json_response(True, data=data)
    except Exception as e:
        logger.error("Factor registry error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/factor/ic-analysis")
@rate_limiter(max_calls=_cfg.ic_analysis_rate_limit, time_window=_cfg.rate_limit_window)
async def factor_ic_analysis(request: Request):
    try:
        body = await request.json()
        from core.multi_factor_framework import factor_ic_analysis as _ic_analysis
        factor_values = pd.Series(body.get("factor_values", []), dtype=float)
        forward_returns = pd.Series(body.get("forward_returns", []), dtype=float)
        max_lag = int(body.get("max_lag", 20))
        n_quintiles = int(body.get("n_quintiles", 5))
        if len(factor_values) < 10 or len(forward_returns) < 10:
            return _json_response(False, error=f"因子值和远期收益至少需要{_cfg.min_observations}个观测值")
        if max_lag < 1:
            return _json_response(False, error="max_lag 必须 ≥ 1")
        if n_quintiles < 2:
            return _json_response(False, error="n_quintiles 必须 ≥ 2")
        if _has_nan_inf(factor_values) or _has_nan_inf(forward_returns):
            return _json_response(False, error="因子值和远期收益不能包含 NaN 或 Inf")
        if len(factor_values) != len(forward_returns):
            return _json_response(False, error="因子值和远期收益长度必须一致")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _ic_analysis, factor_values, forward_returns, max_lag, n_quintiles)
        return _json_response(True, data={
            "factor_name": result.factor_name,
            "mean_ic": round(result.mean_ic, 6),
            "icir": round(result.icir, 6),
            "ic_decay": [round(v, 6) for v in result.ic_decay],
            "turnover": round(result.turnover, 6),
            "long_short_return": round(result.long_short_return, 6),
            "long_short_sharpe": round(result.long_short_sharpe, 6),
            "monotonicity": round(result.monotonicity, 6),
        })
    except Exception as e:
        logger.error("Factor IC analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/factor/quintile-test")
async def factor_quintile_test(request: Request):
    try:
        body = await request.json()
        from core.multi_factor_framework import quintile_return_test
        factor_values = pd.Series(body.get("factor_values", []), dtype=float)
        forward_returns = pd.Series(body.get("forward_returns", []), dtype=float)
        n_quintiles = int(body.get("n_quintiles", 5))
        if n_quintiles < 2:
            return _json_response(False, error="n_quintiles 必须 ≥ 2")
        if len(factor_values) < n_quintiles or len(forward_returns) < n_quintiles:
            return _json_response(False, error="数据不足以进行分位数测试")
        if _has_nan_inf(factor_values) or _has_nan_inf(forward_returns):
            return _json_response(False, error="因子值和远期收益不能包含 NaN 或 Inf")
        if len(factor_values) != len(forward_returns):
            return _json_response(False, error="因子值和远期收益长度必须一致")
        result = quintile_return_test(factor_values, forward_returns, n_quintiles)
        return _json_response(True, data={str(k): round(v, 6) for k, v in result.items()})
    except Exception as e:
        logger.error("Factor quintile test error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/factor/neutralize")
async def factor_neutralize(request: Request):
    try:
        body = await request.json()
        from core.multi_factor_framework import barra_neutralize
        factor_values = pd.Series(body.get("factor_values", []), dtype=float)
        industry_labels = pd.Series(body.get("industry_labels", []))
        market_cap = pd.Series(body.get("market_cap", []), dtype=float)
        if not (len(factor_values) == len(industry_labels) == len(market_cap)):
            return _json_response(False, error="factor_values, industry_labels, market_cap 长度必须一致")
        if _has_nan_inf(factor_values) or _has_nan_inf(market_cap):
            return _json_response(False, error="factor_values 和 market_cap 不能包含 NaN 或 Inf")
        if factor_values.empty:
            return _json_response(False, error="factor_values 不能为空")
        style_factors = None
        if body.get("style_factors"):
            style_factors = pd.DataFrame(body.get("style_factors"))
        result = barra_neutralize(factor_values, industry_labels, market_cap, style_factors)
        return _json_response(True, data={
            "neutralized_values": [round(float(v), 6) if np.isfinite(v) else None for v in result.values],
        })
    except Exception as e:
        logger.error("Factor neutralize error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/factor/rotation")
async def factor_rotation_detect(request: Request):
    try:
        body = await request.json()
        from core.multi_factor_framework import FactorRotationDetector
        factor_names = body.get("factor_names", [])
        factor_values_ts = pd.DataFrame(body.get("factor_values_ts", {}))
        forward_returns_ts = pd.DataFrame(body.get("forward_returns_ts", {}))
        if factor_values_ts.empty or forward_returns_ts.empty:
            return _json_response(False, error="因子时间序列和远期收益时间序列不能为空")
        detector = FactorRotationDetector(
            recent_window=int(body.get("recent_window", 60)),
            long_term_window=int(body.get("long_term_window", 252)),
            ic_threshold=float(body.get("ic_threshold", 0.02)),
        )
        signals = detector.detect_rotation_multi(factor_names, factor_values_ts, forward_returns_ts)
        return _json_response(True, data=[
            {"factor_name": s.factor_name, "recent_ic": round(s.recent_ic, 6),
             "long_term_ic": round(s.long_term_ic, 6), "ic_change": round(s.ic_change, 6),
             "recommendation": s.recommendation}
            for s in signals
        ])
    except Exception as e:
        logger.error("Factor rotation error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/factor/optimize")
@rate_limiter(max_calls=_cfg.optimize_rate_limit, time_window=_cfg.rate_limit_window)
async def factor_optimize_portfolio(request: Request):
    try:
        body = await request.json()
        from core.multi_factor_framework import optimize_with_factor_exposure
        expected_returns = np.array(body.get("expected_returns", []), dtype=float)
        cov_matrix = np.array(body.get("cov_matrix", [[]]), dtype=float)
        factor_exposures = np.array(body.get("factor_exposures", [[]]), dtype=float)
        factor_constraints = np.array(body.get("factor_constraints", []), dtype=float)
        if len(expected_returns) == 0:
            return _json_response(False, error="expected_returns 不能为空")
        if cov_matrix.ndim != 2 or cov_matrix.shape[0] != cov_matrix.shape[1]:
            return _json_response(False, error="cov_matrix 必须是方阵")
        if len(expected_returns) != cov_matrix.shape[0]:
            return _json_response(False, error="expected_returns 长度与 cov_matrix 维度不匹配")
        if np.any(np.isnan(expected_returns)) or np.any(np.isinf(expected_returns)):
            return _json_response(False, error="expected_returns 不能包含 NaN 或 Inf")
        if np.any(np.isnan(cov_matrix)) or np.any(np.isinf(cov_matrix)):
            return _json_response(False, error="cov_matrix 不能包含 NaN 或 Inf")
        weights = optimize_with_factor_exposure(
            expected_returns, cov_matrix, factor_exposures, factor_constraints,
            max_weight=float(body.get("max_weight", 0.05)),
            min_weight=float(body.get("min_weight", 0.0)),
            risk_free_rate=float(body.get("risk_free_rate", 0.03)),
            lambda_risk=float(body.get("lambda_risk", 1.0)),
        )
        return _json_response(True, data={
            "weights": [round(float(w), 6) for w in weights],
        })
    except Exception as e:
        logger.error("Factor optimize error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/ml/labels")
async def ml_generate_labels(request: Request):
    try:
        body = await request.json()
        from core.ml_strategy_framework import MLStrategyPipeline
        prices = pd.Series(body.get("prices", []), dtype=float)
        if prices.empty:
            return _json_response(False, error="prices 不能为空")
        if _has_nan_inf(prices):
            return _json_response(False, error="prices 不能包含 NaN 或 Inf")
        if len(prices) < 3:
            return _json_response(False, error=f"prices 至少需要{_cfg.min_prices}个观测值")
        pipeline = MLStrategyPipeline()
        method = body.get("method", "triple_barrier")
        kwargs = {}
        if body.get("pt_sl"):
            kwargs["pt_sl"] = body["pt_sl"]
        if body.get("min_ret"):
            kwargs["min_ret"] = float(body["min_ret"])
        if body.get("events"):
            kwargs["events"] = pd.DataFrame(body["events"])
        result = pipeline.generate_labels(prices, method=method, **kwargs)
        labels = result["label"].tolist() if "label" in result.columns else []
        return _json_response(True, data={
            "n_labels": len(result),
            "labels": labels[:500],
            "profit_count": int((result["label"] == 1).sum()) if "label" in result.columns else 0,
            "loss_count": int((result["label"] == -1).sum()) if "label" in result.columns else 0,
            "timeout_count": int((result["label"] == 0).sum()) if "label" in result.columns else 0,
        })
    except Exception as e:
        logger.error("ML labels error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/ml/train")
@rate_limiter(max_calls=_cfg.ml_train_rate_limit, time_window=_cfg.rate_limit_window)
async def ml_train_model(request: Request):
    try:
        body = await request.json()
        from core.ml_strategy_framework import MLStrategyPipeline, SKLEARN_AVAILABLE
        if not SKLEARN_AVAILABLE:
            return _json_response(False, error="scikit-learn 未安装，无法使用 ML 功能")
        x = pd.DataFrame(body.get("features", {}))
        y = pd.Series(body.get("labels", []), dtype=int)
        if x.empty or y.empty:
            return _json_response(False, error="features 和 labels 不能为空")
        pipeline = MLStrategyPipeline(
            n_splits=int(body.get("n_splits", 5)),
            pct_embargo=float(body.get("pct_embargo", 0.01)),
        )
        method = body.get("cv_method", "purged_kfold")
        model_type = body.get("model_type", "random_forest")
        result = pipeline.train_model(x, y, method=method, model_type=model_type)
        return _json_response(True, data={
            "cv_mean": round(float(result.cv_scores.mean()), 4),
            "cv_std": round(float(result.cv_scores.std()), 4),
            "feature_importance": {k: round(v, 6) for k, v in result.feature_importance.items()},
            "n_samples": len(x),
        })
    except Exception as e:
        logger.error("ML train error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/ml/predict")
async def ml_predict(request: Request):
    try:
        body = await request.json()
        from core.ml_strategy_framework import SKLEARN_AVAILABLE
        if not SKLEARN_AVAILABLE:
            return _json_response(False, error="scikit-learn 未安装")
        model_data = body.get("model")
        if not model_data:
            return _json_response(False, error="需要提供已训练的模型信息")
        x = pd.DataFrame(body.get("features", {}))
        if x.empty:
            return _json_response(False, error="features 不能为空")
        return _json_response(False, error="模型预测需要持久化模型支持，请使用 train 接口训练后直接预测")
    except Exception as e:
        logger.error("ML predict error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/ml/drift-check")
@rate_limiter(max_calls=_cfg.ml_drift_rate_limit, time_window=_cfg.rate_limit_window)
async def ml_drift_check(request: Request):
    try:
        body = await request.json()
        from core.ml_strategy_framework import DistributionDriftMonitor
        current = pd.DataFrame(body.get("current_features", {}))
        reference = pd.DataFrame(body.get("reference_features", {}))
        if current.empty or reference.empty:
            return _json_response(False, error="current_features 和 reference_features 不能为空")
        current_cols = set(current.columns)
        reference_cols = set(reference.columns)
        if current_cols != reference_cols:
            missing_in_ref = current_cols - reference_cols
            missing_in_cur = reference_cols - current_cols
            detail = []
            if missing_in_ref:
                detail.append(f"reference 缺少: {sorted(missing_in_ref)}")
            if missing_in_cur:
                detail.append(f"current 缺少: {sorted(missing_in_cur)}")
            return _json_response(False, error=f"特征列不一致: {'; '.join(detail)}")
        monitor = DistributionDriftMonitor(
            significance_level=float(body.get("significance_level", 0.05)),
            alert_threshold=float(body.get("alert_threshold", 0.3)),
        )
        result = monitor.monitor(current, reference)
        return _json_response(True, data={
            "drift_detected": result.drift_detected,
            "drifted_features": result.drifted_features,
            "ks_statistics": {k: round(v, 6) for k, v in result.ks_statistics.items()},
            "alert_level": result.alert_level,
        })
    except Exception as e:
        logger.error("ML drift check error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.post("/ml/meta-label")
@rate_limiter(max_calls=_cfg.ml_meta_label_rate_limit, time_window=_cfg.rate_limit_window)
async def ml_meta_label(request: Request):
    try:
        body = await request.json()
        from core.ml_strategy_framework import meta_labeling as _meta_labeling, SKLEARN_AVAILABLE
        if not SKLEARN_AVAILABLE:
            return _json_response(False, error="scikit-learn 未安装，无法使用 meta-labeling")
        primary_signals = pd.Series(body.get("primary_signals", []), dtype=float)
        actual_returns = pd.Series(body.get("actual_returns", []), dtype=float)
        features = pd.DataFrame(body.get("features", {}))
        if primary_signals.empty or actual_returns.empty or features.empty:
            return _json_response(False, error="primary_signals, actual_returns, features 不能为空")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _meta_labeling, primary_signals, actual_returns, features)
        return _json_response(True, data={
            "n_samples": len(result.meta_labels),
            "positive_rate": round(float(result.meta_labels.mean()), 4),
            "cv_mean": round(float(result.cv_scores.mean()), 4),
            "cv_std": round(float(result.cv_scores.std()), 4),
            "feature_importance": {k: round(v, 6) for k, v in result.feature_importance.items()},
        })
    except Exception as e:
        logger.error("ML meta-label error: %s", e)
        return _json_response(False, error=safe_error(e))


@feature_router.websocket("/ws/factor-rotation")
async def factor_rotation_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            factor_names = data.get("factor_names", [])
            factor_values_ts = data.get("factor_values_ts", {})
            forward_returns_ts = data.get("forward_returns_ts", {})
            if not factor_names or not factor_values_ts or not forward_returns_ts:
                await websocket.send_json({"type": "error", "data": {"message": "factor_names, factor_values_ts, forward_returns_ts required"}})
                continue
            from core.multi_factor_framework import FactorRotationDetector
            detector = FactorRotationDetector(
                recent_window=int(data.get("recent_window", 60)),
                long_term_window=int(data.get("long_term_window", 252)),
                ic_threshold=float(data.get("ic_threshold", 0.02)),
            )
            fv_ts = pd.DataFrame(factor_values_ts)
            fr_ts = pd.DataFrame(forward_returns_ts)
            signals = detector.detect_rotation_multi(factor_names, fv_ts, fr_ts)
            for s in signals:
                await websocket.send_json({
                    "type": "factor_rotation",
                    "data": {
                        "factor_name": s.factor_name,
                        "recent_ic": round(s.recent_ic, 6),
                        "long_term_ic": round(s.long_term_ic, 6),
                        "ic_change": round(s.ic_change, 6),
                        "recommendation": s.recommendation,
                    },
                })
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("Factor rotation WS error: %s", e)
