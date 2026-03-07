import json

from agent_internet.cli import main


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


def test_cli_show_state_prints_snapshot(tmp_path, capsys):
    state_path = tmp_path / "state" / "control_plane.json"

    assert main(["show-state", "--state-path", str(state_path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["identities"] == []
    assert payload["endpoints"] == []


def test_cli_init_dual_city_lab_and_send(tmp_path, capsys):
    root = tmp_path / "lab"

    assert main(["init-dual-city-lab", "--root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cities"][0]["city_id"] == "city-a"

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
