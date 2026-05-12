from __future__ import annotations

NETWORK_TIMEOUT_SECONDS = 30

import asyncio
import contextlib
import json
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import aiohttp
import numpy as np
import pandas as pd

from core.database import SQLiteStore, ThreadSafeLRU, get_db
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

_aiohttp_session: aiohttp.ClientSession | None = None
_session_lock: asyncio.Lock | None = None


def _get_session_lock() -> asyncio.Lock:
    global _session_lock
    if _session_lock is None:
        _session_lock = asyncio.Lock()
    return _session_lock


async def get_aiohttp_session() -> aiohttp.ClientSession:
    global _aiohttp_session
    if _aiohttp_session is None or _aiohttp_session.closed:
        async with _get_session_lock():
            if _aiohttp_session is None or _aiohttp_session.closed:
                connector = aiohttp.TCPConnector(
                    limit=500,
                    limit_per_host=50,
                    ttl_dns_cache=1800,
                    use_dns_cache=True,
                    keepalive_timeout=60,
                    enable_cleanup_closed=True,
                    force_close=False,
                )
                timeout = aiohttp.ClientTimeout(total=12, connect=5)
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


@asynccontextmanager
async def session_manager():
    yield await get_aiohttp_session()
    await close_aiohttp_session()


async def async_http_get(url: str, headers: dict | None = None) -> str | None:
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
            logger.debug("HTTP GET %s returned status %s", url, resp)
    except TimeoutError:
        logger.debug("HTTP GET %s timeout", url)
    except (aiohttp.ClientError, OSError) as e:
        logger.debug("HTTP GET %s error: %s", url, e)
    return None


async def http_get_json(
    url: str,
    params: dict | None = None,
    referer: str = "https://data.eastmoney.com/",
    use_jsonp: bool = False,
) -> dict | None:
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
    except (aiohttp.ClientError, OSError) as e:
        logger.debug("http_get_json request error for %s: %s", url, e)
        return None
    if not text:
        return None
    if use_jsonp:
        m = re.search(r'jQuery_callback\((.+)\)\s*;?\s*$', text, re.DOTALL)
        if m:
            text = m.group(1)
        else:
            logger.debug("http_get_json JSONP callback not found in response from %s", url)
            return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.debug("http_get_json JSON decode error for %s: %s", url, e)
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

_realtime_cache = ThreadSafeLRU(maxsize=50000, ttl=8)
_history_cache = ThreadSafeLRU(maxsize=30000, ttl=1800)
_indicator_cache = ThreadSafeLRU(maxsize=6000, ttl=900)
_financial_cache = ThreadSafeLRU(maxsize=3000, ttl=10800)
_northbound_cache = ThreadSafeLRU(maxsize=1000, ttl=180)
_market_overview_cache = ThreadSafeLRU(maxsize=500, ttl=60)
_tick_cache = None
_hot_symbols_cache: list[str] = []
_hot_symbols_lock = threading.Lock()


def _get_hot_symbols() -> list[str]:
    with _hot_symbols_lock:
        return list(_hot_symbols_cache)


def _set_hot_symbols(symbols: list[str]) -> None:
    global _hot_symbols_cache
    with _hot_symbols_lock:
        _hot_symbols_cache = list(symbols)

_inflight_requests: dict[str, asyncio.Future] = {}
_inflight_lock = asyncio.Lock()
_INFLIGHT_MAX = 500


class RequestCoalescer:
    __slots__ = ("_window_ms", "_pending", "_lock")

    def __init__(self, window_ms: int = 50):
        self._window_ms = window_ms
        self._pending: dict[str, list[asyncio.Future]] = {}
        self._lock = asyncio.Lock()

    async def get_or_wait(self, key: str, fetch_fn) -> Any:
        async with self._lock:
            if key in self._pending:
                fut = asyncio.get_event_loop().create_future()
                self._pending[key].append(fut)
                return await fut
            self._pending[key] = []
        try:
            result = await fetch_fn()
            async with self._lock:
                waiters = self._pending.pop(key, [])
            for w in waiters:
                if not w.done():
                    w.set_result(result)
            return result
        except Exception as e:
            async with self._lock:
                waiters = self._pending.pop(key, [])
            for w in waiters:
                if not w.done():
                    w.set_exception(e)
            raise

_request_coalescer = RequestCoalescer(window_ms=50)

CACHE_TTL_TIERS = {
    "realtime": 18,
    "realtime_hot": 8,
    "history": 480,
    "indicator": 900,
    "financial": 10800,
    "northbound": 180,
    "limit_up": 45,
    "dragon_tiger": 600,
    "market_overview": 60,
}


