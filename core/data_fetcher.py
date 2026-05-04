"""
QuantCore 数据获取模块
支持腾讯、新浪、AKShare等多数据源

asyncio.to_thread 使用审计:
- akshare相关调用保留to_thread: akshare是纯同步库，无法改为async
- baostock相关调用保留to_thread: baostock是纯同步库，无法改为async
- TencentSource.fetch_realtime: 已改为async，不再需要to_thread
- TencentSource.fetch_history: 已改为async，不再需要to_thread
- SinaSource.fetch_realtime: 已改为async，不再需要to_thread
"""
import asyncio
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import aiohttp
import numpy as np
import pandas as pd
from urllib.parse import urlencode

from core.database import SQLiteStore, get_db, ThreadSafeLRU
from core.market_detector import MarketDetector

logger = logging.getLogger(__name__)

try:
    import akshare as ak  # noqa: F811
except ImportError:
    ak = None

try:
    import baostock as bs  # noqa: F811
except ImportError:
    bs = None

_aiohttp_session: Optional[aiohttp.ClientSession] = None
_session_lock = asyncio.Lock()


async def get_aiohttp_session() -> aiohttp.ClientSession:
    global _aiohttp_session
    if _aiohttp_session is None or _aiohttp_session.closed:
        async with _session_lock:
            if _aiohttp_session is None or _aiohttp_session.closed:
                connector = aiohttp.TCPConnector(
                    limit=100,
                    ttl_dns_cache=300,
                    use_dns_cache=True,
                )
                timeout = aiohttp.ClientTimeout(total=8, connect=3)
                _aiohttp_session = aiohttp.ClientSession(
                    connector=connector,
                    timeout=timeout,
                )
    return _aiohttp_session


async def close_aiohttp_session() -> None:
    global _aiohttp_session
    if _aiohttp_session is not None and not _aiohttp_session.closed:
        await _aiohttp_session.close()
        _aiohttp_session = None


async def async_http_get(url: str, headers: Optional[dict] = None) -> Optional[str]:
    try:
        session = await get_aiohttp_session()
        async with session.get(url, headers=headers or {}) as resp:
            if resp.status == 200:
                content = await resp.read()
                try:
                    return content.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        return content.decode('gbk')
                    except UnicodeDecodeError:
                        return content.decode('gb2312', errors='replace')
            logger.debug(f"HTTP GET {url} returned status {resp.status}")
    except asyncio.TimeoutError:
        logger.debug(f"HTTP GET {url} timeout")
    except Exception as e:
        logger.debug(f"HTTP GET {url} error: {e}")
    return None


async def http_get_json(
    url: str,
    params: Optional[dict] = None,
    referer: str = "https://data.eastmoney.com/",
    use_jsonp: bool = False,
) -> Optional[dict]:
    if params is None:
        params = {}
    if use_jsonp:
        params["cb"] = "jQuery_callback"
    full_url = f"{url}?{urlencode(params)}" if params else url
    try:
        text = await async_http_get(full_url, headers={
            "Referer": referer,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })
    except Exception as e:
        logger.debug(f"http_get_json request error for {url}: {e}")
        return None
    if not text:
        return None
    if use_jsonp:
        m = re.search(r'jQuery_callback\((.+)\)\s*;?\s*$', text, re.DOTALL)
        if m:
            text = m.group(1)
        else:
            logger.debug(f"http_get_json JSONP callback not found in response from {url}")
            return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.debug(f"http_get_json JSON decode error for {url}: {e}")
        return None


def _http_get(url: str, headers: Optional[dict] = None) -> Optional[str]:
    try:
        import requests
        resp = requests.get(url, headers=headers or {}, timeout=8)
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception as e:
        logger.debug(f"HTTP GET fallback error for {url}: {e}")
    return None


KLINE_TYPE_MAP = {
    "1d": "daily",
    "1w": "weekly",
    "1M": "monthly",
    "1y": "daily",
    "3y": "daily",
    "5y": "daily",
}

TENCENT_PREFIX_MAP = {
    "A": {
        "0": "sz",
        "3": "sz",
        "6": "sh",
    },
}

CN_INDICES = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000300": "沪深300",
    "sh000905": "中证500",
    "sh000852": "中证1000",
}

HK_INDICES = {
    "HSI": "恒生指数",
    "HSTECH": "恒生科技",
}

US_INDICES = {
    ".DJI": "道琼斯",
    ".IXIC": "纳斯达克",
    ".INX": "标普500",
}

_realtime_cache = ThreadSafeLRU(maxsize=1000, ttl=8)
_history_cache = ThreadSafeLRU(maxsize=500, ttl=120)
_indicator_cache = ThreadSafeLRU(maxsize=300, ttl=300)
_financial_cache = ThreadSafeLRU(maxsize=200, ttl=3600)
_northbound_cache = ThreadSafeLRU(maxsize=50, ttl=60)
_hot_symbols_cache: list[str] = []
_hot_symbols_lock: Optional[asyncio.Lock] = None


def _get_hot_symbols_lock() -> asyncio.Lock:
    global _hot_symbols_lock
    if _hot_symbols_lock is None:
        _hot_symbols_lock = asyncio.Lock()
    return _hot_symbols_lock

CACHE_TTL_TIERS = {
    "realtime": 8,
    "realtime_hot": 3,
    "history": 120,
    "indicator": 300,
    "financial": 3600,
    "northbound": 60,
    "limit_up": 30,
    "dragon_tiger": 300,
}


