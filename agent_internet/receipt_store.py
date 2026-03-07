from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .agent_city_contract import AgentCityFilesystemContract


def _read_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _atomic_write_json(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(path)


@dataclass(slots=True)
class FilesystemReceiptStore:
    contract: AgentCityFilesystemContract

    def list_receipts(self) -> list[dict]:
        self.contract.ensure_dirs()
        return _read_json_list(self.contract.receipts_path)

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
        entries = self.list_receipts()
        if any(entry.get("envelope_id") == envelope_id for entry in entries):
            return
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
        _atomic_write_json(self.contract.receipts_path, entries)