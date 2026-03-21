"""agent-internet own heartbeat — announce control plane presence to federation."""

import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# nadi_kit is vendored at repo root
sys.path.insert(0, str(_REPO_ROOT))
from nadi_kit import NadiNode

log = logging.getLogger("agent_internet.own_heartbeat")


def create_internet_node(federation_dir: Path | None = None) -> NadiNode:
    """Create NadiNode for agent-internet's own identity."""
    if federation_dir is None:
        federation_dir = _REPO_ROOT / "data" / "federation"
    peer_json = federation_dir / "peer.json"
    return NadiNode.from_peer_json(peer_json)


def emit_control_plane_heartbeat(*, health: float = 1.0, version: str = "0.1.0") -> dict:
    """Emit agent-internet's own heartbeat + sync cycle.

    Returns sync stats dict.
    """
    node = create_internet_node()
    node.heartbeat(health=health, version=version)
    stats = node.sync()
    log.info(
        "control plane heartbeat: pushed=%d pulled=%d processed=%d",
        stats["pushed"], stats["pulled"], stats["processed"],
    )
    return stats
