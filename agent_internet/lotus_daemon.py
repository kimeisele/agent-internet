from __future__ import annotations

import json
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, unquote, urlsplit

from .lotus_api import LOTUS_MUTATING_ACTIONS, LotusControlPlaneAPI
from .snapshot import ControlPlaneStateStore


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
    _httpd: _LotusThreadingHTTPServer | None = field(default=None, init=False, repr=False)
    _thread: Thread | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        if self._httpd is not None:
            return
        httpd = _LotusThreadingHTTPServer((self.host, self.port), _LotusRequestHandler)
        httpd.lotus_daemon = self  # type: ignore[attr-defined]
        self._httpd = httpd

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
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._httpd = None
        self._thread = None

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

    def dispatch(self, *, method: str, raw_path: str, authorization: str, body: bytes) -> tuple[int, dict]:
        split = urlsplit(raw_path)
        path = split.path
        query = parse_qs(split.query, keep_blank_values=False)
        if method == "GET" and path == "/healthz":
            return 200, {"status": "ok", "state_path": str(self.state_path)}

        token = _extract_bearer_token(authorization)
        if not token:
            return 401, {"error": "missing_bearer_token"}

        try:
            if method == "GET" and path == "/v1/lotus/state":
                return 200, self._call(token, "show_state", {})
            if method == "GET" and path == "/v1/lotus/steward-protocol":
                return 200, self._call(token, "show_steward_protocol", {})
            if method == "GET" and path == "/v1/lotus/spaces":
                return 200, self._call(token, "list_spaces", {})
            if method == "GET" and path == "/v1/lotus/slots":
                return 200, self._call(token, "list_slots", {})
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
            if method == "POST" and path == "/v1/lotus/addresses/assign":
                return 200, self._call(token, "assign_addresses", _decode_json_object(body))
            if method == "POST" and path == "/v1/lotus/endpoints":
                return 200, self._call(token, "publish_endpoint", _decode_json_object(body))
            if method == "POST" and path == "/v1/lotus/services":
                return 200, self._call(token, "publish_service", _decode_json_object(body))
            if method == "POST" and path == "/v1/lotus/routes":
                return 200, self._call(token, "publish_route", _decode_json_object(body))
            return 404, {"error": "not_found", "path": path}
        except PermissionError as exc:
            message = str(exc)
            return (401 if message == "invalid_token" else 403), {"error": message}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            message = str(exc)
            return (404 if message.startswith("unknown_intent:") else 400), {"error": message}

    def _call(self, bearer_token: str, action: str, params: dict) -> dict:
        store = ControlPlaneStateStore(path=self.state_path)
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