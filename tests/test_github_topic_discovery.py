import json

from agent_internet.github_topic_discovery import discover_federation_descriptors_by_github_topic


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_discover_federation_descriptors_by_github_topic_builds_descriptor_urls(monkeypatch):
    captured = {}

    def _mock_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        return _Response(
            {
                "items": [
                    {
                        "full_name": "kimeisele/agent-world",
                        "default_branch": "main",
                        "html_url": "https://github.com/kimeisele/agent-world",
                        "description": "World node",
                    },
                ],
            },
        )

    monkeypatch.setattr("agent_internet.github_topic_discovery.urlopen", _mock_urlopen)

    results = discover_federation_descriptors_by_github_topic(topic="agent-federation-node", owner="kimeisele")

    assert results[0].descriptor_url == "https://raw.githubusercontent.com/kimeisele/agent-world/main/.well-known/agent-federation.json"
    assert "topic%3Aagent-federation-node" in captured["url"]
    assert "user%3Akimeisele" in captured["url"]
    assert captured["headers"]["Accept"] == "application/vnd.github+json"