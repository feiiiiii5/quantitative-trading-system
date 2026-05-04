"""
QuantCore 资讯引擎模块
对标同花顺资讯中心：财经新闻聚合、情绪分析、市场情绪指数
数据源：东方财富、新浪财经
"""
import asyncio
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_POSITIVE_WORDS = frozenset({
    "上涨", "大涨", "涨停", "暴涨", "飙升", "新高", "突破", "利好", "盈利",
    "增长", "增持", "回购", "超预期", "强势", "反弹", "回暖", "复苏", "景气",
    "订单", "扩产", "中标", "签约", "合作", "创新高", "翻倍", "龙头", "领先",
    "业绩大增", "营收增长", "净利润增长", "分红", "高送转", "并购", "重组",
    "获批", "上市", "首发", "量产", "交付", "突破性", "里程碑",
})

_NEGATIVE_WORDS = frozenset({
    "下跌", "大跌", "跌停", "暴跌", "闪崩", "新低", "破位", "利空", "亏损",
    "下滑", "减持", "退市", "违规", "处罚", "警示", "风险", "违约", "爆雷",
    "诉讼", "调查", "冻结", "停牌", "质押", "强平", "清仓", "踩雷", "暴雷",
    "业绩下滑", "营收下降", "亏损扩大", "商誉减值", "退市风险", "被查",
    "罚款", "制裁", "禁令", "限制", "暂停", "终止", "失败",
})


@dataclass
class NewsItem:
    title: str
    source: str
    url: str
    time: str
    content: str = ""
    sentiment: float = 0.0
    sentiment_label: str = "neutral"
    related_symbols: list[str] = field(default_factory=list)


@dataclass
class MarketSentiment:
    fear_greed_index: float
    label: str
    news_sentiment: float
    volume_sentiment: float
    momentum_sentiment: float
    breadth_sentiment: float
    timestamp: float = 0.0


def _analyze_sentiment(text: str) -> tuple[float, str]:
    if not text:
        return 0.0, "neutral"
    pos_count = sum(1 for w in _POSITIVE_WORDS if w in text)
    neg_count = sum(1 for w in _NEGATIVE_WORDS if w in text)
    total = pos_count + neg_count
    if total == 0:
        return 0.0, "neutral"
    score = (pos_count - neg_count) / total
    if score > 0.3:
        label = "bullish"
    elif score < -0.3:
        label = "bearish"
    elif score > 0.1:
        label = "slightly_bullish"
    elif score < -0.1:
        label = "slightly_bearish"
    else:
        label = "neutral"
    return round(score, 4), label


def _extract_symbols(text: str) -> list[str]:
    symbols = []
    patterns = [
        r'[（(](\d{6})[）)]',
        r'(\d{6})[·\.]',
        r'[沪深]([036]\d{5})',
    ]
    for pat in patterns:
        for m in re.finditer(pat, text):
            code = m.group(1)
            if code not in symbols:
                symbols.append(code)
    return symbols[:5]


async def _fetch_eastmoney_news(page: int = 1, count: int = 40) -> list[dict]:
    try:
        from core.data_fetcher import get_aiohttp_session
        session = await get_aiohttp_session()
        url = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
        params = {
            "client": "web",
            "biz": "web_news_col",
            "column": "350",
            "order": "1",
            "needInteractData": "0",
            "page_index": str(page),
            "page_size": str(count),
        }
        async with session.get(url, params=params, headers={"Referer": "https://finance.eastmoney.com/"}) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
            data = json.loads(text)
            items = data.get("data", {}).get("list", [])
            result = []
            for item in items:
                title = item.get("title", "")
                source = item.get("source", "")
                url_val = item.get("url", "")
                pub_time = item.get("showTime", "")
                content = item.get("digest", title)
                if not title:
                    continue
                score, label = _analyze_sentiment(title + " " + content)
                symbols = _extract_symbols(title + " " + content)
                result.append({
                    "title": title,
                    "source": source,
                    "url": url_val,
                    "time": pub_time,
                    "content": content[:200],
                    "sentiment": score,
                    "sentiment_label": label,
                    "related_symbols": symbols,
                })
            return result
    except Exception as e:
        logger.debug(f"EastMoney news fetch error: {e}")
    return []


