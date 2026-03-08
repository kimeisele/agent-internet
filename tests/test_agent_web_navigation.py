import json

import pytest

from agent_internet.agent_web_navigation import read_agent_web_document_from_repo_root, resolve_agent_web_link


def test_resolve_agent_web_link_by_rel_and_href():
    manifest = {
        "links": [
            {"rel": "wiki_home", "href": "Home.md", "media_type": "text/markdown"},
            {"rel": "agent_web", "href": "Agent-Web.md", "media_type": "text/markdown"},
        ]
    }

    assert resolve_agent_web_link(manifest, rel="agent_web")["href"] == "Agent-Web.md"
    assert resolve_agent_web_link(manifest, href="Home.md")["rel"] == "wiki_home"


def test_read_agent_web_document_from_repo_root(tmp_path):
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
    state_snapshot = {
        "spaces": [{"space_id": "space:city-web:moltbook_assistant", "city_id": "city-web"}],
        "slots": [{"slot_id": "slot:city-web:assistant-social", "space_id": "space:city-web:moltbook_assistant"}],
        "service_addresses": [],
        "routes": [],
        "fork_lineage": [],
    }

    payload = read_agent_web_document_from_repo_root(repo_root, state_snapshot=state_snapshot, rel="assistant_surface")

    assert payload["link"]["rel"] == "assistant_surface"
    assert payload["document"]["path"] == "Assistant-Surface.md"
    assert "## Active Campaigns" in payload["document"]["content"]
    assert "Internet adaptation" in payload["document"]["content"]


def test_read_agent_web_document_rejects_non_markdown_links(tmp_path):
    repo_root = tmp_path / "city"
    (repo_root / "data" / "federation").mkdir(parents=True)
    (repo_root / "data" / "assistant_state.json").write_text("{}")
    (repo_root / "data" / "federation" / "peer.json").write_text(
        json.dumps(
            {
                "identity": {"city_id": "city-web", "slug": "web", "repo": "org/city-web"},
                "git_federation": {"wiki_repo_url": "git@github.com:org/city-web.wiki.git"},
            },
        ),
    )

    with pytest.raises(ValueError, match="unsupported_agent_web_link_media_type"):
        read_agent_web_document_from_repo_root(
            repo_root,
            state_snapshot={"spaces": [], "slots": [], "service_addresses": [], "routes": [], "fork_lineage": []},
            rel="wiki_repo",
        )