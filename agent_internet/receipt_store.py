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

    def compact(
        self,
        *,
        max_entries: int | None = None,
        older_than_s: float | None = None,
        now: float | None = None,
    ) -> int:
        self.contract.ensure_dirs()
        before = self.list_receipts()
        update_locked_json_value(
            self.contract.receipts_path,
            default=[],
            updater=lambda raw: _compact_receipt_entries(
                raw,
                max_entries=max_entries,
                older_than_s=older_than_s,
                now=now,
            ),
        )
        after = self.list_receipts()
        return len(before) - len(after)


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


def _compact_receipt_entries(
    raw: object,
    *,
    max_entries: int | None,
    older_than_s: float | None,
    now: float | None,
) -> list[dict]:
    entries = [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    if older_than_s is not None:
        current_time = time.time() if now is None else now
        cutoff = current_time - older_than_s
        entries = [entry for entry in entries if float(entry.get("delivered_at", 0.0)) >= cutoff]
    if max_entries is not None:
        limit = max(max_entries, 0)
        if limit == 0:
            return []
        entries = sorted(entries, key=lambda entry: float(entry.get("delivered_at", 0.0)))[-limit:]
    return entries