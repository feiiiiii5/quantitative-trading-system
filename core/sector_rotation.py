"""
QuantCore 板块轮动模块
对标同花顺板块轮动：板块强度排名、轮动追踪、领涨股、动量评分
数据源：东方财富板块数据
"""
import asyncio
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field

from core.data_fetcher import http_get_json

logger = logging.getLogger(__name__)

_SECTOR_CACHE: list[dict] = []
_SECTOR_CACHE_TS: float = 0.0
_SECTOR_CACHE_TTL = 300
_SECTOR_CACHE_LOCK = threading.Lock()

_ROTATION_HISTORY: list[dict] = []
_ROTATION_HISTORY_MAX = 20
_ROTATION_HISTORY_LOCK = threading.Lock()


@dataclass
class SectorStrength:
    name: str
    code: str
    change_pct: float
    momentum_score: float
    capital_flow: float
    leading_stocks: list[dict] = field(default_factory=list)
    rank: int = 0


async def fetch_sector_list() -> list[dict]:
    global _SECTOR_CACHE, _SECTOR_CACHE_TS
    now = time.monotonic()
    with _SECTOR_CACHE_LOCK:
        if _SECTOR_CACHE and now - _SECTOR_CACHE_TS < _SECTOR_CACHE_TTL:
            return list(_SECTOR_CACHE)

    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_board_industry_name_em)
        if df is not None and not df.empty:
            result = []
            for row in df.to_dict("records"):
                result.append({
                    "code": str(row.get("板块代码", "")),
                    "name": str(row.get("板块名称", "")),
                    "change_pct": float(row.get("涨跌幅", 0) or 0),
                    "change": float(row.get("涨跌额", 0) or 0),
                    "amount": 0,
                    "turnover_rate": float(row.get("换手率", 0) or 0),
                    "main_net_inflow": float(row.get("主力净流入", 0) or 0),
                    "up_count": int(row.get("上涨家数", 0) or 0),
                    "down_count": int(row.get("下跌家数", 0) or 0),
                    "leading_stock": str(row.get("领涨股票", "")),
                    "leading_change": float(row.get("领涨股票涨跌幅", 0) or 0),
                })
            with _SECTOR_CACHE_LOCK:
                _SECTOR_CACHE = result
                _SECTOR_CACHE_TS = now
            return result
    except Exception as e:
        logger.warning("AKShare sector list error: %s", e)

    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": "100",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:90+t:2+f:!50",
            "fields": "f2,f3,f4,f6,f8,f12,f14,f62,f104,f105,f128,f136,f140",
        }
        data = await http_get_json(url, params, use_jsonp=True)
        if data and data.get("data", {}).get("diff"):
            diff = data["data"]["diff"]
            result = []
            for item in diff:
                result.append({
                    "code": item.get("f12", ""),
                    "name": item.get("f14", ""),
                    "change_pct": float(item.get("f3", 0) or 0),
                    "change": float(item.get("f4", 0) or 0),
                    "amount": float(item.get("f6", 0) or 0),
                    "turnover_rate": float(item.get("f8", 0) or 0),
                    "main_net_inflow": float(item.get("f62", 0) or 0),
                    "up_count": int(item.get("f104", 0) or 0),
                    "down_count": int(item.get("f105", 0) or 0),
                    "leading_stock": item.get("f128", ""),
                    "leading_change": float(item.get("f140", 0) or 0),
                })
            with _SECTOR_CACHE_LOCK:
                _SECTOR_CACHE = result
                _SECTOR_CACHE_TS = now
            return result
    except Exception as e:
        logger.warning("Sector list fetch error: %s", e)

    try:
        url2 = "https://push2.eastmoney.com/api/qt/clist/get"
        params2 = {
            "pn": "1",
            "pz": "100",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:90+t:3+f:!50",
            "fields": "f2,f3,f4,f6,f8,f12,f14,f62,f104,f105,f128,f140",
        }
        data2 = await http_get_json(url2, params2, use_jsonp=True)
        if data2 and data2.get("data", {}).get("diff"):
            diff2 = data2["data"]["diff"]
            result = []
            for item in diff2:
                result.append({
                    "code": item.get("f12", ""),
                    "name": item.get("f14", ""),
                    "change_pct": float(item.get("f3", 0) or 0),
                    "change": float(item.get("f4", 0) or 0),
                    "amount": float(item.get("f6", 0) or 0),
                    "turnover_rate": float(item.get("f8", 0) or 0),
                    "main_net_inflow": float(item.get("f62", 0) or 0),
                    "up_count": int(item.get("f104", 0) or 0),
                    "down_count": int(item.get("f105", 0) or 0),
                    "leading_stock": item.get("f128", ""),
                    "leading_change": float(item.get("f140", 0) or 0),
                })
            with _SECTOR_CACHE_LOCK:
                _SECTOR_CACHE = result
                _SECTOR_CACHE_TS = now
            return result
    except Exception as e:
        logger.warning("Sector list fetch error (concept): %s", e)

    try:
        from core.data_fetcher import get_fetcher
        fetcher = get_fetcher()
        overview = await fetcher.get_market_overview()
        sector_data = overview.get("sector_heatmap", [])
        if sector_data:
            result = []
            for i, s in enumerate(sector_data[:50]):
                result.append({
                    "code": s.get("code", f"BK{str(i).zfill(4)}"),
                    "name": s.get("name", ""),
                    "change_pct": float(s.get("change_pct", 0) or 0),
                    "change": 0,
                    "amount": float(s.get("amount", 0) or 0),
                    "turnover_rate": 0,
                    "main_net_inflow": 0,
                    "up_count": 0,
                    "down_count": 0,
                    "leading_stock": "",
                    "leading_change": 0,
                })
            with _SECTOR_CACHE_LOCK:
                _SECTOR_CACHE = result
                _SECTOR_CACHE_TS = now
            return result
    except Exception as e:
        logger.debug("Market overview sector fallback error: %s", e)

    try:
        url = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
        from core.data_fetcher import async_http_get
        text = await async_http_get(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        })
        if text:
            m = re.search(r'=\s*({.*})', text, re.DOTALL)
            if m:
                data = json.loads(m.group(1))
                result = []
                for _key, val in data.items():
                    parts = val.split(',')
                    if len(parts) >= 6:
                        name = parts[1]
                        code = parts[0].strip('"') if parts[0] else ""
                        change_pct = float(parts[5]) if parts[5] else 0
                        amount = float(parts[7]) if len(parts) > 7 and parts[7] else 0
                        leading_stock = parts[11] if len(parts) > 11 else ""
                        result.append({
                            "code": code,
                            "name": name,
                            "change_pct": round(change_pct, 2),
                            "change": 0,
                            "amount": amount,
                            "turnover_rate": 0,
                            "main_net_inflow": 0,
                            "up_count": 0,
                            "down_count": 0,
                            "leading_stock": leading_stock,
                            "leading_change": 0,
                        })
                if result:
                    with _SECTOR_CACHE_LOCK:
                        _SECTOR_CACHE = result
                        _SECTOR_CACHE_TS = now
                    return result
    except Exception as e:
        logger.warning("Sina sector fallback error: %s", e)

    with _SECTOR_CACHE_LOCK:
        return _SECTOR_CACHE


