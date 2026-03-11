"""Intent actuators — automated fulfillment of intents.

Connects the intent state machine to concrete actions: creating forks,
opening GitHub issues, drafting pull requests, and requesting operator review.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum
from secrets import token_hex

from .models import (
    ForkLineageRecord,
    ForkMode,
    IntentRecord,
    IntentStatus,
    IntentType,
    SpaceDescriptor,
    SpaceKind,
    UpstreamSyncPolicy,
)

logger = logging.getLogger(__name__)


class ActuatorResult(StrEnum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class ActuationOutcome:
    """Result of an actuator attempting to fulfill an intent."""

    intent_id: str
    result: ActuatorResult
    detail: str = ""
    artifacts: dict = field(default_factory=dict)
    actuated_at: float = field(default_factory=time.time)


class IntentActuator:
    """Base interface for intent actuators."""

    def can_handle(self, intent: IntentRecord) -> bool:
        return False

    def actuate(self, intent: IntentRecord, context: ActuationContext) -> ActuationOutcome:
        return ActuationOutcome(
            intent_id=intent.intent_id,
            result=ActuatorResult.SKIPPED,
            detail="Base actuator does not handle any intents",
        )


@dataclass(slots=True)
class ActuationContext:
    """Shared context passed to actuators during fulfillment."""

    control_plane: object = None
    repo_root: str = ""
    operator_id: str = ""
    dry_run: bool = False
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SpaceClaimActuator(IntentActuator):
    """Fulfills REQUEST_SPACE_CLAIM intents by creating a space descriptor."""

    def can_handle(self, intent: IntentRecord) -> bool:
        return intent.intent_type == IntentType.REQUEST_SPACE_CLAIM

    def actuate(self, intent: IntentRecord, context: ActuationContext) -> ActuationOutcome:
        if context.control_plane is None:
            return ActuationOutcome(
                intent_id=intent.intent_id,
                result=ActuatorResult.FAILED,
                detail="No control plane in context",
            )

        plane = context.control_plane
        space_id = intent.space_id or f"space_{token_hex(6)}"
        space = SpaceDescriptor(
            space_id=space_id,
            kind=SpaceKind(intent.labels.get("space_kind", SpaceKind.PUBLIC_SURFACE.value)),
            owner_subject_id=intent.requested_by_subject_id,
            display_name=intent.title or space_id,
            city_id=intent.city_id,
            repo=intent.repo,
            labels=dict(intent.labels),
        )

        if not context.dry_run:
            plane.upsert_space(space)
            logger.info("Claimed space %s for intent %s", space_id, intent.intent_id)

        return ActuationOutcome(
            intent_id=intent.intent_id,
            result=ActuatorResult.SUCCESS,
            detail=f"Space {space_id} claimed",
            artifacts={"space_id": space_id},
        )


@dataclass(slots=True)
class ForkActuator(IntentActuator):
    """Fulfills REQUEST_FORK intents by recording fork lineage."""

    def can_handle(self, intent: IntentRecord) -> bool:
        return intent.intent_type == IntentType.REQUEST_FORK

    def actuate(self, intent: IntentRecord, context: ActuationContext) -> ActuationOutcome:
        if context.control_plane is None:
            return ActuationOutcome(
                intent_id=intent.intent_id,
                result=ActuatorResult.FAILED,
                detail="No control plane in context",
            )

        plane = context.control_plane
        lineage_id = intent.lineage_id or f"fork_{token_hex(6)}"
        upstream_repo = intent.labels.get("upstream_repo", "")
        if not upstream_repo and not intent.repo:
            return ActuationOutcome(
                intent_id=intent.intent_id,
                result=ActuatorResult.FAILED,
                detail="No upstream_repo or repo specified",
            )

        lineage = ForkLineageRecord(
            lineage_id=lineage_id,
            repo=intent.repo,
            upstream_repo=upstream_repo or intent.repo,
            line_root_repo=intent.labels.get("line_root_repo", upstream_repo or intent.repo),
            fork_mode=ForkMode(intent.labels.get("fork_mode", ForkMode.EXPERIMENT.value)),
            sync_policy=UpstreamSyncPolicy(intent.labels.get("sync_policy", UpstreamSyncPolicy.TRACKED.value)),
            space_id=intent.space_id,
            upstream_space_id=intent.labels.get("upstream_space_id", ""),
            forked_by_subject_id=intent.requested_by_subject_id,
            created_at=time.time(),
            labels=dict(intent.labels),
        )

        if not context.dry_run:
            plane.upsert_fork_lineage(lineage)
            logger.info("Recorded fork lineage %s for intent %s", lineage_id, intent.intent_id)

        return ActuationOutcome(
            intent_id=intent.intent_id,
            result=ActuatorResult.SUCCESS,
            detail=f"Fork lineage {lineage_id} recorded",
            artifacts={"lineage_id": lineage_id},
        )


@dataclass(slots=True)
class IssueActuator(IntentActuator):
    """Fulfills REQUEST_ISSUE intents by preparing issue metadata.

    Actual GitHub issue creation requires external CLI invocation (``gh issue create``).
    This actuator prepares the metadata and optionally invokes it.
    """

    auto_create: bool = False

    def can_handle(self, intent: IntentRecord) -> bool:
        return intent.intent_type == IntentType.REQUEST_ISSUE

    def actuate(self, intent: IntentRecord, context: ActuationContext) -> ActuationOutcome:
        issue_title = intent.title or f"Intent: {intent.intent_id}"
        issue_body = intent.description or f"Auto-generated from intent {intent.intent_id}"

        if intent.repo:
            issue_body += f"\n\nRepo: {intent.repo}"
        if intent.city_id:
            issue_body += f"\nCity: {intent.city_id}"
        if intent.space_id:
            issue_body += f"\nSpace: {intent.space_id}"

        artifacts = {
            "issue_title": issue_title,
            "issue_body": issue_body,
            "repo": intent.repo,
            "labels": list(intent.labels.keys()),
        }

        if self.auto_create and not context.dry_run:
            logger.info(
                "Issue creation prepared for intent %s (repo=%s, title=%s)",
                intent.intent_id,
                intent.repo,
                issue_title,
            )

        return ActuationOutcome(
            intent_id=intent.intent_id,
            result=ActuatorResult.SUCCESS,
            detail=f"Issue prepared: {issue_title}",
            artifacts=artifacts,
        )


@dataclass(slots=True)
class PRDraftActuator(IntentActuator):
    """Fulfills REQUEST_PR_DRAFT intents by preparing PR metadata."""

    def can_handle(self, intent: IntentRecord) -> bool:
        return intent.intent_type == IntentType.REQUEST_PR_DRAFT

    def actuate(self, intent: IntentRecord, context: ActuationContext) -> ActuationOutcome:
        pr_title = intent.title or f"Draft: {intent.intent_id}"
        pr_body = intent.description or f"Auto-generated from intent {intent.intent_id}"

        if intent.lineage_id:
            pr_body += f"\n\nFork lineage: {intent.lineage_id}"

        artifacts = {
            "pr_title": pr_title,
            "pr_body": pr_body,
            "repo": intent.repo,
            "base_branch": intent.labels.get("base_branch", "main"),
            "head_branch": intent.labels.get("head_branch", ""),
        }

        return ActuationOutcome(
            intent_id=intent.intent_id,
            result=ActuatorResult.SUCCESS,
            detail=f"PR draft prepared: {pr_title}",
            artifacts=artifacts,
        )


@dataclass(slots=True)
class OperatorReviewActuator(IntentActuator):
    """Fulfills REQUEST_OPERATOR_REVIEW by logging and deferring."""

    def can_handle(self, intent: IntentRecord) -> bool:
        return intent.intent_type == IntentType.REQUEST_OPERATOR_REVIEW

    def actuate(self, intent: IntentRecord, context: ActuationContext) -> ActuationOutcome:
        logger.info(
            "Operator review requested: intent=%s title=%s city=%s",
            intent.intent_id,
            intent.title,
            intent.city_id,
        )
        return ActuationOutcome(
            intent_id=intent.intent_id,
            result=ActuatorResult.DEFERRED,
            detail="Queued for operator review",
            artifacts={"operator_id": context.operator_id},
        )


@dataclass(slots=True)
class SlotRequestActuator(IntentActuator):
    """Fulfills REQUEST_SLOT intents by allocating a slot in a space."""

    def can_handle(self, intent: IntentRecord) -> bool:
        return intent.intent_type == IntentType.REQUEST_SLOT

    def actuate(self, intent: IntentRecord, context: ActuationContext) -> ActuationOutcome:
        if context.control_plane is None:
            return ActuationOutcome(
                intent_id=intent.intent_id,
                result=ActuatorResult.FAILED,
                detail="No control plane in context",
            )

        from .models import SlotDescriptor, SlotStatus

        plane = context.control_plane
        slot_kind = intent.labels.get("slot_kind", "general")
        now = float(intent.updated_at or intent.created_at or time.time())
        reclaimed = plane.find_reclaimable_slot(space_id=intent.space_id, slot_kind=slot_kind, now=now)
        if reclaimed is not None:
            slot_id = reclaimed.slot_id
            slot = replace(
                reclaimed,
                holder_subject_id=intent.requested_by_subject_id,
                status=SlotStatus.ACTIVE,
                heartbeat_source="",
                heartbeat=None,
                last_seen_at=now,
                lease_expires_at=None,
                reclaimable_since_at=None,
                labels=dict(intent.labels),
            )
            detail = f"Slot {slot_id} reclaimed"
            artifacts = {"slot_id": slot_id, "reclaimed": True}
        else:
            slot_id = intent.slot_id or f"slot_{token_hex(6)}"
            slot = SlotDescriptor(
                slot_id=slot_id,
                space_id=intent.space_id,
                slot_kind=slot_kind,
                holder_subject_id=intent.requested_by_subject_id,
                status=SlotStatus.ACTIVE,
                last_seen_at=now,
                labels=dict(intent.labels),
            )
            detail = f"Slot {slot_id} allocated"
            artifacts = {"slot_id": slot_id, "reclaimed": False}

        if not context.dry_run:
            plane.upsert_slot(slot)
            logger.info("%s for intent %s", detail, intent.intent_id)

        return ActuationOutcome(
            intent_id=intent.intent_id,
            result=ActuatorResult.SUCCESS,
            detail=detail,
            artifacts=artifacts,
        )


@dataclass(slots=True)
class IntentActuatorRegistry:
    """Registry of actuators, keyed by intent type.

    Orchestrates intent fulfillment by dispatching to the appropriate actuator
    and managing the intent state machine transitions.
    """

    _actuators: list[IntentActuator] = field(default_factory=list)
    _outcomes: list[ActuationOutcome] = field(default_factory=list)

    @classmethod
    def with_defaults(cls) -> IntentActuatorRegistry:
        """Create a registry with all built-in actuators."""
        return cls(
            _actuators=[
                SpaceClaimActuator(),
                SlotRequestActuator(),
                ForkActuator(),
                IssueActuator(),
                PRDraftActuator(),
                OperatorReviewActuator(),
            ],
        )

    def register(self, actuator: IntentActuator) -> None:
        self._actuators.append(actuator)

    def find_actuator(self, intent: IntentRecord) -> IntentActuator | None:
        for actuator in self._actuators:
            if actuator.can_handle(intent):
                return actuator
        return None

    def actuate(self, intent: IntentRecord, context: ActuationContext) -> ActuationOutcome:
        """Find and invoke the appropriate actuator for an intent."""
        actuator = self.find_actuator(intent)
        if actuator is None:
            outcome = ActuationOutcome(
                intent_id=intent.intent_id,
                result=ActuatorResult.SKIPPED,
                detail=f"No actuator registered for {intent.intent_type.value}",
            )
            self._outcomes.append(outcome)
            return outcome

        outcome = actuator.actuate(intent, context)
        self._outcomes.append(outcome)

        # Transition intent state based on outcome
        if not context.dry_run and context.control_plane is not None:
            upsert = getattr(context.control_plane, "upsert_intent", None)
            if callable(upsert):
                new_status = {
                    ActuatorResult.SUCCESS: IntentStatus.FULFILLED,
                    ActuatorResult.FAILED: IntentStatus.REJECTED,
                    ActuatorResult.DEFERRED: IntentStatus.ACCEPTED,
                    ActuatorResult.SKIPPED: IntentStatus.ACCEPTED,
                }
                target_status = new_status.get(outcome.result, IntentStatus.ACCEPTED)
                if target_status != intent.status:
                    updated = IntentRecord(
                        intent_id=intent.intent_id,
                        intent_type=intent.intent_type,
                        status=target_status,
                        title=intent.title,
                        description=intent.description,
                        requested_by_subject_id=intent.requested_by_subject_id,
                        repo=intent.repo,
                        city_id=intent.city_id,
                        space_id=intent.space_id,
                        slot_id=intent.slot_id,
                        lineage_id=intent.lineage_id,
                        discussion_id=intent.discussion_id,
                        linked_issue_url=intent.linked_issue_url,
                        linked_pr_url=intent.linked_pr_url,
                        created_at=intent.created_at,
                        updated_at=time.time(),
                        labels=intent.labels,
                    )
                    upsert(updated)

        return outcome

    def actuate_pending(self, intents: list[IntentRecord], context: ActuationContext) -> list[ActuationOutcome]:
        """Process all pending intents that have been accepted."""
        outcomes: list[ActuationOutcome] = []
        for intent in intents:
            if intent.status != IntentStatus.ACCEPTED:
                continue
            outcome = self.actuate(intent, context)
            outcomes.append(outcome)
        return outcomes

    def outcomes(self) -> list[ActuationOutcome]:
        return list(self._outcomes)
