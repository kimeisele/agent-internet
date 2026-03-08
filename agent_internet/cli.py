from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .agent_web import build_agent_web_manifest_from_repo_root
from .agent_web_crawl import build_agent_web_crawl_bootstrap, search_agent_web_crawl_bootstrap
from .agent_web_federated_index import (
    DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH,
    load_agent_web_federated_index,
    refresh_agent_web_federated_index,
    search_agent_web_federated_index,
)
from .agent_web_semantic_graph import read_agent_web_semantic_neighbors
from .agent_web_graph import build_agent_web_public_graph_from_repo_root
from .agent_web_index import build_agent_web_search_index_from_repo_root, search_agent_web_index
from .agent_web_navigation import read_agent_web_document_from_repo_root
from .agent_web_semantic_capabilities import build_agent_web_semantic_capability_manifest
from .agent_web_semantic_contracts import build_agent_web_semantic_contract_manifest, read_agent_web_semantic_contract_descriptor
from .agent_web_source_registry import (
    DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH,
    build_agent_web_crawl_bootstrap_from_registry,
    load_agent_web_source_registry,
    remove_agent_web_source_registry_entry,
    search_agent_web_crawl_bootstrap_from_registry,
    upsert_agent_web_source_registry_entry,
)
from .agent_web_semantic_overlay import (
    DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH,
    expand_query_with_agent_web_semantic_overlay,
    load_agent_web_semantic_overlay,
    refresh_agent_web_semantic_overlay,
    remove_agent_web_semantic_bridge,
    upsert_agent_web_semantic_bridge,
)
from .agent_web_wordnet_bridge import load_agent_web_wordnet_bridge
from .agent_city_peer import AgentCityPeer
from .assistant_surface import assistant_surface_snapshot_from_repo_root
from .git_federation import GitWikiFederationSync, detect_git_remote_metadata, ensure_git_checkout
from .local_lab import LocalDualCityLab
from .lotus_api import LOTUS_MUTATING_ACTIONS, LotusControlPlaneAPI
from .lotus_daemon import LotusApiDaemon
from .models import EndpointVisibility, LotusApiScope, TrustLevel, TrustRecord
from .snapshot import ControlPlaneStateStore, snapshot_control_plane
from .steward_protocol_compat import summarize_steward_protocol_bindings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-internet")
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish_peer = subparsers.add_parser(
        "publish-agent-city-peer",
        help="Write a self-description file so an agent-city repo can be auto-discovered",
    )
    publish_peer.add_argument("--root", required=True)
    publish_peer.add_argument("--city-id", required=True)
    publish_peer.add_argument("--repo")
    publish_peer.add_argument("--slug")
    publish_peer.add_argument("--public-key", default="")
    publish_peer.add_argument("--capability", action="append", default=[])
    publish_peer.add_argument("--endpoint-transport", default="filesystem")
    publish_peer.add_argument("--endpoint-location")

    onboard = subparsers.add_parser("onboard-agent-city", help="Onboard an agent-city repository root")
    onboard.add_argument("--root", required=True)
    onboard.add_argument("--city-id")
    onboard.add_argument("--repo")
    onboard.add_argument("--slug")
    onboard.add_argument("--public-key", default="")
    onboard.add_argument("--capability", action="append", default=[])
    onboard.add_argument("--endpoint-transport", default="filesystem")
    onboard.add_argument("--endpoint-location")
    onboard.add_argument("--discover", action="store_true")
    onboard.add_argument("--state-path", default="data/control_plane/state.json")
    onboard.add_argument("--trust-source", default="agent-internet")
    onboard.add_argument(
        "--trust-level",
        choices=[level.value for level in TrustLevel],
        default=TrustLevel.OBSERVED.value,
    )

    show = subparsers.add_parser("show-state", help="Print the current persisted control-plane state")
    show.add_argument("--state-path", default="data/control_plane/state.json")

    assistant_snapshot = subparsers.add_parser(
        "agent-city-assistant-snapshot",
        help="Project the current Moltbook assistant surface from an agent-city repo",
    )
    assistant_snapshot.add_argument("--root", required=True)
    assistant_snapshot.add_argument("--city-id")
    assistant_snapshot.add_argument("--assistant-id", default="moltbook_assistant")
    assistant_snapshot.add_argument("--heartbeat-source", default="steward-protocol/mahamantra")

    agent_web_manifest = subparsers.add_parser(
        "agent-web-manifest",
        help="Project a machine-readable agent-web manifest from an agent-city repo",
    )
    agent_web_manifest.add_argument("--root", required=True)
    agent_web_manifest.add_argument("--state-path", default="data/control_plane/state.json")
    agent_web_manifest.add_argument("--city-id")
    agent_web_manifest.add_argument("--assistant-id", default="moltbook_assistant")
    agent_web_manifest.add_argument("--heartbeat-source", default="steward-protocol/mahamantra")

    agent_web_graph = subparsers.add_parser(
        "agent-web-graph",
        help="Project a derived public graph from an agent-city repo",
    )
    agent_web_graph.add_argument("--root", required=True)
    agent_web_graph.add_argument("--state-path", default="data/control_plane/state.json")
    agent_web_graph.add_argument("--city-id")
    agent_web_graph.add_argument("--assistant-id", default="moltbook_assistant")
    agent_web_graph.add_argument("--heartbeat-source", default="steward-protocol/mahamantra")

    agent_web_semantic_capabilities = subparsers.add_parser(
        "agent-web-semantic-capabilities",
        help="Print the consumer-agnostic semantic capability manifest",
    )
    agent_web_semantic_capabilities.add_argument("--base-url")

    agent_web_semantic_contracts = subparsers.add_parser(
        "agent-web-semantic-contracts",
        help="Print semantic contract descriptors or a single contract descriptor",
    )
    agent_web_semantic_contracts.add_argument("--base-url")
    agent_web_semantic_contracts.add_argument("--capability-id")
    agent_web_semantic_contracts.add_argument("--contract-id")
    agent_web_semantic_contracts.add_argument("--version", type=int)

    agent_web_index = subparsers.add_parser(
        "agent-web-index",
        help="Project a derived search index from an agent-city repo",
    )
    agent_web_index.add_argument("--root", required=True)
    agent_web_index.add_argument("--state-path", default="data/control_plane/state.json")
    agent_web_index.add_argument("--city-id")
    agent_web_index.add_argument("--assistant-id", default="moltbook_assistant")
    agent_web_index.add_argument("--heartbeat-source", default="steward-protocol/mahamantra")

    agent_web_search = subparsers.add_parser(
        "agent-web-search",
        help="Query the derived search index for an agent-city repo",
    )
    agent_web_search.add_argument("--root", required=True)
    agent_web_search.add_argument("--state-path", default="data/control_plane/state.json")
    agent_web_search.add_argument("--city-id")
    agent_web_search.add_argument("--assistant-id", default="moltbook_assistant")
    agent_web_search.add_argument("--heartbeat-source", default="steward-protocol/mahamantra")
    agent_web_search.add_argument("--query", required=True)
    agent_web_search.add_argument("--limit", type=int, default=10)

    agent_web_crawl = subparsers.add_parser(
        "agent-web-crawl",
        help="Bootstrap a multi-root crawl view across multiple agent-city repos",
    )
    agent_web_crawl.add_argument("--root", dest="roots", action="append", required=True)
    agent_web_crawl.add_argument("--state-path", default="data/control_plane/state.json")
    agent_web_crawl.add_argument("--assistant-id", default="moltbook_assistant")
    agent_web_crawl.add_argument("--heartbeat-source", default="steward-protocol/mahamantra")

    agent_web_crawl_search = subparsers.add_parser(
        "agent-web-crawl-search",
        help="Search across a multi-root crawl bootstrap view",
    )
    agent_web_crawl_search.add_argument("--root", dest="roots", action="append", required=True)
    agent_web_crawl_search.add_argument("--state-path", default="data/control_plane/state.json")
    agent_web_crawl_search.add_argument("--assistant-id", default="moltbook_assistant")
    agent_web_crawl_search.add_argument("--heartbeat-source", default="steward-protocol/mahamantra")
    agent_web_crawl_search.add_argument("--query", required=True)
    agent_web_crawl_search.add_argument("--limit", type=int, default=10)

    agent_web_source_registry = subparsers.add_parser(
        "agent-web-source-registry",
        help="Show the local source registry for crawl bootstrap seeds",
    )
    agent_web_source_registry.add_argument("--registry-path", default=DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH)

    agent_web_source_add = subparsers.add_parser(
        "agent-web-source-add",
        help="Add or update a crawl source in the local source registry",
    )
    agent_web_source_add.add_argument("--registry-path", default=DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH)
    agent_web_source_add.add_argument("--root", required=True)
    agent_web_source_add.add_argument("--source-id")
    agent_web_source_add.add_argument("--label", dest="labels", action="append", default=[])
    agent_web_source_add.add_argument("--notes", default="")
    agent_web_source_add.add_argument("--disabled", action="store_true")

    agent_web_source_remove = subparsers.add_parser(
        "agent-web-source-remove",
        help="Remove a crawl source from the local source registry",
    )
    agent_web_source_remove.add_argument("--registry-path", default=DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH)
    agent_web_source_remove.add_argument("--root")
    agent_web_source_remove.add_argument("--source-id")

    agent_web_crawl_registry = subparsers.add_parser(
        "agent-web-crawl-registry",
        help="Bootstrap crawl view from the local source registry",
    )
    agent_web_crawl_registry.add_argument("--registry-path", default=DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH)
    agent_web_crawl_registry.add_argument("--state-path", default="data/control_plane/state.json")
    agent_web_crawl_registry.add_argument("--assistant-id", default="moltbook_assistant")
    agent_web_crawl_registry.add_argument("--heartbeat-source", default="steward-protocol/mahamantra")

    agent_web_crawl_registry_search = subparsers.add_parser(
        "agent-web-crawl-registry-search",
        help="Search across crawl sources loaded from the local source registry",
    )
    agent_web_crawl_registry_search.add_argument("--registry-path", default=DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH)
    agent_web_crawl_registry_search.add_argument("--state-path", default="data/control_plane/state.json")
    agent_web_crawl_registry_search.add_argument("--assistant-id", default="moltbook_assistant")
    agent_web_crawl_registry_search.add_argument("--heartbeat-source", default="steward-protocol/mahamantra")
    agent_web_crawl_registry_search.add_argument("--query", required=True)
    agent_web_crawl_registry_search.add_argument("--limit", type=int, default=10)

    agent_web_federated_index_refresh = subparsers.add_parser(
        "agent-web-federated-index-refresh",
        help="Refresh the persisted federated index from the local source registry",
    )
    agent_web_federated_index_refresh.add_argument("--index-path", default=DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH)
    agent_web_federated_index_refresh.add_argument("--registry-path", default=DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH)
    agent_web_federated_index_refresh.add_argument("--state-path", default="data/control_plane/state.json")
    agent_web_federated_index_refresh.add_argument("--overlay-path", default=DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH)
    agent_web_federated_index_refresh.add_argument("--wordnet-path")
    agent_web_federated_index_refresh.add_argument("--assistant-id", default="moltbook_assistant")
    agent_web_federated_index_refresh.add_argument("--heartbeat-source", default="steward-protocol/mahamantra")

    agent_web_federated_index = subparsers.add_parser(
        "agent-web-federated-index",
        help="Read the persisted federated index",
    )
    agent_web_federated_index.add_argument("--index-path", default=DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH)

    agent_web_federated_search = subparsers.add_parser(
        "agent-web-federated-search",
        help="Search the persisted federated index",
    )
    agent_web_federated_search.add_argument("--index-path", default=DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH)
    agent_web_federated_search.add_argument("--overlay-path", default=DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH)
    agent_web_federated_search.add_argument("--wordnet-path")
    agent_web_federated_search.add_argument("--query", required=True)
    agent_web_federated_search.add_argument("--limit", type=int, default=10)

    agent_web_semantic_overlay = subparsers.add_parser(
        "agent-web-semantic-overlay",
        help="Read the local semantic overlay used for federated search expansion",
    )
    agent_web_semantic_overlay.add_argument("--overlay-path", default=DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH)

    agent_web_semantic_overlay_refresh = subparsers.add_parser(
        "agent-web-semantic-overlay-refresh",
        help="Normalize and persist the local semantic overlay",
    )
    agent_web_semantic_overlay_refresh.add_argument("--overlay-path", default=DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH)

    agent_web_semantic_bridge_add = subparsers.add_parser(
        "agent-web-semantic-bridge-add",
        help="Add or update a semantic bridge for federated search expansion",
    )
    agent_web_semantic_bridge_add.add_argument("--overlay-path", default=DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH)
    agent_web_semantic_bridge_add.add_argument("--bridge-kind", required=True)
    agent_web_semantic_bridge_add.add_argument("--bridge-id")
    agent_web_semantic_bridge_add.add_argument("--term", dest="terms", action="append", required=True)
    agent_web_semantic_bridge_add.add_argument("--expansion", dest="expansions", action="append", required=True)
    agent_web_semantic_bridge_add.add_argument("--weight", type=float)
    agent_web_semantic_bridge_add.add_argument("--notes", default="")
    agent_web_semantic_bridge_add.add_argument("--disabled", action="store_true")

    agent_web_semantic_bridge_remove = subparsers.add_parser(
        "agent-web-semantic-bridge-remove",
        help="Remove a semantic bridge from the local semantic overlay",
    )
    agent_web_semantic_bridge_remove.add_argument("--overlay-path", default=DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH)
    agent_web_semantic_bridge_remove.add_argument("--bridge-id", required=True)

    agent_web_semantic_expand = subparsers.add_parser(
        "agent-web-semantic-expand",
        help="Expand a query through the local semantic overlay",
    )
    agent_web_semantic_expand.add_argument("--overlay-path", default=DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH)
    agent_web_semantic_expand.add_argument("--wordnet-path")
    agent_web_semantic_expand.add_argument("--query", required=True)

    agent_web_semantic_neighbors = subparsers.add_parser(
        "agent-web-semantic-neighbors",
        help="Read persisted semantic neighbors for a federated index record",
    )
    agent_web_semantic_neighbors.add_argument("--index-path", default=DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH)
    agent_web_semantic_neighbors.add_argument("--record-id", required=True)
    agent_web_semantic_neighbors.add_argument("--limit", type=int, default=5)

    agent_web_read = subparsers.add_parser(
        "agent-web-read",
        help="Resolve an agent-web link and read the linked markdown document",
    )
    agent_web_read.add_argument("--root", required=True)
    agent_web_read.add_argument("--state-path", default="data/control_plane/state.json")
    agent_web_read.add_argument("--city-id")
    agent_web_read.add_argument("--assistant-id", default="moltbook_assistant")
    agent_web_read.add_argument("--heartbeat-source", default="steward-protocol/mahamantra")
    agent_web_read.add_argument("--rel", default="agent_web")
    agent_web_read.add_argument("--href")
    agent_web_read.add_argument("--document-id")

    git_describe = subparsers.add_parser(
        "git-federation-describe",
        help="Autodetect git origin/wiki metadata for a repository root",
    )
    git_describe.add_argument("--root", required=True)

    git_sync = subparsers.add_parser(
        "git-federation-sync-wiki",
        help="Project the current control-plane view into the repo's git-backed wiki",
    )
    git_sync.add_argument("--root", required=True)
    git_sync.add_argument("--state-path", default="data/control_plane/state.json")
    git_sync.add_argument("--wiki-repo-url")
    git_sync.add_argument("--wiki-checkout-path")
    git_sync.add_argument("--heartbeat-label", default="manual")

    git_onboard = subparsers.add_parser(
        "git-federation-onboard-repo",
        help="Clone/pull a remote repo, discover its peer descriptor, and onboard it",
    )
    git_onboard.add_argument("--repo-url", required=True)
    git_onboard.add_argument("--checkout-path", required=True)
    git_onboard.add_argument("--state-path", default="data/control_plane/state.json")
    git_onboard.add_argument("--trust-source", default="agent-internet")
    git_onboard.add_argument(
        "--trust-level",
        choices=[level.value for level in TrustLevel],
        default=TrustLevel.OBSERVED.value,
    )

    subparsers.add_parser(
        "lotus-show-steward-protocol",
        help="Show the currently active steward-protocol compatibility bindings",
    )

    lotus_assign = subparsers.add_parser(
        "lotus-assign-addresses",
        help="Allocate MAC- and IPv6-like Lotus addresses for a city in the persisted control plane",
    )
    lotus_assign.add_argument("--state-path", default="data/control_plane/state.json")
    lotus_assign.add_argument("--city-id", required=True)
    lotus_assign.add_argument("--ttl-s", type=float)

    lotus_publish = subparsers.add_parser(
        "lotus-publish-endpoint",
        help="Publish a leaseable Lotus public handle for a city's hosted endpoint",
    )
    lotus_publish.add_argument("--state-path", default="data/control_plane/state.json")
    lotus_publish.add_argument("--city-id", required=True)
    lotus_publish.add_argument("--public-handle", required=True)
    lotus_publish.add_argument("--transport", required=True)
    lotus_publish.add_argument("--location", required=True)
    lotus_publish.add_argument("--endpoint-id", default="")
    lotus_publish.add_argument(
        "--visibility",
        choices=[visibility.value for visibility in EndpointVisibility],
        default=EndpointVisibility.PUBLIC.value,
    )
    lotus_publish.add_argument("--ttl-s", type=float)

    lotus_resolve = subparsers.add_parser(
        "lotus-resolve-handle",
        help="Resolve an active Lotus public handle from the persisted control plane",
    )
    lotus_resolve.add_argument("--state-path", default="data/control_plane/state.json")
    lotus_resolve.add_argument("--public-handle", required=True)

    lotus_publish_service = subparsers.add_parser(
        "lotus-publish-service",
        help="Publish a Lotus service address for a city's API/service endpoint",
    )
    lotus_publish_service.add_argument("--state-path", default="data/control_plane/state.json")
    lotus_publish_service.add_argument("--city-id", required=True)
    lotus_publish_service.add_argument("--service-name", required=True)
    lotus_publish_service.add_argument("--public-handle", required=True)
    lotus_publish_service.add_argument("--transport", required=True)
    lotus_publish_service.add_argument("--location", required=True)
    lotus_publish_service.add_argument("--service-id", default="")
    lotus_publish_service.add_argument(
        "--visibility",
        choices=[visibility.value for visibility in EndpointVisibility],
        default=EndpointVisibility.FEDERATED.value,
    )
    lotus_publish_service.add_argument("--ttl-s", type=float)
    lotus_publish_service.add_argument("--no-auth", action="store_true")
    lotus_publish_service.add_argument("--required-scope", action="append", default=[])

    lotus_resolve_service = subparsers.add_parser(
        "lotus-resolve-service",
        help="Resolve a Lotus service address by city and service name",
    )
    lotus_resolve_service.add_argument("--state-path", default="data/control_plane/state.json")
    lotus_resolve_service.add_argument("--city-id", required=True)
    lotus_resolve_service.add_argument("--service-name", required=True)

    lotus_publish_route = subparsers.add_parser(
        "lotus-publish-route",
        help="Publish a Lotus prefix route with steward-aligned Nadi semantics",
    )
    lotus_publish_route.add_argument("--state-path", default="data/control_plane/state.json")
    lotus_publish_route.add_argument("--owner-city-id", required=True)
    lotus_publish_route.add_argument("--destination-prefix", required=True)
    lotus_publish_route.add_argument("--target-city-id", required=True)
    lotus_publish_route.add_argument("--next-hop-city-id", required=True)
    lotus_publish_route.add_argument("--route-id", default="")
    lotus_publish_route.add_argument("--metric", type=int, default=100)
    lotus_publish_route.add_argument("--nadi-type", default="")
    lotus_publish_route.add_argument("--priority", dest="priority", default="")
    lotus_publish_route.add_argument("--nadi-priority", dest="priority")
    lotus_publish_route.add_argument("--ttl-ms", type=int)
    lotus_publish_route.add_argument("--ttl-s", type=float)

    lotus_resolve_next_hop = subparsers.add_parser(
        "lotus-resolve-next-hop",
        help="Resolve the best Lotus next hop for a destination string using prefix routes",
    )
    lotus_resolve_next_hop.add_argument("--state-path", default="data/control_plane/state.json")
    lotus_resolve_next_hop.add_argument("--source-city-id", required=True)
    lotus_resolve_next_hop.add_argument("--destination", required=True)

    lotus_issue_token = subparsers.add_parser(
        "lotus-issue-token",
        help="Issue a scoped Lotus bearer token for authenticated API access",
    )
    lotus_issue_token.add_argument("--state-path", default="data/control_plane/state.json")
    lotus_issue_token.add_argument("--subject", required=True)
    lotus_issue_token.add_argument("--token-id", default="")
    lotus_issue_token.add_argument("--scope", action="append", default=[])

    lotus_api_call = subparsers.add_parser(
        "lotus-api-call",
        help="Execute a direct authenticated Lotus API action against the persisted control plane",
    )
    lotus_api_call.add_argument("--state-path", default="data/control_plane/state.json")
    lotus_api_call.add_argument("--token", required=True)
    lotus_api_call.add_argument("--action", required=True)
    lotus_api_call.add_argument("--params-json", default="{}")

    lotus_api_daemon = subparsers.add_parser(
        "lotus-api-daemon",
        help="Run the authenticated Lotus HTTP control-plane daemon",
    )
    lotus_api_daemon.add_argument("--state-path", default="data/control_plane/state.json")
    lotus_api_daemon.add_argument("--host", default="127.0.0.1")
    lotus_api_daemon.add_argument("--port", type=int, default=8788)

    lab_init = subparsers.add_parser("init-dual-city-lab", help="Create a local two-city filesystem lab")
    lab_init.add_argument("--root", required=True)
    lab_init.add_argument("--city-a-id", default="city-a")
    lab_init.add_argument("--city-b-id", default="city-b")

    lab_send = subparsers.add_parser("lab-send", help="Relay a message between two local lab cities")
    lab_send.add_argument("--root", required=True)
    lab_send.add_argument("--source-city-id", required=True)
    lab_send.add_argument("--target-city-id", required=True)
    lab_send.add_argument("--operation", required=True)
    lab_send.add_argument("--payload-json", default="{}")
    lab_send.add_argument("--correlation-id", default="")
    lab_send.add_argument("--nadi-type", default="")
    lab_send.add_argument("--nadi-op", default="")
    lab_send.add_argument("--nadi-priority", default="")
    lab_send.add_argument("--ttl-ms", type=int)
    lab_send.add_argument("--ttl-s", type=float)

    lab_emit_outbox = subparsers.add_parser(
        "lab-emit-outbox",
        help="Append a message to a local lab city's real federation outbox",
    )
    lab_emit_outbox.add_argument("--root", required=True)
    lab_emit_outbox.add_argument("--source-city-id", required=True)
    lab_emit_outbox.add_argument("--target-city-id", required=True)
    lab_emit_outbox.add_argument("--operation", required=True)
    lab_emit_outbox.add_argument("--payload-json", default="{}")
    lab_emit_outbox.add_argument("--correlation-id", default="")
    lab_emit_outbox.add_argument("--nadi-type", default="")
    lab_emit_outbox.add_argument("--nadi-op", default="")
    lab_emit_outbox.add_argument("--nadi-priority", default="")
    lab_emit_outbox.add_argument("--ttl-ms", type=int)
    lab_emit_outbox.add_argument("--ttl-s", type=float)

    lab_pump_outbox = subparsers.add_parser(
        "lab-pump-outbox",
        help="Pump a local lab city's federation outbox through agent-internet relay",
    )
    lab_pump_outbox.add_argument("--root", required=True)
    lab_pump_outbox.add_argument("--source-city-id", required=True)
    lab_pump_outbox.add_argument("--drain-delivered", action="store_true")

    lab_sync = subparsers.add_parser(
        "lab-sync",
        help="Run bounded bidirectional sync cycles between the two local lab cities",
    )
    lab_sync.add_argument("--root", required=True)
    lab_sync.add_argument("--city-a-id", default="city-a")
    lab_sync.add_argument("--city-b-id", default="city-b")
    lab_sync.add_argument("--cycles", type=int, default=1)
    lab_sync.add_argument("--drain-delivered", action="store_true")

    lab_compact_receipts = subparsers.add_parser(
        "lab-compact-receipts",
        help="Compact a local lab city's receipt journal by age and/or max retained entries",
    )
    lab_compact_receipts.add_argument("--root", required=True)
    lab_compact_receipts.add_argument("--city-id", required=True)
    lab_compact_receipts.add_argument("--max-entries", type=int)
    lab_compact_receipts.add_argument("--older-than-s", type=float)

    lab_issue_directive = subparsers.add_parser(
        "lab-issue-directive",
        help="Write an agent-city federation directive into a local lab city's directive intake",
    )
    lab_issue_directive.add_argument("--root", required=True)
    lab_issue_directive.add_argument("--city-id", required=True)
    lab_issue_directive.add_argument("--directive-type", required=True)
    lab_issue_directive.add_argument("--params-json", default="{}")
    lab_issue_directive.add_argument("--directive-id", default="")
    lab_issue_directive.add_argument("--source", default="agent-internet")

    lab_run_directives = subparsers.add_parser(
        "lab-run-directives",
        help="Execute pending agent-city federation directives through the real GENESIS directive hook",
    )
    lab_run_directives.add_argument("--root", required=True)
    lab_run_directives.add_argument("--city-id", required=True)
    lab_run_directives.add_argument("--agent-name", default="")

    lab_phase_tick = subparsers.add_parser(
        "lab-phase-tick",
        help="Run the real agent-city Mayor phase ticks for a local lab city",
    )
    lab_phase_tick.add_argument("--root", required=True)
    lab_phase_tick.add_argument("--city-id", required=True)
    lab_phase_tick.add_argument("--cycles", type=int, default=1)
    lab_phase_tick.add_argument("--no-governance", action="store_true")
    lab_phase_tick.add_argument("--no-federation", action="store_true")
    lab_phase_tick.add_argument("--ingress-source", default="")
    lab_phase_tick.add_argument("--ingress-text", default="")
    lab_phase_tick.add_argument("--conversation-id", default="")
    lab_phase_tick.add_argument("--from-agent", default="")
    lab_phase_tick.add_argument("--agent-name", default="")

    lab_execute_code = subparsers.add_parser(
        "lab-execute-code",
        help="Issue a real execute_code directive and drive it through the agent-city mission pipeline",
    )
    lab_execute_code.add_argument("--root", required=True)
    lab_execute_code.add_argument("--city-id", required=True)
    lab_execute_code.add_argument("--contract", required=True)
    lab_execute_code.add_argument("--directive-id", default="")
    lab_execute_code.add_argument("--source", default="agent-internet")
    lab_execute_code.add_argument("--cycles", type=int, default=3)
    lab_execute_code.add_argument("--no-governance", action="store_true")
    lab_execute_code.add_argument("--no-federation", action="store_true")

    lab_immigrate = subparsers.add_parser(
        "lab-immigrate",
        help="Run a dual-city immigration flow against a host city's real ImmigrationService",
    )
    lab_immigrate.add_argument("--root", required=True)
    lab_immigrate.add_argument("--source-city-id", required=True)
    lab_immigrate.add_argument("--host-city-id", required=True)
    lab_immigrate.add_argument("--agent-name", required=True)
    lab_immigrate.add_argument("--visa-class", default="worker")
    lab_immigrate.add_argument("--reason", default="temporary_visitor")
    lab_immigrate.add_argument("--sponsor", default="city_genesis")

    return parser


