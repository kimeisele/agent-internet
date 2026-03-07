from __future__ import annotations

from dataclasses import field, dataclass
from enum import StrEnum


class HealthStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class TrustLevel(StrEnum):
    UNKNOWN = "unknown"
    OBSERVED = "observed"
    VERIFIED = "verified"
    TRUSTED = "trusted"


@dataclass(frozen=True, slots=True)
class CityIdentity:
    city_id: str
    slug: str
    repo: str
    public_key: str = ""
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CityEndpoint:
    city_id: str
    transport: str
    location: str


@dataclass(frozen=True, slots=True)
class CityPresence:
    city_id: str
    health: HealthStatus = HealthStatus.UNKNOWN
    last_seen_at: float | None = None
    heartbeat: int | None = None
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TrustRecord:
    issuer_city_id: str
    subject_city_id: str
    level: TrustLevel
    reason: str = ""