class DataSourceHealthMonitor:
    """数据源健康度监控，基于内存滑动窗口统计"""

    def __init__(self, db: SQLiteStore | None = None):
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
                logger.debug("Health monitor write error: %s", e)

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
                    logger.debug("Source ranking error for %s: %s", name, e)
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
        if not re.match(r'^[0-9a-zA-Z]{1,10}$', clean):
            return ""
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
    async def fetch_realtime(symbol: str, market: str) -> dict | None:
        code = TencentSource._build_code(symbol, market)
        if not code:
            return None
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
                    "price": safe_float(parts[3], 0) if len(parts) > 3 else 0,
                    "last_close": safe_float(parts[4], 0) if len(parts) > 4 else 0,
                    "open": safe_float(parts[5], 0) if len(parts) > 5 else 0,
                    "volume": safe_float(parts[6], 0) if len(parts) > 6 else 0,
                    "amount": safe_float(parts[37], 0) if len(parts) > 37 else 0,
                    "high": safe_float(parts[33], 0) if len(parts) > 33 else 0,
                    "low": safe_float(parts[34], 0) if len(parts) > 34 else 0,
                    "change_pct": safe_float(parts[32], 0) if len(parts) > 32 else 0,
                    "change": safe_float(parts[31], 0) if len(parts) > 31 else 0,
                    "turnover_rate": safe_float(parts[38], 0) if len(parts) > 38 else 0,
                }
            except (ValueError, IndexError):
                continue
        return results

    @staticmethod
    async def fetch_history(symbol: str, market: str, kline_type: str = "daily",
                            adjust: str = "", count: int = 300) -> pd.DataFrame | None:
        code = TencentSource._build_code(symbol, market)
        if not code:
            return None
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
            logger.debug("Tencent history parse error: %s", e)
        return None

    @staticmethod
    def _parse_realtime(text: str, symbol: str, market: str) -> dict | None:
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
                    "price": safe_float(parts[3], 0),
                    "last_close": safe_float(parts[4], 0),
                    "open": safe_float(parts[5], 0),
                    "volume": safe_float(parts[6], 0),
                    "high": safe_float(parts[33], 0) if len(parts) > 33 else 0,
                    "low": safe_float(parts[34], 0) if len(parts) > 34 else 0,
                    "change_pct": safe_float(parts[32], 0) if len(parts) > 32 else 0,
                    "change": safe_float(parts[31], 0) if len(parts) > 31 else 0,
                    "amount": safe_float(parts[37], 0) if len(parts) > 37 else 0,
                    "turnover_rate": safe_float(parts[38], 0) if len(parts) > 38 else 0,
                    "timestamp": time.time(),
                }
            except (ValueError, IndexError):
                continue
        return None


class SinaSource:
    """新浪财经数据源"""

    @staticmethod
    async def fetch_realtime(symbol: str, market: str) -> dict | None:
        clean = re.sub(r"^(sh|sz|SH|SZ)", "", str(symbol)).strip()
        if market == "A":
            prefix = "sh" if clean.startswith("6") else "sz"
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
    def _parse_realtime(text: str, symbol: str, market: str) -> dict | None:
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
                    open_price = safe_float(fields[1], 0)
                    last_close = safe_float(fields[2], 0)
                    price = safe_float(fields[3], 0)
                    high = safe_float(fields[4], 0)
                    low = safe_float(fields[5], 0)
                    volume = safe_float(fields[8], 0)
                    amount = safe_float(fields[9], 0)
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
                    open_price = safe_float(fields[2], 0)
                    last_close = safe_float(fields[3], 0)
                    high = safe_float(fields[4], 0)
                    low = safe_float(fields[5], 0)
                    price = safe_float(fields[6], 0)
                    volume = safe_float(fields[12], 0)
                    amount = safe_float(fields[11], 0)
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
                    price = safe_float(fields[1], 0)
                    change_pct = safe_float(fields[2], 0)
                    change = safe_float(fields[3], 0)
                    open_price = safe_float(fields[4], 0)
                    high = safe_float(fields[5], 0)
                    low = safe_float(fields[6], 0)
                    volume = safe_float(fields[7], 0) if len(fields) > 7 else 0
                    amount = safe_float(fields[8], 0) if len(fields) > 8 else 0
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
                        "amount": amount,
                        "turnover_rate": 0,
                        "timestamp": time.time(),
                    }
        except (ValueError, IndexError) as e:
            logger.debug("Sina parse error for %s: %s", symbol, e)
        return None


def safe_float(value: Any, default: float = 0.0) -> float:
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
    async def fetch_realtime(symbol: str, market: str) -> dict | None:
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
            logger.debug("EastMoney realtime parse error: %s", e)
            return None

    @staticmethod
    async def fetch_history_em(symbol: str, market: str, ktype: str = "101",
                               fqt: int = 1) -> pd.DataFrame | None:
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
            logger.debug("EastMoney history parse error: %s", e)
        return None

    @staticmethod
    async def fetch_financial_report(symbol: str) -> dict | None:
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
            logger.debug("EastMoney financial parse error: %s", e)
            return None

    @staticmethod
    async def fetch_north_bound_flow(date=None) -> dict | None:
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
            logger.debug("akshare northbound fetch error: %s", e)
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
            logger.debug("EastMoney limit-up parse error: %s", e)
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
            logger.debug("EastMoney dragon-tiger parse error: %s", e)
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
            na_run = cleaned[col].isna().astype(int).groupby(cleaned[col].isna().cumsum()).sum().max()
            if pd.notna(na_run) and na_run >= 3:
                warnings.append(f"{col}_consecutive_nan:{int(na_run)}")
            cleaned[col] = cleaned[col].ffill()

        price_cols = [c for c in ["open", "high", "low", "close"] if c in cleaned.columns]
        if price_cols:
            non_positive = (cleaned[price_cols] <= 0).any(axis=1).sum()
            if non_positive:
                warnings.append(f"non_positive_price:{int(non_positive)}")
                cleaned.loc[(cleaned[price_cols] <= 0).any(axis=1), price_cols] = np.nan
                cleaned[price_cols] = cleaned[price_cols].ffill()

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