def cmd_publish_agent_city_peer(args: argparse.Namespace) -> int:
    peer = AgentCityPeer.from_repo_root(
        args.root,
        city_id=args.city_id,
        repo=args.repo,
        slug=args.slug,
        public_key=args.public_key,
        capabilities=tuple(args.capability),
        endpoint_transport=args.endpoint_transport,
        endpoint_location=args.endpoint_location,
    )
    payload = peer.publish_self_description()
    print(
        json.dumps(
            {
                "root": str(peer.root),
                "descriptor_path": str(peer.contract.peer_descriptor_path),
                "peer": payload,
            },
            indent=2,
        ),
    )
    return 0


def cmd_git_federation_describe(args: argparse.Namespace) -> int:
    remote = detect_git_remote_metadata(args.root)
    print(json.dumps({
        "repo_root": str(remote.repo_root),
        "origin_url": remote.origin_url,
        "repo_ref": remote.repo_ref,
        "wiki_repo_url": remote.wiki_repo_url,
    }, indent=2))
    return 0


def cmd_git_federation_sync_wiki(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    peer = AgentCityPeer.discover_from_repo_root(root)
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    peer_descriptor = peer.publish_self_description()
    assistant_snapshot = asdict(assistant_surface_snapshot_from_repo_root(root, city_id=peer.identity.city_id))
    git_federation = peer_descriptor.get("git_federation", {})
    effective_wiki_repo_url = args.wiki_repo_url or str(git_federation.get("wiki_repo_url", ""))
    if effective_wiki_repo_url:
        peer_descriptor.setdefault("git_federation", {})["wiki_repo_url"] = effective_wiki_repo_url
    sync = GitWikiFederationSync(
        repo_root=root,
        wiki_repo_url=effective_wiki_repo_url,
        checkout_path=None if not args.wiki_checkout_path else Path(args.wiki_checkout_path),
    )
    result = sync.sync(
        peer_descriptor=peer_descriptor,
        state_snapshot=snapshot_control_plane(plane),
        heartbeat_label=args.heartbeat_label,
        assistant_snapshot=assistant_snapshot,
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_git_federation_onboard_repo(args: argparse.Namespace) -> int:
    checkout = ensure_git_checkout(args.repo_url, args.checkout_path)
    peer = AgentCityPeer.discover_from_repo_root(checkout)
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    observed = peer.onboard(plane)
    projected = _maybe_publish_assistant_surface(plane, checkout, peer.identity.city_id)
    plane.record_trust(
        TrustRecord(
            issuer_city_id=args.trust_source,
            subject_city_id=peer.identity.city_id,
            level=TrustLevel(args.trust_level),
            reason="git federation onboarding",
        ),
    )
    store.save(plane)
    print(
        json.dumps(
            {
                "city_id": peer.identity.city_id,
                "repo_url": args.repo_url,
                "checkout_path": str(checkout),
                "discovered": True,
                "observed": None
                if observed is None
                else {
                    "health": observed.health,
                    "heartbeat": observed.heartbeat,
                    "last_seen_at": observed.last_seen_at,
                },
                "assistant_projection": projected,
                "state_path": str(store.path),
            },
            indent=2,
        ),
    )
    return 0


def cmd_onboard_agent_city(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    if args.discover:
        peer = AgentCityPeer.discover_from_repo_root(args.root)
    else:
        if not args.city_id:
            raise SystemExit("onboard-agent-city requires --city-id unless --discover is set")
        peer = AgentCityPeer.from_repo_root(
            args.root,
            city_id=args.city_id,
            repo=args.repo,
            slug=args.slug,
            public_key=args.public_key,
            capabilities=tuple(args.capability),
            endpoint_transport=args.endpoint_transport,
            endpoint_location=args.endpoint_location,
        )
    observed = peer.onboard(plane)
    projected = _maybe_publish_assistant_surface(plane, args.root, peer.identity.city_id)
    plane.record_trust(
        TrustRecord(
            issuer_city_id=args.trust_source,
            subject_city_id=peer.identity.city_id,
            level=TrustLevel(args.trust_level),
            reason="cli onboarding",
        ),
    )
    store.save(plane)
    print(
        json.dumps(
            {
                "city_id": peer.identity.city_id,
                "discovered": args.discover,
                "observed": None
                if observed is None
                else {
                    "health": observed.health,
                    "heartbeat": observed.heartbeat,
                    "last_seen_at": observed.last_seen_at,
                },
                "assistant_projection": projected,
                "state_path": str(store.path),
            },
            indent=2,
        ),
    )
    return 0


def cmd_show_state(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    print(json.dumps(snapshot_control_plane(plane), indent=2, sort_keys=True))
    return 0


def cmd_agent_city_assistant_snapshot(args: argparse.Namespace) -> int:
    snapshot = assistant_surface_snapshot_from_repo_root(
        args.root,
        city_id=args.city_id,
        assistant_id=args.assistant_id,
        heartbeat_source=args.heartbeat_source,
    )
    print(json.dumps(asdict(snapshot), indent=2, sort_keys=True))
    return 0


def cmd_agent_web_manifest(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    manifest = build_agent_web_manifest_from_repo_root(
        args.root,
        state_snapshot=snapshot_control_plane(plane),
        city_id=args.city_id,
        assistant_id=args.assistant_id,
        heartbeat_source=args.heartbeat_source,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_graph(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    graph = build_agent_web_public_graph_from_repo_root(
        args.root,
        state_snapshot=snapshot_control_plane(plane),
        city_id=args.city_id,
        assistant_id=args.assistant_id,
        heartbeat_source=args.heartbeat_source,
    )
    print(json.dumps(graph, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_semantic_capabilities(args: argparse.Namespace) -> int:
    payload = build_agent_web_semantic_capability_manifest(base_url=args.base_url)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_semantic_contracts(args: argparse.Namespace) -> int:
    payload = (
        read_agent_web_semantic_contract_descriptor(
            capability_id=args.capability_id,
            contract_id=args.contract_id,
            version=args.version,
            base_url=args.base_url,
        )
        if any(value not in (None, "") for value in (args.capability_id, args.contract_id, args.version))
        else build_agent_web_semantic_contract_manifest(base_url=args.base_url)
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_index(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    index = build_agent_web_search_index_from_repo_root(
        args.root,
        state_snapshot=snapshot_control_plane(plane),
        city_id=args.city_id,
        assistant_id=args.assistant_id,
        heartbeat_source=args.heartbeat_source,
    )
    print(json.dumps(index, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_search(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    index = build_agent_web_search_index_from_repo_root(
        args.root,
        state_snapshot=snapshot_control_plane(plane),
        city_id=args.city_id,
        assistant_id=args.assistant_id,
        heartbeat_source=args.heartbeat_source,
    )
    results = search_agent_web_index(index, query=args.query, limit=args.limit)
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_crawl(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    crawl = build_agent_web_crawl_bootstrap(
        list(args.roots),
        state_snapshot=snapshot_control_plane(plane),
        assistant_id=args.assistant_id,
        heartbeat_source=args.heartbeat_source,
    )
    print(json.dumps(crawl, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_crawl_search(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    crawl = build_agent_web_crawl_bootstrap(
        list(args.roots),
        state_snapshot=snapshot_control_plane(plane),
        assistant_id=args.assistant_id,
        heartbeat_source=args.heartbeat_source,
    )
    results = search_agent_web_crawl_bootstrap(crawl, query=args.query, limit=args.limit)
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_source_registry(args: argparse.Namespace) -> int:
    payload = load_agent_web_source_registry(args.registry_path)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_source_add(args: argparse.Namespace) -> int:
    payload = upsert_agent_web_source_registry_entry(
        args.registry_path,
        root=args.root,
        source_id=args.source_id,
        labels=list(args.labels),
        notes=args.notes,
        enabled=not bool(args.disabled),
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_source_remove(args: argparse.Namespace) -> int:
    payload = remove_agent_web_source_registry_entry(
        args.registry_path,
        root=args.root,
        source_id=args.source_id,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_crawl_registry(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    payload = build_agent_web_crawl_bootstrap_from_registry(
        args.registry_path,
        state_snapshot=snapshot_control_plane(plane),
        assistant_id=args.assistant_id,
        heartbeat_source=args.heartbeat_source,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_crawl_registry_search(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    payload = search_agent_web_crawl_bootstrap_from_registry(
        args.registry_path,
        state_snapshot=snapshot_control_plane(plane),
        assistant_id=args.assistant_id,
        heartbeat_source=args.heartbeat_source,
        query=args.query,
        limit=args.limit,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_federated_index_refresh(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    payload = refresh_agent_web_federated_index(
        args.index_path,
        registry_path=args.registry_path,
        state_snapshot=snapshot_control_plane(plane),
        semantic_overlay=load_agent_web_semantic_overlay(args.overlay_path),
        wordnet_bridge=None if not args.wordnet_path else load_agent_web_wordnet_bridge(args.wordnet_path),
        assistant_id=args.assistant_id,
        heartbeat_source=args.heartbeat_source,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_federated_index(args: argparse.Namespace) -> int:
    payload = load_agent_web_federated_index(args.index_path)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_federated_search(args: argparse.Namespace) -> int:
    payload = search_agent_web_federated_index(
        load_agent_web_federated_index(args.index_path),
        query=args.query,
        limit=args.limit,
        semantic_overlay=load_agent_web_semantic_overlay(args.overlay_path),
        wordnet_bridge=load_agent_web_wordnet_bridge(args.wordnet_path),
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_semantic_overlay(args: argparse.Namespace) -> int:
    payload = load_agent_web_semantic_overlay(args.overlay_path)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_semantic_overlay_refresh(args: argparse.Namespace) -> int:
    payload = refresh_agent_web_semantic_overlay(args.overlay_path)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_semantic_bridge_add(args: argparse.Namespace) -> int:
    payload = upsert_agent_web_semantic_bridge(
        args.overlay_path,
        bridge_kind=args.bridge_kind,
        bridge_id=args.bridge_id,
        terms=list(args.terms),
        expansions=list(args.expansions),
        weight=args.weight,
        notes=args.notes,
        enabled=not bool(args.disabled),
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_semantic_bridge_remove(args: argparse.Namespace) -> int:
    payload = remove_agent_web_semantic_bridge(args.overlay_path, bridge_id=args.bridge_id)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_semantic_expand(args: argparse.Namespace) -> int:
    payload = expand_query_with_agent_web_semantic_overlay(
        load_agent_web_semantic_overlay(args.overlay_path),
        query=args.query,
        wordnet_bridge=load_agent_web_wordnet_bridge(args.wordnet_path),
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_semantic_neighbors(args: argparse.Namespace) -> int:
    payload = read_agent_web_semantic_neighbors(
        load_agent_web_federated_index(args.index_path),
        record_id=args.record_id,
        limit=args.limit,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_agent_web_read(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    payload = read_agent_web_document_from_repo_root(
        args.root,
        state_snapshot=snapshot_control_plane(plane),
        rel=None if (args.href or args.document_id) else args.rel,
        href=args.href,
        document_id=args.document_id,
        city_id=args.city_id,
        assistant_id=args.assistant_id,
        heartbeat_source=args.heartbeat_source,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _maybe_publish_assistant_surface(plane: AgentInternetControlPlane, root: Path | str, city_id: str) -> dict | None:
    snapshot = assistant_surface_snapshot_from_repo_root(root, city_id=city_id)
    if not _assistant_surface_has_signal(snapshot):
        return None
    space, slot = plane.publish_assistant_surface(snapshot)
    return {
        "space_id": space.space_id,
        "slot_id": slot.slot_id,
        "status": slot.status,
        "campaign_count": len(snapshot.active_campaigns),
        "campaign_focus": snapshot.active_campaigns[0].get("title", "") if snapshot.active_campaigns else "",
    }


def _assistant_surface_has_signal(snapshot) -> bool:
    return bool(
        snapshot.state_present
        or "moltbook" in snapshot.capabilities
        or "moltbook_assistant" in snapshot.capabilities
        or snapshot.active_campaigns
        or snapshot.total_follows
        or snapshot.total_invites
        or snapshot.total_posts
        or snapshot.following
        or snapshot.invited
        or snapshot.spotlighted
    )


def cmd_lotus_show_steward_protocol(_args: argparse.Namespace) -> int:
    print(json.dumps(summarize_steward_protocol_bindings(), indent=2, sort_keys=True))
    return 0


def cmd_lotus_assign_addresses(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    link_address, network_address = store.update(
        lambda plane: plane.assign_lotus_addresses(args.city_id, ttl_s=args.ttl_s),
    )
    print(
        json.dumps(
            {
                "city_id": args.city_id,
                "link_address": asdict(link_address),
                "network_address": asdict(network_address),
                "state_path": str(store.path),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lotus_publish_endpoint(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    endpoint = store.update(
        lambda plane: plane.publish_hosted_endpoint(
            owner_city_id=args.city_id,
            public_handle=args.public_handle,
            transport=args.transport,
            location=args.location,
            visibility=EndpointVisibility(args.visibility),
            ttl_s=args.ttl_s,
            endpoint_id=args.endpoint_id,
        ),
    )
    print(
        json.dumps(
            {
                "hosted_endpoint": asdict(endpoint),
                "state_path": str(store.path),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lotus_resolve_handle(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    endpoint = plane.resolve_public_handle(args.public_handle)
    print(
        json.dumps(
            {
                "public_handle": args.public_handle,
                "resolved": None if endpoint is None else asdict(endpoint),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lotus_publish_service(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    service = store.update(
        lambda plane: plane.publish_service_address(
            owner_city_id=args.city_id,
            service_name=args.service_name,
            public_handle=args.public_handle,
            transport=args.transport,
            location=args.location,
            visibility=EndpointVisibility(args.visibility),
            ttl_s=args.ttl_s,
            service_id=args.service_id,
            auth_required=not args.no_auth,
            required_scopes=tuple(args.required_scope),
        ),
    )
    print(json.dumps({"service_address": asdict(service), "state_path": str(store.path)}, indent=2))
    return 0


def cmd_lotus_resolve_service(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    service = plane.resolve_service_address(args.city_id, args.service_name)
    print(
        json.dumps(
            {
                "city_id": args.city_id,
                "service_name": args.service_name,
                "resolved": None if service is None else asdict(service),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lotus_publish_route(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    route = store.update(
        lambda plane: plane.publish_route(
            owner_city_id=args.owner_city_id,
            destination_prefix=args.destination_prefix,
            target_city_id=args.target_city_id,
            next_hop_city_id=args.next_hop_city_id,
            route_id=args.route_id,
            metric=args.metric,
            nadi_type=args.nadi_type,
            priority=args.priority,
            ttl_ms=args.ttl_ms,
            ttl_s=args.ttl_s,
        ),
    )
    print(json.dumps({"route": asdict(route), "state_path": str(store.path)}, indent=2))
    return 0


def cmd_lotus_resolve_next_hop(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    plane = store.load()
    resolution = plane.resolve_next_hop(args.source_city_id, args.destination)
    print(
        json.dumps(
            {
                "source_city_id": args.source_city_id,
                "destination": args.destination,
                "resolved": None if resolution is None else asdict(resolution),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lotus_issue_token(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    issued = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject=args.subject,
            scopes=tuple(args.scope or [LotusApiScope.READ.value]),
            token_id=args.token_id,
        ),
    )
    print(
        json.dumps(
            {
                "token": asdict(issued.token),
                "secret": issued.secret,
                "state_path": str(store.path),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lotus_api_call(args: argparse.Namespace) -> int:
    store = ControlPlaneStateStore(path=Path(args.state_path))
    params = json.loads(args.params_json)
    if args.action in LOTUS_MUTATING_ACTIONS:
        result = store.update(
            lambda plane: LotusControlPlaneAPI(plane).call(
                bearer_token=args.token,
                action=args.action,
                params=params,
            ),
        )
    else:
        plane = store.load()
        result = LotusControlPlaneAPI(plane).call(
            bearer_token=args.token,
            action=args.action,
            params=params,
        )
    print(json.dumps(result, indent=2))
    return 0


def cmd_lotus_api_daemon(args: argparse.Namespace) -> int:
    daemon = LotusApiDaemon(
        state_path=Path(args.state_path),
        host=args.host,
        port=args.port,
    )
    daemon.start()
    host, port = daemon.address
    print(
        json.dumps(
            {
                "status": "listening",
                "host": host,
                "port": port,
                "state_path": str(Path(args.state_path)),
            },
            indent=2,
        ),
        flush=True,
    )
    try:
        daemon.serve_forever()
    except KeyboardInterrupt:
        daemon.shutdown()
    return 0


def cmd_init_dual_city_lab(args: argparse.Namespace) -> int:
    lab = LocalDualCityLab.create(
        args.root,
        city_a_id=args.city_a_id,
        city_b_id=args.city_b_id,
    )
    print(
        json.dumps(
            {
                "root": str(lab.root),
                "cities": [
                    {
                        "city_id": city_id,
                        "root": str(lab.city_root(city_id)),
                        "lotus_addresses": lab.lotus_addresses(city_id),
                    }
                    for city_id in lab.city_ids
                ],
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_send(args: argparse.Namespace) -> int:
    lab = LocalDualCityLab.create(args.root, city_a_id=args.source_city_id, city_b_id=args.target_city_id)
    receipt = lab.send(
        args.source_city_id,
        args.target_city_id,
        operation=args.operation,
        payload=json.loads(args.payload_json),
        correlation_id=args.correlation_id,
        nadi_type=args.nadi_type,
        nadi_op=args.nadi_op,
        priority=args.nadi_priority,
        ttl_ms=args.ttl_ms,
        ttl_s=args.ttl_s,
    )
    inbox = lab.read_inbox(args.target_city_id)
    print(
        json.dumps(
            {
                "receipt": {
                    "status": receipt.status,
                    "transport": receipt.transport,
                    "target_city_id": receipt.target_city_id,
                    "detail": receipt.detail,
                },
                "target_inbox": [
                    {
                        "source_city_id": env.source_city_id,
                        "target_city_id": env.target_city_id,
                        "operation": env.operation,
                        "payload": env.payload,
                        "correlation_id": env.correlation_id,
                        "nadi_type": env.nadi_type,
                        "nadi_op": env.nadi_op,
                        "nadi_priority": env.priority,
                        "ttl_ms": env.ttl_ms,
                        "maha_header_hex": env.maha_header_hex,
                    }
                    for env in inbox
                ],
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_emit_outbox(args: argparse.Namespace) -> int:
    lab = LocalDualCityLab.create(args.root, city_a_id=args.source_city_id, city_b_id=args.target_city_id)
    count = lab.emit_outbox_message(
        args.source_city_id,
        args.target_city_id,
        operation=args.operation,
        payload=json.loads(args.payload_json),
        correlation_id=args.correlation_id,
        nadi_type=args.nadi_type,
        nadi_op=args.nadi_op,
        priority=args.nadi_priority,
        ttl_ms=args.ttl_ms,
        ttl_s=args.ttl_s,
    )
    print(
        json.dumps(
            {
                "appended": count,
                "source_outbox": lab.read_outbox(args.source_city_id),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_pump_outbox(args: argparse.Namespace) -> int:
    other_city = "city-b" if args.source_city_id == "city-a" else "city-a"
    lab = LocalDualCityLab.create(args.root, city_a_id=args.source_city_id, city_b_id=other_city)
    receipts = lab.pump_outbox(args.source_city_id, drain_delivered=args.drain_delivered)
    print(
        json.dumps(
            {
                "receipts": [
                    {
                        "status": receipt.status,
                        "transport": receipt.transport,
                        "target_city_id": receipt.target_city_id,
                        "detail": receipt.detail,
                    }
                    for receipt in receipts
                ],
                "remaining_outbox": lab.read_outbox(args.source_city_id),
                "target_receipts": lab.read_receipts(other_city),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_sync(args: argparse.Namespace) -> int:
    lab = LocalDualCityLab.create(args.root, city_a_id=args.city_a_id, city_b_id=args.city_b_id)
    cycles = lab.sync_cycles(args.cycles, drain_delivered=args.drain_delivered)
    print(
        json.dumps(
            {
                "cycles": [
                    {
                        "cycle": cycle.cycle,
                        "receipts_by_city": {
                            city_id: [
                                {
                                    "status": receipt.status,
                                    "transport": receipt.transport,
                                    "target_city_id": receipt.target_city_id,
                                    "detail": receipt.detail,
                                }
                                for receipt in receipts
                            ]
                            for city_id, receipts in cycle.receipts_by_city.items()
                        },
                        "total_receipts": cycle.total_receipts,
                    }
                    for cycle in cycles
                ],
                "outboxes": {city_id: lab.read_outbox(city_id) for city_id in lab.city_ids},
                "receipts": {city_id: lab.read_receipts(city_id) for city_id in lab.city_ids},
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_compact_receipts(args: argparse.Namespace) -> int:
    other_city = "city-b" if args.city_id == "city-a" else "city-a"
    lab = LocalDualCityLab.create(args.root, city_a_id=args.city_id, city_b_id=other_city)
    removed = lab.compact_receipts(
        args.city_id,
        max_entries=args.max_entries,
        older_than_s=args.older_than_s,
    )
    print(
        json.dumps(
            {
                "removed": removed,
                "remaining_receipts": lab.read_receipts(args.city_id),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_issue_directive(args: argparse.Namespace) -> int:
    other_city = "city-b" if args.city_id == "city-a" else "city-a"
    lab = LocalDualCityLab.create(args.root, city_a_id=args.city_id, city_b_id=other_city)
    directive_id = lab.issue_directive(
        args.city_id,
        directive_type=args.directive_type,
        params=json.loads(args.params_json),
        directive_id=args.directive_id,
        source=args.source,
    )
    print(
        json.dumps(
            {
                "directive_id": directive_id,
                "pending_directives": lab.read_directives(args.city_id),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_run_directives(args: argparse.Namespace) -> int:
    other_city = "city-b" if args.city_id == "city-a" else "city-a"
    lab = LocalDualCityLab.create(args.root, city_a_id=args.city_id, city_b_id=other_city)
    result = lab.execute_directives(args.city_id)
    print(
        json.dumps(
            {
                "operations": result.operations,
                "acknowledged": result.acknowledged,
                "pending_directives": result.pending_directives,
                "agent": None if not args.agent_name else lab.read_agent(args.city_id, args.agent_name),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_phase_tick(args: argparse.Namespace) -> int:
    other_city = "city-b" if args.city_id == "city-a" else "city-a"
    lab = LocalDualCityLab.create(args.root, city_a_id=args.city_id, city_b_id=other_city)
    ingress_items = None
    if args.ingress_source or args.ingress_text:
        ingress_items = [
            {
                "source": args.ingress_source or "local",
                "text": args.ingress_text,
                "conversation_id": args.conversation_id,
                "from_agent": args.from_agent,
            },
        ]
    result = lab.run_phase_ticks(
        args.city_id,
        cycles=args.cycles,
        governance=not args.no_governance,
        federation=not args.no_federation,
        ingress_items=ingress_items,
    )
    print(
        json.dumps(
            {
                "heartbeats": result.heartbeats,
                "registry_services": result.registry_services,
                "council_state": result.council_state,
                "mission_results": result.mission_results,
                "pending_directives": result.pending_directives,
                "queued_ingress_before": result.queued_ingress_before,
                "queued_ingress_after": result.queued_ingress_after,
                "agent": None if not args.agent_name else lab.read_agent(args.city_id, args.agent_name),
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_execute_code(args: argparse.Namespace) -> int:
    other_city = "city-b" if args.city_id == "city-a" else "city-a"
    lab = LocalDualCityLab.create(args.root, city_a_id=args.city_id, city_b_id=other_city)
    result = lab.run_execute_code_mission(
        args.city_id,
        contract=args.contract,
        directive_id=args.directive_id,
        source=args.source,
        cycles=args.cycles,
        governance=not args.no_governance,
        federation=not args.no_federation,
    )
    print(
        json.dumps(
            {
                "directive_id": result.directive_id,
                "contract": result.contract,
                "exec_operations": result.exec_operations,
                "target_missions": result.target_missions,
                "mission_results": result.phase_tick.mission_results,
                "pending_directives": result.phase_tick.pending_directives,
                "heartbeats": result.phase_tick.heartbeats,
            },
            indent=2,
        ),
    )
    return 0


def cmd_lab_immigrate(args: argparse.Namespace) -> int:
    lab = LocalDualCityLab.create(args.root, city_a_id=args.source_city_id, city_b_id=args.host_city_id)
    result = lab.run_immigration_flow(
        source_city_id=args.source_city_id,
        host_city_id=args.host_city_id,
        agent_name=args.agent_name,
        visa_class=args.visa_class,
        reason=args.reason,
        sponsor=args.sponsor,
    )
    application = result["application"]
    visa = result["visa"]
    receipt = result["receipt"]
    print(
        json.dumps(
            {
                "receipt": {
                    "status": receipt.status,
                    "transport": receipt.transport,
                    "target_city_id": receipt.target_city_id,
                },
                "application": {
                    "application_id": application.application_id,
                    "agent_name": application.agent_name,
                    "status": application.status.value,
                    "requested_visa_class": application.requested_visa_class.value,
                },
                "visa": {
                    "agent_name": visa.agent_name,
                    "visa_class": visa.visa_class.value,
                    "sponsor": visa.sponsor,
                    "lineage_depth": visa.lineage_depth,
                },
                "stats": result["stats"],
            },
            indent=2,
        ),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "publish-agent-city-peer":
        return cmd_publish_agent_city_peer(args)
    if args.command == "git-federation-describe":
        return cmd_git_federation_describe(args)
    if args.command == "git-federation-sync-wiki":
        return cmd_git_federation_sync_wiki(args)
    if args.command == "git-federation-onboard-repo":
        return cmd_git_federation_onboard_repo(args)
    if args.command == "onboard-agent-city":
        return cmd_onboard_agent_city(args)
    if args.command == "show-state":
        return cmd_show_state(args)
    if args.command == "agent-city-assistant-snapshot":
        return cmd_agent_city_assistant_snapshot(args)
    if args.command == "agent-web-manifest":
        return cmd_agent_web_manifest(args)
    if args.command == "agent-web-graph":
        return cmd_agent_web_graph(args)
    if args.command == "agent-web-semantic-capabilities":
        return cmd_agent_web_semantic_capabilities(args)
    if args.command == "agent-web-semantic-contracts":
        return cmd_agent_web_semantic_contracts(args)
    if args.command == "agent-web-index":
        return cmd_agent_web_index(args)
    if args.command == "agent-web-search":
        return cmd_agent_web_search(args)
    if args.command == "agent-web-crawl":
        return cmd_agent_web_crawl(args)
    if args.command == "agent-web-crawl-search":
        return cmd_agent_web_crawl_search(args)
    if args.command == "agent-web-source-registry":
        return cmd_agent_web_source_registry(args)
    if args.command == "agent-web-source-add":
        return cmd_agent_web_source_add(args)
    if args.command == "agent-web-source-remove":
        return cmd_agent_web_source_remove(args)
    if args.command == "agent-web-crawl-registry":
        return cmd_agent_web_crawl_registry(args)
    if args.command == "agent-web-crawl-registry-search":
        return cmd_agent_web_crawl_registry_search(args)
    if args.command == "agent-web-federated-index-refresh":
        return cmd_agent_web_federated_index_refresh(args)
    if args.command == "agent-web-federated-index":
        return cmd_agent_web_federated_index(args)
    if args.command == "agent-web-federated-search":
        return cmd_agent_web_federated_search(args)
    if args.command == "agent-web-semantic-overlay":
        return cmd_agent_web_semantic_overlay(args)
    if args.command == "agent-web-semantic-overlay-refresh":
        return cmd_agent_web_semantic_overlay_refresh(args)
    if args.command == "agent-web-semantic-bridge-add":
        return cmd_agent_web_semantic_bridge_add(args)
    if args.command == "agent-web-semantic-bridge-remove":
        return cmd_agent_web_semantic_bridge_remove(args)
    if args.command == "agent-web-semantic-expand":
        return cmd_agent_web_semantic_expand(args)
    if args.command == "agent-web-semantic-neighbors":
        return cmd_agent_web_semantic_neighbors(args)
    if args.command == "agent-web-read":
        return cmd_agent_web_read(args)
    if args.command == "lotus-show-steward-protocol":
        return cmd_lotus_show_steward_protocol(args)
    if args.command == "lotus-assign-addresses":
        return cmd_lotus_assign_addresses(args)
    if args.command == "lotus-publish-endpoint":
        return cmd_lotus_publish_endpoint(args)
    if args.command == "lotus-resolve-handle":
        return cmd_lotus_resolve_handle(args)
    if args.command == "lotus-publish-service":
        return cmd_lotus_publish_service(args)
    if args.command == "lotus-resolve-service":
        return cmd_lotus_resolve_service(args)
    if args.command == "lotus-publish-route":
        return cmd_lotus_publish_route(args)
    if args.command == "lotus-resolve-next-hop":
        return cmd_lotus_resolve_next_hop(args)
    if args.command == "lotus-issue-token":
        return cmd_lotus_issue_token(args)
    if args.command == "lotus-api-call":
        return cmd_lotus_api_call(args)
    if args.command == "lotus-api-daemon":
        return cmd_lotus_api_daemon(args)
    if args.command == "init-dual-city-lab":
        return cmd_init_dual_city_lab(args)
    if args.command == "lab-send":
        return cmd_lab_send(args)
    if args.command == "lab-emit-outbox":
        return cmd_lab_emit_outbox(args)
    if args.command == "lab-pump-outbox":
        return cmd_lab_pump_outbox(args)
    if args.command == "lab-sync":
        return cmd_lab_sync(args)
    if args.command == "lab-compact-receipts":
        return cmd_lab_compact_receipts(args)
    if args.command == "lab-issue-directive":
        return cmd_lab_issue_directive(args)
    if args.command == "lab-run-directives":
        return cmd_lab_run_directives(args)
    if args.command == "lab-phase-tick":
        return cmd_lab_phase_tick(args)
    if args.command == "lab-execute-code":
        return cmd_lab_execute_code(args)
    if args.command == "lab-immigrate":
        return cmd_lab_immigrate(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
