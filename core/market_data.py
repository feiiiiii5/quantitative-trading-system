"""
QuantCore 市场数据辅助模块
提供股票列表获取和后台刷新
"""
import asyncio
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_refresh_thread: Optional[threading.Thread] = None
_refresh_stop = threading.Event()


def get_stock_list(market: str) -> list[dict]:
    """获取指定市场的股票列表"""
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
        logger.debug(f"Get stock list error for {market}: {e}")
    return []


def _refresh_loop() -> None:
    while not _refresh_stop.is_set():
        try:
            _refresh_stop.wait(timeout=3600)
            if _refresh_stop.is_set():
                break
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