class HKStockSource:
    @staticmethod
    async def fetch_realtime(symbol: str) -> dict | None:
        code = re.sub(r"^(hk|HK)", "", str(symbol)).strip().zfill(5)
        if not re.match(r'^\d{5}$', code):
            return None
        secid = f"116.{code}"
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170"
        text = await async_http_get(url, headers={"Referer": "https://finance.eastmoney.com"})
        if not text:
            secid = f"128.{code}"
            url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170"
            text = await async_http_get(url, headers={"Referer": "https://finance.eastmoney.com"})
        if not text:
            return None
        try:
            payload = json.loads(text)
            data = payload.get("data") or {}
            if not data:
                return None
            price = safe_float(data.get("f43"), 0)
            last_close = safe_float(data.get("f60"), 0)
            return {
                "symbol": symbol, "market": "HK",
                "name": data.get("f58") or code,
                "price": price, "last_close": last_close,
                "open": safe_float(data.get("f46"), 0),
                "high": safe_float(data.get("f44"), 0),
                "low": safe_float(data.get("f45"), 0),
                "volume": safe_float(data.get("f47"), 0),
                "amount": safe_float(data.get("f48"), 0),
                "change": safe_float(data.get("f169"), 0),
                "change_pct": safe_float(data.get("f170"), 0),
                "timestamp": time.time(),
            }
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.debug("HKStockSource realtime parse error: %s", e)
        return None

    @staticmethod
    async def fetch_history(symbol: str, period: str = "1y", kline_type: str = "daily", adjust: str = "") -> pd.DataFrame | None:
        try:
            if ak is None:
                return None
            code = re.sub(r"^(hk|HK)", "", str(symbol)).strip().zfill(5)
            df = await asyncio.to_thread(ak.stock_hk_hist, symbol=code, period=kline_type, adjust=adjust or "")
            if df is not None and not df.empty:
                rename_map = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount"}
                df = df.rename(columns=rename_map)
                for col in ["open", "high", "low", "close", "volume", "amount"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                return df
        except Exception as e:
            logger.debug("HKStockSource history error: %s", e)
        return None


class USStockSource:
    @staticmethod
    async def fetch_realtime(symbol: str) -> dict | None:
        clean = re.sub(r"^(us|US)", "", str(symbol)).strip().upper()
        url = f"http://hq.sinajs.cn/list=gb_{clean.lower()}"
        headers = {"Referer": "http://finance.sina.com.cn"}
        text = await async_http_get(url, headers=headers)
        if text:
            result = SinaSource._parse_realtime(text, clean, "US")
            if result:
                return result
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid=105.{clean}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170"
        text = await async_http_get(url, headers={"Referer": "https://finance.eastmoney.com"})
        if not text:
            return None
        try:
            payload = json.loads(text)
            data = payload.get("data") or {}
            if not data:
                return None
            price = safe_float(data.get("f43"), 0)
            last_close = safe_float(data.get("f60"), 0)
            return {
                "symbol": clean, "market": "US",
                "name": data.get("f58") or clean,
                "price": price, "last_close": last_close,
                "open": safe_float(data.get("f46"), 0),
                "high": safe_float(data.get("f44"), 0),
                "low": safe_float(data.get("f45"), 0),
                "volume": safe_float(data.get("f47"), 0),
                "amount": safe_float(data.get("f48"), 0),
                "change": safe_float(data.get("f169"), 0),
                "change_pct": safe_float(data.get("f170"), 0),
                "timestamp": time.time(),
            }
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.debug("USStockSource realtime parse error: %s", e)
        return None

    @staticmethod
    async def fetch_history(symbol: str, period: str = "1y", kline_type: str = "daily", adjust: str = "") -> pd.DataFrame | None:
        try:
            if ak is None:
                return None
            clean = re.sub(r"^(us|US)", "", str(symbol)).strip().upper()
            df = await asyncio.to_thread(ak.stock_us_hist, symbol=clean, period=kline_type, adjust=adjust or "")
            if df is not None and not df.empty:
                rename_map = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount"}
                df = df.rename(columns=rename_map)
                for col in ["open", "high", "low", "close", "volume", "amount"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                return df
        except Exception as e:
            logger.debug("USStockSource history error: %s", e)
        return None


class DataNormalizer:
    REQUIRED_FIELDS = {"date", "open", "high", "low", "close", "volume"}

    @staticmethod
    def normalize_kline(df: pd.DataFrame, source: str = "") -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        result = df.copy()
        cn_to_en = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount", "换手率": "turnover_rate"}
        result = result.rename(columns=cn_to_en)
        for col in DataNormalizer.REQUIRED_FIELDS - {"date"}:
            if col in result.columns:
                result[col] = pd.to_numeric(result[col], errors="coerce")
        if "date" in result.columns:
            result["date"] = pd.to_datetime(result["date"], errors="coerce")
        return result

    @staticmethod
    def validate_ohlcv(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        warnings = []
        if df is None or df.empty:
            return pd.DataFrame(), ["empty_dataframe"]
        cleaned = df.copy()
        if {"high", "low", "close"}.issubset(cleaned.columns):
            bad_high = cleaned["high"] < cleaned["close"]
            bad_low = cleaned["low"] > cleaned["close"]
            if bad_high.any():
                cleaned.loc[bad_high, "high"] = cleaned.loc[bad_high, "close"]
                warnings.append(f"high_lt_close_fixed:{int(bad_high.sum())}")
            if bad_low.any():
                cleaned.loc[bad_low, "low"] = cleaned.loc[bad_low, "close"]
                warnings.append(f"low_gt_close_fixed:{int(bad_low.sum())}")
        if "volume" in cleaned.columns:
            neg_vol = (cleaned["volume"] < 0).sum()
            if neg_vol:
                cleaned.loc[cleaned["volume"] < 0, "volume"] = 0
                warnings.append(f"negative_volume_fixed:{int(neg_vol)}")
        if "close" in cleaned.columns:
            pct = cleaned["close"].pct_change()
            suspicious = pct.abs() > 0.15
            if suspicious.any():
                warnings.append(f"suspicious_price_move:{int(suspicious.sum())}")
        return cleaned, warnings


class CircuitBreakerError(Exception):
    """Circuit breaker exception raised when circuit is open"""
    pass


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
        self._half_open_sem = asyncio.Semaphore(half_open_calls)

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

    async def _acquire_permission(self, func_name: str) -> bool:
        async with self._lock:
            if self.state == "CLOSED":
                return True
            if self.state == "OPEN":
                if time.monotonic() - self.last_failure_time > self.timeout:
                    self.state = "HALF_OPEN"
                    self.half_open_calls = 0
                    return True
                return False
            if self.state == "HALF_OPEN":
                return True
            return False

    async def _record_success(self, result) -> None:
        async with self._lock:
            if self.state == "HALF_OPEN":
                self.half_open_calls += 1
                if self._is_valid_result(result):
                    if self.half_open_calls >= self.half_open_max:
                        self.state = "CLOSED"
                        self.failure_count = 0
                else:
                    self.failure_count += 1
                    self.last_failure_time = time.monotonic()
                    if self.failure_count >= self.failure_threshold:
                        self.state = "OPEN"
            else:
                if self._is_valid_result(result):
                    self.failure_count = 0
                else:
                    self.failure_count += 1
                    self.last_failure_time = time.monotonic()
                    if self.failure_count >= self.failure_threshold:
                        self.state = "OPEN"

    async def _record_failure(self) -> None:
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.monotonic()
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"

    async def call(self, func, *args, **kwargs):
        func_name = getattr(func, '__name__', 'source')
        if not await self._acquire_permission(func_name):
            raise CircuitBreakerError(f"Circuit breaker OPEN for {func_name}")
        is_half_open = self.state == "HALF_OPEN"
        try:
            if is_half_open:
                async with self._half_open_sem:
                    result = await func(*args, **kwargs)
            else:
                result = await func(*args, **kwargs)
            await self._record_success(result)
            return result
        except Exception as e:
            logger.debug("CircuitBreaker call error: %s", e)
            await self._record_failure()
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
    now = datetime.now()
    is_market_hours = 9 <= now.hour < 16
    date_ok = (ts_date == now.date()) if is_market_hours else (ts_date >= now.date() - timedelta(days=3))
    ok = price > 0 and -20 <= pct <= 20 and volume >= 0 and date_ok
    if not ok:
        logger.debug("Invalid realtime data for %s: %s", symbol, data)
    return ok


def validate_kline_data(df: pd.DataFrame, symbol: str) -> bool:
    if df is None or len(df) < 10 or "date" not in df.columns:
        logger.debug("Invalid kline data for %s: insufficient rows/date", symbol)
        return False
    data = df.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    price_cols = [c for c in ["open", "high", "low", "close"] if c in data.columns]
    ok = data["date"].notna().all() and data["date"].is_monotonic_increasing
    if price_cols:
        ok = ok and (data[price_cols] > 0).all().all()
    if not ok:
        logger.debug("Invalid kline data for %s", symbol)
    return bool(ok)


class AKShareSource:
    """AKShare数据源（同步库，保留to_thread）"""

    @staticmethod
    async def fetch_history(symbol: str, market: str, kline_type: str = "daily",
                            adjust: str = "", period: str = "1y") -> pd.DataFrame | None:
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(AKShareSource._sync_fetch_history, symbol, market, kline_type, adjust, period),
                timeout=NETWORK_TIMEOUT_SECONDS,
            )
            return df
        except TimeoutError:
            logger.warning("AKShare fetch_history timed out after %ss: %s", NETWORK_TIMEOUT_SECONDS, symbol)
            return None
        except Exception as e:
            logger.debug("AKShare fetch_history error: %s", e)
            return None

    @staticmethod
    def _sync_fetch_history(symbol: str, market: str, kline_type: str = "daily",
                            adjust: str = "", period: str = "1y") -> pd.DataFrame | None:
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
            logger.debug("AKShare sync fetch error: %s", e)
        return None

    @staticmethod
    async def fetch_fundamentals(symbol: str, market: str) -> dict | None:
        try:
            result = await asyncio.to_thread(AKShareSource._sync_fetch_fundamentals, symbol, market)
            return result
        except Exception as e:
            logger.debug("AKShare fundamentals error: %s", e)
            return None

    @staticmethod
    def _sync_fetch_fundamentals(symbol: str, market: str) -> dict | None:
        try:
            if ak is None:
                return None
            if market != "A":
                return None
            df = ak.stock_individual_info_em(symbol=symbol)
            if df is None or df.empty:
                return None
            result = {}
            for row in df.to_dict("records"):
                vals = list(row.values())
                key = str(vals[0]).strip()
                val = str(vals[1]).strip() if len(vals) > 1 else ""
                result[key] = val
            return result
        except Exception as e:
            logger.debug("AKShare fundamentals sync error: %s", e)
        return None


class BaoStockSource:
    """BaoStock数据源（同步库，保留to_thread）"""

    _baostock_lock = threading.Lock()

    @staticmethod
    async def fetch_history(symbol: str, market: str, kline_type: str = "daily",
                            adjust: str = "", start_date: str = "",
                            end_date: str = "") -> pd.DataFrame | None:
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(BaoStockSource._sync_fetch_history, symbol, market, kline_type, adjust, start_date, end_date),
                timeout=NETWORK_TIMEOUT_SECONDS,
            )
            return df
        except TimeoutError:
            logger.warning("BaoStock fetch_history timed out after %ss: %s", NETWORK_TIMEOUT_SECONDS, symbol)
            return None
        except Exception as e:
            logger.debug("BaoStock fetch error: %s", e)
            return None

    @staticmethod
    def _sync_fetch_history(symbol: str, market: str, kline_type: str = "daily",
                            adjust: str = "", start_date: str = "",
                            end_date: str = "") -> pd.DataFrame | None:
        try:
            if bs is None:
                return None
            import io as _io
            with BaoStockSource._baostock_lock:
                with contextlib.redirect_stdout(_io.StringIO()), contextlib.redirect_stderr(_io.StringIO()):
                    lg = bs.login()
                if lg.error_code != "0":
                    return None
                try:
                    if not end_date:
                        end_date = datetime.now().strftime("%Y-%m-%d")
                    if not start_date:
                        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

                    if market != "A":
                        with contextlib.redirect_stdout(_io.StringIO()), contextlib.redirect_stderr(_io.StringIO()):
                            bs.logout()
                        return None

                    bs_code = f"sh.{symbol}" if symbol.startswith("6") else f"sz.{symbol}"

                    freq_map = {"daily": "d", "weekly": "w", "monthly": "m"}
                    freq = freq_map.get(kline_type, "d")
                    adjust_flag = "2" if adjust == "qfq" else "1" if adjust == "hfq" else "3"

                    with contextlib.redirect_stdout(_io.StringIO()), contextlib.redirect_stderr(_io.StringIO()):
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

                    if not rows:
                        return None

                    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount", "turnover_rate"])
                    for col in ["open", "high", "low", "close", "volume", "amount"]:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors="coerce")
                    return df
                finally:
                    with contextlib.redirect_stdout(_io.StringIO()), contextlib.redirect_stderr(_io.StringIO()):
                        bs.logout()
        except Exception as e:
            logger.debug("BaoStock sync error: %s", e)
            import io as _io2
            with contextlib.redirect_stdout(_io2.StringIO()), contextlib.redirect_stderr(_io2.StringIO()):
                try:
                    with BaoStockSource._baostock_lock:
                        bs.logout()
                except Exception as e2:
                    logger.debug("BaoStock logout failed: %s", e2)
            return None


