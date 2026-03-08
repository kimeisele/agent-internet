from agent_internet.agent_web_semantic_capabilities import build_agent_web_semantic_capability_manifest


def test_build_agent_web_semantic_capability_manifest():
    payload = build_agent_web_semantic_capability_manifest(base_url="https://agent.example")

    assert payload["kind"] == "agent_web_semantic_capability_manifest"
    assert payload["standard_profile"]["source_system"] == "agent_city"
    assert payload["standard_profile"]["provider_runtime"] == "agent_internet"
    assert payload["auth"]["required_scopes"] == ["lotus.read"]
    assert payload["contracts_discovery"]["collection_lotus_action"] == "agent_web_semantic_contracts"
    assert payload["contracts_discovery"]["detail_query_parameters"] == ["capability_id?", "contract_id?", "version?"]
    assert payload["capabilities"][0]["http"]["href"].startswith("https://agent.example/")
    assert payload["capabilities"][0]["lotus"]["action"] == "agent_web_federated_search"
    assert payload["capabilities"][0]["contract_descriptor"]["http"]["href"].startswith("https://agent.example/")
    assert payload["capabilities"][0]["contract_descriptor"]["contract_id"] == "semantic_federated_search.v1"