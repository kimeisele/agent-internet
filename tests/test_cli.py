import json
import subprocess

from agent_internet.cli import main


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_git_repo(tmp_path):
    repo_remote = tmp_path / "agent-city.git"
    wiki_remote = tmp_path / "agent-city.wiki.git"
    repo_root = tmp_path / "agent-city"
    _git(tmp_path, "init", "--bare", str(repo_remote))
    _git(tmp_path, "init", "--bare", str(wiki_remote))
    _git(tmp_path, "clone", str(repo_remote), str(repo_root))
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test User")
    (repo_root / "README.md").write_text("# agent city\n")
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-m", "init")
    _git(repo_root, "push", "origin", "HEAD")
    _git(repo_root, "remote", "set-url", "origin", "git@github.com:org/agent-city-cli.git")
    return repo_root, wiki_remote


def test_cli_onboards_agent_city_and_persists_state(tmp_path, capsys):
    repo_root = tmp_path / "agent-city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_8.json").write_text(
        json.dumps(
            {
                "heartbeat": 8,
                "timestamp": 8.0,
                "population": 3,
                "alive": 3,
                "dead": 0,
                "chain_valid": True,
            },
        ),
    )
    state_path = tmp_path / "state" / "control_plane.json"

    exit_code = main(
        [
            "onboard-agent-city",
            "--root",
            str(repo_root),
            "--city-id",
            "city-a",
            "--repo",
            "org/agent-city-a",
            "--state-path",
            str(state_path),
            "--capability",
            "federation",
        ],
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["city_id"] == "city-a"
    assert payload["observed"]["health"] == "healthy"
    assert state_path.exists()


def test_cli_publishes_and_discovers_agent_city_peer(tmp_path, capsys):
    repo_root = tmp_path / "agent-city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_5.json").write_text(
        json.dumps(
            {
                "heartbeat": 5,
                "timestamp": 5.0,
                "population": 2,
                "alive": 2,
                "dead": 0,
                "chain_valid": True,
            },
        ),
    )
    state_path = tmp_path / "state" / "control_plane.json"

    assert main(
        [
            "publish-agent-city-peer",
            "--root",
            str(repo_root),
            "--city-id",
            "city-z",
            "--repo",
            "org/agent-city-z",
            "--capability",
            "federation",
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["peer"]["identity"]["city_id"] == "city-z"

    assert main(
        [
            "onboard-agent-city",
            "--root",
            str(repo_root),
            "--discover",
            "--state-path",
            str(state_path),
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["city_id"] == "city-z"
    assert payload["discovered"] is True
    assert payload["observed"]["health"] == "healthy"


def test_cli_git_federation_describe_and_sync_wiki(tmp_path, capsys):
    repo_root, wiki_remote = _init_git_repo(tmp_path)
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_2.json").write_text(
        json.dumps({"heartbeat": 2, "timestamp": 2.0, "population": 1, "alive": 1, "dead": 0, "chain_valid": True}),
    )
    state_path = tmp_path / "state" / "control_plane.json"

    assert main(["git-federation-describe", "--root", str(repo_root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["repo_ref"] == "org/agent-city-cli"

    assert main(
        [
            "publish-agent-city-peer",
            "--root",
            str(repo_root),
            "--city-id",
            "city-cli",
        ],
    ) == 0
    _ = capsys.readouterr().out

    assert main(
        [
            "onboard-agent-city",
            "--root",
            str(repo_root),
            "--discover",
            "--state-path",
            str(state_path),
        ],
    ) == 0
    _ = capsys.readouterr().out

    assert main(
        [
            "git-federation-sync-wiki",
            "--root",
            str(repo_root),
            "--state-path",
            str(state_path),
            "--wiki-repo-url",
            str(wiki_remote),
            "--wiki-checkout-path",
            str(tmp_path / "wiki-checkout"),
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is True
    assert "Home.md" in payload["pages"]


def test_cli_show_state_prints_snapshot(tmp_path, capsys):
    state_path = tmp_path / "state" / "control_plane.json"

    assert main(["show-state", "--state-path", str(state_path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["identities"] == []
    assert payload["endpoints"] == []
    assert payload["hosted_endpoints"] == []
    assert payload["routes"] == []
    assert payload["service_addresses"] == []


def test_cli_init_dual_city_lab_and_send(tmp_path, capsys):
    root = tmp_path / "lab"

    assert main(["init-dual-city-lab", "--root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cities"][0]["city_id"] == "city-a"
    assert payload["cities"][0]["lotus_addresses"]["link"]["mac_address"].startswith("02:00:")

    assert main(
        [
            "lab-send",
            "--root",
            str(root),
            "--source-city-id",
            "city-a",
            "--target-city-id",
            "city-b",
            "--operation",
            "sync",
            "--payload-json",
            '{"heartbeat": 5}',
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["receipt"]["status"] == "delivered"
    assert payload["target_inbox"][0]["payload"] == {"heartbeat": 5}


def test_cli_lab_immigrate_runs_real_immigration_flow(tmp_path, capsys):
    root = tmp_path / "lab"

    assert main(
        [
            "lab-immigrate",
            "--root",
            str(root),
            "--source-city-id",
            "city-a",
            "--host-city-id",
            "city-b",
            "--agent-name",
            "MIRA",
            "--visa-class",
            "worker",
        ],
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["receipt"]["status"] == "delivered"
    assert payload["application"]["status"] == "citizenship_granted"
    assert payload["visa"]["visa_class"] == "worker"


def test_cli_lotus_assign_publish_and_resolve(tmp_path, capsys):
    state_path = tmp_path / "state" / "control_plane.json"

    assert main(["lotus-assign-addresses", "--state-path", str(state_path), "--city-id", "city-a"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["link_address"]["mac_address"].startswith("02:00:")
    assert payload["network_address"]["ip_address"].startswith("fd10:")

    assert main(
        [
            "lotus-publish-endpoint",
            "--state-path",
            str(state_path),
            "--city-id",
            "city-a",
            "--public-handle",
            "forum.city-a.lotus",
            "--transport",
            "https",
            "--location",
            "https://forum.city-a.example",
            "--visibility",
            "federated",
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hosted_endpoint"]["public_handle"] == "forum.city-a.lotus"
    assert payload["hosted_endpoint"]["visibility"] == "federated"

    assert main(["lotus-resolve-handle", "--state-path", str(state_path), "--public-handle", "forum.city-a.lotus"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["resolved"]["location"] == "https://forum.city-a.example"


def test_cli_lotus_issue_token_publish_service_and_api_call(tmp_path, capsys):
    state_path = tmp_path / "state" / "control_plane.json"

    assert main(
        [
            "lotus-issue-token",
            "--state-path",
            str(state_path),
            "--subject",
            "operator",
            "--token-id",
            "tok-cli",
            "--scope",
            "lotus.read",
            "--scope",
            "lotus.write.service",
        ],
    ) == 0
    issued = json.loads(capsys.readouterr().out)
    token = issued["secret"]

    assert main(
        [
            "lotus-api-call",
            "--state-path",
            str(state_path),
            "--token",
            token,
            "--action",
            "publish_service",
            "--params-json",
            '{"city_id":"city-a","service_name":"forum-api","public_handle":"api.forum.city-a.lotus","transport":"https","location":"https://forum.city-a.example/api","required_scopes":["lotus.read"]}',
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["service_address"]["service_id"] == "city-a:forum-api"

    assert main(
        [
            "lotus-api-call",
            "--state-path",
            str(state_path),
            "--token",
            token,
            "--action",
            "resolve_service",
            "--params-json",
            '{"city_id":"city-a","service_name":"forum-api"}',
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["resolved"]["location"] == "https://forum.city-a.example/api"


def test_cli_lotus_show_steward_protocol(capsys):
    assert main(["lotus-show-steward-protocol"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["default_route_nadi_type"] == "vyana"
    assert payload["default_timeout_ms"] > 0


def test_cli_lotus_publish_route_and_resolve_next_hop(tmp_path, capsys):
    repo_root = tmp_path / "city-b"
    state_path = tmp_path / "state" / "control_plane.json"

    assert main(
        [
            "onboard-agent-city",
            "--root",
            str(repo_root),
            "--city-id",
            "city-b",
            "--repo",
            "org/city-b",
            "--state-path",
            str(state_path),
        ],
    ) == 0
    _ = capsys.readouterr().out

    assert main(
        [
            "lotus-publish-route",
            "--state-path",
            str(state_path),
            "--owner-city-id",
            "city-a",
            "--destination-prefix",
            "service:city-z/forum",
            "--target-city-id",
            "city-z",
            "--next-hop-city-id",
            "city-b",
            "--metric",
            "5",
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["route"]["nadi_type"] == "vyana"

    assert main(
        [
            "lotus-resolve-next-hop",
            "--state-path",
            str(state_path),
            "--source-city-id",
            "agent-internet",
            "--destination",
            "service:city-z/forum-api",
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["resolved"]["next_hop_city_id"] == "city-b"


def test_cli_emit_and_pump_outbox(tmp_path, capsys):
    root = tmp_path / "lab"

    assert main(
        [
            "lab-emit-outbox",
            "--root",
            str(root),
            "--source-city-id",
            "city-a",
            "--target-city-id",
            "city-b",
            "--operation",
            "sync",
            "--payload-json",
            '{"heartbeat": 11}',
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["appended"] == 1
    assert payload["source_outbox"][0]["payload"] == {"heartbeat": 11}

    assert main(
        [
            "lab-pump-outbox",
            "--root",
            str(root),
            "--source-city-id",
            "city-a",
            "--drain-delivered",
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["receipts"][0]["status"] == "delivered"
    assert payload["remaining_outbox"] == []
    assert payload["target_receipts"][0]["target_city_id"] == "city-b"


def test_cli_lab_sync_runs_bounded_bidirectional_cycles(tmp_path, capsys):
    root = tmp_path / "lab"

    assert main(
        [
            "lab-emit-outbox",
            "--root",
            str(root),
            "--source-city-id",
            "city-a",
            "--target-city-id",
            "city-b",
            "--operation",
            "sync-a",
            "--payload-json",
            '{"from": "a"}',
            "--correlation-id",
            "env-a",
        ],
    ) == 0
    _ = capsys.readouterr().out

    assert main(
        [
            "lab-emit-outbox",
            "--root",
            str(root),
            "--source-city-id",
            "city-b",
            "--target-city-id",
            "city-a",
            "--operation",
            "sync-b",
            "--payload-json",
            '{"from": "b"}',
            "--correlation-id",
            "env-b",
        ],
    ) == 0
    _ = capsys.readouterr().out

    assert main(["lab-sync", "--root", str(root), "--cycles", "2", "--drain-delivered"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cycles"][0]["total_receipts"] == 2
    assert payload["cycles"][1]["total_receipts"] == 0
    assert payload["outboxes"]["city-a"] == []
    assert payload["outboxes"]["city-b"] == []


def test_cli_compacts_receipts(tmp_path, capsys):
    root = tmp_path / "lab"

    assert main(
        [
            "lab-emit-outbox",
            "--root",
            str(root),
            "--source-city-id",
            "city-a",
            "--target-city-id",
            "city-b",
            "--operation",
            "sync",
            "--payload-json",
            '{"n": 1}',
            "--correlation-id",
            "env-1",
        ],
    ) == 0
    _ = capsys.readouterr().out
    assert main(["lab-pump-outbox", "--root", str(root), "--source-city-id", "city-a", "--drain-delivered"]) == 0
    _ = capsys.readouterr().out

    assert main(
        [
            "lab-emit-outbox",
            "--root",
            str(root),
            "--source-city-id",
            "city-a",
            "--target-city-id",
            "city-b",
            "--operation",
            "sync",
            "--payload-json",
            '{"n": 2}',
            "--correlation-id",
            "env-2",
        ],
    ) == 0
    _ = capsys.readouterr().out
    assert main(["lab-pump-outbox", "--root", str(root), "--source-city-id", "city-a", "--drain-delivered"]) == 0
    _ = capsys.readouterr().out

    assert main(["lab-compact-receipts", "--root", str(root), "--city-id", "city-b", "--max-entries", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == 1
    assert len(payload["remaining_receipts"]) == 1


def test_cli_issue_and_run_directives_executes_real_agent_city_hook(tmp_path, capsys):
    root = tmp_path / "lab"

    assert main(
        [
            "lab-issue-directive",
            "--root",
            str(root),
            "--city-id",
            "city-a",
            "--directive-type",
            "register_agent",
            "--params-json",
            '{"name": "MIRA"}',
            "--directive-id",
            "dir-mira",
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["directive_id"] == "dir-mira"
    assert payload["pending_directives"][0]["directive_type"] == "register_agent"

    assert main(
        [
            "lab-run-directives",
            "--root",
            str(root),
            "--city-id",
            "city-a",
            "--agent-name",
            "MIRA",
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["acknowledged"] == ["dir-mira"]
    assert payload["agent"]["name"] == "MIRA"
    assert payload["pending_directives"] == []


def test_cli_lab_phase_tick_runs_real_cycle_with_ingress_and_council(tmp_path, capsys):
    root = tmp_path / "lab"

    assert main(
        [
            "lab-issue-directive",
            "--root",
            str(root),
            "--city-id",
            "city-a",
            "--directive-type",
            "register_agent",
            "--params-json",
            '{"name": "MIRA"}',
            "--directive-id",
            "dir-mira",
        ],
    ) == 0
    _ = capsys.readouterr().out

    assert main(
        [
            "lab-phase-tick",
            "--root",
            str(root),
            "--city-id",
            "city-a",
            "--cycles",
            "3",
            "--ingress-source",
            "operator",
            "--ingress-text",
            "hello city",
            "--agent-name",
            "MIRA",
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [heartbeat["department"] for heartbeat in payload["heartbeats"]] == ["GENESIS", "DHARMA", "KARMA"]
    assert payload["queued_ingress_before"] == 1
    assert payload["queued_ingress_after"] == 0
    assert payload["council_state"]["elected_mayor"] == "MIRA"
    assert payload["agent"]["name"] == "MIRA"
    assert isinstance(payload["mission_results"], list)


def test_cli_lab_execute_code_runs_real_exec_mission_path(tmp_path, capsys):
    root = tmp_path / "lab"

    assert main(
        [
            "lab-execute-code",
            "--root",
            str(root),
            "--city-id",
            "city-a",
            "--contract",
            "tests_pass",
            "--directive-id",
            "dir-exec",
            "--cycles",
            "3",
        ],
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["directive_id"] == "dir-exec"
    assert payload["pending_directives"] == []
    assert any(op == "exec_mission:exec_dir-exec_0:pending" for op in payload["exec_operations"])
    assert payload["target_missions"][0]["id"] == "exec_dir-exec_0"
    assert payload["target_missions"][0]["status"] == "active"
