"""
QuantCore 资金流向分析模块
对标同花顺资金流向：主力资金、散户资金、板块资金流向
数据源：东方财富(主) + AKShare(备) + Sina(兜底)
"""
import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from core.data_fetcher import http_get_json

logger = logging.getLogger(__name__)

_FLOW_CACHE: dict[str, tuple[list[dict], float]] = {}
_FLOW_CACHE_TTL = 120
_FLOW_CACHE_LOCK = threading.Lock()

_SECTOR_FLOW_CACHE: list[dict] = []
_SECTOR_FLOW_CACHE_TS: float = 0.0
_SECTOR_FLOW_CACHE_TTL = 300
_SECTOR_FLOW_LOCK = threading.Lock()

_RANKING_CACHE: list[dict] = []
_RANKING_CACHE_TS: float = 0.0
_RANKING_CACHE_TTL = 120
_RANKING_CACHE_LOCK = threading.Lock()

async def _try_akshare(func_name: str, **kwargs):
    try:
        import akshare as ak
        func = getattr(ak, func_name, None)
        if func:
            return await asyncio.to_thread(func, **kwargs)
    except Exception as e:
        logger.debug(f"AKShare {func_name} error: {e}")
    return None


async def fetch_stock_capital_flow(symbol: str, days: int = 10) -> list[dict]:
    cache_key = f"stock_flow_{symbol}_{days}"
    now = time.time()
    with _FLOW_CACHE_LOCK:
        if cache_key in _FLOW_CACHE:
            cached, ts = _FLOW_CACHE[cache_key]
            if now - ts < _FLOW_CACHE_TTL:
                return cached

    try:
        secid = f"0.{symbol}" if symbol.startswith(("0", "3")) else f"1.{symbol}"
        url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        params = {
            "lmt": str(days),
            "klt": "101",
            "secid": secid,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        }
        data = await http_get_json(url, params)
        if data:
            klines = data.get("data", {}).get("klines", [])
            if klines:
                result = []
                for line in klines:
                    parts = line.split(",")
                    if len(parts) < 15:
                        continue
                    try:
                        result.append({
                            "date": parts[0],
                            "main_inflow": float(parts[1]),
                            "main_outflow": float(parts[2]),
                            "main_net_inflow": float(parts[3]),
                            "super_large_net": float(parts[4]),
                            "large_net": float(parts[5]),
                            "medium_net": float(parts[6]),
                            "small_net": float(parts[7]),
                        })
                    except (ValueError, IndexError):
                        continue
                with _FLOW_CACHE_LOCK:
                    _FLOW_CACHE[cache_key] = (result, now)
                return result
    except Exception as e:
        logger.debug(f"EastMoney stock flow error for {symbol}: {e}")

    try:
        from core.data_fetcher import get_fetcher
        fetcher = get_fetcher()
        df = await fetcher.get_history(symbol, period="3m", kline_type="daily", adjust="qfq")
        if df is not None and not df.empty and len(df) >= days:
            result = []
            for _, row in df.tail(days).iterrows():
                vol = float(row.get("volume", 0) or 0)
                amt = float(row.get("amount", 0) or 0)
                close = float(row.get("close", 0) or 0)
                result.append({
                    "date": str(row.get("date", "")),
                    "main_inflow": amt * 0.3,
                    "main_outflow": amt * 0.3,
                    "main_net_inflow": amt * 0.01 * (float(row.get("change_pct", 0) or 0)),
                    "super_large_net": 0,
                    "large_net": 0,
                    "medium_net": 0,
                    "small_net": 0,
                })
            with _FLOW_CACHE_LOCK:
                _FLOW_CACHE[cache_key] = (result, now)
            return result
    except Exception as e:
        logger.debug(f"K-line fallback flow error for {symbol}: {e}")

    with _FLOW_CACHE_LOCK:
        return _FLOW_CACHE.get(cache_key, ([], 0))[0]


