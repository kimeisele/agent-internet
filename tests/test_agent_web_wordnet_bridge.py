import json

from agent_internet.agent_web_wordnet_bridge import load_agent_web_wordnet_bridge, wordnet_phrase_score


def test_agent_web_wordnet_bridge_loads_and_scores_phrase_similarity(tmp_path):
    wordnet_path = tmp_path / "wordnet_bridge.json"
    wordnet_path.write_text(
        json.dumps(
            {
                "synsets": ["market.n.01", "commerce.n.01", "internet.n.01"],
                "words": {
                    "w1": {"t": ["bazaar"], "c": [0, 1]},
                    "w2": {"t": ["marketplace"], "c": [0, 1]},
                    "w3": {"t": ["commerce"], "c": [0, 1]},
                    "w4": {"t": ["internet"], "c": [2]},
                },
            },
        ),
    )

    bridge = load_agent_web_wordnet_bridge(wordnet_path)
    assert bridge["available"] is True
    assert bridge["stats"]["token_count"] == 4

    score_related = wordnet_phrase_score("bazaar", "marketplace", bridge=bridge)
    score_unrelated = wordnet_phrase_score("bazaar", "internet", bridge=bridge)
    assert score_related > score_unrelated
    assert score_related > 0.0