async def _fetch_sina_news() -> list[dict]:
    try:
        from core.data_fetcher import async_http_get
        from urllib.parse import urlencode
        base_url = "https://feed.mix.sina.com.cn/api/roll/get"
        query_params = urlencode({
            "pageid": "153",
            "lid": "2516",
            "k": "",
            "num": "40",
            "page": "1",
            "r": f"0.{int(time.time() * 1000)}",
        })
        text = await async_http_get(f"{base_url}?{query_params}", headers={"Referer": "https://finance.sina.com.cn/"})
        if not text:
            return []
        data = json.loads(text)
        items = data.get("result", {}).get("data", [])
        result = []
        for item in items:
            title = item.get("title", "")
            source = item.get("author", item.get("media_name", ""))
            url_val = item.get("url", "")
            ctime = item.get("ctime", "")
            content = item.get("intro", title)
            if not title:
                continue
            score, label = _analyze_sentiment(title + " " + content)
            symbols = _extract_symbols(title + " " + content)
            result.append({
                "title": title,
                "source": source,
                "url": url_val,
                "time": ctime,
                "content": content[:200],
                "sentiment": score,
                "sentiment_label": label,
                "related_symbols": symbols,
            })
        return result
    except Exception as e:
        logger.debug(f"Sina news fetch error: {e}")
    return []


async def _fetch_stock_news_eastmoney(symbol: str, count: int = 20) -> list[dict]:
    try:
        from core.data_fetcher import get_aiohttp_session
        session = await get_aiohttp_session()
        secid = f"0.{symbol}" if symbol.startswith(("0", "3")) else f"1.{symbol}"
        url = f"https://search-api-web.eastmoney.com/search/jsonp"
        params = {
            "cb": "jQuery",
            "param": json.dumps({
                "uid": "",
                "keyword": symbol,
                "type": ["cmsArticleWebOld"],
                "client": "web",
                "clientType": "web",
                "clientVersion": "curr",
                "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default", "pageIndex": 1, "pageSize": count, "preTag": "", "postTag": ""}},
            }),
        }
        async with session.get(url, params=params, headers={"Referer": "https://so.eastmoney.com/"}) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
            json_str = re.sub(r'^jQuery\(', '', text).rstrip(')')
            data = json.loads(json_str)
            items = data.get("result", {}).get("cmsArticleWebOld", {}).get("list", [])
            result = []
            for item in items:
                title = item.get("title", "").replace("<em>", "").replace("</em>", "")
                source = item.get("mediaName", "")
                url_val = item.get("url", "")
                pub_time = item.get("date", "")
                content = item.get("content", title).replace("<em>", "").replace("</em>", "")
                if not title:
                    continue
                score, label = _analyze_sentiment(title + " " + content)
                result.append({
                    "title": title,
                    "source": source,
                    "url": url_val,
                    "time": pub_time,
                    "content": content[:200],
                    "sentiment": score,
                    "sentiment_label": label,
                    "related_symbols": [symbol],
                })
            return result
    except Exception as e:
        logger.debug(f"Stock news fetch error for {symbol}: {e}")
    return []