async def fetch_sector_stocks(sector_code: str, count: int = 20) -> list[dict]:
    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_board_industry_cons_em, symbol=sector_code)
        if df is not None and not df.empty:
            result = []
            for row in df.head(count).to_dict("records"):
                result.append({
                    "symbol": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "price": float(row.get("最新价", 0) or 0),
                    "change_pct": float(row.get("涨跌幅", 0) or 0),
                    "change": float(row.get("涨跌额", 0) or 0),
                    "turnover_rate": float(row.get("换手率", 0) or 0),
                    "high": float(row.get("最高", 0) or 0),
                    "low": float(row.get("最低", 0) or 0),
                    "main_net_inflow": 0,
                })
            return result
    except Exception as e:
        logger.warning("AKShare sector stocks error for %s: %s", sector_code, e)

    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": str(count),
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": f"b:{sector_code}+f:!50",
            "fields": "f2,f3,f4,f8,f12,f14,f15,f16,f17,f62",
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
                    "change": float(item.get("f4", 0) or 0),
                    "turnover_rate": float(item.get("f8", 0) or 0),
                    "high": float(item.get("f15", 0) or 0),
                    "low": float(item.get("f16", 0) or 0),
                    "main_net_inflow": float(item.get("f62", 0) or 0),
                })
            return result
    except Exception as e:
        logger.debug("Sector stocks fetch error for %s: %s", sector_code, e)

    try:
        sector_name = ""
        sectors = await fetch_sector_list()
        for s in sectors:
            if s.get("code") == sector_code:
                sector_name = s.get("name", "")
                break
        if sector_name:
            from core.market_data import fetch_all_a_stocks_async
            all_stocks = await fetch_all_a_stocks_async()
            matched = [s for s in all_stocks if s.get("industry") == sector_name]
            if matched:
                matched.sort(key=lambda x: abs(float(x.get("amount", 0) or 0)), reverse=True)
                result = []
                for s in matched[:count]:
                    result.append({
                        "symbol": s.get("symbol", ""),
                        "name": s.get("name", ""),
                        "price": float(s.get("price", 0) or 0),
                        "change_pct": float(s.get("change_pct", 0) or 0),
                        "change": float(s.get("change", 0) or 0),
                        "turnover_rate": float(s.get("turnover_rate", 0) or 0),
                        "high": 0,
                        "low": 0,
                        "main_net_inflow": 0,
                    })
                return result
    except Exception as e:
        logger.warning("Sector stocks by name fallback error: %s", e)

    return []


