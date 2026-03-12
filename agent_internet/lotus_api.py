from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass, replace

from .agent_web import build_agent_web_manifest_for_plane
from .agent_web_crawl import build_agent_web_crawl_bootstrap_for_plane, search_agent_web_crawl_bootstrap
from .agent_web_federated_index import (
    DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH,
    load_agent_web_federated_index,
    refresh_agent_web_federated_index_for_plane,
    search_agent_web_federated_index,
)
from .agent_web_graph import build_agent_web_public_graph_for_plane
from .agent_web_index import build_agent_web_search_index_for_plane, search_agent_web_index
from .agent_web_navigation import read_agent_web_document_for_plane
from .agent_web_repo_graph import build_agent_web_repo_graph_snapshot, read_agent_web_repo_graph_context, read_agent_web_repo_graph_neighbors
from .agent_web_repo_graph_capabilities import build_agent_web_repo_graph_capability_manifest
from .agent_web_repo_graph_contracts import build_agent_web_repo_graph_contract_manifest, read_agent_web_repo_graph_contract_descriptor
from .agent_web_semantic_capabilities import build_agent_web_semantic_capability_manifest
from .agent_web_semantic_contracts import build_agent_web_semantic_contract_manifest, read_agent_web_semantic_contract_descriptor
from .agent_web_source_registry import (
    build_agent_web_crawl_bootstrap_from_registry_for_plane,
    load_agent_web_source_registry,
    search_agent_web_crawl_bootstrap_from_registry,
)
from .agent_web_semantic_overlay import (
    DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH,
    expand_query_with_agent_web_semantic_overlay,
    load_agent_web_semantic_overlay,
    refresh_agent_web_semantic_overlay,
)
from .agent_web_semantic_graph import read_agent_web_semantic_neighbors
from .agent_web_wordnet_bridge import load_agent_web_wordnet_bridge
from .assistant_surface import assistant_surface_snapshot_from_repo_root
from .control_plane import AgentInternetControlPlane
from .lotus_capabilities import build_lotus_capability_manifest
from .models import ClaimStatus, EndpointVisibility, IntentRecord, IntentStatus, IntentType, LeaseStatus, LotusApiScope, LotusApiToken, OperationReceiptRecord
from .snapshot import snapshot_control_plane
from .steward_protocol_compat import load_steward_protocol_bindings, summarize_steward_protocol_bindings


LOTUS_MUTATING_ACTIONS = frozenset(
    {
        "assign_addresses",
        "accept_intent",
        "cancel_intent",
        "create_intent",
        "expire_slot_lease",
        "expire_space_claim",
        "fulfill_intent",
        "import_authority_bundle",
        "issue_token",
        "run_projection_reconcile_once",
        "sweep_expired_grants",
        "release_slot_lease",
        "release_space_claim",
        "set_source_authority_feed_enabled",
        "publish_endpoint",
        "publish_route",
        "publish_service",
        "reject_intent",
        "refresh_agent_web_federated_index",
        "refresh_agent_web_semantic_overlay",
    },
)

_IDEMPOTENCY_EPHEMERAL_KEYS = frozenset({"request_id", "idempotency_key", "now"})
_PREFLIGHT_SUPPORTED_ACTIONS = frozenset(
    {
        "create_intent",
        "publish_endpoint",
        "publish_service",
        "publish_route",
        "release_space_claim",
        "expire_space_claim",
        "release_slot_lease",
        "expire_slot_lease",
        "sweep_expired_grants",
    },
)


def _serialize_lotus_route(route: dict) -> dict:
    payload = dict(route)
    if "priority" in payload and "nadi_priority" not in payload:
        payload["nadi_priority"] = payload["priority"]
    return payload


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IssuedLotusApiToken:
    token: LotusApiToken
    secret: str


