import json
from hashlib import sha256

import pytest

from agent_internet.control_plane import STEWARD_AUTHORITY_BUNDLE_FEED_ID, STEWARD_PUBLIC_WIKI_BINDING_ID, AgentInternetControlPlane
from agent_internet.lotus_api import LotusControlPlaneAPI
from agent_internet.models import (
    AssistantSurfaceSnapshot,
    AuthorityExportKind,
    AuthorityExportRecord,
    ClaimStatus,
    CityEndpoint,
    CityIdentity,
    ForkLineageRecord,
    ForkMode,
    IntentStatus,
    IntentType,
    LeaseStatus,
    LotusApiScope,
    PublicationState,
    ProjectionReconcileState,
    ProjectionReconcileStatusRecord,
    SlotDescriptor,
    SlotLeaseRecord,
    SlotStatus,
    SpaceClaimRecord,
    TrustLevel,
    TrustRecord,
    UpstreamSyncPolicy,
)
from agent_internet.agent_web_source_registry import upsert_agent_web_source_registry_entry
from agent_internet.agent_web_semantic_overlay import upsert_agent_web_semantic_bridge


def _write_authority_bundle(tmp_path, *, version: str = "2026-03-09T19:00:00Z"):
    bundle_dir = tmp_path / "bundle"
    (bundle_dir / ".authority-exports").mkdir(parents=True)
    canonical_payload = {"kind": "canonical_surface", "documents": [{"document_id": "constitution"}]}
    canonical_path = ".authority-exports/canonical-surface.json"
    (bundle_dir / canonical_path).write_text(json.dumps(canonical_payload, indent=2, sort_keys=True) + "\n")
    canonical_digest = sha256(json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    bundle = {
        "kind": "source_authority_bundle",
        "contract_version": 1,
        "generated_at": 301.0,
        "source_sha": "fedcba",
        "repo_role": {
            "repo_id": "steward-protocol",
            "role": "normative_source",
            "owner_boundary": "normative_protocol_surface",
            "exports": ["canonical_surface"],
            "consumes": [],
            "publication_targets": [STEWARD_PUBLIC_WIKI_BINDING_ID],
            "labels": {"public_surface_owner": "agent-internet"},
        },
        "authority_exports": [
            {
                "export_id": "steward-protocol/canonical_surface",
                "repo_id": "steward-protocol",
                "export_kind": "canonical_surface",
                "version": version,
                "artifact_uri": canonical_path,
                "generated_at": 300.0,
                "contract_version": 1,
                "content_sha256": canonical_digest,
                "labels": {"source_sha": "fedcba"},
            },
        ],
        "artifact_paths": {"canonical_surface": canonical_path},
    }
    path = bundle_dir / ".authority-export-bundle.json"
    path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    return path


def test_lotus_api_issues_token_and_allows_scoped_calls():
    plane = AgentInternetControlPlane()
    plane.register_city(
        CityIdentity(city_id="city-a", slug="a", repo="org/city-a"),
        CityEndpoint(city_id="city-a", transport="filesystem", location="/tmp/city-a"),
    )
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="operator",
        scopes=(LotusApiScope.READ.value, LotusApiScope.SERVICE_WRITE.value),
        token_secret="secret-token",
        token_id="tok-1",
        now=10.0,
    )

    published = api.call(
        bearer_token=issued.secret,
        action="publish_service",
        params={
            "city_id": "city-a",
            "service_name": "forum-api",
            "public_handle": "api.forum.city-a.lotus",
            "transport": "https",
            "location": "https://forum.city-a.example/api",
            "required_scopes": [LotusApiScope.READ.value],
        },
    )

    assert published["service_address"]["service_id"] == "city-a:forum-api"
    resolved = api.call(
        bearer_token=issued.secret,
        action="resolve_service",
        params={"city_id": "city-a", "service_name": "forum-api"},
    )
    assert resolved["resolved"]["location"] == "https://forum.city-a.example/api"


def test_lotus_api_rejects_missing_scope():
    plane = AgentInternetControlPlane()
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="observer",
        scopes=(LotusApiScope.READ.value,),
        token_secret="read-only-token",
        token_id="tok-2",
        now=10.0,
    )

    with pytest.raises(PermissionError, match="missing_scopes"):
        api.call(
            bearer_token=issued.secret,
            action="assign_addresses",
            params={"city_id": "city-a"},
        )


def test_lotus_api_describes_capabilities_manifest():
    plane = AgentInternetControlPlane()
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="observer",
        scopes=(LotusApiScope.READ.value,),
        token_secret="caps-token",
        token_id="tok-caps",
        now=10.0,
    )

    manifest = api.call(
        bearer_token=issued.secret,
        action="lotus_capabilities",
        params={"base_url": "https://lotus.example"},
    )

    payload = manifest["lotus_capabilities"]
    assert payload["kind"] == "lotus_capability_manifest"
    assert payload["discovery"]["manifest_http_path"] == "https://lotus.example/v1/lotus/capabilities"
    assert payload["recoverability"]["manual_sweep_action"] == "sweep_expired_grants"
    assert "create_intent" in payload["recoverability"]["request_id_supported_actions"]
    assert "release_space_claim" in payload["recoverability"]["request_id_supported_actions"]
    assert payload["parseability"]["http_error_envelope_fields"] == ["error", "error_code", "error_kind", "recoverable", "retryable", "context"]
    assert any(item["lotus_action"] == "create_intent" for item in payload["capabilities"])


def test_lotus_api_generates_cli_safe_secret_prefix():
    plane = AgentInternetControlPlane()
    api = LotusControlPlaneAPI(plane)

    issued = api.issue_token(subject="operator", scopes=(LotusApiScope.READ.value,))

    assert issued.secret.startswith("lotus_")


def test_lotus_api_lists_projection_feeds_and_reconcile_status(tmp_path):
    plane = AgentInternetControlPlane()
    bundle_path = _write_authority_bundle(tmp_path)
    plane.bootstrap_steward_public_wiki_feed(bundle_path=bundle_path, now=10.0)
    plane.upsert_projection_reconcile_status(
        ProjectionReconcileStatusRecord(
            binding_id=STEWARD_PUBLIC_WIKI_BINDING_ID,
            feed_id=STEWARD_AUTHORITY_BUNDLE_FEED_ID,
            status=ProjectionReconcileState.SKIPPED,
            last_checked_at=11.0,
            next_retry_at=120.0,
            last_error="backoff_active",
        ),
    )
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="operator",
        scopes=(LotusApiScope.READ.value, LotusApiScope.RECONCILE_WRITE.value),
        token_secret="reconcile-token",
        token_id="tok-reconcile",
        now=10.0,
    )

    feeds = api.call(bearer_token=issued.secret, action="list_source_authority_feeds", params={})
    statuses = api.call(bearer_token=issued.secret, action="list_projection_reconcile_statuses", params={})
    paused = api.call(
        bearer_token=issued.secret,
        action="set_source_authority_feed_enabled",
        params={"feed_id": STEWARD_AUTHORITY_BUNDLE_FEED_ID, "enabled": False},
    )

    assert feeds["source_authority_feeds"][0]["feed_id"] == STEWARD_AUTHORITY_BUNDLE_FEED_ID
    assert statuses["projection_reconcile_statuses"][0]["last_error"] == "backoff_active"
    assert paused["source_authority_feed"]["enabled"] is False


