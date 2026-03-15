"""Federation Relay Pump — read outboxes from all federation repos and route messages.

Bootstraps the control plane, registers all federation peers (steward gets
full Lotus addressing via register_federation_steward), pumps Nadi outboxes,
and optionally refreshes the federated index.

Usage:
    python scripts/federation_relay_pump.py [--drain-delivered] [--refresh-index]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[1]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.filesystem_message_transport import AgentCityFilesystemMessageTransport
from agent_internet.models import CityEndpoint, CityIdentity, CityPresence, HealthStatus, TrustLevel, TrustRecord
from agent_internet.pump import OutboxRelayPump
from agent_internet.transport import TransportScheme

# ---------------------------------------------------------------------------
# Federation peer definitions
# ---------------------------------------------------------------------------

FEDERATION_PEERS: list[dict] = [
    {
        "city_id": "steward",
        "slug": "steward",
        "repo": "kimeisele/steward-protocol",
        "sibling_dir": "steward-protocol",
        "capabilities": ("federation", "heartbeat", "immune-stats", "peer-status", "nadi-protocol"),
        "labels": {"role": "protocol-steward", "layer": "substrate"},
    },
    {
        "city_id": "agent-city",
        "slug": "agent-city",
        "repo": "kimeisele/agent-city",
        "sibling_dir": "agent-city",
        "capabilities": ("federation", "governance", "city-runtime"),
        "labels": {"role": "city-runtime", "layer": "runtime"},
    },
    {
        "city_id": "agent-world",
        "slug": "agent-world",
        "repo": "kimeisele/agent-world",
        "sibling_dir": "agent-world",
        "capabilities": ("federation", "world-registry", "agent-registry"),
        "labels": {"role": "world-governance", "layer": "governance"},
    },
]


def _discover_peer_root(sibling_dir: str) -> Path | None:
    candidate = _repo_root.parent / sibling_dir
    return candidate if candidate.is_dir() else None


def _register_peer(
    plane: AgentInternetControlPlane,
    peer: dict,
    *,
    root: Path | None,
) -> None:
    """Register a non-steward federation peer."""
    city_id = peer["city_id"]
    transport_value = TransportScheme.FILESYSTEM.value if root else "https"
    location = str(root) if root else f"https://github.com/{peer['repo']}"

    plane.register_city(
        CityIdentity(
            city_id=city_id,
            slug=peer["slug"],
            repo=peer["repo"],
            labels=peer.get("labels", {}),
        ),
        CityEndpoint(city_id=city_id, transport=transport_value, location=location),
    )
    plane.record_trust(TrustRecord(
        source_city_id="agent-internet",
        target_city_id=city_id,
        level=TrustLevel.VERIFIED,
        reason=f"federation-peer:{peer['repo']}",
    ))
    plane.announce_city(CityPresence(
        city_id=city_id,
        health=HealthStatus.HEALTHY if root else HealthStatus.UNKNOWN,
        last_seen_at=time.time(),
        heartbeat=1,
        capabilities=peer.get("capabilities", ()),
    ))


def _register_all_peers(
    plane: AgentInternetControlPlane,
    discovered_roots: dict[str, Path],
) -> None:
    """Register all federation peers, using the dedicated steward method."""
    for peer in FEDERATION_PEERS:
        city_id = peer["city_id"]
        root = discovered_roots.get(city_id)
        transport_value = TransportScheme.FILESYSTEM.value if root else "https"
        location = str(root) if root else f"https://github.com/{peer['repo']}"

        if city_id == "steward":
            plane.register_federation_steward(
                transport=transport_value,
                location=location,
            )
        else:
            _register_peer(plane, peer, root=root)

    # Establish bidirectional trust and routes between all peers so the relay
    # can deliver messages from any peer to any other peer.
    all_city_ids = [p["city_id"] for p in FEDERATION_PEERS] + ["agent-internet"]
    for source in all_city_ids:
        for target in all_city_ids:
            if source == target:
                continue
            plane.record_trust(TrustRecord(
                source_city_id=source,
                target_city_id=target,
                level=TrustLevel.VERIFIED,
                reason="federation-mesh-peer",
            ))
            plane.publish_route(
                owner_city_id="agent-internet",
                destination_prefix=target,
                target_city_id=target,
                next_hop_city_id=target,
                metric=100,
                labels={"origin": "federation-relay-pump"},
            )


def _pump_peer(
    pump: OutboxRelayPump,
    root: Path,
    *,
    drain_delivered: bool,
) -> list[dict]:
    receipts = pump.pump_city_root(root, drain_delivered=drain_delivered)
    return [
        {
            "envelope_id": receipt.target_city_id,
            "status": receipt.status.value,
            "transport": receipt.transport,
            "detail": receipt.detail,
        }
        for receipt in receipts
    ]


def _refresh_federated_index(plane: AgentInternetControlPlane, discovered_roots: dict[str, Path]) -> dict:
    from agent_internet.agent_web_federated_index import (
        DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH,
        refresh_agent_web_federated_index_for_plane,
    )
    from agent_internet.agent_web_source_registry import upsert_agent_web_source_registry_entry

    for city_id, root in discovered_roots.items():
        peer_descriptor = root / "data" / "federation" / "peer.json"
        if not peer_descriptor.exists():
            continue
        peer_info = next((p for p in FEDERATION_PEERS if p["city_id"] == city_id), FEDERATION_PEERS[0])
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
    args = parser.parse_args()

    plane = AgentInternetControlPlane()
    plane.register_transport(
        TransportScheme.FILESYSTEM.value,
        AgentCityFilesystemMessageTransport(),
    )

    # Register agent-internet itself.
    _register_peer(plane, {
        "city_id": "agent-internet",
        "slug": "agent-internet",
        "repo": "kimeisele/agent-internet",
        "labels": {"role": "control-plane", "layer": "internet"},
    }, root=_repo_root)

    # Discover sibling repos.
    discovered_roots: dict[str, Path] = {}
    for peer in FEDERATION_PEERS:
        root = _discover_peer_root(peer["sibling_dir"])
        if root:
            discovered_roots[peer["city_id"]] = root

    # Register all peers (steward via dedicated method, others generically).
    _register_all_peers(plane, discovered_roots)

    # Pump outboxes.
    pump = OutboxRelayPump(plane)
    all_receipts: dict[str, list[dict]] = {}
    total_pumped = 0
    total_delivered = 0

    for peer in FEDERATION_PEERS:
        city_id = peer["city_id"]
        root = discovered_roots.get(city_id)
        if root is None:
            all_receipts[city_id] = [{"status": "skipped", "detail": f"not found at {_repo_root.parent / peer['sibling_dir']}"}]
            continue
        receipts = _pump_peer(pump, root, drain_delivered=args.drain_delivered)
        all_receipts[city_id] = receipts
        total_pumped += len(receipts)
        total_delivered += sum(1 for r in receipts if r["status"] in ("DELIVERED", "DUPLICATE"))

    # Refresh federated index.
    index_result = None
    if args.refresh_index and discovered_roots:
        try:
            index_result = _refresh_federated_index(plane, discovered_roots)
        except Exception as exc:
            index_result = {"error": f"{type(exc).__name__}: {exc}"}

    result = {
        "kind": "federation_relay_pump_result",
        "version": 1,
        "timestamp": time.time(),
        "peers_registered": [p["city_id"] for p in FEDERATION_PEERS],
        "peers_discovered": list(discovered_roots.keys()),
        "receipts": all_receipts,
        "stats": {
            "total_pumped": total_pumped,
            "total_delivered": total_delivered,
            "peers_with_outbox": len(discovered_roots),
            "peers_skipped": len(FEDERATION_PEERS) - len(discovered_roots),
        },
    }
    if index_result is not None:
        result["federated_index"] = {
            "refreshed": "error" not in index_result,
            "record_count": index_result.get("stats", {}).get("record_count", 0) if isinstance(index_result, dict) else 0,
            "source_count": index_result.get("stats", {}).get("source_count", 0) if isinstance(index_result, dict) else 0,
            "error": index_result.get("error") if isinstance(index_result, dict) and "error" in index_result else None,
        }

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Federation Relay Pump @ {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
        print(f"  registered: {', '.join(p['city_id'] for p in FEDERATION_PEERS)}")
        print(f"  discovered: {', '.join(discovered_roots.keys()) or '(none)'}")
        print(f"  pumped: {total_pumped}  delivered: {total_delivered}")
        for city_id, receipts in all_receipts.items():
            if receipts:
                print(f"  [{city_id}] {len(receipts)} msg: {', '.join(r['status'] for r in receipts)}")
        if index_result and "error" not in index_result:
            print(f"  index: {index_result.get('stats', {}).get('record_count', 0)} records")

    return 0


if __name__ == "__main__":
    sys.exit(main())
