import json

from agent_internet.agent_web_semantic_consumer import bootstrap_agent_web_semantic_consumer
from agent_internet.cli import main
from agent_internet.lotus_api import LotusControlPlaneAPI
from agent_internet.lotus_daemon import LotusApiDaemon
from agent_internet.models import LotusApiScope
from agent_internet.snapshot import ControlPlaneStateStore


def test_bootstrap_agent_web_semantic_consumer_over_http(tmp_path):
    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    token = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="bootstrap-consumer",
            scopes=(LotusApiScope.READ.value,),
            token_secret="bootstrap-secret",
            token_id="tok-bootstrap",
        ).secret,
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()

    try:
        payload = bootstrap_agent_web_semantic_consumer(
            base_url=daemon.base_url,
            bearer_token=token,
            capability_id="semantic_federated_search",
            transport="http",
        )
        assert payload["kind"] == "agent_web_semantic_consumer_bootstrap"
        assert payload["selector"]["contract_id"] == "semantic_federated_search.v1"
        assert payload["invocation_plan"]["transport_kind"] == "http"
        assert payload["invocation_plan"]["http"]["path"] == "/v1/lotus/agent-web-federated-search"
        assert any(binding["name"] == "query" and binding["transport_name"] == "q" for binding in payload["invocation_plan"]["input_bindings"])
    finally:
        daemon.shutdown()


def test_cli_agent_web_semantic_bootstrap(tmp_path, capsys):
    store = ControlPlaneStateStore(path=tmp_path / "state" / "control_plane.json")
    token = store.update(
        lambda plane: LotusControlPlaneAPI(plane).issue_token(
            subject="bootstrap-consumer",
            scopes=(LotusApiScope.READ.value,),
            token_secret="bootstrap-secret",
            token_id="tok-bootstrap",
        ).secret,
    )
    daemon = LotusApiDaemon(state_path=store.path, port=0)
    daemon.start_in_thread()

    try:
        assert main([
            "agent-web-semantic-bootstrap",
            "--base-url",
            daemon.base_url,
            "--token",
            token,
            "--contract-id",
            "semantic_neighbors.v1",
            "--transport",
            "cli",
        ]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["capability"]["capability_id"] == "semantic_neighbors"
        assert payload["invocation_plan"]["transport_kind"] == "cli"
        assert payload["invocation_plan"]["cli"]["command"] == "agent-web-semantic-neighbors"
    finally:
        daemon.shutdown()