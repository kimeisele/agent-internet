from __future__ import annotations

import time
from dataclasses import dataclass

from .agent_city_contract import AgentCityFilesystemContract
from .file_locking import read_locked_json_value, update_locked_json_value


@dataclass(slots=True)
class FilesystemReceiptStore:
    contract: AgentCityFilesystemContract

    def list_receipts(self) -> list[dict]:
        self.contract.ensure_dirs()
        raw = read_locked_json_value(self.contract.receipts_path, default=[])
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def has_envelope(self, envelope_id: str) -> bool:
        return any(entry.get("envelope_id") == envelope_id for entry in self.list_receipts())

    def record_delivery(
        self,
        *,
        envelope_id: str,
        source_city_id: str,
        target_city_id: str,
        operation: str,
        correlation_id: str = "",
    ) -> None:
        self.contract.ensure_dirs()
        update_locked_json_value(
            self.contract.receipts_path,
            default=[],
            updater=lambda raw: _update_receipt_entries(
                raw,
                envelope_id=envelope_id,
                source_city_id=source_city_id,
                target_city_id=target_city_id,
                operation=operation,
                correlation_id=correlation_id,
            ),
        )


def _update_receipt_entries(
    raw: object,
    *,
    envelope_id: str,
    source_city_id: str,
    target_city_id: str,
    operation: str,
    correlation_id: str,
) -> list[dict]:
    entries = [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    if any(entry.get("envelope_id") == envelope_id for entry in entries):
        return entries
    entries.append(
        {
            "envelope_id": envelope_id,
            "source_city_id": source_city_id,
            "target_city_id": target_city_id,
            "operation": operation,
            "correlation_id": correlation_id,
            "delivered_at": time.time(),
        },
    )
    return entries