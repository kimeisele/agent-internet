from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .agent_city_contract import AgentCityFilesystemContract
from .file_locking import read_locked_json_value, update_locked_json_value, write_locked_json_value


def _coerce_dict(value: object) -> dict:
    if isinstance(value, dict):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        if isinstance(data, dict):
            return dict(data)
    raise TypeError(f"Expected dict-like value, got {type(value)!r}")


def _coerce_json_list(raw: object, path: Path) -> list[dict]:
    if isinstance(raw, list):
        return [dict(item) for item in raw]
    if isinstance(raw, dict):
        return [dict(raw)]
    raise TypeError(f"Expected list or dict in {path}")


@dataclass(slots=True)
class FilesystemFederationTransport:
    """Phase 0 transport using the existing agent-city federation filesystem."""

    contract: AgentCityFilesystemContract

    def read_outbox(self) -> list[dict]:
        raw = read_locked_json_value(self.contract.nadi_outbox, default=[])
        return _coerce_json_list(raw, self.contract.nadi_outbox)

    def append_to_outbox(self, messages: list[object]) -> int:
        self.contract.ensure_dirs()
        additions = [_coerce_dict(message) for message in messages]
        update_locked_json_value(
            self.contract.nadi_outbox,
            default=[],
            updater=lambda raw: _coerce_json_list(raw, self.contract.nadi_outbox) + additions,
        )
        return len(messages)

    def replace_outbox(self, messages: list[object]) -> None:
        self.contract.ensure_dirs()
        write_locked_json_value(self.contract.nadi_outbox, [_coerce_dict(message) for message in messages])

    def read_inbox(self) -> list[dict]:
        raw = read_locked_json_value(self.contract.nadi_inbox, default=[])
        return _coerce_json_list(raw, self.contract.nadi_inbox)

    def append_to_inbox(self, messages: list[object]) -> int:
        self.contract.ensure_dirs()
        additions = [_coerce_dict(message) for message in messages]
        update_locked_json_value(
            self.contract.nadi_inbox,
            default=[],
            updater=lambda raw: _coerce_json_list(raw, self.contract.nadi_inbox) + additions,
        )
        return len(messages)

    def write_directive(self, directive: object, *, directive_id: str) -> None:
        self.contract.ensure_dirs()
        write_locked_json_value(self.contract.directive_path(directive_id), _coerce_dict(directive))

    def list_directives(self) -> list[dict]:
        self.contract.ensure_dirs()
        directives: list[dict] = []
        for path in sorted(self.contract.directives_dir.glob("*.json")):
            if path.name.endswith(".done.json"):
                continue
            data = read_locked_json_value(path, default={})
            if isinstance(data, dict):
                directives.append(dict(data))
        return directives

    def list_reports(self) -> list[dict]:
        self.contract.ensure_dirs()
        reports: list[dict] = []
        for path in sorted(self.contract.reports_dir.glob("report_*.json")):
            data = read_locked_json_value(path, default={})
            if isinstance(data, dict):
                reports.append(dict(data))
        return reports