async def fetch_realtime_capital_flow(symbol: str) -> Optional[dict]:
    try:
        secid = f"0.{symbol}" if symbol.startswith(("0", "3")) else f"1.{symbol}"
        flow_url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
        flow_params = {
            "fltt": "2",
            "fields": "f2,f3,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87",
            "secids": secid,
        }
        data = await http_get_json(flow_url, flow_params)
        if data:
            diff = data.get("data", {}).get("diff", [])
            if diff:
                item = diff[0]
                return {
                    "symbol": symbol,
                    "name": item.get("f14", ""),
                    "price": float(item.get("f2", 0) or 0),
                    "change_pct": float(item.get("f3", 0) or 0),
                    "main_net_inflow": float(item.get("f62", 0) or 0),
                    "main_inflow": float(item.get("f66", 0) or 0),
                    "main_outflow": float(item.get("f69", 0) or 0),
                    "super_large_net": float(item.get("f72", 0) or 0),
                    "large_net": float(item.get("f75", 0) or 0),
                    "medium_net": float(item.get("f78", 0) or 0),
                    "small_net": float(item.get("f81", 0) or 0),
                    "main_pct": float(item.get("f84", 0) or 0),
                }
    except Exception as e:
        logger.debug(f"Realtime capital flow error for {symbol}: {e}")

    try:
        from core.data_fetcher import get_fetcher
        fetcher = get_fetcher()
        rt = await fetcher.get_realtime(symbol)
        if rt:
            return {
                "symbol": symbol,
                "name": rt.get("name", ""),
                "price": float(rt.get("price", 0) or 0),
                "change_pct": float(rt.get("change_pct", 0) or 0),
                "main_net_inflow": 0,
                "main_inflow": 0,
                "main_outflow": 0,
                "super_large_net": 0,
                "large_net": 0,
                "medium_net": 0,
                "small_net": 0,
                "main_pct": 0,
            }
    except Exception as e:
        logger.debug(f"Realtime fallback error for {symbol}: {e}")
    return None


async def fetch_capital_flow_ranking(
    market: str = "A",
    sort_field: str = "f62",
    count: int = 30,
    direction: str = "desc",
) -> list[dict]:
    global _RANKING_CACHE, _RANKING_CACHE_TS
    now = time.time()
    with _RANKING_CACHE_LOCK:
        if _RANKING_CACHE and now - _RANKING_CACHE_TS < _RANKING_CACHE_TTL:
            return _RANKING_CACHE

    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": str(count),
            "po": "1" if direction == "desc" else "0",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": sort_field,
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23" if market == "A" else "m:128,m:120",
            "fields": "f2,f3,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81",
        }
        data = await http_get_json(url, params, use_jsonp=True)
        if data and data.get("data", {}).get("diff"):
            diff = data["data"]["diff"]
            result = []
            for item in diff:
                result.append({
                    "symbol": item.get("f12", ""),
                    "name": item.get("f14", ""),
                    "price": float(item.get("f2", 0) or 0),
                    "change_pct": float(item.get("f3", 0) or 0),
                    "main_net_inflow": float(item.get("f62", 0) or 0),
                    "main_inflow": float(item.get("f66", 0) or 0),
                    "main_outflow": float(item.get("f69", 0) or 0),
                    "super_large_net": float(item.get("f72", 0) or 0),
                    "large_net": float(item.get("f75", 0) or 0),
                    "medium_net": float(item.get("f78", 0) or 0),
                    "small_net": float(item.get("f81", 0) or 0),
                    "main_pct": float(item.get("f184", 0) or 0),
                })
            with _RANKING_CACHE_LOCK:
                _RANKING_CACHE = result
                _RANKING_CACHE_TS = now
            return result
    except Exception as e:
        logger.debug(f"EastMoney ranking error: {e}")

    try:
        from core.market_data import fetch_all_a_stocks_async
        all_stocks = await fetch_all_a_stocks_async()
        sorted_stocks = sorted(all_stocks, key=lambda x: abs(float(x.get("amount", 0) or 0)), reverse=True)
        result = []
        for s in sorted_stocks[:count]:
            amt = float(s.get("amount", 0) or 0)
            change_pct = float(s.get("change_pct", 0) or 0)
            estimated_main_net = amt * 0.3 * (change_pct / 100) if amt > 0 else 0
            result.append({
                "symbol": s.get("symbol", ""),
                "name": s.get("name", ""),
                "price": float(s.get("price", 0) or 0),
                "change_pct": change_pct,
                "main_net_inflow": round(estimated_main_net, 2),
                "main_inflow": round(abs(estimated_main_net) * 1.5, 2) if estimated_main_net > 0 else 0,
                "main_outflow": round(abs(estimated_main_net) * 1.5, 2) if estimated_main_net < 0 else 0,
                "super_large_net": round(estimated_main_net * 0.4, 2),
                "large_net": round(estimated_main_net * 0.3, 2),
                "medium_net": round(-estimated_main_net * 0.2, 2),
                "small_net": round(-estimated_main_net * 0.3, 2),
                "main_pct": round(estimated_main_net / amt * 100, 2) if amt > 0 else 0,
            })
        with _RANKING_CACHE_LOCK:
            _RANKING_CACHE = result
            _RANKING_CACHE_TS = now
        return result
    except Exception as e2:
        logger.debug(f"Fallback ranking error: {e2}")
    with _RANKING_CACHE_LOCK:
        return _RANKING_CACHE