class NewsEngine:
    """资讯引擎 - 新闻聚合与情绪分析"""

    def __init__(self):
        self._cache: list[dict] = []
        self._cache_ts: float = 0.0
        self._cache_ttl = 300

    async def fetch_latest_news(self, count: int = 40) -> list[dict]:
        now = time.time()
        if self._cache and now - self._cache_ts < self._cache_ttl:
            return self._cache[:count]

        all_news = []
        tasks = [
            _fetch_eastmoney_news(1, count),
            _fetch_sina_news(),
        ]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            logger.warning("新闻获取超时（10秒），使用已有缓存")
            return self._cache[:count] if self._cache else []
        for r in results:
            if isinstance(r, list):
                all_news.extend(r)

        seen_titles = set()
        unique = []
        for n in all_news:
            t = n.get("title", "")
            if t not in seen_titles:
                seen_titles.add(t)
                unique.append(n)

        unique.sort(key=lambda x: x.get("time", ""), reverse=True)
        self._cache = unique
        self._cache_ts = now
        return unique[:count]

    async def fetch_stock_news(self, symbol: str, count: int = 20) -> list[dict]:
        results = await _fetch_stock_news_eastmoney(symbol, count)
        if results:
            return results[:count]
        news = await self.fetch_latest_news(100)
        related = [n for n in news if symbol in n.get("related_symbols", []) or symbol in n.get("title", "") or symbol in n.get("content", "")]
        return related[:count] if related else news[:count]

    def compute_market_sentiment(
        self,
        news_items: list[dict],
        market_stocks: Optional[list[dict]] = None,
        indices_data: Optional[dict] = None,
    ) -> MarketSentiment:
        news_scores = [n.get("sentiment", 0) for n in news_items if n.get("sentiment")]
        news_sentiment = float(np.mean(news_scores)) if news_scores else 0.0

        volume_sentiment = 0.0
        if market_stocks:
            advancers = sum(1 for s in market_stocks if float(s.get("change_pct", 0) or 0) > 0)
            decliners = sum(1 for s in market_stocks if float(s.get("change_pct", 0) or 0) < 0)
            total = advancers + decliners
            if total > 0:
                volume_sentiment = (advancers - decliners) / total

        momentum_sentiment = 0.0
        if indices_data:
            changes = []
            for key, val in indices_data.items():
                if isinstance(val, dict):
                    pct = float(val.get("change_pct", 0) or 0)
                    changes.append(pct)
            if changes:
                momentum_sentiment = float(np.mean(changes)) / 3.0

        breadth_sentiment = 0.0
        if market_stocks:
            limit_up = sum(1 for s in market_stocks if float(s.get("change_pct", 0) or 0) > 9.5)
            limit_down = sum(1 for s in market_stocks if float(s.get("change_pct", 0) or 0) < -9.5)
            total_stocks = len(market_stocks)
            if total_stocks > 0:
                breadth_sentiment = (limit_up - limit_down) / total_stocks * 10

        raw_index = (
            news_sentiment * 25
            + volume_sentiment * 25
            + momentum_sentiment * 25
            + breadth_sentiment * 25
            + 50
        )
        fear_greed_index = max(0, min(100, raw_index))

        if fear_greed_index >= 80:
            label = "极度贪婪"
        elif fear_greed_index >= 60:
            label = "贪婪"
        elif fear_greed_index >= 40:
            label = "中性"
        elif fear_greed_index >= 20:
            label = "恐惧"
        else:
            label = "极度恐惧"

        return MarketSentiment(
            fear_greed_index=round(fear_greed_index, 1),
            label=label,
            news_sentiment=round(news_sentiment, 4),
            volume_sentiment=round(volume_sentiment, 4),
            momentum_sentiment=round(momentum_sentiment, 4),
            breadth_sentiment=round(breadth_sentiment, 4),
            timestamp=time.time(),
        )

    def get_news_summary(self, news_items: list[dict]) -> dict:
        if not news_items:
            return {"total": 0, "bullish": 0, "bearish": 0, "neutral": 0, "hot_symbols": []}
        bullish = sum(1 for n in news_items if n.get("sentiment_label") in ("bullish", "slightly_bullish"))
        bearish = sum(1 for n in news_items if n.get("sentiment_label") in ("bearish", "slightly_bearish"))
        neutral = len(news_items) - bullish - bearish
        symbol_count: dict[str, int] = {}
        for n in news_items:
            for s in n.get("related_symbols", []):
                symbol_count[s] = symbol_count.get(s, 0) + 1
        hot_symbols = sorted(symbol_count.items(), key=lambda x: x[1], reverse=True)[:10]
        return {
            "total": len(news_items),
            "bullish": bullish,
            "bearish": bearish,
            "neutral": neutral,
            "hot_symbols": [{"symbol": s, "count": c} for s, c in hot_symbols],
        }


_news_engine: Optional[NewsEngine] = None
_news_engine_lock = threading.Lock()


def get_news_engine() -> NewsEngine:
    global _news_engine
    if _news_engine is None:
        with _news_engine_lock:
            if _news_engine is None:
                _news_engine = NewsEngine()
    return _news_engine
