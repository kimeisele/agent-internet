from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .agent_web import build_agent_web_manifest
from .agent_web_graph import build_agent_web_public_graph
from .agent_web_index import build_agent_web_search_index
from .node_health import (
    build_node_surface_snapshot,
    render_federation_status_page,
    render_node_health_page,
    render_repo_quality_page,
    render_surface_integrity_page,
)
from .agent_web_repo_graph_capabilities import render_agent_web_repo_graph_capability_page
from .agent_web_repo_graph_contracts import render_agent_web_repo_graph_contract_page
from .agent_web_semantic_capabilities import render_agent_web_semantic_capability_page
from .agent_web_semantic_contracts import render_agent_web_semantic_contract_page
from .file_locking import write_locked_json_value

HOME_SUMMARY_START = "<!-- AGENT_INTERNET_SUMMARY_START -->"
HOME_SUMMARY_END = "<!-- AGENT_INTERNET_SUMMARY_END -->"


@dataclass(frozen=True, slots=True)
class GitRemoteMetadata:
    repo_root: Path
    origin_url: str
    repo_ref: str
    wiki_repo_url: str


def ensure_git_checkout(repo_url: str, checkout_path: Path | str) -> Path:
    checkout = Path(checkout_path).resolve()
    if not checkout.exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", repo_url, str(checkout)], check=True, capture_output=True, text=True)
    else:
        subprocess.run(["git", "fetch", "origin", "--prune"], cwd=str(checkout), check=True, capture_output=True, text=True)
        current_branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=str(checkout), check=True, capture_output=True, text=True
        ).stdout.strip()
        remote_branches = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"],
            cwd=str(checkout),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        if current_branch and f"origin/{current_branch}" in remote_branches:
            subprocess.run(
                ["git", "pull", "--rebase", "origin", current_branch],
                cwd=str(checkout),
                check=True,
                capture_output=True,
                text=True,
            )
    return checkout


def detect_git_remote_metadata(root: Path | str) -> GitRemoteMetadata:
    repo_root = Path(_run_git(root, "rev-parse", "--show-toplevel")).resolve()
    origin_url = _run_git(repo_root, "config", "--get", "remote.origin.url")
    repo_ref = derive_repo_ref(origin_url)
    return GitRemoteMetadata(
        repo_root=repo_root,
        origin_url=origin_url,
        repo_ref=repo_ref,
        wiki_repo_url=derive_wiki_repo_url(origin_url),
    )


def derive_repo_ref(origin_url: str) -> str:
    if ":" in origin_url and "@" in origin_url and not origin_url.startswith(("http://", "https://", "file://")):
        _, path = origin_url.split(":", 1)
        return _strip_git_suffix(path.lstrip("/"))
    parsed = urlsplit(origin_url)
    if parsed.scheme == "file":
        return _strip_git_suffix(Path(parsed.path).name)
    if parsed.scheme:
        return _strip_git_suffix(parsed.path.lstrip("/"))
    if origin_url.startswith(("/", "./", "../")):
        return _strip_git_suffix(Path(origin_url).name)
    return _strip_git_suffix(origin_url)


def derive_wiki_repo_url(origin_url: str) -> str:
    if origin_url.endswith(".wiki.git"):
        return origin_url
    if ":" in origin_url and "@" in origin_url and not origin_url.startswith(("http://", "https://", "file://")):
        prefix, path = origin_url.split(":", 1)
        return f"{prefix}:{_append_wiki_suffix(path)}"
    parsed = urlsplit(origin_url)
    if parsed.scheme:
        return urlunsplit(parsed._replace(path=_append_wiki_suffix(parsed.path)))
    return _append_wiki_suffix(origin_url)


