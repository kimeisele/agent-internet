"""Public entrypoints for the Agent Internet control plane."""

from .agent_city_directives import AgentCityDirectiveFactory, AgentCityDirectiveType, validate_agent_city_directive
from .agent_city_directive_bridge import (
    AgentCityDirectiveExecutionAdapter,
    AgentCityDirectiveExecutionBindings,
    DirectiveExecutionResult,
    load_agent_city_directive_execution_bindings,
)
from .assistant_surface import (
    assistant_social_slot_from_snapshot,
    assistant_space_from_snapshot,
    assistant_surface_snapshot_from_repo_root,
)
from .agent_city_phase_tick_bridge import (
    AgentCityPhaseTickAdapter,
    AgentCityPhaseTickBindings,
    PhaseTickResult,
    load_agent_city_phase_tick_bindings,
)
from .agent_city_immigration import (
    AgentCityImmigrationAdapter,
    AgentCityImmigrationBindings,
    load_agent_city_immigration_bindings,
)
from .agent_city_mission_bridge import AgentCityMissionExecutionAdapter, MissionExecutionResult
from .agent_city_peer import AgentCityPeer
from .agent_city_bridge import AgentCityBridge, city_presence_from_report
from .agent_city_contract import AgentCityFilesystemContract
from .control_plane import AgentInternetControlPlane
from .file_locking import locked_file, read_locked_json_value, update_locked_json_value, write_locked_json_value
from .git_federation import GitRemoteMetadata, GitWikiFederationSync, detect_git_remote_metadata, ensure_git_checkout
from .filesystem_transport import FilesystemFederationTransport
from .filesystem_message_transport import AgentCityFilesystemMessageTransport
from .interfaces import CityRegistry, DiscoveryService, FederationTransport, InternetRouter, TrustEngine
from .local_lab import LocalDualCityLab
from .lotus_api import IssuedLotusApiToken, LotusControlPlaneAPI
from .lotus_daemon import LotusApiDaemon
from .memory_registry import InMemoryCityRegistry
from .models import (
    AssistantSurfaceSnapshot,
    CityEndpoint,
    CityIdentity,
    CityPresence,
    ClaimStatus,
    EndpointVisibility,
    ForkLineageRecord,
    ForkMode,
    HealthStatus,
    HostedEndpoint,
    IntentRecord,
    IntentStatus,
    IntentType,
    LotusApiScope,
    LotusApiToken,
    LotusLinkAddress,
    LotusNetworkAddress,
    LotusRoute,
    LotusRouteResolution,
    LotusServiceAddress,
    LeaseStatus,
    SlotDescriptor,
    SlotLeaseRecord,
    SlotStatus,
    SpaceClaimRecord,
    SpaceDescriptor,
    SpaceKind,
    TrustLevel,
    TrustRecord,
    UpstreamSyncPolicy,
)
from .receipt_store import FilesystemReceiptStore
from .router import RegistryRouter
from .snapshot import ControlPlaneStateStore, restore_control_plane, snapshot_control_plane
from .steward_protocol_compat import StewardProtocolBindings, load_steward_protocol_bindings
from .steward_substrate import StewardSubstrateBindings, load_steward_substrate
from .steward_federation import StewardFederationAdapter
from .sync_worker import BidirectionalSyncWorker, SyncCycleResult
from .pump import OutboxRelayPump
from .transport import (
    DeliveryEnvelope,
    DeliveryReceipt,
    DeliveryStatus,
    LoopbackTransport,
    RelayService,
    TransportRegistry,
    TransportScheme,
)
from .trust import InMemoryTrustEngine, trust_allows

# --- New modules (v0.2) ---
from .event_bus import Event, EventBus, EventKind, Subscription
from .trust_enhanced import (
    EnhancedTrustEngine,
    EnhancedTrustRecord,
    EvidenceKind,
    RevocationReason,
    TrustDelegation,
    TrustEvidence,
)
from .thread_safe_registry import ThreadSafeRegistryWrapper
from .https_transport import HttpsTransport, HttpsTransportConfig
from .intent_actuators import (
    ActuationContext,
    ActuationOutcome,
    ActuatorResult,
    IntentActuatorRegistry,
)
from .contract_verification import (
    ContractManifest,
    ContractVerificationResult,
    ContractVerifier,
    CapabilityDescriptor,
    VerificationStatus,
)
from .discovery_bootstrap import (
    DiscoveryAnnouncement,
    DiscoveryBootstrapService,
    DiscoveryPeer,
    FilesystemBeaconScanner,
)
from .operator_status import OperatorDashboard, build_operator_dashboard, format_dashboard_text
from .sqlite_registry import SqliteCityRegistry

# --- Agent Web Repo Graph (federation surface) ---
from .agent_web_repo_graph import (
    build_agent_web_repo_graph_snapshot,
    read_agent_web_repo_graph_context,
    read_agent_web_repo_graph_neighbors,
)
from .agent_web_repo_graph_capabilities import (
    build_agent_web_repo_graph_capability_manifest,
    render_agent_web_repo_graph_capability_page,
)
from .agent_web_repo_graph_contracts import (
    build_agent_web_repo_graph_contract_manifest,
    read_agent_web_repo_graph_contract_descriptor,
    render_agent_web_repo_graph_contract_page,
)

