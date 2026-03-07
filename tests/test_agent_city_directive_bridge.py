from agent_internet.local_lab import LocalDualCityLab


def test_directive_bridge_registers_agent_and_acknowledges_file(tmp_path):
    lab = LocalDualCityLab.create(tmp_path / "lab")

    directive_id = lab.issue_directive(
        "city-a",
        directive_type="register_agent",
        params={"name": "MIRA"},
        directive_id="dir-register-mira",
    )

    result = lab.execute_directives("city-a")

    assert directive_id == "dir-register-mira"
    assert result.processed_count == 1
    assert result.acknowledged == ["dir-register-mira"]
    assert "directive:register_agent:True" in result.operations
    assert lab.read_directives("city-a") == []
    assert lab.read_agent("city-a", "MIRA") is not None
    done_files = list(lab.contract("city-a").directives_dir.glob("*.json.done"))
    assert len(done_files) == 1


def test_directive_bridge_can_freeze_existing_agent(tmp_path):
    lab = LocalDualCityLab.create(tmp_path / "lab")
    lab.issue_directive(
        "city-a",
        directive_type="register_agent",
        params={"name": "ARJUN"},
        directive_id="dir-register-arjun",
    )
    lab.execute_directives("city-a")

    lab.issue_directive(
        "city-a",
        directive_type="freeze_agent",
        params={"name": "ARJUN"},
        directive_id="dir-freeze-arjun",
    )

    result = lab.execute_directives("city-a")

    assert result.acknowledged == ["dir-freeze-arjun"]
    assert "directive:freeze_agent:True" in result.operations
    assert lab.read_agent("city-a", "ARJUN")["status"] == "frozen"