class DataSourceHealthMonitor:
    """数据源健康度监控，基于内存滑动窗口统计"""

    def __init__(self, db: Optional[SQLiteStore] = None):
        self._db = db or get_db()
        self._memory_stats: dict[tuple[str, str], dict] = {}
        self._pending_writes = 0
        self._write_threshold = 20

    def record_request(self, source_name: str, request_type: str,
                       success: bool, latency: float = 0) -> None:
        key = (source_name, request_type)
        if key not in self._memory_stats:
            self._memory_stats[key] = {
                "success_count": 0,
                "fail_count": 0,
                "latency_sum": 0.0,
                "last_success_ts": 0.0,
            }
        stats = self._memory_stats[key]
        if success:
            stats["success_count"] += 1
            stats["latency_sum"] += latency
            stats["last_success_ts"] = time.time()
        else:
            stats["fail_count"] += 1

        self._pending_writes += 1
        if self._pending_writes >= self._write_threshold:
            self._pending_writes = 0
            try:
                self._db.record_source_request(source_name, request_type, success, latency)
            except Exception as e:
                logger.debug(f"Health monitor write error: {e}")

    def rank_sources(self, source_names: list[str], request_type: str = "realtime") -> list[str]:
        scored = []
        for name in source_names:
            key = (name, request_type)
            if key in self._memory_stats:
                stats = self._memory_stats[key]
                total = stats["success_count"] + stats["fail_count"]
                success_rate = stats["success_count"] / total if total > 0 else 0.5
                avg_latency = stats["latency_sum"] / stats["success_count"] if stats["success_count"] > 0 else 999
                latency_score = 1.0 / (1.0 + avg_latency)
                score = success_rate * 0.6 + latency_score * 0.4
            else:
                try:
                    db_stats = self._db.get_source_stats(name, request_type)
                    if db_stats:
                        s = db_stats[0]
                        total = s.get("success_count", 0) + s.get("fail_count", 0)
                        success_rate = s.get("success_count", 0) / total if total > 0 else 0.5
                        avg_latency = s.get("avg_latency", 999)
                        latency_score = 1.0 / (1.0 + avg_latency)
                        score = success_rate * 0.6 + latency_score * 0.4
                    else:
                        score = 0.5
                except Exception as e:
                    logger.debug(f"Source ranking error for {name}: {e}")
                    score = 0.5
            scored.append((name, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in scored]


class TencentSource:
    """腾讯财经数据源"""

    BASE_URL = "http://qt.gtimg.cn/q="

    @staticmethod
    def _build_code(symbol: str, market: str) -> str:
        clean = re.sub(r"^(sh|sz|SH|SZ)", "", str(symbol)).strip()
        if market == "A":
            if clean.startswith("6"):
                return f"sh{clean}"
            return f"sz{clean}"
        if market == "HK":
            return f"hk{clean.zfill(5)}"
        if market == "US":
            return f"us{clean.upper()}"
        return clean

    @staticmethod
    async def fetch_realtime(symbol: str, market: str) -> Optional[dict]:
        code = TencentSource._build_code(symbol, market)
        url = f"{TencentSource.BASE_URL}{code}"
        text = await async_http_get(url)
        if not text:
            return None
        return TencentSource._parse_realtime(text, symbol, market)

    @staticmethod
    async def fetch_batch_realtime(codes: list[str]) -> dict[str, dict]:
        if not codes:
            return {}
        url = f"{TencentSource.BASE_URL}{','.join(codes)}"
        text = await async_http_get(url)
        if not text:
            return {}
        results = {}
        for line in text.strip().split(";"):
            line = line.strip()
            if not line or "~" not in line:
                continue
            parts = line.split("~")
            if len(parts) < 45:
                continue
            try:
                raw_code = parts[0]
                match = re.search(r'q="([^"]+)"', raw_code)
                code_key = match.group(1) if match else parts[2] if len(parts) > 2 else ""
                results[code_key] = {
                    "name": parts[1] if len(parts) > 1 else "",
                    "code": parts[2] if len(parts) > 2 else "",
                    "price": float(parts[3]) if len(parts) > 3 and parts[3] else 0,
                    "last_close": float(parts[4]) if len(parts) > 4 and parts[4] else 0,
                    "open": float(parts[5]) if len(parts) > 5 and parts[5] else 0,
                    "volume": float(parts[6]) if len(parts) > 6 and parts[6] else 0,
                    "amount": float(parts[37]) if len(parts) > 37 and parts[37] else 0,
                    "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                    "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                    "change_pct": float(parts[32]) if len(parts) > 32 and parts[32] else 0,
                    "change": float(parts[31]) if len(parts) > 31 and parts[31] else 0,
                    "turnover_rate": float(parts[38]) if len(parts) > 38 and parts[38] else 0,
                }
            except (ValueError, IndexError):
                continue
        return results

    @staticmethod
    async def fetch_history(symbol: str, market: str, kline_type: str = "daily",
                            adjust: str = "", count: int = 300) -> Optional[pd.DataFrame]:
        code = TencentSource._build_code(symbol, market)
        ktype_map = {"daily": "day", "weekly": "week", "monthly": "month"}
        ktype = ktype_map.get(kline_type, "day")
        url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},{ktype},,,{count},,"
        if adjust == "qfq":
            url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},{ktype},,,{count},1,"
        text = await async_http_get(url)
        if not text:
            return None
        try:
            data = json.loads(text)
            keys = list(data.get("data", {}).keys())
            if not keys:
                return None
            stock_data = data["data"][keys[0]]
            day_key = ktype
            if day_key not in stock_data:
                day_key = "day"
            raw_rows = stock_data.get(day_key, [])
            if not raw_rows:
                return None
            rows = []
            for r in raw_rows:
                if len(r) >= 6:
                    rows.append({
                        "date": r[0],
                        "open": float(r[1]),
                        "close": float(r[2]),
                        "high": float(r[3]),
                        "low": float(r[4]),
                        "volume": float(r[5]),
                        "amount": float(r[6]) if len(r) > 6 else 0,
                    })
            if rows:
                return pd.DataFrame(rows)
        except (json.JSONDecodeError, KeyError, ValueError, IndexError) as e:
            logger.debug(f"Tencent history parse error: {e}")
        return None

    @staticmethod
    def _parse_realtime(text: str, symbol: str, market: str) -> Optional[dict]:
        for line in text.strip().split(";"):
            line = line.strip()
            if not line or "~" not in line:
                continue
            parts = line.split("~")
            if len(parts) < 45:
                continue
            try:
                return {
                    "symbol": symbol,
                    "market": market,
                    "name": parts[1],
                    "price": float(parts[3]),
                    "last_close": float(parts[4]),
                    "open": float(parts[5]),
                    "volume": float(parts[6]),
                    "high": float(parts[33]) if len(parts) > 33 else 0,
                    "low": float(parts[34]) if len(parts) > 34 else 0,
                    "change_pct": float(parts[32]) if len(parts) > 32 else 0,
                    "change": float(parts[31]) if len(parts) > 31 else 0,
                    "amount": float(parts[37]) if len(parts) > 37 else 0,
                    "turnover_rate": float(parts[38]) if len(parts) > 38 else 0,
                    "timestamp": time.time(),
                }
            except (ValueError, IndexError):
                continue
        return None


class SinaSource:
    """新浪财经数据源"""

    @staticmethod
    async def fetch_realtime(symbol: str, market: str) -> Optional[dict]:
        clean = re.sub(r"^(sh|sz|SH|SZ)", "", str(symbol)).strip()
        if market == "A":
            if clean.startswith("6"):
                prefix = "sh"
            else:
                prefix = "sz"
            url = f"http://hq.sinajs.cn/list={prefix}{clean}"
        elif market == "HK":
            url = f"http://hq.sinajs.cn/list=rt_hk{clean.zfill(5)}"
        elif market == "US":
            url = f"http://hq.sinajs.cn/list=gb_{clean.lower()}"
        else:
            return None

        headers = {"Referer": "http://finance.sina.com.cn"}
        text = await async_http_get(url, headers=headers)
        if not text:
            return None
        return SinaSource._parse_realtime(text, symbol, market)

    @staticmethod
    def _parse_realtime(text: str, symbol: str, market: str) -> Optional[dict]:
        try:
            for line in text.strip().split("\n"):
                if '="' not in line:
                    continue
                _, data_part = line.split('="', 1)
                data_part = data_part.rstrip('";')
                if not data_part:
                    continue
                fields = data_part.split(",")
                if market == "A" and len(fields) >= 32:
                    name = fields[0]
                    open_price = float(fields[1]) if fields[1] else 0
                    last_close = float(fields[2]) if fields[2] else 0
                    price = float(fields[3]) if fields[3] else 0
                    high = float(fields[4]) if fields[4] else 0
                    low = float(fields[5]) if fields[5] else 0
                    volume = float(fields[8]) if fields[8] else 0
                    amount = float(fields[9]) if fields[9] else 0
                    change = price - last_close if last_close > 0 else 0
                    change_pct = (change / last_close * 100) if last_close > 0 else 0
                    return {
                        "symbol": symbol,
                        "market": market,
                        "name": name,
                        "price": price,
                        "last_close": last_close,
                        "open": open_price,
                        "volume": volume,
                        "high": high,
                        "low": low,
                        "change_pct": round(change_pct, 2),
                        "change": round(change, 3),
                        "amount": amount,
                        "turnover_rate": 0,
                        "timestamp": time.time(),
                    }
                elif market == "HK" and len(fields) >= 13:
                    name = fields[1]
                    open_price = float(fields[2]) if fields[2] else 0
                    last_close = float(fields[3]) if fields[3] else 0
                    high = float(fields[4]) if fields[4] else 0
                    low = float(fields[5]) if fields[5] else 0
                    price = float(fields[6]) if fields[6] else 0
                    volume = float(fields[12]) if fields[12] else 0
                    amount = float(fields[11]) if fields[11] else 0
                    change = price - last_close if last_close > 0 else 0
                    change_pct = (change / last_close * 100) if last_close > 0 else 0
                    return {
                        "symbol": symbol,
                        "market": market,
                        "name": name,
                        "price": price,
                        "last_close": last_close,
                        "open": open_price,
                        "volume": volume,
                        "high": high,
                        "low": low,
                        "change_pct": round(change_pct, 2),
                        "change": round(change, 3),
                        "amount": amount,
                        "turnover_rate": 0,
                        "timestamp": time.time(),
                    }
                elif market == "US" and len(fields) >= 9:
                    name = fields[0]
                    price = float(fields[1]) if fields[1] else 0
                    change_pct = float(fields[2]) if fields[2] else 0
                    change = float(fields[3]) if fields[3] else 0
                    open_price = float(fields[4]) if fields[4] else 0
                    high = float(fields[5]) if fields[5] else 0
                    low = float(fields[6]) if fields[6] else 0
                    volume = float(fields[8]) if fields[8] else 0
                    last_close = price - change if change else 0
                    return {
                        "symbol": symbol,
                        "market": market,
                        "name": name,
                        "price": price,
                        "last_close": last_close,
                        "open": open_price,
                        "volume": volume,
                        "high": high,
                        "low": low,
                        "change_pct": round(change_pct, 2),
                        "change": round(change, 3),
                        "amount": 0,
                        "turnover_rate": 0,
                        "timestamp": time.time(),
                    }
        except (ValueError, IndexError) as e:
            logger.debug(f"Sina parse error for {symbol}: {e}")
        return None


def safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        if value in (None, "-", ""):
            return default
        val = float(value)
        return val if pd.notna(val) else default
    except (TypeError, ValueError):
        return default


class EastMoneySource:
    """东方财富数据源"""

    QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
    KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    DATA_URL = "https://datacenter.eastmoney.com/api/data/v1/get"

    @staticmethod
    def _clean_symbol(symbol: str) -> str:
        code = re.sub(r"^(sh|sz|SH|SZ)", "", str(symbol)).strip()
        if not re.match(r'^[0-9a-zA-Z]{1,10}$', code):
            return ""
        return code

    @staticmethod
    def _secid(symbol: str, market: str = "A") -> str:
        code = EastMoneySource._clean_symbol(symbol)
        if market == "A":
            return f"1.{code}" if code.startswith("6") else f"0.{code}"
        return code

    @staticmethod
    def _num(value: Any, default: float = 0.0) -> float:
        return safe_float(value, default)

    @staticmethod
    async def fetch_realtime(symbol: str, market: str) -> Optional[dict]:
        if market != "A":
            return None
        code = EastMoneySource._clean_symbol(symbol)
        fields = "f43,f44,f45,f46,f47,f48,f57,f58,f60,f116,f117,f168,f169,f170"
        url = f"{EastMoneySource.QUOTE_URL}?secid={EastMoneySource._secid(code, market)}&fields={fields}"
        text = await async_http_get(url, headers={"Referer": "https://finance.eastmoney.com"})
        if not text:
            return None
        try:
            payload = json.loads(text)
            data = payload.get("data") or {}
            if not data:
                return None
            price = EastMoneySource._num(data.get("f43"))
            last_close = EastMoneySource._num(data.get("f60"))
            return {
                "symbol": code,
                "market": market,
                "name": data.get("f58") or code,
                "price": price,
                "last_close": last_close,
                "open": EastMoneySource._num(data.get("f46")),
                "high": EastMoneySource._num(data.get("f44")),
                "low": EastMoneySource._num(data.get("f45")),
                "volume": EastMoneySource._num(data.get("f47")),
                "amount": EastMoneySource._num(data.get("f48")),
                "change": EastMoneySource._num(data.get("f169")),
                "change_pct": EastMoneySource._num(data.get("f170")),
                "turnover_rate": EastMoneySource._num(data.get("f168")),
                "total_market_cap": EastMoneySource._num(data.get("f116")),
                "float_market_cap": EastMoneySource._num(data.get("f117")),
                "timestamp": time.time(),
            }
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.debug(f"EastMoney realtime parse error: {e}")
            return None

    @staticmethod
    async def fetch_history_em(symbol: str, market: str, ktype: str = "101",
                               fqt: int = 1) -> Optional[pd.DataFrame]:
        if market != "A":
            return None
        code = EastMoneySource._clean_symbol(symbol)
        fields1 = "f1,f2,f3,f4,f5,f6"
        fields2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        url = (
            f"{EastMoneySource.KLINE_URL}?secid={EastMoneySource._secid(code, market)}"
            f"&klt={ktype}&fqt={int(fqt)}&fields1={fields1}&fields2={fields2}"
        )
        text = await async_http_get(url, headers={"Referer": "https://quote.eastmoney.com"})
        if not text:
            return None
        try:
            payload = json.loads(text)
            klines = ((payload.get("data") or {}).get("klines")) or []
            rows = []
            for raw in klines:
                parts = str(raw).split(",")
                if len(parts) < 7:
                    continue
                rows.append({
                    "date": parts[0],
                    "open": EastMoneySource._num(parts[1], np.nan),
                    "close": EastMoneySource._num(parts[2], np.nan),
                    "high": EastMoneySource._num(parts[3], np.nan),
                    "low": EastMoneySource._num(parts[4], np.nan),
                    "volume": EastMoneySource._num(parts[5], 0.0),
                    "amount": EastMoneySource._num(parts[6], 0.0),
                    "change_pct": EastMoneySource._num(parts[8], 0.0) if len(parts) > 8 else 0.0,
                    "turnover_rate": EastMoneySource._num(parts[10], 0.0) if len(parts) > 10 else 0.0,
                })
            if rows:
                return pd.DataFrame(rows)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.debug(f"EastMoney history parse error: {e}")
        return None

    @staticmethod
    async def fetch_financial_report(symbol: str) -> Optional[dict]:
        code = EastMoneySource._clean_symbol(symbol)
        fields = "SECURITY_CODE,PE_TTM,PB_MRQ,BASIC_EPS,ROE_WEIGHT,OPERATE_INCOME_YOY,NETPROFIT_YOY,DEBT_ASSET_RATIO"
        url = (
            f"{EastMoneySource.DATA_URL}?reportName=RPT_F10_FINANCE_GMAININDICATOR"
            f"&columns={fields}&filter=(SECURITY_CODE=\"{code}\")&pageNumber=1&pageSize=1"
        )
        text = await async_http_get(url, headers={"Referer": "https://data.eastmoney.com"})
        if not text:
            return None
        try:
            payload = json.loads(text)
            records = ((payload.get("result") or {}).get("data")) or []
            item = records[0] if records else {}
            return {
                "pe_ttm": EastMoneySource._num(item.get("PE_TTM")),
                "pb": EastMoneySource._num(item.get("PB_MRQ")),
                "roe": EastMoneySource._num(item.get("ROE_WEIGHT")),
                "eps": EastMoneySource._num(item.get("BASIC_EPS")),
                "revenue_yoy": EastMoneySource._num(item.get("OPERATE_INCOME_YOY")),
                "profit_yoy": EastMoneySource._num(item.get("NETPROFIT_YOY")),
                "debt_ratio": EastMoneySource._num(item.get("DEBT_ASSET_RATIO")),
            }
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.debug(f"EastMoney financial parse error: {e}")
            return None

    @staticmethod
    async def fetch_north_bound_flow(date=None) -> Optional[dict]:
        try:
            if ak is None:
                return None
            df_sh = await asyncio.to_thread(ak.stock_hsgt_hist_em, symbol="沪股通")
            df_sz = await asyncio.to_thread(ak.stock_hsgt_hist_em, symbol="深股通")
            valid_sh = df_sh.dropna(subset=["当日成交净买额"]) if df_sh is not None and len(df_sh) > 0 else pd.DataFrame()
            valid_sz = df_sz.dropna(subset=["当日成交净买额"]) if df_sz is not None and len(df_sz) > 0 else pd.DataFrame()
            if len(valid_sh) == 0 and len(valid_sz) == 0:
                return None
            sh_row = valid_sh.iloc[-1] if len(valid_sh) > 0 else None
            sz_row = valid_sz.iloc[-1] if len(valid_sz) > 0 else None
            sh_buy = float(sh_row["买入成交额"]) if sh_row is not None else 0.0
            sh_sell = float(sh_row["卖出成交额"]) if sh_row is not None else 0.0
            sz_buy = float(sz_row["买入成交额"]) if sz_row is not None else 0.0
            sz_sell = float(sz_row["卖出成交额"]) if sz_row is not None else 0.0
            sh_net = float(sh_row["当日成交净买额"]) if sh_row is not None else 0.0
            sz_net = float(sz_row["当日成交净买额"]) if sz_row is not None else 0.0
            return {
                "sh_buy": sh_buy,
                "sh_sell": sh_sell,
                "sz_buy": sz_buy,
                "sz_sell": sz_sell,
                "total_net": sh_net + sz_net,
                "top_stocks": [],
            }
        except Exception as e:
            logger.debug(f"akshare northbound fetch error: {e}")
            return None

    @staticmethod
    async def fetch_limit_up_pool() -> list[dict]:
        date_str = datetime.now().strftime("%Y%m%d")
        url = f"https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989&d={date_str}&Pageindex=0&pagesize=100"
        text = await async_http_get(url, headers={"Referer": "https://quote.eastmoney.com"})
        if not text:
            return []
        try:
            payload = json.loads(text)
            pool = ((payload.get("data") or {}).get("pool")) or []
            return [{
                "code": item.get("c", ""),
                "name": item.get("n", ""),
                "time": item.get("t", ""),
                "reason": item.get("zttj", {}).get("ct", "") if isinstance(item.get("zttj"), dict) else "",
                "chain_count": int(EastMoneySource._num(item.get("lbc"), 0)),
                "seal_amount": EastMoneySource._num(item.get("fund")),
            } for item in pool]
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.debug(f"EastMoney limit-up parse error: {e}")
            return []

    @staticmethod
    async def fetch_dragon_tiger_list(date=None) -> list[dict]:
        date_str = date or datetime.now().strftime("%Y-%m-%d")
        url = (
            f"{EastMoneySource.DATA_URL}?reportName=RPT_DAILYBILLBOARD_DETAILSNEW"
            f"&columns=ALL&filter=(TRADE_DATE='{date_str}')&pageNumber=1&pageSize=100"
        )
        text = await async_http_get(url, headers={"Referer": "https://data.eastmoney.com"})
        if not text:
            return []
        try:
            payload = json.loads(text)
            records = ((payload.get("result") or {}).get("data")) or []
            return [{
                "code": item.get("SECURITY_CODE", ""),
                "name": item.get("SECURITY_NAME_ABBR", ""),
                "reason": item.get("EXPLAIN", ""),
                "buy_amount": EastMoneySource._num(item.get("BILLBOARD_BUY_AMT")),
                "sell_amount": EastMoneySource._num(item.get("BILLBOARD_SELL_AMT")),
                "institutions": item.get("ORG_NAME", ""),
            } for item in records]
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.debug(f"EastMoney dragon-tiger parse error: {e}")
            return []

    @staticmethod
    def simulate_level2_depth(current_price: float, volume: float,
                              avg_volume: float = 0, n_levels: int = 5) -> dict:
        """基于1分钟K线模拟盘口深度（买一到买五/卖一到卖五）"""
        if current_price <= 0:
            return {"bids": [], "asks": []}
        tick = max(current_price * 0.001, 0.01)
        vol_ratio = (volume / avg_volume) if avg_volume > 0 else 1.0
        base_qty = max(volume * 0.05, 100)
        rng = np.random.default_rng()
        bids = []
        asks = []
        for i in range(n_levels):
            bid_price = round(current_price - tick * (i + 1), 2)
            ask_price = round(current_price + tick * (i + 1), 2)
            depth_decay = 1.0 / (i + 1)
            noise = rng.uniform(0.5, 1.5)
            bid_qty = int(base_qty * depth_decay * noise * min(vol_ratio, 3.0))
            ask_qty = int(base_qty * depth_decay * noise * min(vol_ratio, 3.0))
            bids.append({"price": bid_price, "quantity": bid_qty})
            asks.append({"price": ask_price, "quantity": ask_qty})
        return {"bids": bids, "asks": asks}


