from agent_internet.local_lab import LocalDualCityLab


def test_mission_bridge_drives_execute_code_directive_into_karma(tmp_path):
    lab = LocalDualCityLab.create(tmp_path / "lab")

    result = lab.run_execute_code_mission(
        "city-a",
        contract="tests_pass",
        directive_id="dir-exec",
        cycles=3,
    )

    assert result.directive_id == "dir-exec"
    assert [heartbeat["department"] for heartbeat in result.phase_tick.heartbeats] == ["GENESIS", "DHARMA", "KARMA"]
    assert result.phase_tick.pending_directives == []
    assert any(operation == "exec_mission:exec_dir-exec_0:pending" for operation in result.exec_operations)
    assert result.target_missions[0]["id"] == "exec_dir-exec_0"
    assert result.target_missions[0]["name"] == "Execute: tests_pass"
    assert result.target_missions[0]["status"] == "active"


def test_phase_tick_bridge_exposes_mission_results(tmp_path):
    lab = LocalDualCityLab.create(tmp_path / "lab")
    lab.run_execute_code_mission("city-a", contract="tests_pass", directive_id="dir-exec", cycles=3)

    phase_tick = lab.run_phase_ticks("city-a", cycles=1)

    assert any(mission["id"] == "exec_dir-exec_0" for mission in phase_tick.mission_results)