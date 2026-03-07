from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .agent_city_directive_bridge import AgentCityDirectiveExecutionAdapter
from .agent_city_directives import AgentCityDirectiveFactory
from .agent_city_phase_tick_bridge import AgentCityPhaseTickAdapter, PhaseTickResult


@dataclass(frozen=True, slots=True)
class MissionExecutionResult:
    directive_id: str
    contract: str
    phase_tick: PhaseTickResult
    target_missions: list[dict]

    @property
    def exec_operations(self) -> list[str]:
        operations: list[str] = []
        for heartbeat in self.phase_tick.heartbeats:
            operations.extend(
                operation
                for operation in heartbeat.get("operations", [])
                if isinstance(operation, str) and operation.startswith("exec_mission:")
            )
        return operations


@dataclass(slots=True)
class AgentCityMissionExecutionAdapter:
    root: Path | str
    directive_factory: AgentCityDirectiveFactory = field(default_factory=AgentCityDirectiveFactory)

    @property
    def repo_root(self) -> Path:
        return Path(self.root).resolve()

    def issue_execute_code(
        self,
        contract: str,
        *,
        directive_id: str | None = None,
        source: str = "agent-internet",
    ) -> str:
        directive = self.directive_factory.execute_code(contract, directive_id=directive_id, source=source)
        return AgentCityDirectiveExecutionAdapter(self.repo_root).issue(directive)

    def run_execute_code(
        self,
        contract: str,
        *,
        directive_id: str | None = None,
        source: str = "agent-internet",
        cycles: int = 3,
        governance: bool = True,
        federation: bool = True,
    ) -> MissionExecutionResult:
        issued_id = self.issue_execute_code(contract, directive_id=directive_id, source=source)
        phase_tick = AgentCityPhaseTickAdapter(self.repo_root).run(
            cycles=cycles,
            governance=governance,
            federation=federation,
        )
        target_missions = [
            mission for mission in phase_tick.mission_results if str(mission.get("id", "")).startswith(f"exec_{issued_id}_")
        ]
        return MissionExecutionResult(
            directive_id=issued_id,
            contract=contract,
            phase_tick=phase_tick,
            target_missions=target_missions,
        )