class DataQualityChecker:
    @staticmethod
    def check_kline(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        warnings = []
        if df is None or df.empty:
            return pd.DataFrame(), ["empty_kline"]

        cleaned = df.copy()
        if "date" in cleaned.columns:
            cleaned["date"] = pd.to_datetime(cleaned["date"], errors="coerce")
            bad_dates = cleaned["date"].isna().sum()
            if bad_dates:
                warnings.append(f"invalid_date:{bad_dates}")
            cleaned = cleaned.dropna(subset=["date"]).sort_values("date").drop_duplicates("date").reset_index(drop=True)

        numeric_cols = [c for c in ["open", "high", "low", "close", "volume", "amount", "turnover_rate"] if c in cleaned.columns]
        for col in numeric_cols:
            cleaned[col] = pd.to_numeric(cleaned[col], errors="coerce")
            na_run = cleaned[col].isna().astype(int).groupby(cleaned[col].notna().cumsum()).sum().max()
            if pd.notna(na_run) and na_run >= 3:
                warnings.append(f"{col}_consecutive_nan:{int(na_run)}")
            cleaned[col] = cleaned[col].interpolate(limit=1, limit_direction="both")

        price_cols = [c for c in ["open", "high", "low", "close"] if c in cleaned.columns]
        if price_cols:
            non_positive = (cleaned[price_cols] <= 0).any(axis=1).sum()
            if non_positive:
                warnings.append(f"non_positive_price:{int(non_positive)}")
                cleaned.loc[(cleaned[price_cols] <= 0).any(axis=1), price_cols] = np.nan
                cleaned[price_cols] = cleaned[price_cols].interpolate(limit=1, limit_direction="both")

        if {"open", "high", "low", "close"}.issubset(cleaned.columns):
            row_high = cleaned[["open", "close", "high"]].max(axis=1)
            row_low = cleaned[["open", "close", "low"]].min(axis=1)
            ohlc_bad = ((cleaned["high"] < cleaned[["open", "close"]].max(axis=1)) |
                        (cleaned["low"] > cleaned[["open", "close"]].min(axis=1))).sum()
            if ohlc_bad:
                warnings.append(f"ohlc_fixed:{int(ohlc_bad)}")
            cleaned["high"] = row_high
            cleaned["low"] = row_low

            pct = cleaned["close"].pct_change()
            suspicious = pct.abs() > 0.20
            if suspicious.any():
                warnings.append(f"suspicious_price_move:{int(suspicious.sum())}")

        if {"volume", "close"}.issubset(cleaned.columns):
            vol_zero_move = ((cleaned["volume"].fillna(0) <= 0) & (cleaned["close"].pct_change().abs() > 0.001)).sum()
            if vol_zero_move:
                warnings.append(f"zero_volume_with_price_move:{int(vol_zero_move)}")
            cleaned["volume"] = cleaned["volume"].fillna(0).clip(lower=0)

        cleaned = cleaned.dropna(subset=[c for c in ["open", "high", "low", "close"] if c in cleaned.columns])
        return cleaned.reset_index(drop=True), warnings

    @staticmethod
    def detect_corporate_actions(df: pd.DataFrame) -> list[dict]:
        if df is None or df.empty or "close" not in df.columns:
            return []
        data = df.copy()
        if "date" not in data.columns:
            data["date"] = np.arange(len(data))
        close = pd.to_numeric(data["close"], errors="coerce")
        volume = pd.to_numeric(data["volume"], errors="coerce") if "volume" in data.columns else pd.Series(0, index=data.index)
        ratio = close / close.shift(1)
        vol_ratio = volume / volume.rolling(20).mean().replace(0, np.nan)
        events = []
        mask = (ratio < 0.7) | (ratio > 1.3)
        for idx in data.index[mask.fillna(False)]:
            events.append({
                "date": str(data.loc[idx, "date"])[:10],
                "type": "split_or_adjustment",
                "ratio": round(float(ratio.loc[idx]), 4),
                "volume_ratio": round(float(vol_ratio.loc[idx]), 4) if pd.notna(vol_ratio.loc[idx]) else 0,
            })
        return events

    @staticmethod
    def normalize_adjust_factor(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        cleaned, _ = DataQualityChecker.check_kline(df)
        return cleaned


class CircuitBreaker:
    """防止级联失败的断路器"""

    def __init__(self, failure_threshold=5, timeout=60, half_open_calls=2):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.state = "CLOSED"
        self.last_failure_time = 0.0
        self.half_open_calls = 0
        self.half_open_max = half_open_calls
        self._lock = asyncio.Lock()

    @staticmethod
    def _is_valid_result(result) -> bool:
        if result is None:
            return False
        if isinstance(result, pd.DataFrame):
            return not result.empty
        if isinstance(result, dict):
            return len(result) > 0
        if isinstance(result, (list, tuple)):
            return len(result) > 0
        return True

    async def call(self, func, *args, **kwargs):
        async with self._lock:
            if self.state == "OPEN":
                if time.time() - self.last_failure_time > self.timeout:
                    self.state = "HALF_OPEN"
                    self.half_open_calls = 0
                else:
                    raise Exception(f"Circuit breaker OPEN for {getattr(func, '__name__', 'source')}")

        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                if self.state == "HALF_OPEN":
                    self.half_open_calls += 1
                    if self.half_open_calls >= self.half_open_max:
                        self.state = "CLOSED"
                        self.failure_count = 0
                elif self._is_valid_result(result):
                    self.failure_count = 0
                else:
                    self.failure_count += 1
                    self.last_failure_time = time.time()
                    if self.failure_count >= self.failure_threshold:
                        self.state = "OPEN"
            return result
        except Exception as e:
            logger.debug(f"CircuitBreaker call error: {e}")
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                if self.failure_count >= self.failure_threshold:
                    self.state = "OPEN"
            raise


def validate_realtime_data(data: dict, symbol: str) -> bool:
    if not data:
        return False
    price = EastMoneySource._num(data.get("price"))
    pct = EastMoneySource._num(data.get("change_pct"))
    volume = EastMoneySource._num(data.get("volume"))
    ts = data.get("timestamp", time.time())
    try:
        ts_date = datetime.fromtimestamp(float(ts)).date()
    except (ValueError, TypeError, OSError):
        ts_date = datetime.now().date()
    ok = price > 0 and -20 <= pct <= 20 and volume >= 0 and ts_date >= (datetime.now().date() - timedelta(days=1))
    if not ok:
        logger.debug(f"Invalid realtime data for {symbol}: {data}")
    return ok


def validate_kline_data(df: pd.DataFrame, symbol: str) -> bool:
    if df is None or len(df) < 10 or "date" not in df.columns:
        logger.debug(f"Invalid kline data for {symbol}: insufficient rows/date")
        return False
    data = df.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    price_cols = [c for c in ["open", "high", "low", "close"] if c in data.columns]
    ok = data["date"].notna().all() and data["date"].is_monotonic_increasing
    if price_cols:
        ok = ok and (data[price_cols] > 0).all().all()
    if not ok:
        logger.debug(f"Invalid kline data for {symbol}")
    return bool(ok)


class AKShareSource:
    """AKShare数据源（同步库，保留to_thread）"""

    @staticmethod
    async def fetch_history(symbol: str, market: str, kline_type: str = "daily",
                            adjust: str = "", period: str = "1y") -> Optional[pd.DataFrame]:
        try:
            df = await asyncio.to_thread(AKShareSource._sync_fetch_history,
                                         symbol, market, kline_type, adjust, period)
            return df
        except Exception as e:
            logger.debug(f"AKShare fetch_history error: {e}")
            return None

    @staticmethod
    def _sync_fetch_history(symbol: str, market: str, kline_type: str = "daily",
                            adjust: str = "", period: str = "1y") -> Optional[pd.DataFrame]:
        try:
            if ak is None:
                return None
            if market == "A":
                period_map = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}
                adj_map = {"qfq": "qfq", "hfq": "hfq", "": ""}
                ktype = period_map.get(kline_type, "daily")
                adj = adj_map.get(adjust, "")
                if adj:
                    df = ak.stock_zh_a_hist(symbol=symbol, period=ktype, adjust=adj)
                else:
                    df = ak.stock_zh_a_hist(symbol=symbol, period=ktype)
                if df is not None and not df.empty:
                    rename_map = {
                        "日期": "date", "开盘": "open", "收盘": "close",
                        "最高": "high", "最低": "low", "成交量": "volume",
                        "成交额": "amount", "换手率": "turnover_rate",
                    }
                    df = df.rename(columns=rename_map)
                    for col in ["open", "high", "low", "close", "volume", "amount"]:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors="coerce")
                    return df
            elif market == "HK":
                df = ak.stock_hk_hist(symbol=symbol, period=kline_type, adjust=adjust or "")
                if df is not None and not df.empty:
                    rename_map = {
                        "日期": "date", "开盘": "open", "收盘": "close",
                        "最高": "high", "最低": "low", "成交量": "volume",
                        "成交额": "amount",
                    }
                    df = df.rename(columns=rename_map)
                    return df
            elif market == "US":
                df = ak.stock_us_hist(symbol=symbol, period=kline_type, adjust=adjust or "")
                if df is not None and not df.empty:
                    rename_map = {
                        "日期": "date", "开盘": "open", "收盘": "close",
                        "最高": "high", "最低": "low", "成交量": "volume",
                        "成交额": "amount",
                    }
                    df = df.rename(columns=rename_map)
                    return df
        except Exception as e:
            logger.debug(f"AKShare sync fetch error: {e}")
        return None

    @staticmethod
    async def fetch_fundamentals(symbol: str, market: str) -> Optional[dict]:
        try:
            result = await asyncio.to_thread(AKShareSource._sync_fetch_fundamentals, symbol, market)
            return result
        except Exception as e:
            logger.debug(f"AKShare fundamentals error: {e}")
            return None

    @staticmethod
    def _sync_fetch_fundamentals(symbol: str, market: str) -> Optional[dict]:
        try:
            if ak is None:
                return None
            if market != "A":
                return None
            df = ak.stock_individual_info_em(symbol=symbol)
            if df is None or df.empty:
                return None
            result = {}
            for _, row in df.iterrows():
                key = str(row.iloc[0]).strip()
                val = str(row.iloc[1]).strip() if len(row) > 1 else ""
                result[key] = val
            return result
        except Exception as e:
            logger.debug(f"AKShare fundamentals sync error: {e}")
        return None