class SmartDataFetcher:
    """智能数据获取器，自动选择最优数据源"""

    def __init__(self, db: SQLiteStore | None = None):
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

    async def get_realtime(self, symbol: str, market: str | None = None) -> dict | None:
        if market is None:
            market = MarketDetector.detect(symbol)

        clean_symbol = re.sub(r"^(sh|sz|SH|SZ)", "", str(symbol)).strip()
        cache_key = f"rt_{clean_symbol}_{market}"
        cached = _realtime_cache.get(cache_key)
        if cached is not None:
            return cached

        inflight_key = f"rt:{cache_key}"
        should_fetch_direct = False
        async with _inflight_lock:
            if inflight_key in _inflight_requests:
                existing_fut = _inflight_requests[inflight_key]
            else:
                existing_fut = None
            if existing_fut is None and len(_inflight_requests) >= _INFLIGHT_MAX:
                should_fetch_direct = True
            elif existing_fut is None:
                loop = asyncio.get_running_loop()
                fut = loop.create_future()
                _inflight_requests[inflight_key] = fut

        if existing_fut is not None:
            return await existing_fut

        if should_fetch_direct:
            result = await self._fetch_realtime_from_sources(symbol, market, cache_key)
            if result and validate_realtime_data(result, symbol):
                _realtime_cache.set(cache_key, result)
            return result

        try:
            result = await self._fetch_realtime_from_sources(symbol, market, cache_key)
            if result and validate_realtime_data(result, symbol):
                _realtime_cache.set(cache_key, result)
            if not fut.done():
                fut.set_result(result)
            return result
        except Exception as e:
            logger.debug("Realtime fetch failed for %s", symbol, exc_info=True)
            if not fut.done():
                fut.set_exception(e)
            return None
        finally:
            async with _inflight_lock:
                _inflight_requests.pop(inflight_key, None)

    async def _fetch_realtime_from_sources(self, symbol: str, market: str, cache_key: str) -> dict | None:
        ranked = self._health.rank_sources(["eastmoney", "tencent", "sina"], "realtime")

        for source_name in ranked:
            source = self._sources.get(source_name)
            if source is None:
                continue
            start = time.monotonic()
            try:
                breaker = self._circuit_breakers.get(source_name)
                if breaker:
                    result = await breaker.call(source.fetch_realtime, symbol, market)
                else:
                    result = await source.fetch_realtime(symbol, market)
                latency = time.monotonic() - start
                if result and validate_realtime_data(result, symbol):
                    self._health.record_request(source_name, "realtime", True, latency)
                    _realtime_cache.set(cache_key, result)
                    try:
                        from core.metrics import metrics
                        metrics.increment("data_fetch_success", tags={"source": source_name, "type": "realtime"})
                        metrics.timer("data_fetch_latency", latency, tags={"source": source_name, "type": "realtime"})
                    except Exception as e:
                        logger.debug("Metrics recording failed: %s", e)
                    return result
                self._health.record_request(source_name, "realtime", False, latency)
            except Exception as e:
                latency = time.monotonic() - start
                self._health.record_request(source_name, "realtime", False, latency)
                logger.debug("Source %s realtime error: %s", source_name, e)

        logger.warning("All sources failed for realtime %s (market=%s)", symbol, market)
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
                            logger.debug("Batch realtime fetch failed for %s: %s", s, e)

        if other_symbols:
            tasks = [self.get_realtime(s, m) for s, m in other_symbols]
            other_results = await asyncio.gather(*tasks, return_exceptions=True)
            for (s, _m), result in zip(other_symbols, other_results, strict=False):
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

        inflight_key = f"hist:{cache_key}"
        should_fetch_direct = False
        async with _inflight_lock:
            if inflight_key in _inflight_requests:
                existing_fut = _inflight_requests[inflight_key]
            else:
                existing_fut = None
            if existing_fut is None and len(_inflight_requests) >= _INFLIGHT_MAX:
                should_fetch_direct = True
            elif existing_fut is None:
                loop = asyncio.get_running_loop()
                fut = loop.create_future()
                _inflight_requests[inflight_key] = fut

        if existing_fut is not None:
            return await existing_fut

        if should_fetch_direct:
            df = await self._fetch_history_from_sources(clean_symbol, market, kline_type, adjust, period)
            if df is not None and not df.empty:
                _history_cache.set(cache_key, df)
            return df if df is not None else pd.DataFrame()

        try:
            df = await self._fetch_history_from_sources(clean_symbol, market, kline_type, adjust, period)
            if df is not None and not df.empty:
                df, warnings = DataQualityChecker.check_kline(df)
                if warnings:
                    logger.debug("Data quality warnings for %s: %s", symbol, warnings)
                if not validate_kline_data(df, symbol):
                    result = pd.DataFrame()
                    if not fut.done():
                        fut.set_result(result)
                    return result
                rows = df.to_dict("records")
                self._db.upsert_kline_rows(symbol, market, kline_type, adjust, rows)
                _history_cache.set(cache_key, df)
                if not fut.done():
                    fut.set_result(df)
                return df
            result = pd.DataFrame()
            if not fut.done():
                fut.set_result(result)
            return result
        except Exception as e:
            logger.debug("History fetch failed for %s", symbol, exc_info=True)
            if not fut.done():
                fut.set_exception(e)
            return pd.DataFrame()
        finally:
            async with _inflight_lock:
                _inflight_requests.pop(inflight_key, None)

    async def get_history_batch(self, symbols: list[str], period: str = "1y",
                                kline_type: str = "daily", adjust: str = "qfq",
                                max_concurrent: int = 16) -> dict[str, pd.DataFrame]:
        if not symbols:
            return {}
        sem = asyncio.Semaphore(max_concurrent)

        async def _fetch_one(sym):
            async with sem:
                try:
                    return sym, await self.get_history(sym, period, kline_type, adjust)
                except Exception as e:
                    logger.debug("Batch history fetch failed for %s: %s", sym, e)
                    return sym, pd.DataFrame()

        tasks = [_fetch_one(s) for s in symbols[:50]]
        results = await asyncio.gather(*tasks)
        return {sym: df for sym, df in results if not df.empty}

    async def _fetch_history_from_sources(self, symbol: str, market: str,
                                           kline_type: str, adjust: str,
                                           period: str) -> pd.DataFrame | None:
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
                    logger.debug("History source task failed: %s", e)

            if len(results) >= 2:
                dfs = list(results.values())
                srcs = list(results.keys())
                len_min = min(len(dfs[0]), len(dfs[1]))
                if len_min > 0:
                    close_a = pd.to_numeric(dfs[0]["close"].iloc[-len_min:], errors="coerce").dropna().values.astype(float)
                    close_b = pd.to_numeric(dfs[1]["close"].iloc[-len_min:], errors="coerce").dropna().values.astype(float)
                    diff_pct = np.mean(np.abs(close_a - close_b) / np.maximum(close_a, 1e-8))
                    if diff_pct > 0.05:
                        price_cols = [c for c in ["open", "high", "low", "close"] if c in dfs[0].columns and c in dfs[1].columns]
                        score_a = len(dfs[0]) - dfs[0][price_cols].isna().sum().sum() if price_cols else len(dfs[0])
                        score_b = len(dfs[1]) - dfs[1][price_cols].isna().sum().sum() if price_cols else len(dfs[1])
                        chosen_src = srcs[0] if score_a >= score_b else srcs[1]
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
                                         kline_type: str, adjust: str, period: str) -> pd.DataFrame | None:
        start = time.monotonic()
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
                logger.warning("Unknown data source: %s", source_name)
                return None

            latency = time.monotonic() - start
            if result is not None and not result.empty:
                self._health.record_request(source_name, "history", True, latency)
                try:
                    from core.metrics import metrics
                    metrics.increment("data_fetch_success", tags={"source": source_name, "type": "history"})
                    metrics.timer("data_fetch_latency", latency, tags={"source": source_name, "type": "history"})
                except Exception as e:
                    logger.debug("History metrics recording failed: %s", e)
                return result
            self._health.record_request(source_name, "history", False, latency)
        except Exception as e:
            latency = time.monotonic() - start
            self._health.record_request(source_name, "history", False, latency)
            logger.debug("Source %s history error: %s", source_name, e)
        return None

    async def get_fundamentals(self, symbol: str, market: str | None = None) -> dict | None:
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

    async def fetch_north_bound_flow(self, date=None) -> dict | None:
        cache_key = f"north_bound:{date or 'latest'}"
        cached = _realtime_cache.get(cache_key)
        if cached is not None:
            return cached
        result = await EastMoneySource.fetch_north_bound_flow(date)
        if result:
            _realtime_cache.set(cache_key, result, ttl=900)
        return result

    async def fetch_limit_up_pool(self) -> list[dict]:
        cache_key = "limit_up_pool"
        cached = _realtime_cache.get(cache_key)
        if cached is not None:
            return cached
        result = await EastMoneySource.fetch_limit_up_pool()
        _realtime_cache.set(cache_key, result, ttl=60)
        return result

    async def fetch_dragon_tiger_list(self, date=None) -> list[dict]:
        cache_key = f"dragon_tiger:{date or 'latest'}"
        cached = _realtime_cache.get(cache_key)
        if cached is not None:
            return cached
        result = await EastMoneySource.fetch_dragon_tiger_list(date)
        _realtime_cache.set(cache_key, result, ttl=900)
        return result

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
                            price = safe_float(parts[3], 0)
                            change_pct = safe_float(parts[32], 0) if len(parts) > 32 else 0
                            change = safe_float(parts[31], 0) if len(parts) > 31 else 0
                            key = None
                            for k, _v in CN_INDICES.items():
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
                                price = safe_float(parts[3], 0)
                                change_pct = safe_float(parts[32], 0) if len(parts) > 32 else 0
                                change = safe_float(parts[31], 0) if len(parts) > 31 else 0
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
                                price = safe_float(parts[3], 0)
                                change_pct = safe_float(parts[32], 0) if len(parts) > 32 else 0
                                change = safe_float(parts[31], 0) if len(parts) > 31 else 0
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
                                amount_val = safe_float(parts[3], 0)
                                northbound[name] = amount_val
                            except (ValueError, IndexError):
                                pass
            except Exception as e:
                logger.debug("Northbound flow fetch failed: %s", e)

        async def fetch_temperature():
            try:
                up_count = 0
                down_count = 0
                for _k, v in all_indices.items():
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
                logger.debug("Temperature calculation failed: %s", e)
                temperature["value"] = 50.0

        try:
            await asyncio.gather(
                asyncio.wait_for(fetch_northbound(), timeout=8),
                asyncio.wait_for(fetch_temperature(), timeout=4),
            )
        except TimeoutError:
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

    async def get_batch_realtime_optimized(self, symbols: list[str]) -> dict[str, dict]:
        if not symbols:
            return {}
        from core.async_utils import rt_cache, CACHE_TTL
        cache_key = f"batch_rt_{','.join(sorted(symbols[:20]))}"
        cached = await rt_cache.get(cache_key)
        if cached is not None:
            return {s: cached[s] for s in symbols if s in cached}
        try:
            if ak is None:
                return await self.get_realtime_batch(symbols)
            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
            if df is None or df.empty:
                return await self.get_realtime_batch(symbols)
            target_codes = set()
            for s in symbols:
                clean = re.sub(r"^(sh|sz|SH|SZ)", "", str(s)).strip()
                target_codes.add(clean)
            if "代码" in df.columns:
                filtered = df[df["代码"].isin(target_codes)]
            else:
                return await self.get_realtime_batch(symbols)
            result = {}
            for _, row in filtered.iterrows():
                code = str(row.get("代码", ""))
                symbol = code
                for s in symbols:
                    clean = re.sub(r"^(sh|sz|SH|SZ)", "", str(s)).strip()
                    if clean == code:
                        symbol = s
                        break
                result[symbol] = {
                    "symbol": symbol,
                    "market": "A",
                    "name": str(row.get("名称", "")),
                    "price": safe_float(row.get("最新价"), 0),
                    "change_pct": safe_float(row.get("涨跌幅"), 0),
                    "change": safe_float(row.get("涨跌额"), 0),
                    "volume": safe_float(row.get("成交量"), 0),
                    "amount": safe_float(row.get("成交额"), 0),
                    "high": safe_float(row.get("最高"), 0),
                    "low": safe_float(row.get("最低"), 0),
                    "open": safe_float(row.get("今开"), 0),
                    "last_close": safe_float(row.get("昨收"), 0),
                    "turnover_rate": safe_float(row.get("换手率"), 0),
                    "timestamp": time.time(),
                }
            await rt_cache.set(cache_key, result, CACHE_TTL["realtime_batch"])
            return result
        except Exception as e:
            logger.debug("Batch realtime optimized error: %s", e)
            return await self.get_realtime_batch(symbols)

    async def get_sector_heatmap(self) -> dict:
        from core.async_utils import sector_cache, CACHE_TTL
        cache_key = "sector_heatmap"
        cached = await sector_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            if ak is None:
                return {"items": [], "timestamp": time.time()}
            df = await asyncio.to_thread(ak.stock_board_industry_name_em)
            if df is None or df.empty:
                return {"items": [], "timestamp": time.time()}
            items = []
            for _, row in df.head(30).iterrows():
                items.append({
                    "name": str(row.get("板块名称", "")),
                    "change_pct": safe_float(row.get("涨跌幅"), 0),
                    "amount": safe_float(row.get("成交额"), 0),
                    "leading_stock": str(row.get("领涨股票", "")),
                    "leading_stock_change_pct": safe_float(row.get("领涨股票涨跌幅"), 0),
                })
            result = {"items": items, "timestamp": time.time()}
            await sector_cache.set(cache_key, result, CACHE_TTL["sector_heatmap"])
            return result
        except Exception as e:
            logger.debug("Sector heatmap error: %s", e)
            return {"items": [], "timestamp": time.time()}

    async def get_market_breadth(self) -> dict:
        from core.async_utils import breadth_cache, CACHE_TTL
        cache_key = "market_breadth"
        cached = await breadth_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            if ak is None:
                return {"advance_count": 0, "decline_count": 0, "flat_count": 0, "total_amount": 0, "up": 0, "down": 0, "flat": 0, "timestamp": time.time()}
            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
            if df is None or df.empty:
                return {"advance_count": 0, "decline_count": 0, "flat_count": 0, "total_amount": 0, "up": 0, "down": 0, "flat": 0, "timestamp": time.time()}
            if "涨跌幅" in df.columns:
                pct = pd.to_numeric(df["涨跌幅"], errors="coerce").fillna(0)
                up = int((pct > 0).sum())
                down = int((pct < 0).sum())
                flat = int((pct == 0).sum())
            else:
                up = down = flat = 0
            result = {
                "advance_count": up,
                "decline_count": down,
                "flat_count": flat,
                "total_amount": 0,
                "up": up,
                "down": down,
                "flat": flat,
                "total": up + down + flat,
                "up_ratio": round(up / max(up + down + flat, 1), 4),
                "timestamp": time.time(),
            }
            await breadth_cache.set(cache_key, result, CACHE_TTL["market_breadth"])
            return result
        except Exception as e:
            logger.debug("Market breadth error: %s", e)
            return {"advance_count": 0, "decline_count": 0, "flat_count": 0, "total_amount": 0, "up": 0, "down": 0, "flat": 0, "timestamp": time.time()}

    async def refresh_hot_symbols_cache(self) -> None:
        try:
            if ak is None:
                return
            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
            if df is not None and not df.empty:
                df = df.sort_values("成交额", ascending=False) if "成交额" in df.columns else df
                symbols = df["代码"].tolist()[:50] if "代码" in df.columns else []
                _set_hot_symbols(symbols)
        except Exception as e:
            logger.debug("Refresh hot symbols error: %s", e)

    async def preload_all(self) -> None:
        try:
            await self.get_market_overview()
        except Exception as e:
            logger.debug("Preload market overview error: %s", e)
        try:
            await self.refresh_hot_symbols_cache()
        except Exception as e:
            logger.debug("Preload hot symbols error: %s", e)
        try:
            hot = _get_hot_symbols()[:10]
            if hot:
                await self.prefetch_symbols(hot, priority="watchlist")
        except Exception as e:
            logger.debug("Preload hot prefetch error: %s", e)

    async def prefetch_symbols(self, symbols: list[str], priority: str = "normal") -> None:
        """批量预热缓存，按优先级排序：watchlist > portfolio > hot"""
        if not symbols:
            return

        if priority == "watchlist":
            batch = symbols[:30]
        elif priority == "portfolio":
            batch = symbols[:20]
        else:
            batch = symbols[:15]

        tasks = []
        for symbol in batch:
            market = MarketDetector.detect(symbol)
            tasks.append(self.get_realtime(symbol, market))

        await asyncio.gather(*tasks, return_exceptions=True)

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
        except Exception as e:
            logger.debug("Cache validity check failed: %s", e)
            return False


