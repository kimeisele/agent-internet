"""Environment probe, capability manifest, and federation discovery.

Provides self-knowledge for agents: what can the browser reach, with what
credentials, and who are the known federation peers.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .agent_web_browser import BrowserConfig, PageSource

logger = logging.getLogger("AGENT_INTERNET.WEB_BROWSER.ENV")


# ---------------------------------------------------------------------------
# Environment probe
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class EnvironmentProbe:
    """Result of probing the runtime network environment."""

    has_internet: bool
    has_proxy: bool
    proxy_url: str
    has_github_token: bool
    github_api_reachable: bool
    github_user: str
    registered_sources: tuple[str, ...]
    python_version: str
    platform: str
    hostname: str
    working_directory: str
    probed_at: float


def probe_environment(
    *,
    config: BrowserConfig | None = None,
    sources: list[PageSource] | None = None,
) -> dict:
    """Probe and report the agent's runtime network environment.

    Returns a structured dict agents can use to understand what they can
    reach and with what credentials.
    """
    cfg = config or BrowserConfig()
    proxy = os.environ.get("HTTPS_PROXY", os.environ.get("HTTP_PROXY", ""))
    github_token = os.environ.get("GITHUB_TOKEN", "")

    github_user = ""
    github_reachable = False
    if github_token:
        try:
            req = urllib.request.Request(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"token {github_token}",
                    "User-Agent": cfg.user_agent,
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            with urllib.request.urlopen(req, timeout=cfg.probe_timeout) as resp:
                data = json.loads(resp.read())
                github_user = data.get("login", "")
                github_reachable = True
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.debug("GitHub API user probe failed: %s", exc)
            try:
                req = urllib.request.Request(
                    "https://api.github.com",
                    headers={"User-Agent": cfg.user_agent},
                )
                with urllib.request.urlopen(req, timeout=cfg.probe_timeout):
                    github_reachable = True
            except (urllib.error.URLError, TimeoutError, OSError) as exc2:
                logger.debug("GitHub API root probe failed: %s", exc2)

    has_internet = github_reachable
    if not has_internet:
        try:
            req = urllib.request.Request(
                "https://example.com",
                headers={"User-Agent": cfg.user_agent},
                method="HEAD",
            )
            with urllib.request.urlopen(req, timeout=cfg.probe_timeout):
                has_internet = True
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.debug("Internet probe failed: %s", exc)

    source_names = tuple(type(s).__name__ for s in (sources or []))

    probe = EnvironmentProbe(
        has_internet=has_internet,
        has_proxy=bool(proxy),
        proxy_url=proxy.split("@")[-1] if "@" in proxy else proxy[:50] if proxy else "",
        has_github_token=bool(github_token),
        github_api_reachable=github_reachable,
        github_user=github_user,
        registered_sources=source_names,
        python_version=platform.python_version(),
        platform=f"{platform.system()} {platform.release()}",
        hostname=platform.node(),
        working_directory=os.getcwd(),
        probed_at=time.time(),
    )

    return {
        "kind": "agent_web_browser_environment",
        "version": 1,
        "connectivity": {
            "has_internet": probe.has_internet,
            "has_proxy": probe.has_proxy,
            "proxy_endpoint": probe.proxy_url,
        },
        "github": {
            "authenticated": probe.has_github_token,
            "api_reachable": probe.github_api_reachable,
            "user": probe.github_user,
        },
        "sources": list(probe.registered_sources),
        "runtime": {
            "python": probe.python_version,
            "platform": probe.platform,
            "hostname": probe.hostname,
            "cwd": probe.working_directory,
        },
        "probed_at": probe.probed_at,
    }


# ---------------------------------------------------------------------------
# GAD-000 capability manifest
# ---------------------------------------------------------------------------

def build_browser_capability_manifest(
    *,
    base_url: str = "",
    sources: list[PageSource] | None = None,
) -> dict:
    """Build a GAD-000-conformant capability manifest for the agent web browser."""
    source_names = [type(s).__name__ for s in (sources or [])]

    capabilities = [
        {
            "capability_id": "web_browse",
            "summary": "Fetch a URL and return structured, agent-readable page content.",
            "mode": "read_only",
            "contract_version": 1,
            "input_schema": {
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "use_cache": {"type": "boolean", "default": True},
                },
            },
            "stable_response_subset": {
                "top_level_fields": [
                    "url", "status_code", "title", "content_text",
                    "links", "forms", "meta", "ok", "error",
                ],
                "link_fields": ["href", "text", "rel", "index"],
                "form_fields": ["action", "method", "fields", "form_id", "index"],
                "meta_fields": [
                    "description", "keywords", "author", "canonical_url",
                    "og_title", "og_description",
                ],
            },
        },
        {
            "capability_id": "web_follow_link",
            "summary": "Follow a link on the current page by index or text search.",
            "mode": "read_only",
            "contract_version": 1,
            "input_schema": {
                "required": ["index_or_query"],
                "properties": {
                    "index_or_query": {
                        "type": ["integer", "string"],
                        "description": "Link index (int) or text/href search query (str)",
                    },
                },
            },
            "stable_response_subset": {
                "top_level_fields": [
                    "url", "status_code", "title", "content_text",
                    "links", "forms", "meta", "ok", "error",
                ],
            },
        },
        {
            "capability_id": "web_navigate",
            "summary": "Navigate back/forward in tab history.",
            "mode": "read_only",
            "contract_version": 1,
            "input_schema": {
                "required": ["direction"],
                "properties": {
                    "direction": {"type": "string", "enum": ["back", "forward", "refresh"]},
                },
            },
        },
        {
            "capability_id": "web_search_links",
            "summary": "Search links on the current page by keyword.",
            "mode": "read_only",
            "contract_version": 1,
            "input_schema": {
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
            "stable_response_subset": {"result_fields": ["href", "text", "rel", "index"]},
        },
        {
            "capability_id": "web_submit_form",
            "summary": "Submit a form on the current page with provided values.",
            "mode": "write",
            "contract_version": 1,
            "input_schema": {
                "required": ["index_or_id"],
                "properties": {
                    "index_or_id": {"type": ["integer", "string"]},
                    "values": {"type": "object", "description": "Field name → value overrides"},
                },
            },
        },
        {
            "capability_id": "web_environment",
            "summary": "Probe the runtime environment: connectivity, proxy, credentials, sources.",
            "mode": "read_only",
            "contract_version": 1,
            "input_schema": {"properties": {}},
            "stable_response_subset": {
                "top_level_fields": ["connectivity", "github", "sources", "runtime", "probed_at"],
            },
        },
        {
            "capability_id": "web_tab_management",
            "summary": "Create, switch, close, and list browser tabs.",
            "mode": "read_write",
            "contract_version": 1,
            "input_schema": {
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": ["new", "switch", "close", "list"]},
                    "tab_id": {"type": "string"},
                    "label": {"type": "string"},
                },
            },
        },
    ]

    return {
        "kind": "agent_web_browser_capability_manifest",
        "version": 1,
        "standard_profile": {
            "profile_id": "agent_web_browser_standard.v1",
            "gad_conformance": "gad_000_plus",
            "source_system": "agent_internet",
            "provider_role": "public_web_transport_adapter",
            "consumer_roles": ["autonomous_agent", "orchestrator", "proxy_wrapper"],
        },
        "surface_kind": "agent_web_browser_surface",
        "consumer_model": "stateful_session",
        "federation_surface": {
            "surface_role": "public_web_transport_adapter",
            "canonical_for_public_federation": False,
            "transport_boundary": "Per ADR-0003: external protocols are transport, not substrate.",
        },
        "sources": {
            "registered": source_names,
            "available": ["GitHubBrowserSource", "custom PageSource implementations"],
        },
        "capabilities": capabilities,
        "non_goals": [
            "The browser does not execute JavaScript or render CSS.",
            "External web identity is not imported into the federation identity model.",
            "Page content is transport-level projection, not substrate truth.",
        ],
        "stats": {"capability_count": len(capabilities)},
    }


# ---------------------------------------------------------------------------
# Federation discovery
# ---------------------------------------------------------------------------

_FEDERATION_DESCRIPTOR_SEEDS = (
    "kimeisele/agent-internet",
    "kimeisele/steward-protocol",
    "kimeisele/agent-city",
    "kimeisele/agent-world",
    "kimeisele/steward",
)


def discover_federation_descriptors(*, config: BrowserConfig | None = None) -> list[dict]:
    """Fetch .well-known/agent-federation.json from known federation peers.

    Used by ``about:federation`` to give agents a live map of the ecosystem.
    """
    cfg = config or BrowserConfig()
    descriptors: list[dict] = []

    try:
        seed_path = Path("data/federation/authority-descriptor-seeds.json")
        if seed_path.exists():
            seed_data = json.loads(seed_path.read_text())
            if isinstance(seed_data, list):
                for seed in seed_data:
                    url = seed.get("descriptor_url", "") if isinstance(seed, dict) else ""
                    if url and "/agent-federation.json" in url:
                        parts = url.split("githubusercontent.com/")
                        if len(parts) > 1:
                            repo_parts = parts[1].split("/")
                            if len(repo_parts) >= 2:
                                repo_id = f"{repo_parts[0]}/{repo_parts[1]}"
                                if repo_id not in _FEDERATION_DESCRIPTOR_SEEDS:
                                    _fetch_descriptor(url, repo_id, descriptors, cfg)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Failed to load federation seed file: %s", exc)

    for repo_id in _FEDERATION_DESCRIPTOR_SEEDS:
        url = f"https://raw.githubusercontent.com/{repo_id}/main/.well-known/agent-federation.json"
        _fetch_descriptor(url, repo_id, descriptors, cfg)

    return descriptors


def _fetch_descriptor(
    url: str, repo_id: str, descriptors: list[dict], cfg: BrowserConfig,
) -> None:
    """Fetch a single federation descriptor and append to the list."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": cfg.user_agent})
        with urllib.request.urlopen(req, timeout=cfg.probe_timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and data.get("kind") == "agent_federation_descriptor":
                data.setdefault("repo_id", repo_id)
                descriptors.append(data)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.debug("Federation descriptor fetch failed for %s: %s", repo_id, exc)
