from __future__ import annotations

from dataclasses import dataclass

from .interfaces import CityRegistry, DiscoveryService, TrustEngine
from .models import CityEndpoint, HealthStatus, TrustLevel
from .trust import trust_allows


@dataclass(slots=True)
class RegistryRouter:
    registry: CityRegistry
    discovery: DiscoveryService | None = None
    trust_engine: TrustEngine | None = None
    minimum_trust: TrustLevel = TrustLevel.OBSERVED

    def resolve(self, source_city_id: str, target_city_id: str) -> CityEndpoint | None:
        endpoint = self.registry.get_endpoint(target_city_id)
        if endpoint is None:
            return None

        if self.discovery is not None:
            presence = self.discovery.get_presence(target_city_id)
            if presence is not None and presence.health == HealthStatus.OFFLINE:
                return None

        if self.trust_engine is not None:
            trust = self.trust_engine.evaluate(source_city_id, target_city_id)
            if not trust_allows(trust, self.minimum_trust):
                return None

        return endpoint
