import json

import pytest

from agent_internet.agent_city_bridge import AgentCityBridge, city_presence_from_report
from agent_internet.assistant_surface import assistant_social_slot_from_snapshot, assistant_space_from_snapshot
from agent_internet.agent_city_contract import AgentCityFilesystemContract
from agent_internet.control_plane import AGENT_INTERNET_REPO_ID, STEWARD_PROTOCOL_REPO_ID, STEWARD_PUBLIC_WIKI_BINDING_ID, AgentInternetControlPlane
from agent_internet.filesystem_transport import FilesystemFederationTransport
from agent_internet.models import AssistantSurfaceSnapshot, AuthorityExportKind, AuthorityExportRecord, CityEndpoint, CityIdentity, EndpointVisibility, ForkLineageRecord, ForkMode, HealthStatus, IntentRecord, IntentStatus, IntentType, LotusApiScope, ProjectionFailurePolicy, ProjectionMode, PublicationState, RepoRole, SlotStatus, SpaceKind, TrustLevel, TrustRecord, UpstreamSyncPolicy
from agent_internet.snapshot import restore_control_plane, snapshot_control_plane


def test_city_presence_from_report_maps_health_states():
    report = {
        "heartbeat": 7,
        "timestamp": 100.0,
        "population": 10,
        "alive": 10,
        "dead": 0,
        "chain_valid": True,
    }

    presence = city_presence_from_report("city-a", report, capabilities=("federation",))

    assert presence.city_id == "city-a"
    assert presence.health == HealthStatus.HEALTHY
    assert presence.capabilities == ("federation",)


def test_agent_city_bridge_uses_latest_report_and_writes_directives(tmp_path):
    contract = AgentCityFilesystemContract(root=tmp_path)
    transport = FilesystemFederationTransport(contract=contract)
    contract.ensure_dirs()
    (contract.reports_dir / "report_1.json").write_text(json.dumps({"heartbeat": 1, "timestamp": 1.0}))
    (contract.reports_dir / "report_2.json").write_text(
        json.dumps({"heartbeat": 2, "timestamp": 2.0, "population": 4, "alive": 3, "dead": 1, "chain_valid": True}),
    )
    bridge = AgentCityBridge(city_id="city-a", transport=transport)

    assert bridge.latest_report()["heartbeat"] == 2
    assert bridge.latest_presence().health == HealthStatus.DEGRADED

    bridge.write_directive({"directive_type": "sync"}, directive_id="dir-1")
    assert json.loads(contract.directive_path("dir-1").read_text())["directive_type"] == "sync"


def test_control_plane_registers_observes_and_routes(tmp_path):
    contract = AgentCityFilesystemContract(root=tmp_path)
    transport = FilesystemFederationTransport(contract=contract)
    contract.ensure_dirs()
    (contract.reports_dir / "report_4.json").write_text(
        json.dumps({"heartbeat": 4, "timestamp": 4.0, "population": 2, "alive": 2, "dead": 0, "chain_valid": True}),
    )

    plane = AgentInternetControlPlane()
    identity = CityIdentity(city_id="city-b", slug="b", repo="org/city-b")
    endpoint = CityEndpoint(city_id="city-b", transport="git", location="https://example/city-b.git")

    plane.register_city(identity, endpoint)
    observed = plane.observe_agent_city(
        AgentCityBridge(city_id="city-b", transport=transport),
        identity=identity,
        endpoint=endpoint,
    )
    plane.record_trust(TrustRecord("city-a", "city-b", TrustLevel.OBSERVED, reason="federation seed"))

    assert observed.health == HealthStatus.HEALTHY
    assert plane.resolve_route("city-a", "city-b") == endpoint
    assert plane.registry.get_link_address("city-b").city_id == "city-b"
    assert plane.registry.get_network_address("city-b").city_id == "city-b"


def test_control_plane_publishes_and_resolves_lotus_handle():
    plane = AgentInternetControlPlane()
    plane.register_city(
        CityIdentity(city_id="city-a", slug="a", repo="org/city-a"),
        CityEndpoint(city_id="city-a", transport="filesystem", location="/tmp/city-a"),
    )
    plane.announce_city(city_presence_from_report("city-a", {"heartbeat": 1, "timestamp": 1.0, "population": 1, "alive": 1, "dead": 0, "chain_valid": True}))

    hosted = plane.publish_hosted_endpoint(
        owner_city_id="city-a",
        public_handle="forum.city-a.lotus",
        transport="https",
        location="https://forum.city-a.example",
        visibility=EndpointVisibility.FEDERATED,
        ttl_s=60.0,
        now=5.0,
    )

    assert hosted.visibility == EndpointVisibility.FEDERATED
    assert plane.resolve_public_handle("forum.city-a.lotus", now=10.0).location == "https://forum.city-a.example"


