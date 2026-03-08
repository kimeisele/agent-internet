from agent_internet.agent_web_semantic_contracts import (
    build_agent_web_semantic_contract_manifest,
    read_agent_web_semantic_contract_descriptor,
)


def test_build_agent_web_semantic_contract_manifest():
    payload = build_agent_web_semantic_contract_manifest(base_url="https://agent.example")

    assert payload["kind"] == "agent_web_semantic_contract_manifest"
    assert payload["discovery"]["detail_query_parameters"] == ["capability_id?", "contract_id?", "version?"]
    assert payload["stats"]["descriptor_count"] == 3
    assert payload["descriptors"][0]["descriptor_transport"]["http"]["href"].startswith("https://agent.example/")


def test_read_agent_web_semantic_contract_descriptor():
    payload = read_agent_web_semantic_contract_descriptor(
        capability_id="semantic_neighbors",
        base_url="https://agent.example",
    )

    assert payload["kind"] == "agent_web_semantic_contract_descriptor"
    assert payload["contract_id"] == "semantic_neighbors.v1"
    assert payload["latest_for_capability"] is True
    assert payload["request_schema"]["required"] == ["record_id"]
    assert payload["transport"]["lotus"]["action"] == "agent_web_semantic_neighbors"


def test_read_agent_web_semantic_contract_descriptor_by_contract_id():
    payload = read_agent_web_semantic_contract_descriptor(
        contract_id="semantic_expand.v1",
        base_url="https://agent.example",
    )

    assert payload["kind"] == "agent_web_semantic_contract_descriptor"
    assert payload["capability_id"] == "semantic_expand"
    assert payload["version"] == 1