from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_internet.agent_web_repo_graph import (
    build_agent_web_repo_graph_snapshot,
    read_agent_web_repo_graph_context,
    read_agent_web_repo_graph_neighbors,
)
from agent_internet.agent_web_repo_graph_capabilities import build_agent_web_repo_graph_capability_manifest
from agent_internet.agent_web_repo_graph_contracts import build_agent_web_repo_graph_contract_manifest, read_agent_web_repo_graph_contract_descriptor


class _FakeGraph:
    def __init__(self) -> None:
        self.nodes = {
            "module.city": _node("module.city", "module", "city", "core"),
            "function.city.tick": _node("function.city.tick", "function", "tick", "core"),
            "doc.city": _node("doc.city", "doc", "City Overview", "docs"),
        }
        self.edges = {
            "module.city": [_edge("module.city", "function.city.tick", "defines")],
            "function.city.tick": [_edge("function.city.tick", "doc.city", "documents")],
        }
        self.constraints = {"c1": _constraint("c1")}
        self.metrics = {"module.city": {"authority": _metric("module.city", "authority", 9)}}

    def search_nodes(self, query: str):
        needle = query.lower()
        return [node for node in self.nodes.values() if needle in node.name.lower() or needle in node.description.lower()]

    def get_node(self, node_id: str):
        return self.nodes.get(node_id)

    def compile_prompt_context(self, concept: str) -> str:
        return f"context::{concept}"


def _node(node_id: str, node_type: str, name: str, domain: str):
    return SimpleNamespace(id=node_id, type=SimpleNamespace(value=node_type), name=name, domain=domain, description=f"desc:{name}", properties={"rank": 1})


def _edge(source: str, target: str, relation: str):
    return SimpleNamespace(source=source, target=target, relation=SimpleNamespace(value=relation), weight=1.0, properties={})


def _constraint(constraint_id: str):
    return SimpleNamespace(id=constraint_id, type=SimpleNamespace(value="hard"), condition="x", action=SimpleNamespace(value="block"), message="nope", applies_to=["*"])


def _metric(node_id: str, metric_type: str, value: float):
    return SimpleNamespace(node_id=node_id, metric_type=SimpleNamespace(value=metric_type), value=value, scale_min=0, scale_max=10)


def test_repo_graph_capabilities_manifest_has_expected_surface():
    manifest = build_agent_web_repo_graph_capability_manifest(base_url="https://agent.example")

    assert manifest["kind"] == "agent_web_repo_graph_capability_manifest"
    assert manifest["standard_profile"]["profile_id"] == "agent_web_repo_graph_read_standard.v1"
    assert [item["capability_id"] for item in manifest["capabilities"]] == [
        "repo_graph_snapshot",
        "repo_graph_neighbors",
        "repo_graph_context",
    ]
    assert manifest["capabilities"][0]["http"]["href"].startswith("https://agent.example/")


def test_repo_graph_contract_manifest_and_descriptor_selection():
    manifest = build_agent_web_repo_graph_contract_manifest(base_url="https://agent.example")

    assert manifest["kind"] == "agent_web_repo_graph_contract_manifest"
    assert manifest["descriptors"][0]["contract_id"] == "repo_graph_snapshot.v1"

    descriptor = read_agent_web_repo_graph_contract_descriptor(contract_id="repo_graph_neighbors.v1", base_url="https://agent.example")
    assert descriptor["capability_id"] == "repo_graph_neighbors"
    assert descriptor["transport"]["http"]["href"] == "https://agent.example/v1/lotus/agent-web-repo-graph-neighbors"


def test_repo_graph_snapshot_neighbors_and_context(monkeypatch, tmp_path):
    root = tmp_path / "steward-protocol"
    root.mkdir()
    graph = _FakeGraph()
    monkeypatch.setattr("agent_internet.agent_web_repo_graph._load_repo_graph", lambda repo_root: (graph, "test_fixture"))

    snapshot = build_agent_web_repo_graph_snapshot(root, node_type="module", limit=5)
    assert snapshot["kind"] == "agent_web_repo_graph_snapshot"
    assert snapshot["summary"]["node_count"] == 3
    assert snapshot["nodes"][0]["node_id"] == "module.city"
    assert snapshot["source"]["repo_name"] == "steward-protocol"

    neighbors = read_agent_web_repo_graph_neighbors(root, node_id="module.city", depth=2, limit=5)
    assert neighbors["record"]["node_id"] == "module.city"
    assert {item["node_id"] for item in neighbors["neighbors"]} == {"function.city.tick", "doc.city"}

    context = read_agent_web_repo_graph_context(root, concept="heartbeat")
    assert context["context"] == "context::heartbeat"


def test_repo_graph_snapshot_rejects_unknown_node_type(monkeypatch, tmp_path):
    root = tmp_path / "steward-protocol"
    root.mkdir()
    monkeypatch.setattr("agent_internet.agent_web_repo_graph._load_repo_graph", lambda repo_root: (_FakeGraph(), "test_fixture"))

    with pytest.raises(ValueError, match="unknown_node_type"):
        build_agent_web_repo_graph_snapshot(root, node_type="alien")


def test_repo_graph_context_falls_back_to_search_matches(monkeypatch, tmp_path):
    root = tmp_path / "steward-protocol"
    root.mkdir()
    graph = _FakeGraph()
    graph.compile_prompt_context = lambda concept: ""
    monkeypatch.setattr("agent_internet.agent_web_repo_graph._load_repo_graph", lambda repo_root: (graph, "test_fixture"))

    payload = read_agent_web_repo_graph_context(root, concept="city")

    assert "Repository graph matches" in payload["context"]
    assert "module.city" in payload["context"]