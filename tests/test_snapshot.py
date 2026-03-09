from pathlib import Path

from agent_internet.control_plane import STEWARD_AUTHORITY_BUNDLE_FEED_ID, STEWARD_PROTOCOL_REPO_ID, STEWARD_PUBLIC_WIKI_BINDING_ID, AgentInternetControlPlane
from agent_internet.lotus_api import LotusControlPlaneAPI
from agent_internet.models import AuthorityFeedTransport, CityEndpoint, CityIdentity, CityPresence, EndpointVisibility, HealthStatus, LotusApiScope, ProjectionReconcileState, ProjectionReconcileStatusRecord, TrustLevel, TrustRecord
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
    plane.publish_service_address(
        owner_city_id="city-b",
        service_name="forum-api",
        public_handle="api.forum.city-b.lotus",
        transport="https",
        location="https://forum.city-b.example/api",
        required_scopes=(LotusApiScope.READ.value,),
        now=21.0,
    )
    plane.publish_route(
        owner_city_id="city-a",
        destination_prefix="service:city-b/forum",
        target_city_id="city-b",
        next_hop_city_id="city-b",
        metric=7,
        now=21.5,
    )
    LotusControlPlaneAPI(plane).issue_token(
        subject="operator",
        scopes=(LotusApiScope.READ.value, LotusApiScope.SERVICE_WRITE.value),
        token_secret="snapshot-token",
        token_id="tok-snapshot",
        now=22.0,
    )
    plane.bootstrap_steward_public_wiki_feed(bundle_path="/tmp/steward/.authority-export-bundle.json", now=23.0)
    plane.upsert_projection_reconcile_status(
        ProjectionReconcileStatusRecord(
            binding_id=STEWARD_PUBLIC_WIKI_BINDING_ID,
            feed_id=STEWARD_AUTHORITY_BUNDLE_FEED_ID,
            status=ProjectionReconcileState.SUCCESS,
            last_checked_at=24.0,
            last_imported_at=24.0,
            last_imported_source_sha="bundle-sha",
            last_imported_export_version="v1",
            last_publish_attempt_at=24.5,
            last_success_at=24.5,
            labels={"source_repo_id": STEWARD_PROTOCOL_REPO_ID},
        ),
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
    assert restored.resolve_service_address("city-b", "forum-api").public_handle == "api.forum.city-b.lotus"
    assert restored.registry.get_route("city-a:service:city-b/forum:city-b").target_city_id == "city-b"
    assert restored.registry.get_api_token("tok-snapshot").subject == "operator"
    assert restored.registry.get_source_authority_feed(STEWARD_AUTHORITY_BUNDLE_FEED_ID).transport == AuthorityFeedTransport.FILESYSTEM_BUNDLE
    assert restored.registry.get_projection_reconcile_status(STEWARD_PUBLIC_WIKI_BINDING_ID).status == ProjectionReconcileState.SUCCESS


def test_state_store_persists_and_loads_control_plane(tmp_path: Path):
    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    original = _build_plane()

    store.save(original)
    loaded = store.load()

    assert loaded.trust_engine.evaluate("city-a", "city-b") == TrustLevel.TRUSTED
    assert loaded.resolve_route("city-a", "city-b").city_id == "city-b"
    assert loaded.resolve_public_handle("forum.city-b.lotus").location == "https://forum.city-b.example"
    assert loaded.resolve_service_address("city-b", "forum-api").location == "https://forum.city-b.example/api"
    assert loaded.registry.get_route("city-a:service:city-b/forum:city-b").metric == 7
