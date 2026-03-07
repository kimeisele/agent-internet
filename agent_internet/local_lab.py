from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .agent_city_contract import AgentCityFilesystemContract
from .agent_city_peer import AgentCityPeer
from .control_plane import AgentInternetControlPlane
from .filesystem_message_transport import AgentCityFilesystemMessageTransport
from .models import HealthStatus, TrustLevel, TrustRecord
from .transport import DeliveryEnvelope, DeliveryReceipt, TransportScheme


def _report_payload(*, heartbeat: int, timestamp: float | None = None) -> dict:
    return {
        "heartbeat": heartbeat,
        "timestamp": float(timestamp if timestamp is not None else time.time()),
        "population": 1,
        "alive": 1,
        "dead": 0,
        "elected_mayor": None,
        "council_seats": 0,
        "open_proposals": 0,
        "chain_valid": True,
    }


@dataclass(slots=True)
class LocalDualCityLab:
    root: Path
    city_ids: tuple[str, str]
    plane: AgentInternetControlPlane
    message_transport: AgentCityFilesystemMessageTransport = field(
        default_factory=AgentCityFilesystemMessageTransport,
    )

    @classmethod
    def create(
        cls,
        root: Path | str,
        *,
        city_a_id: str = "city-a",
        city_b_id: str = "city-b",
    ) -> "LocalDualCityLab":
        lab_root = Path(root).resolve()
        lab_root.mkdir(parents=True, exist_ok=True)
        plane = AgentInternetControlPlane()
        lab = cls(root=lab_root, city_ids=(city_a_id, city_b_id), plane=plane)
        plane.register_transport(TransportScheme.FILESYSTEM.value, lab.message_transport)

        for city_id in lab.city_ids:
            city_root = lab.city_root(city_id)
            city_root.mkdir(parents=True, exist_ok=True)
            contract = AgentCityFilesystemContract(root=city_root)
            contract.ensure_dirs()
            lab.seed_report(city_id, heartbeat=1)
            peer = AgentCityPeer.from_repo_root(
                city_root,
                city_id=city_id,
                repo=f"local/{city_id}",
                slug=city_id,
                capabilities=("federation", "dual-city-lab"),
                endpoint_transport=TransportScheme.FILESYSTEM.value,
            )
            peer.onboard(plane)

        for source_city in lab.city_ids:
            for target_city in lab.city_ids:
                if source_city == target_city:
                    continue
                plane.record_trust(
                    TrustRecord(
                        issuer_city_id=source_city,
                        subject_city_id=target_city,
                        level=TrustLevel.OBSERVED,
                        reason="local dual-city lab",
                    ),
                )

        return lab

    def city_root(self, city_id: str) -> Path:
        return self.root / city_id

    def contract(self, city_id: str) -> AgentCityFilesystemContract:
        return AgentCityFilesystemContract(root=self.city_root(city_id))

    def seed_report(self, city_id: str, *, heartbeat: int, timestamp: float | None = None) -> Path:
        contract = self.contract(city_id)
        contract.ensure_dirs()
        path = contract.reports_dir / f"report_{heartbeat}.json"
        path.write_text(json.dumps(_report_payload(heartbeat=heartbeat, timestamp=timestamp), indent=2))
        self.plane.announce_city(
            self.plane.registry.get_presence(city_id)
            or self._healthy_presence(city_id, heartbeat=heartbeat, timestamp=timestamp)
        )
        return path

    def _healthy_presence(
        self,
        city_id: str,
        *,
        heartbeat: int,
        timestamp: float | None = None,
    ):
        from .models import CityPresence

        return CityPresence(
            city_id=city_id,
            health=HealthStatus.HEALTHY,
            heartbeat=heartbeat,
            last_seen_at=float(timestamp if timestamp is not None else time.time()),
            capabilities=("federation", "dual-city-lab"),
        )

    def send(
        self,
        source_city_id: str,
        target_city_id: str,
        *,
        operation: str,
        payload: dict,
        correlation_id: str = "",
        ttl_s: float = 300.0,
    ) -> DeliveryReceipt:
        return self.plane.relay_envelope(
            DeliveryEnvelope(
                source_city_id=source_city_id,
                target_city_id=target_city_id,
                operation=operation,
                payload=dict(payload),
                correlation_id=correlation_id,
                ttl_s=ttl_s,
            ),
        )

    def read_inbox(self, city_id: str):
        return self.message_transport.receive(self.city_root(city_id))
