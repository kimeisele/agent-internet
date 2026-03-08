from agent_internet.agent_web_semantic_overlay import (
    expand_query_with_agent_web_semantic_overlay,
    load_agent_web_semantic_overlay,
    refresh_agent_web_semantic_overlay,
    remove_agent_web_semantic_bridge,
    upsert_agent_web_semantic_bridge,
)
from agent_internet.agent_web_wordnet_bridge import load_agent_web_wordnet_bridge


def test_agent_web_semantic_overlay_add_refresh_expand_remove(tmp_path):
    overlay_path = tmp_path / "semantic_overlay.json"
    wordnet_path = tmp_path / "wordnet_bridge.json"
    wordnet_path.write_text(
        '{"synsets": ["market.n.01", "commerce.n.01"], "words": {"w1": {"t": ["bazaar"], "c": [0, 1]}, "w2": {"t": ["marketplace"], "c": [0, 1]}, "w3": {"t": ["commerce"], "c": [0, 1]}}}',
    )

    overlay = upsert_agent_web_semantic_bridge(
        overlay_path,
        bridge_kind="wordnet",
        bridge_id="wordnet:marketplace",
        terms=["marketplace"],
        expansions=["commerce"],
        weight=0.8,
        notes="bootstrap wordnet",
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
    expansion = expand_query_with_agent_web_semantic_overlay(loaded, query="bazaar search", wordnet_bridge=load_agent_web_wordnet_bridge(wordnet_path))
    assert "marketplace" in expansion["expanded_terms"]
    assert expansion["matched_bridges"][0]["bridge_id"] == "wordnet:marketplace"
    assert expansion["matched_bridges"][0]["wordnet_score"] > 0.0
    assert expansion["weighted_expanded_terms"][0]["weight"] > 0.0

    removed = remove_agent_web_semantic_bridge(overlay_path, bridge_id="wordnet:marketplace")
    assert removed["stats"]["bridge_count"] == 1