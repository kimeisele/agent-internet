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
    INTENT_WRITE = "lotus.write.intent"
    INTENT_SUBJECT_DELEGATE = "lotus.write.intent.subject"
    INTENT_REVIEW = "lotus.write.intent.review"
    TOKEN_WRITE = "lotus.write.token"


class SpaceKind(StrEnum):
    CITY = "city"
    HIL = "hil"
    GUILD = "guild"
    ASSISTANT = "assistant"
    CLUSTER = "cluster"
    PUBLIC_SURFACE = "public_surface"


class SlotStatus(StrEnum):
    UNKNOWN = "unknown"
    ACTIVE = "active"
    DORMANT = "dormant"


class ForkMode(StrEnum):
    MIRROR = "mirror"
    EXPERIMENT = "experiment"
    SOVEREIGN = "sovereign"
    SERVICE_DERIVATIVE = "service_derivative"
    ASSISTANT_DERIVATIVE = "assistant_derivative"


class UpstreamSyncPolicy(StrEnum):
    MANUAL_ONLY = "manual_only"
    TRACKED = "tracked"
    ADVISORY = "advisory"
    MERGE_CANDIDATE = "merge_candidate"
    ISOLATED = "isolated"


class IntentType(StrEnum):
    REQUEST_SPACE_CLAIM = "request_space_claim"
    REQUEST_SLOT = "request_slot"
    REQUEST_FORK = "request_fork"
    REQUEST_ISSUE = "request_issue"
    REQUEST_PR_DRAFT = "request_pr_draft"
    REQUEST_OPERATOR_REVIEW = "request_operator_review"


class IntentStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


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
class AssistantSurfaceSnapshot:
    assistant_id: str
    assistant_kind: str
    city_id: str
    city_slug: str = ""
    repo: str = ""
    repo_root: str = ""
    heartbeat_source: str = "steward-protocol/mahamantra"
    heartbeat: int | None = None
    last_seen_at: float | None = None
    city_health: HealthStatus = HealthStatus.UNKNOWN
    capabilities: tuple[str, ...] = ()
    state_present: bool = False
    following: int = 0
    invited: int = 0
    spotlighted: int = 0
    total_follows: int = 0
    total_invites: int = 0
    total_posts: int = 0
    last_post_age_s: int | None = None
    series_cursor: int = -1


@dataclass(frozen=True, slots=True)
class SpaceDescriptor:
    space_id: str
    kind: SpaceKind
    owner_subject_id: str
    display_name: str = ""
    city_id: str = ""
    repo: str = ""
    heartbeat_source: str = ""
    heartbeat: int | None = None
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SlotDescriptor:
    slot_id: str
    space_id: str
    slot_kind: str
    holder_subject_id: str
    status: SlotStatus = SlotStatus.UNKNOWN
    capacity: int = 1
    heartbeat_source: str = ""
    heartbeat: int | None = None
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ForkLineageRecord:
    lineage_id: str
    repo: str
    upstream_repo: str
    line_root_repo: str
    fork_mode: ForkMode = ForkMode.EXPERIMENT
    sync_policy: UpstreamSyncPolicy = UpstreamSyncPolicy.MANUAL_ONLY
    space_id: str = ""
    upstream_space_id: str = ""
    forked_by_subject_id: str = ""
    created_at: float | None = None
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IntentRecord:
    intent_id: str
    intent_type: IntentType
    status: IntentStatus = IntentStatus.PENDING
    title: str = ""
    description: str = ""
    requested_by_subject_id: str = ""
    repo: str = ""
    city_id: str = ""
    space_id: str = ""
    slot_id: str = ""
    lineage_id: str = ""
    discussion_id: str = ""
    linked_issue_url: str = ""
    linked_pr_url: str = ""
    created_at: float | None = None
    updated_at: float | None = None
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TrustRecord:
    issuer_city_id: str
    subject_city_id: str
    level: TrustLevel
    reason: str = ""
