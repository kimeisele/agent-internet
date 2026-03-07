from __future__ import annotations

import time
from dataclasses import dataclass, field

from .models import CityEndpoint, CityIdentity, CityPresence, HostedEndpoint, LotusLinkAddress, LotusNetworkAddress


def _lease_started_at(now: float | None) -> float:
    return float(time.time() if now is None else now)


def _lease_expires_at(started_at: float, ttl_s: float | None) -> float | None:
    return None if ttl_s is None else started_at + max(ttl_s, 0.0)


def _lease_active(expires_at: float | None, now: float | None) -> bool:
    current = _lease_started_at(now)
    return expires_at is None or expires_at > current


def _format_link_address(index: int) -> str:
    return f"02:00:{(index >> 24) & 0xFF:02x}:{(index >> 16) & 0xFF:02x}:{(index >> 8) & 0xFF:02x}:{index & 0xFF:02x}"


def _format_network_address(index: int) -> str:
    return f"fd10:{(index >> 16) & 0xFFFF:04x}:{index & 0xFFFF:04x}:0000::1"


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
    _link_addresses: dict[str, LotusLinkAddress] = field(default_factory=dict)
    _network_addresses: dict[str, LotusNetworkAddress] = field(default_factory=dict)
    _hosted_endpoints: dict[str, HostedEndpoint] = field(default_factory=dict)
    _handle_index: dict[str, str] = field(default_factory=dict)
    _next_link_id: int = 1
    _next_network_id: int = 1

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

    def list_endpoints(self) -> list[CityEndpoint]:
        return [self._endpoints[city_id] for city_id in sorted(self._endpoints)]

    def assign_link_address(
        self,
        city_id: str,
        *,
        ttl_s: float | None = None,
        interface: str = "lotus0",
        now: float | None = None,
    ) -> LotusLinkAddress:
        current = self._link_addresses.get(city_id)
        if current is not None and _lease_active(current.lease_expires_at, now):
            return current
        started_at = _lease_started_at(now)
        assigned = LotusLinkAddress(
            city_id=city_id,
            mac_address=_format_link_address(self._next_link_id),
            interface=interface,
            lease_started_at=started_at,
            lease_expires_at=_lease_expires_at(started_at, ttl_s),
        )
        self._next_link_id += 1
        self._link_addresses[city_id] = assigned
        return assigned

    def get_link_address(self, city_id: str) -> LotusLinkAddress | None:
        return self._link_addresses.get(city_id)

    def list_link_addresses(self) -> list[LotusLinkAddress]:
        return [self._link_addresses[city_id] for city_id in sorted(self._link_addresses)]

    def assign_network_address(
        self,
        city_id: str,
        *,
        ttl_s: float | None = None,
        prefix_length: int = 64,
        now: float | None = None,
    ) -> LotusNetworkAddress:
        current = self._network_addresses.get(city_id)
        if current is not None and _lease_active(current.lease_expires_at, now):
            return current
        started_at = _lease_started_at(now)
        assigned = LotusNetworkAddress(
            city_id=city_id,
            ip_address=_format_network_address(self._next_network_id),
            prefix_length=prefix_length,
            lease_started_at=started_at,
            lease_expires_at=_lease_expires_at(started_at, ttl_s),
        )
        self._next_network_id += 1
        self._network_addresses[city_id] = assigned
        return assigned

    def get_network_address(self, city_id: str) -> LotusNetworkAddress | None:
        return self._network_addresses.get(city_id)

    def list_network_addresses(self) -> list[LotusNetworkAddress]:
        return [self._network_addresses[city_id] for city_id in sorted(self._network_addresses)]

    def upsert_hosted_endpoint(self, endpoint: HostedEndpoint) -> None:
        self._hosted_endpoints[endpoint.endpoint_id] = endpoint
        self._handle_index[endpoint.public_handle] = endpoint.endpoint_id

    def get_hosted_endpoint(self, endpoint_id: str) -> HostedEndpoint | None:
        return self._hosted_endpoints.get(endpoint_id)

    def get_hosted_endpoint_by_handle(self, public_handle: str, *, now: float | None = None) -> HostedEndpoint | None:
        endpoint_id = self._handle_index.get(public_handle)
        if endpoint_id is None:
            return None
        endpoint = self._hosted_endpoints.get(endpoint_id)
        if endpoint is None or not _lease_active(endpoint.lease_expires_at, now):
            return None
        return endpoint

    def list_hosted_endpoints(self) -> list[HostedEndpoint]:
        return [self._hosted_endpoints[endpoint_id] for endpoint_id in sorted(self._hosted_endpoints)]

    def announce(self, presence: CityPresence) -> None:
        self._presence[presence.city_id] = presence

    def get_presence(self, city_id: str) -> CityPresence | None:
        return self._presence.get(city_id)

    def list_cities(self) -> list[CityPresence]:
        return [self._presence[city_id] for city_id in sorted(self._presence)]

    def allocation_state(self) -> dict[str, int]:
        return {
            "next_link_id": self._next_link_id,
            "next_network_id": self._next_network_id,
        }

    def restore_allocation_state(self, *, next_link_id: int = 1, next_network_id: int = 1) -> None:
        self._next_link_id = max(1, int(next_link_id))
        self._next_network_id = max(1, int(next_network_id))
