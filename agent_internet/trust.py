from __future__ import annotations

from dataclasses import dataclass, field

from .models import TrustLevel, TrustRecord

_TRUST_RANK = {
    TrustLevel.UNKNOWN: 0,
    TrustLevel.OBSERVED: 1,
    TrustLevel.VERIFIED: 2,
    TrustLevel.TRUSTED: 3,
}


def trust_allows(level: TrustLevel, minimum: TrustLevel) -> bool:
    return _TRUST_RANK[level] >= _TRUST_RANK[minimum]


@dataclass(slots=True)
class InMemoryTrustEngine:
    """Explicit, overwriteable trust ledger between cities."""

    _records: dict[tuple[str, str], TrustRecord] = field(default_factory=dict)
    _default_level: TrustLevel = TrustLevel.UNKNOWN

    def record(self, trust: TrustRecord) -> None:
        self._records[(trust.issuer_city_id, trust.subject_city_id)] = trust

    def get_record(self, source_city_id: str, target_city_id: str) -> TrustRecord | None:
        return self._records.get((source_city_id, target_city_id))

    def evaluate(self, source_city_id: str, target_city_id: str) -> TrustLevel:
        if source_city_id == target_city_id:
            return TrustLevel.TRUSTED
        record = self.get_record(source_city_id, target_city_id)
        return record.level if record is not None else self._default_level
