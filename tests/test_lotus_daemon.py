import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from agent_internet.lotus_api import LotusControlPlaneAPI
from agent_internet.lotus_daemon import LotusApiDaemon
from agent_internet.models import (
    AssistantSurfaceSnapshot,
    CityEndpoint,
    CityIdentity,
    CityPresence,
    ForkLineageRecord,
    ForkMode,
    HealthStatus,
    IntentStatus,
    IntentType,
    LotusApiScope,
    TrustLevel,
    TrustRecord,
    UpstreamSyncPolicy,
)
from agent_internet.agent_web_source_registry import upsert_agent_web_source_registry_entry
from agent_internet.agent_web_semantic_overlay import upsert_agent_web_semantic_bridge
from agent_internet.snapshot import ControlPlaneStateStore


def _request_json(base_url: str, path: str, *, method: str = "GET", token: str = "", payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(f"{base_url}{path}", data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_lotus_daemon_serves_authenticated_http_api(tmp_path):
    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="root",
            scopes=(LotusApiScope.READ.value, LotusApiScope.SERVICE_WRITE.value, LotusApiScope.TOKEN_WRITE.value),
            token_secret="root-secret",
            token_id="tok-root",
        ).secret,
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()

    try:
        status, health = _request_json(daemon.base_url, "/healthz")
        assert status == 200
        assert health["status"] == "ok"

        status, issued = _request_json(
            daemon.base_url,
            "/v1/lotus/tokens",
            method="POST",
            token=root_secret,
            payload={
                "subject": "operator",
                "scopes": [LotusApiScope.READ.value, LotusApiScope.SERVICE_WRITE.value],
                "token_id": "tok-operator",
            },
        )
        assert status == 200
        operator_secret = issued["secret"]

        status, published = _request_json(
            daemon.base_url,
            "/v1/lotus/services",
            method="POST",
            token=operator_secret,
            payload={
                "city_id": "city-a",
                "service_name": "forum-api",
                "public_handle": "api.forum.city-a.lotus",
                "transport": "https",
                "location": "https://forum.city-a.example/api",
                "required_scopes": [LotusApiScope.READ.value],
            },
        )
        assert status == 200
        assert published["service_address"]["service_id"] == "city-a:forum-api"

        status, resolved = _request_json(
            daemon.base_url,
            "/v1/lotus/services/city-a/forum-api",
            token=operator_secret,
        )
        assert status == 200
        assert resolved["resolved"]["location"] == "https://forum.city-a.example/api"
    finally:
        daemon.shutdown()


def test_lotus_daemon_rejects_missing_auth(tmp_path):
    daemon = LotusApiDaemon(state_path=tmp_path / "state" / "control_plane.json", port=0)
    daemon.start_in_thread()

    try:
        with pytest.raises(HTTPError) as exc_info:
            _request_json(daemon.base_url, "/v1/lotus/state")
        assert exc_info.value.code == 401
        payload = json.loads(exc_info.value.read().decode("utf-8"))
        assert payload["error"] == "missing_bearer_token"
    finally:
        daemon.shutdown()


def test_lotus_daemon_serves_route_resolution_http_api(tmp_path):
    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="root",
            scopes=(LotusApiScope.READ.value, LotusApiScope.SERVICE_WRITE.value),
            token_secret="route-root",
            token_id="tok-route-root",
        ).secret,
    )
    store.update(
        lambda plane: (
            plane.register_city(
                CityIdentity(city_id="city-b", slug="b", repo="org/city-b"),
                CityEndpoint(city_id="city-b", transport="git", location="https://example/city-b.git"),
            ),
            plane.announce_city(CityPresence(city_id="city-b", health=HealthStatus.HEALTHY)),
            plane.record_trust(TrustRecord("city-a", "city-b", TrustLevel.TRUSTED, reason="route daemon test")),
        ),
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()

    try:
        status, published = _request_json(
            daemon.base_url,
            "/v1/lotus/routes",
            method="POST",
            token=root_secret,
            payload={
                "owner_city_id": "city-a",
                "destination_prefix": "service:city-z/forum",
                "target_city_id": "city-z",
                "next_hop_city_id": "city-b",
                "metric": 5,
                "nadi_priority": "suddha",
            },
        )
        assert status == 200
        assert published["route"]["nadi_type"] == "vyana"
        assert published["route"]["priority"] == "suddha"
        assert published["route"]["nadi_priority"] == "suddha"

        status, resolved = _request_json(
            daemon.base_url,
            "/v1/lotus/routes/city-a/service%3Acity-z%2Fforum-api",
            token=root_secret,
        )
        assert status == 200
        assert resolved["resolved"]["next_hop_city_id"] == "city-b"
        assert resolved["resolved"]["nadi_priority"] == "suddha"
    finally:
        daemon.shutdown()


def test_lotus_daemon_serves_assistant_snapshot_http_api(tmp_path):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_7.json").write_text(
        json.dumps(
            {
                "heartbeat": 7,
                "timestamp": 70.0,
                "population": 1,
                "alive": 1,
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
        json.dumps({"followed": ["alice", "bob"], "ops": {"invites": 3}}),
    )
    (repo_root / "data" / "federation" / "peer.json").write_text(
        json.dumps({"identity": {"city_id": "city-http", "slug": "http", "repo": "org/city-http"}, "capabilities": ["moltbook"]}),
    )

    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="root",
            scopes=(LotusApiScope.READ.value,),
            token_secret="snapshot-root",
            token_id="tok-snapshot-root",
        ).secret,
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()

    try:
        status, payload = _request_json(
            daemon.base_url,
            f"/v1/lotus/assistant-snapshot?root={repo_root}",
            token=root_secret,
        )
        assert status == 200
        assert payload["assistant_snapshot"]["city_id"] == "city-http"
        assert payload["assistant_snapshot"]["heartbeat"] == 7
        assert payload["assistant_snapshot"]["following"] == 2
        assert payload["assistant_snapshot"]["total_invites"] == 3
        assert payload["assistant_snapshot"]["active_campaigns"][0]["title"] == "Internet adaptation"
    finally:
        daemon.shutdown()


def test_lotus_daemon_serves_agent_web_manifest_http_api(tmp_path):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_7.json").write_text(
        json.dumps(
            {
                "heartbeat": 7,
                "timestamp": 70.0,
                "population": 1,
                "alive": 1,
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
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 1}}))
    (repo_root / "data" / "federation" / "peer.json").write_text(
        json.dumps({"identity": {"city_id": "city-http", "slug": "http", "repo": "org/city-http"}, "capabilities": ["moltbook"]}),
    )

    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="root",
            scopes=(LotusApiScope.READ.value, LotusApiScope.TOKEN_WRITE.value),
            token_secret="root-secret",
            token_id="tok-root",
        ).secret,
    )
    store.update(
        lambda plane: plane.publish_assistant_surface(
            AssistantSurfaceSnapshot(
                assistant_id="moltbook_assistant",
                assistant_kind="moltbook_assistant",
                city_id="city-http",
                city_slug="http",
                repo="org/city-http",
                heartbeat_source="steward-protocol/mahamantra",
                heartbeat=7,
                state_present=True,
                total_posts=1,
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
        ),
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()
    try:
        status, payload = _request_json(
            daemon.base_url,
            f"/v1/lotus/agent-web-manifest?root={repo_root}",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_manifest"]["identity"]["city_id"] == "city-http"
        assert payload["agent_web_manifest"]["campaigns"][0]["id"] == "internet-adaptation"
        assert any(link["rel"] == "wiki_home" for link in payload["agent_web_manifest"]["links"])

        status, payload = _request_json(
            daemon.base_url,
            "/v1/lotus/agent-web-semantic-capabilities",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_semantic_capabilities"]["capabilities"][0]["http"]["href"].startswith(daemon.base_url)

        status, payload = _request_json(
            daemon.base_url,
            "/v1/lotus/agent-web-semantic-contracts?capability_id=semantic_neighbors",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_semantic_contracts"]["contract_id"] == "semantic_neighbors.v1"

        status, payload = _request_json(
            daemon.base_url,
            "/v1/lotus/agent-web-semantic-contracts?contract_id=semantic_expand.v1",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_semantic_contracts"]["capability_id"] == "semantic_expand"

        status, payload = _request_json(
            daemon.base_url,
            "/v1/lotus/agent-web-semantic-contracts?capability_id=semantic_federated_search&version=1",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_semantic_contracts"]["version"] == 1

        status, payload = _request_json(
            daemon.base_url,
            "/v1/lotus/agent-web-repo-graph-capabilities",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_repo_graph_capabilities"]["capabilities"][0]["capability_id"] == "repo_graph_snapshot"

        status, payload = _request_json(
            daemon.base_url,
            "/v1/lotus/agent-web-repo-graph-contracts?contract_id=repo_graph_context.v1",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_repo_graph_contracts"]["capability_id"] == "repo_graph_context"
    finally:
        daemon.shutdown()


def test_lotus_daemon_serves_repo_graph_http_api(tmp_path, monkeypatch):
    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="root",
            scopes=(LotusApiScope.READ.value, LotusApiScope.SERVICE_WRITE.value, LotusApiScope.TOKEN_WRITE.value),
            token_secret="root-secret",
            token_id="tok-root",
        ).secret,
    )
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
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()
    root = tmp_path / "steward-protocol"
    root.mkdir()

    try:
        status, payload = _request_json(
            daemon.base_url,
            f"/v1/lotus/agent-web-repo-graph?root={root}",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_repo_graph"]["kind"] == "agent_web_repo_graph_snapshot"

        status, payload = _request_json(
            daemon.base_url,
            f"/v1/lotus/agent-web-repo-graph-neighbors?root={root}&node_id=module.city",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_repo_graph_neighbors"]["record"]["node_id"] == "module.city"

        status, payload = _request_json(
            daemon.base_url,
            f"/v1/lotus/agent-web-repo-graph-context?root={root}&concept=heartbeat",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_repo_graph_context"]["concept"] == "heartbeat"
    finally:
        daemon.shutdown()


def test_lotus_daemon_serves_agent_web_graph_http_api(tmp_path):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_7.json").write_text(
        json.dumps(
            {
                "heartbeat": 7,
                "timestamp": 70.0,
                "population": 1,
                "alive": 1,
                "dead": 0,
                "chain_valid": True,
                "active_campaigns": [{"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]}],
            },
        ),
    )
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 1}}))
    (repo_root / "data" / "federation" / "peer.json").write_text(
        json.dumps({"identity": {"city_id": "city-http", "slug": "http", "repo": "org/city-http"}, "capabilities": ["moltbook"]}),
    )

    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="root",
            scopes=(LotusApiScope.READ.value, LotusApiScope.TOKEN_WRITE.value),
            token_secret="root-secret",
            token_id="tok-root",
        ).secret,
    )
    store.update(
        lambda plane: plane.publish_assistant_surface(
            AssistantSurfaceSnapshot(
                assistant_id="moltbook_assistant",
                assistant_kind="moltbook_assistant",
                city_id="city-http",
                city_slug="http",
                repo="org/city-http",
                heartbeat_source="steward-protocol/mahamantra",
                heartbeat=7,
                state_present=True,
                total_posts=1,
                active_campaigns=({"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]},),
            ),
        ),
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()
    try:
        status, payload = _request_json(
            daemon.base_url,
            f"/v1/lotus/agent-web-graph?root={repo_root}",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_graph"]["kind"] == "agent_web_public_graph"
        assert any(node["node_id"] == "document:public_graph" for node in payload["agent_web_graph"]["nodes"])
    finally:
        daemon.shutdown()


def test_lotus_daemon_serves_agent_web_index_and_search_http_api(tmp_path):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_7.json").write_text(
        json.dumps(
            {
                "heartbeat": 7,
                "timestamp": 70.0,
                "population": 1,
                "alive": 1,
                "dead": 0,
                "chain_valid": True,
                "active_campaigns": [{"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]}],
            },
        ),
    )
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 1}}))
    (repo_root / "data" / "federation" / "peer.json").write_text(
        json.dumps({"identity": {"city_id": "city-http", "slug": "http", "repo": "org/city-http"}, "capabilities": ["moltbook"]}),
    )

    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="root",
            scopes=(LotusApiScope.READ.value, LotusApiScope.TOKEN_WRITE.value),
            token_secret="root-secret",
            token_id="tok-root",
        ).secret,
    )
    store.update(
        lambda plane: plane.publish_assistant_surface(
            AssistantSurfaceSnapshot(
                assistant_id="moltbook_assistant",
                assistant_kind="moltbook_assistant",
                city_id="city-http",
                city_slug="http",
                repo="org/city-http",
                heartbeat_source="steward-protocol/mahamantra",
                heartbeat=7,
                state_present=True,
                total_posts=1,
                active_campaigns=({"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]},),
            ),
        ),
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()
    try:
        status, payload = _request_json(
            daemon.base_url,
            f"/v1/lotus/agent-web-index?root={repo_root}",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_index"]["kind"] == "agent_web_search_index"
        assert any(record["record_id"] == "document:search_index" for record in payload["agent_web_index"]["records"])

        status, payload = _request_json(
            daemon.base_url,
            f"/v1/lotus/agent-web-search?root={repo_root}&q=internet%20adaptation&limit=3",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_search"]["kind"] == "agent_web_search_results"
        assert payload["agent_web_search"]["results"][0]["kind"] == "campaign"
    finally:
        daemon.shutdown()


def test_lotus_daemon_serves_agent_web_crawl_and_search_http_api(tmp_path):
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
        (reports_dir / "report_7.json").write_text(
            json.dumps(
                {
                    "heartbeat": 7,
                    "timestamp": 70.0,
                    "population": 1,
                    "alive": 1,
                    "dead": 0,
                    "chain_valid": True,
                    "active_campaigns": [{"id": campaign_title.lower().replace(' ', '-'), "title": campaign_title, "north_star": campaign_title, "status": "active", "last_gap_summary": ["keep execution bounded"]}],
                },
            ),
        )

    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="root",
            scopes=(LotusApiScope.READ.value, LotusApiScope.TOKEN_WRITE.value),
            token_secret="root-secret",
            token_id="tok-root",
        ).secret,
    )
    store.update(
        lambda plane: (
            plane.publish_assistant_surface(
                AssistantSurfaceSnapshot(
                    assistant_id="moltbook_assistant",
                    assistant_kind="moltbook_assistant",
                    city_id="city-a",
                    city_slug="city-a",
                    repo="org/city-a",
                    heartbeat_source="steward-protocol/mahamantra",
                    heartbeat=7,
                    state_present=True,
                    total_posts=1,
                    active_campaigns=(),
                ),
            ),
            plane.publish_assistant_surface(
                AssistantSurfaceSnapshot(
                    assistant_id="moltbook_assistant",
                    assistant_kind="moltbook_assistant",
                    city_id="city-b",
                    city_slug="city-b",
                    repo="org/city-b",
                    heartbeat_source="steward-protocol/mahamantra",
                    heartbeat=7,
                    state_present=True,
                    total_posts=1,
                    active_campaigns=(),
                ),
            ),
            plane.publish_service_address(
                owner_city_id="city-a",
                service_name="forum",
                public_handle="forum.city-a.lotus",
                transport="https",
                location="https://forum.city-a.lotus",
                auth_required=False,
            ),
            plane.publish_service_address(
                owner_city_id="city-b",
                service_name="market",
                public_handle="market.city-b.lotus",
                transport="https",
                location="https://market.city-b.lotus",
                auth_required=False,
            ),
        ),
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()
    try:
        status, payload = _request_json(
            daemon.base_url,
            f"/v1/lotus/agent-web-crawl?root={repo_a}&root={repo_b}",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_crawl"]["kind"] == "agent_web_crawl_bootstrap"
        assert payload["agent_web_crawl"]["stats"]["source_count"] == 2

        status, payload = _request_json(
            daemon.base_url,
            f"/v1/lotus/agent-web-crawl-search?root={repo_a}&root={repo_b}&q=marketplace&limit=3",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_crawl_search"]["kind"] == "agent_web_crawl_search_results"
        assert payload["agent_web_crawl_search"]["results"][0]["source_city_id"] == "city-b"
    finally:
        daemon.shutdown()


def test_lotus_daemon_serves_source_registry_and_registry_crawl_http_api(tmp_path):
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
        (reports_dir / "report_8.json").write_text(json.dumps({"heartbeat": 8, "timestamp": 80.0, "population": 1, "alive": 1, "dead": 0, "chain_valid": True, "active_campaigns": [{"id": campaign_title.lower().replace(' ', '-'), "title": campaign_title, "north_star": campaign_title, "status": "active", "last_gap_summary": ["keep execution bounded"]}]}))
    upsert_agent_web_source_registry_entry(registry_path, root=repo_a)
    upsert_agent_web_source_registry_entry(registry_path, root=repo_b, source_id="city-b-source")

    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(lambda plane: LotusControlPlaneAPI(plane).issue_token(subject="root", scopes=(LotusApiScope.READ.value, LotusApiScope.TOKEN_WRITE.value), token_secret="root-secret", token_id="tok-root").secret)
    store.update(
        lambda plane: (
            plane.publish_assistant_surface(AssistantSurfaceSnapshot(assistant_id="moltbook_assistant", assistant_kind="moltbook_assistant", city_id="city-a", city_slug="city-a", repo="org/city-a", heartbeat_source="steward-protocol/mahamantra", heartbeat=8, state_present=True, total_posts=1, active_campaigns=())),
            plane.publish_assistant_surface(AssistantSurfaceSnapshot(assistant_id="moltbook_assistant", assistant_kind="moltbook_assistant", city_id="city-b", city_slug="city-b", repo="org/city-b", heartbeat_source="steward-protocol/mahamantra", heartbeat=8, state_present=True, total_posts=1, active_campaigns=())),
            plane.publish_service_address(owner_city_id="city-a", service_name="forum", public_handle="forum.city-a.lotus", transport="https", location="https://forum.city-a.lotus", auth_required=False),
            plane.publish_service_address(owner_city_id="city-b", service_name="market", public_handle="market.city-b.lotus", transport="https", location="https://market.city-b.lotus", auth_required=False),
        ),
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()
    try:
        status, payload = _request_json(daemon.base_url, f"/v1/lotus/agent-web-source-registry?registry_path={registry_path}", token=root_secret)
        assert status == 200
        assert payload["agent_web_source_registry"]["stats"]["source_count"] == 2

        status, payload = _request_json(daemon.base_url, f"/v1/lotus/agent-web-crawl-registry?registry_path={registry_path}", token=root_secret)
        assert status == 200
        assert payload["agent_web_crawl_registry"]["registry"]["enabled_source_count"] == 2

        status, payload = _request_json(daemon.base_url, f"/v1/lotus/agent-web-crawl-registry-search?registry_path={registry_path}&q=marketplace&limit=3", token=root_secret)
        assert status == 200
        assert payload["agent_web_crawl_registry_search"]["results"][0]["source_city_id"] == "city-b"
    finally:
        daemon.shutdown()


def test_lotus_daemon_refreshes_and_reads_federated_index_http_api(tmp_path):
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
        (reports_dir / "report_10.json").write_text(json.dumps({"heartbeat": 10, "timestamp": 100.0, "population": 1, "alive": 1, "dead": 0, "chain_valid": True, "active_campaigns": [{"id": campaign_title.lower().replace(' ', '-'), "title": campaign_title, "north_star": campaign_title, "status": "active", "last_gap_summary": ["keep execution bounded"]}]}))
    upsert_agent_web_source_registry_entry(registry_path, root=repo_a)
    upsert_agent_web_source_registry_entry(registry_path, root=repo_b)
    wordnet_path.write_text('{"synsets": ["market.n.01", "commerce.n.01"], "words": {"w1": {"t": ["bazaar"], "c": [0, 1]}, "w2": {"t": ["marketplace"], "c": [0, 1]}, "w3": {"t": ["commerce"], "c": [0, 1]}}}')
    upsert_agent_web_semantic_bridge(overlay_path, bridge_kind="wordnet", terms=["marketplace"], expansions=["commerce"], weight=0.8)

    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(lambda plane: LotusControlPlaneAPI(plane).issue_token(subject="root", scopes=(LotusApiScope.READ.value, LotusApiScope.TOKEN_WRITE.value), token_secret="root-secret", token_id="tok-root").secret)
    store.update(
        lambda plane: (
            plane.publish_assistant_surface(AssistantSurfaceSnapshot(assistant_id="moltbook_assistant", assistant_kind="moltbook_assistant", city_id="city-a", city_slug="city-a", repo="org/city-a", heartbeat_source="steward-protocol/mahamantra", heartbeat=10, state_present=True, total_posts=1, active_campaigns=())),
            plane.publish_assistant_surface(AssistantSurfaceSnapshot(assistant_id="moltbook_assistant", assistant_kind="moltbook_assistant", city_id="city-b", city_slug="city-b", repo="org/city-b", heartbeat_source="steward-protocol/mahamantra", heartbeat=10, state_present=True, total_posts=1, active_campaigns=())),
            plane.publish_service_address(owner_city_id="city-a", service_name="forum", public_handle="forum.city-a.lotus", transport="https", location="https://forum.city-a.lotus", auth_required=False),
            plane.publish_service_address(owner_city_id="city-b", service_name="market", public_handle="market.city-b.lotus", transport="https", location="https://market.city-b.lotus", auth_required=False),
        ),
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()
    try:
        status, payload = _request_json(daemon.base_url, "/v1/lotus/agent-web-federated-index/refresh", method="POST", token=root_secret, payload={"index_path": str(index_path), "registry_path": str(registry_path), "overlay_path": str(overlay_path), "wordnet_path": str(wordnet_path), "now": 123.0})
        assert status == 200
        assert payload["agent_web_federated_index"]["refreshed_at"] == 123.0
        assert payload["agent_web_federated_index"]["semantic_graph"]["stats"]["edge_count"] > 0

        status, payload = _request_json(daemon.base_url, f"/v1/lotus/agent-web-federated-index?index_path={index_path}", token=root_secret)
        assert status == 200
        assert payload["agent_web_federated_index"]["stats"]["source_count"] == 2
        semantic_record_id = payload["agent_web_federated_index"]["records"][0]["record_id"]

        status, payload = _request_json(daemon.base_url, f"/v1/lotus/agent-web-semantic-neighbors?index_path={index_path}&record_id={semantic_record_id}&limit=2", token=root_secret)
        assert status == 200
        assert payload["agent_web_semantic_neighbors"]["kind"] == "agent_web_semantic_neighbors"

        status, payload = _request_json(daemon.base_url, f"/v1/lotus/agent-web-semantic-overlay?overlay_path={overlay_path}", token=root_secret)
        assert status == 200
        assert payload["agent_web_semantic_overlay"]["stats"]["bridge_count"] == 1

        status, payload = _request_json(daemon.base_url, f"/v1/lotus/agent-web-semantic-expand?overlay_path={overlay_path}&wordnet_path={wordnet_path}&q=bazaar", token=root_secret)
        assert status == 200
        assert "marketplace" in payload["agent_web_semantic_expand"]["expanded_terms"]

        status, payload = _request_json(daemon.base_url, f"/v1/lotus/agent-web-federated-search?index_path={index_path}&overlay_path={overlay_path}&wordnet_path={wordnet_path}&q=bazaar&limit=3", token=root_secret)
        assert status == 200
        assert payload["agent_web_federated_search"]["results"][0]["source_city_id"] == "city-b"
        assert payload["agent_web_federated_search"]["wordnet_bridge"]["available"] is True
        assert payload["agent_web_federated_search"]["results"][0]["why_matched"]["expanded_term_matches"]
    finally:
        daemon.shutdown()


def test_lotus_daemon_serves_agent_web_document_http_api(tmp_path):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_7.json").write_text(
        json.dumps(
            {
                "heartbeat": 7,
                "timestamp": 70.0,
                "population": 1,
                "alive": 1,
                "dead": 0,
                "chain_valid": True,
                "active_campaigns": [{"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]}],
            },
        ),
    )
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 1}}))
    (repo_root / "data" / "federation" / "peer.json").write_text(
        json.dumps({"identity": {"city_id": "city-http", "slug": "http", "repo": "org/city-http"}, "capabilities": ["moltbook"]}),
    )

    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="root",
            scopes=(LotusApiScope.READ.value, LotusApiScope.TOKEN_WRITE.value),
            token_secret="root-secret",
            token_id="tok-root",
        ).secret,
    )
    store.update(
        lambda plane: plane.publish_assistant_surface(
            AssistantSurfaceSnapshot(
                assistant_id="moltbook_assistant",
                assistant_kind="moltbook_assistant",
                city_id="city-http",
                city_slug="http",
                repo="org/city-http",
                heartbeat_source="steward-protocol/mahamantra",
                heartbeat=7,
                state_present=True,
                total_posts=1,
                active_campaigns=({"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]},),
            ),
        ),
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()
    try:
        status, payload = _request_json(
            daemon.base_url,
            f"/v1/lotus/agent-web-document?root={repo_root}&document_id=semantic_capabilities",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_document"]["document"]["document_id"] == "semantic_capabilities"
        assert payload["agent_web_document"]["document"]["path"] == "Semantic-Capabilities.md"
        assert "# Semantic Capabilities" in payload["agent_web_document"]["document"]["content"]

        status, payload = _request_json(
            daemon.base_url,
            f"/v1/lotus/agent-web-document?root={repo_root}&document_id=semantic_contracts",
            token=root_secret,
        )
        assert status == 200
        assert payload["agent_web_document"]["document"]["document_id"] == "semantic_contracts"
        assert payload["agent_web_document"]["document"]["path"] == "Semantic-Contracts.md"
        assert "# Semantic Contracts" in payload["agent_web_document"]["document"]["content"]
    finally:
        daemon.shutdown()


def test_lotus_daemon_serves_spaces_and_slots_http_api(tmp_path):
    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: (
            plane.publish_assistant_surface(
                AssistantSurfaceSnapshot(
                    assistant_id="moltbook_assistant",
                    assistant_kind="moltbook_assistant",
                    city_id="city-http-space",
                    city_slug="http-space",
                    repo="org/city-http-space",
                    heartbeat_source="steward-protocol/mahamantra",
                    heartbeat=8,
                    state_present=True,
                    total_posts=4,
                ),
            ),
            LotusControlPlaneAPI(plane).issue_token(
                subject="root",
                scopes=(LotusApiScope.READ.value,),
                token_secret="space-root",
                token_id="tok-space-root",
            ).secret,
        )[1],
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()

    try:
        status, spaces = _request_json(daemon.base_url, "/v1/lotus/spaces", token=root_secret)
        assert status == 200
        assert spaces["spaces"][0]["space_id"] == "space:city-http-space:moltbook_assistant"
        status, slots = _request_json(daemon.base_url, "/v1/lotus/slots", token=root_secret)
        assert status == 200
        assert slots["slots"][0]["slot_id"] == "slot:city-http-space:assistant-social"
    finally:
        daemon.shutdown()


def test_lotus_daemon_serves_lineage_http_api(tmp_path):
    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: (
            plane.upsert_fork_lineage(
                ForkLineageRecord(
                    lineage_id="lineage:city-fork",
                    repo="org/city-fork",
                    upstream_repo="org/city-root",
                    line_root_repo="org/city-root",
                    fork_mode=ForkMode.EXPERIMENT,
                    sync_policy=UpstreamSyncPolicy.ADVISORY,
                    space_id="space:city-fork:moltbook_assistant",
                    upstream_space_id="space:city-root:moltbook_assistant",
                    forked_by_subject_id="human:ss",
                    created_at=456.0,
                ),
            ),
            LotusControlPlaneAPI(plane).issue_token(
                subject="root",
                scopes=(LotusApiScope.READ.value,),
                token_secret="lineage-root",
                token_id="tok-lineage-root",
            ).secret,
        )[1],
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()

    try:
        status, payload = _request_json(daemon.base_url, "/v1/lotus/lineage", token=root_secret)
        assert status == 200
        assert payload["fork_lineage"][0]["lineage_id"] == "lineage:city-fork"
        assert payload["fork_lineage"][0]["fork_mode"] == "experiment"
        assert payload["fork_lineage"][0]["sync_policy"] == "advisory"
    finally:
        daemon.shutdown()


def test_lotus_daemon_creates_and_lists_intents_http_api(tmp_path):
    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="human:ss",
            scopes=(LotusApiScope.READ.value, LotusApiScope.INTENT_WRITE.value),
            token_secret="intent-root",
            token_id="tok-intent-root",
        ).secret,
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()

    try:
        status, created = _request_json(
            daemon.base_url,
            "/v1/lotus/intents",
            method="POST",
            token=root_secret,
            payload={
                "intent_id": "intent:slot-city-http",
                "intent_type": IntentType.REQUEST_SLOT.value,
                "title": "Request social slot",
                "description": "Request assistant social slot exposure.",
                "space_id": "space:city-http:moltbook_assistant",
                "labels": {"channel": "http"},
                "now": 789.0,
            },
        )
        assert status == 200
        assert created["intent"]["intent_id"] == "intent:slot-city-http"
        assert created["intent"]["requested_by_subject_id"] == "human:ss"

        status, listed = _request_json(daemon.base_url, "/v1/lotus/intents", token=root_secret)
        assert status == 200
        assert listed["intents"][0]["intent_type"] == "request_slot"
        assert listed["intents"][0]["status"] == "pending"

        status, fetched = _request_json(daemon.base_url, "/v1/lotus/intents/intent%3Aslot-city-http", token=root_secret)
        assert status == 200
        assert fetched["intent"]["intent_id"] == "intent:slot-city-http"
    finally:
        daemon.shutdown()


def test_lotus_daemon_transitions_intents_http_api(tmp_path):
    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="operator",
            scopes=(LotusApiScope.READ.value, LotusApiScope.INTENT_WRITE.value, LotusApiScope.INTENT_REVIEW.value),
            token_secret="intent-review-root",
            token_id="tok-intent-review-root",
        ).secret,
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()

    try:
        status, _created = _request_json(
            daemon.base_url,
            "/v1/lotus/intents",
            method="POST",
            token=root_secret,
            payload={
                "intent_id": "intent:review-city-http",
                "intent_type": IntentType.REQUEST_OPERATOR_REVIEW.value,
                "title": "Operator review",
                "now": 900.0,
            },
        )
        assert status == 200

        status, accepted = _request_json(
            daemon.base_url,
            "/v1/lotus/intents/intent%3Areview-city-http/accept",
            method="POST",
            token=root_secret,
            payload={"now": 901.0},
        )
        assert status == 200
        assert accepted["intent"]["status"] == IntentStatus.ACCEPTED.value

        status, fulfilled = _request_json(
            daemon.base_url,
            "/v1/lotus/intents/intent%3Areview-city-http/fulfill",
            method="POST",
            token=root_secret,
            payload={"now": 902.0},
        )
        assert status == 200
        assert fulfilled["intent"]["status"] == IntentStatus.FULFILLED.value
    finally:
        daemon.shutdown()