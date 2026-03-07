from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .agent_city_contract import AgentCityFilesystemContract


def _coerce_dict(value: object) -> dict:
    if isinstance(value, dict):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        if isinstance(data, dict):
            return dict(data)
    raise TypeError(f"Expected dict-like value, got {type(value)!r}")


def _read_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    if isinstance(raw, list):
        return [dict(item) for item in raw]
    if isinstance(raw, dict):
        return [dict(raw)]
    raise TypeError(f"Expected list or dict in {path}")


def _atomic_write_json(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(path)


@dataclass(slots=True)
class FilesystemFederationTransport:
    """Phase 0 transport using the existing agent-city federation filesystem."""

    contract: AgentCityFilesystemContract

    def read_outbox(self) -> list[dict]:
        return _read_json_list(self.contract.nadi_outbox)

    def append_to_inbox(self, messages: list[object]) -> int:
        self.contract.ensure_dirs()
        existing = _read_json_list(self.contract.nadi_inbox)
        merged = existing + [_coerce_dict(message) for message in messages]
        _atomic_write_json(self.contract.nadi_inbox, merged)
        return len(messages)

    def write_directive(self, directive: object, *, directive_id: str) -> None:
        self.contract.ensure_dirs()
        _atomic_write_json(self.contract.directive_path(directive_id), _coerce_dict(directive))

    def list_directives(self) -> list[dict]:
        self.contract.ensure_dirs()
        directives: list[dict] = []
        for path in sorted(self.contract.directives_dir.glob("*.json")):
            if path.name.endswith(".done.json"):
                continue
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                directives.append(dict(data))
        return directives

    def list_reports(self) -> list[dict]:
        self.contract.ensure_dirs()
        reports: list[dict] = []
        for path in sorted(self.contract.reports_dir.glob("report_*.json")):
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                reports.append(dict(data))
        return reports
