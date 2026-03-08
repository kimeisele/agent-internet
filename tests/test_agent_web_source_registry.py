import json

from agent_internet.agent_web_source_registry import (
    build_agent_web_crawl_bootstrap_from_registry,
    load_agent_web_source_registry,
    remove_agent_web_source_registry_entry,
    search_agent_web_crawl_bootstrap_from_registry,
    upsert_agent_web_source_registry_entry,
)


def test_agent_web_source_registry_add_remove_and_crawl(tmp_path):
    registry_path = tmp_path / "registry.json"
    repo_a = _write_repo(tmp_path / "city-a", city_id="city-a", repo="org/city-a", campaign_title="Internet adaptation")
    repo_b = _write_repo(tmp_path / "city-b", city_id="city-b", repo="org/city-b", campaign_title="Marketplace integration")

    empty = load_agent_web_source_registry(registry_path)
    assert empty["stats"]["source_count"] == 0

    registry = upsert_agent_web_source_registry_entry(registry_path, root=repo_a, labels=("manual",), notes="seed a")
    registry = upsert_agent_web_source_registry_entry(registry_path, root=repo_b, source_id="city-b-source", labels=("market",), notes="seed b")
    assert registry["stats"]["source_count"] == 2
    assert any(source["source_id"] == "city-b-source" for source in registry["sources"])

    crawl = build_agent_web_crawl_bootstrap_from_registry(
        registry_path,
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
    assert crawl["registry"]["enabled_source_count"] == 2
    assert crawl["stats"]["source_count"] == 2

    results = search_agent_web_crawl_bootstrap_from_registry(
        registry_path,
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
        query="marketplace",
        limit=5,
    )
    assert results["results"][0]["source_city_id"] == "city-b"

    registry = remove_agent_web_source_registry_entry(registry_path, source_id="city-b-source")
    assert registry["stats"]["source_count"] == 1


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
                "active_campaigns": [{"id": campaign_title.lower().replace(" ", "-"), "title": campaign_title, "north_star": campaign_title, "status": "active", "last_gap_summary": ["keep execution bounded"]}],
            },
        ),
    )
    return repo_root