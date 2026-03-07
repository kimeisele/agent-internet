import pytest

from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.lotus_api import LotusControlPlaneAPI
from agent_internet.models import CityEndpoint, CityIdentity, LotusApiScope


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