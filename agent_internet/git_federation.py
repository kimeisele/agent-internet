from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .agent_web import build_agent_web_manifest
from .authority_contracts import (
    AGENT_WORLD_PUBLIC_AUTHORITY_CONTRACT,
    STEWARD_PUBLIC_AUTHORITY_CONTRACT,
    build_authority_projection_documents,
    iter_public_authority_source_contracts,
)
from .agent_web_graph import build_agent_web_public_graph
from .agent_web_index import build_agent_web_search_index
from .node_health import (
    build_node_surface_snapshot,
    render_federation_status_page,
    render_node_health_page,
    render_repo_quality_page,
    render_surface_integrity_page,
)
from .publication_status import render_publication_status_page
from .agent_web_repo_graph_capabilities import render_agent_web_repo_graph_capability_page
from .agent_web_repo_graph_contracts import render_agent_web_repo_graph_contract_page
from .agent_web_semantic_capabilities import render_agent_web_semantic_capability_page
from .agent_web_semantic_contracts import render_agent_web_semantic_contract_page
from .file_locking import write_locked_json_value


STEWARD_PROTOCOL_REPO_ID = STEWARD_PUBLIC_AUTHORITY_CONTRACT.source_repo_id
AGENT_WORLD_REPO_ID = AGENT_WORLD_PUBLIC_AUTHORITY_CONTRACT.source_repo_id
STEWARD_PUBLIC_WIKI_BINDING_ID = STEWARD_PUBLIC_AUTHORITY_CONTRACT.binding_id
AGENT_WORLD_PUBLIC_WIKI_BINDING_ID = AGENT_WORLD_PUBLIC_AUTHORITY_CONTRACT.binding_id

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


def _authority_projection_snapshots(state_snapshot: dict) -> list[dict[str, Any]]:
    return [
        {
            "contract": contract,
            "view": _authority_view(state_snapshot, source_repo_id=contract.source_repo_id, binding_id=contract.binding_id),
        }
        for contract in iter_public_authority_source_contracts()
    ]