@dataclass(slots=True)
class LotusControlPlaneAPI:
    plane: AgentInternetControlPlane

    def _with_operation_receipt(self, *, action: str, token: LotusApiToken, payload: dict, executor) -> dict:
        request_id = self._request_id(payload)
        if not request_id:
            return executor()
        request_sha256 = self._request_sha256(action=action, payload=payload)
        existing = self.plane.registry.get_operation_receipt(
            action=action,
            operator_subject=token.subject,
            request_id=request_id,
        )
        if existing is not None:
            if existing.request_sha256 != request_sha256:
                raise ValueError(f"idempotency_conflict:{action}:{request_id}")
            replayed = replace(
                existing,
                last_replayed_at=float(time.time() if payload.get("now") is None else payload["now"]),
                replay_count=existing.replay_count + 1,
            )
            self.plane.registry.upsert_operation_receipt(replayed)
            response = dict(replayed.response_payload)
            response["receipt"] = self._receipt_payload(replayed, replayed_request=True)
            return response
        applied = executor()
        receipt = OperationReceiptRecord(
            operation_id=f"op_{secrets.token_urlsafe(12)}",
            request_id=request_id,
            action=action,
            operator_subject=token.subject,
            request_sha256=request_sha256,
            response_payload=dict(applied),
            created_at=float(time.time() if payload.get("now") is None else payload["now"]),
        )
        self.plane.registry.upsert_operation_receipt(receipt)
        response = dict(applied)
        response["receipt"] = self._receipt_payload(receipt, replayed_request=False)
        return response

    @staticmethod
    def _request_id(payload: dict) -> str:
        return str(payload.get("request_id") or payload.get("idempotency_key") or "").strip()

    @staticmethod
    def _request_sha256(*, action: str, payload: dict) -> str:
        normalized = {key: value for key, value in payload.items() if key not in _IDEMPOTENCY_EPHEMERAL_KEYS}
        return _sha256_hex(json.dumps({"action": action, "payload": normalized}, sort_keys=True, separators=(",", ":"), ensure_ascii=True))

    @staticmethod
    def _receipt_payload(receipt: OperationReceiptRecord, *, replayed_request: bool) -> dict[str, object]:
        return {
            "operation_id": receipt.operation_id,
            "request_id": receipt.request_id,
            "action": receipt.action,
            "operator_subject": receipt.operator_subject,
            "status": receipt.status,
            "applied": not replayed_request,
            "replayed": replayed_request,
            "created_at": receipt.created_at,
            "last_replayed_at": receipt.last_replayed_at,
            "replay_count": receipt.replay_count,
        }

    def _preflight_idempotency(self, *, action: str, token: LotusApiToken, payload: dict) -> dict[str, object]:
        request_id = self._request_id(payload)
        if not request_id:
            return {"mode": "absent", "request_id": ""}
        request_sha256 = self._request_sha256(action=action, payload=payload)
        receipt = self.plane.registry.get_operation_receipt(action=action, operator_subject=token.subject, request_id=request_id)
        if receipt is None:
            return {"mode": "new", "request_id": request_id}
        if receipt.request_sha256 != request_sha256:
            return {
                "mode": "conflict",
                "request_id": request_id,
                "operation_id": receipt.operation_id,
                "error": f"idempotency_conflict:{action}:{request_id}",
            }
        return {
            "mode": "replay",
            "request_id": request_id,
            "operation_id": receipt.operation_id,
            "status": receipt.status,
        }

    def _preflight_result(
        self,
        *,
        action: str,
        ok: bool,
        would_apply: bool,
        effect_kind: str,
        idempotency: dict[str, object],
        blockers: list[str] | None = None,
        typed_blockers: list[dict[str, object]] | None = None,
        preview: dict[str, object] | None = None,
    ) -> dict[str, object]:
        blocker_list = list(blockers or ())
        typed_blocker_list = [dict(item) for item in (typed_blockers or ())]
        preview_payload = dict(preview or {})
        remediation_hints = self._preflight_remediation_hints(
            action=action,
            effect_kind=effect_kind,
            blockers=blocker_list,
            typed_blockers=typed_blocker_list,
            idempotency=dict(idempotency),
            preview=preview_payload,
        )
        return {
            "kind": "lotus_mutation_preflight",
            "target_action": action,
            "ok": ok,
            "would_apply": would_apply,
            "effect_kind": effect_kind,
            "blockers": blocker_list,
            "typed_blockers": typed_blocker_list,
            "idempotency": dict(idempotency),
            "preview": preview_payload,
            "remediation_hints": remediation_hints,
            "next_actions": self._preflight_next_actions(remediation_hints),
        }

    @staticmethod
    def _remediation_hint(
        *,
        hint_code: str,
        summary: str,
        lotus_action: str | None = None,
        http_path: str | None = None,
        params: dict[str, object] | None = None,
        suggested_change: dict[str, object] | None = None,
    ) -> dict[str, object]:
        hint = {
            "hint_code": hint_code,
            "summary": summary,
            "params": dict(params or {}),
        }
        if lotus_action:
            hint["lotus_action"] = lotus_action
        if http_path:
            hint["http_path"] = http_path
        if suggested_change is not None:
            hint["suggested_change"] = dict(suggested_change)
        return hint

    @staticmethod
    def _next_action(
        *,
        action_code: str,
        action_kind: str,
        purpose: str,
        lotus_action: str | None = None,
        http_path: str | None = None,
        params: dict[str, object] | None = None,
        suggested_change: dict[str, object] | None = None,
    ) -> dict[str, object]:
        action = {
            "action_code": action_code,
            "action_kind": action_kind,
            "purpose": purpose,
            "params": dict(params or {}),
        }
        if lotus_action:
            action["lotus_action"] = lotus_action
        if http_path:
            action["http_path"] = http_path
        if suggested_change is not None:
            action["suggested_change"] = dict(suggested_change)
        return action

    @staticmethod
    def _typed_blocker(*, blocker_code: str, summary: str, **context: object) -> dict[str, object]:
        blocker = {
            "blocker_code": blocker_code,
            "summary": summary,
            "context": dict(context),
        }
        return blocker

    def _preflight_remediation_hints(
        self,
        *,
        action: str,
        effect_kind: str,
        blockers: list[str],
        typed_blockers: list[dict[str, object]],
        idempotency: dict[str, object],
        preview: dict[str, object],
    ) -> list[dict[str, object]]:
        hints: list[dict[str, object]] = []
        request_id = str(idempotency.get("request_id", "") or "")
        operation_id = str(idempotency.get("operation_id", "") or "")
        if effect_kind == "replay":
            receipt_params = {"operation_id": operation_id} if operation_id else {"action": action, "request_id": request_id}
            receipt_path = f"/v1/lotus/operations/{operation_id}" if operation_id else f"/v1/lotus/operations/by-request?action={action}&request_id={request_id}"
            hints.append(
                self._remediation_hint(
                    hint_code="read_existing_receipt",
                    summary="This request already maps to an applied operation; reuse the stored receipt and skip a duplicate write.",
                    lotus_action="show_operation_receipt",
                    http_path=receipt_path,
                    params=receipt_params,
                )
            )
            return hints
        if effect_kind == "noop":
            hints.append(
                self._remediation_hint(
                    hint_code=("no_expired_grants_detected" if action == "sweep_expired_grants" else "verify_current_state"),
                    summary=(
                        "No grants are currently due for expiry; skip the sweep mutation and retry later if new expirations appear."
                        if action == "sweep_expired_grants"
                        else "The requested state already matches the current control-plane state; no mutation is needed."
                    ),
                    lotus_action="show_state",
                    http_path="/v1/lotus/state",
                )
            )
        blocker_details = typed_blockers or [self._typed_blocker(blocker_code=blocker.split(":", 1)[0], summary=blocker) for blocker in blockers]
        for blocker in blocker_details:
            blocker_code = str(blocker.get("blocker_code", ""))
            context = dict(blocker.get("context", {}))
            if blocker_code == "idempotency_conflict":
                hints.append(
                    self._remediation_hint(
                        hint_code="inspect_conflicting_receipt",
                        summary="This request_id is already bound to a different payload. Inspect the existing receipt before deciding whether to reuse or replace the request.",
                        lotus_action="show_operation_receipt",
                        http_path=f"/v1/lotus/operations/by-request?action={action}&request_id={request_id}",
                        params={"action": action, "request_id": request_id},
                    )
                )
                hints.append(
                    self._remediation_hint(
                        hint_code="mint_new_request_id",
                        summary="If you intend a different mutation payload, retry with a fresh request_id instead of reusing the conflicting one.",
                        suggested_change={"field": "request_id", "strategy": "mint_new_unique_value"},
                    )
                )
                continue
            if blocker_code == "unknown_space_claim":
                hints.append(
                    self._remediation_hint(
                        hint_code="refresh_space_claim_inventory",
                        summary="The referenced claim_id was not found. Refresh the claims inventory before retrying the lifecycle transition.",
                        lotus_action="list_space_claims",
                        http_path="/v1/lotus/space-claims",
                        params={"claim_id": context.get("resource_id", "")},
                    )
                )
                continue
            if blocker_code == "unknown_slot_lease":
                hints.append(
                    self._remediation_hint(
                        hint_code="refresh_slot_lease_inventory",
                        summary="The referenced lease_id was not found. Refresh the slot-lease inventory before retrying the lifecycle transition.",
                        lotus_action="list_slot_leases",
                        http_path="/v1/lotus/slot-leases",
                        params={"lease_id": context.get("resource_id", "")},
                    )
                )
                continue
            if blocker_code == "invalid_space_claim_transition":
                current_status = str(context.get("current_status", preview.get("current_status", "")))
                target_status = str(context.get("target_status", preview.get("target_status", "")))
                hints.append(
                    self._remediation_hint(
                        hint_code=("skip_duplicate_transition" if current_status == target_status else "inspect_space_claim_status"),
                        summary=(
                            "The claim already has the requested target status; skip this duplicate transition and continue."
                            if current_status == target_status
                            else "The claim is not in a transitionable status. Inspect current claim state before choosing the next lifecycle action."
                        ),
                        lotus_action="list_space_claims",
                        http_path="/v1/lotus/space-claims",
                        params={"claim_id": context.get("resource_id", preview.get("claim_id", ""))},
                    )
                )
                continue
            if blocker_code == "invalid_slot_lease_transition":
                current_status = str(context.get("current_status", preview.get("current_status", "")))
                target_status = str(context.get("target_status", preview.get("target_status", "")))
                hints.append(
                    self._remediation_hint(
                        hint_code=("skip_duplicate_transition" if current_status == target_status else "inspect_slot_lease_status"),
                        summary=(
                            "The lease already has the requested target status; skip this duplicate transition and continue."
                            if current_status == target_status
                            else "The lease is not in a transitionable status. Inspect current lease state before choosing the next lifecycle action."
                        ),
                        lotus_action="list_slot_leases",
                        http_path="/v1/lotus/slot-leases",
                        params={"lease_id": context.get("resource_id", preview.get("lease_id", ""))},
                    )
                )
                continue
            if blocker_code in {"invalid_nadi_type", "invalid_priority"}:
                hints.append(
                    self._remediation_hint(
                        hint_code="read_steward_protocol_bindings",
                        summary="The proposed route parameters do not match the steward protocol bindings. Read the current bindings and choose an allowed nadi type / priority.",
                        lotus_action="show_steward_protocol",
                        http_path="/v1/lotus/steward-protocol",
                    )
                )
        return hints

    def _preflight_next_actions(self, remediation_hints: list[dict[str, object]]) -> list[dict[str, object]]:
        next_actions: list[dict[str, object]] = []
        for hint in remediation_hints:
            hint_code = str(hint.get("hint_code", ""))
            lotus_action = hint.get("lotus_action")
            http_path = hint.get("http_path")
            params = dict(hint.get("params", {}))
            suggested_change = hint.get("suggested_change")
            summary = str(hint.get("summary", ""))
            if lotus_action:
                next_actions.append(
                    self._next_action(
                        action_code=hint_code,
                        action_kind="lotus_call",
                        purpose=summary,
                        lotus_action=str(lotus_action),
                        http_path=(str(http_path) if http_path else None),
                        params=params,
                    )
                )
                continue
            if suggested_change is not None:
                next_actions.append(
                    self._next_action(
                        action_code=hint_code,
                        action_kind="local_change",
                        purpose=summary,
                        suggested_change=dict(suggested_change),
                    )
                )
        return next_actions

    def _preflight_blocked(
        self,
        *,
        action: str,
        blocker: str | None = None,
        blockers: list[str] | None = None,
        typed_blockers: list[dict[str, object]] | None = None,
        idempotency: dict[str, object] | None = None,
        preview: dict[str, object] | None = None,
    ) -> dict[str, object]:
        blocker_list = list(blockers or ())
        if blocker is not None:
            blocker_list.append(blocker)
        typed_blocker_list = [dict(item) for item in (typed_blockers or ())]
        return self._preflight_result(
            action=action,
            ok=False,
            would_apply=False,
            effect_kind=("conflict" if any(item.get("blocker_code") == "idempotency_conflict" for item in typed_blocker_list) or any(item.startswith("idempotency_conflict:") for item in blocker_list) else "blocked"),
            blockers=blocker_list,
            typed_blockers=typed_blocker_list,
            idempotency=(idempotency or {"mode": "absent", "request_id": ""}),
            preview=preview,
        )

    def _preflight_mutation(self, *, bearer_token: str, payload: dict) -> dict:
        target_action = str(payload.get("target_action", "")).strip()
        raw_params = payload.get("params", {})
        if not isinstance(raw_params, dict):
            raise ValueError("invalid_preflight_params")
        params = dict(raw_params)
        if target_action not in _PREFLIGHT_SUPPORTED_ACTIONS:
            raise ValueError(f"unsupported_preflight_action:{target_action}")
        if target_action == "create_intent":
            return self._preflight_create_intent(bearer_token=bearer_token, payload=params)
        if target_action == "publish_endpoint":
            return self._preflight_publish_endpoint(bearer_token=bearer_token, payload=params)
        if target_action == "publish_service":
            return self._preflight_publish_service(bearer_token=bearer_token, payload=params)
        if target_action == "publish_route":
            return self._preflight_publish_route(bearer_token=bearer_token, payload=params)
        if target_action in {"release_space_claim", "expire_space_claim"}:
            return self._preflight_space_claim_transition(
                action=target_action,
                bearer_token=bearer_token,
                payload=params,
                status=(ClaimStatus.RELEASED if target_action == "release_space_claim" else ClaimStatus.EXPIRED),
            )
        if target_action in {"release_slot_lease", "expire_slot_lease"}:
            return self._preflight_slot_lease_transition(
                action=target_action,
                bearer_token=bearer_token,
                payload=params,
                status=(LeaseStatus.RELEASED if target_action == "release_slot_lease" else LeaseStatus.EXPIRED),
            )
        return self._preflight_sweep_expired_grants(bearer_token=bearer_token, payload=params)

    def _preflight_create_intent(self, *, bearer_token: str, payload: dict) -> dict:
        token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.INTENT_WRITE.value,))
        requested_by_subject_id = token.subject
        delegated_subject = str(payload.get("requested_by_subject_id", "")).strip()
        if delegated_subject:
            if LotusApiScope.INTENT_SUBJECT_DELEGATE.value not in set(token.scopes):
                raise PermissionError(f"missing_scopes:{LotusApiScope.INTENT_SUBJECT_DELEGATE.value}")
            requested_by_subject_id = delegated_subject
        idempotency = self._preflight_idempotency(action="create_intent", token=token, payload=payload)
        if idempotency["mode"] == "conflict":
            return {
                "token_id": token.token_id,
                "preflight": self._preflight_blocked(
                    action="create_intent",
                    blocker=str(idempotency["error"]),
                    typed_blockers=[
                        self._typed_blocker(
                            blocker_code="idempotency_conflict",
                            summary="This request_id is already bound to a different create_intent payload.",
                            request_id=idempotency.get("request_id", ""),
                            operation_id=idempotency.get("operation_id", ""),
                            target_action="create_intent",
                        )
                    ],
                    idempotency=idempotency,
                ),
            }
        if idempotency["mode"] == "replay":
            return {"token_id": token.token_id, "preflight": self._preflight_result(action="create_intent", ok=True, would_apply=False, effect_kind="replay", idempotency=idempotency, preview={"operation_id": idempotency["operation_id"]})}
        created_at = float(time.time() if payload.get("now") is None else payload["now"])
        intent = IntentRecord(
            intent_id=str(payload.get("intent_id") or f"intent_{created_at:.6f}".replace(".", "_")),
            intent_type=IntentType(str(payload["intent_type"])),
            status=IntentStatus.PENDING,
            title=str(payload.get("title", "")),
            description=str(payload.get("description", "")),
            requested_by_subject_id=requested_by_subject_id,
            repo=str(payload.get("repo", "")),
            city_id=str(payload.get("city_id", "")),
            space_id=str(payload.get("space_id", "")),
            slot_id=str(payload.get("slot_id", "")),
            lineage_id=str(payload.get("lineage_id", "")),
            discussion_id=str(payload.get("discussion_id", "")),
            linked_issue_url=str(payload.get("linked_issue_url", "")),
            linked_pr_url=str(payload.get("linked_pr_url", "")),
            created_at=created_at,
            updated_at=created_at,
            labels=dict(payload.get("labels", {})),
        )
        existing = self.plane.registry.get_intent(intent.intent_id)
        effect_kind = "create"
        would_apply = True
        if existing is not None:
            effect_kind = "noop" if asdict(existing) == asdict(intent) else "update"
            would_apply = effect_kind != "noop"
        return {
            "token_id": token.token_id,
            "preflight": self._preflight_result(
                action="create_intent",
                ok=True,
                would_apply=would_apply,
                effect_kind=effect_kind,
                idempotency=idempotency,
                preview={"intent": asdict(intent)},
            ),
        }

    def _preflight_publish_endpoint(self, *, bearer_token: str, payload: dict) -> dict:
        token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.ENDPOINT_WRITE.value,))
        idempotency = self._preflight_idempotency(action="publish_endpoint", token=token, payload=payload)
        if idempotency["mode"] == "conflict":
            return {
                "token_id": token.token_id,
                "preflight": self._preflight_blocked(
                    action="publish_endpoint",
                    blocker=str(idempotency["error"]),
                    typed_blockers=[
                        self._typed_blocker(
                            blocker_code="idempotency_conflict",
                            summary="This request_id is already bound to a different publish_endpoint payload.",
                            request_id=idempotency.get("request_id", ""),
                            operation_id=idempotency.get("operation_id", ""),
                            target_action="publish_endpoint",
                        )
                    ],
                    idempotency=idempotency,
                ),
            }
        if idempotency["mode"] == "replay":
            return {"token_id": token.token_id, "preflight": self._preflight_result(action="publish_endpoint", ok=True, would_apply=False, effect_kind="replay", idempotency=idempotency, preview={"operation_id": idempotency["operation_id"]})}
        endpoint_id = str(payload.get("endpoint_id") or f"{payload['city_id']}:{payload['public_handle']}")
        visibility = EndpointVisibility(payload.get("visibility", EndpointVisibility.PUBLIC.value))
        existing = self.plane.registry.get_hosted_endpoint(endpoint_id)
        preview = {
            "endpoint": {
                "endpoint_id": endpoint_id,
                "owner_city_id": str(payload["city_id"]),
                "public_handle": str(payload["public_handle"]),
                "transport": str(payload["transport"]),
                "location": str(payload["location"]),
                "visibility": visibility.value,
                "ttl_s": payload.get("ttl_s"),
                "would_assign_link_address": self.plane.registry.get_link_address(str(payload["city_id"])) is None,
                "would_assign_network_address": self.plane.registry.get_network_address(str(payload["city_id"])) is None,
            },
        }
        effect_kind = "create"
        would_apply = True
        if existing is not None:
            unchanged = (
                existing.owner_city_id == str(payload["city_id"])
                and existing.public_handle == str(payload["public_handle"])
                and existing.transport == str(payload["transport"])
                and existing.location == str(payload["location"])
                and existing.visibility == visibility
                and dict(existing.labels) == dict(payload.get("labels", {}))
            )
            effect_kind = "noop" if unchanged else "update"
            would_apply = effect_kind != "noop"
        return {"token_id": token.token_id, "preflight": self._preflight_result(action="publish_endpoint", ok=True, would_apply=would_apply, effect_kind=effect_kind, idempotency=idempotency, preview=preview)}

    def _preflight_publish_service(self, *, bearer_token: str, payload: dict) -> dict:
        token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.SERVICE_WRITE.value,))
        idempotency = self._preflight_idempotency(action="publish_service", token=token, payload=payload)
        if idempotency["mode"] == "conflict":
            return {
                "token_id": token.token_id,
                "preflight": self._preflight_blocked(
                    action="publish_service",
                    blocker=str(idempotency["error"]),
                    typed_blockers=[
                        self._typed_blocker(
                            blocker_code="idempotency_conflict",
                            summary="This request_id is already bound to a different publish_service payload.",
                            request_id=idempotency.get("request_id", ""),
                            operation_id=idempotency.get("operation_id", ""),
                            target_action="publish_service",
                        )
                    ],
                    idempotency=idempotency,
                ),
            }
        if idempotency["mode"] == "replay":
            return {"token_id": token.token_id, "preflight": self._preflight_result(action="publish_service", ok=True, would_apply=False, effect_kind="replay", idempotency=idempotency, preview={"operation_id": idempotency["operation_id"]})}
        service_id = str(payload.get("service_id") or f"{payload['city_id']}:{payload['service_name']}")
        visibility = EndpointVisibility(payload.get("visibility", EndpointVisibility.FEDERATED.value))
        existing = self.plane.registry.get_service_address(service_id)
        preview = {
            "service_address": {
                "service_id": service_id,
                "owner_city_id": str(payload["city_id"]),
                "service_name": str(payload["service_name"]),
                "public_handle": str(payload["public_handle"]),
                "transport": str(payload["transport"]),
                "location": str(payload["location"]),
                "visibility": visibility.value,
                "auth_required": bool(payload.get("auth_required", True)),
                "required_scopes": list(payload.get("required_scopes", ())),
                "would_assign_network_address": self.plane.registry.get_network_address(str(payload["city_id"])) is None,
            },
        }
        effect_kind = "create"
        would_apply = True
        if existing is not None:
            unchanged = (
                existing.owner_city_id == str(payload["city_id"])
                and existing.service_name == str(payload["service_name"])
                and existing.public_handle == str(payload["public_handle"])
                and existing.transport == str(payload["transport"])
                and existing.location == str(payload["location"])
                and existing.visibility == visibility
                and existing.auth_required == bool(payload.get("auth_required", True))
                and tuple(existing.required_scopes) == tuple(payload.get("required_scopes", ()))
                and dict(existing.labels) == dict(payload.get("labels", {}))
            )
            effect_kind = "noop" if unchanged else "update"
            would_apply = effect_kind != "noop"
        return {"token_id": token.token_id, "preflight": self._preflight_result(action="publish_service", ok=True, would_apply=would_apply, effect_kind=effect_kind, idempotency=idempotency, preview=preview)}

    def _preflight_publish_route(self, *, bearer_token: str, payload: dict) -> dict:
        token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.SERVICE_WRITE.value,))
        idempotency = self._preflight_idempotency(action="publish_route", token=token, payload=payload)
        if idempotency["mode"] == "conflict":
            return {
                "token_id": token.token_id,
                "preflight": self._preflight_blocked(
                    action="publish_route",
                    blocker=str(idempotency["error"]),
                    typed_blockers=[
                        self._typed_blocker(
                            blocker_code="idempotency_conflict",
                            summary="This request_id is already bound to a different publish_route payload.",
                            request_id=idempotency.get("request_id", ""),
                            operation_id=idempotency.get("operation_id", ""),
                            target_action="publish_route",
                        )
                    ],
                    idempotency=idempotency,
                ),
            }
        if idempotency["mode"] == "replay":
            return {"token_id": token.token_id, "preflight": self._preflight_result(action="publish_route", ok=True, would_apply=False, effect_kind="replay", idempotency=idempotency, preview={"operation_id": idempotency["operation_id"]})}
        bindings = load_steward_protocol_bindings()
        selected_nadi_type = str(payload.get("nadi_type", "") or bindings.default_route_nadi_type)
        selected_priority = str(payload.get("nadi_priority", payload.get("priority", "")) or bindings.default_route_priority)
        blockers: list[str] = []
        typed_blockers: list[dict[str, object]] = []
        if selected_nadi_type not in bindings.allowed_nadi_types:
            blockers.append(f"invalid_nadi_type:{selected_nadi_type}")
            typed_blockers.append(
                self._typed_blocker(
                    blocker_code="invalid_nadi_type",
                    summary="The proposed route nadi type is not allowed by the steward protocol bindings.",
                    field="nadi_type",
                    value=selected_nadi_type,
                    allowed_values=list(bindings.allowed_nadi_types),
                )
            )
        if selected_priority not in bindings.allowed_priorities:
            blockers.append(f"invalid_priority:{selected_priority}")
            typed_blockers.append(
                self._typed_blocker(
                    blocker_code="invalid_priority",
                    summary="The proposed route priority is not allowed by the steward protocol bindings.",
                    field="priority",
                    value=selected_priority,
                    allowed_values=list(bindings.allowed_priorities),
                )
            )
        route_id = str(payload.get("route_id") or f"{payload['owner_city_id']}:{payload['destination_prefix']}")
        preview = {
            "route": {
                "route_id": route_id,
                "owner_city_id": str(payload["owner_city_id"]),
                "destination_prefix": str(payload["destination_prefix"]),
                "target_city_id": str(payload["target_city_id"]),
                "next_hop_city_id": str(payload["next_hop_city_id"]),
                "metric": int(payload.get("metric", 100)),
                "nadi_type": selected_nadi_type,
                "priority": selected_priority,
                "ttl_ms": int(payload.get("ttl_ms", payload.get("ttl_s", 24.0) * 1000 if payload.get("ttl_s") is not None else 24_000)),
            },
        }
        if blockers:
            return {
                "token_id": token.token_id,
                "preflight": self._preflight_blocked(
                    action="publish_route",
                    blockers=blockers,
                    typed_blockers=typed_blockers,
                    idempotency=idempotency,
                    preview=preview,
                ),
            }
        existing = self.plane.registry.get_route(route_id)
        effect_kind = "create"
        would_apply = True
        if existing is not None:
            unchanged = (
                existing.owner_city_id == str(payload["owner_city_id"])
                and existing.destination_prefix == str(payload["destination_prefix"])
                and existing.target_city_id == str(payload["target_city_id"])
                and existing.next_hop_city_id == str(payload["next_hop_city_id"])
                and existing.metric == int(payload.get("metric", 100))
                and existing.nadi_type == selected_nadi_type
                and existing.priority == selected_priority
                and dict(existing.labels) == dict(payload.get("labels", {}))
            )
            effect_kind = "noop" if unchanged else "update"
            would_apply = effect_kind != "noop"
        return {"token_id": token.token_id, "preflight": self._preflight_result(action="publish_route", ok=True, would_apply=would_apply, effect_kind=effect_kind, idempotency=idempotency, preview=preview)}

    def _preflight_space_claim_transition(self, *, action: str, bearer_token: str, payload: dict, status: ClaimStatus) -> dict:
        token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.CONTRACT_WRITE.value,))
        idempotency = self._preflight_idempotency(action=action, token=token, payload=payload)
        if idempotency["mode"] == "conflict":
            return {
                "token_id": token.token_id,
                "preflight": self._preflight_blocked(
                    action=action,
                    blocker=str(idempotency["error"]),
                    typed_blockers=[
                        self._typed_blocker(
                            blocker_code="idempotency_conflict",
                            summary="This request_id is already bound to a different space-claim lifecycle payload.",
                            request_id=idempotency.get("request_id", ""),
                            operation_id=idempotency.get("operation_id", ""),
                            target_action=action,
                        )
                    ],
                    idempotency=idempotency,
                ),
            }
        if idempotency["mode"] == "replay":
            return {"token_id": token.token_id, "preflight": self._preflight_result(action=action, ok=True, would_apply=False, effect_kind="replay", idempotency=idempotency, preview={"operation_id": idempotency["operation_id"]})}
        claim = self.plane.registry.get_space_claim(str(payload["claim_id"]))
        preview = {"claim_id": str(payload["claim_id"]), "target_status": status.value}
        if claim is None:
            return {
                "token_id": token.token_id,
                "preflight": self._preflight_blocked(
                    action=action,
                    blocker=f"unknown_space_claim:{payload['claim_id']}",
                    typed_blockers=[
                        self._typed_blocker(
                            blocker_code="unknown_space_claim",
                            summary="The referenced space claim does not exist in the current registry snapshot.",
                            resource_kind="space_claim",
                            resource_id=str(payload["claim_id"]),
                            target_action=action,
                        )
                    ],
                    idempotency=idempotency,
                    preview=preview,
                ),
            }
        allowed = status in {ClaimStatus.RELEASED, ClaimStatus.EXPIRED} and claim.status == ClaimStatus.GRANTED
        if not allowed:
            return {
                "token_id": token.token_id,
                "preflight": self._preflight_blocked(
                    action=action,
                    blocker=f"invalid_space_claim_transition:{claim.status.value}->{status.value}",
                    typed_blockers=[
                        self._typed_blocker(
                            blocker_code="invalid_space_claim_transition",
                            summary="The space claim is not currently in a transitionable status for this lifecycle action.",
                            resource_kind="space_claim",
                            resource_id=claim.claim_id,
                            current_status=claim.status.value,
                            target_status=status.value,
                            allowed_from_statuses=[ClaimStatus.GRANTED.value],
                            target_action=action,
                        )
                    ],
                    idempotency=idempotency,
                    preview={**preview, "current_status": claim.status.value},
                ),
            }
        return {"token_id": token.token_id, "preflight": self._preflight_result(action=action, ok=True, would_apply=True, effect_kind="transition", idempotency=idempotency, preview={**preview, "current_status": claim.status.value})}

    def _preflight_slot_lease_transition(self, *, action: str, bearer_token: str, payload: dict, status: LeaseStatus) -> dict:
        token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.CONTRACT_WRITE.value,))
        idempotency = self._preflight_idempotency(action=action, token=token, payload=payload)
        if idempotency["mode"] == "conflict":
            return {
                "token_id": token.token_id,
                "preflight": self._preflight_blocked(
                    action=action,
                    blocker=str(idempotency["error"]),
                    typed_blockers=[
                        self._typed_blocker(
                            blocker_code="idempotency_conflict",
                            summary="This request_id is already bound to a different slot-lease lifecycle payload.",
                            request_id=idempotency.get("request_id", ""),
                            operation_id=idempotency.get("operation_id", ""),
                            target_action=action,
                        )
                    ],
                    idempotency=idempotency,
                ),
            }
        if idempotency["mode"] == "replay":
            return {"token_id": token.token_id, "preflight": self._preflight_result(action=action, ok=True, would_apply=False, effect_kind="replay", idempotency=idempotency, preview={"operation_id": idempotency["operation_id"]})}
        lease = self.plane.registry.get_slot_lease(str(payload["lease_id"]))
        preview = {"lease_id": str(payload["lease_id"]), "target_status": status.value}
        if lease is None:
            return {
                "token_id": token.token_id,
                "preflight": self._preflight_blocked(
                    action=action,
                    blocker=f"unknown_slot_lease:{payload['lease_id']}",
                    typed_blockers=[
                        self._typed_blocker(
                            blocker_code="unknown_slot_lease",
                            summary="The referenced slot lease does not exist in the current registry snapshot.",
                            resource_kind="slot_lease",
                            resource_id=str(payload["lease_id"]),
                            target_action=action,
                        )
                    ],
                    idempotency=idempotency,
                    preview=preview,
                ),
            }
        allowed = status in {LeaseStatus.RELEASED, LeaseStatus.EXPIRED} and lease.status == LeaseStatus.ACTIVE
        if not allowed:
            return {
                "token_id": token.token_id,
                "preflight": self._preflight_blocked(
                    action=action,
                    blocker=f"invalid_slot_lease_transition:{lease.status.value}->{status.value}",
                    typed_blockers=[
                        self._typed_blocker(
                            blocker_code="invalid_slot_lease_transition",
                            summary="The slot lease is not currently in a transitionable status for this lifecycle action.",
                            resource_kind="slot_lease",
                            resource_id=lease.lease_id,
                            current_status=lease.status.value,
                            target_status=status.value,
                            allowed_from_statuses=[LeaseStatus.ACTIVE.value],
                            target_action=action,
                        )
                    ],
                    idempotency=idempotency,
                    preview={**preview, "current_status": lease.status.value},
                ),
            }
        return {"token_id": token.token_id, "preflight": self._preflight_result(action=action, ok=True, would_apply=True, effect_kind="transition", idempotency=idempotency, preview={**preview, "current_status": lease.status.value})}

    def _preflight_sweep_expired_grants(self, *, bearer_token: str, payload: dict) -> dict:
        token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.CONTRACT_WRITE.value,))
        idempotency = self._preflight_idempotency(action="sweep_expired_grants", token=token, payload=payload)
        if idempotency["mode"] == "conflict":
            return {
                "token_id": token.token_id,
                "preflight": self._preflight_blocked(
                    action="sweep_expired_grants",
                    blocker=str(idempotency["error"]),
                    typed_blockers=[
                        self._typed_blocker(
                            blocker_code="idempotency_conflict",
                            summary="This request_id is already bound to a different expired-grant sweep payload.",
                            request_id=idempotency.get("request_id", ""),
                            operation_id=idempotency.get("operation_id", ""),
                            target_action="sweep_expired_grants",
                        )
                    ],
                    idempotency=idempotency,
                ),
            }
        if idempotency["mode"] == "replay":
            return {"token_id": token.token_id, "preflight": self._preflight_result(action="sweep_expired_grants", ok=True, would_apply=False, effect_kind="replay", idempotency=idempotency, preview={"operation_id": idempotency["operation_id"]})}
        checked_at = float(time.time() if payload.get("now") is None else payload["now"])
        expired_space_claim_ids = [claim.claim_id for claim in self.plane.registry.list_space_claims() if claim.status == ClaimStatus.GRANTED and claim.expires_at is not None and claim.expires_at < checked_at]
        expired_slot_lease_ids = [lease.lease_id for lease in self.plane.registry.list_slot_leases() if lease.status == LeaseStatus.ACTIVE and lease.expires_at is not None and lease.expires_at < checked_at]
        return {
            "token_id": token.token_id,
            "preflight": self._preflight_result(
                action="sweep_expired_grants",
                ok=True,
                would_apply=bool(expired_space_claim_ids or expired_slot_lease_ids),
                effect_kind=("sweep" if expired_space_claim_ids or expired_slot_lease_ids else "noop"),
                idempotency=idempotency,
                preview={
                    "checked_at": checked_at,
                    "expired_space_claim_ids": expired_space_claim_ids,
                    "expired_slot_lease_ids": expired_slot_lease_ids,
                    "expired_space_claim_count": len(expired_space_claim_ids),
                    "expired_slot_lease_count": len(expired_slot_lease_ids),
                },
            ),
        }

    def _show_operation_receipt(self, *, bearer_token: str, payload: dict) -> dict:
        token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
        operation_id = str(payload.get("operation_id", "")).strip()
        if operation_id:
            receipt = self.plane.registry.get_operation_receipt_by_id(operation_id)
            if receipt is None:
                raise ValueError(f"unknown_operation_receipt:{operation_id}")
            return {"token_id": token.token_id, "operation_receipt": asdict(receipt)}
        action = str(payload.get("action", "")).strip()
        request_id = self._request_id(payload)
        if not action or not request_id:
            raise ValueError("missing_operation_receipt_lookup")
        receipt = self.plane.registry.get_operation_receipt(
            action=action,
            operator_subject=token.subject,
            request_id=request_id,
        )
        if receipt is None:
            raise ValueError(f"unknown_operation_receipt:{action}:{request_id}")
        return {"token_id": token.token_id, "operation_receipt": asdict(receipt)}

    def _transition_intent(self, *, bearer_token: str, payload: dict, status: IntentStatus) -> dict:
        token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.INTENT_REVIEW.value,))
        updated_at = float(time.time() if payload.get("now") is None else payload["now"])
        intent = self.plane.transition_intent(
            intent_id=str(payload["intent_id"]),
            status=status,
            updated_at=updated_at,
        )
        return {"token_id": token.token_id, "intent": asdict(intent)}

    def _transition_space_claim(self, *, action: str, bearer_token: str, payload: dict, status: ClaimStatus) -> dict:
        token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.CONTRACT_WRITE.value,))
        return self._with_operation_receipt(
            action=action,
            token=token,
            payload=payload,
            executor=lambda: {
                "token_id": token.token_id,
                "space_claim": asdict(
                    self.plane.transition_space_claim(
                        claim_id=str(payload["claim_id"]),
                        status=status,
                        updated_at=float(time.time() if payload.get("now") is None else payload["now"]),
                    )
                ),
            },
        )

    def _transition_slot_lease(self, *, action: str, bearer_token: str, payload: dict, status: LeaseStatus) -> dict:
        token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.CONTRACT_WRITE.value,))
        return self._with_operation_receipt(
            action=action,
            token=token,
            payload=payload,
            executor=lambda: {
                "token_id": token.token_id,
                "slot_lease": asdict(
                    self.plane.transition_slot_lease(
                        lease_id=str(payload["lease_id"]),
                        status=status,
                        updated_at=float(time.time() if payload.get("now") is None else payload["now"]),
                    )
                ),
            },
        )

    def _sweep_expired_grants(self, *, bearer_token: str, payload: dict) -> dict:
        token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.CONTRACT_WRITE.value,))
        return self._with_operation_receipt(
            action="sweep_expired_grants",
            token=token,
            payload=payload,
            executor=lambda: {
                "token_id": token.token_id,
                "grant_sweep": self.plane.sweep_expired_grants(current_time=(None if payload.get("now") is None else float(payload["now"]))),
            },
        )

    def issue_token(
        self,
        *,
        subject: str,
        scopes: tuple[str, ...],
        token_id: str = "",
        token_secret: str = "",
        now: float | None = None,
    ) -> IssuedLotusApiToken:
        issued_at = float(time.time() if now is None else now)
        secret = token_secret or f"lotus_{secrets.token_urlsafe(24)}"
        token = LotusApiToken(
            token_id=token_id or f"tok_{issued_at:.6f}".replace(".", "_"),
            subject=subject,
            token_hint=secret[:8],
            token_sha256=_sha256_hex(secret),
            scopes=tuple(sorted(set(scopes))),
            issued_at=issued_at,
        )
        self.plane.store_api_token(token)
        return IssuedLotusApiToken(token=token, secret=secret)

    def authenticate(self, bearer_token: str, *, required_scopes: tuple[str, ...] = ()) -> LotusApiToken:
        token = self.plane.registry.get_api_token_by_sha256(_sha256_hex(bearer_token))
        if token is None or token.revoked_at is not None:
            raise PermissionError("invalid_token")
        missing = sorted(set(required_scopes) - set(token.scopes))
        if missing:
            raise PermissionError(f"missing_scopes:{','.join(missing)}")
        return token

    def call(self, *, bearer_token: str, action: str, params: dict | None = None) -> dict:
        payload = dict(params or {})
        if action == "show_state":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "state": snapshot_control_plane(self.plane)}
        if action == "show_steward_protocol":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "bindings": summarize_steward_protocol_bindings()}
        if action == "preflight_mutation":
            return self._preflight_mutation(bearer_token=bearer_token, payload=payload)
        if action == "show_operation_receipt":
            return self._show_operation_receipt(bearer_token=bearer_token, payload=payload)
        if action == "lotus_capabilities":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {
                "token_id": token.token_id,
                "lotus_capabilities": build_lotus_capability_manifest(base_url=(None if payload.get("base_url") in (None, "") else str(payload.get("base_url")))),
            }
        if action == "list_spaces":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "spaces": [asdict(space) for space in self.plane.registry.list_spaces()]}
        if action == "list_slots":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "slots": [asdict(slot) for slot in self.plane.registry.list_slots()]}
        if action == "list_space_claims":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "space_claims": [asdict(claim) for claim in self.plane.registry.list_space_claims()]}
        if action == "list_slot_leases":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "slot_leases": [asdict(lease) for lease in self.plane.registry.list_slot_leases()]}
        if action == "release_space_claim":
            return self._transition_space_claim(action=action, bearer_token=bearer_token, payload=params, status=ClaimStatus.RELEASED)
        if action == "expire_space_claim":
            return self._transition_space_claim(action=action, bearer_token=bearer_token, payload=params, status=ClaimStatus.EXPIRED)
        if action == "release_slot_lease":
            return self._transition_slot_lease(action=action, bearer_token=bearer_token, payload=params, status=LeaseStatus.RELEASED)
        if action == "expire_slot_lease":
            return self._transition_slot_lease(action=action, bearer_token=bearer_token, payload=params, status=LeaseStatus.EXPIRED)
        if action == "sweep_expired_grants":
            return self._sweep_expired_grants(bearer_token=bearer_token, payload=payload)
        if action == "list_repo_roles":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "repo_roles": [asdict(record) for record in self.plane.registry.list_repo_roles()]}
        if action == "list_authority_exports":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "authority_exports": [asdict(record) for record in self.plane.registry.list_authority_exports()]}
        if action == "list_projection_bindings":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "projection_bindings": [asdict(record) for record in self.plane.registry.list_projection_bindings()]}
        if action == "list_publication_statuses":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "publication_statuses": [asdict(record) for record in self.plane.registry.list_publication_statuses()]}
        if action == "list_source_authority_feeds":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "source_authority_feeds": [asdict(record) for record in self.plane.registry.list_source_authority_feeds()]}
        if action == "list_projection_reconcile_statuses":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {
                "token_id": token.token_id,
                "projection_reconcile_statuses": [asdict(record) for record in self.plane.registry.list_projection_reconcile_statuses()],
            }
        if action == "list_fork_lineage":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {
                "token_id": token.token_id,
                "fork_lineage": [asdict(lineage) for lineage in self.plane.registry.list_fork_lineage()],
            }
        if action == "list_intents":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "intents": [asdict(intent) for intent in self.plane.registry.list_intents()]}
        if action == "get_intent":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            intent_id = str(payload["intent_id"])
            intent = self.plane.registry.get_intent(intent_id)
            if intent is None:
                raise ValueError(f"unknown_intent:{intent_id}")
            return {"token_id": token.token_id, "intent": asdict(intent)}
        if action == "assistant_snapshot":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            snapshot = assistant_surface_snapshot_from_repo_root(
                payload["root"],
                city_id=payload.get("city_id"),
                assistant_id=str(payload.get("assistant_id", "moltbook_assistant")),
                heartbeat_source=str(payload.get("heartbeat_source", "steward-protocol/mahamantra")),
            )
            return {"token_id": token.token_id, "assistant_snapshot": asdict(snapshot)}
        if action == "agent_web_manifest":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            manifest = build_agent_web_manifest_for_plane(
                payload["root"],
                plane=self.plane,
                city_id=payload.get("city_id"),
                assistant_id=str(payload.get("assistant_id", "moltbook_assistant")),
                heartbeat_source=str(payload.get("heartbeat_source", "steward-protocol/mahamantra")),
            )
            return {"token_id": token.token_id, "agent_web_manifest": manifest}
        if action == "agent_web_semantic_capabilities":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            manifest = build_agent_web_semantic_capability_manifest(base_url=payload.get("base_url"))
            return {"token_id": token.token_id, "agent_web_semantic_capabilities": manifest}
        if action == "agent_web_semantic_contracts":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            manifest = (
                read_agent_web_semantic_contract_descriptor(
                    capability_id=payload.get("capability_id"),
                    contract_id=payload.get("contract_id"),
                    version=payload.get("version"),
                    base_url=payload.get("base_url"),
                )
                if any(payload.get(key) not in (None, "") for key in ("capability_id", "contract_id", "version"))
                else build_agent_web_semantic_contract_manifest(base_url=payload.get("base_url"))
            )
            return {"token_id": token.token_id, "agent_web_semantic_contracts": manifest}
        if action == "agent_web_repo_graph_capabilities":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            manifest = build_agent_web_repo_graph_capability_manifest(base_url=payload.get("base_url"))
            return {"token_id": token.token_id, "agent_web_repo_graph_capabilities": manifest}
        if action == "agent_web_repo_graph_contracts":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            manifest = (
                read_agent_web_repo_graph_contract_descriptor(
                    capability_id=payload.get("capability_id"),
                    contract_id=payload.get("contract_id"),
                    version=payload.get("version"),
                    base_url=payload.get("base_url"),
                )
                if any(payload.get(key) not in (None, "") for key in ("capability_id", "contract_id", "version"))
                else build_agent_web_repo_graph_contract_manifest(base_url=payload.get("base_url"))
            )
            return {"token_id": token.token_id, "agent_web_repo_graph_contracts": manifest}
        if action == "agent_web_repo_graph_snapshot":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            graph = build_agent_web_repo_graph_snapshot(
                payload["root"],
                node_type=payload.get("node_type"),
                domain=payload.get("domain"),
                query=payload.get("query"),
                limit=int(payload.get("limit", 25) or 25),
            )
            return {"token_id": token.token_id, "agent_web_repo_graph": graph}
        if action == "agent_web_repo_graph_neighbors":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            graph = read_agent_web_repo_graph_neighbors(
                payload["root"],
                node_id=str(payload.get("node_id", "")),
                relation=payload.get("relation"),
                depth=int(payload.get("depth", 1) or 1),
                limit=int(payload.get("limit", 25) or 25),
            )
            return {"token_id": token.token_id, "agent_web_repo_graph_neighbors": graph}
        if action == "agent_web_repo_graph_context":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            graph = read_agent_web_repo_graph_context(payload["root"], concept=str(payload.get("concept", "")))
            return {"token_id": token.token_id, "agent_web_repo_graph_context": graph}
        if action == "agent_web_graph":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            graph = build_agent_web_public_graph_for_plane(
                payload["root"],
                plane=self.plane,
                city_id=payload.get("city_id"),
                assistant_id=str(payload.get("assistant_id", "moltbook_assistant")),
                heartbeat_source=str(payload.get("heartbeat_source", "steward-protocol/mahamantra")),
            )
            return {"token_id": token.token_id, "agent_web_graph": graph}
        if action == "agent_web_index":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            index = build_agent_web_search_index_for_plane(
                payload["root"],
                plane=self.plane,
                city_id=payload.get("city_id"),
                assistant_id=str(payload.get("assistant_id", "moltbook_assistant")),
                heartbeat_source=str(payload.get("heartbeat_source", "steward-protocol/mahamantra")),
            )
            return {"token_id": token.token_id, "agent_web_index": index}
        if action == "agent_web_search":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            index = build_agent_web_search_index_for_plane(
                payload["root"],
                plane=self.plane,
                city_id=payload.get("city_id"),
                assistant_id=str(payload.get("assistant_id", "moltbook_assistant")),
                heartbeat_source=str(payload.get("heartbeat_source", "steward-protocol/mahamantra")),
            )
            results = search_agent_web_index(
                index,
                query=str(payload.get("query", "")),
                limit=int(payload.get("limit", 10) or 10),
            )
            return {"token_id": token.token_id, "agent_web_search": results}
        if action == "agent_web_crawl":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            crawl = build_agent_web_crawl_bootstrap_for_plane(
                list(payload.get("roots", [])),
                plane=self.plane,
                assistant_id=str(payload.get("assistant_id", "moltbook_assistant")),
                heartbeat_source=str(payload.get("heartbeat_source", "steward-protocol/mahamantra")),
            )
            return {"token_id": token.token_id, "agent_web_crawl": crawl}
        if action == "agent_web_crawl_search":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            crawl = build_agent_web_crawl_bootstrap_for_plane(
                list(payload.get("roots", [])),
                plane=self.plane,
                assistant_id=str(payload.get("assistant_id", "moltbook_assistant")),
                heartbeat_source=str(payload.get("heartbeat_source", "steward-protocol/mahamantra")),
            )
            results = search_agent_web_crawl_bootstrap(
                crawl,
                query=str(payload.get("query", "")),
                limit=int(payload.get("limit", 10) or 10),
            )
            return {"token_id": token.token_id, "agent_web_crawl_search": results}
        if action == "agent_web_source_registry":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            registry = load_agent_web_source_registry(str(payload.get("registry_path", "data/control_plane/agent_web_source_registry.json")))
            return {"token_id": token.token_id, "agent_web_source_registry": registry}
        if action == "agent_web_crawl_registry":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            crawl = build_agent_web_crawl_bootstrap_from_registry_for_plane(
                str(payload.get("registry_path", "data/control_plane/agent_web_source_registry.json")),
                plane=self.plane,
                assistant_id=str(payload.get("assistant_id", "moltbook_assistant")),
                heartbeat_source=str(payload.get("heartbeat_source", "steward-protocol/mahamantra")),
            )
            return {"token_id": token.token_id, "agent_web_crawl_registry": crawl}
        if action == "agent_web_crawl_registry_search":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            results = search_agent_web_crawl_bootstrap_from_registry(
                str(payload.get("registry_path", "data/control_plane/agent_web_source_registry.json")),
                state_snapshot=snapshot_control_plane(self.plane),
                assistant_id=str(payload.get("assistant_id", "moltbook_assistant")),
                heartbeat_source=str(payload.get("heartbeat_source", "steward-protocol/mahamantra")),
                query=str(payload.get("query", "")),
                limit=int(payload.get("limit", 10) or 10),
            )
            return {"token_id": token.token_id, "agent_web_crawl_registry_search": results}
        if action == "refresh_agent_web_federated_index":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            refreshed = refresh_agent_web_federated_index_for_plane(
                str(payload.get("index_path", DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH)),
                registry_path=str(payload.get("registry_path", "data/control_plane/agent_web_source_registry.json")),
                plane=self.plane,
                semantic_overlay=load_agent_web_semantic_overlay(str(payload.get("overlay_path", DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH))),
                wordnet_bridge=None if payload.get("wordnet_path") in (None, "") else load_agent_web_wordnet_bridge(payload.get("wordnet_path")),
                assistant_id=str(payload.get("assistant_id", "moltbook_assistant")),
                heartbeat_source=str(payload.get("heartbeat_source", "steward-protocol/mahamantra")),
                now=payload.get("now"),
            )
            return {"token_id": token.token_id, "agent_web_federated_index": refreshed}
        if action == "agent_web_federated_index":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            index = load_agent_web_federated_index(str(payload.get("index_path", DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH)))
            return {"token_id": token.token_id, "agent_web_federated_index": index}
        if action == "agent_web_semantic_neighbors":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            index = load_agent_web_federated_index(str(payload.get("index_path", DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH)))
            neighbors = read_agent_web_semantic_neighbors(index, record_id=str(payload.get("record_id", "")), limit=int(payload.get("limit", 5) or 5))
            return {"token_id": token.token_id, "agent_web_semantic_neighbors": neighbors}
        if action == "agent_web_federated_search":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            index = load_agent_web_federated_index(str(payload.get("index_path", DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH)))
            results = search_agent_web_federated_index(
                index,
                query=str(payload.get("query", "")),
                limit=int(payload.get("limit", 10) or 10),
                semantic_overlay=load_agent_web_semantic_overlay(str(payload.get("overlay_path", DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH))),
                wordnet_bridge=load_agent_web_wordnet_bridge(payload.get("wordnet_path")),
            )
            return {"token_id": token.token_id, "agent_web_federated_search": results}
        if action == "refresh_agent_web_semantic_overlay":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            overlay = refresh_agent_web_semantic_overlay(
                str(payload.get("overlay_path", DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH)),
                now=payload.get("now"),
            )
            return {"token_id": token.token_id, "agent_web_semantic_overlay": overlay}
        if action == "agent_web_semantic_overlay":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            overlay = load_agent_web_semantic_overlay(str(payload.get("overlay_path", DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH)))
            return {"token_id": token.token_id, "agent_web_semantic_overlay": overlay}
        if action == "agent_web_semantic_expand":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            overlay = load_agent_web_semantic_overlay(str(payload.get("overlay_path", DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH)))
            expansion = expand_query_with_agent_web_semantic_overlay(
                overlay,
                query=str(payload.get("query", "")),
                wordnet_bridge=load_agent_web_wordnet_bridge(payload.get("wordnet_path")),
            )
            return {"token_id": token.token_id, "agent_web_semantic_expand": expansion}
        if action == "agent_web_document":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            document = read_agent_web_document_for_plane(
                payload["root"],
                plane=self.plane,
                rel=None if (payload.get("href") or payload.get("document_id")) else str(payload.get("rel", "agent_web")),
                href=payload.get("href"),
                document_id=payload.get("document_id"),
                city_id=payload.get("city_id"),
                assistant_id=str(payload.get("assistant_id", "moltbook_assistant")),
                heartbeat_source=str(payload.get("heartbeat_source", "steward-protocol/mahamantra")),
            )
            return {"token_id": token.token_id, "agent_web_document": document}
        if action == "create_intent":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.INTENT_WRITE.value,))
            created_at = float(time.time() if payload.get("now") is None else payload["now"])
            requested_by_subject_id = token.subject
            delegated_subject = str(payload.get("requested_by_subject_id", "")).strip()
            if delegated_subject:
                if LotusApiScope.INTENT_SUBJECT_DELEGATE.value not in set(token.scopes):
                    raise PermissionError(f"missing_scopes:{LotusApiScope.INTENT_SUBJECT_DELEGATE.value}")
                requested_by_subject_id = delegated_subject
            intent = IntentRecord(
                intent_id=str(payload.get("intent_id") or f"intent_{created_at:.6f}".replace(".", "_")),
                intent_type=IntentType(str(payload["intent_type"])),
                status=IntentStatus.PENDING,
                title=str(payload.get("title", "")),
                description=str(payload.get("description", "")),
                requested_by_subject_id=requested_by_subject_id,
                repo=str(payload.get("repo", "")),
                city_id=str(payload.get("city_id", "")),
                space_id=str(payload.get("space_id", "")),
                slot_id=str(payload.get("slot_id", "")),
                lineage_id=str(payload.get("lineage_id", "")),
                discussion_id=str(payload.get("discussion_id", "")),
                linked_issue_url=str(payload.get("linked_issue_url", "")),
                linked_pr_url=str(payload.get("linked_pr_url", "")),
                created_at=created_at,
                updated_at=created_at,
                labels=dict(payload.get("labels", {})),
            )
            return self._with_operation_receipt(
                action="create_intent",
                token=token,
                payload=payload,
                executor=lambda: _upsert_intent_and_build_response(self.plane, token.token_id, intent),
            )
        if action == "accept_intent":
            return self._transition_intent(bearer_token=bearer_token, payload=payload, status=IntentStatus.ACCEPTED)
        if action == "reject_intent":
            return self._transition_intent(bearer_token=bearer_token, payload=payload, status=IntentStatus.REJECTED)
        if action == "fulfill_intent":
            return self._transition_intent(bearer_token=bearer_token, payload=payload, status=IntentStatus.FULFILLED)
        if action == "cancel_intent":
            return self._transition_intent(bearer_token=bearer_token, payload=payload, status=IntentStatus.CANCELLED)
        if action == "issue_token":
            self.authenticate(bearer_token, required_scopes=(LotusApiScope.TOKEN_WRITE.value,))
            issued = self.issue_token(
                subject=payload["subject"],
                scopes=tuple(payload.get("scopes", (LotusApiScope.READ.value,))),
                token_id=payload.get("token_id", ""),
                token_secret=payload.get("token_secret", ""),
            )
            return {"token": asdict(issued.token), "secret": issued.secret}
        if action == "import_authority_bundle":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.CONTRACT_WRITE.value,))
            imported = self.plane.ingest_authority_bundle_path(
                payload["bundle_path"],
                now=(None if payload.get("now") is None else float(payload["now"])),
            )
            return {
                "token_id": token.token_id,
                "imported": {
                    "repo_role": asdict(imported["repo_role"]),
                    "authority_exports": [asdict(record) for record in imported["authority_exports"]],
                    "publication_statuses": [asdict(record) for record in imported["publication_statuses"]],
                    "artifact_count": imported["artifact_count"],
                    "bundle_path": imported["bundle_path"],
                    "artifact_paths": list(imported["artifact_paths"]),
                },
            }
        if action == "set_source_authority_feed_enabled":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.RECONCILE_WRITE.value,))
            feed = self.plane.set_source_authority_feed_enabled(payload["feed_id"], enabled=bool(payload["enabled"]))
            return {"token_id": token.token_id, "source_authority_feed": asdict(feed)}
        if action == "assign_addresses":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.ADDRESS_WRITE.value,))
            link, network = self.plane.assign_lotus_addresses(payload["city_id"], ttl_s=payload.get("ttl_s"))
            return {"token_id": token.token_id, "link_address": asdict(link), "network_address": asdict(network)}
        if action == "publish_endpoint":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.ENDPOINT_WRITE.value,))
            return self._with_operation_receipt(
                action="publish_endpoint",
                token=token,
                payload=payload,
                executor=lambda: _publish_endpoint_response(self.plane, token.token_id, payload),
            )
        if action == "publish_service":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.SERVICE_WRITE.value,))
            return self._with_operation_receipt(
                action="publish_service",
                token=token,
                payload=payload,
                executor=lambda: _publish_service_response(self.plane, token.token_id, payload),
            )
        if action == "publish_route":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.SERVICE_WRITE.value,))
            return self._with_operation_receipt(
                action="publish_route",
                token=token,
                payload=payload,
                executor=lambda: _publish_route_response(self.plane, token.token_id, payload),
            )
        if action == "resolve_handle":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            endpoint = self.plane.resolve_public_handle(payload["public_handle"])
            return {"token_id": token.token_id, "resolved": None if endpoint is None else asdict(endpoint)}
        if action == "resolve_service":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            service = self.plane.resolve_service_address(payload["city_id"], payload["service_name"])
            if service is not None and service.auth_required:
                self.authenticate(bearer_token, required_scopes=tuple(service.required_scopes))
            return {"token_id": token.token_id, "resolved": None if service is None else asdict(service)}
        if action == "resolve_next_hop":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            resolution = self.plane.resolve_next_hop(payload["source_city_id"], payload["destination"])
            return {"token_id": token.token_id, "resolved": None if resolution is None else _serialize_lotus_route(asdict(resolution))}
        raise ValueError(f"unknown_action:{action}")


