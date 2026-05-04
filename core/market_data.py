"""
QuantCore 市场数据辅助模块
使用新浪财经API获取全量A股列表（快速稳定，替代akshare）
"""
import asyncio
import json
import logging
import threading
import time
from typing import Optional

import aiohttp

from core.data_fetcher import safe_float as _num

logger = logging.getLogger(__name__)

_refresh_thread: Optional[threading.Thread] = None
_refresh_stop = threading.Event()

_all_a_stocks_cache: list[dict] = []
_all_a_stocks_ts: float = 0.0
_A_STOCKS_TTL = 120
_all_a_stocks_lock = threading.Lock()
_all_a_stocks_fetching = False

_SINA_LIST_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
_SINA_HQ_URL = "https://hq.sinajs.cn/list="


async def _fetch_sina_stock_list(page: int = 1, num: int = 80, sort: str = "amount", asc: int = 0) -> list[dict]:
    try:
        from core.data_fetcher import get_aiohttp_session
        session = await get_aiohttp_session()
        params = {
            "page": str(page),
            "num": str(num),
            "sort": sort,
            "asc": str(asc),
            "node": "hs_a",
            "symbol": "",
            "_s_r_a": "auto",
        }
        async with session.get(_SINA_LIST_URL, params=params, headers={"Referer": "https://finance.sina.com.cn"}) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
            data = json.loads(text)
            if not isinstance(data, list):
                return []
            result = []
            for item in data:
                code = item.get("code", "")
                symbol_raw = item.get("symbol", "")
                name = item.get("name", "")
                if not code or not name:
                    continue
                result.append({
                    "symbol": code,
                    "name": name,
                    "price": _num(item.get("trade")),
                    "change_pct": _num(item.get("changepercent")),
                    "change": _num(item.get("pricechange")),
                    "volume": _num(item.get("volume")),
                    "amount": _num(item.get("amount")),
                    "open": _num(item.get("open")),
                    "high": _num(item.get("high")),
                    "low": _num(item.get("low")),
                    "last_close": _num(item.get("settlement")),
                    "pe": _num(item.get("per")),
                    "pb": _num(item.get("pb")),
                    "total_market_cap": _num(item.get("mktcap"), default=None),
                    "float_market_cap": _num(item.get("nmc"), default=None),
                    "turnover_rate": _num(item.get("turnoverratio")),
                    "market": "A",
                    "industry": "",
                })
            return result
    except Exception as e:
        logger.debug(f"Sina stock list fetch error (page={page}): {e}")
    return []


async def _fetch_all_sina_stocks() -> list[dict]:
    try:
        all_stocks: list[dict] = []
        page = 1
        while True:
            batch = await _fetch_sina_stock_list(page=page, num=80, sort="amount", asc=0)
            if not batch:
                break
            all_stocks.extend(batch)
            if len(batch) < 80:
                break
            page += 1
            if page > 80:
                break
        return all_stocks
    except Exception as e:
        logger.debug(f"Fetch all Sina stocks error: {e}")
    return []