@dataclass(slots=True)
class GitWikiFederationSync:
    repo_root: Path
    wiki_repo_url: str
    checkout_path: Path | None = None

    def sync(
        self,
        *,
        peer_descriptor: dict,
        state_snapshot: dict,
        heartbeat_label: str = "manual",
        assistant_snapshot: dict | None = None,
    ) -> dict:
        wiki_path = self._ensure_checkout()
        pages = render_wiki_projection(
            peer_descriptor=peer_descriptor,
            state_snapshot=state_snapshot,
            assistant_snapshot=assistant_snapshot,
            repo_root=self.repo_root,
        )
        for relative_path, content in pages.items():
            target = wiki_path / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        committed = _git_commit_all(wiki_path, f"Agent Internet: sync federation wiki ({heartbeat_label})")
        return {
            "wiki_path": str(wiki_path),
            "wiki_repo_url": self.wiki_repo_url,
            "pages": sorted(pages),
            "committed": committed,
        }

    def _ensure_checkout(self) -> Path:
        if not self.wiki_repo_url:
            raise ValueError("missing_wiki_repo_url")
        checkout = ensure_git_checkout(self.wiki_repo_url, self.checkout_path or (self.repo_root / ".agent_internet" / "wiki"))
        _ensure_local_git_identity(checkout)
        return checkout


def build_git_federation_manifest(*, peer_descriptor: dict, remote: GitRemoteMetadata, shared_pages: tuple[str, ...]) -> dict:
    return {
        "repo_root": str(remote.repo_root),
        "origin_url": remote.origin_url,
        "repo_ref": remote.repo_ref,
        "wiki_repo_url": remote.wiki_repo_url,
        "city_id": peer_descriptor.get("identity", {}).get("city_id", ""),
        "shared_pages": list(shared_pages),
    }


def write_git_federation_manifest(path: Path, *, peer_descriptor: dict, remote: GitRemoteMetadata, shared_pages: tuple[str, ...]) -> dict:
    payload = build_git_federation_manifest(peer_descriptor=peer_descriptor, remote=remote, shared_pages=shared_pages)
    write_locked_json_value(path, payload)
    return payload


def render_wiki_projection(
    *,
    peer_descriptor: dict,
    state_snapshot: dict,
    assistant_snapshot: dict | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, str]:
    identity = dict(peer_descriptor.get("identity", {}))
    git_manifest = dict(peer_descriptor.get("git_federation", {}))
    cities = list(state_snapshot.get("identities", []))
    services = list(state_snapshot.get("service_addresses", []))
    routes = list(state_snapshot.get("routes", []))
    lineage_records = list(state_snapshot.get("fork_lineage", []))
    current_lineage = _resolve_current_lineage(identity=identity, git_manifest=git_manifest, lineage_records=lineage_records)
    summary_lines = [
        f"## Connected City: {identity.get('city_id', 'unknown')}",
        f"- Repo: `{identity.get('repo', '')}`",
        f"- Origin: `{git_manifest.get('origin_url', '')}`",
        f"- Wiki: `{git_manifest.get('wiki_repo_url', '')}`",
        f"- Known Cities: `{len(cities)}`",
        f"- Services: `{len(services)}`",
        f"- Routes: `{len(routes)}`",
    ]
    if assistant_snapshot:
        campaigns = list(assistant_snapshot.get("active_campaigns", []))
        summary_lines.extend(
            [
                f"- Assistant: `{assistant_snapshot.get('assistant_id', '')}` ({assistant_snapshot.get('assistant_kind', '')})",
                f"- Assistant Heartbeat: `{assistant_snapshot.get('heartbeat')}` via `{assistant_snapshot.get('heartbeat_source', '')}`",
                f"- Assistant Activity: follows `{assistant_snapshot.get('total_follows', 0)}`, invites `{assistant_snapshot.get('total_invites', 0)}`, posts `{assistant_snapshot.get('total_posts', 0)}`",
            ],
        )
        if campaigns:
            primary = campaigns[0]
            summary_lines.extend(
                [
                    f"- Active Campaigns: `{len(campaigns)}`",
                    f"- Campaign Focus: `{primary.get('title') or primary.get('id', '')}` ({primary.get('status', 'unknown')})",
                ],
            )
    if current_lineage:
        summary_lines.extend(
            [
                f"- Upstream Repo: `{current_lineage.get('upstream_repo', '')}`",
                f"- Line Root: `{current_lineage.get('line_root_repo', '')}`",
                f"- Fork Mode: `{current_lineage.get('fork_mode', '')}` / Sync: `{current_lineage.get('sync_policy', '')}`",
            ],
        )
    elif lineage_records:
        summary_lines.append(f"- Known Lineage Records: `{len(lineage_records)}`")
    summary = "\n".join(summary_lines)
    home = _replace_block("# Agent Internet Federation\n\n", HOME_SUMMARY_START, HOME_SUMMARY_END, summary)
    assistant_page_snapshot = {
        "city_id": identity.get("city_id", ""),
        "repo": identity.get("repo", ""),
        **dict(assistant_snapshot or {}),
    }
    cities_md = _render_index_page(
        title="Cities",
        count=len(cities),
        entries=[f"- `{item['city_id']}` → `{item['repo']}`" for item in cities],
        empty_message="No cities have published themselves into this surface yet.",
    )
    services_md = _render_index_page(
        title="Services",
        count=len(services),
        entries=[f"- `{item['service_id']}` → `{item['public_handle']}` @ `{item['location']}`" for item in services],
        empty_message="No services are published yet.",
    )
    routes_md = _render_index_page(
        title="Routes",
        count=len(routes),
        entries=[
            f"- `{item['destination_prefix']}` via `{item['next_hop_city_id']}` ({item['nadi_type']}/{item['priority']})"
            for item in routes
        ],
        empty_message="No routes are published yet.",
    )
    manifest_md = "# Git Federation\n\n" + json.dumps(git_manifest, indent=2, sort_keys=True)
    agent_web = build_agent_web_manifest(
        peer_descriptor=peer_descriptor,
        state_snapshot=state_snapshot,
        assistant_snapshot=assistant_snapshot,
    )
    public_graph = build_agent_web_public_graph(agent_web)
    search_index = build_agent_web_search_index(agent_web, public_graph)
    pages = {
        "Home.md": home,
        "Node-Health.md": "",
        "Federation-Status.md": "",
        "Surface-Integrity.md": "",
        "Repo-Quality.md": "",
        "Cities.md": cities_md,
        "Services.md": services_md,
        "Routes.md": routes_md,
        "Git-Federation.md": manifest_md.rstrip() + "\n",
        "Agent-Web.md": _render_agent_web_page(agent_web),
        "Assistant-Surface.md": _render_assistant_surface_page(assistant_page_snapshot),
        "Semantic-Capabilities.md": render_agent_web_semantic_capability_page(dict(agent_web.get("semantic_capabilities", {}))),
        "Semantic-Contracts.md": render_agent_web_semantic_contract_page(dict(agent_web.get("semantic_contracts", {}))),
        "Repo-Graph-Capabilities.md": render_agent_web_repo_graph_capability_page(dict(agent_web.get("repo_graph_capabilities", {}))),
        "Repo-Graph-Contracts.md": render_agent_web_repo_graph_contract_page(dict(agent_web.get("repo_graph_contracts", {}))),
        "Public-Graph.md": _render_public_graph_page(public_graph),
        "Search-Index.md": _render_search_index_page(search_index),
        "Lineage.md": _render_lineage_page(current_lineage=current_lineage, lineage_records=lineage_records),
        "_Sidebar.md": _render_sidebar_page(),
        "_Footer.md": _render_footer_page(),
    }
    node_surface = build_node_surface_snapshot(
        repo_root=repo_root,
        peer_descriptor=peer_descriptor,
        state_snapshot=state_snapshot,
        assistant_snapshot=assistant_snapshot,
        rendered_pages=pages,
        agent_web=agent_web,
    )
    pages["Node-Health.md"] = render_node_health_page(node_surface)
    pages["Federation-Status.md"] = render_federation_status_page(node_surface)
    pages["Surface-Integrity.md"] = render_surface_integrity_page(node_surface)
    pages["Repo-Quality.md"] = render_repo_quality_page(node_surface)
    node_surface = build_node_surface_snapshot(
        repo_root=repo_root,
        peer_descriptor=peer_descriptor,
        state_snapshot=state_snapshot,
        assistant_snapshot=assistant_snapshot,
        rendered_pages=pages,
        agent_web=agent_web,
    )
    pages["Node-Health.md"] = render_node_health_page(node_surface)
    pages["Federation-Status.md"] = render_federation_status_page(node_surface)
    pages["Surface-Integrity.md"] = render_surface_integrity_page(node_surface)
    pages["Repo-Quality.md"] = render_repo_quality_page(node_surface)
    return pages