def test_control_plane_publishes_and_resolves_service_address():
    plane = AgentInternetControlPlane()
    plane.register_city(
        CityIdentity(city_id="city-a", slug="a", repo="org/city-a"),
        CityEndpoint(city_id="city-a", transport="filesystem", location="/tmp/city-a"),
    )
    plane.announce_city(city_presence_from_report("city-a", {"heartbeat": 1, "timestamp": 1.0, "population": 1, "alive": 1, "dead": 0, "chain_valid": True}))

    service = plane.publish_service_address(
        owner_city_id="city-a",
        service_name="forum-api",
        public_handle="api.forum.city-a.lotus",
        transport="https",
        location="https://forum.city-a.example/api",
        required_scopes=(LotusApiScope.READ.value,),
        now=5.0,
    )

    assert service.service_id == "city-a:forum-api"
    assert plane.resolve_service_address("city-a", "forum-api", now=10.0).location == "https://forum.city-a.example/api"


def test_control_plane_publishes_steward_aligned_route_and_resolves_next_hop():
    plane = AgentInternetControlPlane()
    plane.register_city(
        CityIdentity(city_id="city-a", slug="a", repo="org/city-a"),
        CityEndpoint(city_id="city-a", transport="filesystem", location="/tmp/city-a"),
    )
    plane.register_city(
        CityIdentity(city_id="city-b", slug="b", repo="org/city-b"),
        CityEndpoint(city_id="city-b", transport="git", location="https://example/city-b.git"),
    )
    plane.announce_city(
        city_presence_from_report(
            "city-b",
            {"heartbeat": 1, "timestamp": 1.0, "population": 1, "alive": 1, "dead": 0, "chain_valid": True},
        ),
    )
    plane.record_trust(TrustRecord("city-a", "city-b", TrustLevel.TRUSTED, reason="route federation"))

    route = plane.publish_route(
        owner_city_id="city-a",
        destination_prefix="service:city-z/forum",
        target_city_id="city-z",
        next_hop_city_id="city-b",
        metric=5,
        ttl_s=60.0,
        now=5.0,
    )
    resolution = plane.resolve_next_hop("city-a", "service:city-z/forum-api", now=10.0)

    assert route.nadi_type == "vyana"
    assert route.priority == "rajas"
    assert route.ttl_ms == 60000
    assert resolution is not None
    assert resolution.next_hop_city_id == "city-b"
    assert resolution.next_hop_endpoint.location == "https://example/city-b.git"


def test_control_plane_publishes_and_restores_assistant_space_and_slot():
    plane = AgentInternetControlPlane()
    snapshot = AssistantSurfaceSnapshot(
        assistant_id="moltbook_assistant",
        assistant_kind="moltbook_assistant",
        city_id="city-a",
        city_slug="a",
        repo="org/city-a",
        heartbeat_source="steward-protocol/mahamantra",
        heartbeat=5,
        state_present=True,
        total_posts=2,
        following=3,
        active_campaigns=(
            {
                "id": "internet-adaptation",
                "title": "Internet adaptation",
                "north_star": "Continuously adapt to relevant new protocols and standards.",
                "status": "active",
                "last_gap_summary": ["keep execution bounded"],
            },
        ),
    )

    space, slot = plane.publish_assistant_surface(snapshot)
    payload = snapshot_control_plane(plane)
    restored = restore_control_plane(payload)

    assert space.kind == SpaceKind.ASSISTANT
    assert slot.status == SlotStatus.ACTIVE
    assert space.labels["campaign_count"] == "1"
    assert slot.labels["campaign_focus"] == "Internet adaptation"
    assert restored.registry.get_space(space.space_id) == space
    assert restored.registry.get_slot(slot.slot_id) == slot


def test_control_plane_publishes_and_restores_fork_lineage():
    plane = AgentInternetControlPlane()
    lineage = ForkLineageRecord(
        lineage_id="lineage:city-b",
        repo="org/city-b",
        upstream_repo="org/city-a",
        line_root_repo="org/city-a",
        fork_mode=ForkMode.SOVEREIGN,
        sync_policy=UpstreamSyncPolicy.TRACKED,
        space_id="space:city-b:moltbook_assistant",
        upstream_space_id="space:city-a:moltbook_assistant",
        forked_by_subject_id="human:ss",
        created_at=123.0,
        labels={"channel": "github"},
    )

    plane.upsert_fork_lineage(lineage)
    payload = snapshot_control_plane(plane)
    restored = restore_control_plane(payload)

    assert payload["fork_lineage"][0]["repo"] == "org/city-b"
    assert restored.registry.get_fork_lineage("lineage:city-b") == lineage


