import pytest

from core.event_bus import Event, EventBus, EventType, get_event_bus, reset_event_bus


class TestEvent:

    def test_event_creation(self):
        event = Event(event_type=EventType.ORDER_FILLED, data={"symbol": "AAPL"})
        assert event.event_type == EventType.ORDER_FILLED
        assert event.data["symbol"] == "AAPL"
        assert event.timestamp > 0
        assert len(event.event_id) == 12

    def test_event_auto_id(self):
        e1 = Event(event_type=EventType.SYSTEM_ERROR)
        e2 = Event(event_type=EventType.SYSTEM_ERROR)
        assert e1.event_id != e2.event_id

    def test_event_custom_source(self):
        event = Event(event_type=EventType.STRATEGY_SIGNAL, source="MACDStrategy")
        assert event.source == "MACDStrategy"

    def test_event_default_data(self):
        event = Event(event_type=EventType.CACHE_INVALIDATED)
        assert event.data == {}

    def test_event_payload_alias(self):
        event = Event(event_type=EventType.ORDER_FILLED, data={"price": 10.0})
        assert event.payload["price"] == 10.0
        event.payload = {"price": 11.0}
        assert event.data["price"] == 11.0


class TestEventBus:

    def test_subscribe_and_publish_sync(self):
        bus = EventBus()
        received = []
        bus.subscribe(EventType.ORDER_FILLED, lambda e: received.append(e))

        event = Event(event_type=EventType.ORDER_FILLED, data={"price": 150.0})
        bus.publish(event)

        assert len(received) == 1
        assert received[0].data["price"] == 150.0

    def test_multiple_sync_handlers(self):
        bus = EventBus()
        results_a = []
        results_b = []
        bus.subscribe(EventType.POSITION_OPENED, lambda e: results_a.append(e))
        bus.subscribe(EventType.POSITION_OPENED, lambda e: results_b.append(e))

        bus.publish(Event(event_type=EventType.POSITION_OPENED))
        assert len(results_a) == 1
        assert len(results_b) == 1

    def test_handler_priority(self):
        bus = EventBus()
        order = []
        bus.subscribe(EventType.ON_BAR, lambda e: order.append("low"), priority=10)
        bus.subscribe(EventType.ON_BAR, lambda e: order.append("high"), priority=1)
        bus.publish(Event(event_type=EventType.ON_BAR))
        assert order == ["high", "low"]

    def test_subscribe_once(self):
        bus = EventBus()
        count = [0]
        bus.subscribe_once(EventType.ON_TICK, lambda e: count.__setitem__(0, count[0] + 1))
        bus.publish(Event(event_type=EventType.ON_TICK))
        bus.publish(Event(event_type=EventType.ON_TICK))
        assert count[0] == 1

    def test_unsubscribe(self):
        bus = EventBus()
        received = []

        def handler(e):
            received.append(e)

        bus.subscribe(EventType.RISK_LIMIT_BREACHED, handler)
        bus.publish(Event(event_type=EventType.RISK_LIMIT_BREACHED))
        assert len(received) == 1

        bus.unsubscribe(EventType.RISK_LIMIT_BREACHED, handler)
        bus.publish(Event(event_type=EventType.RISK_LIMIT_BREACHED))
        assert len(received) == 1

    def test_unsubscribe_nonexistent(self):
        bus = EventBus()
        result = bus.unsubscribe(EventType.SYSTEM_ERROR, lambda e: None)
        assert result is False

    def test_wildcard_handler(self):
        bus = EventBus()
        all_events = []
        bus.subscribe_all(lambda e: all_events.append(e))

        bus.publish(Event(event_type=EventType.ORDER_FILLED))
        bus.publish(Event(event_type=EventType.SYSTEM_ERROR))

        assert len(all_events) == 2

    def test_handler_error_doesnt_crash(self):
        bus = EventBus()
        def bad_handler(e):
            raise ValueError("test error")

        bus.subscribe(EventType.SYSTEM_ERROR, bad_handler)
        bus.subscribe(EventType.SYSTEM_ERROR, lambda e: None)

        bus.publish(Event(event_type=EventType.SYSTEM_ERROR))

    def test_disabled_bus(self):
        bus = EventBus()
        received = []
        bus.subscribe(EventType.ORDER_FILLED, lambda e: received.append(e))
        bus.enabled = False

        bus.publish(Event(event_type=EventType.ORDER_FILLED))
        assert len(received) == 0

        bus.enabled = True
        bus.publish(Event(event_type=EventType.ORDER_FILLED))
        assert len(received) == 1

    def test_history(self):
        bus = EventBus()
        bus.publish(Event(event_type=EventType.ORDER_FILLED))
        bus.publish(Event(event_type=EventType.SYSTEM_ERROR))
        bus.publish(Event(event_type=EventType.ORDER_FILLED))

        history = bus.get_history()
        assert len(history) == 3

        filled = bus.get_history(event_type=EventType.ORDER_FILLED)
        assert len(filled) == 2

    def test_history_limit(self):
        bus = EventBus()
        for i in range(200):
            bus.publish(Event(event_type=EventType.ORDER_FILLED, data={"i": i}))

        history = bus.get_history(limit=10)
        assert len(history) == 10

    def test_history_max(self):
        bus = EventBus(max_history=50)
        for i in range(100):
            bus.publish(Event(event_type=EventType.ORDER_FILLED, data={"i": i}))

        history = bus.get_history()
        assert len(history) == 50

    def test_clear_history(self):
        bus = EventBus()
        bus.publish(Event(event_type=EventType.ORDER_FILLED))
        bus.clear_history()
        assert len(bus.get_history()) == 0

    def test_clear_handlers(self):
        bus = EventBus()
        bus.subscribe(EventType.ORDER_FILLED, lambda e: None)
        bus.subscribe_all(lambda e: None)
        bus.clear_handlers()
        assert bus.handler_count == 0

    def test_handler_count(self):
        bus = EventBus()
        bus.subscribe(EventType.ORDER_FILLED, lambda e: None)
        bus.subscribe(EventType.SYSTEM_ERROR, lambda e: None)
        bus.subscribe_all(lambda e: None)
        assert bus.handler_count == 3

    def test_replay(self):
        bus = EventBus()
        bus.publish(Event(event_type=EventType.ORDER_FILLED, data={"a": 1}))
        bus.publish(Event(event_type=EventType.ORDER_FILLED, data={"a": 2}))

        replayed = []
        count = bus.replay(handler=lambda e: replayed.append(e))
        assert count == 2
        assert len(replayed) == 2

    def test_replay_by_type(self):
        bus = EventBus()
        bus.publish(Event(event_type=EventType.ORDER_FILLED))
        bus.publish(Event(event_type=EventType.SYSTEM_ERROR))

        replayed = []
        count = bus.replay(event_type=EventType.ORDER_FILLED, handler=lambda e: replayed.append(e))
        assert count == 1