async def _fetch_sina_stocks_fast() -> list[dict]:
    try:
        from core.data_fetcher import get_aiohttp_session
        session = await get_aiohttp_session()
        tasks = []
        for page in range(1, 70):
            params = {
                "page": str(page),
                "num": "80",
                "sort": "amount",
                "asc": "0",
                "node": "hs_a",
                "symbol": "",
                "_s_r_a": "auto",
            }
            tasks.append((page, params))

        all_stocks: list[dict] = []
        batch_size = 5
        for i in range(0, len(tasks), batch_size):
            batch_tasks = tasks[i:i + batch_size]
            coros = []
            for page, params in batch_tasks:
                coros.append(_fetch_sina_stock_list(page=page, num=80))
            results = await asyncio.gather(*coros, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    all_stocks.extend(result)
            batch_results = [r for r in results if isinstance(r, list)]
            if batch_results and all(len(r) < 80 for r in batch_results):
                break

        return all_stocks
    except Exception as e:
        logger.debug(f"Sina fast fetch error: {e}")
    return []


async def fetch_all_a_stocks_async() -> list[dict]:
    global _all_a_stocks_cache, _all_a_stocks_ts, _all_a_stocks_fetching
    now = time.time()
    with _all_a_stocks_lock:
        if _all_a_stocks_cache and (now - _all_a_stocks_ts) < _A_STOCKS_TTL:
            return _all_a_stocks_cache
        if _all_a_stocks_fetching:
            if _all_a_stocks_cache:
                return _all_a_stocks_cache
            return []
        _all_a_stocks_fetching = True

    try:
        data = await _fetch_sina_stocks_fast()
        if data:
            with _all_a_stocks_lock:
                _all_a_stocks_cache = data
                _all_a_stocks_ts = now
            logger.info(f"Fetched {len(data)} A-share stocks from Sina")
            return data

        try:
            import akshare as ak
            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
            if df is not None and not df.empty:
                col_map = {
                    "代码": "symbol", "名称": "name", "最新价": "price",
                    "涨跌幅": "change_pct", "涨跌额": "change", "成交量": "volume",
                    "成交额": "amount", "振幅": "amplitude", "换手率": "turnover_rate",
                    "市盈率-动态": "pe", "市净率": "pb",
                }
                rename = {k: v for k, v in col_map.items() if k in df.columns}
                df = df.rename(columns=rename)
                result = []
                for _, row in df.iterrows():
                    result.append({
                        "symbol": str(row.get("symbol", "")),
                        "name": str(row.get("name", "")),
                        "price": float(row.get("price", 0) or 0),
                        "change_pct": float(row.get("change_pct", 0) or 0),
                        "change": float(row.get("change", 0) or 0),
                        "volume": float(row.get("volume", 0) or 0),
                        "amount": float(row.get("amount", 0) or 0),
                        "turnover_rate": float(row.get("turnover_rate", 0) or 0),
                        "pe": float(row.get("pe", 0) or 0),
                        "pb": float(row.get("pb", 0) or 0),
                        "market": "A",
                        "industry": str(row.get("行业", "")),
                    })
                with _all_a_stocks_lock:
                    _all_a_stocks_cache = result
                    _all_a_stocks_ts = time.time()
                return result
        except Exception as e:
            logger.debug(f"akshare fallback error: {e}")

        with _all_a_stocks_lock:
            return _all_a_stocks_cache if _all_a_stocks_cache else []
    except Exception:
        with _all_a_stocks_lock:
            return _all_a_stocks_cache if _all_a_stocks_cache else []
    finally:
        with _all_a_stocks_lock:
            _all_a_stocks_fetching = False


def get_all_a_stocks_sync() -> list[dict]:
    with _all_a_stocks_lock:
        if _all_a_stocks_cache:
            return _all_a_stocks_cache
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            with _all_a_stocks_lock:
                return _all_a_stocks_cache
        return asyncio.run(fetch_all_a_stocks_async())
    except Exception:
        with _all_a_stocks_lock:
            return _all_a_stocks_cache


def get_stock_list(market: str) -> list[dict]:
    if market == "A":
        stocks = get_all_a_stocks_sync()
        if stocks:
            return stocks
    try:
        import akshare as ak
        if market == "A":
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                result = []
                for _, row in df.iterrows():
                    result.append({
                        "code": str(row.get("代码", "")),
                        "name": str(row.get("名称", "")),
                        "market": "A",
                        "industry": str(row.get("行业", "")),
                    })
                return result
        elif market == "HK":
            df = ak.stock_hk_spot_em()
            if df is not None and not df.empty:
                result = []
                for _, row in df.iterrows():
                    result.append({
                        "code": str(row.get("代码", "")),
                        "name": str(row.get("名称", "")),
                        "market": "HK",
                    })
                return result
        elif market == "US":
            df = ak.stock_us_spot_em()
            if df is not None and not df.empty:
                result = []
                for _, row in df.iterrows():
                    result.append({
                        "code": str(row.get("代码", "")),
                        "name": str(row.get("名称", "")),
                        "market": "US",
                    })
                return result
    except Exception as e:
        logger.debug(f"Get stock list fallback error for {market}: {e}")
    return []


def _refresh_loop() -> None:
    while not _refresh_stop.is_set():
        try:
            _refresh_stop.wait(timeout=120)
            if _refresh_stop.is_set():
                break
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(fetch_all_a_stocks_async())
                loop.close()
            except Exception as e:
                logger.debug(f"Background refresh error: {e}")
        except Exception:
            break


def start_background_refresh() -> None:
    global _refresh_thread
    if _refresh_thread is not None and _refresh_thread.is_alive():
        return
    _refresh_stop.clear()
    _refresh_thread = threading.Thread(target=_refresh_loop, daemon=True)
    _refresh_thread.start()
    logger.info("Background refresh started")


def stop_background_refresh() -> None:
    _refresh_stop.set()
    logger.info("Background refresh stopped")
