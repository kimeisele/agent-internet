from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from .agent_city_contract import AgentCityFilesystemContract
from .agent_city_directives import validate_agent_city_directive
from .filesystem_transport import FilesystemFederationTransport


def _ensure_local_agent_city_repo_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    agent_city_root = repo_root.parent / "agent-city"
    if agent_city_root.exists() and str(agent_city_root) not in sys.path:
        sys.path.insert(0, str(agent_city_root))


@dataclass(frozen=True, slots=True)
class AgentCityDirectiveExecutionBindings:
    CityGateway: type
    CityNetwork: type
    CityServiceRegistry: type
    FederationDirectivesHook: type
    FederationRelay: type
    PhaseContext: type
    Pokedex: type
    SVC_FEDERATION: str


def load_agent_city_directive_execution_bindings() -> AgentCityDirectiveExecutionBindings:
    _ensure_local_agent_city_repo_on_path()

    from city.federation import FederationRelay
    from city.gateway import CityGateway
    from city.hooks.genesis.federation import FederationDirectivesHook
    from city.network import CityNetwork
    from city.phases import PhaseContext
    from city.pokedex import Pokedex
    from city.registry import CityServiceRegistry, SVC_FEDERATION

    return AgentCityDirectiveExecutionBindings(
        CityGateway=CityGateway,
        CityNetwork=CityNetwork,
        CityServiceRegistry=CityServiceRegistry,
        FederationDirectivesHook=FederationDirectivesHook,
        FederationRelay=FederationRelay,
        PhaseContext=PhaseContext,
        Pokedex=Pokedex,
        SVC_FEDERATION=SVC_FEDERATION,
    )


@dataclass(frozen=True, slots=True)
class DirectiveExecutionResult:
    operations: list[str]
    acknowledged: list[str]
    pending_directives: list[dict]

    @property
    def processed_count(self) -> int:
        return len(self.acknowledged)


@dataclass(slots=True)
class AgentCityDirectiveExecutionAdapter:
    root: Path | str
    bindings: AgentCityDirectiveExecutionBindings = field(default_factory=load_agent_city_directive_execution_bindings)
    _pokedex: object | None = field(default=None, init=False, repr=False)

    @property
    def repo_root(self) -> Path:
        return Path(self.root).resolve()

    @property
    def contract(self) -> AgentCityFilesystemContract:
        return AgentCityFilesystemContract(root=self.repo_root)

    def issue(self, directive: object) -> str:
        validate_agent_city_directive(directive)
        directive_id = str(getattr(directive, "id", "") or "")
        if not directive_id and isinstance(directive, dict):
            directive_id = str(directive.get("id", "") or "")
        if not directive_id:
            raise ValueError("Directive id must be a non-empty string")
        FilesystemFederationTransport(self.contract).write_directive(directive, directive_id=directive_id)
        return directive_id

    def list_pending(self) -> list[dict]:
        return FilesystemFederationTransport(self.contract).list_directives()

    def execute_pending(self) -> DirectiveExecutionResult:
        relay = self.bindings.FederationRelay(
            _directives_dir=self.contract.directives_dir,
            _reports_dir=self.contract.reports_dir,
        )
        registry = self.bindings.CityServiceRegistry()
        registry.register(self.bindings.SVC_FEDERATION, relay)
        state_path = self.repo_root / "data" / "phase_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        ctx = self.bindings.PhaseContext(
            pokedex=self.pokedex(),
            gateway=self.bindings.CityGateway(),
            network=self.bindings.CityNetwork(),
            heartbeat_count=0,
            offline_mode=True,
            state_path=state_path,
            registry=registry,
        )
        operations: list[str] = []
        hook = self.bindings.FederationDirectivesHook()
        if hook.should_run(ctx):
            hook.execute(ctx, operations)
        return DirectiveExecutionResult(
            operations=operations,
            acknowledged=relay.pending_acks,
            pending_directives=self.list_pending(),
        )

    def get_agent(self, name: str) -> dict | None:
        return self.pokedex().get(name)

    def pokedex(self):
        if self._pokedex is None:
            db_path = self.repo_root / "data" / "city.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._pokedex = self.bindings.Pokedex(db_path=str(db_path))
        return self._pokedex