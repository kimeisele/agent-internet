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
    SlotDescriptor,
    SlotStatus,
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
    assert outcome.artifacts["claim_id"] == f"claim:{intent.intent_id}"
    assert len(plane.registry.list_spaces()) == 1
    claim = plane.registry.get_space_claim(f"claim:{intent.intent_id}")
    assert claim is not None
    assert claim.space_id == outcome.artifacts["space_id"]


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
    assert outcome.artifacts["reclaimed"] is False
    assert outcome.artifacts["lease_id"] == f"lease:{intent.intent_id}"
    lease = plane.registry.get_slot_lease(f"lease:{intent.intent_id}")
    assert lease is not None
    assert lease.slot_id == outcome.artifacts["slot_id"]


def test_slot_request_actuator_reclaims_matching_dormant_slot():
    plane = AgentInternetControlPlane()
    plane.upsert_slot(
        SlotDescriptor(
            slot_id="slot-reclaim",
            space_id="space-1",
            slot_kind="general",
            holder_subject_id="old-holder",
            status=SlotStatus.DORMANT,
            reclaimable_since_at=10.0,
            lease_expires_at=10.0,
            heartbeat_source="steward-protocol/mahamantra",
            heartbeat=2,
        )
    )
    registry = IntentActuatorRegistry.with_defaults()
    intent = _make_intent(IntentType.REQUEST_SLOT, space_id="space-1", created_at=20.0, labels={"slot_kind": "general"})
    context = ActuationContext(control_plane=plane)

    outcome = registry.actuate(intent, context)

    assert outcome.result == ActuatorResult.SUCCESS
    assert outcome.artifacts == {"slot_id": "slot-reclaim", "reclaimed": True, "lease_id": f"lease:{intent.intent_id}"}
    stored = plane.registry.get_slot("slot-reclaim")
    assert stored is not None
    assert stored.holder_subject_id == "operator-1"
    assert stored.status == SlotStatus.ACTIVE
    assert stored.last_seen_at == 20.0
    assert stored.lease_expires_at is None
    assert stored.reclaimable_since_at is None
    lease = plane.registry.get_slot_lease(f"lease:{intent.intent_id}")
    assert lease is not None
    assert lease.slot_id == "slot-reclaim"
    assert lease.labels["reclaimed"] == "true"


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
