"""Federation Relay Pump — discover peers dynamically, pump Nadi outboxes.

No hardcoded peer lists. Discovery uses three layers:
1. GitHub Topic search (global — finds any repo tagged agent-federation-node)
2. Filesystem beacons (local — sibling repos that announced themselves)
3. Descriptor fetch + validation (verifies each discovered node is real)

Usage:
    python scripts/federation_relay_pump.py [--drain-delivered] [--refresh-index]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[1]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.discovery_bootstrap import DiscoveryBootstrapService, FilesystemBeaconScanner
from agent_internet.federation_descriptor import load_federation_descriptor
from agent_internet.filesystem_message_transport import AgentCityFilesystemMessageTransport
from agent_internet.github_topic_discovery import discover_federation_descriptors_by_github_topic
from agent_internet.models import TrustLevel, TrustRecord
from agent_internet.pump import OutboxRelayPump
from agent_internet.transport import TransportScheme

logger = logging.getLogger(__name__)

# Cache file so we don't hit GitHub API every single cycle
_PEER_CACHE_PATH = _repo_root / "data" / "federation" / "discovered_peers.json"
_CACHE_TTL_S = 900  # 15 minutes — matches the relay pump cycle


def _discover_peers_via_github_topic() -> list[dict]:
    """Global discovery: find all repos tagged agent-federation-node on GitHub."""
    try:
        results = discover_federation_descriptors_by_github_topic(limit=100)
    except Exception as exc:
        logger.warning("GitHub topic discovery failed: %s", exc)
        return []

    peers = []
    for result in results:
        repo = result.repository_full_name
        repo_id = repo.split("/", 1)[1] if "/" in repo else repo
        # Skip ourselves
        if repo_id == "agent-internet":
            continue
        peers.append({
            "city_id": repo_id,
            "slug": repo_id,
            "repo": repo,
            "descriptor_url": result.descriptor_url,
            "description": result.description,
        })
    return peers


def _fetch_descriptor_metadata(peer: dict) -> dict:
    """Fetch .well-known/agent-federation.json to get capabilities, role, status."""
    try:
        descriptor, _source = load_federation_descriptor(peer["descriptor_url"])
        peer["status"] = descriptor.status.value
        peer["display_name"] = descriptor.display_name
        peer["owner_boundary"] = descriptor.owner_boundary
    except Exception as exc:
        logger.warning("Failed to fetch descriptor for %s: %s", peer["city_id"], exc)
        peer["status"] = "unknown"
    return peer


def _discover_local_sibling(city_id: str) -> Path | None:
    """Check if a peer repo exists as a sibling directory."""
    candidate = _repo_root.parent / city_id
    return candidate if candidate.is_dir() else None


def _load_cached_peers() -> list[dict] | None:
    """Load cached peer list if fresh enough."""
    if not _PEER_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(_PEER_CACHE_PATH.read_text())
        cached_at = data.get("cached_at", 0)
        if time.time() - cached_at > _CACHE_TTL_S:
            return None
        return data.get("peers", [])
    except Exception:
        return None


def _save_peer_cache(peers: list[dict]) -> None:
    """Cache discovered peers to avoid hitting GitHub API every cycle."""
    _PEER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PEER_CACHE_PATH.write_text(json.dumps({
        "cached_at": time.time(),
        "peers": peers,
    }, indent=2, default=str))


def _discover_all_peers() -> list[dict]:
    """Full discovery: cache → GitHub Topics → descriptor validation → local siblings."""
    # Try cache first
    cached = _load_cached_peers()
    if cached is not None:
        logger.info("Using cached peer list (%d peers)", len(cached))
        return cached

    # Global discovery via GitHub Topics
    peers = _discover_peers_via_github_topic()
    logger.info("GitHub topic discovery found %d peers", len(peers))

    # Also scan local beacons for peers that might not have the topic yet
    beacon_scanner = FilesystemBeaconScanner(
        beacon_dir=_repo_root / ".agent-internet" / "beacons"
    )
    for ann in beacon_scanner.scan():
        if ann.city_id == "agent-internet":
            continue
        if not any(p["city_id"] == ann.city_id for p in peers):
            peers.append({
                "city_id": ann.city_id,
                "slug": ann.slug or ann.city_id,
                "repo": ann.repo,
                "descriptor_url": "",
                "description": "",
                "capabilities": list(ann.capabilities),
                "labels": dict(ann.labels),
            })
            logger.info("Beacon discovery added: %s", ann.city_id)

    # Fetch descriptors to validate and enrich
    validated = []
    for peer in peers:
        if peer.get("descriptor_url"):
            peer = _fetch_descriptor_metadata(peer)
        # Only include active nodes
        if peer.get("status", "active") in ("active", "unknown"):
            validated.append(peer)

    # Cache for next cycle
    _save_peer_cache(validated)

    return validated


def _register_discovered_peers(
    plane: AgentInternetControlPlane,
    peers: list[dict],
) -> dict[str, Path]:
    """Register all discovered peers and return their local roots."""
    discovered_roots: dict[str, Path] = {}

    for peer in peers:
        city_id = peer["city_id"]
        local_root = _discover_local_sibling(city_id)
        if local_root:
            discovered_roots[city_id] = local_root

        transport_value = TransportScheme.FILESYSTEM.value if local_root else "https"
        location = str(local_root) if local_root else f"https://github.com/{peer['repo']}"

        plane.register_federation_peer(
            city_id=city_id,
            slug=peer.get("slug", city_id),
            repo=peer.get("repo", ""),
            transport=transport_value,
            location=location,
            capabilities=tuple(peer.get("capabilities", ())),
            labels=peer.get("labels", {}),
            publish_nadi_service=True,
        )

    # Bidirectional trust + routes
    all_city_ids = [p["city_id"] for p in peers] + ["agent-internet"]
    for source in all_city_ids:
        for target in all_city_ids:
            if source == target:
                continue
            plane.record_trust(
                TrustRecord(
                    issuer_city_id=source,
                    subject_city_id=target,
                    level=TrustLevel.VERIFIED,
                    reason="federation-mesh",
                )
            )
            plane.publish_route(
                owner_city_id="agent-internet",
                destination_prefix=target,
                target_city_id=target,
                next_hop_city_id=target,
                metric=100,
                labels={"origin": "relay-pump"},
            )

    return discovered_roots


def _pump_peer(
    pump: OutboxRelayPump,
    root: Path,
    *,
    city_id: str,
    drain_delivered: bool,
    all_peer_ids: list[str] | None = None,
) -> list[dict]:
    """Pump a peer's outbox. Resolves broadcast (*) to unicast before relay."""
    from agent_internet.agent_city_contract import AgentCityFilesystemContract
    from agent_internet.filesystem_transport import FilesystemFederationTransport

    transport = FilesystemFederationTransport(AgentCityFilesystemContract(root=Path(root)))
    raw_messages = transport.read_outbox()

    # Resolve broadcast: replace target=* with individual unicast messages
    expanded: list[dict] = []
    for msg in raw_messages:
        if msg.get("target") == "*" and all_peer_ids:
            source = msg.get("source", "")
            for peer_id in all_peer_ids:
                if peer_id != source and peer_id != city_id:
                    unicast = dict(msg)
                    unicast["target"] = peer_id
                    expanded.append(unicast)
        else:
            expanded.append(msg)

    # Write expanded messages back and pump
    if expanded != raw_messages:
        transport.replace_outbox(expanded)

    # Use city_id as source — message "source" field may contain internal
    # identifiers (e.g. MURALI phase names) instead of the federation identity.
    receipts = pump.pump_city_root(root, drain_delivered=drain_delivered, source_city_id=city_id)
    return [
        {
            "envelope_id": receipt.target_city_id,
            "status": receipt.status.value,
            "transport": receipt.transport,
            "detail": receipt.detail,
        }
        for receipt in receipts
    ]


