from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

from .agent_city_bridge import AgentCityBridge
from .assistant_surface import assistant_social_slot_from_snapshot, assistant_space_from_snapshot
from .memory_registry import InMemoryCityRegistry
from .models import (
    AssistantSurfaceSnapshot,
    AuthorityExportKind,
    AuthorityExportRecord,
    CityEndpoint,
    CityIdentity,
    CityPresence,
    EndpointVisibility,
    ForkLineageRecord,
    HostedEndpoint,
    IntentRecord,
    IntentStatus,
    LotusApiToken,
    LotusLinkAddress,
    LotusNetworkAddress,
    LotusRoute,
    LotusRouteResolution,
    LotusServiceAddress,
    ProjectionBindingRecord,
    ProjectionFailurePolicy,
    ProjectionMode,
    PublicationState,
    PublicationStatusRecord,
    RepoRole,
    RepoRoleRecord,
    SlotDescriptor,
    SpaceDescriptor,
    TrustLevel,
    TrustRecord,
)
from .router import RegistryRouter
from .steward_protocol_compat import build_maha_route_header_hex, load_steward_protocol_bindings
from .transport import DeliveryEnvelope, DeliveryReceipt, RelayService, TransportRegistry
from .trust import InMemoryTrustEngine


STEWARD_PROTOCOL_REPO_ID = "steward-protocol"
AGENT_INTERNET_REPO_ID = "agent-internet"
STEWARD_PUBLIC_WIKI_BINDING_ID = "steward-public-wiki"


