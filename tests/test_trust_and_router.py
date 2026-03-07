from agent_internet.memory_registry import InMemoryCityRegistry
from agent_internet.models import CityEndpoint, CityPresence, HealthStatus, HostedEndpoint, TrustLevel, TrustRecord
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


def test_router_resolves_public_handle_only_while_owner_online_and_lease_active():
    registry = InMemoryCityRegistry()
    link = registry.assign_link_address("city-b", now=5.0)
    network = registry.assign_network_address("city-b", now=5.0)
    registry.upsert_hosted_endpoint(
        HostedEndpoint(
            endpoint_id="city-b:public-forum",
            owner_city_id="city-b",
            public_handle="forum.city-b.lotus",
            transport="https",
            location="https://forum.city-b.example",
            link_address=link.mac_address,
            network_address=network.ip_address,
            lease_started_at=5.0,
            lease_expires_at=35.0,
        ),
    )
    registry.announce(CityPresence("city-b", health=HealthStatus.HEALTHY))
    router = RegistryRouter(registry=registry, discovery=registry)

    assert router.resolve_public_handle("forum.city-b.lotus", now=10.0).endpoint_id == "city-b:public-forum"
    assert router.resolve_public_handle("forum.city-b.lotus", now=50.0) is None

    registry.announce(CityPresence("city-b", health=HealthStatus.OFFLINE))

    assert router.resolve_public_handle("forum.city-b.lotus", now=10.0) is None