def test_lotus_api_publishes_and_resolves_next_hop():
    plane = AgentInternetControlPlane()
    plane.register_city(
        CityIdentity(city_id="city-a", slug="a", repo="org/city-a"),
        CityEndpoint(city_id="city-a", transport="filesystem", location="/tmp/city-a"),
    )
    plane.register_city(
        CityIdentity(city_id="city-b", slug="b", repo="org/city-b"),
        CityEndpoint(city_id="city-b", transport="git", location="https://example/city-b.git"),
    )
    plane.record_trust(TrustRecord("city-a", "city-b", TrustLevel.TRUSTED, reason="route api test"))
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="operator",
        scopes=(LotusApiScope.READ.value, LotusApiScope.SERVICE_WRITE.value),
        token_secret="route-token",
        token_id="tok-route",
        now=10.0,
    )

    api.call(
        bearer_token=issued.secret,
        action="publish_route",
        params={
            "owner_city_id": "city-a",
            "destination_prefix": "service:city-z/forum",
            "target_city_id": "city-z",
            "next_hop_city_id": "city-b",
            "metric": 5,
        },
    )
    resolved = api.call(
        bearer_token=issued.secret,
        action="resolve_next_hop",
        params={"source_city_id": "city-a", "destination": "service:city-z/forum-api"},
    )

    assert resolved["resolved"]["next_hop_city_id"] == "city-b"


def test_lotus_api_accepts_nadi_priority_alias_and_returns_it_explicitly():
    plane = AgentInternetControlPlane()
    plane.register_city(
        CityIdentity(city_id="city-a", slug="a", repo="org/city-a"),
        CityEndpoint(city_id="city-a", transport="filesystem", location="/tmp/city-a"),
    )
    plane.register_city(
        CityIdentity(city_id="city-b", slug="b", repo="org/city-b"),
        CityEndpoint(city_id="city-b", transport="git", location="https://example/city-b.git"),
    )
    plane.record_trust(TrustRecord("city-a", "city-b", TrustLevel.TRUSTED, reason="route api alias test"))
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="operator",
        scopes=(LotusApiScope.READ.value, LotusApiScope.SERVICE_WRITE.value),
        token_secret="route-alias-token",
        token_id="tok-route-alias",
        now=10.0,
    )

    published = api.call(
        bearer_token=issued.secret,
        action="publish_route",
        params={
            "owner_city_id": "city-a",
            "destination_prefix": "service:city-z/forum",
            "target_city_id": "city-z",
            "next_hop_city_id": "city-b",
            "metric": 5,
            "nadi_priority": "suddha",
        },
    )
    resolved = api.call(
        bearer_token=issued.secret,
        action="resolve_next_hop",
        params={"source_city_id": "city-a", "destination": "service:city-z/forum-api"},
    )

    assert published["route"]["priority"] == "suddha"
    assert published["route"]["nadi_priority"] == "suddha"
    assert resolved["resolved"]["priority"] == "suddha"
    assert resolved["resolved"]["nadi_priority"] == "suddha"


def test_lotus_api_returns_assistant_snapshot(tmp_path):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_4.json").write_text(
        json.dumps(
            {
                "heartbeat": 4,
                "timestamp": 40.0,
                "population": 2,
                "alive": 2,
                "dead": 0,
                "chain_valid": True,
                "active_campaigns": [
                    {
                        "id": "internet-adaptation",
                        "title": "Internet adaptation",
                        "north_star": "Continuously adapt to relevant new protocols and standards.",
                        "status": "active",
                        "last_gap_summary": ["keep execution bounded"],
                    }
                ],
            },
        ),
    )
    (repo_root / "data" / "assistant_state.json").write_text(
        json.dumps({"followed": ["alice"], "ops": {"posts": 2}}),
    )
    peer_dir = repo_root / "data" / "federation"
    peer_dir.mkdir(parents=True, exist_ok=True)
    (peer_dir / "peer.json").write_text(
        json.dumps({"identity": {"city_id": "city-api", "slug": "api", "repo": "org/city-api"}, "capabilities": ["moltbook"]}),
    )

    plane = AgentInternetControlPlane()
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="observer",
        scopes=(LotusApiScope.READ.value,),
        token_secret="assistant-token",
        token_id="tok-assistant",
        now=10.0,
    )

    response = api.call(
        bearer_token=issued.secret,
        action="assistant_snapshot",
        params={"root": str(repo_root)},
    )

    assert response["assistant_snapshot"]["city_id"] == "city-api"
    assert response["assistant_snapshot"]["assistant_kind"] == "moltbook_assistant"
    assert response["assistant_snapshot"]["heartbeat"] == 4
    assert response["assistant_snapshot"]["following"] == 1
    assert response["assistant_snapshot"]["total_posts"] == 2
    assert response["assistant_snapshot"]["active_campaigns"][0]["id"] == "internet-adaptation"


def test_lotus_api_returns_agent_web_manifest(tmp_path):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_4.json").write_text(
        json.dumps(
            {
                "heartbeat": 4,
                "timestamp": 40.0,
                "population": 2,
                "alive": 2,
                "dead": 0,
                "chain_valid": True,
                "active_campaigns": [
                    {
                        "id": "internet-adaptation",
                        "title": "Internet adaptation",
                        "north_star": "Continuously adapt to relevant new protocols and standards.",
                        "status": "active",
                        "last_gap_summary": ["keep execution bounded"],
                    }
                ],
            },
        ),
    )
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 2}}))
    peer_dir = repo_root / "data" / "federation"
    peer_dir.mkdir(parents=True, exist_ok=True)
    (peer_dir / "peer.json").write_text(
        json.dumps({"identity": {"city_id": "city-http", "slug": "http", "repo": "org/city-http"}, "capabilities": ["moltbook"]}),
    )

    plane = AgentInternetControlPlane()
    plane.publish_assistant_surface(
        AssistantSurfaceSnapshot(
            assistant_id="moltbook_assistant",
            assistant_kind="moltbook_assistant",
            city_id="city-http",
            city_slug="http",
            repo="org/city-http",
            heartbeat_source="steward-protocol/mahamantra",
            heartbeat=4,
            state_present=True,
            total_posts=2,
            active_campaigns=(
                {
                    "id": "internet-adaptation",
                    "title": "Internet adaptation",
                    "north_star": "Continuously adapt to relevant new protocols and standards.",
                    "status": "active",
                    "last_gap_summary": ["keep execution bounded"],
                },
            ),
        ),
    )
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="operator", scopes=(LotusApiScope.READ.value,), token_secret="secret")

    response = api.call(
        bearer_token=issued.secret,
        action="agent_web_manifest",
        params={"root": str(repo_root)},
    )

    assert response["agent_web_manifest"]["identity"]["city_id"] == "city-http"
    assert response["agent_web_manifest"]["campaigns"][0]["title"] == "Internet adaptation"
    assert response["agent_web_manifest"]["entrypoints"]["default"]["document_id"] == "agent_web"
    assert response["agent_web_manifest"]["entrypoints"]["public_graph"]["document_id"] == "public_graph"
    assert response["agent_web_manifest"]["entrypoints"]["semantic_capabilities"]["document_id"] == "semantic_capabilities"
    assert response["agent_web_manifest"]["entrypoints"]["semantic_contracts"]["document_id"] == "semantic_contracts"
    assert response["agent_web_manifest"]["entrypoints"]["repo_graph_capabilities"]["document_id"] == "repo_graph_capabilities"
    assert response["agent_web_manifest"]["entrypoints"]["repo_graph_contracts"]["document_id"] == "repo_graph_contracts"
    assert response["agent_web_manifest"]["entrypoints"]["steward_authority"]["document_id"] == "steward_authority"
    assert any(document["document_id"] == "search_index" for document in response["agent_web_manifest"]["documents"])
    assert any(document["document_id"] == "repo_graph_capabilities" for document in response["agent_web_manifest"]["documents"])
    assert any(document["document_id"] == "assistant_surface" for document in response["agent_web_manifest"]["documents"])
    assert any(document["document_id"] == "steward_authority" for document in response["agent_web_manifest"]["documents"])
    assert any(link["rel"] == "assistant_surface" for link in response["agent_web_manifest"]["links"])

    semantic = api.call(
        bearer_token=issued.secret,
        action="agent_web_semantic_capabilities",
        params={"base_url": "https://agent.example"},
    )
    assert semantic["agent_web_semantic_capabilities"]["capabilities"][0]["http"]["href"].startswith("https://agent.example/")

    contracts = api.call(
        bearer_token=issued.secret,
        action="agent_web_semantic_contracts",
        params={"base_url": "https://agent.example", "capability_id": "semantic_expand"},
    )
    assert contracts["agent_web_semantic_contracts"]["contract_id"] == "semantic_expand.v1"

    contracts = api.call(
        bearer_token=issued.secret,
        action="agent_web_semantic_contracts",
        params={"base_url": "https://agent.example", "contract_id": "semantic_neighbors.v1"},
    )
    assert contracts["agent_web_semantic_contracts"]["capability_id"] == "semantic_neighbors"

    contracts = api.call(
        bearer_token=issued.secret,
        action="agent_web_semantic_contracts",
        params={"base_url": "https://agent.example", "capability_id": "semantic_federated_search", "version": 1},
    )
    assert contracts["agent_web_semantic_contracts"]["version"] == 1


