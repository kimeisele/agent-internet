from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .control_plane import AgentInternetControlPlane
from .models import CityEndpoint, CityIdentity, CityPresence, HealthStatus, TrustLevel, TrustRecord


def snapshot_control_plane(plane: AgentInternetControlPlane) -> dict:
    return {
        "minimum_trust": plane.minimum_trust.value,
        "identities": [asdict(identity) for identity in plane.registry.list_identities()],
        "endpoints": [asdict(endpoint) for endpoint in plane.registry.list_endpoints()],
        "presence": [asdict(presence) for presence in plane.registry.list_cities()],
        "trust": [asdict(record) for record in plane.trust_engine.list_records()],
    }


def restore_control_plane(payload: dict) -> AgentInternetControlPlane:
    plane = AgentInternetControlPlane(minimum_trust=TrustLevel(payload.get("minimum_trust", "observed")))

    for data in payload.get("identities", []):
        plane.registry.upsert_identity(CityIdentity(**data))
    for data in payload.get("endpoints", []):
        plane.registry.upsert_endpoint(CityEndpoint(**data))
    for data in payload.get("presence", []):
        plane.registry.announce(
            CityPresence(
                city_id=data["city_id"],
                health=HealthStatus(data.get("health", "unknown")),
                last_seen_at=data.get("last_seen_at"),
                heartbeat=data.get("heartbeat"),
                capabilities=tuple(data.get("capabilities", ())),
            ),
        )
    for data in payload.get("trust", []):
        plane.trust_engine.record(
            TrustRecord(
                issuer_city_id=data["issuer_city_id"],
                subject_city_id=data["subject_city_id"],
                level=TrustLevel(data.get("level", "unknown")),
                reason=data.get("reason", ""),
            ),
        )

    return plane


def _atomic_write_json(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(path)


@dataclass(slots=True)
class ControlPlaneStateStore:
    path: Path

    def load(self) -> AgentInternetControlPlane:
        if not self.path.exists():
            return AgentInternetControlPlane()
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict payload in {self.path}")
        return restore_control_plane(data)

    def save(self, plane: AgentInternetControlPlane) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.path, snapshot_control_plane(plane))