# --- Agent Web Browser (internet explorer for agents) ---
from .agent_web_browser import (
    AgentWebBrowser,
    BrowserConfig,
    BrowserPage,
    BrowserTab,
    FormField,
    PageForm,
    PageLink,
    PageMeta,
    PageSource,
    fetch_url,
    parse_html,
)
from .agent_web_browser_github import GitHubBrowserSource, create_github_browser

__all__ = [
    "AgentCityDirectiveFactory",
    "AgentCityDirectiveExecutionAdapter",
    "AgentCityDirectiveExecutionBindings",
    "AgentCityDirectiveType",
    "AgentCityFilesystemMessageTransport",
    "AgentCityImmigrationAdapter",
    "AgentCityImmigrationBindings",
    "AgentCityMissionExecutionAdapter",
    "AgentCityPhaseTickAdapter",
    "AgentCityPhaseTickBindings",
    "AgentCityBridge",
    "AgentCityFilesystemContract",
    "AgentCityPeer",
    "AgentInternetControlPlane",
    "AssistantSurfaceSnapshot",
    "SlotDescriptor",
    "SlotStatus",
    "SpaceDescriptor",
    "SpaceKind",
    "ForkLineageRecord",
    "ForkMode",
    "UpstreamSyncPolicy",
    "IntentRecord",
    "IntentStatus",
    "IntentType",
    "BidirectionalSyncWorker",
    "CityEndpoint",
    "CityIdentity",
    "CityPresence",
    "CityRegistry",
    "ControlPlaneStateStore",
    "DeliveryEnvelope",
    "DeliveryReceipt",
    "DeliveryStatus",
    "DirectiveExecutionResult",
    "DiscoveryService",
    "EndpointVisibility",
    "FederationTransport",
    "FilesystemFederationTransport",
    "FilesystemReceiptStore",
    "GitRemoteMetadata",
    "GitWikiFederationSync",
    "HealthStatus",
    "HostedEndpoint",
    "InMemoryCityRegistry",
    "InMemoryTrustEngine",
    "IssuedLotusApiToken",
    "InternetRouter",
    "LoopbackTransport",
    "LocalDualCityLab",
    "locked_file",
    "LotusApiDaemon",
    "LotusApiScope",
    "LotusApiToken",
    "LotusControlPlaneAPI",
    "LotusLinkAddress",
    "LotusNetworkAddress",
    "LotusRoute",
    "LotusRouteResolution",
    "LotusServiceAddress",
    "MissionExecutionResult",
    "OutboxRelayPump",
    "PhaseTickResult",
    "read_locked_json_value",
    "RelayService",
    "RegistryRouter",
    "StewardFederationAdapter",
    "StewardProtocolBindings",
    "StewardSubstrateBindings",
    "SyncCycleResult",
    "TransportRegistry",
    "TransportScheme",
    "TrustEngine",
    "TrustLevel",
    "TrustRecord",
    "update_locked_json_value",
    "assistant_social_slot_from_snapshot",
    "assistant_space_from_snapshot",
    "assistant_surface_snapshot_from_repo_root",
    "city_presence_from_report",
    "detect_git_remote_metadata",
    "ensure_git_checkout",
    "load_agent_city_directive_execution_bindings",
    "load_agent_city_phase_tick_bindings",
    "load_steward_protocol_bindings",
    "load_steward_substrate",
    "load_agent_city_immigration_bindings",
    "restore_control_plane",
    "snapshot_control_plane",
    "trust_allows",
    "validate_agent_city_directive",
    "write_locked_json_value",
    # --- New modules (v0.2) ---
    "Event",
    "EventBus",
    "EventKind",
    "Subscription",
    "EnhancedTrustEngine",
    "EnhancedTrustRecord",
    "EvidenceKind",
    "RevocationReason",
    "TrustDelegation",
    "TrustEvidence",
    "ThreadSafeRegistryWrapper",
    "HttpsTransport",
    "HttpsTransportConfig",
    "ActuationContext",
    "ActuationOutcome",
    "ActuatorResult",
    "IntentActuatorRegistry",
    "ContractManifest",
    "ContractVerificationResult",
    "ContractVerifier",
    "CapabilityDescriptor",
    "VerificationStatus",
    "DiscoveryAnnouncement",
    "DiscoveryBootstrapService",
    "DiscoveryPeer",
    "FilesystemBeaconScanner",
    "OperatorDashboard",
    "build_operator_dashboard",
    "format_dashboard_text",
    "SqliteCityRegistry",
    # --- Agent Web Repo Graph (federation surface) ---
    "build_agent_web_repo_graph_snapshot",
    "read_agent_web_repo_graph_context",
    "read_agent_web_repo_graph_neighbors",
    "build_agent_web_repo_graph_capability_manifest",
    "render_agent_web_repo_graph_capability_page",
    "build_agent_web_repo_graph_contract_manifest",
    "read_agent_web_repo_graph_contract_descriptor",
    "render_agent_web_repo_graph_contract_page",
    # --- Agent Web Browser (internet explorer for agents) ---
    "AgentWebBrowser",
    "BrowserConfig",
    "BrowserPage",
    "BrowserTab",
    "FormField",
    "GitHubBrowserSource",
    "PageForm",
    "PageLink",
    "PageMeta",
    "PageSource",
    "create_github_browser",
    "fetch_url",
    "parse_html",
]
