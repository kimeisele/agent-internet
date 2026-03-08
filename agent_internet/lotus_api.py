from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import asdict, dataclass

from .agent_web import build_agent_web_manifest_for_plane
from .agent_web_graph import build_agent_web_public_graph_for_plane
from .agent_web_navigation import read_agent_web_document_for_plane
from .assistant_surface import assistant_surface_snapshot_from_repo_root
from .control_plane import AgentInternetControlPlane
from .models import EndpointVisibility, IntentRecord, IntentStatus, IntentType, LotusApiScope, LotusApiToken
from .snapshot import snapshot_control_plane
from .steward_protocol_compat import summarize_steward_protocol_bindings


LOTUS_MUTATING_ACTIONS = frozenset(
    {
        "assign_addresses",
        "accept_intent",
        "cancel_intent",
        "create_intent",
        "fulfill_intent",
        "issue_token",
        "publish_endpoint",
        "publish_route",
        "publish_service",
        "reject_intent",
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

    def _transition_intent(self, *, bearer_token: str, payload: dict, status: IntentStatus) -> dict:
        token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.INTENT_REVIEW.value,))
        updated_at = float(time.time() if payload.get("now") is None else payload["now"])
        intent = self.plane.transition_intent(
            intent_id=str(payload["intent_id"]),
            status=status,
            updated_at=updated_at,
        )
        return {"token_id": token.token_id, "intent": asdict(intent)}

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
        if action == "list_spaces":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "spaces": [asdict(space) for space in self.plane.registry.list_spaces()]}
        if action == "list_slots":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.READ.value,))
            return {"token_id": token.token_id, "slots": [asdict(slot) for slot in self.plane.registry.list_slots()]}
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
            self.plane.upsert_intent(intent)
            return {"token_id": token.token_id, "intent": asdict(intent)}
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
        if action == "assign_addresses":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.ADDRESS_WRITE.value,))
            link, network = self.plane.assign_lotus_addresses(payload["city_id"], ttl_s=payload.get("ttl_s"))
            return {"token_id": token.token_id, "link_address": asdict(link), "network_address": asdict(network)}
        if action == "publish_endpoint":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.ENDPOINT_WRITE.value,))
            endpoint = self.plane.publish_hosted_endpoint(
                owner_city_id=payload["city_id"],
                public_handle=payload["public_handle"],
                transport=payload["transport"],
                location=payload["location"],
                visibility=EndpointVisibility(payload.get("visibility", EndpointVisibility.PUBLIC.value)),
                ttl_s=payload.get("ttl_s"),
                endpoint_id=payload.get("endpoint_id", ""),
                labels=dict(payload.get("labels", {})),
            )
            return {"token_id": token.token_id, "hosted_endpoint": asdict(endpoint)}
        if action == "publish_service":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.SERVICE_WRITE.value,))
            service = self.plane.publish_service_address(
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
            )
            return {"token_id": token.token_id, "service_address": asdict(service)}
        if action == "publish_route":
            token = self.authenticate(bearer_token, required_scopes=(LotusApiScope.SERVICE_WRITE.value,))
            route = self.plane.publish_route(
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
            )
            return {"token_id": token.token_id, "route": _serialize_lotus_route(asdict(route))}
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