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
        json.dumps({"heartbeat": 7, "timestamp": 70.0, "population": 1, "alive": 1, "dead": 0, "chain_valid": True}),
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