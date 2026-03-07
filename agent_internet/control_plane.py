from __future__ import annotations

from dataclasses import dataclass, field

from .agent_city_bridge import AgentCityBridge
from .memory_registry import InMemoryCityRegistry
from .models import CityEndpoint, CityIdentity, CityPresence, TrustLevel, TrustRecord
from .router import RegistryRouter
from .trust import InMemoryTrustEngine


@dataclass(slots=True)
class AgentInternetControlPlane:
    registry: InMemoryCityRegistry = field(default_factory=InMemoryCityRegistry)
    trust_engine: InMemoryTrustEngine = field(default_factory=InMemoryTrustEngine)
    minimum_trust: TrustLevel = TrustLevel.OBSERVED
    router: RegistryRouter = field(init=False)

    def __post_init__(self) -> None:
        self.router = RegistryRouter(
            registry=self.registry,
            discovery=self.registry,
            trust_engine=self.trust_engine,
            minimum_trust=self.minimum_trust,
        )

    def register_city(self, identity: CityIdentity, endpoint: CityEndpoint) -> None:
        self.registry.upsert_identity(identity)
        self.registry.upsert_endpoint(endpoint)

    def announce_city(self, presence: CityPresence) -> None:
        self.registry.announce(presence)

    def record_trust(self, trust: TrustRecord) -> None:
        self.trust_engine.record(trust)

    def resolve_route(self, source_city_id: str, target_city_id: str) -> CityEndpoint | None:
        return self.router.resolve(source_city_id, target_city_id)

    def observe_agent_city(
        self,
        bridge: AgentCityBridge,
        *,
        identity: CityIdentity | None = None,
        endpoint: CityEndpoint | None = None,
    ) -> CityPresence | None:
        if identity is not None:
            self.registry.upsert_identity(identity)
        if endpoint is not None:
            self.registry.upsert_endpoint(endpoint)
        presence = bridge.latest_presence()
        if presence is not None:
            self.registry.announce(presence)
        return presence
