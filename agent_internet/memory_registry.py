from __future__ import annotations

import time
from dataclasses import dataclass, field

from .models import (
    AuthorityArtifactRecord,
    AuthorityExportRecord,
    SlotDescriptor,
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
    ProjectionBindingRecord,
    ProjectionReconcileStatusRecord,
    PublicationStatusRecord,
    RepoRoleRecord,
    SourceAuthorityFeedRecord,
    SpaceDescriptor,
)


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
    _service_addresses: dict[str, LotusServiceAddress] = field(default_factory=dict)
    _service_name_index: dict[tuple[str, str], str] = field(default_factory=dict)
    _routes: dict[str, LotusRoute] = field(default_factory=dict)
    _api_tokens: dict[str, LotusApiToken] = field(default_factory=dict)
    _api_token_hash_index: dict[str, str] = field(default_factory=dict)
    _spaces: dict[str, SpaceDescriptor] = field(default_factory=dict)
    _slots: dict[str, SlotDescriptor] = field(default_factory=dict)
    _fork_lineage: dict[str, ForkLineageRecord] = field(default_factory=dict)
    _intents: dict[str, IntentRecord] = field(default_factory=dict)
    _repo_roles: dict[str, RepoRoleRecord] = field(default_factory=dict)
    _authority_exports: dict[str, AuthorityExportRecord] = field(default_factory=dict)
    _authority_artifacts: dict[str, AuthorityArtifactRecord] = field(default_factory=dict)
    _projection_bindings: dict[str, ProjectionBindingRecord] = field(default_factory=dict)
    _publication_statuses: dict[str, PublicationStatusRecord] = field(default_factory=dict)
    _source_authority_feeds: dict[str, SourceAuthorityFeedRecord] = field(default_factory=dict)
    _projection_reconcile_statuses: dict[str, ProjectionReconcileStatusRecord] = field(default_factory=dict)
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

    def upsert_service_address(self, service: LotusServiceAddress) -> None:
        self._service_addresses[service.service_id] = service
        self._service_name_index[(service.owner_city_id, service.service_name)] = service.service_id

    def get_service_address(self, service_id: str) -> LotusServiceAddress | None:
        service = self._service_addresses.get(service_id)
        if service is None or not _lease_active(service.lease_expires_at, None):
            return None
        return service

    def get_service_address_by_name(self, owner_city_id: str, service_name: str, *, now: float | None = None) -> LotusServiceAddress | None:
        service_id = self._service_name_index.get((owner_city_id, service_name))
        if service_id is None:
            return None
        service = self._service_addresses.get(service_id)
        if service is None or not _lease_active(service.lease_expires_at, now):
            return None
        return service

    def list_service_addresses(self) -> list[LotusServiceAddress]:
        return [self._service_addresses[service_id] for service_id in sorted(self._service_addresses)]

    def upsert_route(self, route: LotusRoute) -> None:
        self._routes[route.route_id] = route

    def get_route(self, route_id: str) -> LotusRoute | None:
        route = self._routes.get(route_id)
        if route is None or not _lease_active(route.lease_expires_at, None):
            return None
        return route

    def list_routes(self) -> list[LotusRoute]:
        return [self._routes[route_id] for route_id in sorted(self._routes)]

    def upsert_api_token(self, token: LotusApiToken) -> None:
        self._api_tokens[token.token_id] = token
        self._api_token_hash_index[token.token_sha256] = token.token_id

    def get_api_token(self, token_id: str) -> LotusApiToken | None:
        return self._api_tokens.get(token_id)

    def get_api_token_by_sha256(self, token_sha256: str) -> LotusApiToken | None:
        token_id = self._api_token_hash_index.get(token_sha256)
        if token_id is None:
            return None
        return self._api_tokens.get(token_id)

    def list_api_tokens(self) -> list[LotusApiToken]:
        return [self._api_tokens[token_id] for token_id in sorted(self._api_tokens)]

    def upsert_space(self, space: SpaceDescriptor) -> None:
        self._spaces[space.space_id] = space

    def get_space(self, space_id: str) -> SpaceDescriptor | None:
        return self._spaces.get(space_id)

    def list_spaces(self) -> list[SpaceDescriptor]:
        return [self._spaces[space_id] for space_id in sorted(self._spaces)]

    def upsert_slot(self, slot: SlotDescriptor) -> None:
        self._slots[slot.slot_id] = slot

    def get_slot(self, slot_id: str) -> SlotDescriptor | None:
        return self._slots.get(slot_id)

    def list_slots(self) -> list[SlotDescriptor]:
        return [self._slots[slot_id] for slot_id in sorted(self._slots)]

    def upsert_fork_lineage(self, lineage: ForkLineageRecord) -> None:
        self._fork_lineage[lineage.lineage_id] = lineage

    def get_fork_lineage(self, lineage_id: str) -> ForkLineageRecord | None:
        return self._fork_lineage.get(lineage_id)

    def list_fork_lineage(self) -> list[ForkLineageRecord]:
        return [self._fork_lineage[lineage_id] for lineage_id in sorted(self._fork_lineage)]

    def upsert_intent(self, intent: IntentRecord) -> None:
        self._intents[intent.intent_id] = intent

    def get_intent(self, intent_id: str) -> IntentRecord | None:
        return self._intents.get(intent_id)

    def list_intents(self) -> list[IntentRecord]:
        return [self._intents[intent_id] for intent_id in sorted(self._intents)]

    def upsert_repo_role(self, record: RepoRoleRecord) -> None:
        self._repo_roles[record.repo_id] = record

    def get_repo_role(self, repo_id: str) -> RepoRoleRecord | None:
        return self._repo_roles.get(repo_id)

    def list_repo_roles(self) -> list[RepoRoleRecord]:
        return [self._repo_roles[repo_id] for repo_id in sorted(self._repo_roles)]

    def upsert_authority_export(self, record: AuthorityExportRecord) -> None:
        self._authority_exports[record.export_id] = record

    def get_authority_export(self, export_id: str) -> AuthorityExportRecord | None:
        return self._authority_exports.get(export_id)

    def list_authority_exports(self) -> list[AuthorityExportRecord]:
        return [self._authority_exports[export_id] for export_id in sorted(self._authority_exports)]

    def upsert_authority_artifact(self, record: AuthorityArtifactRecord) -> None:
        self._authority_artifacts[record.export_id] = record

    def get_authority_artifact(self, export_id: str) -> AuthorityArtifactRecord | None:
        return self._authority_artifacts.get(export_id)

    def list_authority_artifacts(self) -> list[AuthorityArtifactRecord]:
        return [self._authority_artifacts[export_id] for export_id in sorted(self._authority_artifacts)]

    def find_authority_export(self, repo_id: str, export_kind: str) -> AuthorityExportRecord | None:
        for export in self.list_authority_exports():
            if export.repo_id == repo_id and export.export_kind == export_kind:
                return export
        return None

    def upsert_projection_binding(self, record: ProjectionBindingRecord) -> None:
        self._projection_bindings[record.binding_id] = record

    def get_projection_binding(self, binding_id: str) -> ProjectionBindingRecord | None:
        return self._projection_bindings.get(binding_id)

    def list_projection_bindings(self) -> list[ProjectionBindingRecord]:
        return [self._projection_bindings[binding_id] for binding_id in sorted(self._projection_bindings)]

    def upsert_publication_status(self, record: PublicationStatusRecord) -> None:
        self._publication_statuses[record.binding_id] = record

    def get_publication_status(self, binding_id: str) -> PublicationStatusRecord | None:
        return self._publication_statuses.get(binding_id)

    def list_publication_statuses(self) -> list[PublicationStatusRecord]:
        return [self._publication_statuses[binding_id] for binding_id in sorted(self._publication_statuses)]

    def upsert_source_authority_feed(self, record: SourceAuthorityFeedRecord) -> None:
        self._source_authority_feeds[record.feed_id] = record

    def get_source_authority_feed(self, feed_id: str) -> SourceAuthorityFeedRecord | None:
        return self._source_authority_feeds.get(feed_id)

    def list_source_authority_feeds(self) -> list[SourceAuthorityFeedRecord]:
        return [self._source_authority_feeds[feed_id] for feed_id in sorted(self._source_authority_feeds)]

    def upsert_projection_reconcile_status(self, record: ProjectionReconcileStatusRecord) -> None:
        self._projection_reconcile_statuses[record.binding_id] = record

    def get_projection_reconcile_status(self, binding_id: str) -> ProjectionReconcileStatusRecord | None:
        return self._projection_reconcile_statuses.get(binding_id)

    def list_projection_reconcile_statuses(self) -> list[ProjectionReconcileStatusRecord]:
        return [self._projection_reconcile_statuses[binding_id] for binding_id in sorted(self._projection_reconcile_statuses)]

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
