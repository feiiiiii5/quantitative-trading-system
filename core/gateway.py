__all__ = [
    "BarData",
    "TickData",
    "BaseGateway",
    "GatewayManager",
]

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from core.events import Event, EventBus, EventType, get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class TickData:
    symbol: str
    market: str
    name: str = ""
    price: float = 0.0
    last_close: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    turnover_rate: float = 0.0
    total_market_cap: float = 0.0
    float_market_cap: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "market": self.market,
            "name": self.name,
            "price": self.price,
            "last_close": self.last_close,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "volume": self.volume,
            "amount": self.amount,
            "change": self.change,
            "change_pct": self.change_pct,
            "turnover_rate": self.turnover_rate,
            "total_market_cap": self.total_market_cap,
            "float_market_cap": self.float_market_cap,
            "timestamp": self.timestamp,
        }


@dataclass
class BarData:
    symbol: str
    market: str
    date: str = ""
    open: float = 0.0
    close: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    change_pct: float = 0.0
    turnover_rate: float = 0.0


class BaseGateway(ABC):
    gateway_name: str = ""

    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or get_event_bus()

    @abstractmethod
    async def fetch_tick(self, symbol: str, market: str) -> TickData | None:
        ...

    @abstractmethod
    async def fetch_bars(
        self,
        symbol: str,
        market: str,
        kline_type: str = "daily",
        adjust: str = "",
        count: int = 300,
    ) -> pd.DataFrame | None:
        ...

    async def fetch_ticks_batch(self, symbols: list[tuple[str, str]]) -> dict[str, TickData]:
        results: dict[str, TickData] = {}
        for symbol, market in symbols:
            tick = await self.fetch_tick(symbol, market)
            if tick is not None:
                results[symbol] = tick
        return results

    async def fetch_bars_batch(
        self,
        symbols: list[tuple[str, str]],
        kline_type: str = "daily",
        adjust: str = "",
        count: int = 300,
    ) -> dict[str, pd.DataFrame]:
        results: dict[str, pd.DataFrame] = {}
        for symbol, market in symbols:
            bars = await self.fetch_bars(symbol, market, kline_type, adjust, count)
            if bars is not None and not bars.empty:
                results[symbol] = bars
        return results

    def on_event(self, event_type: EventType, data: dict[str, Any]) -> None:
        self._event_bus.publish(Event(event_type, data))

    @property
    def name(self) -> str:
        return self.gateway_name or self.__class__.__name__


class _EastMoneyGateway(BaseGateway):
    gateway_name = "eastmoney"
    _source = None

    def __init__(self, event_bus: EventBus | None = None):
        super().__init__(event_bus)

    @classmethod
    def _get_source(cls):
        if cls._source is None:
            try:
                from core.data_fetcher import EastMoneySource
                cls._source = EastMoneySource
            except ImportError:
                logger.warning("EastMoneySource not available")
        return cls._source

    async def fetch_tick(self, symbol: str, market: str) -> TickData | None:
        source = self._get_source()
        if source is None:
            return None
        data = await source.fetch_realtime(symbol, market)
        if data is None:
            return None
        return TickData(
            symbol=data.get("symbol", symbol),
            market=data.get("market", market),
            name=data.get("name", ""),
            price=data.get("price", 0),
            last_close=data.get("last_close", 0),
            open=data.get("open", 0),
            high=data.get("high", 0),
            low=data.get("low", 0),
            volume=data.get("volume", 0),
            amount=data.get("amount", 0),
            change=data.get("change", 0),
            change_pct=data.get("change_pct", 0),
            turnover_rate=data.get("turnover_rate", 0),
            total_market_cap=data.get("total_market_cap", 0),
            float_market_cap=data.get("float_market_cap", 0),
            timestamp=data.get("timestamp", 0),
        )

    async def fetch_bars(
        self,
        symbol: str,
        market: str,
        kline_type: str = "daily",
        adjust: str = "",
        count: int = 300,
    ) -> pd.DataFrame | None:
        source = self._get_source()
        if source is None:
            return None
        ktype_map = {"daily": "101", "weekly": "102", "monthly": "103"}
        fqt_map = {"": 0, "qfq": 1, "hfq": 2}
        return await source.fetch_history_em(
            symbol, market,
            ktype_map.get(kline_type, "101"),
            fqt_map.get(adjust, 1),
        )


