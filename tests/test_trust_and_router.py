from agent_internet.memory_registry import InMemoryCityRegistry
from agent_internet.models import CityEndpoint, CityPresence, HealthStatus, TrustLevel, TrustRecord
from agent_internet.router import RegistryRouter
from agent_internet.trust import InMemoryTrustEngine


def test_trust_engine_trusts_same_city_and_records_explicit_links():
    engine = InMemoryTrustEngine()

    assert engine.evaluate("city-a", "city-a") == TrustLevel.TRUSTED

    engine.record(TrustRecord("city-a", "city-b", TrustLevel.VERIFIED, reason="signed treaty"))

    assert engine.evaluate("city-a", "city-b") == TrustLevel.VERIFIED


def test_router_requires_endpoint_and_explicit_trust():
    registry = InMemoryCityRegistry()
    registry.upsert_endpoint(CityEndpoint("city-b", "git", "https://example/b.git"))
    trust = InMemoryTrustEngine()
    router = RegistryRouter(registry=registry, discovery=registry, trust_engine=trust)

    assert router.resolve("city-a", "city-b") is None

    trust.record(TrustRecord("city-a", "city-b", TrustLevel.OBSERVED, reason="seen in registry"))

    assert router.resolve("city-a", "city-b") == CityEndpoint(
        "city-b", "git", "https://example/b.git",
    )


def test_router_blocks_offline_target_even_if_trusted():
    registry = InMemoryCityRegistry()
    endpoint = CityEndpoint("city-b", "git", "https://example/b.git")
    registry.upsert_endpoint(endpoint)
    registry.announce(CityPresence("city-b", health=HealthStatus.OFFLINE))

    trust = InMemoryTrustEngine()
    trust.record(TrustRecord("city-a", "city-b", TrustLevel.TRUSTED, reason="core federation"))
    router = RegistryRouter(registry=registry, discovery=registry, trust_engine=trust)

    assert router.resolve("city-a", "city-b") is None