def test_control_plane_publishes_and_restores_intents():
    plane = AgentInternetControlPlane()
    intent = IntentRecord(
        intent_id="intent:claim-city-b",
        intent_type=IntentType.REQUEST_SPACE_CLAIM,
        status=IntentStatus.PENDING,
        title="Claim assistant space",
        description="Request claim of the assistant space for city-b.",
        requested_by_subject_id="human:ss",
        repo="org/city-b",
        city_id="city-b",
        space_id="space:city-b:moltbook_assistant",
        created_at=321.0,
        updated_at=321.0,
        labels={"channel": "lotus"},
    )

    plane.upsert_intent(intent)
    payload = snapshot_control_plane(plane)
    restored = restore_control_plane(payload)

    assert payload["intents"][0]["intent_type"] == "request_space_claim"
    assert restored.registry.get_intent("intent:claim-city-b") == intent


def test_control_plane_transitions_intents_with_state_rules():
    plane = AgentInternetControlPlane()
    plane.upsert_intent(
        IntentRecord(
            intent_id="intent:fork-city-b",
            intent_type=IntentType.REQUEST_FORK,
            requested_by_subject_id="human:ss",
            created_at=100.0,
            updated_at=100.0,
        ),
    )

    accepted = plane.transition_intent(
        intent_id="intent:fork-city-b",
        status=IntentStatus.ACCEPTED,
        updated_at=101.0,
    )
    fulfilled = plane.transition_intent(
        intent_id="intent:fork-city-b",
        status=IntentStatus.FULFILLED,
        updated_at=102.0,
    )

    assert accepted.status == IntentStatus.ACCEPTED
    assert fulfilled.status == IntentStatus.FULFILLED
    assert fulfilled.updated_at == 102.0

    with pytest.raises(ValueError, match="invalid_intent_transition"):
        plane.transition_intent(
            intent_id="intent:fork-city-b",
            status=IntentStatus.REJECTED,
            updated_at=103.0,
        )


def test_control_plane_bootstraps_explicit_steward_public_wiki_contract():
    plane = AgentInternetControlPlane()

    seeded = plane.bootstrap_steward_public_wiki_contract(now=123.0)

    steward_role = plane.registry.get_repo_role(STEWARD_PROTOCOL_REPO_ID)
    operator_role = plane.registry.get_repo_role(AGENT_INTERNET_REPO_ID)
    binding = plane.registry.get_projection_binding(STEWARD_PUBLIC_WIKI_BINDING_ID)
    status = plane.registry.get_publication_status(STEWARD_PUBLIC_WIKI_BINDING_ID)

    assert seeded["binding"] == binding
    assert steward_role.role == RepoRole.NORMATIVE_SOURCE
    assert AuthorityExportKind.CANONICAL_SURFACE.value in steward_role.exports
    assert operator_role.role == RepoRole.PUBLIC_MEMBRANE_OPERATOR
    assert binding.required_export_kind == AuthorityExportKind.CANONICAL_SURFACE
    assert binding.projection_mode == ProjectionMode.REQUIRED
    assert binding.failure_policy == ProjectionFailurePolicy.FAIL_CLOSED
    assert status.status == PublicationState.BLOCKED
    assert status.failure_reason == "missing_authority_export:steward-protocol:canonical_surface"


def test_control_plane_bootstrap_preserves_existing_publication_status_and_snapshots_contract():
    plane = AgentInternetControlPlane()
    plane.upsert_authority_export(
        AuthorityExportRecord(
            export_id="steward-protocol/canonical-surface",
            repo_id=STEWARD_PROTOCOL_REPO_ID,
            export_kind=AuthorityExportKind.CANONICAL_SURFACE,
            version="2026-03-09T15:00:00Z",
            artifact_uri="agent-web://steward/canonical-surface",
            generated_at=222.0,
        ),
    )

    plane.bootstrap_steward_public_wiki_contract(now=223.0)
    seeded_status = plane.registry.get_publication_status(STEWARD_PUBLIC_WIKI_BINDING_ID)
    assert seeded_status.status == PublicationState.STALE
    assert seeded_status.projected_from_export_id == "steward-protocol/canonical-surface"

    plane.upsert_publication_status(
        seeded_status.__class__(
            binding_id=seeded_status.binding_id,
            status=PublicationState.SUCCESS,
            projected_from_export_id=seeded_status.projected_from_export_id,
            target_kind=seeded_status.target_kind,
            target_locator=seeded_status.target_locator,
            published_at=224.0,
            checked_at=224.0,
            stale=False,
            failure_reason="",
        ),
    )
    plane.bootstrap_steward_public_wiki_contract(now=225.0)

    payload = snapshot_control_plane(plane)
    restored = restore_control_plane(payload)
    restored_status = restored.registry.get_publication_status(STEWARD_PUBLIC_WIKI_BINDING_ID)

    assert restored.registry.get_authority_export("steward-protocol/canonical-surface").artifact_uri == "agent-web://steward/canonical-surface"
    assert restored.registry.get_projection_binding(STEWARD_PUBLIC_WIKI_BINDING_ID).target_kind == "github_wiki"
    assert restored_status.status == PublicationState.SUCCESS
    assert restored_status.published_at == 224.0