import pytest

pytest.importorskip("vibe_core")

from agent_internet.agent_city_directives import (
    AgentCityDirectiveFactory,
    AgentCityDirectiveType,
    validate_agent_city_directive,
)


def test_factory_builds_real_agent_city_directive_types():
    factory = AgentCityDirectiveFactory(source="agent-internet")

    register = factory.register_agent("HERALD")
    mission = factory.create_mission("heal federation", context="stabilize city", priority="high")
    execute = factory.execute_code("ruff_clean")
    policy = factory.policy_update("tighten ingress", changes={"mode": "strict"})

    assert register.directive_type == AgentCityDirectiveType.REGISTER_AGENT.value
    assert register.params["name"] == "HERALD"
    assert mission.params["topic"] == "heal federation"
    assert execute.params["contract"] == "ruff_clean"
    assert policy.params["changes"] == {"mode": "strict"}


def test_validation_rejects_missing_required_params():
    with pytest.raises(ValueError):
        validate_agent_city_directive(
            {"id": "dir-1", "directive_type": AgentCityDirectiveType.REGISTER_AGENT.value, "params": {}},
        )


def test_validation_accepts_known_policy_update_without_extra_fields():
    validate_agent_city_directive(
        {
            "id": "dir-2",
            "directive_type": AgentCityDirectiveType.POLICY_UPDATE.value,
            "params": {"description": "note only"},
        },
    )
