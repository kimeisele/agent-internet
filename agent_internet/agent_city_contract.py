from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AgentCityFilesystemContract:
    """Current filesystem federation contract exposed by agent-city.

    This intentionally follows the existing paths used by `city.federation`
    and `city.federation_nadi` so the first version of agent-internet can sit
    beside the current file-based transport instead of replacing it blindly.
    """

    root: Path

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def federation_dir(self) -> Path:
        return self.data_dir / "federation"

    @property
    def assistant_state_path(self) -> Path:
        return self.data_dir / "assistant_state.json"

    @property
    def nadi_outbox(self) -> Path:
        return self.federation_dir / "nadi_outbox.json"

    @property
    def nadi_inbox(self) -> Path:
        return self.federation_dir / "nadi_inbox.json"

    @property
    def reports_dir(self) -> Path:
        return self.federation_dir / "reports"

    @property
    def directives_dir(self) -> Path:
        return self.federation_dir / "directives"

    @property
    def receipts_path(self) -> Path:
        return self.federation_dir / "receipts.json"

    @property
    def peer_descriptor_path(self) -> Path:
        return self.federation_dir / "peer.json"

    @property
    def git_federation_manifest_path(self) -> Path:
        return self.federation_dir / "git_federation.json"

    def directive_path(self, directive_id: str) -> Path:
        return self.directives_dir / f"{directive_id}.json"

    def ensure_dirs(self) -> None:
        self.federation_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.directives_dir.mkdir(parents=True, exist_ok=True)
