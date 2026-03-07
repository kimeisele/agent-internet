import time

from agent_internet.filesystem_message_transport import AgentCityFilesystemMessageTransport
from agent_internet.models import CityEndpoint
from agent_internet.transport import DeliveryEnvelope, DeliveryStatus, TransportScheme


def test_filesystem_message_transport_delivers_to_agent_city_inbox(tmp_path):
    target_root = tmp_path / "city-b"
    target_root.mkdir()
    endpoint = CityEndpoint(city_id="city-b", transport=TransportScheme.FILESYSTEM.value, location=str(target_root))
    transport = AgentCityFilesystemMessageTransport()

    receipt = transport.send(
        endpoint,
        DeliveryEnvelope(
            source_city_id="city-a",
            target_city_id="city-b",
            operation="sync",
            payload={"heartbeat": 3},
            correlation_id="corr-1",
        ),
    )

    assert receipt.status == DeliveryStatus.DELIVERED
    received = transport.receive(target_root)
    assert len(received) == 1
    assert received[0].source_city_id == "city-a"
    assert received[0].payload == {"heartbeat": 3}
    assert received[0].correlation_id == "corr-1"
    assert received[0].envelope_id
    assert received[0].nadi_type == "vyana"
    assert received[0].nadi_op == "send"
    assert received[0].priority == "rajas"
    assert received[0].ttl_ms == 24000
    assert received[0].maha_header_hex


def test_filesystem_message_transport_rejects_missing_target_root(tmp_path):
    endpoint = CityEndpoint(
        city_id="city-b",
        transport=TransportScheme.FILESYSTEM.value,
        location=str(tmp_path / "missing-city"),
    )

    receipt = AgentCityFilesystemMessageTransport().send(
        endpoint,
        DeliveryEnvelope(source_city_id="city-a", target_city_id="city-b", operation="sync", payload={}),
    )

    assert receipt.status == DeliveryStatus.REJECTED


def test_filesystem_message_transport_marks_expired_envelope(tmp_path):
    target_root = tmp_path / "city-b"
    target_root.mkdir()
    endpoint = CityEndpoint(city_id="city-b", transport=TransportScheme.FILESYSTEM.value, location=str(target_root))

    receipt = AgentCityFilesystemMessageTransport().send(
        endpoint,
        DeliveryEnvelope(
            source_city_id="city-a",
            target_city_id="city-b",
            operation="sync",
            payload={},
            created_at=time.time() - 10,
            ttl_s=0.1,
        ),
    )

    assert receipt.status == DeliveryStatus.EXPIRED


def test_filesystem_message_transport_dedupes_by_envelope_id(tmp_path):
    target_root = tmp_path / "city-b"
    target_root.mkdir()
    endpoint = CityEndpoint(city_id="city-b", transport=TransportScheme.FILESYSTEM.value, location=str(target_root))
    transport = AgentCityFilesystemMessageTransport()
    envelope = DeliveryEnvelope(
        source_city_id="city-a",
        target_city_id="city-b",
        operation="sync",
        payload={"heartbeat": 3},
        envelope_id="env-fixed",
    )

    first = transport.send(endpoint, envelope)
    second = transport.send(endpoint, envelope)

    assert first.status == DeliveryStatus.DELIVERED
    assert second.status == DeliveryStatus.DUPLICATE
    assert len(transport.receive(target_root)) == 1


def test_filesystem_message_transport_preserves_explicit_nadi_metadata(tmp_path):
    target_root = tmp_path / "city-b"
    target_root.mkdir()
    endpoint = CityEndpoint(city_id="city-b", transport=TransportScheme.FILESYSTEM.value, location=str(target_root))
    transport = AgentCityFilesystemMessageTransport()

    receipt = transport.send(
        endpoint,
        DeliveryEnvelope(
            source_city_id="city-a",
            target_city_id="city-b",
            operation="sync_request",
            payload={"heartbeat": 3},
            nadi_type="udana",
            nadi_op="delegate",
            priority="suddha",
            ttl_ms=48000,
            maha_header_hex="deadbeef",
        ),
    )

    assert receipt.status == DeliveryStatus.DELIVERED
    received = transport.receive(target_root)
    assert received[0].nadi_type == "udana"
    assert received[0].nadi_op == "delegate"
    assert received[0].priority == "suddha"
    assert received[0].ttl_ms == 48000
    assert received[0].maha_header_hex == "deadbeef"