class _TencentGateway(BaseGateway):
    gateway_name = "tencent"
    _source = None

    def __init__(self, event_bus: EventBus | None = None):
        super().__init__(event_bus)

    @classmethod
    def _get_source(cls):
        if cls._source is None:
            try:
                from core.data_fetcher import TencentSource
                cls._source = TencentSource
            except ImportError:
                logger.warning("TencentSource not available")
        return cls._source

    async def fetch_tick(self, symbol: str, market: str) -> TickData | None:
        source = self._get_source()
        if source is None:
            return None
        data = await source.fetch_realtime(symbol, market)
        if data is None:
            return None
        return TickData(
            symbol=data.get("symbol", symbol),
            market=data.get("market", market),
            name=data.get("name", ""),
            price=data.get("price", 0),
            last_close=data.get("last_close", 0),
            open=data.get("open", 0),
            high=data.get("high", 0),
            low=data.get("low", 0),
            volume=data.get("volume", 0),
            amount=data.get("amount", 0),
            change=data.get("change", 0),
            change_pct=data.get("change_pct", 0),
            turnover_rate=data.get("turnover_rate", 0),
            timestamp=data.get("timestamp", 0),
        )

    async def fetch_bars(
        self,
        symbol: str,
        market: str,
        kline_type: str = "daily",
        adjust: str = "",
        count: int = 300,
    ) -> pd.DataFrame | None:
        source = self._get_source()
        if source is None:
            return None
        return await source.fetch_history(symbol, market, kline_type, adjust, count)

    async def fetch_ticks_batch(self, symbols: list[tuple[str, str]]) -> dict[str, TickData]:
        source = self._get_source()
        if source is None:
            return {}
        codes = [source._build_code(s, m) for s, m in symbols]
        batch_data = await source.fetch_batch_realtime(codes)
        code_to_symbol = {source._build_code(s, m): (s, m) for s, m in symbols}
        results: dict[str, TickData] = {}
        for code_key, data in batch_data.items():
            if code_key in code_to_symbol:
                sym, mkt = code_to_symbol[code_key]
                results[sym] = TickData(
                    symbol=sym,
                    market=mkt,
                    name=data.get("name", ""),
                    price=data.get("price", 0),
                    last_close=data.get("last_close", 0),
                    open=data.get("open", 0),
                    high=data.get("high", 0),
                    low=data.get("low", 0),
                    volume=data.get("volume", 0),
                    amount=data.get("amount", 0),
                    change_pct=data.get("change_pct", 0),
                    change=data.get("change", 0),
                    turnover_rate=data.get("turnover_rate", 0),
                )
        return results


class _SinaGateway(BaseGateway):
    gateway_name = "sina"
    _source = None

    def __init__(self, event_bus: EventBus | None = None):
        super().__init__(event_bus)

    @classmethod
    def _get_source(cls):
        if cls._source is None:
            try:
                from core.data_fetcher import SinaSource
                cls._source = SinaSource
            except ImportError:
                logger.warning("SinaSource not available")
        return cls._source

    async def fetch_tick(self, symbol: str, market: str) -> TickData | None:
        source = self._get_source()
        if source is None:
            return None
        data = await source.fetch_realtime(symbol, market)
        if data is None:
            return None
        return TickData(
            symbol=data.get("symbol", symbol),
            market=data.get("market", market),
            name=data.get("name", ""),
            price=data.get("price", 0),
            last_close=data.get("last_close", 0),
            open=data.get("open", 0),
            high=data.get("high", 0),
            low=data.get("low", 0),
            volume=data.get("volume", 0),
            amount=data.get("amount", 0),
            change=data.get("change", 0),
            change_pct=data.get("change_pct", 0),
            turnover_rate=data.get("turnover_rate", 0),
            timestamp=data.get("timestamp", 0),
        )

    async def fetch_bars(
        self,
        symbol: str,
        market: str,
        kline_type: str = "daily",
        adjust: str = "",
        count: int = 300,
    ) -> pd.DataFrame | None:
        return None


class _AKShareGateway(BaseGateway):
    gateway_name = "akshare"
    _source = None

    def __init__(self, event_bus: EventBus | None = None):
        super().__init__(event_bus)

    @classmethod
    def _get_source(cls):
        if cls._source is None:
            try:
                from core.data_fetcher import AKShareSource
                cls._source = AKShareSource
            except ImportError:
                logger.warning("AKShareSource not available")
        return cls._source

    async def fetch_tick(self, symbol: str, market: str) -> TickData | None:
        return None

    async def fetch_bars(
        self,
        symbol: str,
        market: str,
        kline_type: str = "daily",
        adjust: str = "",
        count: int = 300,
    ) -> pd.DataFrame | None:
        source = self._get_source()
        if source is None:
            return None
        return await source.fetch_history(symbol, market, kline_type, adjust)


