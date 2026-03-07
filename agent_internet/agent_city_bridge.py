from __future__ import annotations

from dataclasses import dataclass, field

from .interfaces import FederationTransport
from .models import CityPresence, HealthStatus


def city_presence_from_report(
    city_id: str,
    report: dict,
    *,
    capabilities: tuple[str, ...] = (),
) -> CityPresence:
    alive = int(report.get("alive", 0))
    population = int(report.get("population", 0))
    dead = int(report.get("dead", 0))
    chain_valid = bool(report.get("chain_valid", False))

    if population > 0 and alive <= 0:
        health = HealthStatus.OFFLINE
    elif not chain_valid or dead > 0 or alive < population:
        health = HealthStatus.DEGRADED
    else:
        health = HealthStatus.HEALTHY

    return CityPresence(
        city_id=city_id,
        health=health,
        last_seen_at=float(report.get("timestamp", 0.0)) or None,
        heartbeat=int(report.get("heartbeat", 0)) or None,
        capabilities=capabilities,
    )


@dataclass(slots=True)
class AgentCityBridge:
    city_id: str
    transport: FederationTransport
    capabilities: tuple[str, ...] = field(default_factory=tuple)

    def latest_report(self) -> dict | None:
        reports = self.transport.list_reports()
        if not reports:
            return None
        return max(
            reports,
            key=lambda report: (int(report.get("heartbeat", 0)), float(report.get("timestamp", 0.0))),
        )

    def latest_presence(self) -> CityPresence | None:
        report = self.latest_report()
        if report is None:
            return None
        return city_presence_from_report(self.city_id, report, capabilities=self.capabilities)

    def write_directive(self, directive: object, *, directive_id: str) -> None:
        self.transport.write_directive(directive, directive_id=directive_id)
