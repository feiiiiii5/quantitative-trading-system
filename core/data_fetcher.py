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
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import aiohttp
import pandas as pd

from core.database import SQLiteStore, get_db, ThreadSafeLRU
from core.market_detector import MarketDetector

logger = logging.getLogger(__name__)

_aiohttp_session: Optional[aiohttp.ClientSession] = None


async def get_aiohttp_session() -> aiohttp.ClientSession:
    global _aiohttp_session
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


def _http_get(url: str, headers: Optional[dict] = None) -> Optional[str]:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import requests
            resp = requests.get(url, headers=headers or {}, timeout=8)
            if resp.status_code == 200:
                return resp.text
            return None
        return loop.run_until_complete(async_http_get(url, headers))
    except Exception:
        try:
            import requests
            resp = requests.get(url, headers=headers or {}, timeout=8)
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            logger.debug(f"HTTP GET fallback error: {e}")
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

_realtime_cache = ThreadSafeLRU(maxsize=500, ttl=5)
_history_cache = ThreadSafeLRU(maxsize=200, ttl=60)
_hot_symbols_cache: list[str] = []
_hot_symbols_lock = asyncio.Lock()


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
                except Exception:
                    score = 0.5
            scored.append((name, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in scored]


class TencentSource:
    """腾讯财经数据源"""

    BASE_URL = "http://qt.gtimg.cn/q="

    @staticmethod
    def _build_code(symbol: str, market: str) -> str:
        if market == "A":
            if symbol.startswith("6"):
                return f"sh{symbol}"
            return f"sz{symbol}"
        if market == "HK":
            return f"hk{symbol.zfill(5)}"
        if market == "US":
            return f"us{symbol.upper()}"
        return symbol

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
        if market == "A":
            if symbol.startswith("6"):
                prefix = "sh"
            else:
                prefix = "sz"
            url = f"http://hq.sinajs.cn/list={prefix}{symbol}"
        elif market == "HK":
            url = f"http://hq.sinajs.cn/list=rt_hk{symbol.zfill(5)}"
        elif market == "US":
            url = f"http://hq.sinajs.cn/list=gb_{symbol.lower()}"
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
            import akshare as ak
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
            import akshare as ak
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
            import baostock as bs
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
            except Exception:
                pass
            return None


class SmartDataFetcher:
    """智能数据获取器，自动选择最优数据源"""

    def __init__(self, db: Optional[SQLiteStore] = None):
        self._db = db or get_db()
        self._health = DataSourceHealthMonitor(self._db)
        self._sources = {
            "tencent": TencentSource,
            "sina": SinaSource,
        }

    async def get_realtime(self, symbol: str, market: Optional[str] = None) -> Optional[dict]:
        if market is None:
            market = MarketDetector.detect(symbol)

        cache_key = f"rt_{symbol}_{market}"
        cached = _realtime_cache.get(cache_key)
        if cached is not None:
            return cached

        ranked = self._health.rank_sources(["tencent", "sina"], "realtime")

        for source_name in ranked:
            source = self._sources.get(source_name)
            if source is None:
                continue
            start = time.time()
            try:
                result = await source.fetch_realtime(symbol, market)
                latency = time.time() - start
                if result:
                    self._health.record_request(source_name, "realtime", True, latency)
                    _realtime_cache.set(cache_key, result)
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
                    except Exception:
                        pass

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
        if kline_type == "daily" and period in KLINE_TYPE_MAP:
            kline_type = KLINE_TYPE_MAP[period]

        market = MarketDetector.detect(symbol)

        cache_key = f"hist_{symbol}_{market}_{kline_type}_{adjust}_{period}"
        cached = _history_cache.get(cache_key)
        if cached is not None:
            return cached

        db_df = self._db.load_kline_rows(symbol, market, kline_type, adjust)
        if not db_df.empty and len(db_df) >= 30:
            _history_cache.set(cache_key, db_df)
            return db_df

        df = await self._fetch_history_from_sources(symbol, market, kline_type, adjust, period)
        if df is not None and not df.empty:
            rows = df.to_dict("records")
            self._db.upsert_kline_rows(symbol, market, kline_type, adjust, rows)
            _history_cache.set(cache_key, df)
            return df

        return pd.DataFrame()

    async def _fetch_history_from_sources(self, symbol: str, market: str,
                                           kline_type: str, adjust: str,
                                           period: str) -> Optional[pd.DataFrame]:
        ranked = self._health.rank_sources(["tencent", "akshare", "baostock"], "history")

        for source_name in ranked:
            start = time.time()
            try:
                if source_name == "tencent":
                    count_map = {"1y": 300, "3y": 800, "5y": 1300}
                    count = count_map.get(period, 300)
                    result = await TencentSource.fetch_history(symbol, market, kline_type, adjust, count)
                elif source_name == "akshare":
                    result = await AKShareSource.fetch_history(symbol, market, kline_type, adjust, period)
                elif source_name == "baostock":
                    result = await BaoStockSource.fetch_history(symbol, market, kline_type, adjust)
                else:
                    continue

                latency = time.time() - start
                if result is not None and not result.empty:
                    self._health.record_request(source_name, "history", True, latency)
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
        return await AKShareSource.fetch_fundamentals(symbol, market)

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
            except Exception:
                pass

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
            except Exception:
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
            import akshare as ak
            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
            if df is not None and not df.empty:
                df = df.sort_values("成交额", ascending=False) if "成交额" in df.columns else df
                symbols = df["代码"].tolist()[:50] if "代码" in df.columns else []
                async with _hot_symbols_lock:
                    _hot_symbols_cache = symbols
        except Exception as e:
            logger.debug(f"Refresh hot symbols error: {e}")

    async def preload_all(self) -> None:
        try:
            await self.get_market_overview()
        except Exception as e:
            logger.debug(f"Preload market overview error: {e}")
