"""
QuantCore 智能选股器模块
对标同花顺i问财：多条件选股、预设策略、自定义筛选
基于全量A股实时数据进行技术面+基本面综合筛选
"""
import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class FilterOperator(str, Enum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    BETWEEN = "between"
    IN = "in"


@dataclass
class FilterCondition:
    field: str
    operator: FilterOperator
    value: float | list[float] | str | list[str]
    label: str = ""


@dataclass
class ScreeningPreset:
    id: str
    name: str
    description: str
    conditions: list[FilterCondition] = field(default_factory=list)
    category: str = "custom"


PRESET_STRATEGIES: list[ScreeningPreset] = [
    ScreeningPreset(
        id="breakout_high",
        name="突破新高",
        description="股价创60日新高，成交量放大",
        conditions=[
            FilterCondition("change_pct", FilterOperator.GT, 0, "今日上涨"),
            FilterCondition("volume_ratio", FilterOperator.GT, 1.5, "量比>1.5"),
            FilterCondition("high_60d_ratio", FilterOperator.GT, 0.98, "接近60日新高"),
        ],
        category="technical",
    ),
    ScreeningPreset(
        id="volume_surge",
        name="放量拉升",
        description="成交量急剧放大，股价上涨",
        conditions=[
            FilterCondition("change_pct", FilterOperator.GT, 3, "涨幅>3%"),
            FilterCondition("volume_ratio", FilterOperator.GT, 2.0, "量比>2"),
            FilterCondition("turnover_rate", FilterOperator.GT, 3, "换手率>3%"),
        ],
        category="technical",
    ),
    ScreeningPreset(
        id="low_valuation",
        name="低估值蓝筹",
        description="PE/PB双低，大市值蓝筹股",
        conditions=[
            FilterCondition("pe", FilterOperator.BETWEEN, [0, 15], "PE 0-15"),
            FilterCondition("pb", FilterOperator.BETWEEN, [0, 1.5], "PB 0-1.5"),
            FilterCondition("total_market_cap", FilterOperator.GT, 500e8, "市值>500亿"),
        ],
        category="fundamental",
    ),
    ScreeningPreset(
        id="high_growth",
        name="高成长股",
        description="高ROE低PE，成长性突出",
        conditions=[
            FilterCondition("pe", FilterOperator.BETWEEN, [5, 30], "PE 5-30"),
            FilterCondition("roe", FilterOperator.GT, 15, "ROE>15%"),
            FilterCondition("revenue_yoy", FilterOperator.GT, 20, "营收增长>20%"),
        ],
        category="fundamental",
    ),
    ScreeningPreset(
        id="oversold_bounce",
        name="超跌反弹",
        description="近期大幅下跌，可能反弹",
        conditions=[
            FilterCondition("change_pct", FilterOperator.GT, 2, "今日反弹>2%"),
            FilterCondition("pct_20d", FilterOperator.LT, -15, "20日跌幅>15%"),
            FilterCondition("volume_ratio", FilterOperator.GT, 1.2, "量比>1.2"),
        ],
        category="technical",
    ),
    ScreeningPreset(
        id="strong_momentum",
        name="强势 momentum",
        description="连续上涨，动量强劲",
        conditions=[
            FilterCondition("change_pct", FilterOperator.GT, 1, "今日上涨>1%"),
            FilterCondition("pct_5d", FilterOperator.GT, 5, "5日涨幅>5%"),
            FilterCondition("turnover_rate", FilterOperator.BETWEEN, [2, 15], "换手率2-15%"),
        ],
        category="technical",
    ),
    ScreeningPreset(
        id="limit_up_pool",
        name="涨停板",
        description="今日涨停股票",
        conditions=[
            FilterCondition("change_pct", FilterOperator.GTE, 9.5, "涨幅>=9.5%"),
        ],
        category="market_activity",
    ),
    ScreeningPreset(
        id="high_dividend",
        name="高股息率",
        description="股息率高，稳定分红",
        conditions=[
            FilterCondition("dividend_yield", FilterOperator.GT, 4, "股息率>4%"),
            FilterCondition("pe", FilterOperator.BETWEEN, [0, 20], "PE 0-20"),
            FilterCondition("total_market_cap", FilterOperator.GT, 200e8, "市值>200亿"),
        ],
        category="fundamental",
    ),
]


def _apply_condition(stock: dict, cond: FilterCondition) -> bool:
    val = stock.get(cond.field)
    if val is None:
        return False
    try:
        val = float(val)
    except (ValueError, TypeError):
        if cond.operator == FilterOperator.IN:
            return str(val) in cond.value if isinstance(cond.value, list) else str(val) == str(cond.value)
        return False

    if cond.operator == FilterOperator.GT:
        return val > cond.value
    elif cond.operator == FilterOperator.GTE:
        return val >= cond.value
    elif cond.operator == FilterOperator.LT:
        return val < cond.value
    elif cond.operator == FilterOperator.LTE:
        return val <= cond.value
    elif cond.operator == FilterOperator.EQ:
        return abs(val - float(cond.value)) < 1e-9
    elif cond.operator == FilterOperator.BETWEEN:
        if isinstance(cond.value, list) and len(cond.value) == 2:
            return cond.value[0] <= val <= cond.value[1]
    elif cond.operator == FilterOperator.IN:
        if isinstance(cond.value, list):
            return val in [float(v) for v in cond.value]
    return False


_ENRICHED_FIELDS = {"pct_5d", "pct_20d", "high_60d_ratio", "volume_ratio", "roe", "dividend_yield", "revenue_yoy"}


class StockScreener:
    """智能选股器 - 多条件筛选A股"""

    def __init__(self):
        self._presets = {p.id: p for p in PRESET_STRATEGIES}

    def list_presets(self) -> list[dict]:
        result = []
        for p in PRESET_STRATEGIES:
            result.append({
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "category": p.category,
                "conditions": [
                    {"field": c.field, "operator": c.operator.value, "value": c.value, "label": c.label}
                    for c in p.conditions
                ],
            })
        return result

    def get_preset(self, preset_id: str) -> Optional[ScreeningPreset]:
        return self._presets.get(preset_id)

    def screen_by_preset(self, stocks: list[dict], preset_id: str) -> list[dict]:
        preset = self._presets.get(preset_id)
        if not preset:
            return []
        return self._screen(stocks, preset.conditions)

    def screen_by_conditions(self, stocks: list[dict], conditions: list[dict]) -> list[dict]:
        parsed = []
        for c in conditions:
            try:
                op = FilterOperator(c.get("operator", "gt"))
                parsed.append(FilterCondition(
                    field=c["field"],
                    operator=op,
                    value=c.get("value", 0),
                    label=c.get("label", ""),
                ))
            except (ValueError, KeyError):
                continue
        return self._screen(stocks, parsed)

    def _screen(self, stocks: list[dict], conditions: list[FilterCondition]) -> list[dict]:
        if not conditions:
            return stocks[:100]
        results = []
        for stock in stocks:
            if all(_apply_condition(stock, c) for c in conditions):
                results.append(stock)
        return results

    def _screen_raw_only(self, stocks: list[dict], conditions: list[FilterCondition]) -> list[dict]:
        if not conditions:
            return stocks[:500]
        raw_conditions = [c for c in conditions if c.field not in _ENRICHED_FIELDS]
        if not raw_conditions:
            return stocks[:500]
        results = []
        for stock in stocks:
            if all(_apply_condition(stock, c) for c in raw_conditions):
                results.append(stock)
        return results

    async def screen_with_enrichment(
        self,
        stocks: list[dict],
        preset_id: Optional[str] = None,
        custom_conditions: Optional[list[dict]] = None,
        sort_by: str = "change_pct",
        sort_desc: bool = True,
        limit: int = 50,
    ) -> list[dict]:
        if preset_id:
            preset = self._presets.get(preset_id)
            conditions = preset.conditions if preset else []
        elif custom_conditions:
            parsed = []
            for c in custom_conditions:
                try:
                    op = FilterOperator(c.get("operator", "gt"))
                    parsed.append(FilterCondition(
                        field=c["field"],
                        operator=op,
                        value=c.get("value", 0),
                        label=c.get("label", ""),
                    ))
                except (ValueError, KeyError):
                    continue
            conditions = parsed
        else:
            conditions = []

        needs_enrichment = any(c.field in _ENRICHED_FIELDS for c in conditions)

        if needs_enrichment and conditions:
            filtered = self._screen_raw_only(stocks, conditions)
            if filtered and needs_enrichment:
                filtered = await self._enrich_with_history(filtered)
            for stock in filtered:
                stock.setdefault("pct_5d", 0)
                stock.setdefault("pct_20d", 0)
                stock.setdefault("high_60d_ratio", 0)
                stock.setdefault("volume_ratio", 0)
            enriched_conditions = [c for c in conditions if c.field in _ENRICHED_FIELDS]
            if enriched_conditions:
                filtered = [s for s in filtered if all(_apply_condition(s, c) for c in enriched_conditions)]
        elif conditions:
            filtered = self._screen(stocks, conditions)
        else:
            filtered = stocks

        for stock in filtered:
            stock.setdefault("pct_5d", 0)
            stock.setdefault("pct_20d", 0)
            stock.setdefault("high_60d_ratio", 0)
            stock.setdefault("volume_ratio", 0)

        reverse = sort_desc
        filtered.sort(key=lambda x: float(x.get(sort_by) if x.get(sort_by) is not None else 0), reverse=reverse)
        return filtered[:limit]

    async def _enrich_with_history(self, stocks: list[dict]) -> list[dict]:
        try:
            from core.data_fetcher import get_fetcher
            fetcher = get_fetcher()
        except Exception:
            return stocks

        enriched = []
        batch_size = 10
        for i in range(0, len(stocks), batch_size):
            batch = stocks[i:i + batch_size]
            tasks = [self._enrich_single(fetcher, s) for s in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for stock, result in zip(batch, results):
                if isinstance(result, Exception):
                    stock["pct_5d"] = 0
                    stock["pct_20d"] = 0
                    stock["high_60d_ratio"] = 0
                    stock["volume_ratio"] = 0
                else:
                    stock.update(result)
                enriched.append(stock)
        return enriched

    @staticmethod
    async def _enrich_single(fetcher, stock: dict) -> dict:
        symbol = stock.get("symbol", "")
        if not symbol:
            return {"pct_5d": 0, "pct_20d": 0, "high_60d_ratio": 0, "volume_ratio": 0}
        try:
            df = await fetcher.get_history(symbol, period="6m", kline_type="daily", adjust="qfq")
            if df is None or df.empty or len(df) < 5:
                return {"pct_5d": 0, "pct_20d": 0, "high_60d_ratio": 0, "volume_ratio": 0}
            close = df["close"].astype(float)
            high = df["high"].astype(float)
            volume = df["volume"].astype(float)
            current = float(close.iloc[-1])
            result = {"pct_5d": 0, "pct_20d": 0, "high_60d_ratio": 0, "volume_ratio": 0}
            if len(close) >= 6:
                pct_5d = (current / float(close.iloc[-6]) - 1) * 100
                result["pct_5d"] = round(pct_5d, 2)
            if len(close) >= 21:
                pct_20d = (current / float(close.iloc[-21]) - 1) * 100
                result["pct_20d"] = round(pct_20d, 2)
            if len(high) >= 60:
                high_60d_max = float(high.rolling(60).max().iloc[-1])
                if high_60d_max > 0:
                    result["high_60d_ratio"] = round(current / high_60d_max, 4)
            elif len(high) >= 5:
                high_max = float(high.max())
                if high_max > 0:
                    result["high_60d_ratio"] = round(current / high_max, 4)
            if len(volume) >= 20:
                vol_ma20 = float(volume.iloc[-21:-1].mean())
                if vol_ma20 > 0:
                    result["volume_ratio"] = round(float(volume.iloc[-1]) / vol_ma20, 2)
            return result
        except Exception:
            return {"pct_5d": 0, "pct_20d": 0, "high_60d_ratio": 0, "volume_ratio": 0}


_screener: Optional[StockScreener] = None
_screener_lock = threading.Lock()


def get_stock_screener() -> StockScreener:
    global _screener
    if _screener is None:
        with _screener_lock:
            if _screener is None:
                _screener = StockScreener()
    return _screener
