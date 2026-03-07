from agent_internet.local_lab import LocalDualCityLab


def test_local_lab_runs_cross_city_immigration_flow(tmp_path):
    lab = LocalDualCityLab.create(tmp_path / "lab")

    result = lab.run_immigration_flow(
        source_city_id="city-a",
        host_city_id="city-b",
        agent_name="MIRA",
        visa_class="worker",
        reason="temporary_visitor",
    )

    assert result["receipt"].status.value == "delivered"
    assert result["application"].status.value == "citizenship_granted"
    assert result["visa"].agent_name == "MIRA"
    assert result["visa"].visa_class.value == "worker"