def render_wiki_projection(
    *,
    peer_descriptor: dict,
    state_snapshot: dict,
    assistant_snapshot: dict | None = None,
    publication_snapshot: dict | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, str]:
    identity = dict(peer_descriptor.get("identity", {}))
    git_manifest = dict(peer_descriptor.get("git_federation", {}))
    cities = list(state_snapshot.get("identities", []))
    services = list(state_snapshot.get("service_addresses", []))
    routes = list(state_snapshot.get("routes", []))
    lineage_records = list(state_snapshot.get("fork_lineage", []))
    current_lineage = _resolve_current_lineage(identity=identity, git_manifest=git_manifest, lineage_records=lineage_records)
    authority_snapshots = _authority_projection_snapshots(state_snapshot)
    authority_documents = build_authority_projection_documents(state_snapshot)
    authority_snapshots_by_repo = {snapshot["contract"].source_repo_id: snapshot for snapshot in authority_snapshots}
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
    for authority_snapshot in authority_snapshots:
        summary_lines.extend(_build_authority_home_summary_lines(authority_snapshot["view"], label=authority_snapshot["contract"].label))
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
        "Publication-Status.md": render_publication_status_page(publication_snapshot),
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
        "_Sidebar.md": _render_sidebar_page(authority_documents),
        "_Footer.md": _render_footer_page(),
    }
    for authority_document in authority_documents:
        authority_snapshot = authority_snapshots_by_repo.get(authority_document["source_repo_id"])
        if authority_snapshot is None:
            continue
        authority_view = authority_snapshot["view"]
        render_mode = authority_document.get("render_mode")
        if render_mode == "overview":
            pages[authority_document["href"]] = _render_authority_page(
                authority_view,
                title=authority_document["title"],
                label=authority_document["source_label"],
                source_repo_id=authority_document["source_repo_id"],
                binding_id=authority_document["binding_id"],
                empty_message=authority_document["empty_message"],
            )
        elif render_mode == "canonical_index":
            pages[authority_document["href"]] = _render_canonical_surface_page(
                authority_view,
                title=authority_document["title"],
                label=authority_document["source_label"],
                source_repo_id=authority_document["source_repo_id"],
                empty_message=authority_document["empty_message"],
                projected_documents=[
                    document
                    for document in authority_documents
                    if document.get("source_repo_id") == authority_document["source_repo_id"]
                    and document.get("render_mode") == "canonical_document"
                ],
            )
        elif render_mode == "canonical_document":
            pages[authority_document["href"]] = _render_canonical_document_page(
                authority_view,
                title=authority_document["title"],
                source_repo_id=authority_document["source_repo_id"],
                source_document_id=str(authority_document.get("source_document_id", "")),
            )
    node_surface = build_node_surface_snapshot(
        repo_root=repo_root,
        peer_descriptor=peer_descriptor,
        state_snapshot=state_snapshot,
        assistant_snapshot=assistant_snapshot,
        publication_snapshot=publication_snapshot,
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
        publication_snapshot=publication_snapshot,
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


def _authority_view(state_snapshot: dict, *, source_repo_id: str, binding_id: str) -> dict[str, Any]:
    role = next(
        (
            dict(record)
            for record in list(state_snapshot.get("repo_roles", []))
            if isinstance(record, dict) and str(record.get("repo_id", "")) == source_repo_id
        ),
        None,
    )
    publication_status = next(
        (
            dict(record)
            for record in list(state_snapshot.get("publication_statuses", []))
            if isinstance(record, dict) and str(record.get("binding_id", "")) == binding_id
        ),
        None,
    )
    exports_by_kind: dict[str, dict[str, Any]] = {}
    for record in list(state_snapshot.get("authority_exports", [])):
        if not isinstance(record, dict) or str(record.get("repo_id", "")) != source_repo_id:
            continue
        export_kind = str(record.get("export_kind", "")).strip()
        if export_kind:
            exports_by_kind[export_kind] = dict(record)
    artifacts_by_export_id = {
        str(record.get("export_id", "")): dict(record)
        for record in list(state_snapshot.get("authority_artifacts", []))
        if isinstance(record, dict)
    }
    artifacts_by_kind: dict[str, dict[str, Any]] = {}
    for export_kind, export_record in exports_by_kind.items():
        artifact_record = artifacts_by_export_id.get(str(export_record.get("export_id", "")))
        payload = artifact_record.get("payload") if artifact_record is not None else None
        if isinstance(payload, dict):
            artifacts_by_kind[export_kind] = dict(payload)
    return {
        "role": role,
        "publication_status": publication_status,
        "exports_by_kind": exports_by_kind,
        "artifacts_by_kind": artifacts_by_kind,
    }


def _agent_world_authority_view(state_snapshot: dict) -> dict[str, Any]:
    return _authority_view(state_snapshot, source_repo_id=AGENT_WORLD_REPO_ID, binding_id=AGENT_WORLD_PUBLIC_WIKI_BINDING_ID)


def _steward_authority_view(state_snapshot: dict) -> dict[str, Any]:
    return _authority_view(state_snapshot, source_repo_id=STEWARD_PROTOCOL_REPO_ID, binding_id=STEWARD_PUBLIC_WIKI_BINDING_ID)


def _build_authority_home_summary_lines(authority_view: dict[str, Any], *, label: str) -> list[str]:
    publication_status = authority_view.get("publication_status")
    exports_by_kind = dict(authority_view.get("exports_by_kind", {}))
    artifacts_by_kind = dict(authority_view.get("artifacts_by_kind", {}))
    canonical_payload = dict(artifacts_by_kind.get("canonical_surface", {}))
    if not publication_status and not exports_by_kind and not canonical_payload:
        return []
    status_labels = dict(publication_status.get("labels", {})) if isinstance(publication_status, dict) else {}
    documents = [record for record in list(canonical_payload.get("documents", [])) if isinstance(record, dict)]
    source_version = status_labels.get("source_export_version") or str(exports_by_kind.get("canonical_surface", {}).get("version", ""))
    source_status = str(publication_status.get("status", "missing")) if isinstance(publication_status, dict) else "missing"
    return [
        f"- {label} Projection Status: `{source_status}`",
        f"- {label} Source Export Version: `{source_version}`",
        f"- {label} Canonical Docs: `{len(documents)}`",
    ]


def _source_surface_records(source_registry: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = source_registry.get("documents") or source_registry.get("pages") or []
    return [record for record in list(candidates) if isinstance(record, dict)]


def _render_authority_page(
    authority_view: dict[str, Any],
    *,
    title: str,
    label: str,
    source_repo_id: str,
    binding_id: str,
    empty_message: str,
) -> str:
    role = authority_view.get("role") if isinstance(authority_view.get("role"), dict) else None
    publication_status = authority_view.get("publication_status") if isinstance(authority_view.get("publication_status"), dict) else None
    exports_by_kind = dict(authority_view.get("exports_by_kind", {}))
    artifacts_by_kind = dict(authority_view.get("artifacts_by_kind", {}))
    status_labels = dict(publication_status.get("labels", {})) if publication_status is not None else {}
    source_registry = dict(artifacts_by_kind.get("source_surface_registry", {}))
    summary_registry = dict(artifacts_by_kind.get("public_summary_registry", {}))
    metadata_payload = dict(artifacts_by_kind.get("surface_metadata", {}))
    repo_graph = dict(artifacts_by_kind.get("repo_graph", {}))
    source_records = _source_surface_records(source_registry)
    surface_registry = dict(metadata_payload.get("surface_registry", {}))
    lines = [
        f"# {title}",
        "",
        f"- Source Repo: `{source_repo_id}`",
        f"- Repo Role: `{role.get('role', 'missing') if role else 'missing'}`",
        f"- Publication Binding: `{binding_id}`",
        f"- Publication Status: `{publication_status.get('status', 'missing') if publication_status else 'missing'}`",
        f"- Projected From Export: `{publication_status.get('projected_from_export_id', '') if publication_status else ''}`",
        f"- Source Export Version: `{status_labels.get('source_export_version') or exports_by_kind.get('canonical_surface', {}).get('version', '')}`",
        f"- Source Export SHA256: `{status_labels.get('source_export_sha256', '')}`",
        f"- Authority Bundle Source SHA: `{status_labels.get('authority_bundle_source_sha', '')}`",
        f"- Imported Export Count: `{len(exports_by_kind)}`",
        f"- Declared Source Documents: `{len(source_records)}`",
        f"- Public Summary Records: `{len([record for record in list(summary_registry.get('records', [])) if isinstance(record, dict)])}`",
        f"- Repo Graph Nodes: `{dict(repo_graph.get('summary', {})).get('node_count', 0)}`",
        f"- Surface Metadata Documents: `{surface_registry.get('document_count', surface_registry.get('page_count', 0))}`",
        "",
    ]
    if not exports_by_kind:
        lines.extend([empty_message, ""])
        return "\n".join(lines).rstrip() + "\n"
    lines.extend([f"This page is rendered from imported {label.lower()} source-authority artifacts.", ""])
    lines.extend(["## Imported Authority Exports", ""])
    for export_kind in sorted(exports_by_kind):
        export_record = exports_by_kind[export_kind]
        lines.append(f"- `{export_kind}` → `{export_record.get('artifact_uri', '')}` (`{export_record.get('version', '')}`)")
    summary_records = [record for record in list(summary_registry.get("records", [])) if isinstance(record, dict)]
    if summary_records:
        lines.extend(["", "## Public Summaries", ""])
        for record in summary_records:
            title_value = record.get("title") or record.get("wiki_name") or record.get("id", "")
            lines.append(f"- **{title_value}** — {record.get('public_summary', '')}")
    if source_records:
        lines.extend(["", "## Source Surface Registry", ""])
        for record in source_records:
            title_value = record.get("wiki_name") or record.get("title") or record.get("document_id") or record.get("id", "")
            category = record.get("authority") or record.get("page_class") or record.get("section") or ""
            scope = record.get("domain") or record.get("source_path") or record.get("section") or ""
            lines.append(f"- `{title_value}` (`{category}` / `{scope}`)")
    return "\n".join(lines).rstrip() + "\n"


def _render_canonical_surface_page(
    authority_view: dict[str, Any],
    *,
    title: str,
    label: str,
    source_repo_id: str,
    empty_message: str,
    projected_documents: list[dict[str, Any]],
) -> str:
    publication_status = authority_view.get("publication_status") if isinstance(authority_view.get("publication_status"), dict) else None
    status_labels = dict(publication_status.get("labels", {})) if publication_status is not None else {}
    artifacts_by_kind = dict(authority_view.get("artifacts_by_kind", {}))
    canonical_payload = dict(artifacts_by_kind.get("canonical_surface", {}))
    lines = [
        f"# {title}",
        "",
        f"- Source Repo: `{source_repo_id}`",
        f"- Source Export Version: `{status_labels.get('source_export_version', '')}`",
        f"- Source Bundle SHA: `{status_labels.get('authority_bundle_source_sha', '')}`",
        "",
    ]
    documents = [record for record in list(canonical_payload.get("documents", [])) if isinstance(record, dict)]
    if not documents:
        lines.extend([empty_message, ""])
        return "\n".join(lines).rstrip() + "\n"
    lines.extend([f"This page is rendered from imported {label.lower()} `canonical_surface` authority artifacts.", ""])
    lines.extend(["## Projected Canonical Documents", ""])
    for document in projected_documents:
        source_document = _canonical_document_by_id(authority_view, str(document.get("source_document_id", "")))
        lines.append(
            f"- [[{document.get('title', '')}|{str(document.get('href', '')).removesuffix('.md')}]]"
            f" → `{source_document.get('source_path', '')}`"
        )
        public_summary = str(source_document.get("public_summary", "")).strip()
        if public_summary:
            lines.append(f"  - {public_summary}")
    return "\n".join(lines).rstrip() + "\n"


def _render_canonical_document_page(
    authority_view: dict[str, Any],
    *,
    title: str,
    source_repo_id: str,
    source_document_id: str,
) -> str:
    publication_status = authority_view.get("publication_status") if isinstance(authority_view.get("publication_status"), dict) else None
    status_labels = dict(publication_status.get("labels", {})) if publication_status is not None else {}
    document = _canonical_document_by_id(authority_view, source_document_id)
    lines = [
        f"# {title}",
        "",
        f"- Source Repo: `{source_repo_id}`",
        f"- Source Document ID: `{source_document_id}`",
        f"- Source Export Version: `{status_labels.get('source_export_version', '')}`",
        f"- Source Bundle SHA: `{status_labels.get('authority_bundle_source_sha', '')}`",
        f"- Source Path: `{document.get('source_path', '')}`",
    ]
    public_summary = str(document.get("public_summary", "")).strip()
    if public_summary:
        lines.append(f"- Public Summary: {public_summary}")
    lines.extend(["", str(document.get("content", "")).strip() or "_No canonical content available._", ""])
    return "\n".join(lines).rstrip() + "\n"


def _canonical_document_by_id(authority_view: dict[str, Any], source_document_id: str) -> dict[str, Any]:
    artifacts_by_kind = dict(authority_view.get("artifacts_by_kind", {}))
    canonical_payload = dict(artifacts_by_kind.get("canonical_surface", {}))
    return next(
        (
            dict(record)
            for record in list(canonical_payload.get("documents", []))
            if isinstance(record, dict) and str(record.get("document_id", "")) == source_document_id
        ),
        {},
    )


def _render_agent_world_authority_page(authority_view: dict[str, Any]) -> str:
    return _render_authority_page(
        authority_view,
        title="Agent World Authority",
        label="Agent World",
        source_repo_id=AGENT_WORLD_REPO_ID,
        binding_id=AGENT_WORLD_PUBLIC_WIKI_BINDING_ID,
        empty_message="No imported agent-world authority exports have been imported yet.",
    )


def _render_steward_authority_page(authority_view: dict[str, Any]) -> str:
    return _render_authority_page(
        authority_view,
        title="Steward Authority",
        label="Steward",
        source_repo_id=STEWARD_PROTOCOL_REPO_ID,
        binding_id=STEWARD_PUBLIC_WIKI_BINDING_ID,
        empty_message="No steward authority exports have been imported yet.",
    )


def _render_agent_world_canonical_surface_page(authority_view: dict[str, Any]) -> str:
    return _render_canonical_surface_page(
        authority_view,
        title="Agent World Canonical Surface",
        label="Agent World",
        source_repo_id=AGENT_WORLD_REPO_ID,
        empty_message="No imported agent-world canonical documents are available yet.",
        projected_documents=[],
    )


def _render_steward_canonical_surface_page(authority_view: dict[str, Any]) -> str:
    return _render_canonical_surface_page(
        authority_view,
        title="Steward Canonical Surface",
        label="Steward",
        source_repo_id=STEWARD_PROTOCOL_REPO_ID,
        empty_message="No imported steward canonical documents are available yet.",
        projected_documents=[],
    )


def _render_sidebar_page(authority_documents: tuple[dict[str, Any], ...]) -> str:
    links = [
        ("Home", "Home"),
        ("Node Health", "Node-Health"),
        ("Publication Status", "Publication-Status"),
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
    authority_links = [
        (
            str(document.get("sidebar_title") or document.get("title", "")),
            str(document.get("href", "")).removesuffix(".md"),
        )
        for document in authority_documents
        if document.get("render_mode") in {"overview", "canonical_index"} or document.get("sidebar")
    ]
    links = links[:8] + authority_links + links[8:]
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