_shared_fetcher: SmartDataFetcher | None = None
_shared_fetcher_lock = threading.Lock()


def get_fetcher() -> SmartDataFetcher:
    global _shared_fetcher
    if _shared_fetcher is None:
        with _shared_fetcher_lock:
            if _shared_fetcher is None:
                _shared_fetcher = SmartDataFetcher()
    return _shared_fetcher


class DataSourceRouter:
    def __init__(self):
        self._health_scores: dict[str, float] = {}
        self._latency_p95: dict[str, float] = {}
        self._error_rates: dict[str, float] = {}
        self._request_counts: dict[str, int] = {}
        self._error_counts: dict[str, int] = {}
        self._total_latency: dict[str, float] = {}

    def _source_key(self, source_name: str, market: str, data_type: str) -> str:
        return f"{source_name}:{market}:{data_type}"

    def record_success(self, source_name: str, market: str, data_type: str, latency_ms: float) -> None:
        key = self._source_key(source_name, market, data_type)
        self._request_counts[key] = self._request_counts.get(key, 0) + 1
        self._total_latency[key] = self._total_latency.get(key, 0) + latency_ms
        self._health_scores[key] = min(100.0, self._health_scores.get(key, 50.0) + 2)
        errors = self._error_counts.get(key, 0)
        total = self._request_counts.get(key, 1)
        self._error_rates[key] = errors / total

    def record_failure(self, source_name: str, market: str, data_type: str) -> None:
        key = self._source_key(source_name, market, data_type)
        self._request_counts[key] = self._request_counts.get(key, 0) + 1
        self._error_counts[key] = self._error_counts.get(key, 0) + 1
        self._health_scores[key] = max(0.0, self._health_scores.get(key, 50.0) - 10)
        errors = self._error_counts.get(key, 0)
        total = self._request_counts.get(key, 1)
        self._error_rates[key] = errors / total

    def get_source_ranking(self, market: str, data_type: str) -> list[str]:
        priority_map = {
            ("A", "realtime"): ["eastmoney_push2", "tencent", "sina", "juhe"],
            ("A", "history"): ["eastmoney_kline", "akshare", "baostock", "tushare"],
            ("HK", "realtime"): ["eastmoney_hk", "akshare_hk", "sina_hk"],
            ("HK", "history"): ["akshare_hk", "eastmoney_hk", "sina_hk"],
            ("US", "realtime"): ["sina_us", "yahoo", "alpha_vantage"],
            ("US", "history"): ["yahoo", "akshare_us", "alpha_vantage"],
        }
        sources = priority_map.get((market, data_type), ["eastmoney_push2", "akshare", "sina"])
        def sort_key(s: str) -> float:
            key = self._source_key(s, market, data_type)
            return -self._health_scores.get(key, 50.0)
        return sorted(sources, key=sort_key)

    async def fetch_with_fallback(
        self,
        symbol: str,
        market: str,
        data_type: str,
        timeout: float = 5.0,
    ) -> dict | pd.DataFrame | None:
        ranking = self.get_source_ranking(market, data_type)
        for source_name in ranking:
            start = time.monotonic()
            try:
                result = await self._fetch_from_source(source_name, symbol, market, data_type, timeout)
                latency_ms = (time.monotonic() - start) * 1000
                self.record_success(source_name, market, data_type, latency_ms)
                return result
            except Exception as e:
                logger.debug("Fetch from source %s failed: %s", source_name, e)
                self.record_failure(source_name, market, data_type)
        return None

    async def _fetch_from_source(
        self, source_name: str, symbol: str, market: str, data_type: str, timeout: float,
    ) -> dict | pd.DataFrame | None:
        fetcher = get_fetcher()
        if data_type == "realtime":
            return await fetcher.get_realtime(symbol)
        elif data_type == "history":
            return await fetcher.get_history(symbol, period="1y", kline_type="daily", adjust="qfq")
        return None

    def get_health_report(self) -> dict[str, dict]:
        report = {}
        for key, score in self._health_scores.items():
            parts = key.split(":")
            report[key] = {
                "source": parts[0] if len(parts) > 0 else "",
                "market": parts[1] if len(parts) > 1 else "",
                "data_type": parts[2] if len(parts) > 2 else "",
                "health_score": round(score, 1),
                "error_rate": round(self._error_rates.get(key, 0), 4),
                "request_count": self._request_counts.get(key, 0),
            }
        return report


_data_source_router: DataSourceRouter | None = None


def get_data_source_router() -> DataSourceRouter:
    global _data_source_router
    if _data_source_router is None:
        _data_source_router = DataSourceRouter()
    return _data_source_router
