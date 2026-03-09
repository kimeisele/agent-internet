from __future__ import annotations

import json
import time

from agent_internet.https_transport import (
    HttpsTransport,
    HttpsTransportConfig,
    _envelope_from_wire,
    _envelope_to_wire,
)
from agent_internet.models import CityEndpoint
from agent_internet.transport import DeliveryEnvelope, DeliveryStatus


def test_envelope_roundtrip():
    envelope = DeliveryEnvelope(
        source_city_id="alpha",
        target_city_id="beta",
        operation="ping",
        payload={"msg": "hello"},
        nadi_type="vyana",
    )
    wire = _envelope_to_wire(envelope)
    restored = _envelope_from_wire(wire)
    assert restored.source_city_id == "alpha"
    assert restored.target_city_id == "beta"
    assert restored.operation == "ping"
    assert restored.payload == {"msg": "hello"}


def test_expired_envelope_rejected():
    transport = HttpsTransport()
    endpoint = CityEndpoint(city_id="beta", transport="https", location="https://example.com/inbox")
    envelope = DeliveryEnvelope(
        source_city_id="alpha",
        target_city_id="beta",
        operation="ping",
        payload={},
        created_at=time.time() - 100000,
        ttl_s=1.0,
    )
    receipt = transport.send(endpoint, envelope)
    assert receipt.status == DeliveryStatus.EXPIRED


def test_oversized_payload_rejected():
    config = HttpsTransportConfig(max_payload_bytes=10)
    transport = HttpsTransport(config=config)
    endpoint = CityEndpoint(city_id="beta", transport="https", location="https://example.com/inbox")
    envelope = DeliveryEnvelope(
        source_city_id="alpha",
        target_city_id="beta",
        operation="ping",
        payload={"data": "x" * 100},
    )
    receipt = transport.send(endpoint, envelope)
    assert receipt.status == DeliveryStatus.REJECTED
    assert "max size" in receipt.detail


def test_delivery_log():
    transport = HttpsTransport()
    endpoint = CityEndpoint(city_id="beta", transport="https", location="https://example.com/inbox")
    envelope = DeliveryEnvelope(
        source_city_id="alpha",
        target_city_id="beta",
        operation="ping",
        payload={},
        created_at=time.time() - 100000,
        ttl_s=1.0,
    )
    transport.send(endpoint, envelope)
    log = transport.delivery_log()
    assert len(log) == 1


def test_receive_from_wire():
    transport = HttpsTransport()
    wire = json.dumps({
        "source_city_id": "alpha",
        "target_city_id": "beta",
        "operation": "data",
        "payload": {"key": "value"},
    })
    envelope = transport.receive_from_wire(wire)
    assert envelope.source_city_id == "alpha"
    assert envelope.payload == {"key": "value"}
