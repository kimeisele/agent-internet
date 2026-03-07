from pathlib import Path

from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.models import CityEndpoint, CityIdentity, CityPresence, EndpointVisibility, HealthStatus, TrustLevel, TrustRecord
from agent_internet.snapshot import ControlPlaneStateStore, restore_control_plane, snapshot_control_plane


def _build_plane() -> AgentInternetControlPlane:
    plane = AgentInternetControlPlane(minimum_trust=TrustLevel.VERIFIED)
    plane.register_city(
        CityIdentity(city_id="city-b", slug="b", repo="org/city-b", public_key="pk"),
        CityEndpoint(city_id="city-b", transport="git", location="https://example/city-b.git"),
    )
    plane.announce_city(
        CityPresence(city_id="city-b", health=HealthStatus.HEALTHY, last_seen_at=42.0, heartbeat=7),
    )
    plane.record_trust(TrustRecord("city-a", "city-b", TrustLevel.TRUSTED, reason="treaty"))
    plane.publish_hosted_endpoint(
        owner_city_id="city-b",
        public_handle="forum.city-b.lotus",
        transport="https",
        location="https://forum.city-b.example",
        visibility=EndpointVisibility.PUBLIC,
        now=20.0,
    )
    return plane


def test_snapshot_roundtrip_restores_route_resolution():
    original = _build_plane()

    restored = restore_control_plane(snapshot_control_plane(original))

    assert restored.minimum_trust == TrustLevel.VERIFIED
    assert restored.registry.get_identity("city-b").repo == "org/city-b"
    assert restored.registry.get_presence("city-b").health == HealthStatus.HEALTHY
    assert restored.resolve_route("city-a", "city-b").location == "https://example/city-b.git"
    assert restored.registry.get_link_address("city-b").mac_address.startswith("02:00:")
    assert restored.resolve_public_handle("forum.city-b.lotus").owner_city_id == "city-b"


def test_state_store_persists_and_loads_control_plane(tmp_path: Path):
    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    original = _build_plane()

    store.save(original)
    loaded = store.load()

    assert loaded.trust_engine.evaluate("city-a", "city-b") == TrustLevel.TRUSTED
    assert loaded.resolve_route("city-a", "city-b").city_id == "city-b"
    assert loaded.resolve_public_handle("forum.city-b.lotus").location == "https://forum.city-b.example"