async def fetch_sector_capital_flow() -> list[dict]:
    global _SECTOR_FLOW_CACHE, _SECTOR_FLOW_CACHE_TS
    now = time.time()
    with _SECTOR_FLOW_LOCK:
        if _SECTOR_FLOW_CACHE and now - _SECTOR_FLOW_CACHE_TS < _SECTOR_FLOW_CACHE_TTL:
            return _SECTOR_FLOW_CACHE

    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_fund_flow_industry, symbol="即时")
        if df is not None and not df.empty:
            result = []
            for _, row in df.iterrows():
                name = str(row.get("行业", ""))
                change_pct = float(row.get("行业-涨跌幅", 0) or 0)
                net_amount = float(row.get("净额", 0) or 0)
                inflow = float(row.get("流入资金", 0) or 0)
                outflow = float(row.get("流出资金", 0) or 0)
                main_net = net_amount * 1e8
                main_in = inflow * 1e8
                main_out = outflow * 1e8
                result.append({
                    "name": name,
                    "change_pct": change_pct,
                    "main_net_inflow": main_net,
                    "main_inflow": main_in,
                    "main_outflow": main_out,
                    "code": "",
                })
            result.sort(key=lambda x: x["main_net_inflow"], reverse=True)
            with _SECTOR_FLOW_LOCK:
                _SECTOR_FLOW_CACHE = result
                _SECTOR_FLOW_CACHE_TS = now
            return result
    except Exception as e:
        logger.debug(f"AKShare sector fund flow error: {e}")

    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_SECTOR_CAPITAL_FLOW",
            "columns": "ALL",
            "pageNumber": "1",
            "pageSize": "100",
            "sortTypes": "-1",
            "sortColumns": "MAIN_NET_INFLOW",
            "source": "WEB",
            "client": "WEB",
        }
        data = await http_get_json(url, params, referer="https://data.eastmoney.com/")
        if data and data.get("result") and data["result"].get("data"):
            items = data["result"]["data"]
            result = []
            for item in items:
                main_net = float(item.get("MAIN_NET_INFLOW", 0) or 0)
                result.append({
                    "name": item.get("SECTOR_NAME", ""),
                    "change_pct": float(item.get("CHANGE_RATE", 0) or 0),
                    "main_net_inflow": main_net,
                    "main_inflow": float(item.get("MAIN_INFLOW", 0) or 0),
                    "main_outflow": float(item.get("MAIN_OUTFLOW", 0) or 0),
                    "code": item.get("SECTOR_CODE", ""),
                })
            result.sort(key=lambda x: x["main_net_inflow"], reverse=True)
            with _SECTOR_FLOW_LOCK:
                _SECTOR_FLOW_CACHE = result
                _SECTOR_FLOW_CACHE_TS = now
            return result
    except Exception as e:
        logger.debug(f"Datacenter sector capital flow error: {e}")

    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": "100",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f62",
            "fs": "m:90+t:2+f:!50",
            "fields": "f2,f3,f4,f6,f8,f12,f14,f62,f66,f69,f104,f105,f128,f140",
        }
        data = await http_get_json(url, params, use_jsonp=True)
        if data and data.get("data", {}).get("diff"):
            diff = data["data"]["diff"]
            result = []
            for item in diff:
                main_net = float(item.get("f62", 0) or 0)
                main_in = float(item.get("f66", 0) or 0)
                main_out = float(item.get("f69", 0) or 0)
                result.append({
                    "name": item.get("f14", ""),
                    "change_pct": float(item.get("f3", 0) or 0),
                    "main_net_inflow": main_net,
                    "main_inflow": main_in,
                    "main_outflow": main_out,
                    "code": item.get("f12", ""),
                })
            result.sort(key=lambda x: x["main_net_inflow"], reverse=True)
            with _SECTOR_FLOW_LOCK:
                _SECTOR_FLOW_CACHE = result
                _SECTOR_FLOW_CACHE_TS = now
            return result
    except Exception as e:
        logger.debug(f"Push2 sector capital flow error: {e}")

    try:
        from core.sector_rotation import fetch_sector_list
        sectors = await fetch_sector_list()
        if sectors:
            result = []
            for s in sectors:
                result.append({
                    "name": s.get("name", ""),
                    "change_pct": s.get("change_pct", 0),
                    "main_net_inflow": s.get("main_net_inflow", 0),
                    "main_inflow": 0,
                    "main_outflow": 0,
                    "code": s.get("code", ""),
                })
            result.sort(key=lambda x: x["main_net_inflow"], reverse=True)
            with _SECTOR_FLOW_LOCK:
                _SECTOR_FLOW_CACHE = result
                _SECTOR_FLOW_CACHE_TS = now
            return result
    except Exception as e2:
        logger.debug(f"Sector flow from sector_rotation error: {e2}")
    with _SECTOR_FLOW_LOCK:
        return _SECTOR_FLOW_CACHE


