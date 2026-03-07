from __future__ import annotations

from dataclasses import dataclass

from .local_lab import LocalDualCityLab
from .transport import DeliveryReceipt


@dataclass(frozen=True, slots=True)
class SyncCycleResult:
    cycle: int
    receipts_by_city: dict[str, list[DeliveryReceipt]]

    @property
    def total_receipts(self) -> int:
        return sum(len(receipts) for receipts in self.receipts_by_city.values())


@dataclass(slots=True)
class BidirectionalSyncWorker:
    lab: LocalDualCityLab
    drain_delivered: bool = True

    def sync_once(self, *, cycle: int = 1) -> SyncCycleResult:
        receipts_by_city = {
            city_id: self.lab.pump_outbox(city_id, drain_delivered=self.drain_delivered)
            for city_id in self.lab.city_ids
        }
        return SyncCycleResult(cycle=cycle, receipts_by_city=receipts_by_city)

    def sync_cycles(self, cycles: int) -> list[SyncCycleResult]:
        if cycles < 1:
            return []
        return [self.sync_once(cycle=index) for index in range(1, cycles + 1)]