@dataclass(slots=True)
class AgentInternetControlPlane:
    registry: InMemoryCityRegistry = field(default_factory=InMemoryCityRegistry)
    trust_engine: InMemoryTrustEngine = field(default_factory=InMemoryTrustEngine)
    minimum_trust: TrustLevel = TrustLevel.OBSERVED
    router: RegistryRouter = field(init=False)
    transports: TransportRegistry = field(default_factory=TransportRegistry)
    relay: RelayService = field(init=False)

    def __post_init__(self) -> None:
        self.router = RegistryRouter(
            registry=self.registry,
            discovery=self.registry,
            trust_engine=self.trust_engine,
            minimum_trust=self.minimum_trust,
        )
        self.relay = RelayService(router=self.router, registry=self.transports)

    def register_city(self, identity: CityIdentity, endpoint: CityEndpoint) -> None:
        self.registry.upsert_identity(identity)
        self.registry.upsert_endpoint(endpoint)
        self.assign_lotus_addresses(identity.city_id)

    def announce_city(self, presence: CityPresence) -> None:
        self.registry.announce(presence)

    def record_trust(self, trust: TrustRecord) -> None:
        self.trust_engine.record(trust)

    def resolve_route(self, source_city_id: str, target_city_id: str) -> CityEndpoint | None:
        return self.router.resolve(source_city_id, target_city_id)

    def assign_lotus_addresses(
        self,
        city_id: str,
        *,
        ttl_s: float | None = None,
    ) -> tuple[LotusLinkAddress, LotusNetworkAddress]:
        return (
            self.registry.assign_link_address(city_id, ttl_s=ttl_s),
            self.registry.assign_network_address(city_id, ttl_s=ttl_s),
        )

    def publish_hosted_endpoint(
        self,
        *,
        owner_city_id: str,
        public_handle: str,
        transport: str,
        location: str,
        visibility: EndpointVisibility = EndpointVisibility.PUBLIC,
        ttl_s: float | None = None,
        endpoint_id: str = "",
        labels: dict[str, str] | None = None,
        now: float | None = None,
    ) -> HostedEndpoint:
        link_address, network_address = self.assign_lotus_addresses(owner_city_id)
        started_at = float(time.time() if now is None else now)
        hosted = HostedEndpoint(
            endpoint_id=endpoint_id or f"{owner_city_id}:{public_handle}",
            owner_city_id=owner_city_id,
            public_handle=public_handle,
            transport=transport,
            location=location,
            link_address=link_address.mac_address,
            network_address=network_address.ip_address,
            visibility=visibility,
            lease_started_at=started_at,
            lease_expires_at=None if ttl_s is None else started_at + max(ttl_s, 0.0),
            labels=dict(labels or {}),
        )
        self.registry.upsert_hosted_endpoint(hosted)
        return hosted

    def resolve_public_handle(self, public_handle: str, *, now: float | None = None) -> HostedEndpoint | None:
        return self.router.resolve_public_handle(public_handle, now=now)

    def publish_service_address(
        self,
        *,
        owner_city_id: str,
        service_name: str,
        public_handle: str,
        transport: str,
        location: str,
        visibility: EndpointVisibility = EndpointVisibility.FEDERATED,
        auth_required: bool = True,
        required_scopes: tuple[str, ...] = (),
        ttl_s: float | None = None,
        service_id: str = "",
        labels: dict[str, str] | None = None,
        now: float | None = None,
    ) -> LotusServiceAddress:
        _, network_address = self.assign_lotus_addresses(owner_city_id)
        started_at = float(time.time() if now is None else now)
        service = LotusServiceAddress(
            service_id=service_id or f"{owner_city_id}:{service_name}",
            owner_city_id=owner_city_id,
            service_name=service_name,
            public_handle=public_handle,
            transport=transport,
            location=location,
            network_address=network_address.ip_address,
            visibility=visibility,
            auth_required=auth_required,
            required_scopes=tuple(required_scopes),
            lease_started_at=started_at,
            lease_expires_at=None if ttl_s is None else started_at + max(ttl_s, 0.0),
            labels=dict(labels or {}),
        )
        self.registry.upsert_service_address(service)
        return service

    def resolve_service_address(self, owner_city_id: str, service_name: str, *, now: float | None = None) -> LotusServiceAddress | None:
        return self.router.resolve_service(owner_city_id, service_name, now=now)

    def publish_route(
        self,
        *,
        owner_city_id: str,
        destination_prefix: str,
        target_city_id: str,
        next_hop_city_id: str,
        metric: int = 100,
        nadi_type: str = "",
        priority: str = "",
        ttl_ms: int | None = None,
        ttl_s: float | None = None,
        route_id: str = "",
        labels: dict[str, str] | None = None,
        now: float | None = None,
    ) -> LotusRoute:
        bindings = load_steward_protocol_bindings()
        selected_nadi_type = nadi_type or bindings.default_route_nadi_type
        selected_priority = priority or bindings.default_route_priority
        if selected_nadi_type not in bindings.allowed_nadi_types:
            raise ValueError(f"invalid_nadi_type:{selected_nadi_type}")
        if selected_priority not in bindings.allowed_priorities:
            raise ValueError(f"invalid_priority:{selected_priority}")

        effective_ttl_ms = int(
            ttl_ms if ttl_ms is not None else (ttl_s * 1000 if ttl_s is not None else bindings.default_timeout_ms),
        )
        started_at = float(time.time() if now is None else now)
        route = LotusRoute(
            route_id=route_id or f"{owner_city_id}:{destination_prefix}:{next_hop_city_id}",
            owner_city_id=owner_city_id,
            destination_prefix=destination_prefix,
            target_city_id=target_city_id,
            next_hop_city_id=next_hop_city_id,
            metric=int(metric),
            nadi_type=selected_nadi_type,
            priority=selected_priority,
            ttl_ms=max(0, effective_ttl_ms),
            maha_header_hex=build_maha_route_header_hex(
                source_key=owner_city_id,
                target_key=target_city_id,
                ttl_ms=max(0, effective_ttl_ms),
                metric=int(metric),
            ),
            lease_started_at=started_at,
            lease_expires_at=None if ttl_s is None else started_at + max(ttl_s, 0.0),
            labels=dict(labels or {}),
        )
        self.registry.upsert_route(route)
        return route

    def resolve_next_hop(self, source_city_id: str, destination: str, *, now: float | None = None) -> LotusRouteResolution | None:
        return self.router.resolve_next_hop(source_city_id, destination, now=now)

    def store_api_token(self, token: LotusApiToken) -> None:
        self.registry.upsert_api_token(token)

    def upsert_space(self, space: SpaceDescriptor) -> None:
        self.registry.upsert_space(space)

    def upsert_slot(self, slot: SlotDescriptor) -> None:
        self.registry.upsert_slot(slot)

    def upsert_fork_lineage(self, lineage: ForkLineageRecord) -> None:
        self.registry.upsert_fork_lineage(lineage)

    def upsert_intent(self, intent: IntentRecord) -> None:
        self.registry.upsert_intent(intent)

    def upsert_repo_role(self, record: RepoRoleRecord) -> None:
        self.registry.upsert_repo_role(record)

    def upsert_authority_export(self, record: AuthorityExportRecord) -> None:
        self.registry.upsert_authority_export(record)

    def upsert_projection_binding(self, record: ProjectionBindingRecord) -> None:
        self.registry.upsert_projection_binding(record)

    def upsert_publication_status(self, record: PublicationStatusRecord) -> None:
        self.registry.upsert_publication_status(record)

    def bootstrap_steward_public_wiki_contract(self, *, now: float | None = None) -> dict[str, object]:
        checked_at = float(time.time() if now is None else now)
        steward_role = RepoRoleRecord(
            repo_id=STEWARD_PROTOCOL_REPO_ID,
            role=RepoRole.NORMATIVE_SOURCE,
            owner_boundary="normative_protocol_surface",
            exports=(
                AuthorityExportKind.CANONICAL_SURFACE.value,
                AuthorityExportKind.PUBLIC_SUMMARY_REGISTRY.value,
                AuthorityExportKind.SOURCE_SURFACE_REGISTRY.value,
                AuthorityExportKind.REPO_GRAPH.value,
                AuthorityExportKind.SURFACE_METADATA.value,
            ),
            publication_targets=(STEWARD_PUBLIC_WIKI_BINDING_ID,),
            labels={"public_surface_owner": AGENT_INTERNET_REPO_ID},
        )
        operator_role = RepoRoleRecord(
            repo_id=AGENT_INTERNET_REPO_ID,
            role=RepoRole.PUBLIC_MEMBRANE_OPERATOR,
            owner_boundary="public_membrane",
            exports=(
                AuthorityExportKind.AGENT_WEB_MANIFEST.value,
                AuthorityExportKind.PUBLIC_GRAPH.value,
                AuthorityExportKind.SEARCH_INDEX.value,
            ),
            consumes=(
                AuthorityExportKind.CANONICAL_SURFACE.value,
                AuthorityExportKind.PUBLIC_SUMMARY_REGISTRY.value,
                AuthorityExportKind.REPO_GRAPH.value,
                AuthorityExportKind.SURFACE_METADATA.value,
            ),
            publication_targets=(STEWARD_PUBLIC_WIKI_BINDING_ID,),
            labels={"projects": STEWARD_PROTOCOL_REPO_ID},
        )
        binding = ProjectionBindingRecord(
            binding_id=STEWARD_PUBLIC_WIKI_BINDING_ID,
            source_repo_id=STEWARD_PROTOCOL_REPO_ID,
            required_export_kind=AuthorityExportKind.CANONICAL_SURFACE,
            operator_repo_id=AGENT_INTERNET_REPO_ID,
            target_kind="github_wiki",
            target_locator="github.com/kimeisele/steward-protocol.wiki.git",
            projection_mode=ProjectionMode.REQUIRED,
            failure_policy=ProjectionFailurePolicy.FAIL_CLOSED,
            freshness_sla_seconds=3600,
            labels={"public_surface": "steward-wiki"},
        )
        export = self.registry.find_authority_export(binding.source_repo_id, binding.required_export_kind.value)
        existing_status = self.registry.get_publication_status(binding.binding_id)
        status = existing_status or PublicationStatusRecord(
            binding_id=binding.binding_id,
            status=PublicationState.BLOCKED if export is None else PublicationState.STALE,
            projected_from_export_id="" if export is None else export.export_id,
            target_kind=binding.target_kind,
            target_locator=binding.target_locator,
            checked_at=checked_at,
            stale=export is not None,
            failure_reason=(
                f"missing_authority_export:{binding.source_repo_id}:{binding.required_export_kind.value}"
                if export is None
                else "projection_not_published"
            ),
        )

        self.registry.upsert_repo_role(steward_role)
        self.registry.upsert_repo_role(operator_role)
        self.registry.upsert_projection_binding(binding)
        if existing_status is None:
            self.registry.upsert_publication_status(status)
        return {
            "source_repo_role": steward_role,
            "operator_repo_role": operator_role,
            "binding": binding,
            "publication_status": self.registry.get_publication_status(binding.binding_id) or status,
        }

    def transition_intent(self, *, intent_id: str, status: IntentStatus, updated_at: float | None = None) -> IntentRecord:
        intent = self.registry.get_intent(intent_id)
        if intent is None:
            raise ValueError(f"unknown_intent:{intent_id}")
        allowed_transitions = {
            IntentStatus.PENDING: {IntentStatus.ACCEPTED, IntentStatus.REJECTED, IntentStatus.CANCELLED},
            IntentStatus.ACCEPTED: {IntentStatus.FULFILLED, IntentStatus.CANCELLED},
        }
        if status not in allowed_transitions.get(intent.status, set()):
            raise ValueError(f"invalid_intent_transition:{intent.status.value}->{status.value}")
        updated = replace(intent, status=status, updated_at=updated_at)
        self.registry.upsert_intent(updated)
        return updated

    def publish_assistant_surface(self, snapshot: AssistantSurfaceSnapshot) -> tuple[SpaceDescriptor, SlotDescriptor]:
        space = assistant_space_from_snapshot(snapshot)
        slot = assistant_social_slot_from_snapshot(snapshot)
        self.registry.upsert_space(space)
        self.registry.upsert_slot(slot)
        return space, slot

    def register_transport(self, scheme: str, transport: object) -> None:
        self.transports.register(scheme, transport)

    def relay_envelope(self, envelope: DeliveryEnvelope) -> DeliveryReceipt:
        return self.relay.relay(envelope)

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
