from agent_internet.local_lab import LocalDualCityLab


def test_phase_tick_bridge_processes_directive_and_elects_council(tmp_path):
    lab = LocalDualCityLab.create(tmp_path / "lab")
    lab.issue_directive(
        "city-a",
        directive_type="register_agent",
        params={"name": "MIRA"},
        directive_id="dir-mira",
    )

    result = lab.run_phase_ticks("city-a", cycles=2)

    assert [heartbeat["department"] for heartbeat in result.heartbeats] == ["GENESIS", "DHARMA"]
    assert result.pending_directives == []
    assert "council" in result.registry_services
    assert "federation" in result.registry_services
    assert result.council_state is not None
    assert result.council_state["elected_mayor"] == "MIRA"
    assert lab.read_agent("city-a", "MIRA")["name"] == "MIRA"


def test_phase_tick_bridge_drains_ingress_within_same_runtime(tmp_path):
    lab = LocalDualCityLab.create(tmp_path / "lab")

    result = lab.run_phase_ticks(
        "city-a",
        cycles=3,
        ingress_items=[{"source": "operator", "text": "hello city", "conversation_id": "conv-1"}],
    )

    assert [heartbeat["department"] for heartbeat in result.heartbeats] == ["GENESIS", "DHARMA", "KARMA"]
    assert result.queued_ingress_before == 1
    assert result.queued_ingress_after == 0