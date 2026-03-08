import json

from agent_internet.agent_web_crawl import build_agent_web_crawl_bootstrap, search_agent_web_crawl_bootstrap


def test_build_agent_web_crawl_bootstrap_and_search(tmp_path):
    repo_a = _write_repo(tmp_path / "city-a", city_id="city-a", repo="org/city-a", campaign_title="Internet adaptation")
    repo_b = _write_repo(tmp_path / "city-b", city_id="city-b", repo="org/city-b", campaign_title="Marketplace integration")

    crawl = build_agent_web_crawl_bootstrap(
        [str(repo_a), str(repo_b), str(tmp_path / "missing")],
        state_snapshot={
            "spaces": [
                {"space_id": "space:city-a:moltbook_assistant", "city_id": "city-a", "display_name": "moltbook_assistant", "kind": "assistant"},
                {"space_id": "space:city-b:moltbook_assistant", "city_id": "city-b", "display_name": "moltbook_assistant", "kind": "assistant"},
            ],
            "slots": [
                {"slot_id": "slot:city-a:assistant-social", "space_id": "space:city-a:moltbook_assistant", "slot_kind": "assistant_social", "status": "active"},
                {"slot_id": "slot:city-b:assistant-social", "space_id": "space:city-b:moltbook_assistant", "slot_kind": "assistant_social", "status": "active"},
            ],
            "service_addresses": [
                {"service_id": "city-a:forum", "owner_city_id": "city-a", "service_name": "forum", "public_handle": "forum.city-a.lotus", "transport": "https", "location": "https://forum.city-a.lotus", "visibility": "public", "auth_required": False, "required_scopes": []},
                {"service_id": "city-b:market", "owner_city_id": "city-b", "service_name": "market", "public_handle": "market.city-b.lotus", "transport": "https", "location": "https://market.city-b.lotus", "visibility": "public", "auth_required": False, "required_scopes": []},
            ],
            "routes": [],
            "fork_lineage": [],
        },
    )

    assert crawl["kind"] == "agent_web_crawl_bootstrap"
    assert crawl["stats"]["source_count"] == 2
    assert crawl["stats"]["error_count"] == 1
    assert any(source["city_id"] == "city-a" for source in crawl["sources"])
    assert any(record["source_city_id"] == "city-b" for record in crawl["aggregate_index"]["records"])

    results = search_agent_web_crawl_bootstrap(crawl, query="marketplace", limit=5)
    assert results["kind"] == "agent_web_crawl_search_results"
    assert results["results"][0]["source_city_id"] == "city-b"
    assert results["results"][0]["kind"] == "campaign"


def _write_repo(repo_root, *, city_id: str, repo: str, campaign_title: str):
    reports_dir = repo_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (repo_root / "data" / "assistant_state.json").write_text(json.dumps({"followed": ["alice"], "ops": {"posts": 1}}))
    (repo_root / "data" / "federation" / "peer.json").write_text(
        json.dumps({"identity": {"city_id": city_id, "slug": city_id, "repo": repo}, "capabilities": ["moltbook"]}),
    )
    (reports_dir / "report_1.json").write_text(
        json.dumps(
            {
                "heartbeat": 1,
                "timestamp": 1.0,
                "population": 1,
                "alive": 1,
                "dead": 0,
                "chain_valid": True,
                "active_campaigns": [{"id": campaign_title.lower().replace(' ', '-'), "title": campaign_title, "north_star": campaign_title, "status": "active", "last_gap_summary": ["keep execution bounded"]}],
            },
        ),
    )
    return repo_root