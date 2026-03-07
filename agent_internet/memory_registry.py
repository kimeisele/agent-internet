from __future__ import annotations

from dataclasses import dataclass, field

from .models import CityEndpoint, CityIdentity, CityPresence


@dataclass(slots=True)
class InMemoryCityRegistry:
    """In-memory city state store for the control plane.

    Keeps identity, endpoint, and presence separate so the internet layer can
    reason about who a city is, how it is reached, and whether it is currently
    healthy without coupling those concerns together.
    """

    _identities: dict[str, CityIdentity] = field(default_factory=dict)
    _endpoints: dict[str, CityEndpoint] = field(default_factory=dict)
    _presence: dict[str, CityPresence] = field(default_factory=dict)

    def upsert_identity(self, identity: CityIdentity) -> None:
        self._identities[identity.city_id] = identity

    def get_identity(self, city_id: str) -> CityIdentity | None:
        return self._identities.get(city_id)

    def list_identities(self) -> list[CityIdentity]:
        return [self._identities[city_id] for city_id in sorted(self._identities)]

    def upsert_endpoint(self, endpoint: CityEndpoint) -> None:
        self._endpoints[endpoint.city_id] = endpoint

    def get_endpoint(self, city_id: str) -> CityEndpoint | None:
        return self._endpoints.get(city_id)

    def announce(self, presence: CityPresence) -> None:
        self._presence[presence.city_id] = presence

    def get_presence(self, city_id: str) -> CityPresence | None:
        return self._presence.get(city_id)

    def list_cities(self) -> list[CityPresence]:
        return [self._presence[city_id] for city_id in sorted(self._presence)]