def test_lotus_api_returns_repo_graph_surfaces(monkeypatch, tmp_path):
    plane = AgentInternetControlPlane()
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="operator", scopes=(LotusApiScope.READ.value,), token_secret="secret")
    root = tmp_path / "steward-protocol"
    root.mkdir()

    monkeypatch.setattr(
        "agent_internet.lotus_api.build_agent_web_repo_graph_snapshot",
        lambda repo_root, **kwargs: {"kind": "agent_web_repo_graph_snapshot", "source": {"root": str(repo_root)}, "nodes": [{"node_id": "module.city"}]},
    )
    monkeypatch.setattr(
        "agent_internet.lotus_api.read_agent_web_repo_graph_neighbors",
        lambda repo_root, **kwargs: {"kind": "agent_web_repo_graph_neighbors", "record": {"node_id": kwargs["node_id"]}, "neighbors": []},
    )
    monkeypatch.setattr(
        "agent_internet.lotus_api.read_agent_web_repo_graph_context",
        lambda repo_root, **kwargs: {"kind": "agent_web_repo_graph_context", "concept": kwargs["concept"], "context": "ctx"},
    )

    response = api.call(bearer_token=issued.secret, action="agent_web_repo_graph_capabilities", params={"base_url": "https://agent.example"})
    assert response["agent_web_repo_graph_capabilities"]["capabilities"][0]["capability_id"] == "repo_graph_snapshot"

    response = api.call(bearer_token=issued.secret, action="agent_web_repo_graph_contracts", params={"contract_id": "repo_graph_neighbors.v1"})
    assert response["agent_web_repo_graph_contracts"]["capability_id"] == "repo_graph_neighbors"

    response = api.call(bearer_token=issued.secret, action="agent_web_repo_graph_snapshot", params={"root": str(root), "node_type": "module"})
    assert response["agent_web_repo_graph"]["kind"] == "agent_web_repo_graph_snapshot"

    response = api.call(bearer_token=issued.secret, action="agent_web_repo_graph_neighbors", params={"root": str(root), "node_id": "module.city"})
    assert response["agent_web_repo_graph_neighbors"]["record"]["node_id"] == "module.city"

    response = api.call(bearer_token=issued.secret, action="agent_web_repo_graph_context", params={"root": str(root), "concept": "heartbeat"})
    assert response["agent_web_repo_graph_context"]["concept"] == "heartbeat"


