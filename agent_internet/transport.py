from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import StrEnum
from secrets import token_hex
from typing import Deque

from .interfaces import InternetRouter
from .models import CityEndpoint


class TransportScheme(StrEnum):
    FILESYSTEM = "filesystem"
    LOOPBACK = "loopback"
    GIT = "git"
    HTTPS = "https"


class DeliveryStatus(StrEnum):
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNROUTABLE = "unroutable"


@dataclass(frozen=True, slots=True)
class DeliveryEnvelope:
    source_city_id: str
    target_city_id: str
    operation: str
    payload: dict
    envelope_id: str = field(default_factory=lambda: f"env_{token_hex(8)}")
    correlation_id: str = ""
    content_type: str = "application/json"
    created_at: float = field(default_factory=time.time)
    ttl_s: float = 300.0

    @property
    def is_expired(self) -> bool:
        return time.time() > self.created_at + self.ttl_s


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    envelope_id: str
    status: DeliveryStatus
    transport: str
    target_city_id: str
    detail: str = ""
    acknowledged_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class TransportRegistry:
    _transports: dict[str, object] = field(default_factory=dict)

    def register(self, scheme: str, transport: object) -> None:
        self._transports[scheme] = transport

    def get(self, scheme: str) -> object | None:
        return self._transports.get(scheme)

    def schemes(self) -> tuple[str, ...]:
        return tuple(sorted(self._transports))


@dataclass(slots=True)
class LoopbackTransport:
    """In-memory transport for local city-to-city relay tests."""

    _queues: dict[str, Deque[DeliveryEnvelope]] = field(default_factory=lambda: defaultdict(deque))
    _receipts: list[DeliveryReceipt] = field(default_factory=list)

    def send(self, endpoint: CityEndpoint, envelope: DeliveryEnvelope) -> DeliveryReceipt:
        if envelope.is_expired:
            receipt = DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.EXPIRED,
                transport=endpoint.transport,
                target_city_id=endpoint.city_id,
                detail="Envelope TTL expired before delivery",
            )
            self._receipts.append(receipt)
            return receipt

        self._queues[endpoint.city_id].append(envelope)
        receipt = DeliveryReceipt(
            envelope_id=envelope.envelope_id,
            status=DeliveryStatus.DELIVERED,
            transport=endpoint.transport,
            target_city_id=endpoint.city_id,
        )
        self._receipts.append(receipt)
        return receipt

    def receive(self, city_id: str, *, limit: int | None = None) -> list[DeliveryEnvelope]:
        queue = self._queues[city_id]
        items: list[DeliveryEnvelope] = []
        remaining = len(queue) if limit is None else max(limit, 0)
        while queue and remaining > 0:
            items.append(queue.popleft())
            remaining -= 1
        return items

    def receipts(self) -> list[DeliveryReceipt]:
        return list(self._receipts)


@dataclass(slots=True)
class RelayService:
    router: InternetRouter
    registry: TransportRegistry

    def relay(self, envelope: DeliveryEnvelope) -> DeliveryReceipt:
        if envelope.is_expired:
            return DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.EXPIRED,
                transport="none",
                target_city_id=envelope.target_city_id,
                detail="Envelope TTL expired before routing",
            )

        endpoint = self.router.resolve(envelope.source_city_id, envelope.target_city_id)
        if endpoint is None:
            return DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.UNROUTABLE,
                transport="none",
                target_city_id=envelope.target_city_id,
                detail="No route available",
            )

        transport = self.registry.get(endpoint.transport)
        if transport is None:
            return DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.REJECTED,
                transport=endpoint.transport,
                target_city_id=envelope.target_city_id,
                detail=f"No transport registered for scheme {endpoint.transport}",
            )

        send = getattr(transport, "send", None)
        if not callable(send):
            raise TypeError(f"Transport for scheme {endpoint.transport} does not implement send()")
        return send(endpoint, envelope)
