"""Thread-safe wrapper for CityRegistry implementations.

Provides fine-grained read/write locking around an underlying registry to enable
safe concurrent access from the Lotus API daemon and background workers.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TypeVar

from .models import (
    CityEndpoint,
    CityIdentity,
    CityPresence,
    ForkLineageRecord,
    HostedEndpoint,
    IntentRecord,
    LotusApiToken,
    LotusLinkAddress,
    LotusNetworkAddress,
    LotusRoute,
    LotusServiceAddress,
    SlotDescriptor,
    SlotLeaseRecord,
    SpaceClaimRecord,
    SpaceDescriptor,
)

_T = TypeVar("_T")


class _RWLock:
    """Simple readers-writer lock (writer-preferring)."""

    def __init__(self) -> None:
        self._readers = 0
        self._writers_waiting = 0
        self._writer_active = False
        self._lock = threading.Lock()
        self._readers_ok = threading.Condition(self._lock)
        self._writer_ok = threading.Condition(self._lock)

    def acquire_read(self) -> None:
        with self._lock:
            while self._writer_active or self._writers_waiting > 0:
                self._readers_ok.wait()
            self._readers += 1

    def release_read(self) -> None:
        with self._lock:
            self._readers -= 1
            if self._readers == 0:
                self._writer_ok.notify()

    def acquire_write(self) -> None:
        with self._lock:
            self._writers_waiting += 1
            while self._writer_active or self._readers > 0:
                self._writer_ok.wait()
            self._writers_waiting -= 1
            self._writer_active = True

    def release_write(self) -> None:
        with self._lock:
            self._writer_active = False
            self._writer_ok.notify()
            self._readers_ok.notify_all()


@dataclass(slots=True)
class ThreadSafeRegistryWrapper:
    """Wraps any CityRegistry + DiscoveryService implementation with RW-locking.

    Read operations acquire a shared lock, write operations acquire an exclusive
    lock.  This allows multiple concurrent readers while serializing writes.
    """

    _inner: object
    _rw_lock: _RWLock = field(default_factory=_RWLock)

    def _read(self, method: str, *args, **kwargs) -> object:
        self._rw_lock.acquire_read()
        try:
            return getattr(self._inner, method)(*args, **kwargs)
        finally:
            self._rw_lock.release_read()

    def _write(self, method: str, *args, **kwargs) -> object:
        self._rw_lock.acquire_write()
        try:
            return getattr(self._inner, method)(*args, **kwargs)
        finally:
            self._rw_lock.release_write()

    # --- CityRegistry: write operations ---

    def upsert_identity(self, identity: CityIdentity) -> None:
        self._write("upsert_identity", identity)

    def upsert_endpoint(self, endpoint: CityEndpoint) -> None:
        self._write("upsert_endpoint", endpoint)

    def assign_link_address(self, city_id: str, *, ttl_s: float | None = None) -> LotusLinkAddress:
        return self._write("assign_link_address", city_id, ttl_s=ttl_s)  # type: ignore[return-value]

    def assign_network_address(self, city_id: str, *, ttl_s: float | None = None) -> LotusNetworkAddress:
        return self._write("assign_network_address", city_id, ttl_s=ttl_s)  # type: ignore[return-value]

    def upsert_hosted_endpoint(self, endpoint: HostedEndpoint) -> None:
        self._write("upsert_hosted_endpoint", endpoint)

    def upsert_service_address(self, service: LotusServiceAddress) -> None:
        self._write("upsert_service_address", service)

    def upsert_route(self, route: LotusRoute) -> None:
        self._write("upsert_route", route)

    def upsert_api_token(self, token: LotusApiToken) -> None:
        self._write("upsert_api_token", token)

    def upsert_space(self, space: SpaceDescriptor) -> None:
        self._write("upsert_space", space)

    def upsert_slot(self, slot: SlotDescriptor) -> None:
        self._write("upsert_slot", slot)

    def upsert_space_claim(self, claim: SpaceClaimRecord) -> None:
        self._write("upsert_space_claim", claim)

    def upsert_slot_lease(self, lease: SlotLeaseRecord) -> None:
        self._write("upsert_slot_lease", lease)

    def upsert_fork_lineage(self, lineage: ForkLineageRecord) -> None:
        self._write("upsert_fork_lineage", lineage)

    def upsert_intent(self, intent: IntentRecord) -> None:
        self._write("upsert_intent", intent)

    # --- CityRegistry: read operations ---

    def get_identity(self, city_id: str) -> CityIdentity | None:
        return self._read("get_identity", city_id)  # type: ignore[return-value]

    def list_identities(self) -> list[CityIdentity]:
        return self._read("list_identities")  # type: ignore[return-value]

    def get_endpoint(self, city_id: str) -> CityEndpoint | None:
        return self._read("get_endpoint", city_id)  # type: ignore[return-value]

    def list_endpoints(self) -> list[CityEndpoint]:
        return self._read("list_endpoints")  # type: ignore[return-value]

    def get_link_address(self, city_id: str) -> LotusLinkAddress | None:
        return self._read("get_link_address", city_id)  # type: ignore[return-value]

    def list_link_addresses(self) -> list[LotusLinkAddress]:
        return self._read("list_link_addresses")  # type: ignore[return-value]

    def get_network_address(self, city_id: str) -> LotusNetworkAddress | None:
        return self._read("get_network_address", city_id)  # type: ignore[return-value]

    def list_network_addresses(self) -> list[LotusNetworkAddress]:
        return self._read("list_network_addresses")  # type: ignore[return-value]

    def get_hosted_endpoint(self, endpoint_id: str) -> HostedEndpoint | None:
        return self._read("get_hosted_endpoint", endpoint_id)  # type: ignore[return-value]

    def get_hosted_endpoint_by_handle(self, public_handle: str, *, now: float | None = None) -> HostedEndpoint | None:
        return self._read("get_hosted_endpoint_by_handle", public_handle, now=now)  # type: ignore[return-value]

    def list_hosted_endpoints(self) -> list[HostedEndpoint]:
        return self._read("list_hosted_endpoints")  # type: ignore[return-value]

    def get_service_address(self, service_id: str) -> LotusServiceAddress | None:
        return self._read("get_service_address", service_id)  # type: ignore[return-value]

    def get_service_address_by_name(self, owner_city_id: str, service_name: str, *, now: float | None = None) -> LotusServiceAddress | None:
        return self._read("get_service_address_by_name", owner_city_id, service_name, now=now)  # type: ignore[return-value]

    def list_service_addresses(self) -> list[LotusServiceAddress]:
        return self._read("list_service_addresses")  # type: ignore[return-value]

    def get_route(self, route_id: str) -> LotusRoute | None:
        return self._read("get_route", route_id)  # type: ignore[return-value]

    def list_routes(self) -> list[LotusRoute]:
        return self._read("list_routes")  # type: ignore[return-value]

    def get_api_token(self, token_id: str) -> LotusApiToken | None:
        return self._read("get_api_token", token_id)  # type: ignore[return-value]

    def get_api_token_by_sha256(self, token_sha256: str) -> LotusApiToken | None:
        return self._read("get_api_token_by_sha256", token_sha256)  # type: ignore[return-value]

    def list_api_tokens(self) -> list[LotusApiToken]:
        return self._read("list_api_tokens")  # type: ignore[return-value]

    def get_space(self, space_id: str) -> SpaceDescriptor | None:
        return self._read("get_space", space_id)  # type: ignore[return-value]

    def list_spaces(self) -> list[SpaceDescriptor]:
        return self._read("list_spaces")  # type: ignore[return-value]

    def get_slot(self, slot_id: str) -> SlotDescriptor | None:
        return self._read("get_slot", slot_id)  # type: ignore[return-value]

    def list_slots(self) -> list[SlotDescriptor]:
        return self._read("list_slots")  # type: ignore[return-value]

    def get_space_claim(self, claim_id: str) -> SpaceClaimRecord | None:
        return self._read("get_space_claim", claim_id)  # type: ignore[return-value]

    def list_space_claims(self) -> list[SpaceClaimRecord]:
        return self._read("list_space_claims")  # type: ignore[return-value]

    def get_slot_lease(self, lease_id: str) -> SlotLeaseRecord | None:
        return self._read("get_slot_lease", lease_id)  # type: ignore[return-value]

    def list_slot_leases(self) -> list[SlotLeaseRecord]:
        return self._read("list_slot_leases")  # type: ignore[return-value]

    def get_fork_lineage(self, lineage_id: str) -> ForkLineageRecord | None:
        return self._read("get_fork_lineage", lineage_id)  # type: ignore[return-value]

    def list_fork_lineage(self) -> list[ForkLineageRecord]:
        return self._read("list_fork_lineage")  # type: ignore[return-value]

    def get_intent(self, intent_id: str) -> IntentRecord | None:
        return self._read("get_intent", intent_id)  # type: ignore[return-value]

    def list_intents(self) -> list[IntentRecord]:
        return self._read("list_intents")  # type: ignore[return-value]

    # --- DiscoveryService ---

    def announce(self, presence: CityPresence) -> None:
        self._write("announce", presence)

    def get_presence(self, city_id: str) -> CityPresence | None:
        return self._read("get_presence", city_id)  # type: ignore[return-value]

    def list_cities(self) -> list[CityPresence]:
        return self._read("list_cities")  # type: ignore[return-value]

    # --- Allocation state (InMemoryCityRegistry-specific) ---

    def allocation_state(self) -> dict[str, int]:
        return self._read("allocation_state")  # type: ignore[return-value]

    def restore_allocation_state(self, *, next_link_id: int = 1, next_network_id: int = 1) -> None:
        self._write("restore_allocation_state", next_link_id=next_link_id, next_network_id=next_network_id)