def test_lotus_api_returns_agent_web_graph(tmp_path):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_4.json").write_text(
        json.dumps(
            {
                "heartbeat": 4,
                "timestamp": 40.0,
                "population": 2,
                "alive": 2,
                "dead": 0,
                "chain_valid": True,
                "active_campaigns": [{"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]}],
            },
        ),
    )
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 2}}))
    (repo_root / "data" / "federation" / "peer.json").write_text(
        json.dumps({"identity": {"city_id": "city-http", "slug": "http", "repo": "org/city-http"}, "capabilities": ["moltbook"]}),
    )

    plane = AgentInternetControlPlane()
    plane.publish_assistant_surface(
        AssistantSurfaceSnapshot(
            assistant_id="moltbook_assistant",
            assistant_kind="moltbook_assistant",
            city_id="city-http",
            city_slug="http",
            repo="org/city-http",
            heartbeat_source="steward-protocol/mahamantra",
            heartbeat=4,
            state_present=True,
            total_posts=2,
            active_campaigns=({"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]},),
        ),
    )
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="operator", scopes=(LotusApiScope.READ.value,), token_secret="secret")

    response = api.call(
        bearer_token=issued.secret,
        action="agent_web_graph",
        params={"root": str(repo_root)},
    )

    assert response["agent_web_graph"]["kind"] == "agent_web_public_graph"
    assert any(node["node_id"] == "document:public_graph" for node in response["agent_web_graph"]["nodes"])
    assert any(edge["kind"] == "focuses_on" for edge in response["agent_web_graph"]["edges"])


def test_lotus_api_returns_agent_web_index_and_search(tmp_path):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_4.json").write_text(
        json.dumps(
            {
                "heartbeat": 4,
                "timestamp": 40.0,
                "population": 2,
                "alive": 2,
                "dead": 0,
                "chain_valid": True,
                "active_campaigns": [{"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]}],
            },
        ),
    )
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 2}}))
    (repo_root / "data" / "federation" / "peer.json").write_text(
        json.dumps({"identity": {"city_id": "city-http", "slug": "http", "repo": "org/city-http"}, "capabilities": ["moltbook"]}),
    )

    plane = AgentInternetControlPlane()
    plane.publish_assistant_surface(
        AssistantSurfaceSnapshot(
            assistant_id="moltbook_assistant",
            assistant_kind="moltbook_assistant",
            city_id="city-http",
            city_slug="http",
            repo="org/city-http",
            heartbeat_source="steward-protocol/mahamantra",
            heartbeat=4,
            state_present=True,
            total_posts=2,
            active_campaigns=({"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]},),
        ),
    )
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="operator", scopes=(LotusApiScope.READ.value,), token_secret="secret")

    index_response = api.call(
        bearer_token=issued.secret,
        action="agent_web_index",
        params={"root": str(repo_root)},
    )
    assert index_response["agent_web_index"]["kind"] == "agent_web_search_index"
    assert any(record["record_id"] == "document:search_index" for record in index_response["agent_web_index"]["records"])

    search_response = api.call(
        bearer_token=issued.secret,
        action="agent_web_search",
        params={"root": str(repo_root), "query": "internet adaptation", "limit": 3},
    )
    assert search_response["agent_web_search"]["kind"] == "agent_web_search_results"
    assert search_response["agent_web_search"]["results"][0]["kind"] == "campaign"


def test_lotus_api_returns_agent_web_crawl_and_search(tmp_path):
    repo_a = tmp_path / "city-a"
    repo_b = tmp_path / "city-b"
    for repo_root, city_id, repo_name, campaign_title in (
        (repo_a, "city-a", "org/city-a", "Internet adaptation"),
        (repo_b, "city-b", "org/city-b", "Marketplace integration"),
    ):
        reports_dir = repo_root / "data" / "federation" / "reports"
        reports_dir.mkdir(parents=True)
        (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 1}}))
        (repo_root / "data" / "federation" / "peer.json").write_text(
            json.dumps({"identity": {"city_id": city_id, "slug": city_id, "repo": repo_name}, "capabilities": ["moltbook"]}),
        )
        (reports_dir / "report_4.json").write_text(
            json.dumps(
                {
                    "heartbeat": 4,
                    "timestamp": 40.0,
                    "population": 1,
                    "alive": 1,
                    "dead": 0,
                    "chain_valid": True,
                    "active_campaigns": [{"id": campaign_title.lower().replace(' ', '-'), "title": campaign_title, "north_star": campaign_title, "status": "active", "last_gap_summary": ["keep execution bounded"]}],
                },
            ),
        )

    plane = AgentInternetControlPlane()
    for city_id, repo_name, heartbeat in (("city-a", "org/city-a", 4), ("city-b", "org/city-b", 5)):
        plane.publish_assistant_surface(
            AssistantSurfaceSnapshot(
                assistant_id="moltbook_assistant",
                assistant_kind="moltbook_assistant",
                city_id=city_id,
                city_slug=city_id,
                repo=repo_name,
                heartbeat_source="steward-protocol/mahamantra",
                heartbeat=heartbeat,
                state_present=True,
                total_posts=1,
                active_campaigns=(),
            ),
        )
    plane.publish_service_address(
        owner_city_id="city-a",
        service_name="forum",
        public_handle="forum.city-a.lotus",
        transport="https",
        location="https://forum.city-a.lotus",
        auth_required=False,
    )
    plane.publish_service_address(
        owner_city_id="city-b",
        service_name="market",
        public_handle="market.city-b.lotus",
        transport="https",
        location="https://market.city-b.lotus",
        auth_required=False,
    )

    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="operator", scopes=(LotusApiScope.READ.value,), token_secret="secret")

    crawl_response = api.call(
        bearer_token=issued.secret,
        action="agent_web_crawl",
        params={"roots": [str(repo_a), str(repo_b)]},
    )
    assert crawl_response["agent_web_crawl"]["kind"] == "agent_web_crawl_bootstrap"
    assert crawl_response["agent_web_crawl"]["stats"]["source_count"] == 2

    search_response = api.call(
        bearer_token=issued.secret,
        action="agent_web_crawl_search",
        params={"roots": [str(repo_a), str(repo_b)], "query": "marketplace", "limit": 3},
    )
    assert search_response["agent_web_crawl_search"]["kind"] == "agent_web_crawl_search_results"
    assert search_response["agent_web_crawl_search"]["results"][0]["source_city_id"] == "city-b"


def test_lotus_api_returns_source_registry_and_registry_crawl(tmp_path):
    registry_path = tmp_path / "registry.json"
    repo_a = tmp_path / "city-a"
    repo_b = tmp_path / "city-b"
    for repo_root, city_id, repo_name, campaign_title in (
        (repo_a, "city-a", "org/city-a", "Internet adaptation"),
        (repo_b, "city-b", "org/city-b", "Marketplace integration"),
    ):
        reports_dir = repo_root / "data" / "federation" / "reports"
        reports_dir.mkdir(parents=True)
        (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 1}}))
        (repo_root / "data" / "federation" / "peer.json").write_text(json.dumps({"identity": {"city_id": city_id, "slug": city_id, "repo": repo_name}, "capabilities": ["moltbook"]}))
        (reports_dir / "report_6.json").write_text(json.dumps({"heartbeat": 6, "timestamp": 60.0, "population": 1, "alive": 1, "dead": 0, "chain_valid": True, "active_campaigns": [{"id": campaign_title.lower().replace(' ', '-'), "title": campaign_title, "north_star": campaign_title, "status": "active", "last_gap_summary": ["keep execution bounded"]}]}))
    upsert_agent_web_source_registry_entry(registry_path, root=repo_a)
    upsert_agent_web_source_registry_entry(registry_path, root=repo_b, source_id="city-b-source")

    plane = AgentInternetControlPlane()
    for city_id, repo_name in (("city-a", "org/city-a"), ("city-b", "org/city-b")):
        plane.publish_assistant_surface(AssistantSurfaceSnapshot(assistant_id="moltbook_assistant", assistant_kind="moltbook_assistant", city_id=city_id, city_slug=city_id, repo=repo_name, heartbeat_source="steward-protocol/mahamantra", heartbeat=6, state_present=True, total_posts=1, active_campaigns=()))
    plane.publish_service_address(owner_city_id="city-a", service_name="forum", public_handle="forum.city-a.lotus", transport="https", location="https://forum.city-a.lotus", auth_required=False)
    plane.publish_service_address(owner_city_id="city-b", service_name="market", public_handle="market.city-b.lotus", transport="https", location="https://market.city-b.lotus", auth_required=False)
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="operator", scopes=(LotusApiScope.READ.value,), token_secret="secret")

    registry_response = api.call(bearer_token=issued.secret, action="agent_web_source_registry", params={"registry_path": str(registry_path)})
    assert registry_response["agent_web_source_registry"]["stats"]["source_count"] == 2

    crawl_response = api.call(bearer_token=issued.secret, action="agent_web_crawl_registry", params={"registry_path": str(registry_path)})
    assert crawl_response["agent_web_crawl_registry"]["registry"]["enabled_source_count"] == 2

    search_response = api.call(bearer_token=issued.secret, action="agent_web_crawl_registry_search", params={"registry_path": str(registry_path), "query": "marketplace", "limit": 3})
    assert search_response["agent_web_crawl_registry_search"]["results"][0]["source_city_id"] == "city-b"


