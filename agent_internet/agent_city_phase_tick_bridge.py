from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from .agent_city_contract import AgentCityFilesystemContract
from .agent_city_directive_bridge import _ensure_local_agent_city_repo_on_path
from .filesystem_transport import FilesystemFederationTransport


@dataclass(frozen=True, slots=True)
class AgentCityPhaseTickBindings:
    build_city_runtime: object
    persist_city_runtime: object
    SVC_COUNCIL: str


def load_agent_city_phase_tick_bindings() -> AgentCityPhaseTickBindings:
    _ensure_local_agent_city_repo_on_path()

    from city.registry import SVC_COUNCIL
    from city.runtime import build_city_runtime, persist_city_runtime

    return AgentCityPhaseTickBindings(
        build_city_runtime=build_city_runtime,
        persist_city_runtime=persist_city_runtime,
        SVC_COUNCIL=SVC_COUNCIL,
    )


@dataclass(frozen=True, slots=True)
class PhaseTickResult:
    heartbeats: list[dict]
    pending_directives: list[dict]
    registry_services: list[str]
    council_state: dict | None
    queued_ingress_before: int
    queued_ingress_after: int


@dataclass(slots=True)
class AgentCityPhaseTickAdapter:
    root: Path | str
    bindings: AgentCityPhaseTickBindings = field(default_factory=load_agent_city_phase_tick_bindings)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("agent_internet.phase_tick"))

    @property
    def repo_root(self) -> Path:
        return Path(self.root).resolve()

    @property
    def contract(self) -> AgentCityFilesystemContract:
        return AgentCityFilesystemContract(root=self.repo_root)

    def run(
        self,
        *,
        cycles: int = 1,
        governance: bool = True,
        federation: bool = True,
        ingress_items: list[dict] | None = None,
    ) -> PhaseTickResult:
        with _working_directory(self.repo_root):
            runtime = self.bindings.build_city_runtime(
                args=SimpleNamespace(
                    db=str(self.repo_root / "data" / "city.db"),
                    offline=True,
                    governance=governance,
                    federation=federation,
                    federation_dry_run=False,
                ),
                config={},
                log=self.logger,
            )
            for item in ingress_items or []:
                runtime.mayor.enqueue(
                    str(item.get("source", "local")),
                    str(item.get("text", "")),
                    conversation_id=str(item.get("conversation_id", "")),
                    from_agent=str(item.get("from_agent", "")),
                )
            queue_before = len(getattr(runtime.mayor, "_gateway_queue", []))
            heartbeats = runtime.mayor.run_cycle(cycles)
            queue_after = len(getattr(runtime.mayor, "_gateway_queue", []))
            self.bindings.persist_city_runtime(runtime, self.logger)
            council = runtime.registry.get(self.bindings.SVC_COUNCIL)
            council_state = council.to_dict() if council is not None and hasattr(council, "to_dict") else None
            return PhaseTickResult(
                heartbeats=[dict(result) for result in heartbeats],
                pending_directives=FilesystemFederationTransport(self.contract).list_directives(),
                registry_services=sorted(runtime.registry.names()),
                council_state=council_state,
                queued_ingress_before=queue_before,
                queued_ingress_after=queue_after,
            )


@contextmanager
def _working_directory(path: Path):
    previous = Path.cwd()
    path.mkdir(parents=True, exist_ok=True)
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)