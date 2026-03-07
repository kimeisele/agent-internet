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