def test_lotus_api_refreshes_and_reads_federated_index(tmp_path):
    registry_path = tmp_path / "registry.json"
    index_path = tmp_path / "federated_index.json"
    overlay_path = tmp_path / "semantic_overlay.json"
    wordnet_path = tmp_path / "wordnet_bridge.json"
    repo_a = tmp_path / "city-a"
    repo_b = tmp_path / "city-b"
    for repo_root, city_id, repo_name, campaign_title in (
        (repo_a, "city-a", "org/city-a", "Internet adaptation"),
        (repo_b, "city-b", "org/city-b", "Marketplace integration"),
    ):
        reports_dir = repo_root / "data" / "federation" / "reports"
        reports_dir.mkdir(parents=True)
        (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 1}}))
        (repo_root / "data" / "federation" / "peer.json").write_text(json.dumps({"identity": {"city_id": city_id, "slug": city_id, "repo": repo_name}, "capabilities": ["moltbook"]}))
        (reports_dir / "report_9.json").write_text(json.dumps({"heartbeat": 9, "timestamp": 90.0, "population": 1, "alive": 1, "dead": 0, "chain_valid": True, "active_campaigns": [{"id": campaign_title.lower().replace(' ', '-'), "title": campaign_title, "north_star": campaign_title, "status": "active", "last_gap_summary": ["keep execution bounded"]}]}))
    upsert_agent_web_source_registry_entry(registry_path, root=repo_a)
    upsert_agent_web_source_registry_entry(registry_path, root=repo_b)
    wordnet_path.write_text('{"synsets": ["market.n.01", "commerce.n.01"], "words": {"w1": {"t": ["bazaar"], "c": [0, 1]}, "w2": {"t": ["marketplace"], "c": [0, 1]}, "w3": {"t": ["commerce"], "c": [0, 1]}}}')
    upsert_agent_web_semantic_bridge(overlay_path, bridge_kind="wordnet", terms=["marketplace"], expansions=["commerce"], weight=0.8)

    plane = AgentInternetControlPlane()
    for city_id, repo_name in (("city-a", "org/city-a"), ("city-b", "org/city-b")):
        plane.publish_assistant_surface(AssistantSurfaceSnapshot(assistant_id="moltbook_assistant", assistant_kind="moltbook_assistant", city_id=city_id, city_slug=city_id, repo=repo_name, heartbeat_source="steward-protocol/mahamantra", heartbeat=9, state_present=True, total_posts=1, active_campaigns=()))
    plane.publish_service_address(owner_city_id="city-a", service_name="forum", public_handle="forum.city-a.lotus", transport="https", location="https://forum.city-a.lotus", auth_required=False)
    plane.publish_service_address(owner_city_id="city-b", service_name="market", public_handle="market.city-b.lotus", transport="https", location="https://market.city-b.lotus", auth_required=False)
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="operator", scopes=(LotusApiScope.READ.value,), token_secret="secret")

    refresh_response = api.call(bearer_token=issued.secret, action="refresh_agent_web_federated_index", params={"index_path": str(index_path), "registry_path": str(registry_path), "overlay_path": str(overlay_path), "wordnet_path": str(wordnet_path), "now": 99.0})
    assert refresh_response["agent_web_federated_index"]["refreshed_at"] == 99.0
    assert refresh_response["agent_web_federated_index"]["stats"]["source_count"] == 2
    assert refresh_response["agent_web_federated_index"]["semantic_graph"]["stats"]["edge_count"] > 0

    read_response = api.call(bearer_token=issued.secret, action="agent_web_federated_index", params={"index_path": str(index_path)})
    assert read_response["agent_web_federated_index"]["semantic_extensions"]["status"] == "ready_for_overlay"
    semantic_record_id = read_response["agent_web_federated_index"]["records"][0]["record_id"]

    neighbors_response = api.call(bearer_token=issued.secret, action="agent_web_semantic_neighbors", params={"index_path": str(index_path), "record_id": semantic_record_id, "limit": 2})
    assert neighbors_response["agent_web_semantic_neighbors"]["kind"] == "agent_web_semantic_neighbors"

    overlay_response = api.call(bearer_token=issued.secret, action="agent_web_semantic_overlay", params={"overlay_path": str(overlay_path)})
    assert overlay_response["agent_web_semantic_overlay"]["stats"]["bridge_count"] == 1

    expansion_response = api.call(bearer_token=issued.secret, action="agent_web_semantic_expand", params={"overlay_path": str(overlay_path), "wordnet_path": str(wordnet_path), "query": "bazaar"})
    assert "marketplace" in expansion_response["agent_web_semantic_expand"]["expanded_terms"]

    search_response = api.call(bearer_token=issued.secret, action="agent_web_federated_search", params={"index_path": str(index_path), "overlay_path": str(overlay_path), "wordnet_path": str(wordnet_path), "query": "bazaar", "limit": 3})
    assert search_response["agent_web_federated_search"]["results"][0]["source_city_id"] == "city-b"
    assert search_response["agent_web_federated_search"]["wordnet_bridge"]["available"] is True
    assert search_response["agent_web_federated_search"]["results"][0]["why_matched"]["semantic_bridge_matches"]


def test_lotus_api_returns_agent_web_document(tmp_path):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_4.json").write_text(
        json.dumps(
            {
                "heartbeat": 4,
                "timestamp": 40.0,
                "population": 2,
                "alive": 2,
                "dead": 0,
                "chain_valid": True,
                "active_campaigns": [{"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]}],
            },
        ),
    )
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 2}}))
    (repo_root / "data" / "federation" / "peer.json").write_text(
        json.dumps({"identity": {"city_id": "city-http", "slug": "http", "repo": "org/city-http"}, "capabilities": ["moltbook"]}),
    )

    plane = AgentInternetControlPlane()
    plane.publish_assistant_surface(
        AssistantSurfaceSnapshot(
            assistant_id="moltbook_assistant",
            assistant_kind="moltbook_assistant",
            city_id="city-http",
            city_slug="http",
            repo="org/city-http",
            heartbeat_source="steward-protocol/mahamantra",
            heartbeat=4,
            state_present=True,
            total_posts=2,
            active_campaigns=({"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]},),
        ),
    )
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="operator", scopes=(LotusApiScope.READ.value,), token_secret="secret")

    response = api.call(
        bearer_token=issued.secret,
        action="agent_web_document",
        params={"root": str(repo_root), "document_id": "semantic_capabilities"},
    )

    assert response["agent_web_document"]["link"]["rel"] == "semantic_capabilities"
    assert response["agent_web_document"]["document"]["document_id"] == "semantic_capabilities"
    assert response["agent_web_document"]["document"]["path"] == "Semantic-Capabilities.md"
    assert "# Semantic Capabilities" in response["agent_web_document"]["document"]["content"]

    response = api.call(
        bearer_token=issued.secret,
        action="agent_web_document",
        params={"root": str(repo_root), "document_id": "semantic_contracts"},
    )

    assert response["agent_web_document"]["link"]["rel"] == "semantic_contracts"
    assert response["agent_web_document"]["document"]["document_id"] == "semantic_contracts"
    assert response["agent_web_document"]["document"]["path"] == "Semantic-Contracts.md"
    assert "# Semantic Contracts" in response["agent_web_document"]["document"]["content"]


def test_lotus_api_lists_spaces_and_slots():
    plane = AgentInternetControlPlane()
    plane.publish_assistant_surface(
        AssistantSurfaceSnapshot(
            assistant_id="moltbook_assistant",
            assistant_kind="moltbook_assistant",
            city_id="city-space",
            city_slug="space",
            repo="org/city-space",
            heartbeat_source="steward-protocol/mahamantra",
            heartbeat=6,
            state_present=True,
            total_posts=2,
        ),
    )
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="observer",
        scopes=(LotusApiScope.READ.value,),
        token_secret="spaces-token",
        token_id="tok-spaces",
        now=10.0,
    )

    spaces = api.call(bearer_token=issued.secret, action="list_spaces", params={})
    slots = api.call(bearer_token=issued.secret, action="list_slots", params={})

    assert spaces["spaces"][0]["space_id"] == "space:city-space:moltbook_assistant"
    assert spaces["spaces"][0]["kind"] == "assistant"
    assert slots["slots"][0]["slot_id"] == "slot:city-space:assistant-social"
    assert slots["slots"][0]["slot_kind"] == "assistant_social"


