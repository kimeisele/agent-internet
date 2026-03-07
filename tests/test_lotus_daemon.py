import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from agent_internet.lotus_api import LotusControlPlaneAPI
from agent_internet.lotus_daemon import LotusApiDaemon
from agent_internet.models import LotusApiScope
from agent_internet.snapshot import ControlPlaneStateStore


def _request_json(base_url: str, path: str, *, method: str = "GET", token: str = "", payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(f"{base_url}{path}", data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_lotus_daemon_serves_authenticated_http_api(tmp_path):
    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    root_secret = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="root",
            scopes=(LotusApiScope.READ.value, LotusApiScope.SERVICE_WRITE.value, LotusApiScope.TOKEN_WRITE.value),
            token_secret="root-secret",
            token_id="tok-root",
        ).secret,
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()

    try:
        status, health = _request_json(daemon.base_url, "/healthz")
        assert status == 200
        assert health["status"] == "ok"

        status, issued = _request_json(
            daemon.base_url,
            "/v1/lotus/tokens",
            method="POST",
            token=root_secret,
            payload={
                "subject": "operator",
                "scopes": [LotusApiScope.READ.value, LotusApiScope.SERVICE_WRITE.value],
                "token_id": "tok-operator",
            },
        )
        assert status == 200
        operator_secret = issued["secret"]

        status, published = _request_json(
            daemon.base_url,
            "/v1/lotus/services",
            method="POST",
            token=operator_secret,
            payload={
                "city_id": "city-a",
                "service_name": "forum-api",
                "public_handle": "api.forum.city-a.lotus",
                "transport": "https",
                "location": "https://forum.city-a.example/api",
                "required_scopes": [LotusApiScope.READ.value],
            },
        )
        assert status == 200
        assert published["service_address"]["service_id"] == "city-a:forum-api"

        status, resolved = _request_json(
            daemon.base_url,
            "/v1/lotus/services/city-a/forum-api",
            token=operator_secret,
        )
        assert status == 200
        assert resolved["resolved"]["location"] == "https://forum.city-a.example/api"
    finally:
        daemon.shutdown()


def test_lotus_daemon_rejects_missing_auth(tmp_path):
    daemon = LotusApiDaemon(state_path=tmp_path / "state" / "control_plane.json", port=0)
    daemon.start_in_thread()

    try:
        with pytest.raises(HTTPError) as exc_info:
            _request_json(daemon.base_url, "/v1/lotus/state")
        assert exc_info.value.code == 401
        payload = json.loads(exc_info.value.read().decode("utf-8"))
        assert payload["error"] == "missing_bearer_token"
    finally:
        daemon.shutdown()