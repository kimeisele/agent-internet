import json

from agent_internet.agent_web_semantic_graph import build_agent_web_semantic_graph, read_agent_web_semantic_neighbors
from agent_internet.agent_web_wordnet_bridge import load_agent_web_wordnet_bridge


def test_build_agent_web_semantic_graph_and_read_neighbors(tmp_path):
    wordnet_path = tmp_path / "wordnet_bridge.json"
    wordnet_path.write_text(json.dumps({"synsets": ["market.n.01", "commerce.n.01"], "words": {"w1": {"t": ["bazaar"], "c": [0, 1]}, "w2": {"t": ["marketplace"], "c": [0, 1]}, "w3": {"t": ["commerce"], "c": [0, 1]}}}))
    overlay = {"bridges": [{"bridge_id": "wordnet:marketplace", "bridge_kind": "wordnet", "terms": ["bazaar"], "expansions": ["marketplace"], "enabled": True}]}
    records = [
        {"record_id": "campaign:city-a:bazaar", "kind": "campaign", "title": "Bazaar Commons", "summary": "Local bazaar network", "href": "Assistant-Surface.md", "tags": ["bazaar"], "terms": ["bazaar", "commons"], "source_city_id": "city-a"},
        {"record_id": "campaign:city-b:marketplace", "kind": "campaign", "title": "Marketplace Integration", "summary": "Commerce layer", "href": "Assistant-Surface.md", "tags": ["marketplace"], "terms": ["marketplace", "commerce"], "source_city_id": "city-b"},
    ]

    graph = build_agent_web_semantic_graph(records, semantic_overlay=overlay, wordnet_bridge=load_agent_web_wordnet_bridge(wordnet_path))
    assert graph["stats"]["edge_count"] == 1

    payload = read_agent_web_semantic_neighbors({"records": records, "semantic_graph": graph}, record_id="campaign:city-a:bazaar", limit=3)
    assert payload["neighbors"][0]["record_id"] == "campaign:city-b:marketplace"
    assert "semantic_bridge" in payload["neighbors"][0]["reason_kinds"]