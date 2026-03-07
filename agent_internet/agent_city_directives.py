from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from secrets import token_hex

from .steward_substrate import StewardSubstrateBindings, load_steward_substrate


class AgentCityDirectiveType(StrEnum):
    REGISTER_AGENT = "register_agent"
    FREEZE_AGENT = "freeze_agent"
    CREATE_MISSION = "create_mission"
    EXECUTE_CODE = "execute_code"
    POLICY_UPDATE = "policy_update"


_REQUIRED_PARAMS = {
    AgentCityDirectiveType.REGISTER_AGENT: ("name",),
    AgentCityDirectiveType.FREEZE_AGENT: ("name",),
    AgentCityDirectiveType.CREATE_MISSION: ("topic",),
    AgentCityDirectiveType.EXECUTE_CODE: ("contract",),
    AgentCityDirectiveType.POLICY_UPDATE: (),
}


def _directive_attr(directive: object, attr: str, default: object = "") -> object:
    if isinstance(directive, dict):
        return directive.get(attr, default)
    return getattr(directive, attr, default)


def validate_agent_city_directive(directive: object) -> None:
    directive_type = AgentCityDirectiveType(_directive_attr(directive, "directive_type"))
    directive_id = _directive_attr(directive, "id")
    params = _directive_attr(directive, "params", {})

    if not isinstance(directive_id, str) or not directive_id:
        raise ValueError("Directive id must be a non-empty string")
    if not isinstance(params, dict):
        raise TypeError("Directive params must be a dict")

    missing = [key for key in _REQUIRED_PARAMS[directive_type] if not params.get(key)]
    if missing:
        raise ValueError(f"Directive {directive_type.value} missing required params: {', '.join(missing)}")


@dataclass(slots=True)
class AgentCityDirectiveFactory:
    source: str = "agent-internet"
    bindings: StewardSubstrateBindings = field(default_factory=load_steward_substrate)

    def register_agent(self, name: str, *, directive_id: str | None = None) -> object:
        return self._build(AgentCityDirectiveType.REGISTER_AGENT, {"name": name}, directive_id)

    def freeze_agent(
        self,
        name: str,
        *,
        directive_id: str | None = None,
        reason: str = "",
    ) -> object:
        params = {"name": name}
        if reason:
            params["reason"] = reason
        return self._build(AgentCityDirectiveType.FREEZE_AGENT, params, directive_id)

    def create_mission(
        self,
        topic: str,
        *,
        directive_id: str | None = None,
        context: str = "",
        priority: str = "medium",
        source_post_id: str = "",
    ) -> object:
        params = {"topic": topic, "priority": priority}
        if context:
            params["context"] = context
        if source_post_id:
            params["source_post_id"] = source_post_id
        return self._build(AgentCityDirectiveType.CREATE_MISSION, params, directive_id)

    def execute_code(
        self,
        contract: str,
        *,
        directive_id: str | None = None,
        source: str = "agent-internet",
    ) -> object:
        return self._build(
            AgentCityDirectiveType.EXECUTE_CODE,
            {"contract": contract, "source": source},
            directive_id,
        )

    def policy_update(
        self,
        description: str,
        *,
        directive_id: str | None = None,
        changes: dict | None = None,
    ) -> object:
        params = {"description": description}
        if changes:
            params["changes"] = dict(changes)
        return self._build(AgentCityDirectiveType.POLICY_UPDATE, params, directive_id)

    def _build(
        self,
        directive_type: AgentCityDirectiveType,
        params: dict,
        directive_id: str | None,
    ) -> object:
        directive = self.bindings.FederationDirective(
            id=directive_id or self._new_id(directive_type),
            directive_type=directive_type.value,
            params=params,
            source=self.source,
        )
        validate_agent_city_directive(directive)
        return directive

    def _new_id(self, directive_type: AgentCityDirectiveType) -> str:
        return f"{directive_type.value}_{token_hex(4)}"
