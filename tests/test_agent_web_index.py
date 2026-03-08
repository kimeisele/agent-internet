import json

from agent_internet.agent_web_graph import build_agent_web_public_graph
from agent_internet.agent_web_index import build_agent_web_search_index, build_agent_web_search_index_from_repo_root, search_agent_web_index


def test_build_agent_web_search_index_and_query():
    manifest = {
        "identity": {"city_id": "city-web", "slug": "web", "repo": "org/city-web"},
        "assistant": {"assistant_id": "moltbook_assistant", "assistant_kind": "moltbook_assistant", "city_health": "healthy"},
        "capabilities": {"city": ["moltbook"], "assistant": ["assistant_surface"]},
        "documents": [
            {"document_id": "agent_web", "rel": "agent_web", "kind": "manifest", "title": "Agent Web", "href": "Agent-Web.md", "entrypoint": True},
            {"document_id": "search_index", "rel": "search_index", "kind": "search_index", "title": "Search Index", "href": "Search-Index.md", "entrypoint": False},
            {"document_id": "assistant_surface", "rel": "assistant_surface", "kind": "assistant_surface", "title": "Assistant Surface", "href": "Assistant-Surface.md", "entrypoint": True},
        ],
        "campaigns": [{"id": "internet-adaptation", "title": "Internet adaptation", "north_star": "Continuously adapt to relevant new protocols and standards.", "status": "active", "last_gap_summary": ["keep execution bounded"]}],
        "service_affordances": [{"service_id": "city-web:forum", "service_name": "forum", "transport": "https", "href": "https://forum.city-web.lotus", "public_handle": "forum.city-web.lotus", "visibility": "public", "auth_required": False, "required_scopes": []}],
        "route_affordances": [],
        "spaces": [{"space_id": "space:city-web:moltbook_assistant", "display_name": "moltbook_assistant", "kind": "assistant"}],
        "slots": [{"slot_id": "slot:city-web:assistant-social", "space_id": "space:city-web:moltbook_assistant", "slot_kind": "assistant_social", "status": "active"}],
        "links": [
            {"rel": "agent_web", "href": "Agent-Web.md", "kind": "document", "document_id": "agent_web"},
            {"rel": "search_index", "href": "Search-Index.md", "kind": "document", "document_id": "search_index"},
            {"rel": "assistant_surface", "href": "Assistant-Surface.md", "kind": "document", "document_id": "assistant_surface"},
        ],
    }
    graph = build_agent_web_public_graph(manifest)

    index = build_agent_web_search_index(manifest, graph)
    results = search_agent_web_index(index, query="internet adaptation", limit=5)

    assert index["kind"] == "agent_web_search_index"
    assert index["stats"]["kind_counts"]["campaign"] == 1
    assert any(record["record_id"] == "document:search_index" for record in index["records"])
    assert results["kind"] == "agent_web_search_results"
    assert results["results"][0]["kind"] == "campaign"
    assert "internet" in results["results"][0]["matched_terms"]


def test_build_agent_web_search_index_from_repo_root(tmp_path):
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

    index = build_agent_web_search_index_from_repo_root(
        repo_root,
        state_snapshot={
            "spaces": [{"space_id": "space:city-web:moltbook_assistant", "city_id": "city-web", "display_name": "moltbook_assistant", "kind": "assistant"}],
            "slots": [{"slot_id": "slot:city-web:assistant-social", "space_id": "space:city-web:moltbook_assistant", "slot_kind": "assistant_social", "status": "active"}],
            "service_addresses": [],
            "routes": [],
            "fork_lineage": [],
        },
    )

    assert index["city_id"] == "city-web"
    assert any(record["record_id"] == "document:search_index" for record in index["records"])