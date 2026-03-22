"""Navigator — Head Agent for agent-internet (Transport Layer).

Perceives: relay receipts, peer freshness, transport errors
Judges: peer health degradation, new peer onboarding, routing quality
Acts: trust updates via NADI, anomaly alerts to steward
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("agent_internet.navigator")

# Import HeadAgent pattern inline (no cross-repo dependency)
# Same pattern as agent-template/head_agent.py but self-contained

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Thresholds
PEER_STALE_HOURS = 2.0  # Peer hasn't sent in 2h = stale
PEER_DEAD_HOURS = 12.0  # Peer hasn't sent in 12h = dead
TRANSPORT_ERROR_THRESHOLD = 0.2  # >20% errors = degraded


class Navigator:
    """Head Agent for agent-internet. Oversees federation transport."""

    agent_type = "navigator"

    def __init__(self, federation_dir: Path | None = None) -> None:
        self.federation_dir = federation_dir or (_REPO_ROOT / "data" / "federation")
        self.cycle_count = 0
        self._nadi_node = None

    def _get_nadi_node(self):
        if self._nadi_node is None:
            import sys
            sys.path.insert(0, str(_REPO_ROOT))
            from nadi_kit import NadiNode
            self._nadi_node = NadiNode.from_peer_json(self.federation_dir / "peer.json")
        return self._nadi_node

    def heartbeat(self) -> dict[str, Any]:
        """Full Navigator cycle."""
        self.cycle_count += 1
        observations = self.perceive()
        decisions = self.judge(observations)
        actions = self.act(decisions)
        self.emit_status(observations, actions)

        log.info(
            "Navigator #%d: %d peers observed, %d decisions, %d actions",
            self.cycle_count, len(observations.get("peers", {})),
            len(decisions), len(actions),
        )
        return {"cycle": self.cycle_count, "observations": observations,
                "decisions": decisions, "actions": actions}

    def perceive(self) -> dict[str, Any]:
        """Read federation state: peer freshness, receipts, transport health."""
        now = time.time()
        observations: dict[str, Any] = {"peers": {}, "timestamp": now}

        # Read inbox for peer liveness
        inbox_path = self.federation_dir / "nadi_inbox.json"
        if inbox_path.exists():
            try:
                msgs = json.loads(inbox_path.read_text())
                # Group by source, find latest timestamp
                by_source: dict[str, float] = {}
                for m in msgs:
                    src = m.get("source", "")
                    ts = m.get("timestamp", 0)
                    if src and ts > by_source.get(src, 0):
                        by_source[src] = ts
                for src, last_ts in by_source.items():
                    age_h = (now - last_ts) / 3600
                    observations["peers"][src] = {
                        "last_seen_h": round(age_h, 1),
                        "status": "alive" if age_h < PEER_STALE_HOURS
                                  else "stale" if age_h < PEER_DEAD_HOURS
                                  else "dead",
                    }
            except Exception as exc:
                log.warning("perceive inbox failed: %s", exc)

        # Read receipts for delivery health
        receipts_path = self.federation_dir / "receipts.json"
        if receipts_path.exists():
            try:
                receipts = json.loads(receipts_path.read_text())
                if isinstance(receipts, list):
                    total = len(receipts)
                    delivered = sum(1 for r in receipts if r.get("status") == "DELIVERED")
                    observations["delivery_rate"] = delivered / total if total else 1.0
                elif isinstance(receipts, dict):
                    observations["delivery_rate"] = 1.0  # dict format = summary
            except Exception:
                observations["delivery_rate"] = 1.0

        return observations

    def judge(self, observations: dict[str, Any]) -> list[dict[str, Any]]:
        """Deterministic rules. Zero LLM."""
        decisions = []
        for peer_id, peer in observations.get("peers", {}).items():
            if peer["status"] == "dead":
                decisions.append({
                    "type": "flag_dead_peer",
                    "peer": peer_id,
                    "last_seen_h": peer["last_seen_h"],
                    "action": "alert_steward",
                })
            elif peer["status"] == "stale":
                decisions.append({
                    "type": "flag_stale_peer",
                    "peer": peer_id,
                    "last_seen_h": peer["last_seen_h"],
                    "action": "monitor",
                })

        delivery_rate = observations.get("delivery_rate", 1.0)
        if delivery_rate < (1.0 - TRANSPORT_ERROR_THRESHOLD):
            decisions.append({
                "type": "transport_degraded",
                "delivery_rate": delivery_rate,
                "action": "alert_steward",
            })

        return decisions

    def act(self, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute decisions via NADI."""
        node = self._get_nadi_node()
        actions = []
        for d in decisions:
            if d.get("action") == "alert_steward":
                node.emit(
                    "transport_alert",
                    {
                        "type": d["type"],
                        "detail": {k: v for k, v in d.items() if k not in ("action",)},
                        "source": "navigator",
                    },
                    target="steward",
                    priority=2,
                )
                actions.append({"emitted": "transport_alert", "target": "steward", "detail": d["type"]})
                log.info("Navigator ACT: %s → steward", d["type"])
        return actions

    def emit_status(self, observations: dict, actions: list) -> None:
        """Emit heartbeat with head_agent identification."""
        node = self._get_nadi_node()
        node.heartbeat(health=1.0)
        node.emit(
            "head_agent_status",
            {
                "head_agent": self.agent_type,
                "cycle": self.cycle_count,
                "peers_observed": len(observations.get("peers", {})),
                "actions_taken": len(actions),
                "delivery_rate": observations.get("delivery_rate", 1.0),
                "timestamp": time.time(),
            },
            priority=1,
        )


def run_navigator() -> dict:
    """Entry point for CI workflow."""
    nav = Navigator()
    return nav.heartbeat()
