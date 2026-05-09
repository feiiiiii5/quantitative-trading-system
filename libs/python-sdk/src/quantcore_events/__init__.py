from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

BROKER_URL = "redpanda:9092"


class EventType(str, Enum):
    MARKET_DATA = "market_data"
    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_REJECTED = "order_rejected"
    RISK_ALERT = "risk_alert"
    RISK_CHECK_PASSED = "risk_check_passed"
    RISK_CHECK_FAILED = "risk_check_failed"
    STRATEGY_DEPLOYED = "strategy_deployed"
    STRATEGY_STOPPED = "strategy_stopped"
    STRATEGY_SIGNAL = "strategy_signal"
    PORTFOLIO_UPDATED = "portfolio_updated"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    BACKTEST_STARTED = "backtest_started"
    BACKTEST_COMPLETED = "backtest_completed"


@dataclass(frozen=True)
class Event:
    event_type: EventType
    aggregate_id: str
    payload: dict[str, Any]
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp_ns: int = field(default_factory=lambda: int(time.time() * 1e9))
    correlation_id: str = ""
    causation_id: str = ""
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "aggregate_id": self.aggregate_id,
            "payload": self.payload,
            "event_id": self.event_id,
            "timestamp_ns": self.timestamp_ns,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        return cls(
            event_type=EventType(data["event_type"]),
            aggregate_id=data["aggregate_id"],
            payload=data["payload"],
            event_id=data.get("event_id", ""),
            timestamp_ns=data.get("timestamp_ns", 0),
            correlation_id=data.get("correlation_id", ""),
            causation_id=data.get("causation_id", ""),
            version=data.get("version", 1),
        )

    def to_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), default=str).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> Event:
        return cls.from_dict(json.loads(data.decode("utf-8")))


EventHandler = Callable[[Event], None]


class EventBus:
    def __init__(self, broker_url: str = BROKER_URL) -> None:
        self._broker_url = broker_url
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._producer: Any = None
        self._consumer: Any = None
        self._running = False

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h is not handler
            ]

    async def publish(self, event: Event) -> None:
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                result = handler(event)
                if hasattr(result, "__await__"):
                    await result
            except Exception as e:
                logger.error(
                    "Event handler error: %s for event %s",
                    e,
                    event.event_type.value,
                    exc_info=True,
                )

        if self._producer is not None:
            try:
                await self._producer.send_and_wait(
                    topic=_event_type_to_topic(event.event_type),
                    value=event.to_bytes(),
                    key=event.aggregate_id.encode("utf-8"),
                )
            except Exception as e:
                logger.error("Kafka publish error: %s", e, exc_info=True)

    async def start_consumer(self, group_id: str, event_types: list[EventType]) -> None:
        try:
            from aiokafka import AIOKafkaConsumer
        except ImportError:
            logger.warning("aiokafka not installed, Kafka consumer disabled")
            return

        topics = [_event_type_to_topic(et) for et in event_types]
        self._consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=self._broker_url,
            group_id=group_id,
            value_deserializer=lambda m: Event.from_bytes(m),
            key_deserializer=lambda m: m.decode("utf-8") if m else None,
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )
        await self._consumer.start()
        self._running = True
        logger.info("Kafka consumer started: topics=%s group=%s", topics, group_id)

        try:
            async for msg in self._consumer:
                if not self._running:
                    break
                event = msg.value
                handlers = self._handlers.get(event.event_type, [])
                for handler in handlers:
                    try:
                        result = handler(event)
                        if hasattr(result, "__await__"):
                            await result
                    except Exception as e:
                        logger.error("Consumer handler error: %s", e, exc_info=True)
        finally:
            await self._consumer.stop()

    async def start_producer(self) -> None:
        try:
            from aiokafka import AIOKafkaProducer
        except ImportError:
            logger.warning("aiokafka not installed, Kafka producer disabled")
            return

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._broker_url,
            value_serializer=lambda v: v,
            key_serializer=lambda k: k.encode("utf-8") if isinstance(k, str) else k,
        )
        await self._producer.start()
        logger.info("Kafka producer started: %s", self._broker_url)

    async def stop(self) -> None:
        self._running = False
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None
        logger.info("EventBus stopped")


class CommandBus:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._command_handlers: dict[str, Callable] = {}

    def register(self, command_type: str, handler: Callable) -> None:
        self._command_handlers[command_type] = handler

    async def dispatch(self, command_type: str, payload: dict[str, Any]) -> Any:
        handler = self._command_handlers.get(command_type)
        if handler is None:
            raise ValueError(f"No handler registered for command: {command_type}")
        result = handler(payload)
        if hasattr(result, "__await__"):
            result = await result
        return result


class QueryBus:
    def __init__(self) -> None:
        self._query_handlers: dict[str, Callable] = {}

    def register(self, query_type: str, handler: Callable) -> None:
        self._query_handlers[query_type] = handler

    async def execute(self, query_type: str, params: dict[str, Any]) -> Any:
        handler = self._query_handlers.get(query_type)
        if handler is None:
            raise ValueError(f"No handler registered for query: {query_type}")
        result = handler(params)
        if hasattr(result, "__await__"):
            result = await result
        return result


class EventStore:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._events: list[Event] = []
        self._by_aggregate: dict[str, list[Event]] = {}

    async def append(self, event: Event) -> None:
        self._events.append(event)
        if event.aggregate_id not in self._by_aggregate:
            self._by_aggregate[event.aggregate_id] = []
        self._by_aggregate[event.aggregate_id].append(event)
        await self._event_bus.publish(event)

    def get_events(self, aggregate_id: str) -> list[Event]:
        return self._by_aggregate.get(aggregate_id, [])

    def get_events_since(self, timestamp_ns: int) -> list[Event]:
        return [e for e in self._events if e.timestamp_ns >= timestamp_ns]


def _event_type_to_topic(event_type: EventType) -> str:
    return f"quantcore.{event_type.value}"


__all__ = [
    "Event",
    "EventType",
    "EventBus",
    "CommandBus",
    "QueryBus",
    "EventStore",
    "EventHandler",
    "BROKER_URL",
]
