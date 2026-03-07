from __future__ import annotations

from dataclasses import dataclass

from .interfaces import CityRegistry, DiscoveryService, TrustEngine
from .models import (
    CityEndpoint,
    HealthStatus,
    HostedEndpoint,
    LotusRouteResolution,
    LotusServiceAddress,
    TrustLevel,
)
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

    def resolve_public_handle(self, public_handle: str, *, now: float | None = None) -> HostedEndpoint | None:
        endpoint = self.registry.get_hosted_endpoint_by_handle(public_handle, now=now)
        if endpoint is None:
            return None

        if self.discovery is not None:
            presence = self.discovery.get_presence(endpoint.owner_city_id)
            if presence is not None and presence.health == HealthStatus.OFFLINE:
                return None

        return endpoint

    def resolve_service(self, owner_city_id: str, service_name: str, *, now: float | None = None) -> LotusServiceAddress | None:
        service = self.registry.get_service_address_by_name(owner_city_id, service_name, now=now)
        if service is None:
            return None

        if self.discovery is not None:
            presence = self.discovery.get_presence(service.owner_city_id)
            if presence is not None and presence.health == HealthStatus.OFFLINE:
                return None

        return service

    def resolve_next_hop(self, source_city_id: str, destination: str, *, now: float | None = None) -> LotusRouteResolution | None:
        routes = sorted(
            (
                route
                for route in self.registry.list_routes()
                if _matches_destination_prefix(destination, route.destination_prefix)
            ),
            key=lambda route: (-len(route.destination_prefix), route.metric, route.route_id),
        )
        for route in routes:
            next_hop_endpoint = self.registry.get_endpoint(route.next_hop_city_id)
            if next_hop_endpoint is None:
                continue

            if self.discovery is not None:
                presence = self.discovery.get_presence(route.next_hop_city_id)
                if presence is not None and presence.health == HealthStatus.OFFLINE:
                    continue

            if self.trust_engine is not None:
                trust = self.trust_engine.evaluate(source_city_id, route.next_hop_city_id)
                if not trust_allows(trust, self.minimum_trust):
                    continue

            return LotusRouteResolution(
                destination=destination,
                matched_prefix=route.destination_prefix,
                route_id=route.route_id,
                target_city_id=route.target_city_id,
                next_hop_city_id=route.next_hop_city_id,
                next_hop_endpoint=next_hop_endpoint,
                nadi_type=route.nadi_type,
                priority=route.priority,
                ttl_ms=route.ttl_ms,
                maha_header_hex=route.maha_header_hex,
            )
        return None


def _matches_destination_prefix(destination: str, prefix: str) -> bool:
    return destination == prefix or destination.startswith(prefix)
