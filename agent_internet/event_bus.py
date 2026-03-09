"""Reactive event bus for the Agent Internet control plane.

Provides a lightweight publish/subscribe system that enables components to react
to state changes without tight coupling.  The bus supports both synchronous
(in-process) and deferred (queued) dispatch, event filtering by kind and source,
and dead-letter tracking for unhandled events.
"""

from __future__ import annotations

import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import StrEnum
from secrets import token_hex
from typing import Callable, Deque


class EventKind(StrEnum):
    # City lifecycle
    CITY_REGISTERED = "city.registered"
    CITY_DEREGISTERED = "city.deregistered"
    CITY_PRESENCE_CHANGED = "city.presence_changed"
    CITY_HEALTH_CHANGED = "city.health_changed"

    # Trust
    TRUST_RECORDED = "trust.recorded"
    TRUST_REVOKED = "trust.revoked"
    TRUST_EXPIRED = "trust.expired"

    # Transport & routing
    ROUTE_PUBLISHED = "route.published"
    ROUTE_EXPIRED = "route.expired"
    ENVELOPE_RELAYED = "envelope.relayed"
    ENVELOPE_REJECTED = "envelope.rejected"
    ENVELOPE_EXPIRED = "envelope.expired"

    # Endpoints & services
    ENDPOINT_PUBLISHED = "endpoint.published"
    ENDPOINT_EXPIRED = "endpoint.expired"
    SERVICE_PUBLISHED = "service.published"
    SERVICE_EXPIRED = "service.expired"

    # Commons (spaces, slots, intents)
    SPACE_UPSERTED = "space.upserted"
    SLOT_UPSERTED = "slot.upserted"
    INTENT_CREATED = "intent.created"
    INTENT_TRANSITIONED = "intent.transitioned"

    # Federation
    FEDERATION_SYNC_COMPLETED = "federation.sync_completed"
    FEDERATION_PEER_DISCOVERED = "federation.peer_discovered"

    # Discovery
    DISCOVERY_ANNOUNCED = "discovery.announced"
    DISCOVERY_QUERY = "discovery.query"

    # Contract verification
    CONTRACT_VERIFIED = "contract.verified"
    CONTRACT_VIOLATION = "contract.violation"


@dataclass(frozen=True, slots=True)
class Event:
    """An immutable event emitted by the control plane or its components."""

    event_id: str = field(default_factory=lambda: f"evt_{token_hex(8)}")
    kind: EventKind = EventKind.CITY_PRESENCE_CHANGED
    source_city_id: str = ""
    target_city_id: str = ""
    timestamp: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)
    correlation_id: str = ""


EventHandler = Callable[[Event], None]


@dataclass(frozen=True, slots=True)
class Subscription:
    """A registered event subscription."""

    subscription_id: str = field(default_factory=lambda: f"sub_{token_hex(6)}")
    kinds: frozenset[EventKind] = field(default_factory=frozenset)
    source_filter: str = ""
    handler: EventHandler = field(default=lambda e: None)


@dataclass(slots=True)
class EventBus:
    """Thread-safe publish/subscribe event bus.

    Supports synchronous dispatch (handlers called inline during emit) and
    dead-letter tracking for events with no subscribers.
    """

    _subscriptions: dict[str, Subscription] = field(default_factory=dict)
    _kind_index: dict[EventKind, set[str]] = field(
        default_factory=lambda: defaultdict(set),
    )
    _history: Deque[Event] = field(default_factory=lambda: deque(maxlen=1000))
    _dead_letters: Deque[Event] = field(default_factory=lambda: deque(maxlen=500))
    _lock: threading.Lock = field(default_factory=threading.Lock)
    max_history: int = 1000
    max_dead_letters: int = 500

    def __post_init__(self) -> None:
        if self._history.maxlen != self.max_history:
            self._history = deque(self._history, maxlen=self.max_history)
        if self._dead_letters.maxlen != self.max_dead_letters:
            self._dead_letters = deque(self._dead_letters, maxlen=self.max_dead_letters)

    def subscribe(
        self,
        *,
        kinds: frozenset[EventKind] | set[EventKind] | None = None,
        source_filter: str = "",
        handler: EventHandler,
    ) -> Subscription:
        """Register a handler for specific event kinds.

        If *kinds* is ``None`` or empty, the handler receives all events.
        """
        frozen_kinds = frozenset(kinds) if kinds else frozenset()
        sub = Subscription(
            kinds=frozen_kinds,
            source_filter=source_filter,
            handler=handler,
        )
        with self._lock:
            self._subscriptions[sub.subscription_id] = sub
            if frozen_kinds:
                for kind in frozen_kinds:
                    self._kind_index[kind].add(sub.subscription_id)
            else:
                for kind in EventKind:
                    self._kind_index[kind].add(sub.subscription_id)
        return sub

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription.  Returns ``True`` if it existed."""
        with self._lock:
            sub = self._subscriptions.pop(subscription_id, None)
            if sub is None:
                return False
            target_kinds = sub.kinds if sub.kinds else frozenset(EventKind)
            for kind in target_kinds:
                self._kind_index.get(kind, set()).discard(subscription_id)
            return True

    def emit(self, event: Event) -> int:
        """Dispatch *event* to matching subscribers.  Returns handler count."""
        with self._lock:
            self._history.append(event)
            sub_ids = set(self._kind_index.get(event.kind, set()))
            matched: list[Subscription] = []
            for sub_id in sub_ids:
                sub = self._subscriptions.get(sub_id)
                if sub is None:
                    continue
                if sub.source_filter and sub.source_filter != event.source_city_id:
                    continue
                matched.append(sub)

        if not matched:
            with self._lock:
                self._dead_letters.append(event)
            return 0

        for sub in matched:
            try:
                sub.handler(event)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "Event handler %s failed for %s", sub.subscription_id, event.kind,
                )
        return len(matched)

    def emit_many(self, events: list[Event]) -> int:
        """Emit multiple events.  Returns total handler invocations."""
        return sum(self.emit(event) for event in events)

    def history(self, *, limit: int | None = None, kind: EventKind | None = None) -> list[Event]:
        """Return recent events, optionally filtered by kind."""
        with self._lock:
            items = list(self._history)
        if kind is not None:
            items = [e for e in items if e.kind == kind]
        if limit is not None:
            items = items[-limit:]
        return items

    def dead_letters(self, *, limit: int | None = None) -> list[Event]:
        """Return events that had no matching subscribers."""
        with self._lock:
            items = list(self._dead_letters)
        if limit is not None:
            items = items[-limit:]
        return items

    def subscription_count(self) -> int:
        with self._lock:
            return len(self._subscriptions)

    def clear(self) -> None:
        """Remove all subscriptions and history."""
        with self._lock:
            self._subscriptions.clear()
            self._kind_index.clear()
            self._history.clear()
            self._dead_letters.clear()