def _refresh_federated_index(
    plane: AgentInternetControlPlane,
    discovered_roots: dict[str, Path],
    peers: list[dict],
) -> dict:
    from agent_internet.agent_web_federated_index import (
        DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH,
        refresh_agent_web_federated_index_for_plane,
    )
    from agent_internet.agent_web_source_registry import upsert_agent_web_source_registry_entry

    for city_id, root in discovered_roots.items():
        peer_descriptor = root / "data" / "federation" / "peer.json"
        if not peer_descriptor.exists():
            continue
        peer_info = next((p for p in peers if p["city_id"] == city_id), {})
        upsert_agent_web_source_registry_entry(
            root=root,
            source_id=city_id,
            labels=[
                "federation-peer",
                peer_info.get("labels", {}).get("role", ""),
                peer_info.get("labels", {}).get("layer", ""),
            ],
            notes=f"Auto-registered by federation relay pump for {city_id}",
            enabled=True,
        )

    index_path = Path(DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    return refresh_agent_web_federated_index_for_plane(
        index_path,
        plane=plane,
        heartbeat_source="steward-protocol/mahamantra",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Federation Relay Pump")
    parser.add_argument("--drain-delivered", action="store_true")
    parser.add_argument("--refresh-index", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--force-discover", action="store_true",
                        help="Ignore cache, force fresh GitHub API discovery")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    plane = AgentInternetControlPlane()
    plane.register_transport(
        TransportScheme.FILESYSTEM.value,
        AgentCityFilesystemMessageTransport(),
    )

    # GitHub API transport for remote peers (no local clone needed)
    from agent_internet.github_api_transport import GitHubApiTransport
    github_transport = GitHubApiTransport()
    if github_transport.available:
        plane.register_transport(TransportScheme.HTTPS.value, github_transport)
        logger.info("GitHub API transport registered (remote delivery enabled)")
    else:
        logger.warning("No GitHub token — remote peers will be skipped")

    # Register agent-internet itself.
    plane.register_federation_peer(
        city_id="agent-internet",
        slug="agent-internet",
        repo="kimeisele/agent-internet",
        transport=TransportScheme.FILESYSTEM.value,
        location=str(_repo_root),
        labels={"role": "control-plane", "layer": "internet"},
    )

    # Dynamic peer discovery — no hardcoded list
    if args.force_discover and _PEER_CACHE_PATH.exists():
        _PEER_CACHE_PATH.unlink()

    peers = _discover_all_peers()

    # Register and discover local roots
    discovered_roots = _register_discovered_peers(plane, peers)

    # Pump outboxes.
    pump = OutboxRelayPump(plane)
    all_receipts: dict[str, list[dict]] = {}
    total_pumped = 0
    total_delivered = 0

    all_peer_ids = [p["city_id"] for p in peers] + ["agent-internet"]

    for peer in peers:
        city_id = peer["city_id"]
        root = discovered_roots.get(city_id)
        if root is None:
            all_receipts[city_id] = [
                {"status": "skipped", "detail": "no local sibling found"}
            ]
            continue
        receipts = _pump_peer(
            pump, root, city_id=city_id, drain_delivered=args.drain_delivered, all_peer_ids=all_peer_ids
        )
        all_receipts[city_id] = receipts
        total_pumped += len(receipts)
        total_delivered += sum(1 for r in receipts if r["status"] in ("DELIVERED", "DUPLICATE"))

    # Refresh federated index.
    index_result = None
    if args.refresh_index and discovered_roots:
        try:
            index_result = _refresh_federated_index(plane, discovered_roots, peers)
        except Exception as exc:
            index_result = {"error": f"{type(exc).__name__}: {exc}"}

    peer_ids = [p["city_id"] for p in peers]
    result = {
        "kind": "federation_relay_pump_result",
        "version": 2,
        "timestamp": time.time(),
        "discovery": "dynamic",
        "peers_registered": peer_ids,
        "peers_discovered_locally": list(discovered_roots.keys()),
        "receipts": all_receipts,
        "stats": {
            "total_peers": len(peers),
            "total_pumped": total_pumped,
            "total_delivered": total_delivered,
            "peers_with_outbox": len(discovered_roots),
            "peers_remote_only": len(peers) - len(discovered_roots),
        },
    }
    if index_result is not None:
        result["federated_index"] = {
            "refreshed": "error" not in index_result,
            "record_count": index_result.get("stats", {}).get("record_count", 0)
            if isinstance(index_result, dict)
            else 0,
            "source_count": index_result.get("stats", {}).get("source_count", 0)
            if isinstance(index_result, dict)
            else 0,
            "error": index_result.get("error")
            if isinstance(index_result, dict) and "error" in index_result
            else None,
        }

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Federation Relay Pump v2 @ {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
        print(f"  discovery: dynamic (topic + beacons)")
        print(f"  peers: {', '.join(peer_ids) or '(none)'}")
        print(f"  local: {', '.join(discovered_roots.keys()) or '(none)'}")
        print(f"  pumped: {total_pumped}  delivered: {total_delivered}")
        for city_id, receipts in all_receipts.items():
            if receipts:
                print(
                    f"  [{city_id}] {len(receipts)} msg: {', '.join(r['status'] for r in receipts)}"
                )
        if index_result and "error" not in index_result:
            print(f"  index: {index_result.get('stats', {}).get('record_count', 0)} records")

    # Emit agent-internet's own heartbeat
    try:
        from agent_internet.own_heartbeat import emit_control_plane_heartbeat
        hb_stats = emit_control_plane_heartbeat(health=1.0)
        print(f"  control plane heartbeat: {hb_stats}")
    except Exception as exc:
        print(f"  control plane heartbeat failed (non-fatal): {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