def _upsert_intent_and_build_response(plane: AgentInternetControlPlane, token_id: str, intent: IntentRecord) -> dict:
    plane.upsert_intent(intent)
    return {"token_id": token_id, "intent": asdict(intent)}


def _publish_endpoint_response(plane: AgentInternetControlPlane, token_id: str, payload: dict) -> dict:
    endpoint = plane.publish_hosted_endpoint(
        owner_city_id=payload["city_id"],
        public_handle=payload["public_handle"],
        transport=payload["transport"],
        location=payload["location"],
        visibility=EndpointVisibility(payload.get("visibility", EndpointVisibility.PUBLIC.value)),
        ttl_s=payload.get("ttl_s"),
        endpoint_id=payload.get("endpoint_id", ""),
        labels=dict(payload.get("labels", {})),
        now=(None if payload.get("now") is None else float(payload["now"])),
    )
    return {"token_id": token_id, "hosted_endpoint": asdict(endpoint)}


def _publish_service_response(plane: AgentInternetControlPlane, token_id: str, payload: dict) -> dict:
    service = plane.publish_service_address(
        owner_city_id=payload["city_id"],
        service_name=payload["service_name"],
        public_handle=payload["public_handle"],
        transport=payload["transport"],
        location=payload["location"],
        visibility=EndpointVisibility(payload.get("visibility", EndpointVisibility.FEDERATED.value)),
        auth_required=bool(payload.get("auth_required", True)),
        required_scopes=tuple(payload.get("required_scopes", ())),
        ttl_s=payload.get("ttl_s"),
        service_id=payload.get("service_id", ""),
        labels=dict(payload.get("labels", {})),
        now=(None if payload.get("now") is None else float(payload["now"])),
    )
    return {"token_id": token_id, "service_address": asdict(service)}


def _publish_route_response(plane: AgentInternetControlPlane, token_id: str, payload: dict) -> dict:
    route = plane.publish_route(
        owner_city_id=payload["owner_city_id"],
        destination_prefix=payload["destination_prefix"],
        target_city_id=payload["target_city_id"],
        next_hop_city_id=payload["next_hop_city_id"],
        metric=int(payload.get("metric", 100)),
        nadi_type=str(payload.get("nadi_type", "")),
        priority=str(payload.get("nadi_priority", payload.get("priority", ""))),
        ttl_ms=payload.get("ttl_ms"),
        ttl_s=payload.get("ttl_s"),
        route_id=payload.get("route_id", ""),
        labels=dict(payload.get("labels", {})),
        now=(None if payload.get("now") is None else float(payload["now"])),
    )
    return {"token_id": token_id, "route": _serialize_lotus_route(asdict(route))}