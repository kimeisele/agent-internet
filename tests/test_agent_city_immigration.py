from agent_internet.agent_city_immigration import AgentCityImmigrationAdapter


def test_agent_city_immigration_adapter_runs_real_service_flow(tmp_path):
    adapter = AgentCityImmigrationAdapter(tmp_path / "city-b")

    application = adapter.submit_application(
        "MIRA",
        reason="temporary_visitor",
        visa_class="worker",
    )
    visa = adapter.approve_and_grant(application.application_id)

    assert visa.agent_name == "MIRA"
    assert visa.visa_class.value == "worker"
    assert adapter.get_application(application.application_id).status.value == "citizenship_granted"
    assert adapter.stats()["total_applications"] == 1