class _BaoStockGateway(BaseGateway):
    gateway_name = "baostock"
    _source = None

    def __init__(self, event_bus: EventBus | None = None):
        super().__init__(event_bus)

    @classmethod
    def _get_source(cls):
        if cls._source is None:
            try:
                from core.data_fetcher import BaoStockSource
                cls._source = BaoStockSource
            except ImportError:
                logger.warning("BaoStockSource not available")
        return cls._source

    async def fetch_tick(self, symbol: str, market: str) -> TickData | None:
        return None

    async def fetch_bars(
        self,
        symbol: str,
        market: str,
        kline_type: str = "daily",
        adjust: str = "",
        count: int = 300,
    ) -> pd.DataFrame | None:
        source = self._get_source()
        if source is None:
            return None
        return await source.fetch_history(symbol, market, kline_type, adjust)


class GatewayManager:
    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus or get_event_bus()
        self._gateways: dict[str, BaseGateway] = {}
        self._tick_priority: list[str] = []
        self._bar_priority: list[str] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        gateways = [
            _EastMoneyGateway(self._event_bus),
            _TencentGateway(self._event_bus),
            _SinaGateway(self._event_bus),
            _AKShareGateway(self._event_bus),
            _BaoStockGateway(self._event_bus),
        ]
        for gw in gateways:
            self._gateways[gw.name] = gw
        self._tick_priority = ["eastmoney", "tencent", "sina"]
        self._bar_priority = ["eastmoney", "tencent", "akshare", "baostock"]

    def register(self, gateway: BaseGateway) -> None:
        self._gateways[gateway.name] = gateway

    def set_tick_priority(self, order: list[str]) -> None:
        self._tick_priority = [n for n in order if n in self._gateways]

    def set_bar_priority(self, order: list[str]) -> None:
        self._bar_priority = [n for n in order if n in self._gateways]

    async def fetch_tick(self, symbol: str, market: str) -> TickData | None:
        for name in self._tick_priority:
            gw = self._gateways.get(name)
            if gw is None:
                continue
            try:
                tick = await gw.fetch_tick(symbol, market)
                if tick is not None and tick.price > 0:
                    return tick
            except Exception as e:
                logger.debug("Gateway %s tick error for %s: %s", name, symbol, e)
        return None

    async def fetch_ticks_batch(self, symbols: list[tuple[str, str]]) -> dict[str, TickData]:
        results: dict[str, TickData] = {}
        a_symbols = [(s, m) for s, m in symbols if m == "A"]
        other_symbols = [(s, m) for s, m in symbols if m != "A"]

        if a_symbols and "tencent" in self._gateways:
            gw = self._gateways["tencent"]
            batch_results = await gw.fetch_ticks_batch(a_symbols)
            results.update(batch_results)

        missing_a = [(s, m) for s, m in a_symbols if s not in results]
        all_missing = missing_a + other_symbols

        if all_missing:
            for symbol, market in all_missing:
                tick = await self.fetch_tick(symbol, market)
                if tick is not None:
                    results[symbol] = tick

        return results

    async def fetch_bars(
        self,
        symbol: str,
        market: str,
        kline_type: str = "daily",
        adjust: str = "",
        count: int = 300,
    ) -> pd.DataFrame | None:
        for name in self._bar_priority:
            gw = self._gateways.get(name)
            if gw is None:
                continue
            try:
                bars = await gw.fetch_bars(symbol, market, kline_type, adjust, count)
                if bars is not None and not bars.empty:
                    return bars
            except Exception as e:
                logger.debug("Gateway %s bars error for %s: %s", name, symbol, e)
        return None

    async def fetch_bars_batch(
        self,
        symbols: list[tuple[str, str]],
        kline_type: str = "daily",
        adjust: str = "",
        count: int = 300,
    ) -> dict[str, pd.DataFrame]:
        results: dict[str, pd.DataFrame] = {}
        for symbol, market in symbols:
            bars = await self.fetch_bars(symbol, market, kline_type, adjust, count)
            if bars is not None and not bars.empty:
                results[symbol] = bars
        return results

    def get_gateway(self, name: str) -> BaseGateway | None:
        return self._gateways.get(name)

    def list_gateways(self) -> list[str]:
        return list(self._gateways.keys())
