from agent_internet.agent_web_semantic_capabilities import build_agent_web_semantic_capability_manifest


def test_build_agent_web_semantic_capability_manifest():
    payload = build_agent_web_semantic_capability_manifest(base_url="https://agent.example")

    assert payload["kind"] == "agent_web_semantic_capability_manifest"
    assert payload["auth"]["required_scopes"] == ["lotus.read"]
    assert payload["capabilities"][0]["http"]["href"].startswith("https://agent.example/")
    assert payload["capabilities"][0]["lotus"]["action"] == "agent_web_federated_search"