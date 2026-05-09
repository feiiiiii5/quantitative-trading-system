__all__ = [
    "EventType",
    "Event",
    "EventBus",
    "BacktestProgressTracker",
    "get_event_bus",
    "reset_event_bus",
]

import asyncio
import contextlib
import logging
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(Enum):
    INIT = "init"
    BEFORE_TRADING = "before_trading"
    ON_BAR = "on_bar"
    AFTER_TRADING = "after_trading"
    ON_TICK = "on_tick"
    ORDER_PENDING_NEW = "order_pending_new"
    ORDER_CREATED = "order_created"
    ORDER_REJECTED = "order_rejected"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_FILLED = "order_filled"
    TRADE_FILLED = "trade_filled"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    POST_SETTLEMENT = "post_settlement"
    RISK_CHECK = "risk_check"
    STOPLOSS_TRIGGERED = "stoploss_triggered"
    TAKEPROFIT_TRIGGERED = "takeprofit_triggered"
    BACKTEST_STARTED = "backtest_started"
    BACKTEST_PROGRESS = "backtest_progress"
    BACKTEST_TRADE = "backtest_trade"
    BACKTEST_COMPLETED = "backtest_completed"
    BACKTEST_ERROR = "backtest_error"
    MARKET_DATA_UPDATED = "market_data_updated"
    PORTFOLIO_REBALANCED = "portfolio_rebalanced"
    RISK_LIMIT_BREACHED = "risk_limit_breached"
    STRATEGY_SIGNAL = "strategy_signal"
    CACHE_INVALIDATED = "cache_invalidated"
    SYSTEM_ERROR = "system_error"
    TIMER = "timer"


@dataclass
class Event:
    event_type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    source: str = ""
    event_id: str = ""

    def __post_init__(self):
        if not self.event_id:
            self.event_id = uuid.uuid4().hex[:12]

    def __repr__(self):
        return f"Event({self.event_type.value}, id={self.event_id})"

    @property
    def payload(self) -> dict[str, Any]:
        return self.data

    @payload.setter
    def payload(self, value: dict[str, Any]) -> None:
        self.data = value


@dataclass
class _HandlerEntry:
    handler: Callable
    priority: int = 0
    is_async: bool = False

    def __lt__(self, other: "_HandlerEntry") -> bool:
        return self.priority < other.priority


class EventBus:
    def __init__(self, max_history: int = 1000):
        self._sync_handlers: dict[EventType, list[_HandlerEntry]] = defaultdict(list)
        self._async_handlers: dict[EventType, list[_HandlerEntry]] = defaultdict(list)
        self._once_sync: dict[EventType, list[_HandlerEntry]] = defaultdict(list)
        self._once_async: dict[EventType, list[_HandlerEntry]] = defaultdict(list)
        self._wildcard_sync: list[_HandlerEntry] = []
        self._wildcard_async: list[_HandlerEntry] = []
        self._history: list[Event] = []
        self._max_history = max_history
        self._enabled = True
        self._lock = threading.Lock()

    def subscribe(
        self,
        event_type: EventType,
        handler: Callable,
        priority: int = 0,
    ) -> None:
        entry = _HandlerEntry(
            handler=handler,
            priority=priority,
            is_async=asyncio.iscoroutinefunction(handler),
        )
        with self._lock:
            if entry.is_async:
                self._async_handlers[event_type].append(entry)
                self._async_handlers[event_type].sort()
            else:
                self._sync_handlers[event_type].append(entry)
                self._sync_handlers[event_type].sort()

    def subscribe_once(
        self,
        event_type: EventType,
        handler: Callable,
        priority: int = 0,
    ) -> None:
        entry = _HandlerEntry(
            handler=handler,
            priority=priority,
            is_async=asyncio.iscoroutinefunction(handler),
        )
        with self._lock:
            if entry.is_async:
                self._once_async[event_type].append(entry)
            else:
                self._once_sync[event_type].append(entry)

    def subscribe_all(self, handler: Callable, priority: int = 0) -> None:
        entry = _HandlerEntry(
            handler=handler,
            priority=priority,
            is_async=asyncio.iscoroutinefunction(handler),
        )
        with self._lock:
            if entry.is_async:
                self._wildcard_async.append(entry)
                self._wildcard_async.sort()
            else:
                self._wildcard_sync.append(entry)
                self._wildcard_sync.sort()

    def unsubscribe(self, event_type: EventType, handler: Callable) -> bool:
        with self._lock:
            for container in (
                self._sync_handlers,
                self._async_handlers,
                self._once_sync,
                self._once_async,
            ):
                entries = container.get(event_type, [])
                for i, entry in enumerate(entries):
                    if entry.handler is handler:
                        entries.pop(i)
                        return True
            return False

    def publish(self, event: Event) -> None:
        if not self._enabled:
            return

        self._record(event)

        with self._lock:
            sync_entries = sorted(self._sync_handlers.get(event.event_type, []))
            once_sync = sorted(self._once_sync.pop(event.event_type, []))
            wildcard_sync = sorted(self._wildcard_sync)

        for entry in sync_entries:
            try:
                entry.handler(event)
            except Exception as e:
                logger.error("Sync handler error for %s: %s", event, e)

        for entry in once_sync:
            try:
                entry.handler(event)
            except Exception as e:
                logger.error("Once sync handler error for %s: %s", event, e)

        for entry in wildcard_sync:
            try:
                entry.handler(event)
            except Exception as e:
                logger.error("Wildcard sync handler error: %s", e)

    async def publish_async(self, event: Event) -> None:
        if not self._enabled:
            return

        self.publish(event)

        with self._lock:
            async_entries = sorted(self._async_handlers.get(event.event_type, []))
            once_async = sorted(self._once_async.pop(event.event_type, []))
            wildcard_async = sorted(self._wildcard_async)

        for entry in async_entries:
            try:
                await entry.handler(event)
            except Exception as e:
                logger.error("Async handler error for %s: %s", event, e)

        for entry in once_async:
            try:
                await entry.handler(event)
            except Exception as e:
                logger.error("Once async handler error for %s: %s", event, e)

        for entry in wildcard_async:
            try:
                await entry.handler(event)
            except Exception as e:
                logger.error("Wildcard async handler error: %s", e)

    def _record(self, event: Event) -> None:
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def get_history(
        self,
        event_type: EventType | None = None,
        limit: int = 100,
    ) -> list[Event]:
        if event_type is None:
            return self._history[-limit:]
        return [e for e in self._history if e.event_type == event_type][-limit:]

    def replay(
        self,
        event_type: EventType | None = None,
        handler: Callable | None = None,
    ) -> int:
        events = self.get_history(event_type, limit=self._max_history)
        count = 0
        for event in events:
            if handler:
                try:
                    handler(event)
                except Exception as e:
                    logger.error("Replay handler error: %s", e)
            else:
                self.publish(event)
            count += 1
        return count

    def clear_history(self) -> None:
        self._history.clear()

    def clear_handlers(self) -> None:
        with self._lock:
            self._sync_handlers.clear()
            self._async_handlers.clear()
            self._once_sync.clear()
            self._once_async.clear()
            self._wildcard_sync.clear()
            self._wildcard_async.clear()

    def clear(self) -> None:
        self.clear_handlers()
        self.clear_history()

    @property
    def handler_count(self) -> int:
        total = sum(len(v) for v in self._sync_handlers.values())
        total += sum(len(v) for v in self._async_handlers.values())
        total += sum(len(v) for v in self._once_sync.values())
        total += sum(len(v) for v in self._once_async.values())
        total += len(self._wildcard_sync) + len(self._wildcard_async)
        return total

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value


