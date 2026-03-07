from agent_internet.memory_registry import InMemoryCityRegistry
from agent_internet.models import CityEndpoint, CityIdentity, CityPresence, HealthStatus, HostedEndpoint, LotusApiToken, LotusRoute, LotusServiceAddress


def test_registry_stores_identity_and_endpoint():
    registry = InMemoryCityRegistry()
    identity = CityIdentity(city_id="city-a", slug="a", repo="org/a")
    endpoint = CityEndpoint(city_id="city-a", transport="git", location="https://example/a.git")

    registry.upsert_identity(identity)
    registry.upsert_endpoint(endpoint)

    assert registry.get_identity("city-a") == identity
    assert registry.get_endpoint("city-a") == endpoint


def test_registry_announces_and_lists_presence_sorted():
    registry = InMemoryCityRegistry()
    registry.announce(CityPresence(city_id="city-b", health=HealthStatus.DEGRADED))
    registry.announce(CityPresence(city_id="city-a", health=HealthStatus.HEALTHY))

    assert registry.get_presence("city-a").health == HealthStatus.HEALTHY
    assert [presence.city_id for presence in registry.list_cities()] == ["city-a", "city-b"]


def test_registry_assigns_lotus_addresses_and_resolves_hosted_handles():
    registry = InMemoryCityRegistry()

    link = registry.assign_link_address("city-a", now=10.0)
    network = registry.assign_network_address("city-a", now=10.0)
    registry.upsert_hosted_endpoint(
        HostedEndpoint(
            endpoint_id="city-a:forum",
            owner_city_id="city-a",
            public_handle="forum.city-a.lotus",
            transport="https",
            location="https://forum.city-a.example",
            link_address=link.mac_address,
            network_address=network.ip_address,
            lease_started_at=10.0,
            lease_expires_at=40.0,
        ),
    )

    assert link.mac_address.startswith("02:00:")
    assert network.ip_address.startswith("fd10:")
    assert registry.get_hosted_endpoint_by_handle("forum.city-a.lotus", now=20.0).endpoint_id == "city-a:forum"
    assert registry.get_hosted_endpoint_by_handle("forum.city-a.lotus", now=50.0) is None


def test_registry_stores_service_addresses_and_api_tokens():
    registry = InMemoryCityRegistry()
    registry.upsert_service_address(
        LotusServiceAddress(
            service_id="city-a:forum-api",
            owner_city_id="city-a",
            service_name="forum-api",
            public_handle="api.forum.city-a.lotus",
            transport="https",
            location="https://forum.city-a.example/api",
            network_address="fd10:0000:0001:0000::1",
            required_scopes=("lotus.read",),
            lease_started_at=5.0,
            lease_expires_at=50.0,
        ),
    )
    registry.upsert_api_token(
        LotusApiToken(
            token_id="tok-1",
            subject="operator",
            token_hint="secret12",
            token_sha256="deadbeef",
            scopes=("lotus.read",),
            issued_at=7.0,
        ),
    )

    assert registry.get_service_address_by_name("city-a", "forum-api", now=10.0).public_handle == "api.forum.city-a.lotus"
    assert registry.get_api_token_by_sha256("deadbeef").token_id == "tok-1"


def test_registry_stores_routes():
    registry = InMemoryCityRegistry()
    registry.upsert_route(
        LotusRoute(
            route_id="r1",
            owner_city_id="city-a",
            destination_prefix="service:city-z/",
            target_city_id="city-z",
            next_hop_city_id="city-b",
        ),
    )

    assert registry.get_route("r1").next_hop_city_id == "city-b"
