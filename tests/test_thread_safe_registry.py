from __future__ import annotations

import threading

from agent_internet.memory_registry import InMemoryCityRegistry
from agent_internet.models import CityEndpoint, CityIdentity, CityPresence, HealthStatus
from agent_internet.thread_safe_registry import ThreadSafeRegistryWrapper


def test_basic_read_write():
    inner = InMemoryCityRegistry()
    registry = ThreadSafeRegistryWrapper(_inner=inner)

    identity = CityIdentity(city_id="alpha", slug="alpha-city", repo="test/alpha")
    registry.upsert_identity(identity)
    result = registry.get_identity("alpha")
    assert result is not None
    assert result.slug == "alpha-city"


def test_list_identities():
    inner = InMemoryCityRegistry()
    registry = ThreadSafeRegistryWrapper(_inner=inner)

    for i in range(3):
        registry.upsert_identity(CityIdentity(city_id=f"city-{i}", slug=f"slug-{i}", repo=""))
    assert len(registry.list_identities()) == 3


def test_concurrent_writes():
    inner = InMemoryCityRegistry()
    registry = ThreadSafeRegistryWrapper(_inner=inner)

    def write_identities(prefix: str):
        for i in range(50):
            registry.upsert_identity(
                CityIdentity(city_id=f"{prefix}-{i}", slug=f"{prefix}-{i}", repo=""),
            )

    threads = [threading.Thread(target=write_identities, args=(f"t{j}",)) for j in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(registry.list_identities()) == 200


def test_concurrent_read_write():
    inner = InMemoryCityRegistry()
    registry = ThreadSafeRegistryWrapper(_inner=inner)

    for i in range(10):
        registry.upsert_identity(CityIdentity(city_id=f"city-{i}", slug=f"slug-{i}", repo=""))

    read_results: list[int] = []

    def reader():
        for _ in range(50):
            read_results.append(len(registry.list_identities()))

    def writer():
        for i in range(10, 20):
            registry.upsert_identity(CityIdentity(city_id=f"city-{i}", slug=f"slug-{i}", repo=""))

    threads = [threading.Thread(target=reader) for _ in range(4)] + [threading.Thread(target=writer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(registry.list_identities()) == 20
    assert all(r >= 10 for r in read_results)


def test_discovery_protocol():
    inner = InMemoryCityRegistry()
    registry = ThreadSafeRegistryWrapper(_inner=inner)

    presence = CityPresence(city_id="alpha", health=HealthStatus.HEALTHY)
    registry.announce(presence)

    result = registry.get_presence("alpha")
    assert result is not None
    assert result.health == HealthStatus.HEALTHY

    cities = registry.list_cities()
    assert len(cities) == 1
