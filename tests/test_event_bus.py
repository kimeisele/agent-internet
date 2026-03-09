from __future__ import annotations

import threading

from agent_internet.event_bus import Event, EventBus, EventKind, Subscription


def test_subscribe_and_emit():
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(kinds={EventKind.CITY_REGISTERED}, handler=received.append)

    event = Event(kind=EventKind.CITY_REGISTERED, source_city_id="alpha")
    count = bus.emit(event)

    assert count == 1
    assert len(received) == 1
    assert received[0].source_city_id == "alpha"


def test_wildcard_subscription():
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(handler=received.append)

    bus.emit(Event(kind=EventKind.CITY_REGISTERED))
    bus.emit(Event(kind=EventKind.TRUST_RECORDED))

    assert len(received) == 2


def test_source_filter():
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(
        kinds={EventKind.CITY_PRESENCE_CHANGED},
        source_filter="alpha",
        handler=received.append,
    )

    bus.emit(Event(kind=EventKind.CITY_PRESENCE_CHANGED, source_city_id="alpha"))
    bus.emit(Event(kind=EventKind.CITY_PRESENCE_CHANGED, source_city_id="beta"))

    assert len(received) == 1
    assert received[0].source_city_id == "alpha"


def test_unsubscribe():
    bus = EventBus()
    received: list[Event] = []
    sub = bus.subscribe(handler=received.append)
    assert bus.subscription_count() == 1

    bus.unsubscribe(sub.subscription_id)
    assert bus.subscription_count() == 0

    bus.emit(Event(kind=EventKind.CITY_REGISTERED))
    assert len(received) == 0


def test_dead_letters():
    bus = EventBus()
    bus.emit(Event(kind=EventKind.TRUST_REVOKED))
    dead = bus.dead_letters()
    assert len(dead) == 1
    assert dead[0].kind == EventKind.TRUST_REVOKED


def test_history():
    bus = EventBus()
    bus.subscribe(handler=lambda e: None)
    for i in range(5):
        bus.emit(Event(kind=EventKind.CITY_REGISTERED, source_city_id=f"city-{i}"))

    history = bus.history(limit=3)
    assert len(history) == 3

    filtered = bus.history(kind=EventKind.TRUST_RECORDED)
    assert len(filtered) == 0


def test_emit_many():
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(handler=received.append)

    events = [Event(kind=EventKind.ROUTE_PUBLISHED) for _ in range(3)]
    total = bus.emit_many(events)

    assert total == 3
    assert len(received) == 3


def test_thread_safety():
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(handler=received.append)

    def emit_events():
        for i in range(50):
            bus.emit(Event(kind=EventKind.CITY_REGISTERED, source_city_id=f"t-{i}"))

    threads = [threading.Thread(target=emit_events) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(received) == 200


def test_clear():
    bus = EventBus()
    bus.subscribe(handler=lambda e: None)
    bus.emit(Event(kind=EventKind.CITY_REGISTERED))
    bus.clear()
    assert bus.subscription_count() == 0
    assert len(bus.history()) == 0
    assert len(bus.dead_letters()) == 0