class BaoStockSource:
    """BaoStock数据源（同步库，保留to_thread）"""

    @staticmethod
    async def fetch_history(symbol: str, market: str, kline_type: str = "daily",
                            adjust: str = "", start_date: str = "",
                            end_date: str = "") -> Optional[pd.DataFrame]:
        try:
            df = await asyncio.to_thread(BaoStockSource._sync_fetch_history,
                                         symbol, market, kline_type, adjust, start_date, end_date)
            return df
        except Exception as e:
            logger.debug(f"BaoStock fetch error: {e}")
            return None

    @staticmethod
    def _sync_fetch_history(symbol: str, market: str, kline_type: str = "daily",
                            adjust: str = "", start_date: str = "",
                            end_date: str = "") -> Optional[pd.DataFrame]:
        try:
            if bs is None:
                return None
            lg = bs.login()
            if lg.error_code != "0":
                return None

            if not end_date:
                end_date = datetime.now().strftime("%Y-%m-%d")
            if not start_date:
                start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

            if market == "A":
                if symbol.startswith("6"):
                    bs_code = f"sh.{symbol}"
                else:
                    bs_code = f"sz.{symbol}"
            else:
                bs.logout()
                return None

            freq_map = {"daily": "d", "weekly": "w", "monthly": "m"}
            freq = freq_map.get(kline_type, "d")
            adjust_flag = "2" if adjust == "qfq" else "1" if adjust == "hfq" else "3"

            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount,turn",
                start_date=start_date,
                end_date=end_date,
                frequency=freq,
                adjustflag=adjust_flag,
            )

            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())

            bs.logout()

            if not rows:
                return None

            df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount", "turnover_rate"])
            for col in ["open", "high", "low", "close", "volume", "amount"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        except Exception as e:
            logger.debug(f"BaoStock sync error: {e}")
            try:
                bs.logout()
            except Exception as e:
                logger.debug(f"BaoStock logout failed: {e}")
            return None


class SmartDataFetcher:
    """智能数据获取器，自动选择最优数据源"""

    def __init__(self, db: Optional[SQLiteStore] = None):
        self._db = db or get_db()
        self._health = DataSourceHealthMonitor(self._db)
        self._sources = {
            "eastmoney": EastMoneySource,
            "tencent": TencentSource,
            "sina": SinaSource,
        }
        self._circuit_breakers = {
            "eastmoney": CircuitBreaker(failure_threshold=5, timeout=30),
            "tencent": CircuitBreaker(failure_threshold=5, timeout=30),
            "sina": CircuitBreaker(failure_threshold=5, timeout=30),
            "akshare": CircuitBreaker(failure_threshold=3, timeout=120),
            "baostock": CircuitBreaker(failure_threshold=3, timeout=120),
        }

    async def get_realtime(self, symbol: str, market: Optional[str] = None) -> Optional[dict]:
        if market is None:
            market = MarketDetector.detect(symbol)

        clean_symbol = re.sub(r"^(sh|sz|SH|SZ)", "", str(symbol)).strip()
        cache_key = f"rt_{clean_symbol}_{market}"
        cached = _realtime_cache.get(cache_key)
        if cached is not None:
            return cached

        ranked = self._health.rank_sources(["eastmoney", "tencent", "sina"], "realtime")

        for source_name in ranked:
            source = self._sources.get(source_name)
            if source is None:
                continue
            start = time.time()
            try:
                breaker = self._circuit_breakers.get(source_name)
                if breaker:
                    result = await breaker.call(source.fetch_realtime, symbol, market)
                else:
                    result = await source.fetch_realtime(symbol, market)
                latency = time.time() - start
                if result and validate_realtime_data(result, symbol):
                    self._health.record_request(source_name, "realtime", True, latency)
                    _realtime_cache.set(cache_key, result)
                    try:
                        from core.metrics import metrics
                        metrics.increment("data_fetch_success", tags={"source": source_name, "type": "realtime"})
                        metrics.timer("data_fetch_latency", latency, tags={"source": source_name, "type": "realtime"})
                    except Exception as e:
                        logger.debug(f"Metrics recording failed: {e}")
                    return result
                self._health.record_request(source_name, "realtime", False, latency)
            except Exception as e:
                latency = time.time() - start
                self._health.record_request(source_name, "realtime", False, latency)
                logger.debug(f"Source {source_name} realtime error: {e}")

        return None

    async def get_realtime_batch(self, symbols: list[str]) -> dict[str, dict]:
        """批量获取A股实时数据，港股美股走并发单只"""
        results: dict[str, dict] = {}
        a_symbols = []
        other_symbols = []

        for s in symbols:
            market = MarketDetector.detect(s)
            if market == "A":
                a_symbols.append((s, market))
            else:
                other_symbols.append((s, market))

        if a_symbols:
            for i in range(0, len(a_symbols), 50):
                batch = a_symbols[i:i + 50]
                codes = [TencentSource._build_code(s, m) for s, m in batch]
                batch_results = await TencentSource.fetch_batch_realtime(codes)
                code_to_symbol = {TencentSource._build_code(s, m): (s, m) for s, m in batch}
                for code_key, data in batch_results.items():
                    if code_key in code_to_symbol:
                        sym, mkt = code_to_symbol[code_key]
                        data["symbol"] = sym
                        data["market"] = mkt
                        results[sym] = data

                for s, m in batch:
                    if s not in results:
                        try:
                            rt = await self.get_realtime(s, m)
                            if rt:
                                results[s] = rt
                        except Exception as e:
                            logger.debug(f"Batch realtime fetch failed for {s}: {e}")

        if other_symbols:
            tasks = [self.get_realtime(s, m) for s, m in other_symbols]
            other_results = await asyncio.gather(*tasks, return_exceptions=True)
            for (s, m), result in zip(other_symbols, other_results):
                if isinstance(result, dict):
                    results[s] = result

        return results

    async def get_history(self, symbol: str, period: str = "1y",
                          kline_type: str = "daily",
                          adjust: str = "") -> pd.DataFrame:
        if kline_type == "daily" and period in KLINE_TYPE_MAP and not adjust:
            kline_type = KLINE_TYPE_MAP[period]

        market = MarketDetector.detect(symbol)
        clean_symbol = re.sub(r"^(sh|sz|SH|SZ)", "", str(symbol)).strip()

        cache_key = f"hist_{clean_symbol}_{market}_{kline_type}_{adjust}_{period}"
        cached = _history_cache.get(cache_key)
        if cached is not None:
            return cached

        db_df = self._db.load_kline_rows(clean_symbol, market, kline_type, adjust)
        if not db_df.empty and len(db_df) >= 30:
            _history_cache.set(cache_key, db_df)
            return db_df

        df = await self._fetch_history_from_sources(clean_symbol, market, kline_type, adjust, period)
        if df is not None and not df.empty:
            df, warnings = DataQualityChecker.check_kline(df)
            if warnings:
                logger.debug(f"Data quality warnings for {symbol}: {warnings}")
            if not validate_kline_data(df, symbol):
                return pd.DataFrame()
            rows = df.to_dict("records")
            self._db.upsert_kline_rows(symbol, market, kline_type, adjust, rows)
            _history_cache.set(cache_key, df)
            return df

        return pd.DataFrame()

    async def _fetch_history_from_sources(self, symbol: str, market: str,
                                           kline_type: str, adjust: str,
                                           period: str) -> Optional[pd.DataFrame]:
        ranked = self._health.rank_sources(["eastmoney", "tencent", "akshare", "baostock"], "history")

        # 并发尝试前两个源，取先返回的有效结果
        if len(ranked) >= 2:
            top2 = ranked[:2]
            tasks = {}
            for src in top2:
                tasks[src] = asyncio.create_task(
                    self._fetch_from_single_source(src, symbol, market, kline_type, adjust, period)
                )
            done, pending = await asyncio.wait(
                tasks.values(),
                timeout=8,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending:
                p.cancel()

            results = {}
            for src, task in tasks.items():
                try:
                    if task.done() and not task.cancelled():
                        r = task.result()
                        if r is not None and not r.empty:
                            results[src] = r
                except Exception as e:
                    logger.debug(f"History source task failed: {e}")

            if len(results) >= 2:
                # 结果投票：若两源数据差异>5%，以成交量更大的为准
                dfs = list(results.values())
                srcs = list(results.keys())
                vol_a = dfs[0]["volume"].sum() if "volume" in dfs[0].columns else 0
                vol_b = dfs[1]["volume"].sum() if "volume" in dfs[1].columns else 0
                len_min = min(len(dfs[0]), len(dfs[1]))
                if len_min > 0:
                    close_a = dfs[0]["close"].iloc[-len_min:].values.astype(float)
                    close_b = dfs[1]["close"].iloc[-len_min:].values.astype(float)
                    diff_pct = np.mean(np.abs(close_a - close_b) / np.maximum(close_a, 1e-8))
                    if diff_pct > 0.05:
                        chosen_src = srcs[0] if vol_a >= vol_b else srcs[1]
                    else:
                        chosen_src = srcs[0]
                else:
                    chosen_src = srcs[0]
                return results[chosen_src]
            elif len(results) == 1:
                return list(results.values())[0]

        # 降级：顺序尝试剩余源
        remaining = ranked[2:] if len(ranked) >= 2 else ranked
        for source_name in remaining:
            result = await self._fetch_from_single_source(source_name, symbol, market, kline_type, adjust, period)
            if result is not None and not result.empty:
                return result

        return None

    async def _fetch_from_single_source(self, source_name: str, symbol: str, market: str,
                                         kline_type: str, adjust: str, period: str) -> Optional[pd.DataFrame]:
        start = time.time()
        try:
            if source_name == "eastmoney":
                ktype_map = {"daily": "101", "weekly": "102", "monthly": "103"}
                fqt_map = {"": 0, "qfq": 1, "hfq": 2}
                result = await self._circuit_breakers[source_name].call(
                    EastMoneySource.fetch_history_em,
                    symbol, market, ktype_map.get(kline_type, "101"), fqt_map.get(adjust, 1)
                )
            elif source_name == "tencent":
                count_map = {"1y": 300, "3y": 800, "5y": 1300, "all": 2500}
                count = count_map.get(period, 300)
                result = await self._circuit_breakers[source_name].call(
                    TencentSource.fetch_history, symbol, market, kline_type, adjust, count
                )
            elif source_name == "akshare":
                result = await self._circuit_breakers[source_name].call(
                    AKShareSource.fetch_history, symbol, market, kline_type, adjust, period
                )
            elif source_name == "baostock":
                result = await self._circuit_breakers[source_name].call(
                    BaoStockSource.fetch_history, symbol, market, kline_type, adjust
                )
            else:
                return None

            latency = time.time() - start
            if result is not None and not result.empty:
                self._health.record_request(source_name, "history", True, latency)
                try:
                    from core.metrics import metrics
                    metrics.increment("data_fetch_success", tags={"source": source_name, "type": "history"})
                    metrics.timer("data_fetch_latency", latency, tags={"source": source_name, "type": "history"})
                except Exception as e:
                    logger.debug(f"History metrics recording failed: {e}")
                return result
            self._health.record_request(source_name, "history", False, latency)
        except Exception as e:
            latency = time.time() - start
            self._health.record_request(source_name, "history", False, latency)
            logger.debug(f"Source {source_name} history error: {e}")
        return None

    async def get_fundamentals(self, symbol: str, market: Optional[str] = None) -> Optional[dict]:
        if market is None:
            market = MarketDetector.detect(symbol)
        if market == "A":
            em = await EastMoneySource.fetch_financial_report(symbol)
            if em and any(v for v in em.values() if v and v != 0):
                return em
            ak = await AKShareSource.fetch_fundamentals(symbol, market)
            if ak:
                return ak
            rt = await self.get_realtime(symbol, market)
            if rt:
                return {
                    "pe_ttm": rt.get("pe", 0),
                    "pb": rt.get("pb", 0),
                    "name": rt.get("name", ""),
                    "price": rt.get("price", 0),
                    "market_cap": rt.get("total_market_cap", 0),
                    "source": "realtime_fallback",
                }
        return await AKShareSource.fetch_fundamentals(symbol, market)

    async def fetch_north_bound_flow(self, date=None) -> Optional[dict]:
        return await EastMoneySource.fetch_north_bound_flow(date)

    async def fetch_limit_up_pool(self) -> list[dict]:
        return await EastMoneySource.fetch_limit_up_pool()

    async def fetch_dragon_tiger_list(self, date=None) -> list[dict]:
        return await EastMoneySource.fetch_dragon_tiger_list(date)

    def simulate_level2_from_daily(self, symbol: str, realtime_data: dict) -> dict:
        price = EastMoneySource._num((realtime_data or {}).get("price"))
        if price <= 0:
            return {"symbol": symbol, "bids": [], "asks": []}
        tick = 0.01 if price < 1000 else 0.1
        volume = max(EastMoneySource._num((realtime_data or {}).get("volume")), 1000)
        rng = np.random.default_rng(abs(hash(symbol)) % (2 ** 32))
        base_sizes = np.maximum(rng.normal(volume / 500, volume / 2000, size=5), 100)
        bids = []
        asks = []
        for i in range(5):
            bids.append({"price": round(price - tick * (i + 1), 2), "volume": round(float(base_sizes[i]), 0)})
            asks.append({"price": round(price + tick * (i + 1), 2), "volume": round(float(base_sizes[::-1][i]), 0)})
        return {"symbol": symbol, "bids": bids, "asks": asks, "timestamp": time.time()}

    async def get_market_overview(self) -> dict:
        cache_key = "market_overview"
        cached = _realtime_cache.get(cache_key)
        if cached is not None:
            return cached

        all_index_keys = {}
        for k in CN_INDICES:
            all_index_keys[f"idx_spot_{k}"] = k
        for k in HK_INDICES:
            all_index_keys[f"idx_spot_{k}"] = k
        for k in US_INDICES:
            all_index_keys[f"idx_spot_{k}"] = k

        all_cached = True
        cached_indices = {}
        for cache_k, idx_k in all_index_keys.items():
            val = _realtime_cache.get(cache_k)
            if val is None:
                all_cached = False
                break
            cached_indices[idx_k] = val

        if all_cached and cached_indices:
            result = self._assemble_market_overview(cached_indices, {}, {})
            return result

        async def fetch_cn_batch():
            codes = list(CN_INDICES.keys())
            url = f"{TencentSource.BASE_URL}{','.join(codes)}"
            text = await async_http_get(url)
            indices = {}
            if text:
                for line in text.strip().split(";"):
                    line = line.strip()
                    if not line or "~" not in line:
                        continue
                    parts = line.split("~")
                    if len(parts) >= 35:
                        try:
                            code = parts[2] if len(parts) > 2 else ""
                            name = parts[1]
                            price = float(parts[3]) if parts[3] else 0
                            change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else 0
                            change = float(parts[31]) if len(parts) > 31 and parts[31] else 0
                            key = None
                            for k, v in CN_INDICES.items():
                                if k.endswith(code) or code in k:
                                    key = k
                                    break
                            if key is None and len(parts) > 2:
                                for k in CN_INDICES:
                                    if code in k:
                                        key = k
                                        break
                            if key:
                                data = {"name": name, "price": price, "change_pct": change_pct, "change": change}
                                indices[key] = data
                                _realtime_cache.set(f"idx_spot_{key}", data)
                        except (ValueError, IndexError):
                            continue
            return indices

        async def fetch_hk_batch():
            async def fetch_one(key, name):
                url = f"{TencentSource.BASE_URL}hk{key}"
                text = await async_http_get(url)
                if text:
                    for line in text.strip().split(";"):
                        line = line.strip()
                        if not line or "~" not in line:
                            continue
                        parts = line.split("~")
                        if len(parts) >= 35:
                            try:
                                price = float(parts[3]) if parts[3] else 0
                                change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else 0
                                change = float(parts[31]) if len(parts) > 31 and parts[31] else 0
                                data = {"name": name, "price": price, "change_pct": change_pct, "change": change}
                                _realtime_cache.set(f"idx_spot_{key}", data)
                                return key, data
                            except (ValueError, IndexError):
                                pass
                return key, None

            tasks = [fetch_one(k, n) for k, n in HK_INDICES.items()]
            results = await asyncio.gather(*tasks)
            return {k: v for k, v in results if v is not None}

        async def fetch_us_batch():
            async def fetch_one(key, name):
                url = f"{TencentSource.BASE_URL}us{key.upper().replace('.', '')}"
                text = await async_http_get(url)
                if text:
                    for line in text.strip().split(";"):
                        line = line.strip()
                        if not line or "~" not in line:
                            continue
                        parts = line.split("~")
                        if len(parts) >= 35:
                            try:
                                price = float(parts[3]) if parts[3] else 0
                                change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else 0
                                change = float(parts[31]) if len(parts) > 31 and parts[31] else 0
                                data = {"name": name, "price": price, "change_pct": change_pct, "change": change}
                                _realtime_cache.set(f"idx_spot_{key}", data)
                                return key, data
                            except (ValueError, IndexError):
                                pass
                return key, None

            tasks = [fetch_one(k, n) for k, n in US_INDICES.items()]
            results = await asyncio.gather(*tasks)
            return {k: v for k, v in results if v is not None}

        cn_task = fetch_cn_batch()
        hk_task = fetch_hk_batch()
        us_task = fetch_us_batch()

        cn_indices, hk_indices, us_indices = await asyncio.gather(cn_task, hk_task, us_task)

        all_indices = {}
        all_indices.update(cn_indices)
        all_indices.update(hk_indices)
        all_indices.update(us_indices)

        northbound = {}
        temperature = {}

        async def fetch_northbound():
            try:
                url = "http://qt.gtimg.cn/q=sh007564,sh007565"
                text = await async_http_get(url)
                if text:
                    for line in text.strip().split(";"):
                        line = line.strip()
                        if not line or "~" not in line:
                            continue
                        parts = line.split("~")
                        if len(parts) >= 35:
                            try:
                                name = parts[1]
                                amount_val = float(parts[3]) if parts[3] else 0
                                northbound[name] = amount_val
                            except (ValueError, IndexError):
                                pass
            except Exception as e:
                logger.debug(f"Northbound flow fetch failed: {e}")

        async def fetch_temperature():
            try:
                up_count = 0
                down_count = 0
                for k, v in all_indices.items():
                    pct = v.get("change_pct", 0)
                    if pct > 0:
                        up_count += 1
                    elif pct < 0:
                        down_count += 1
                total = up_count + down_count
                if total > 0:
                    temperature["value"] = round(up_count / total * 100, 1)
                else:
                    temperature["value"] = 50.0
            except Exception as e:
                logger.debug(f"Temperature calculation failed: {e}")
                temperature["value"] = 50.0

        try:
            await asyncio.gather(
                asyncio.wait_for(fetch_northbound(), timeout=8),
                asyncio.wait_for(fetch_temperature(), timeout=4),
            )
        except asyncio.TimeoutError:
            logger.debug("Market overview northbound/temperature timeout")

        result = self._assemble_market_overview(all_indices, northbound, temperature)
        _realtime_cache.set(cache_key, result, ttl=10)
        return result

    def _assemble_market_overview(self, indices: dict, northbound: dict, temperature: dict) -> dict:
        cn = {}
        for k, v in indices.items():
            if k in CN_INDICES:
                cn[k] = v
        hk = {}
        for k, v in indices.items():
            if k in HK_INDICES:
                hk[k] = v
        us = {}
        for k, v in indices.items():
            if k in US_INDICES:
                us[k] = v

        return {
            "cn_indices": cn,
            "hk_indices": hk,
            "us_indices": us,
            "northbound": northbound,
            "temperature": temperature.get("value", 50.0),
            "timestamp": time.time(),
        }

    async def get_market_temperature(self) -> float:
        overview = await self.get_market_overview()
        return overview.get("temperature", 50.0)

    async def refresh_hot_symbols_cache(self) -> None:
        global _hot_symbols_cache
        try:
            if ak is None:
                return
            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
            if df is not None and not df.empty:
                df = df.sort_values("成交额", ascending=False) if "成交额" in df.columns else df
                symbols = df["代码"].tolist()[:50] if "代码" in df.columns else []
                async with _get_hot_symbols_lock():
                    _hot_symbols_cache = symbols
        except Exception as e:
            logger.debug(f"Refresh hot symbols error: {e}")

    async def preload_all(self) -> None:
        try:
            await self.get_market_overview()
        except Exception as e:
            logger.debug(f"Preload market overview error: {e}")

    async def prefetch_symbols(self, symbols: list[str], priority: str = "normal") -> None:
        """批量预热缓存，按优先级排序：watchlist > portfolio > hot"""
        if not symbols:
            return

        if priority == "watchlist":
            batch = symbols[:20]
        elif priority == "portfolio":
            batch = symbols[:15]
        else:
            batch = symbols[:10]

        tasks = []
        for symbol in batch:
            market = MarketDetector.detect(symbol)
            tasks.append(self.get_realtime(symbol, market))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        history_tasks = []
        for symbol in batch:
            market = MarketDetector.detect(symbol)
            if not self._cache_freshness_check(symbol, market):
                history_tasks.append(self.get_history(symbol, period="1y"))

        if history_tasks:
            await asyncio.gather(*history_tasks, return_exceptions=True)

    def _cache_freshness_check(self, symbol: str, market: str) -> bool:
        """检查缓存数据是否新鲜：交易时间内缓存数据日期非今天则需刷新"""
        try:
            cache_key = f"hist_{symbol}_{market}_daily__1y"
            cached = _history_cache.get(cache_key)
            if cached is None or not hasattr(cached, 'empty') or cached.empty:
                return False

            if "date" in cached.columns:
                last_date = str(cached["date"].iloc[-1])[:10]
                today = time.strftime("%Y-%m-%d")
                if last_date < today:
                    now = datetime.now()
                    weekday = now.weekday()
                    if weekday < 5:
                        hour_min = now.hour * 100 + now.minute
                        if 915 <= hour_min <= 1500:
                            return False
            return True
        except Exception:
            return False


_shared_fetcher: Optional[SmartDataFetcher] = None
_shared_fetcher_lock = threading.Lock()


def get_fetcher() -> SmartDataFetcher:
    global _shared_fetcher
    if _shared_fetcher is None:
        with _shared_fetcher_lock:
            if _shared_fetcher is None:
                _shared_fetcher = SmartDataFetcher()
    return _shared_fetcher