_global_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus


def reset_event_bus() -> None:
    global _global_bus
    if _global_bus is not None:
        _global_bus.clear()
    _global_bus = None


class BacktestProgressTracker:
    def __init__(self, event_bus: EventBus | None = None):
        self._event_bus = event_bus
        self._total_bars = 0
        self._current_bar = 0
        self._trades: list[dict] = []
        self._equity_snapshots: list[dict] = []
        self._start_time: float | None = None
        self._strategy_name = ""

    def start(self, strategy_name: str, total_bars: int) -> None:
        self._strategy_name = strategy_name
        self._total_bars = total_bars
        self._current_bar = 0
        self._trades = []
        self._equity_snapshots = []
        self._start_time = time.monotonic()
        if self._event_bus:
            self._event_bus.publish(Event(EventType.BACKTEST_STARTED, {
                "strategy": strategy_name,
                "total_bars": total_bars,
            }))

    def on_bar(self, bar_index: int, equity: float, date_str: str = "") -> None:
        self._current_bar = bar_index
        if self._total_bars > 0 and bar_index % max(1, self._total_bars // 20) == 0:
            progress = bar_index / self._total_bars
            self._equity_snapshots.append({"date": date_str, "equity": round(equity, 2)})
            if self._event_bus:
                self._event_bus.publish(Event(EventType.BACKTEST_PROGRESS, {
                    "strategy": self._strategy_name,
                    "progress": round(progress, 4),
                    "bar": bar_index,
                    "total": self._total_bars,
                    "equity": round(equity, 2),
                    "date": date_str,
                    "elapsed_seconds": round(time.monotonic() - self._start_time, 2) if self._start_time else 0,
                }))

    def on_trade(self, action: str, price: float, shares: int, date_str: str = "") -> None:
        self._trades.append({"action": action, "price": price, "shares": shares, "date": date_str})
        if self._event_bus:
            self._event_bus.publish(Event(EventType.BACKTEST_TRADE, {
                "strategy": self._strategy_name,
                "action": action,
                "price": price,
                "shares": shares,
                "date": date_str,
                "trade_number": len(self._trades),
            }))

    def complete(self, result_summary: dict) -> None:
        if self._event_bus:
            elapsed = round(time.monotonic() - self._start_time, 2) if self._start_time else 0
            self._event_bus.publish(Event(EventType.BACKTEST_COMPLETED, {
                "strategy": self._strategy_name,
                "elapsed_seconds": elapsed,
                "total_trades": len(self._trades),
                "result": result_summary,
            }))

    def error(self, error_msg: str) -> None:
        if self._event_bus:
            self._event_bus.publish(Event(EventType.BACKTEST_ERROR, {
                "strategy": self._strategy_name,
                "error": error_msg,
            }))

    @property
    def progress(self) -> float:
        return self._current_bar / self._total_bars if self._total_bars > 0 else 0.0

    @property
    def trades(self) -> list:
        return self._trades

    @property
    def equity_snapshots(self) -> list:
        return self._equity_snapshots