class SectorRotationAnalyzer:
    """板块轮动分析器"""

    def __init__(self):
        self._history: list[dict] = []

    async def get_sector_strength(self, top_n: int = 20) -> list[dict]:
        sectors = await fetch_sector_list()
        if not sectors:
            return []

        for s in sectors:
            change_pct = s.get("change_pct", 0)
            main_net = s.get("main_net_inflow", 0)
            up_count = s.get("up_count", 0)
            down_count = s.get("down_count", 0)
            total = up_count + down_count
            breadth = (up_count - down_count) / total if total > 0 else 0

            momentum_score = (
                change_pct * 30
                + min(max(main_net / 1e9, -5), 5) * 20
                + breadth * 30
                + min(s.get("turnover_rate", 0) * 5, 20)
            )
            s["momentum_score"] = round(momentum_score, 2)

        sectors.sort(key=lambda x: x.get("momentum_score", 0), reverse=True)
        for i, s in enumerate(sectors[:top_n]):
            s["rank"] = i + 1

        return sectors[:top_n]

    async def get_rotation_snapshot(self) -> dict:
        sectors = await self.get_sector_strength(30)
        if not sectors:
            return {"timestamp": time.time(), "top_sectors": [], "bottom_sectors": []}

        top_5 = sectors[:5]
        bottom_5 = sectors[-5:] if len(sectors) >= 5 else sectors

        snapshot = {
            "timestamp": time.time(),
            "top_sectors": [{"name": s["name"], "change_pct": s["change_pct"], "momentum_score": s.get("momentum_score", 0)} for s in top_5],
            "bottom_sectors": [{"name": s["name"], "change_pct": s["change_pct"], "momentum_score": s.get("momentum_score", 0)} for s in bottom_5],
        }

        with _ROTATION_HISTORY_LOCK:
            self._history.append(snapshot)
            if len(self._history) > _ROTATION_HISTORY_MAX:
                self._history = self._history[-_ROTATION_HISTORY_MAX:]

        return snapshot

    def get_rotation_trend(self) -> list[dict]:
        with _ROTATION_HISTORY_LOCK:
            return list(self._history)

    async def get_sector_detail(self, sector_code: str) -> dict:
        sectors = await fetch_sector_list()
        sector_info = None
        for s in sectors:
            if s.get("code") == sector_code:
                sector_info = s
                break

        stocks = await fetch_sector_stocks(sector_code, 20)

        return {
            "sector": sector_info,
            "stocks": stocks,
        }

    def detect_rotation_signal(self, current: list[dict], previous: list[dict] | None = None) -> list[dict]:
        if not current:
            return []
        if previous is None and len(self._history) >= 2:
            prev_top = {s["name"] for s in self._history[-2].get("top_sectors", [])}
        elif previous:
            prev_top = {s["name"] for s in previous[:5]}
        else:
            return []

        curr_top = {s["name"] for s in current[:5]}
        new_entries = curr_top - prev_top
        dropped = prev_top - curr_top

        signals = []
        for name in new_entries:
            for s in current:
                if s["name"] == name:
                    signals.append({
                        "type": "sector_entering_top",
                        "sector": name,
                        "change_pct": s.get("change_pct", 0),
                        "signal": f"{name}进入板块前5，关注轮动机会",
                    })
                    break

        for name in dropped:
            signals.append({
                "type": "sector_leaving_top",
                "sector": name,
                "signal": f"{name}退出板块前5，注意资金撤离",
            })

        return signals


_analyzer: SectorRotationAnalyzer | None = None
_analyzer_lock = threading.Lock()


def get_sector_rotation_analyzer() -> SectorRotationAnalyzer:
    global _analyzer
    if _analyzer is None:
        with _analyzer_lock:
            if _analyzer is None:
                _analyzer = SectorRotationAnalyzer()
    return _analyzer