def test_lotus_api_lists_space_claims_and_slot_leases():
    plane = AgentInternetControlPlane()
    plane.upsert_space_claim(SpaceClaimRecord(claim_id="claim-1", source_intent_id="intent-space-1", subject_id="operator-1", space_id="space-1", granted_at=20.0))
    plane.upsert_slot_lease(SlotLeaseRecord(lease_id="lease-1", source_intent_id="intent-slot-1", holder_subject_id="operator-1", space_id="space-1", slot_id="slot-1", status=LeaseStatus.ACTIVE, granted_at=21.0))
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="observer", scopes=(LotusApiScope.READ.value,), token_secret="claims-token", now=10.0)

    claims = api.call(bearer_token=issued.secret, action="list_space_claims", params={})
    leases = api.call(bearer_token=issued.secret, action="list_slot_leases", params={})

    assert claims["space_claims"][0]["claim_id"] == "claim-1"
    assert leases["slot_leases"][0]["lease_id"] == "lease-1"


def test_lotus_api_lists_supersession_links_for_claims_and_leases():
    plane = AgentInternetControlPlane()
    plane.grant_space_claim(SpaceClaimRecord(claim_id="claim-1", source_intent_id="intent-space-1", subject_id="operator-1", space_id="space-1", granted_at=20.0))
    plane.grant_space_claim(SpaceClaimRecord(claim_id="claim-2", source_intent_id="intent-space-2", subject_id="operator-1", space_id="space-1", granted_at=30.0))
    plane.upsert_slot(SlotDescriptor(slot_id="slot-1", space_id="space-1", slot_kind="general", holder_subject_id="operator-1", status=SlotStatus.ACTIVE))
    plane.grant_slot_lease(SlotLeaseRecord(lease_id="lease-1", source_intent_id="intent-slot-1", holder_subject_id="operator-1", space_id="space-1", slot_id="slot-1", status=LeaseStatus.ACTIVE, granted_at=21.0))
    plane.grant_slot_lease(SlotLeaseRecord(lease_id="lease-2", source_intent_id="intent-slot-2", holder_subject_id="operator-2", space_id="space-1", slot_id="slot-1", status=LeaseStatus.ACTIVE, granted_at=31.0))
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="observer", scopes=(LotusApiScope.READ.value,), token_secret="claims-history-token", now=10.0)

    claims = api.call(bearer_token=issued.secret, action="list_space_claims", params={})
    leases = api.call(bearer_token=issued.secret, action="list_slot_leases", params={})

    assert claims["space_claims"][0]["superseded_by_claim_id"] == "claim-2"
    assert claims["space_claims"][1]["supersedes_claim_id"] == "claim-1"
    assert leases["slot_leases"][0]["superseded_by_lease_id"] == "lease-2"
    assert leases["slot_leases"][1]["supersedes_lease_id"] == "lease-1"


def test_lotus_api_transitions_claims_and_leases():
    plane = AgentInternetControlPlane()
    plane.upsert_slot(SlotDescriptor(slot_id="slot-1", space_id="space-1", slot_kind="general", holder_subject_id="operator-1", status=SlotStatus.ACTIVE))
    plane.upsert_space_claim(SpaceClaimRecord(claim_id="claim-1", source_intent_id="intent-space-1", subject_id="operator-1", space_id="space-1", granted_at=20.0))
    plane.upsert_slot_lease(SlotLeaseRecord(lease_id="lease-1", source_intent_id="intent-slot-1", holder_subject_id="operator-1", space_id="space-1", slot_id="slot-1", status=LeaseStatus.ACTIVE, granted_at=21.0))
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="governor", scopes=(LotusApiScope.CONTRACT_WRITE.value,), token_secret="claims-write-token", now=10.0)

    claim = api.call(bearer_token=issued.secret, action="release_space_claim", params={"claim_id": "claim-1", "now": 30.0})
    lease = api.call(bearer_token=issued.secret, action="expire_slot_lease", params={"lease_id": "lease-1", "now": 40.0})

    assert claim["space_claim"]["status"] == ClaimStatus.RELEASED.value
    assert claim["space_claim"]["released_at"] == 30.0
    assert lease["slot_lease"]["status"] == LeaseStatus.EXPIRED.value
    assert lease["slot_lease"]["expires_at"] == 40.0
    assert plane.registry.get_slot("slot-1").status == SlotStatus.DORMANT


def test_lotus_api_replays_claim_and_lease_lifecycle_request_ids():
    plane = AgentInternetControlPlane()
    plane.upsert_space_claim(
        SpaceClaimRecord(
            claim_id="claim-1",
            source_intent_id="intent-space-1",
            subject_id="operator-1",
            space_id="space-1",
            granted_at=20.0,
        )
    )
    plane.upsert_slot(SlotDescriptor(slot_id="slot-1", space_id="space-1", slot_kind="general", holder_subject_id="operator-1", status=SlotStatus.ACTIVE))
    plane.upsert_slot_lease(
        SlotLeaseRecord(
            lease_id="lease-1",
            source_intent_id="intent-slot-1",
            holder_subject_id="operator-1",
            space_id="space-1",
            slot_id="slot-1",
            status=LeaseStatus.ACTIVE,
            granted_at=21.0,
        )
    )
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="governor", scopes=(LotusApiScope.CONTRACT_WRITE.value,), token_secret="claims-write-token", now=10.0)

    claim_first = api.call(
        bearer_token=issued.secret,
        action="release_space_claim",
        params={"request_id": "req-claim-1", "claim_id": "claim-1", "now": 30.0},
    )
    claim_second = api.call(
        bearer_token=issued.secret,
        action="release_space_claim",
        params={"request_id": "req-claim-1", "claim_id": "claim-1", "now": 35.0},
    )
    lease_first = api.call(
        bearer_token=issued.secret,
        action="expire_slot_lease",
        params={"request_id": "req-lease-1", "lease_id": "lease-1", "now": 40.0},
    )
    lease_second = api.call(
        bearer_token=issued.secret,
        action="expire_slot_lease",
        params={"request_id": "req-lease-1", "lease_id": "lease-1", "now": 45.0},
    )

    assert claim_second["space_claim"] == claim_first["space_claim"]
    assert claim_first["receipt"]["applied"] is True
    assert claim_second["receipt"]["replayed"] is True
    assert lease_second["slot_lease"] == lease_first["slot_lease"]
    assert lease_first["receipt"]["applied"] is True
    assert lease_second["receipt"]["replayed"] is True


