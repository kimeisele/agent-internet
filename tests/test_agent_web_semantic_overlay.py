from agent_internet.agent_web_semantic_overlay import (
    expand_query_with_agent_web_semantic_overlay,
    load_agent_web_semantic_overlay,
    refresh_agent_web_semantic_overlay,
    remove_agent_web_semantic_bridge,
    upsert_agent_web_semantic_bridge,
)


def test_agent_web_semantic_overlay_add_refresh_expand_remove(tmp_path):
    overlay_path = tmp_path / "semantic_overlay.json"

    overlay = upsert_agent_web_semantic_bridge(
        overlay_path,
        bridge_kind="synonym",
        bridge_id="synonym:bazaar-marketplace",
        terms=["bazaar"],
        expansions=["marketplace"],
        notes="bootstrap synonym",
    )
    overlay = upsert_agent_web_semantic_bridge(
        overlay_path,
        bridge_kind="concept",
        terms=["agent web"],
        expansions=["agent internet", "public graph"],
    )

    assert overlay["stats"]["bridge_count"] == 2
    assert overlay["stats"]["enabled_bridge_count"] == 2

    refreshed = refresh_agent_web_semantic_overlay(overlay_path, now=55.0)
    assert refreshed["refreshed_at"] == 55.0

    loaded = load_agent_web_semantic_overlay(overlay_path)
    expansion = expand_query_with_agent_web_semantic_overlay(loaded, query="bazaar search")
    assert "marketplace" in expansion["expanded_terms"]
    assert expansion["matched_bridges"][0]["bridge_id"] == "synonym:bazaar-marketplace"

    removed = remove_agent_web_semantic_bridge(overlay_path, bridge_id="synonym:bazaar-marketplace")
    assert removed["stats"]["bridge_count"] == 1