def _render_index_page(*, title: str, count: int, entries: list[str], empty_message: str) -> str:
    lines = [f"# {title}", "", f"- Published entries: `{count}`", ""]
    if entries:
        lines.extend(["## Entries", "", *entries])
    else:
        lines.extend([empty_message, ""])
    return "\n".join(lines).rstrip() + "\n"


def _render_assistant_surface_page(assistant_snapshot: dict) -> str:
    campaigns = list(assistant_snapshot.get("active_campaigns", []))
    lines = [
        "# Assistant Surface",
        "",
        f"- Assistant: `{assistant_snapshot.get('assistant_id', '')}`",
        f"- Kind: `{assistant_snapshot.get('assistant_kind', '')}`",
        f"- City: `{assistant_snapshot.get('city_id', '')}`",
        f"- Repo: `{assistant_snapshot.get('repo', '')}`",
        f"- Heartbeat Source: `{assistant_snapshot.get('heartbeat_source', '')}`",
        f"- Heartbeat: `{assistant_snapshot.get('heartbeat')}`",
        f"- Health: `{assistant_snapshot.get('city_health', '')}`",
        f"- Following: `{assistant_snapshot.get('following', 0)}`",
        f"- Invited: `{assistant_snapshot.get('invited', 0)}`",
        f"- Spotlighted: `{assistant_snapshot.get('spotlighted', 0)}`",
        f"- Total Follows: `{assistant_snapshot.get('total_follows', 0)}`",
        f"- Total Invites: `{assistant_snapshot.get('total_invites', 0)}`",
        f"- Total Posts: `{assistant_snapshot.get('total_posts', 0)}`",
        f"- Last Post Age (s): `{assistant_snapshot.get('last_post_age_s')}`",
        f"- Series Cursor: `{assistant_snapshot.get('series_cursor', -1)}`",
    ]
    if not str(assistant_snapshot.get("assistant_id", "")).strip():
        lines.extend(["", "No assistant snapshot is published yet for this city."])
    if campaigns:
        lines.extend(["", "## Active Campaigns", ""])
        for campaign in campaigns:
            title = campaign.get("title") or campaign.get("id", "")
            lines.append(f"- `{title}` (`{campaign.get('status', 'unknown')}`)")
            north_star = str(campaign.get("north_star", "")).strip()
            if north_star:
                lines.append(f"  - North Star: {north_star}")
            gaps = campaign.get("last_gap_summary", [])
            if gaps:
                lines.append(f"  - Gaps: {', '.join(str(item) for item in gaps[:3])}")
    lines.extend(["", "## Raw Snapshot", "", json.dumps(assistant_snapshot, indent=2, sort_keys=True)])
    return "\n".join(lines).rstrip() + "\n"


def _render_sidebar_page() -> str:
    links = [
        ("Home", "Home"),
        ("Node Health", "Node-Health"),
        ("Federation Status", "Federation-Status"),
        ("Surface Integrity", "Surface-Integrity"),
        ("Repo Quality", "Repo-Quality"),
        ("Agent Web", "Agent-Web"),
        ("Assistant Surface", "Assistant-Surface"),
        ("Public Graph", "Public-Graph"),
        ("Repo Graph Capabilities", "Repo-Graph-Capabilities"),
        ("Repo Graph Contracts", "Repo-Graph-Contracts"),
        ("Semantic Capabilities", "Semantic-Capabilities"),
        ("Semantic Contracts", "Semantic-Contracts"),
        ("Search Index", "Search-Index"),
        ("Cities", "Cities"),
        ("Services", "Services"),
        ("Routes", "Routes"),
        ("Lineage", "Lineage"),
        ("Git Federation", "Git-Federation"),
    ]
    lines = ["## Agent Internet", ""]
    lines.extend(f"- [[{label}|{target}]]" for label, target in links)
    return "\n".join(lines).rstrip() + "\n"


def _render_footer_page() -> str:
    return "Agent Internet · generated public membrane\n"


def _render_agent_web_page(manifest: dict) -> str:
    identity = dict(manifest.get("identity", {}))
    assistant = dict(manifest.get("assistant", {}))
    stats = dict(manifest.get("stats", {}))
    entrypoints = dict(manifest.get("entrypoints", {}))
    lines = [
        "# Agent Web",
        "",
        f"- City: `{identity.get('city_id', '')}`",
        f"- Repo: `{identity.get('repo', '')}`",
        f"- Assistant: `{assistant.get('assistant_id', '')}` ({assistant.get('assistant_kind', '')})",
        f"- Health: `{assistant.get('city_health', '')}`",
        f"- Campaigns: `{stats.get('campaign_count', 0)}`",
        f"- Spaces: `{stats.get('space_count', 0)}`",
        f"- Services: `{stats.get('service_count', 0)}`",
        f"- Routes: `{stats.get('route_count', 0)}`",
        "",
        "## Documents",
        "",
    ]
    for document in manifest.get("documents", []):
        lines.append(
            f"- `{document.get('document_id', '')}` → `{document.get('href', '')}` ({document.get('kind', '')}, entrypoint={document.get('entrypoint', False)})"
        )
    lines.extend([
        "",
        "## Entrypoints",
        "",
    ])
    for name, entrypoint in entrypoints.items():
        lines.append(f"- `{name}` → `{entrypoint.get('document_id', '')}` / `{entrypoint.get('rel', '')}`")
    lines.extend([
        "",
        "## Service Affordances",
        "",
    ])
    for affordance in manifest.get("service_affordances", []):
        lines.append(
            f"- `{affordance.get('service_id', '')}` @ `{affordance.get('href', '')}` ({affordance.get('transport', '')}, auth={affordance.get('auth_required', False)})"
        )
    lines.extend([
        "",
        "## Links",
        "",
    ])
    for link in manifest.get("links", []):
        lines.append(f"- `{link.get('rel', '')}` → `{link.get('href', '')}` [{link.get('kind', '')}]")
    lines.extend(["", "## Raw Manifest", "", json.dumps(manifest, indent=2, sort_keys=True)])
    return "\n".join(lines).rstrip() + "\n"


def _render_public_graph_page(graph: dict) -> str:
    stats = dict(graph.get("stats", {}))
    lines = [
        "# Public Graph",
        "",
        f"- City: `{graph.get('city_id', '')}`",
        f"- Root Node: `{graph.get('root_node_id', '')}`",
        f"- Nodes: `{stats.get('node_count', 0)}`",
        f"- Edges: `{stats.get('edge_count', 0)}`",
        "",
        "## Nodes",
        "",
    ]
    for node in graph.get("nodes", [])[:20]:
        lines.append(f"- `{node.get('node_id', '')}` ({node.get('kind', '')}) → `{node.get('label', '')}`")
    lines.extend(["", "## Edges", ""])
    for edge in graph.get("edges", [])[:30]:
        lines.append(f"- `{edge.get('kind', '')}`: `{edge.get('source_id', '')}` → `{edge.get('target_id', '')}`")
    lines.extend(["", "## Raw Graph", "", json.dumps(graph, indent=2, sort_keys=True)])
    return "\n".join(lines).rstrip() + "\n"


def _render_search_index_page(index: dict) -> str:
    stats = dict(index.get("stats", {}))
    lines = [
        "# Search Index",
        "",
        f"- City: `{index.get('city_id', '')}`",
        f"- Records: `{stats.get('record_count', 0)}`",
        "",
        "## Top Records",
        "",
    ]
    for record in index.get("records", [])[:25]:
        lines.append(
            f"- `{record.get('kind', '')}` `{record.get('title', '')}` → `{record.get('href', '')}` | tags: {', '.join(record.get('tags', [])[:5])}"
        )
    lines.extend(["", "## Raw Index", "", json.dumps(index, indent=2, sort_keys=True)])
    return "\n".join(lines).rstrip() + "\n"


def _resolve_current_lineage(*, identity: dict, git_manifest: dict, lineage_records: list[dict]) -> dict | None:
    repo_candidates = {
        str(identity.get("repo", "")),
        str(git_manifest.get("repo_ref", "")),
        str(git_manifest.get("origin_url", "")),
    }
    repo_candidates.discard("")
    for lineage in lineage_records:
        if str(lineage.get("repo", "")) in repo_candidates:
            return lineage
    return None


def _render_lineage_page(*, current_lineage: dict | None, lineage_records: list[dict]) -> str:
    lines = ["# Lineage", ""]
    if current_lineage:
        lines.extend(
            [
                "## Current Repo Lineage",
                "",
                f"- Repo: `{current_lineage.get('repo', '')}`",
                f"- Upstream Repo: `{current_lineage.get('upstream_repo', '')}`",
                f"- Line Root: `{current_lineage.get('line_root_repo', '')}`",
                f"- Fork Mode: `{current_lineage.get('fork_mode', '')}`",
                f"- Sync Policy: `{current_lineage.get('sync_policy', '')}`",
                f"- Space: `{current_lineage.get('space_id', '')}`",
                f"- Upstream Space: `{current_lineage.get('upstream_space_id', '')}`",
                "",
            ],
        )
    else:
        lines.extend(["No current lineage record is known for this repo.", ""])
    lines.extend(["## Known Lineage Records", ""])
    if lineage_records:
        lines.extend(
            f"- `{item.get('repo', '')}` ← `{item.get('upstream_repo', '')}` ({item.get('fork_mode', '')}/{item.get('sync_policy', '')})"
            for item in lineage_records
        )
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def _replace_block(content: str, start_marker: str, end_marker: str, new_block: str) -> str:
    wrapped = f"{start_marker}\n{new_block}\n{end_marker}"
    if start_marker in content and end_marker in content:
        before, remainder = content.split(start_marker, 1)
        _, after = remainder.split(end_marker, 1)
        return f"{before}{wrapped}{after}"
    return f"{content.rstrip()}\n\n{wrapped}\n"


def _append_wiki_suffix(path: str) -> str:
    stripped = _strip_git_suffix(path)
    return f"{stripped}.wiki.git"


def _strip_git_suffix(value: str) -> str:
    return value[:-4] if value.endswith(".git") else value


def _run_git(root: Path | str, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(Path(root).resolve()), capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _ensure_local_git_identity(root: Path) -> None:
    email = subprocess.run(["git", "config", "--get", "user.email"], cwd=str(root), capture_output=True, text=True)
    name = subprocess.run(["git", "config", "--get", "user.name"], cwd=str(root), capture_output=True, text=True)
    if not email.stdout.strip():
        subprocess.run(["git", "config", "user.email", "agent-internet@example.test"], cwd=str(root), check=True)
    if not name.stdout.strip():
        subprocess.run(["git", "config", "user.name", "Agent Internet"], cwd=str(root), check=True)


def _git_commit_all(root: Path, message: str) -> bool:
    subprocess.run(["git", "add", "."], cwd=str(root), check=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(root), capture_output=True, text=True, check=True)
    if not status.stdout.strip():
        return False
    subprocess.run(["git", "commit", "-m", message], cwd=str(root), check=True, capture_output=True, text=True)
    subprocess.run(["git", "push"], cwd=str(root), check=True, capture_output=True, text=True)
    return True