def test_lotus_api_rejects_claim_lifecycle_request_id_payload_conflict():
    plane = AgentInternetControlPlane()
    plane.upsert_space_claim(
        SpaceClaimRecord(
            claim_id="claim-1",
            source_intent_id="intent-space-1",
            subject_id="operator-1",
            space_id="space-1",
            granted_at=20.0,
        )
    )
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="governor", scopes=(LotusApiScope.CONTRACT_WRITE.value,), token_secret="claims-write-token", now=10.0)

    api.call(
        bearer_token=issued.secret,
        action="release_space_claim",
        params={"request_id": "req-claim-1", "claim_id": "claim-1", "now": 30.0},
    )

    with pytest.raises(ValueError, match="idempotency_conflict:release_space_claim:req-claim-1"):
        api.call(
            bearer_token=issued.secret,
            action="release_space_claim",
            params={"request_id": "req-claim-1", "claim_id": "claim-2", "now": 30.0},
        )


def test_lotus_api_sweeps_expired_grants():
    plane = AgentInternetControlPlane()
    plane.upsert_space_claim(SpaceClaimRecord(claim_id="claim-due", source_intent_id="intent-space-due", subject_id="operator-1", space_id="space-1", status=ClaimStatus.GRANTED, granted_at=20.0, expires_at=40.0))
    plane.upsert_space_claim(SpaceClaimRecord(claim_id="claim-future", source_intent_id="intent-space-future", subject_id="operator-1", space_id="space-1", status=ClaimStatus.GRANTED, granted_at=21.0, expires_at=60.0))
    plane.upsert_slot(SlotDescriptor(slot_id="slot-due", space_id="space-1", slot_kind="general", holder_subject_id="operator-1", status=SlotStatus.ACTIVE))
    plane.upsert_slot(SlotDescriptor(slot_id="slot-future", space_id="space-1", slot_kind="general", holder_subject_id="operator-2", status=SlotStatus.ACTIVE))
    plane.upsert_slot_lease(SlotLeaseRecord(lease_id="lease-due", source_intent_id="intent-slot-due", holder_subject_id="operator-1", space_id="space-1", slot_id="slot-due", status=LeaseStatus.ACTIVE, granted_at=22.0, expires_at=40.0))
    plane.upsert_slot_lease(SlotLeaseRecord(lease_id="lease-future", source_intent_id="intent-slot-future", holder_subject_id="operator-2", space_id="space-1", slot_id="slot-future", status=LeaseStatus.ACTIVE, granted_at=23.0, expires_at=60.0))
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="governor", scopes=(LotusApiScope.CONTRACT_WRITE.value,), token_secret="claims-sweep-token", now=10.0)

    swept = api.call(bearer_token=issued.secret, action="sweep_expired_grants", params={"now": 50.0})

    assert swept["grant_sweep"] == {
        "checked_at": 50.0,
        "expired_space_claim_ids": ("claim-due",),
        "expired_slot_lease_ids": ("lease-due",),
        "expired_space_claim_count": 1,
        "expired_slot_lease_count": 1,
    }
    assert plane.registry.get_space_claim("claim-due").status == ClaimStatus.EXPIRED
    assert plane.registry.get_space_claim("claim-future").status == ClaimStatus.GRANTED
    assert plane.registry.get_slot_lease("lease-due").status == LeaseStatus.EXPIRED
    assert plane.registry.get_slot_lease("lease-future").status == LeaseStatus.ACTIVE
    assert plane.registry.get_slot("slot-due").status == SlotStatus.DORMANT


def test_lotus_api_rejects_request_id_payload_conflict():
    plane = AgentInternetControlPlane()
    plane.register_city(
        CityIdentity(city_id="city-a", slug="a", repo="org/city-a"),
        CityEndpoint(city_id="city-a", transport="filesystem", location="/tmp/city-a"),
    )
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="operator",
        scopes=(LotusApiScope.SERVICE_WRITE.value,),
        token_secret="service-token",
        token_id="tok-service",
        now=10.0,
    )
    params = {
        "request_id": "req-service-1",
        "city_id": "city-a",
        "service_name": "forum-api",
        "public_handle": "api.forum.city-a.lotus",
        "transport": "https",
        "location": "https://forum.city-a.example/api",
    }

    api.call(bearer_token=issued.secret, action="publish_service", params=params)

    with pytest.raises(ValueError, match="idempotency_conflict:publish_service:req-service-1"):
        api.call(
            bearer_token=issued.secret,
            action="publish_service",
            params={**params, "location": "https://forum.city-a.example/v2"},
        )


def test_lotus_api_lists_federation_contract_records():
    plane = AgentInternetControlPlane()
    plane.bootstrap_steward_public_wiki_contract(now=50.0)
    plane.upsert_authority_export(
        AuthorityExportRecord(
            export_id="steward-protocol/canonical-surface",
            repo_id="steward-protocol",
            export_kind=AuthorityExportKind.CANONICAL_SURFACE,
            version="2026-03-09T16:00:00Z",
            artifact_uri="agent-web://steward/canonical-surface",
            generated_at=51.0,
        ),
    )
    plane.upsert_publication_status(
        plane.registry.get_publication_status(STEWARD_PUBLIC_WIKI_BINDING_ID).__class__(
            binding_id=STEWARD_PUBLIC_WIKI_BINDING_ID,
            status=PublicationState.SUCCESS,
            projected_from_export_id="steward-protocol/canonical-surface",
            target_kind="github_wiki",
            target_locator="github.com/kimeisele/steward-protocol.wiki.git",
            published_at=52.0,
            checked_at=52.0,
        ),
    )

    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="observer", scopes=(LotusApiScope.READ.value,), token_secret="federation-token", now=10.0)

    repo_roles = api.call(bearer_token=issued.secret, action="list_repo_roles", params={})
    authority_exports = api.call(bearer_token=issued.secret, action="list_authority_exports", params={})
    projection_bindings = api.call(bearer_token=issued.secret, action="list_projection_bindings", params={})
    publication_statuses = api.call(bearer_token=issued.secret, action="list_publication_statuses", params={})

    assert {record["repo_id"] for record in repo_roles["repo_roles"]} == {"agent-internet", "steward-protocol"}
    assert authority_exports["authority_exports"][0]["export_kind"] == "canonical_surface"
    assert projection_bindings["projection_bindings"][0]["binding_id"] == STEWARD_PUBLIC_WIKI_BINDING_ID
    assert publication_statuses["publication_statuses"][0]["status"] == "success"


def test_lotus_api_imports_authority_bundle_path(tmp_path):
    plane = AgentInternetControlPlane()
    bundle_path = _write_authority_bundle(tmp_path)
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(subject="operator", scopes=(LotusApiScope.CONTRACT_WRITE.value, LotusApiScope.READ.value), token_secret="contract-token", now=10.0)

    imported = api.call(
        bearer_token=issued.secret,
        action="import_authority_bundle",
        params={"bundle_path": str(bundle_path), "now": 305.0},
    )

    assert imported["imported"]["repo_role"]["repo_id"] == "steward-protocol"
    assert imported["imported"]["authority_exports"][0]["content_sha256"]
    assert imported["imported"]["publication_statuses"][0]["status"] == "stale"
    assert plane.registry.get_publication_status(STEWARD_PUBLIC_WIKI_BINDING_ID).labels["authority_bundle_source_sha"] == "fedcba"


def test_lotus_api_lists_fork_lineage():
    plane = AgentInternetControlPlane()
    plane.upsert_fork_lineage(
        ForkLineageRecord(
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
        ),
    )
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="observer",
        scopes=(LotusApiScope.READ.value,),
        token_secret="lineage-token",
        token_id="tok-lineage",
        now=10.0,
    )

    response = api.call(bearer_token=issued.secret, action="list_fork_lineage", params={})

    assert response["fork_lineage"][0]["lineage_id"] == "lineage:city-b"
    assert response["fork_lineage"][0]["fork_mode"] == "sovereign"
    assert response["fork_lineage"][0]["sync_policy"] == "tracked"


