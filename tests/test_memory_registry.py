from agent_internet.memory_registry import InMemoryCityRegistry
from agent_internet.models import CityEndpoint, CityIdentity, CityPresence, HealthStatus, HostedEndpoint


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
