import time

from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.models import CityEndpoint, CityIdentity, CityPresence, HealthStatus, TrustLevel, TrustRecord
from agent_internet.transport import DeliveryEnvelope, DeliveryStatus, LoopbackTransport, TransportScheme


def _build_plane() -> AgentInternetControlPlane:
    plane = AgentInternetControlPlane()
    plane.register_city(
        CityIdentity(city_id="city-a", slug="city-a", repo="org/city-a"),
        CityEndpoint(city_id="city-a", transport=TransportScheme.LOOPBACK.value, location="loop://city-a"),
    )
    plane.register_city(
        CityIdentity(city_id="city-b", slug="city-b", repo="org/city-b"),
        CityEndpoint(city_id="city-b", transport=TransportScheme.LOOPBACK.value, location="loop://city-b"),
    )
    plane.announce_city(CityPresence(city_id="city-a", health=HealthStatus.HEALTHY))
    plane.announce_city(CityPresence(city_id="city-b", health=HealthStatus.HEALTHY))
    plane.record_trust(TrustRecord("city-a", "city-b", TrustLevel.OBSERVED, reason="local test"))
    plane.register_transport(TransportScheme.LOOPBACK.value, LoopbackTransport())
    return plane


def test_relay_delivers_routable_envelope():
    plane = _build_plane()

    receipt = plane.relay_envelope(
        DeliveryEnvelope(
            source_city_id="city-a",
            target_city_id="city-b",
            operation="city_report",
            payload={"heartbeat": 1},
        ),
    )

    assert receipt.status == DeliveryStatus.DELIVERED
    transport = plane.transports.get(TransportScheme.LOOPBACK.value)
    received = transport.receive("city-b")
    assert len(received) == 1
    assert received[0].operation == "city_report"
    assert received[0].payload == {"heartbeat": 1}


def test_relay_rejects_unregistered_transport_scheme():
    plane = AgentInternetControlPlane()
    plane.register_city(
        CityIdentity(city_id="city-a", slug="city-a", repo="org/city-a"),
        CityEndpoint(city_id="city-a", transport="unknown", location="x"),
    )
    plane.register_city(
        CityIdentity(city_id="city-b", slug="city-b", repo="org/city-b"),
        CityEndpoint(city_id="city-b", transport="unknown", location="y"),
    )
    plane.announce_city(CityPresence(city_id="city-b", health=HealthStatus.HEALTHY))
    plane.record_trust(TrustRecord("city-a", "city-b", TrustLevel.OBSERVED, reason="local test"))

    receipt = plane.relay_envelope(
        DeliveryEnvelope(source_city_id="city-a", target_city_id="city-b", operation="sync", payload={}),
    )

    assert receipt.status == DeliveryStatus.REJECTED


def test_relay_marks_expired_envelope_before_delivery():
    plane = _build_plane()
    envelope = DeliveryEnvelope(
        source_city_id="city-a",
        target_city_id="city-b",
        operation="sync",
        payload={},
        created_at=time.time() - 10,
        ttl_s=0.1,
    )

    receipt = plane.relay_envelope(envelope)

    assert receipt.status == DeliveryStatus.EXPIRED


def test_relay_blocks_untrusted_or_offline_routes():
    plane = AgentInternetControlPlane()
    plane.register_city(
        CityIdentity(city_id="city-a", slug="city-a", repo="org/city-a"),
        CityEndpoint(city_id="city-a", transport=TransportScheme.LOOPBACK.value, location="loop://city-a"),
    )
    plane.register_city(
        CityIdentity(city_id="city-b", slug="city-b", repo="org/city-b"),
        CityEndpoint(city_id="city-b", transport=TransportScheme.LOOPBACK.value, location="loop://city-b"),
    )
    plane.announce_city(CityPresence(city_id="city-b", health=HealthStatus.OFFLINE))
    plane.register_transport(TransportScheme.LOOPBACK.value, LoopbackTransport())

    receipt = plane.relay_envelope(
        DeliveryEnvelope(source_city_id="city-a", target_city_id="city-b", operation="sync", payload={}),
    )

    assert receipt.status == DeliveryStatus.UNROUTABLE
