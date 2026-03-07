from agent_internet.memory_registry import InMemoryCityRegistry
from agent_internet.models import CityEndpoint, CityIdentity, CityPresence, HealthStatus


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
