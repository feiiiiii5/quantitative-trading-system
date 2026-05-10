import asyncio
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import StreamingResponse

from api.connection_manager import cache_response
from api.utils import json_response as _json_response
from api.utils import rate_limiter, safe_error, validate_symbol
from core.data_fetcher import SmartDataFetcher, get_fetcher
from core.database import get_db
from core.indicators import calc_all_indicators
from core.market_detector import MarketDetector

import numpy as np
import pandas as pd

from core.indicators import IndicatorAnalysis, KLinePatternRecognizer, TechnicalIndicators
from core.strategies import CompositeStrategy

logger = logging.getLogger(__name__)
router = APIRouter()

_rt_cache = None
_kline_cache = None


def _init_caches():
    global _rt_cache, _kline_cache
    if _rt_cache is None:
        from api.connection_manager import _TTLCache
        _rt_cache = _TTLCache(ttl=8.0, maxsize=15000)
        _kline_cache = _TTLCache(ttl=60.0, maxsize=6000)


_init_caches()

_indicator_api_cache = None
_analysis_cache = None


def _init_local_caches():
    global _indicator_api_cache, _analysis_cache
    if _indicator_api_cache is None:
        from api.connection_manager import _TTLCache
        _indicator_api_cache = _TTLCache(ttl=60.0, maxsize=3000)
        _analysis_cache = _TTLCache(ttl=60.0, maxsize=4000)


_init_local_caches()


