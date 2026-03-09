from __future__ import annotations

from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.intent_actuators import (
    ActuationContext,
    ActuatorResult,
    IntentActuatorRegistry,
)
from agent_internet.models import (
    IntentRecord,
    IntentStatus,
    IntentType,
)


def _make_intent(intent_type: IntentType, status: IntentStatus = IntentStatus.ACCEPTED, **kwargs) -> IntentRecord:
    return IntentRecord(
        intent_id=f"test-intent-{intent_type.value}",
        intent_type=intent_type,
        status=status,
        title=f"Test {intent_type.value}",
        requested_by_subject_id="operator-1",
        repo="test/repo",
        city_id="alpha",
        **kwargs,
    )


def test_space_claim_actuator():
    plane = AgentInternetControlPlane()
    registry = IntentActuatorRegistry.with_defaults()
    intent = _make_intent(IntentType.REQUEST_SPACE_CLAIM)
    context = ActuationContext(control_plane=plane)
    outcome = registry.actuate(intent, context)
    assert outcome.result == ActuatorResult.SUCCESS
    assert "space_id" in outcome.artifacts
    assert len(plane.registry.list_spaces()) == 1


def test_fork_actuator():
    plane = AgentInternetControlPlane()
    registry = IntentActuatorRegistry.with_defaults()
    intent = _make_intent(
        IntentType.REQUEST_FORK,
        labels={"upstream_repo": "origin/main"},
    )
    context = ActuationContext(control_plane=plane)
    outcome = registry.actuate(intent, context)
    assert outcome.result == ActuatorResult.SUCCESS
    assert "lineage_id" in outcome.artifacts
    assert len(plane.registry.list_fork_lineage()) == 1


def test_issue_actuator():
    registry = IntentActuatorRegistry.with_defaults()
    intent = _make_intent(IntentType.REQUEST_ISSUE)
    context = ActuationContext()
    outcome = registry.actuate(intent, context)
    assert outcome.result == ActuatorResult.SUCCESS
    assert "issue_title" in outcome.artifacts


def test_pr_draft_actuator():
    registry = IntentActuatorRegistry.with_defaults()
    intent = _make_intent(IntentType.REQUEST_PR_DRAFT)
    context = ActuationContext()
    outcome = registry.actuate(intent, context)
    assert outcome.result == ActuatorResult.SUCCESS
    assert "pr_title" in outcome.artifacts


def test_operator_review_deferred():
    registry = IntentActuatorRegistry.with_defaults()
    intent = _make_intent(IntentType.REQUEST_OPERATOR_REVIEW)
    context = ActuationContext()
    outcome = registry.actuate(intent, context)
    assert outcome.result == ActuatorResult.DEFERRED


def test_slot_request_actuator():
    plane = AgentInternetControlPlane()
    registry = IntentActuatorRegistry.with_defaults()
    intent = _make_intent(IntentType.REQUEST_SLOT, space_id="space-1")
    context = ActuationContext(control_plane=plane)
    outcome = registry.actuate(intent, context)
    assert outcome.result == ActuatorResult.SUCCESS
    assert len(plane.registry.list_slots()) == 1


def test_actuate_pending_skips_non_accepted():
    registry = IntentActuatorRegistry.with_defaults()
    intents = [
        _make_intent(IntentType.REQUEST_ISSUE, status=IntentStatus.PENDING),
        _make_intent(IntentType.REQUEST_ISSUE, status=IntentStatus.FULFILLED),
    ]
    context = ActuationContext()
    outcomes = registry.actuate_pending(intents, context)
    assert len(outcomes) == 0


def test_dry_run():
    plane = AgentInternetControlPlane()
    registry = IntentActuatorRegistry.with_defaults()
    intent = _make_intent(IntentType.REQUEST_SPACE_CLAIM)
    context = ActuationContext(control_plane=plane, dry_run=True)
    outcome = registry.actuate(intent, context)
    assert outcome.result == ActuatorResult.SUCCESS
    assert len(plane.registry.list_spaces()) == 0


def test_outcomes_tracked():
    registry = IntentActuatorRegistry.with_defaults()
    intent = _make_intent(IntentType.REQUEST_ISSUE)
    context = ActuationContext()
    registry.actuate(intent, context)
    assert len(registry.outcomes()) == 1