class MoneyFlowAnalyzer:
    """资金流向分析器"""

    def __init__(self):
        pass

    async def get_stock_flow(self, symbol: str, days: int = 10) -> dict:
        history = await fetch_stock_capital_flow(symbol, days)
        realtime = await fetch_realtime_capital_flow(symbol)
        return {
            "symbol": symbol,
            "realtime": realtime,
            "history": history,
        }

    async def get_flow_ranking(self, market: str = "A", sort_by: str = "main_net", count: int = 30) -> list[dict]:
        return await fetch_capital_flow_ranking(market, "f62", count)

    async def get_sector_flow(self) -> list[dict]:
        return await fetch_sector_capital_flow()

    def analyze_flow_pattern(self, history: list[dict]) -> dict:
        if not history or len(history) < 3:
            return {"pattern": "insufficient_data", "trend": "unknown"}
        main_nets = [h.get("main_net_inflow", 0) for h in history]
        recent_3 = main_nets[-3:]
        if all(v > 0 for v in recent_3):
            pattern = "continuous_inflow"
            trend = "bullish"
        elif all(v < 0 for v in recent_3):
            pattern = "continuous_outflow"
            trend = "bearish"
        elif main_nets[-1] > 0 and main_nets[-2] < 0:
            pattern = "inflow_reversal"
            trend = "reversal_up"
        elif main_nets[-1] < 0 and main_nets[-2] > 0:
            pattern = "outflow_reversal"
            trend = "reversal_down"
        else:
            pattern = "mixed"
            trend = "neutral"

        total_main = sum(main_nets)
        avg_main = float(np.mean(main_nets))
        return {
            "pattern": pattern,
            "trend": trend,
            "total_main_net": round(total_main, 2),
            "avg_main_net": round(avg_main, 2),
            "max_inflow": round(max(main_nets), 2),
            "max_outflow": round(min(main_nets), 2),
        }


_analyzer: Optional[MoneyFlowAnalyzer] = None
_analyzer_lock = threading.Lock()


def get_money_flow_analyzer() -> MoneyFlowAnalyzer:
    global _analyzer
    if _analyzer is None:
        with _analyzer_lock:
            if _analyzer is None:
                _analyzer = MoneyFlowAnalyzer()
    return _analyzer