@router.get("/stock/realtime/{symbol}")
async def get_stock_realtime(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")):
    try:
        cached = _rt_cache.get(symbol)
        if cached is not None:
            return _json_response(True, data=cached, cached=True)
        fetcher: SmartDataFetcher = request.app.state.fetcher
        data = await fetcher.get_realtime(symbol)
        if data:
            _rt_cache.set(symbol, data)
            return _json_response(True, data=data)
        return _json_response(False, error="未获取到数据")
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/stock/history/{symbol}")
async def get_stock_history(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
    kline_type: str = Query("daily", max_length=10, pattern=r"^(daily|weekly|monthly)$"),
    adjust: str = Query("", max_length=5),
):
    try:
        cache_key = "%s:%s:%s:%s" % (symbol, period, kline_type, adjust)
        cached = _kline_cache.get(cache_key)
        if cached is not None:
            return _json_response(True, data=cached, cached=True)
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period, kline_type, adjust)
        if df.empty:
            return _json_response(False, error="无历史数据")
        result = df.to_dict("records")
        _kline_cache.set(cache_key, result)
        return _json_response(True, data=result)
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/stock/history/export/{symbol}")
async def export_stock_history(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
    kline_type: str = Query("daily", max_length=10, pattern=r"^(daily|weekly|monthly)$"),
    adjust: str = Query("", max_length=5),
    format: str = Query("csv", pattern=r"^(csv|json)$"),
):
    try:
        import io
        import json as json_lib

        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period, kline_type, adjust)
        if df.empty:
            return _json_response(False, error="无历史数据")

        filename = f"{symbol}_{period}_{kline_type}_{adjust if adjust else 'none'}.{format}"

        if format == "csv":
            output = io.StringIO()
            df.to_csv(output, index=False, encoding="utf-8")
            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        else:
            result = df.to_dict("records")
            return StreamingResponse(
                iter([json_lib.dumps(result, ensure_ascii=False, default=str)]),
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
    except Exception as e:
        logger.error("Export history error: %s", e, exc_info=True)
        return _json_response(False, error=safe_error(e))


@router.get("/stock/fundamentals/{symbol}")
@cache_response(3600)
async def get_stock_fundamentals(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$")):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        market = MarketDetector.detect(symbol)
        data = await fetcher.get_fundamentals(symbol, market)
        if data:
            return _json_response(True, data=data)
        return _json_response(False, error="无基本面数据")
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/stock/indicators/{symbol}")
async def get_stock_indicators(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
    kline_type: str = Query("daily"),
):
    try:
        cache_key = "ind:%s:%s:%s" % (symbol, period, kline_type)
        cached = _indicator_api_cache.get(cache_key)
        if cached is not None:
            return _json_response(True, data=cached, cached=True)
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, period, kline_type)
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")
        kline_data = df.to_dict("records")
        result = calc_all_indicators(kline_data)
        _indicator_api_cache.set(cache_key, result)
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Indicators error: %s", e)
        return _json_response(False, error=safe_error(e))


def _period_to_history(period: str) -> str:
    period = (period or "1y").lower()
    if period in {"3m", "6m"}:
        return "1y"
    if period in {"3y", "5y", "all"}:
        return "all"
    return "1y"


@router.get("/stock/analysis/{symbol}")
async def get_deep_analysis(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"), period: str = Query("1y", max_length=5)):
    try:
        cache_key = "analysis:%s:%s" % (symbol, period)
        cached = _analysis_cache.get(cache_key)
        if cached is not None:
            return _json_response(True, data=cached, cached=True)
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="数据不足，至少需要60个交易日")

        df = df.tail(260).copy().reset_index(drop=True)
        c = df["close"].astype(float)
        h = df["high"].astype(float)
        low = df["low"].astype(float)
        df["volume"].astype(float) if "volume" in df.columns else None
        indicators = TechnicalIndicators.compute_all(df, symbol=symbol, period=period)
        ma = indicators.get("ma", {})
        ma20 = ma.get(20, [])
        ma.get(60, [])
        last_close = float(c.iloc[-1])
        trend_slope = 0.0
        if len(ma20) >= 20:
            trend_slope = float(ma20[-1] - ma20[-20]) / max(abs(float(ma20[-20])), 1e-9)
        direction = "up" if trend_slope > 0.02 else "down" if trend_slope < -0.02 else "sideways"
        strength = min(100, abs(trend_slope) * 1200 + abs(indicators.get("trend_score", 0)) * 0.5)
        support_resistance = IndicatorAnalysis.support_resistance(df)
        volume_analysis = IndicatorAnalysis.volume_price_analysis(df)
        patterns = KLinePatternRecognizer.recognize(df.tail(80))

        rsi_data = indicators.get("rsi", {}).get(12, [])
        rsi_val = float(rsi_data[-1]) if rsi_data else 50.0
        macd = indicators.get("macd", {})
        dif = macd.get("dif", [0])[-1] if macd.get("dif") else 0
        dea = macd.get("dea", [0])[-1] if macd.get("dea") else 0
        kdj = indicators.get("kdj", {})
        k_val = kdj.get("k", [50])[-1] if kdj.get("k") else 50
        d_val = kdj.get("d", [50])[-1] if kdj.get("d") else 50

        low_120 = float(low.tail(120).min())
        high_120 = float(h.tail(120).max())
        fib_ratios = [0.236, 0.382, 0.5, 0.618, 0.786]
        fib = [round(high_120 - (high_120 - low_120) * r, 4) for r in fib_ratios]
        composite_score = float(indicators.get("trend_score", 0))
        signal = indicators.get("signal", "neutral")
        confidence = min(100, abs(composite_score) + 35)

        result = {
            "trend": {
                "direction": direction,
                "strength": round(float(strength), 2),
                "duration_days": int(min(len(df), 260)),
                "key_levels": {
                    "support": support_resistance.get("supports", []),
                    "resistance": support_resistance.get("resistances", []),
                },
            },
            "momentum": {
                "rsi_signal": "overbought" if rsi_val > 70 else "oversold" if rsi_val < 30 else "neutral",
                "macd_signal": "bullish" if dif > dea else "bearish" if dif < dea else "neutral",
                "kdj_signal": "bullish" if k_val > d_val else "bearish" if k_val < d_val else "neutral",
                "composite_momentum": round(float(composite_score / 100), 4),
            },
            "volume": {
                "trend": "accumulation" if volume_analysis.get("obv_trend", 0) > 0 else "distribution" if volume_analysis.get("obv_trend", 0) < 0 else "neutral",
                "obv_divergence": bool(indicators.get("rsi_divergence", {}).get("top_divergence")),
                "volume_ratio_5d": volume_analysis.get("volume_ratio", 0),
            },
            "patterns": patterns[-10:],
            "ichimoku": indicators.get("ichimoku", {}),
            "fibonacci_levels": [{"ratio": r, "price": p} for r, p in zip(fib_ratios, fib, strict=False)],
            "composite_score": round(composite_score, 2),
            "signal": signal,
            "signal_confidence": round(float(confidence), 2),
            "last_price": round(last_close, 4),
        }
        _analysis_cache.set(cache_key, result)
        return _json_response(True, data=result)
    except Exception as e:
        logger.error("Deep analysis error for %s: %s", symbol, e, exc_info=True)
        return _json_response(False, error=safe_error(e))


@router.get("/stock/correlation/{symbol}")
async def get_correlation_analysis(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    benchmark: str = Query("sh000300", max_length=20),
    period: str = Query("1y"),
):
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        bench_df = await fetcher.get_history(benchmark, _period_to_history(period), "daily", "qfq")
        if bench_df is None or bench_df.empty:
            try:
                import baostock as bs
                bench_code = benchmark.replace("sh", "sh.", 1).replace("sz", "sz.", 1)
                if not bench_code.startswith("sh.") and not bench_code.startswith("sz."):
                    bench_code = f"sh.{benchmark.removeprefix('sh').removeprefix('sz')}"
                bs.login()
                try:
                    rs = bs.query_history_k_data_plus(bench_code, "date,close", start_date="2023-01-01", end_date=datetime.now().strftime("%Y-%m-%d"), frequency="d")
                    rows = []
                    while rs.next():
                        rows.append(rs.get_row_data())
                    if rows:
                        bench_df = pd.DataFrame(rows, columns=["date", "close"])
                        bench_df["close"] = pd.to_numeric(bench_df["close"], errors="coerce")
                        bench_df["date"] = pd.to_datetime(bench_df["date"], errors="coerce")
                        bench_df = bench_df.dropna(subset=["date", "close"])
                finally:
                    bs.logout()
            except Exception as e:
                logger.debug("BaoStock cleanup failed: %s", e)
        if df is None or df.empty or bench_df is None or bench_df.empty:
            return _json_response(False, error="数据不足")
        left = df[["date", "close"]].rename(columns={"close": "asset_close"})
        right = bench_df[["date", "close"]].rename(columns={"close": "benchmark_close"})
        left["date"] = pd.to_datetime(left["date"], errors="coerce")
        right["date"] = pd.to_datetime(right["date"], errors="coerce")
        merged = left.merge(right, on="date", how="inner").tail(260)
        if len(merged) < 30:
            return _json_response(False, error="重叠数据不足")
        ar = merged["asset_close"].astype(float).pct_change()
        br = merged["benchmark_close"].astype(float).pct_change()
        rolling_corr = ar.rolling(60).corr(br).fillna(0)
        br_var = np.var(br.dropna().tail(120))
        beta = float(np.cov(ar.dropna().tail(120), br.dropna().tail(120))[0][1] / br_var) if br_var > 0 else 1.0
        asset_first = float(merged["asset_close"].iloc[0])
        bench_first = float(merged["benchmark_close"].iloc[0])
        asset_ret = (float(merged["asset_close"].iloc[-1]) / asset_first - 1) if asset_first > 1e-9 else 0.0
        bench_ret = (float(merged["benchmark_close"].iloc[-1]) / bench_first - 1) if bench_first > 1e-9 else 0.0
        rolling_corr_data = [
            {"date": str(d)[:10], "value": round(float(v), 4)}
            for d, v in zip(merged["date"], rolling_corr, strict=False)
        ]
        return _json_response(True, data={
            "rolling_correlation": rolling_corr_data,
            "beta": round(beta, 4),
            "alpha": round(float(asset_ret - beta * bench_ret), 4),
            "relative_strength": round(float(asset_ret - bench_ret), 4),
            "stability_score": round(float(100 - rolling_corr.tail(120).std() * 100), 2),
        })
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/stock/prediction/{symbol}")
@cache_response(120)
async def get_stock_prediction(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"), period: str = Query("1y", max_length=5)):
    """AI预测接口 - 基于技术指标和统计模型"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 60:
            return _json_response(False, error="数据不足")
        df = df.tail(260).copy().reset_index(drop=True)
        c = df["close"].astype(float).values
        _ = df["high"].astype(float).values
        _ = df["low"].astype(float).values
        _ = df["volume"].astype(float).values

        indicators = TechnicalIndicators.compute_all(df, symbol=symbol, period=period)
        trend_score = indicators.get("trend_score", 0)
        signal = indicators.get("signal", "neutral")

        returns = np.diff(c) / np.where(c[:-1] > 0, c[:-1], 1)
        returns = returns[np.isfinite(returns)]
        if len(returns) < 20:
            return _json_response(False, error="数据不足")
        recent_ret = returns[-20:]
        avg_ret = float(np.mean(recent_ret))
        std_ret = float(np.std(recent_ret))
        last_price = float(c[-1])

        predictions = {}
        for days, label in [(5, "5d"), (10, "10d"), (20, "20d")]:
            drift = avg_ret * days
            vol = std_ret * np.sqrt(days)
            pred_price = last_price * (1 + drift)
            pred_upper = last_price * (1 + drift + 1.96 * vol)
            pred_lower = last_price * (1 + drift - 1.96 * vol)
            confidence = max(0.1, min(0.9, 1.0 - vol / max(abs(drift), 0.01)))
            predictions[label] = {
                "price": round(pred_price, 2),
                "upper": round(pred_upper, 2),
                "lower": round(pred_lower, 2),
                "confidence": round(confidence, 2),
                "direction": "up" if drift > 0 else "down",
            }

        composite_signal = "bullish" if trend_score > 20 else "bearish" if trend_score < -20 else "neutral"
        composite_confidence = min(0.95, abs(trend_score) / 100 + 0.3)

        return _json_response(True, data={
            "symbol": symbol,
            "last_price": round(last_price, 2),
            "predictions": predictions,
            "composite_signal": composite_signal,
            "composite_confidence": round(composite_confidence, 2),
            "trend_score": round(float(trend_score), 2),
            "technical_signal": signal,
            "volatility_annual": round(float(std_ret * np.sqrt(252)), 4),
            "timestamp": time.time(),
        })
    except Exception as e:
        logger.error("Prediction error for %s: %s", symbol, e)
        return _json_response(False, error=safe_error(e))


@router.get("/stock/signals/{symbol}")
async def get_stock_signals(
    request: Request,
    symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"),
    period: str = Query("1y", max_length=5),
    strategy: str = Query("all", max_length=30),
):
    """获取股票策略信号历史 — 通过 on_bar() 统一入口"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df.empty or len(df) < 30:
            return _json_response(False, error="数据不足")

        from core.data_governance import DataQualityPipeline
        dq = DataQualityPipeline(enable_anomaly_detect=True, enable_adjust=False)
        df = dq.process(df, symbol)
        suspended_mask = df.get("is_suspended", pd.Series(False, index=df.index))
        df = df[~suspended_mask].reset_index(drop=True) if suspended_mask.any() else df
        if len(df) < 30:
            return _json_response(False, error="有效数据不足（停牌日过滤后）")

        composite = CompositeStrategy()
        signals = []
        step = max(1, len(df) // 50)
        signal_timeout = 10.0
        max_signals = 100
        start_time = time.time()

        for s in composite.strategies:
            s.reset()

        for i in range(30, len(df), step):
            if time.time() - start_time > signal_timeout:
                logger.warning("Signal generation timed out for %s after %d signals", symbol, len(signals))
                break
            if len(signals) >= max_signals:
                break
            row = df.iloc[i]
            bar = {
                "open": float(row.get("open", 0)) if pd.notna(row.get("open")) else 0,
                "high": float(row.get("high", 0)) if pd.notna(row.get("high")) else 0,
                "low": float(row.get("low", 0)) if pd.notna(row.get("low")) else 0,
                "close": float(row.get("close", 0)) if pd.notna(row.get("close")) else 0,
                "volume": float(row.get("volume", 0)) if pd.notna(row.get("volume")) else 0,
                "date": str(row.get("date", ""))[:10] if "date" in df.columns else "",
                "symbol": symbol,
            }
            for j in range(max(0, i - step + 1), i):
                fill_row = df.iloc[j]
                fill_bar = {
                    "open": float(fill_row.get("open", 0)) if pd.notna(fill_row.get("open")) else 0,
                    "high": float(fill_row.get("high", 0)) if pd.notna(fill_row.get("high")) else 0,
                    "low": float(fill_row.get("low", 0)) if pd.notna(fill_row.get("low")) else 0,
                    "close": float(fill_row.get("close", 0)) if pd.notna(fill_row.get("close")) else 0,
                    "volume": float(fill_row.get("volume", 0)) if pd.notna(fill_row.get("volume")) else 0,
                    "date": str(fill_row.get("date", ""))[:10] if "date" in df.columns else "",
                    "symbol": symbol,
                }
                for s in composite.strategies:
                    if strategy != "all" and type(s).__name__ != strategy:
                        continue
                    s.on_bar(fill_bar, {})

            date_str = str(df["date"].iloc[i])[:10] if "date" in df.columns else ""
            bar_signals = []
            for s in composite.strategies:
                if strategy != "all" and type(s).__name__ != strategy:
                    continue
                try:
                    sigs = s.on_bar(bar, {})
                    for sig in sigs:
                        bar_signals.append({
                            "strategy": type(s).__name__,
                            "signal": sig.get("action", "hold"),
                            "confidence": sig.get("confidence", 0),
                            "reason": sig.get("reason", ""),
                        })
                except Exception as e:
                    logger.debug("Signal generation failed for strategy: %s", e)
                    continue
            if bar_signals:
                signals.append({
                    "date": date_str,
                    "price": round(float(df["close"].iloc[i]), 2),
                    "signals": bar_signals,
                })

        return _json_response(True, data={"symbol": symbol, "signals": signals, "truncated": time.time() - start_time > signal_timeout})
    except Exception as e:
        return _json_response(False, error=safe_error(e))


@router.get("/stock/ai_summary/{symbol}")
@cache_response(300)
async def get_stock_ai_summary(request: Request, symbol: str = Path(..., min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z\.]{1,20}$"), period: str = Query("1y", max_length=5)):
    """AI分析摘要 - 基于规则引擎生成综合分析"""
    try:
        fetcher: SmartDataFetcher = request.app.state.fetcher
        df = await fetcher.get_history(symbol, _period_to_history(period), "daily", "qfq")
        if df is None or df.empty:
            return _json_response(False, error="无数据")

        close = df["close"].values
        _ = df["high"].values
        _ = df["low"].values
        volume = df["volume"].values if "volume" in df.columns else None

        summary_points = []

        pct_5d = ((close[-1] / close[-6]) - 1) * 100 if len(close) > 5 else 0
        pct_20d = ((close[-1] / close[-21]) - 1) * 100 if len(close) > 20 else 0
        pct_60d = ((close[-1] / close[-61]) - 1) * 100 if len(close) > 60 else 0

        if pct_5d > 5:
            summary_points.append(f"近5日涨幅{pct_5d:.1f}%，短期强势")
        elif pct_5d < -5:
            summary_points.append(f"近5日跌幅{pct_5d:.1f}%，短期承压")
        else:
            summary_points.append(f"近5日变动{pct_5d:.1f}%，短期震荡")

        if pct_20d > 15:
            summary_points.append("月线级别强势上涨趋势")
        elif pct_20d < -15:
            summary_points.append("月线级别下跌趋势明显")

        close_series = pd.Series(close)
        ma5 = close_series.rolling(5).mean().values
        ma20 = close_series.rolling(20).mean().values
        ma60 = close_series.rolling(60).mean().values
        if not np.isnan(ma5[-1]) and not np.isnan(ma20[-1]):
            if ma5[-1] > ma20[-1] > (ma60[-1] if not np.isnan(ma60[-1]) else 0):
                summary_points.append("均线多头排列，趋势向好")
            elif ma5[-1] < ma20[-1]:
                summary_points.append("短期均线下穿中期均线，注意风险")

        if volume is not None and len(volume) > 10:
            avg_vol = np.mean(volume[-20:])
            recent_vol = np.mean(volume[-5:])
            if recent_vol > avg_vol * 1.5:
                summary_points.append("近期放量明显，关注资金动向")
            elif recent_vol < avg_vol * 0.5:
                summary_points.append("近期缩量，市场观望情绪浓厚")

        try:
            composite = CompositeStrategy()
            signal = composite.generate_signal(df)
            signal_map = {"buy": "买入", "sell": "卖出", "hold": "中性"}
            summary_points.append(f"综合策略信号：{signal_map.get(signal.signal_type.value, '中性')}（强度{signal.strength:.2f}）")
        except Exception as e:
            logger.debug("AI summary composite signal failed: %s", e)

        try:
            analysis = IndicatorAnalysis.comprehensive_analysis(df)
            if analysis.get("volatility", {}).get("current") == "high":
                summary_points.append("当前波动率较高，注意风险控制")
            if analysis.get("volume_price", {}).get("divergence"):
                summary_points.append("量价出现背离信号")
        except Exception as e:
            logger.debug("AI summary indicator analysis failed: %s", e)

        overall = "中性"
        bullish_count = sum(1 for p in summary_points if any(k in p for k in ["强势", "上涨", "向好", "买入"]))
        bearish_count = sum(1 for p in summary_points if any(k in p for k in ["承压", "下跌", "风险", "卖出"]))
        if bullish_count >= 3:
            overall = "偏多"
        elif bearish_count >= 3:
            overall = "偏空"

        return _json_response(True, data={
            "symbol": symbol,
            "overall": overall,
            "points": summary_points,
            "price_change": {"5d": round(pct_5d, 2), "20d": round(pct_20d, 2), "60d": round(pct_60d, 2)},
            "generated_at": time.time(),
        })
    except Exception as e:
        logger.error("AI summary error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.post("/stock/batch/analysis")
@rate_limiter(max_calls=10, time_window=60.0)
async def batch_stock_analysis(
    request: Request,
    symbols: str = Query(..., description="逗号分隔的股票代码，最多20个"),
    period: str = Query("6m", max_length=5, description="分析周期"),
):
    """批量股票分析 — 一次调用返回多只股票的关键指标摘要"""
    try:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            return _json_response(False, error="请提供股票代码")
        symbol_list = symbol_list[:20]

        fetcher: SmartDataFetcher = request.app.state.fetcher
        history_map = await fetcher.get_history_batch(
            symbol_list, _period_to_history(period), "daily", "qfq"
        )

        _batch_sem = asyncio.Semaphore(4)
        from core.regime_detector import RegimeDetector

        async def _analyze_one(sym: str) -> dict:
            async with _batch_sem:
                try:
                    df = history_map.get(sym)
                    if df is None or len(df) < 20:
                        return {"symbol": sym, "error": "数据不足"}

                    close = df["close"].astype(float)
                    volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series(dtype=float)

                    returns = close.pct_change().dropna()
                    if len(returns) < 10:
                        return {"symbol": sym, "error": "收益率数据不足"}

                    total_return = float(close.iloc[-1] / close.iloc[0] - 1)
                    annual_vol = float(returns.std() * np.sqrt(252))
                    annual_return = float(returns.mean() * 252)
                    sharpe = annual_return / annual_vol if annual_vol > 1e-12 else 0.0

                    downside = returns[returns < 0]
                    downside_dev = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(252)) if len(downside) > 0 else 0.0
                    sortino = annual_return / downside_dev if downside_dev > 1e-12 else 0.0

                    cummax = close.cummax()
                    drawdown = (close - cummax) / cummax
                    max_dd = float(drawdown.min())

                    current_price = float(close.iloc[-1])
                    ma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else current_price
                    ma60 = float(close.rolling(60).mean().iloc[-1]) if len(close) >= 60 else current_price

                    avg_vol_20d = float(volume.iloc[-20:].mean()) if len(volume) >= 20 else 0.0

                    detector = RegimeDetector()
                    regime_result = await asyncio.to_thread(detector.detect, df)

                    return {
                        "symbol": sym,
                        "current_price": round(current_price, 2),
                        "total_return": round(total_return, 4),
                        "annual_return": round(annual_return, 4),
                        "annual_volatility": round(annual_vol, 4),
                        "sharpe_ratio": round(sharpe, 2),
                        "sortino_ratio": round(sortino, 2),
                        "max_drawdown": round(max_dd, 4),
                        "ma20": round(ma20, 2),
                        "ma60": round(ma60, 2),
                        "price_vs_ma20": round((current_price / ma20 - 1) * 100, 2),
                        "price_vs_ma60": round((current_price / ma60 - 1) * 100, 2),
                        "avg_volume_20d": float(round(avg_vol_20d, 0)),
                        "regime": regime_result.current_regime.value,
                        "regime_confidence": regime_result.confidence,
                    }
                except Exception as e:
                    logger.debug("Batch analysis failed for %s: %s", sym, e)
                    return {"symbol": sym, "error": safe_error(e)}

        results = await asyncio.gather(*[_analyze_one(sym) for sym in symbol_list])

        valid = [r for r in results if "error" not in r]
        summary = {}
        if valid:
            summary = {
                "n_analyzed": len(valid),
                "avg_return": round(float(np.mean([r["total_return"] for r in valid])), 4),
                "avg_sharpe": round(float(np.mean([r["sharpe_ratio"] for r in valid])), 2),
                "avg_max_drawdown": round(float(np.mean([r["max_drawdown"] for r in valid])), 4),
                "best_return": max(valid, key=lambda x: x["total_return"])["symbol"],
                "worst_return": min(valid, key=lambda x: x["total_return"])["symbol"],
                "best_sharpe": max(valid, key=lambda x: x["sharpe_ratio"])["symbol"],
            }

        return _json_response(True, data={
            "period": period,
            "results": results,
            "summary": summary,
        })
    except Exception as e:
        logger.error("Batch analysis error: %s", e)
        return _json_response(False, error=safe_error(e))


@router.get("/search")
@cache_response(30)
async def search_stocks(request: Request, q: str = Query(..., min_length=1, max_length=100), limit: int = Query(10, ge=1, le=100)):
    try:
        from core.stock_search import search_stocks as do_search
        results = do_search(q, limit=limit)
        return _json_response(True, data=results)
    except Exception as e:
        return _json_response(False, error=safe_error(e))
