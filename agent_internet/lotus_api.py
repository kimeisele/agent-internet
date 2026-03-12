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
from .steward_protocol_compat import summarize_steward_protocol_bindings


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