class TestEventBusAsync:

    @pytest.mark.asyncio
    async def test_async_publish(self):
        bus = EventBus()
        received = []

        async def async_handler(e: Event):
            received.append(e)

        bus.subscribe(EventType.ORDER_FILLED, async_handler)
        await bus.publish_async(Event(event_type=EventType.ORDER_FILLED, data={"x": 1}))
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_async_wildcard(self):
        bus = EventBus()
        received = []

        async def async_wildcard(e: Event):
            received.append(e)

        bus.subscribe_all(async_wildcard)
        await bus.publish_async(Event(event_type=EventType.ORDER_FILLED))
        await bus.publish_async(Event(event_type=EventType.SYSTEM_ERROR))
        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_async_handler_error_doesnt_crash(self):
        bus = EventBus()

        async def bad_handler(e: Event):
            raise ValueError("async error")

        bus.subscribe(EventType.SYSTEM_ERROR, bad_handler)
        await bus.publish_async(Event(event_type=EventType.SYSTEM_ERROR))


class TestGlobalEventBus:

    def test_get_event_bus(self):
        reset_event_bus()
        bus = get_event_bus()
        assert isinstance(bus, EventBus)

        bus2 = get_event_bus()
        assert bus is bus2

    def test_reset_event_bus(self):
        reset_event_bus()
        bus = get_event_bus()
        bus.subscribe(EventType.ORDER_FILLED, lambda e: None)
        assert bus.handler_count == 1

        reset_event_bus()
        bus2 = get_event_bus()
        assert bus2.handler_count == 0
