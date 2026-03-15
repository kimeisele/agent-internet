"""Federation Relay Pump — read outboxes from all federation repos and route messages.

Bootstraps the control plane, registers steward and agent-city as federation
peers with Lotus addresses, pumps their Nadi outboxes through the relay, and
refreshes the federated index with steward's federation data.

Usage:
    python scripts/federation_relay_pump.py [--drain-delivered] [--refresh-index]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Ensure agent_internet is importable when running as a script.
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
    """Locate a sibling federation repo next to agent-internet."""
    candidate = _repo_root.parent / sibling_dir
    if candidate.is_dir():
        return candidate
    return None


def _register_peer(
    plane: AgentInternetControlPlane,
    peer: dict,
    *,
    root: Path | None,
) -> None:
    """Register a federation peer with identity, endpoint, trust and Lotus addresses."""
    city_id = peer["city_id"]
    transport_value = TransportScheme.FILESYSTEM.value if root else "https"
    location = str(root) if root else f"https://github.com/{peer['repo']}"

    identity = CityIdentity(
        city_id=city_id,
        slug=peer["slug"],
        repo=peer["repo"],
        labels=peer.get("labels", {}),
    )
    endpoint = CityEndpoint(
        city_id=city_id,
        transport=transport_value,
        location=location,
    )
    plane.register_city(identity, endpoint)

    # Establish baseline trust so the relay will route messages.
    plane.record_trust(TrustRecord(
        source_city_id="agent-internet",
        target_city_id=city_id,
        level=TrustLevel.VERIFIED,
        reason=f"federation-peer:{peer['repo']}",
    ))

    # Announce presence.
    plane.announce_city(CityPresence(
        city_id=city_id,
        health=HealthStatus.HEALTHY if root else HealthStatus.UNKNOWN,
        last_seen_at=time.time(),
        heartbeat=1,
        capabilities=peer.get("capabilities", ()),
    ))

    # Publish a Lotus service address for steward so messages can be routed to it.
    if city_id == "steward":
        plane.publish_service_address(
            owner_city_id=city_id,
            service_name="nadi-relay",
            public_handle=f"{city_id}.nadi-relay.lotus",
            transport=transport_value,
            location=location,
            labels={"protocol": "nadi", "layer": "substrate"},
        )
        plane.publish_hosted_endpoint(
            owner_city_id=city_id,
            public_handle=f"{city_id}.federation.lotus",
            transport=transport_value,
            location=location,
            labels={"protocol": "federation", "role": "steward"},
        )


def _pump_peer(
    pump: OutboxRelayPump,
    peer: dict,
    root: Path,
    *,
    drain_delivered: bool,
) -> list[dict]:
    """Pump a single peer's outbox and return receipt summaries."""
    receipts = pump.pump_city_root(root, drain_delivered=drain_delivered)
    return [
        {
            "source": receipt.target_city_id,
            "status": receipt.status.value,
            "transport": receipt.transport,
            "detail": receipt.detail,
        }
        for receipt in receipts
    ]


def _refresh_federated_index(plane: AgentInternetControlPlane, discovered_roots: dict[str, Path]) -> dict:
    """Refresh the semantic federated index with steward's federation data."""
    from agent_internet.agent_web_federated_index import (
        DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH,
        refresh_agent_web_federated_index_for_plane,
    )
    from agent_internet.agent_web_source_registry import (
        DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH,
        upsert_agent_web_source_registry_entry,
    )

    # Register discovered peer roots in the source registry so they get indexed.
    for city_id, root in discovered_roots.items():
        peer_descriptor = root / "data" / "federation" / "peer.json"
        if peer_descriptor.exists():
            peer_info = FEDERATION_PEERS[0]  # default
            for p in FEDERATION_PEERS:
                if p["city_id"] == city_id:
                    peer_info = p
                    break
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
    parser.add_argument("--drain-delivered", action="store_true", help="Remove delivered messages from outboxes")
    parser.add_argument("--refresh-index", action="store_true", help="Refresh the federated index after pumping")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    # Bootstrap control plane.
    plane = AgentInternetControlPlane()
    message_transport = AgentCityFilesystemMessageTransport()
    plane.register_transport(TransportScheme.FILESYSTEM.value, message_transport)

    # Register agent-internet itself.
    _register_peer(plane, {
        "city_id": "agent-internet",
        "slug": "agent-internet",
        "repo": "kimeisele/agent-internet",
        "sibling_dir": "agent-internet",
        "labels": {"role": "control-plane", "layer": "internet"},
    }, root=_repo_root)

    # Discover and register all federation peers.
    discovered_roots: dict[str, Path] = {}
    for peer in FEDERATION_PEERS:
        root = _discover_peer_root(peer["sibling_dir"])
        _register_peer(plane, peer, root=root)
        if root:
            discovered_roots[peer["city_id"]] = root

    # Pump outboxes for all discovered peers.
    pump = OutboxRelayPump(plane)
    all_receipts: dict[str, list[dict]] = {}
    total_pumped = 0
    total_delivered = 0

    for peer in FEDERATION_PEERS:
        city_id = peer["city_id"]
        root = discovered_roots.get(city_id)
        if root is None:
            all_receipts[city_id] = [{"status": "skipped", "detail": f"repo not found at {_repo_root.parent / peer['sibling_dir']}"}]
            continue
        receipts = _pump_peer(pump, peer, root, drain_delivered=args.drain_delivered)
        all_receipts[city_id] = receipts
        total_pumped += len(receipts)
        total_delivered += sum(1 for r in receipts if r["status"] in ("DELIVERED", "DUPLICATE"))

    # Refresh federated index if requested.
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
        print(f"Federation Relay Pump completed at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
        print(f"  Peers registered: {', '.join(p['city_id'] for p in FEDERATION_PEERS)}")
        print(f"  Peers discovered: {', '.join(discovered_roots.keys()) or '(none)'}")
        print(f"  Messages pumped:  {total_pumped}")
        print(f"  Messages delivered: {total_delivered}")
        for city_id, receipts in all_receipts.items():
            if receipts:
                statuses = [r["status"] for r in receipts]
                print(f"  [{city_id}] {len(receipts)} message(s): {', '.join(statuses)}")
        if index_result and "error" not in index_result:
            print(f"  Federated index refreshed: {index_result.get('stats', {}).get('record_count', 0)} records")

    return 0


if __name__ == "__main__":
    sys.exit(main())
