from __future__ import annotations

from dataclasses import field, dataclass
from enum import StrEnum


class HealthStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class TrustLevel(StrEnum):
    UNKNOWN = "unknown"
    OBSERVED = "observed"
    VERIFIED = "verified"
    TRUSTED = "trusted"


class EndpointVisibility(StrEnum):
    PRIVATE = "private"
    FEDERATED = "federated"
    PUBLIC = "public"


class LotusApiScope(StrEnum):
    READ = "lotus.read"
    ADDRESS_WRITE = "lotus.write.address"
    ENDPOINT_WRITE = "lotus.write.endpoint"
    SERVICE_WRITE = "lotus.write.service"
    TOKEN_WRITE = "lotus.write.token"


@dataclass(frozen=True, slots=True)
class CityIdentity:
    city_id: str
    slug: str
    repo: str
    public_key: str = ""
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CityEndpoint:
    city_id: str
    transport: str
    location: str


@dataclass(frozen=True, slots=True)
class LotusLinkAddress:
    city_id: str
    mac_address: str
    interface: str = "lotus0"
    lease_started_at: float | None = None
    lease_expires_at: float | None = None


@dataclass(frozen=True, slots=True)
class LotusNetworkAddress:
    city_id: str
    ip_address: str
    prefix_length: int = 64
    lease_started_at: float | None = None
    lease_expires_at: float | None = None


@dataclass(frozen=True, slots=True)
class HostedEndpoint:
    endpoint_id: str
    owner_city_id: str
    public_handle: str
    transport: str
    location: str
    link_address: str
    network_address: str
    visibility: EndpointVisibility = EndpointVisibility.PUBLIC
    lease_started_at: float | None = None
    lease_expires_at: float | None = None
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LotusServiceAddress:
    service_id: str
    owner_city_id: str
    service_name: str
    public_handle: str
    transport: str
    location: str
    network_address: str
    visibility: EndpointVisibility = EndpointVisibility.FEDERATED
    auth_required: bool = True
    required_scopes: tuple[str, ...] = ()
    lease_started_at: float | None = None
    lease_expires_at: float | None = None
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LotusRoute:
    route_id: str
    owner_city_id: str
    destination_prefix: str
    target_city_id: str
    next_hop_city_id: str
    metric: int = 100
    nadi_type: str = "vyana"
    priority: str = "rajas"
    ttl_ms: int = 24_000
    maha_header_hex: str = ""
    lease_started_at: float | None = None
    lease_expires_at: float | None = None
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LotusRouteResolution:
    destination: str
    matched_prefix: str
    route_id: str
    target_city_id: str
    next_hop_city_id: str
    next_hop_endpoint: CityEndpoint
    nadi_type: str
    priority: str
    ttl_ms: int
    maha_header_hex: str = ""


@dataclass(frozen=True, slots=True)
class LotusApiToken:
    token_id: str
    subject: str
    token_hint: str
    token_sha256: str
    scopes: tuple[str, ...] = ()
    issued_at: float | None = None
    revoked_at: float | None = None


@dataclass(frozen=True, slots=True)
class CityPresence:
    city_id: str
    health: HealthStatus = HealthStatus.UNKNOWN
    last_seen_at: float | None = None
    heartbeat: int | None = None
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TrustRecord:
    issuer_city_id: str
    subject_city_id: str
    level: TrustLevel
    reason: str = ""
