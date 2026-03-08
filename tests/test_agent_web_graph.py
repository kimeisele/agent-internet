import json

from agent_internet.agent_web_graph import build_agent_web_public_graph, build_agent_web_public_graph_from_repo_root


def test_build_agent_web_public_graph_from_manifest():
    manifest = {
        "identity": {"city_id": "city-web", "slug": "web", "repo": "org/city-web"},
        "assistant": {"assistant_id": "moltbook_assistant", "assistant_kind": "moltbook_assistant", "city_health": "healthy"},
        "documents": [
            {"document_id": "agent_web", "kind": "manifest", "title": "Agent Web", "href": "Agent-Web.md", "entrypoint": True},
            {"document_id": "public_graph", "kind": "public_graph", "title": "Public Graph", "href": "Public-Graph.md", "entrypoint": True},
            {"document_id": "assistant_surface", "kind": "assistant_surface", "title": "Assistant Surface", "href": "Assistant-Surface.md", "entrypoint": True},
        ],
        "campaigns": [{"id": "internet-adaptation", "title": "Internet adaptation", "status": "active"}],
        "spaces": [{"space_id": "space:city-web:moltbook_assistant", "display_name": "moltbook_assistant", "kind": "assistant"}],
        "slots": [{"slot_id": "slot:city-web:assistant-social", "space_id": "space:city-web:moltbook_assistant", "slot_kind": "assistant_social", "status": "active"}],
        "service_affordances": [{"service_id": "city-web:forum", "transport": "https", "href": "https://forum.city-web.lotus", "auth_required": False}],
        "route_affordances": [{"destination_prefix": "city-z/", "next_hop_city_id": "city-z", "nadi_type": "pingala", "priority": "rajas"}],
        "links": [
            {"rel": "agent_web", "href": "Agent-Web.md", "kind": "document", "document_id": "agent_web"},
            {"rel": "public_graph", "href": "Public-Graph.md", "kind": "document", "document_id": "public_graph"},
            {"rel": "assistant_surface", "href": "Assistant-Surface.md", "kind": "document", "document_id": "assistant_surface"},
        ],
    }

    graph = build_agent_web_public_graph(manifest)

    assert graph["kind"] == "agent_web_public_graph"
    assert graph["root_node_id"] == "city:city-web"
    assert any(node["node_id"] == "campaign:city-web:internet-adaptation" for node in graph["nodes"])
    assert any(edge["kind"] == "focuses_on" for edge in graph["edges"])
    assert any(edge["kind"] == "offers_service" for edge in graph["edges"])
    assert graph["stats"]["node_count"] >= 6


def test_build_agent_web_public_graph_from_repo_root(tmp_path):
    repo_root = tmp_path / "city"
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_2.json").write_text(
        json.dumps(
            {
                "heartbeat": 2,
                "timestamp": 20.0,
                "population": 1,
                "alive": 1,
                "dead": 0,
                "chain_valid": True,
                "active_campaigns": [{"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]}],
            },
        ),
    )
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 1}}))
    (repo_root / "data" / "federation" / "peer.json").write_text(
        json.dumps({"identity": {"city_id": "city-web", "slug": "web", "repo": "org/city-web"}, "capabilities": ["moltbook"]}),
    )
    graph = build_agent_web_public_graph_from_repo_root(
        repo_root,
        state_snapshot={
            "spaces": [{"space_id": "space:city-web:moltbook_assistant", "city_id": "city-web", "display_name": "moltbook_assistant", "kind": "assistant"}],
            "slots": [{"slot_id": "slot:city-web:assistant-social", "space_id": "space:city-web:moltbook_assistant", "slot_kind": "assistant_social", "status": "active"}],
            "service_addresses": [],
            "routes": [],
            "fork_lineage": [],
        },
    )

    assert graph["city_id"] == "city-web"
    assert any(node["kind"] == "document" and node["node_id"] == "document:public_graph" for node in graph["nodes"])