import json

import pytest

from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.lotus_api import LotusControlPlaneAPI
from agent_internet.models import (
    AssistantSurfaceSnapshot,
    CityEndpoint,
    CityIdentity,
    ForkLineageRecord,
    ForkMode,
    IntentStatus,
    IntentType,
    LotusApiScope,
    TrustLevel,
    TrustRecord,
    UpstreamSyncPolicy,
)


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


def test_lotus_api_generates_cli_safe_secret_prefix():
    plane = AgentInternetControlPlane()
    api = LotusControlPlaneAPI(plane)

    issued = api.issue_token(subject="operator", scopes=(LotusApiScope.READ.value,))

    assert issued.secret.startswith("lotus_")


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
        json.dumps({"heartbeat": 4, "timestamp": 40.0, "population": 2, "alive": 2, "dead": 0, "chain_valid": True}),
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