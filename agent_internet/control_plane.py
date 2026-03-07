from __future__ import annotations

import time
from dataclasses import dataclass, field

from .agent_city_bridge import AgentCityBridge
from .memory_registry import InMemoryCityRegistry
from .models import (
    CityEndpoint,
    CityIdentity,
    CityPresence,
    EndpointVisibility,
    HostedEndpoint,
    LotusApiToken,
    LotusLinkAddress,
    LotusNetworkAddress,
    LotusServiceAddress,
    TrustLevel,
    TrustRecord,
)
from .router import RegistryRouter
from .transport import DeliveryEnvelope, DeliveryReceipt, RelayService, TransportRegistry
from .trust import InMemoryTrustEngine


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

    def store_api_token(self, token: LotusApiToken) -> None:
        self.registry.upsert_api_token(token)

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
