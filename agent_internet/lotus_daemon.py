from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.parse import parse_qs, unquote, urlsplit

from .lotus_api import LOTUS_MUTATING_ACTIONS, LotusApiScope, LotusControlPlaneAPI
from .projection_reconciler import ProjectionReconciler
from .snapshot import ControlPlaneStateStore


logger = logging.getLogger(__name__)


class _LotusThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _LotusRequestHandler(BaseHTTPRequestHandler):
    server: _LotusThreadingHTTPServer

    def do_GET(self) -> None:
        self._handle_request()

    def do_POST(self) -> None:
        self._handle_request()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _handle_request(self) -> None:
        app = self.server.lotus_daemon
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        status, payload = app.dispatch(
            method=self.command,
            raw_path=self.path,
            authorization=self.headers.get("Authorization", ""),
            body=body,
        )
        encoded = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@dataclass(slots=True)
class LotusApiDaemon:
    state_path: Path
    host: str = "127.0.0.1"
    port: int = 8788
    grant_sweep_interval_seconds: float = 0.0
    _httpd: _LotusThreadingHTTPServer | None = field(default=None, init=False, repr=False)
    _thread: Thread | None = field(default=None, init=False, repr=False)
    _grant_sweep_thread: Thread | None = field(default=None, init=False, repr=False)
    _stop_event: Event = field(default_factory=Event, init=False, repr=False)
    _last_grant_sweep_summary: dict[str, object] | None = field(default=None, init=False, repr=False)
    _last_grant_sweep_error: dict[str, object] | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        if self._httpd is not None:
            return
        self._stop_event.clear()
        httpd = _LotusThreadingHTTPServer((self.host, self.port), _LotusRequestHandler)
        httpd.lotus_daemon = self  # type: ignore[attr-defined]
        self._httpd = httpd
        self._start_background_workers()

    def serve_forever(self) -> None:
        self.start()
        assert self._httpd is not None
        self._httpd.serve_forever()

    def start_in_thread(self) -> Thread:
        self.start()
        if self._thread is None or not self._thread.is_alive():
            assert self._httpd is not None
            self._thread = Thread(target=self._httpd.serve_forever, daemon=True)
            self._thread.start()
        return self._thread

    def shutdown(self) -> None:
        if self._httpd is None:
            return
        self._stop_event.set()
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._grant_sweep_thread is not None:
            self._grant_sweep_thread.join(timeout=2.0)
        self._httpd = None
        self._thread = None
        self._grant_sweep_thread = None

    @property
    def address(self) -> tuple[str, int]:
        self.start()
        assert self._httpd is not None
        host, port = self._httpd.server_address[:2]
        return str(host), int(port)

    @property
    def base_url(self) -> str:
        host, port = self.address
        return f"http://{host}:{port}"

    def _start_background_workers(self) -> None:
        if self.grant_sweep_interval_seconds <= 0:
            return
        if self._grant_sweep_thread is None or not self._grant_sweep_thread.is_alive():
            self._grant_sweep_thread = Thread(target=self._run_periodic_grant_sweep_loop, daemon=True)
            self._grant_sweep_thread.start()

    def _run_periodic_grant_sweep_once(self, current_time: float | None = None) -> dict[str, object]:
        summary = ControlPlaneStateStore(path=self.state_path).update(
            lambda plane: plane.sweep_expired_grants(current_time=current_time),
        )
        self._last_grant_sweep_summary = dict(summary)
        self._last_grant_sweep_error = None
        if summary["expired_space_claim_count"] or summary["expired_slot_lease_count"]:
            logger.info(
                "Lotus daemon expired grant sweep checked_at=%s claims=%s leases=%s",
                summary["checked_at"],
                summary["expired_space_claim_count"],
                summary["expired_slot_lease_count"],
            )
        return summary

    def _run_periodic_grant_sweep_loop(self) -> None:
        interval = float(self.grant_sweep_interval_seconds)
        while not self._stop_event.is_set():
            try:
                self._run_periodic_grant_sweep_once(current_time=time.time())
            except Exception:
                self._last_grant_sweep_error = {"error": "periodic_grant_sweep_failed", "at": time.time()}
                logger.exception("Lotus daemon periodic grant sweep failed")
            if self._stop_event.wait(interval):
                break

    def dispatch(self, *, method: str, raw_path: str, authorization: str, body: bytes) -> tuple[int, dict]:
        split = urlsplit(raw_path)
        path = split.path
        query = parse_qs(split.query, keep_blank_values=False)
        if method == "GET" and path == "/healthz":
            return 200, {
                "status": "ok",
                "state_path": str(self.state_path),
                "lotus_capabilities_path": "/v1/lotus/capabilities",
                "daemon": {
                    "grant_sweep": {
                        "enabled": self.grant_sweep_interval_seconds > 0,
                        "interval_seconds": self.grant_sweep_interval_seconds,
                        "worker_alive": bool(self._grant_sweep_thread and self._grant_sweep_thread.is_alive()),
                        "last_summary": self._last_grant_sweep_summary,
                        "last_error": self._last_grant_sweep_error,
                    },
                },
            }

        token = _extract_bearer_token(authorization)
        if not token:
            return 401, _error_payload("missing_bearer_token", error_kind="auth", recoverable=True, retryable=False)

        try:
            if method == "GET" and path == "/v1/lotus/state":
                return 200, self._call(token, "show_state", {})
            if method == "GET" and path == "/v1/lotus/steward-protocol":
                return 200, self._call(token, "show_steward_protocol", {})
            if method == "GET" and path == "/v1/lotus/capabilities":
                return 200, self._call(token, "lotus_capabilities", {"base_url": self.base_url})
            if method == "GET" and path == "/v1/lotus/operations":
                return 200, self._call(
                    token,
                    "list_operation_feed",
                    {
                        "limit": int(_query_param(query, "limit") or "50"),
                        "after_operation_id": _query_param(query, "after_operation_id"),
                        "action": _query_param(query, "action"),
                        "operator_subject": _query_param(query, "operator_subject"),
                    },
                )
            if method == "GET" and path == "/v1/lotus/operations/by-request":
                return 200, self._call(
                    token,
                    "show_operation_receipt",
                    {"action": _require_query_param(query, "action"), "request_id": _require_query_param(query, "request_id")},
                )
            if method == "GET" and path.startswith("/v1/lotus/operations/"):
                suffix = path.removeprefix("/v1/lotus/operations/")
                if not suffix or "/" in suffix:
                    return 404, _error_payload("not_found", error_kind="routing", recoverable=True, retryable=False, context={"path": path})
                return 200, self._call(token, "show_operation_receipt", {"operation_id": unquote(suffix)})
            if method == "GET" and path == "/v1/lotus/spaces":
                return 200, self._call(token, "list_spaces", {})
            if method == "GET" and path == "/v1/lotus/slots":
                return 200, self._call(token, "list_slots", {})
            if method == "GET" and path == "/v1/lotus/space-claims":
                return 200, self._call(token, "list_space_claims", {})
            if method == "GET" and path == "/v1/lotus/slot-leases":
                return 200, self._call(token, "list_slot_leases", {})
            if method == "GET" and path == "/v1/lotus/repo-roles":
                return 200, self._call(token, "list_repo_roles", {})
            if method == "GET" and path == "/v1/lotus/authority-exports":
                return 200, self._call(token, "list_authority_exports", {})
            if method == "GET" and path == "/v1/lotus/projection-bindings":
                return 200, self._call(token, "list_projection_bindings", {})
            if method == "GET" and path == "/v1/lotus/publication-statuses":
                return 200, self._call(token, "list_publication_statuses", {})
            if method == "GET" and path == "/v1/lotus/source-authority-feeds":
                return 200, self._call(token, "list_source_authority_feeds", {})
            if method == "GET" and path == "/v1/lotus/projection-reconcile-statuses":
                return 200, self._call(token, "list_projection_reconcile_statuses", {})
            if method == "GET" and path == "/v1/lotus/lineage":
                return 200, self._call(token, "list_fork_lineage", {})
            if method == "GET" and path == "/v1/lotus/intents":
                return 200, self._call(token, "list_intents", {})
            if method == "GET" and path.startswith("/v1/lotus/intents/"):
                suffix = path.removeprefix("/v1/lotus/intents/")
                if not suffix or "/" in suffix:
                    raise ValueError("invalid_intent_path")
                return 200, self._call(token, "get_intent", {"intent_id": unquote(suffix)})
            if method == "GET" and path == "/v1/lotus/assistant-snapshot":
                return 200, self._call(
                    token,
                    "assistant_snapshot",
                    {
                        "root": _require_query_param(query, "root"),
                        "city_id": _query_param(query, "city_id"),
                        "assistant_id": _query_param(query, "assistant_id") or "moltbook_assistant",
                        "heartbeat_source": _query_param(query, "heartbeat_source") or "steward-protocol/mahamantra",
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-manifest":
                return 200, self._call(
                    token,
                    "agent_web_manifest",
                    {
                        "root": _require_query_param(query, "root"),
                        "city_id": _query_param(query, "city_id"),
                        "assistant_id": _query_param(query, "assistant_id") or "moltbook_assistant",
                        "heartbeat_source": _query_param(query, "heartbeat_source") or "steward-protocol/mahamantra",
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-semantic-capabilities":
                return 200, self._call(
                    token,
                    "agent_web_semantic_capabilities",
                    {"base_url": self.base_url},
                )
            if method == "GET" and path == "/v1/lotus/agent-web-semantic-contracts":
                payload = {"base_url": self.base_url}
                capability_id = _query_param(query, "capability_id")
                if capability_id not in (None, ""):
                    payload["capability_id"] = capability_id
                contract_id = _query_param(query, "contract_id")
                if contract_id not in (None, ""):
                    payload["contract_id"] = contract_id
                version = _query_param(query, "version")
                if version not in (None, ""):
                    payload["version"] = version
                return 200, self._call(
                    token,
                    "agent_web_semantic_contracts",
                    payload,
                )
            if method == "GET" and path == "/v1/lotus/agent-web-repo-graph-capabilities":
                return 200, self._call(
                    token,
                    "agent_web_repo_graph_capabilities",
                    {"base_url": self.base_url},
                )
            if method == "GET" and path == "/v1/lotus/agent-web-repo-graph-contracts":
                payload = {"base_url": self.base_url}
                capability_id = _query_param(query, "capability_id")
                if capability_id not in (None, ""):
                    payload["capability_id"] = capability_id
                contract_id = _query_param(query, "contract_id")
                if contract_id not in (None, ""):
                    payload["contract_id"] = contract_id
                version = _query_param(query, "version")
                if version not in (None, ""):
                    payload["version"] = version
                return 200, self._call(
                    token,
                    "agent_web_repo_graph_contracts",
                    payload,
                )
            if method == "GET" and path == "/v1/lotus/agent-web-repo-graph":
                return 200, self._call(
                    token,
                    "agent_web_repo_graph_snapshot",
                    {
                        "root": _require_query_param(query, "root"),
                        "node_type": _query_param(query, "node_type"),
                        "domain": _query_param(query, "domain"),
                        "query": _query_param(query, "query"),
                        "limit": int(_query_param(query, "limit") or "25"),
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-repo-graph-neighbors":
                return 200, self._call(
                    token,
                    "agent_web_repo_graph_neighbors",
                    {
                        "root": _require_query_param(query, "root"),
                        "node_id": _require_query_param(query, "node_id"),
                        "relation": _query_param(query, "relation"),
                        "depth": int(_query_param(query, "depth") or "1"),
                        "limit": int(_query_param(query, "limit") or "25"),
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-repo-graph-context":
                return 200, self._call(
                    token,
                    "agent_web_repo_graph_context",
                    {
                        "root": _require_query_param(query, "root"),
                        "concept": _require_query_param(query, "concept"),
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-graph":
                return 200, self._call(
                    token,
                    "agent_web_graph",
                    {
                        "root": _require_query_param(query, "root"),
                        "city_id": _query_param(query, "city_id"),
                        "assistant_id": _query_param(query, "assistant_id") or "moltbook_assistant",
                        "heartbeat_source": _query_param(query, "heartbeat_source") or "steward-protocol/mahamantra",
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-index":
                return 200, self._call(
                    token,
                    "agent_web_index",
                    {
                        "root": _require_query_param(query, "root"),
                        "city_id": _query_param(query, "city_id"),
                        "assistant_id": _query_param(query, "assistant_id") or "moltbook_assistant",
                        "heartbeat_source": _query_param(query, "heartbeat_source") or "steward-protocol/mahamantra",
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-search":
                return 200, self._call(
                    token,
                    "agent_web_search",
                    {
                        "root": _require_query_param(query, "root"),
                        "city_id": _query_param(query, "city_id"),
                        "assistant_id": _query_param(query, "assistant_id") or "moltbook_assistant",
                        "heartbeat_source": _query_param(query, "heartbeat_source") or "steward-protocol/mahamantra",
                        "query": _require_query_param(query, "q"),
                        "limit": int(_query_param(query, "limit") or "10"),
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-crawl":
                return 200, self._call(
                    token,
                    "agent_web_crawl",
                    {
                        "roots": _require_query_params(query, "root"),
                        "assistant_id": _query_param(query, "assistant_id") or "moltbook_assistant",
                        "heartbeat_source": _query_param(query, "heartbeat_source") or "steward-protocol/mahamantra",
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-crawl-search":
                return 200, self._call(
                    token,
                    "agent_web_crawl_search",
                    {
                        "roots": _require_query_params(query, "root"),
                        "assistant_id": _query_param(query, "assistant_id") or "moltbook_assistant",
                        "heartbeat_source": _query_param(query, "heartbeat_source") or "steward-protocol/mahamantra",
                        "query": _require_query_param(query, "q"),
                        "limit": int(_query_param(query, "limit") or "10"),
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-source-registry":
                return 200, self._call(
                    token,
                    "agent_web_source_registry",
                    {
                        "registry_path": _query_param(query, "registry_path") or "data/control_plane/agent_web_source_registry.json",
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-crawl-registry":
                return 200, self._call(
                    token,
                    "agent_web_crawl_registry",
                    {
                        "registry_path": _query_param(query, "registry_path") or "data/control_plane/agent_web_source_registry.json",
                        "assistant_id": _query_param(query, "assistant_id") or "moltbook_assistant",
                        "heartbeat_source": _query_param(query, "heartbeat_source") or "steward-protocol/mahamantra",
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-crawl-registry-search":
                return 200, self._call(
                    token,
                    "agent_web_crawl_registry_search",
                    {
                        "registry_path": _query_param(query, "registry_path") or "data/control_plane/agent_web_source_registry.json",
                        "assistant_id": _query_param(query, "assistant_id") or "moltbook_assistant",
                        "heartbeat_source": _query_param(query, "heartbeat_source") or "steward-protocol/mahamantra",
                        "query": _require_query_param(query, "q"),
                        "limit": int(_query_param(query, "limit") or "10"),
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-federated-index":
                return 200, self._call(
                    token,
                    "agent_web_federated_index",
                    {
                        "index_path": _query_param(query, "index_path") or "data/control_plane/agent_web_federated_index.json",
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-semantic-neighbors":
                return 200, self._call(
                    token,
                    "agent_web_semantic_neighbors",
                    {
                        "index_path": _query_param(query, "index_path") or "data/control_plane/agent_web_federated_index.json",
                        "record_id": _require_query_param(query, "record_id"),
                        "limit": int(_query_param(query, "limit") or "5"),
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-federated-search":
                return 200, self._call(
                    token,
                    "agent_web_federated_search",
                    {
                        "index_path": _query_param(query, "index_path") or "data/control_plane/agent_web_federated_index.json",
                        "overlay_path": _query_param(query, "overlay_path") or "data/control_plane/agent_web_semantic_overlay.json",
                        "wordnet_path": _query_param(query, "wordnet_path"),
                        "query": _require_query_param(query, "q"),
                        "limit": int(_query_param(query, "limit") or "10"),
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-semantic-overlay":
                return 200, self._call(
                    token,
                    "agent_web_semantic_overlay",
                    {
                        "overlay_path": _query_param(query, "overlay_path") or "data/control_plane/agent_web_semantic_overlay.json",
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-semantic-expand":
                return 200, self._call(
                    token,
                    "agent_web_semantic_expand",
                    {
                        "overlay_path": _query_param(query, "overlay_path") or "data/control_plane/agent_web_semantic_overlay.json",
                        "wordnet_path": _query_param(query, "wordnet_path"),
                        "query": _require_query_param(query, "q"),
                    },
                )
            if method == "GET" and path == "/v1/lotus/agent-web-document":
                return 200, self._call(
                    token,
                    "agent_web_document",
                    {
                        "root": _require_query_param(query, "root"),
                        "city_id": _query_param(query, "city_id"),
                        "assistant_id": _query_param(query, "assistant_id") or "moltbook_assistant",
                        "heartbeat_source": _query_param(query, "heartbeat_source") or "steward-protocol/mahamantra",
                        "rel": _query_param(query, "rel") or "agent_web",
                        "href": _query_param(query, "href"),
                        "document_id": _query_param(query, "document_id"),
                    },
                )
            if method == "GET" and path.startswith("/v1/lotus/handles/"):
                return 200, self._call(
                    token,
                    "resolve_handle",
                    {"public_handle": unquote(path.removeprefix("/v1/lotus/handles/"))},
                )
            if method == "GET" and path.startswith("/v1/lotus/services/"):
                parts = path.removeprefix("/v1/lotus/services/").split("/", 1)
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    raise ValueError("invalid_service_path")
                return 200, self._call(
                    token,
                    "resolve_service",
                    {"city_id": unquote(parts[0]), "service_name": unquote(parts[1])},
                )
            if method == "GET" and path.startswith("/v1/lotus/routes/"):
                parts = path.removeprefix("/v1/lotus/routes/").split("/", 1)
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    raise ValueError("invalid_route_path")
                return 200, self._call(
                    token,
                    "resolve_next_hop",
                    {"source_city_id": unquote(parts[0]), "destination": unquote(parts[1])},
                )
            if method == "POST" and path == "/v1/lotus/call":
                request = _decode_json_object(body)
                return 200, self._call(token, str(request["action"]), dict(request.get("params", {})))
            if method == "POST" and path == "/v1/lotus/tokens":
                return 200, self._call(token, "issue_token", _decode_json_object(body))
            if method == "POST" and path == "/v1/lotus/authority-bundles/import":
                return 200, self._call(token, "import_authority_bundle", _decode_json_object(body))
            if method == "POST" and path == "/v1/lotus/projection-reconcile/run":
                return 200, self._call(token, "run_projection_reconcile_once", _decode_json_object(body))
            if method == "POST" and path == "/v1/lotus/grants/sweep-expired":
                return 200, self._call(token, "sweep_expired_grants", _decode_json_object(body))
            if method == "POST" and path == "/v1/lotus/preflight":
                return 200, self._call(token, "preflight_mutation", _decode_json_object(body))
            if method == "POST" and path.startswith("/v1/lotus/source-authority-feeds/"):
                suffix = path.removeprefix("/v1/lotus/source-authority-feeds/")
                parts = suffix.split("/", 1)
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    raise ValueError("invalid_source_authority_feed_path")
                enabled = {"pause": False, "resume": True}.get(parts[1])
                if enabled is None:
                    raise ValueError("invalid_source_authority_feed_action")
                return 200, self._call(token, "set_source_authority_feed_enabled", {"feed_id": unquote(parts[0]), "enabled": enabled})
            if method == "POST" and path == "/v1/lotus/intents":
                return 200, self._call(token, "create_intent", _decode_json_object(body))
            if method == "POST" and path.startswith("/v1/lotus/intents/"):
                suffix = path.removeprefix("/v1/lotus/intents/")
                parts = suffix.split("/", 1)
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    raise ValueError("invalid_intent_path")
                action = {
                    "accept": "accept_intent",
                    "reject": "reject_intent",
                    "fulfill": "fulfill_intent",
                    "cancel": "cancel_intent",
                }.get(parts[1])
                if action is None:
                    raise ValueError("invalid_intent_action")
                payload = _decode_json_object(body)
                payload["intent_id"] = unquote(parts[0])
                return 200, self._call(token, action, payload)
            if method == "POST" and path.startswith("/v1/lotus/space-claims/"):
                suffix = path.removeprefix("/v1/lotus/space-claims/")
                parts = suffix.split("/", 1)
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    raise ValueError("invalid_space_claim_path")
                action = {
                    "release": "release_space_claim",
                    "expire": "expire_space_claim",
                }.get(parts[1])
                if action is None:
                    raise ValueError("invalid_space_claim_action")
                payload = _decode_json_object(body)
                payload["claim_id"] = unquote(parts[0])
                return 200, self._call(token, action, payload)
            if method == "POST" and path.startswith("/v1/lotus/slot-leases/"):
                suffix = path.removeprefix("/v1/lotus/slot-leases/")
                parts = suffix.split("/", 1)
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    raise ValueError("invalid_slot_lease_path")
                action = {
                    "release": "release_slot_lease",
                    "expire": "expire_slot_lease",
                }.get(parts[1])
                if action is None:
                    raise ValueError("invalid_slot_lease_action")
                payload = _decode_json_object(body)
                payload["lease_id"] = unquote(parts[0])
                return 200, self._call(token, action, payload)
            if method == "POST" and path == "/v1/lotus/addresses/assign":
                return 200, self._call(token, "assign_addresses", _decode_json_object(body))
            if method == "POST" and path == "/v1/lotus/endpoints":
                return 200, self._call(token, "publish_endpoint", _decode_json_object(body))
            if method == "POST" and path == "/v1/lotus/services":
                return 200, self._call(token, "publish_service", _decode_json_object(body))
            if method == "POST" and path == "/v1/lotus/routes":
                return 200, self._call(token, "publish_route", _decode_json_object(body))
            if method == "POST" and path == "/v1/lotus/agent-web-federated-index/refresh":
                return 200, self._call(token, "refresh_agent_web_federated_index", _decode_json_object(body))
            if method == "POST" and path == "/v1/lotus/agent-web-semantic-overlay/refresh":
                return 200, self._call(token, "refresh_agent_web_semantic_overlay", _decode_json_object(body))
            return 404, _error_payload("not_found", error_kind="routing", recoverable=True, retryable=False, context={"path": path})
        except PermissionError as exc:
            message = str(exc)
            return (401 if message == "invalid_token" else 403), _error_payload(
                message,
                error_kind=("auth" if message == "invalid_token" else "authorization"),
                recoverable=True,
                retryable=False,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            message = str(exc)
            return (409 if message.startswith("idempotency_conflict:") else 404 if message.startswith("unknown_") else 400), _error_payload(
                message,
                error_kind=("conflict" if message.startswith("idempotency_conflict:") else "not_found" if message.startswith("unknown_") else "input"),
                recoverable=True,
                retryable=False,
            )
        except Exception:
            logger.exception("Lotus daemon request failed")
            return 500, _error_payload("internal_error", error_kind="internal", recoverable=False, retryable=True)

    def _call(self, bearer_token: str, action: str, params: dict) -> dict:
        store = ControlPlaneStateStore(path=self.state_path)
        if action == "run_projection_reconcile_once":
            plane = store.load()
            token = LotusControlPlaneAPI(plane).authenticate(bearer_token, required_scopes=(LotusApiScope.RECONCILE_WRITE.value,))
            result = ProjectionReconciler(root=Path(params["root"]), state_path=self.state_path).run_once(
                bundle_path=params.get("bundle_path"),
                feed_id=str(params.get("feed_id", "steward-authority-bundle")),
                poll_interval_seconds=int(params.get("poll_interval_seconds", 300)),
                wiki_repo_url=params.get("wiki_repo_url"),
                wiki_path=(None if params.get("wiki_path") in (None, "") else Path(str(params["wiki_path"]))),
                push=bool(params.get("push", False)),
                prune_generated=bool(params.get("prune_generated", False)),
                force=bool(params.get("force", False)),
            )
            return {"token_id": token.token_id, "projection_reconcile": result}
        if action in LOTUS_MUTATING_ACTIONS:
            return store.update(
                lambda plane: LotusControlPlaneAPI(plane).call(
                    bearer_token=bearer_token,
                    action=action,
                    params=params,
                ),
            )
        plane = store.load()
        return LotusControlPlaneAPI(plane).call(
            bearer_token=bearer_token,
            action=action,
            params=params,
        )


def _decode_json_object(body: bytes) -> dict:
    if not body:
        return {}
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("expected_json_object")
    return payload


def _extract_bearer_token(authorization: str) -> str:
    prefix = "Bearer "
    return authorization[len(prefix) :].strip() if authorization.startswith(prefix) else ""


def _error_payload(
    error_code: str,
    *,
    error_kind: str,
    recoverable: bool,
    retryable: bool,
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "error": error_code,
        "error_code": error_code,
        "error_kind": error_kind,
        "recoverable": recoverable,
        "retryable": retryable,
        "context": dict(context or {}),
    }


def _query_param(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    value = values[0]
    return value if value != "" else None


def _require_query_param(query: dict[str, list[str]], name: str) -> str:
    value = _query_param(query, name)
    if value is None:
        raise ValueError(f"missing_query_param:{name}")
    return value


def _require_query_params(query: dict[str, list[str]], name: str) -> list[str]:
    values = [value for value in query.get(name, []) if value != ""]
    if not values:
        raise ValueError(f"missing_query_param:{name}")
    return values