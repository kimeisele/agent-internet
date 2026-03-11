from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GITHUB_REPOSITORY_SEARCH_URL = "https://api.github.com/search/repositories"
FEDERATION_NODE_TOPIC = "agent-federation-node"


@dataclass(frozen=True, slots=True)
class GitHubTopicDiscoveryResult:
    repository_full_name: str
    default_branch: str
    descriptor_url: str
    html_url: str = ""
    description: str = ""


def discover_federation_descriptors_by_github_topic(
    *,
    topic: str = FEDERATION_NODE_TOPIC,
    owner: str | None = None,
    limit: int = 30,
    include_forks: bool = False,
    github_token: str | None = None,
) -> tuple[GitHubTopicDiscoveryResult, ...]:
    query = [f"topic:{str(topic).strip()}", "archived:false"]
    if owner:
        query.append(f"user:{str(owner).strip()}")
    if not include_forks:
        query.append("fork:false")
    request = Request(
        f"{GITHUB_REPOSITORY_SEARCH_URL}?{urlencode({'q': ' '.join(query), 'per_page': max(1, min(int(limit), 100)), 'sort': 'updated', 'order': 'desc'})}",
        headers=_github_headers(github_token),
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    items = list(payload.get("items") or [])
    results: list[GitHubTopicDiscoveryResult] = []
    for item in items[: max(int(limit), 1)]:
        if not isinstance(item, dict):
            continue
        full_name = str(item.get("full_name", "")).strip()
        default_branch = str(item.get("default_branch", "main")).strip() or "main"
        if not full_name:
            continue
        results.append(
            GitHubTopicDiscoveryResult(
                repository_full_name=full_name,
                default_branch=default_branch,
                descriptor_url=f"https://raw.githubusercontent.com/{full_name}/{default_branch}/.well-known/agent-federation.json",
                html_url=str(item.get("html_url", "")).strip(),
                description=str(item.get("description", "") or "").strip(),
            ),
        )
    return tuple(results)


def _github_headers(github_token: str | None = None) -> dict[str, str]:
    token = str(github_token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "agent-internet-github-topic-discovery/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers