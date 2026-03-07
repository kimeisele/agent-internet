import pytest

from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.lotus_api import LotusControlPlaneAPI
from agent_internet.models import CityEndpoint, CityIdentity, LotusApiScope, TrustLevel, TrustRecord


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