def test_lotus_api_creates_and_lists_intents():
    plane = AgentInternetControlPlane()
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="human:ss",
        scopes=(LotusApiScope.READ.value, LotusApiScope.INTENT_WRITE.value),
        token_secret="intent-token",
        token_id="tok-intent",
        now=10.0,
    )

    created = api.call(
        bearer_token=issued.secret,
        action="create_intent",
        params={
            "intent_id": "intent:fork-city-b",
            "intent_type": IntentType.REQUEST_FORK.value,
            "title": "Fork city-b",
            "description": "Create a sovereign derivative line for city-b.",
            "repo": "org/city-b",
            "lineage_id": "lineage:city-b",
            "labels": {"channel": "public-edge"},
            "now": 123.0,
        },
    )
    listed = api.call(bearer_token=issued.secret, action="list_intents", params={})

    assert created["intent"]["intent_id"] == "intent:fork-city-b"
    assert created["intent"]["intent_type"] == "request_fork"
    assert created["intent"]["status"] == "pending"
    assert created["intent"]["requested_by_subject_id"] == "human:ss"
    assert listed["intents"][0]["lineage_id"] == "lineage:city-b"


def test_lotus_api_replays_create_intent_request_id():
    plane = AgentInternetControlPlane()
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="human:ss",
        scopes=(LotusApiScope.INTENT_WRITE.value,),
        token_secret="intent-replay-token",
        token_id="tok-intent-replay",
        now=10.0,
    )
    params = {
        "request_id": "req-intent-1",
        "intent_id": "intent:fork-city-c",
        "intent_type": IntentType.REQUEST_FORK.value,
        "title": "Fork city-c",
        "description": "Create a sovereign derivative line for city-c.",
        "repo": "org/city-c",
        "lineage_id": "lineage:city-c",
        "now": 123.0,
    }

    first = api.call(bearer_token=issued.secret, action="create_intent", params=params)
    second = api.call(
        bearer_token=issued.secret,
        action="create_intent",
        params={**params, "now": 456.0},
    )

    assert first["intent"]["intent_id"] == "intent:fork-city-c"
    assert second["intent"] == first["intent"]
    assert first["receipt"]["request_id"] == "req-intent-1"
    assert first["receipt"]["applied"] is True
    assert first["receipt"]["replayed"] is False
    assert second["receipt"]["applied"] is False
    assert second["receipt"]["replayed"] is True
    assert second["receipt"]["replay_count"] == 1
    assert plane.registry.list_operation_receipts()[0].action == "create_intent"


def test_lotus_api_allows_delegated_intent_subject_with_explicit_scope():
    plane = AgentInternetControlPlane()
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="verified-bridge",
        scopes=(
            LotusApiScope.INTENT_WRITE.value,
            LotusApiScope.INTENT_SUBJECT_DELEGATE.value,
        ),
        token_secret="intent-delegate-token",
        token_id="tok-intent-delegate",
        now=10.0,
    )

    created = api.call(
        bearer_token=issued.secret,
        action="create_intent",
        params={
            "intent_id": "intent:verified-city-b",
            "intent_type": IntentType.REQUEST_PR_DRAFT.value,
            "title": "Verified draft PR",
            "requested_by_subject_id": "verified_agent:agent_ss",
            "now": 123.0,
        },
    )

    assert created["intent"]["requested_by_subject_id"] == "verified_agent:agent_ss"


def test_lotus_api_rejects_delegated_intent_subject_without_scope():
    plane = AgentInternetControlPlane()
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="verified-bridge",
        scopes=(LotusApiScope.INTENT_WRITE.value,),
        token_secret="intent-no-delegate-token",
        token_id="tok-intent-no-delegate",
        now=10.0,
    )

    with pytest.raises(PermissionError, match=f"missing_scopes:{LotusApiScope.INTENT_SUBJECT_DELEGATE.value}"):
        api.call(
            bearer_token=issued.secret,
            action="create_intent",
            params={
                "intent_id": "intent:verified-city-b",
                "intent_type": IntentType.REQUEST_PR_DRAFT.value,
                "title": "Verified draft PR",
                "requested_by_subject_id": "verified_agent:agent_ss",
                "now": 123.0,
            },
        )


def test_lotus_api_gets_single_intent():
    plane = AgentInternetControlPlane()
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="human:ss",
        scopes=(LotusApiScope.READ.value, LotusApiScope.INTENT_WRITE.value),
        token_secret="intent-token-single",
        token_id="tok-intent-single",
        now=10.0,
    )
    api.call(
        bearer_token=issued.secret,
        action="create_intent",
        params={
            "intent_id": "intent:single-city-b",
            "intent_type": IntentType.REQUEST_SLOT.value,
            "title": "Single slot",
            "now": 123.0,
        },
    )

    fetched = api.call(
        bearer_token=issued.secret,
        action="get_intent",
        params={"intent_id": "intent:single-city-b"},
    )

    assert fetched["intent"]["intent_id"] == "intent:single-city-b"
    assert fetched["intent"]["status"] == "pending"


def test_lotus_api_transitions_intents():
    plane = AgentInternetControlPlane()
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="operator",
        scopes=(LotusApiScope.READ.value, LotusApiScope.INTENT_WRITE.value, LotusApiScope.INTENT_REVIEW.value),
        token_secret="intent-review-token",
        token_id="tok-intent-review",
        now=10.0,
    )
    api.call(
        bearer_token=issued.secret,
        action="create_intent",
        params={
            "intent_id": "intent:claim-city-b",
            "intent_type": IntentType.REQUEST_SPACE_CLAIM.value,
            "title": "Claim city-b",
            "now": 123.0,
        },
    )

    accepted = api.call(
        bearer_token=issued.secret,
        action="accept_intent",
        params={"intent_id": "intent:claim-city-b", "now": 124.0},
    )
    fulfilled = api.call(
        bearer_token=issued.secret,
        action="fulfill_intent",
        params={"intent_id": "intent:claim-city-b", "now": 125.0},
    )

    assert accepted["intent"]["status"] == IntentStatus.ACCEPTED.value
    assert fulfilled["intent"]["status"] == IntentStatus.FULFILLED.value
    assert fulfilled["intent"]["updated_at"] == 125.0


def test_lotus_api_rejects_intent_transition_without_review_scope():
    plane = AgentInternetControlPlane()
    api = LotusControlPlaneAPI(plane)
    issued = api.issue_token(
        subject="human:ss",
        scopes=(LotusApiScope.INTENT_WRITE.value,),
        token_secret="intent-write-only",
        token_id="tok-intent-write-only",
        now=10.0,
    )
    api.call(
        bearer_token=issued.secret,
        action="create_intent",
        params={
            "intent_id": "intent:slot-city-b",
            "intent_type": IntentType.REQUEST_SLOT.value,
            "now": 123.0,
        },
    )

    with pytest.raises(PermissionError, match="missing_scopes"):
        api.call(
            bearer_token=issued.secret,
            action="accept_intent",
            params={"intent_id": "intent:slot-city-b", "now": 124.0},
        )