from __future__ import annotations

import json
import subprocess
from pathlib import Path


def build_node_surface_snapshot(
    *,
    repo_root: Path | str | None,
    peer_descriptor: dict,
    state_snapshot: dict,
    assistant_snapshot: dict | None,
    publication_snapshot: dict | None,
    rendered_pages: dict[str, str],
    agent_web: dict,
) -> dict:
    root = Path(repo_root).resolve() if repo_root else None
    repo_quality = _build_repo_quality_snapshot(root)
    publication_status = _build_publication_status_snapshot(publication_snapshot)
    federation_status = _build_federation_status_snapshot(
        peer_descriptor=peer_descriptor,
        state_snapshot=state_snapshot,
        assistant_snapshot=assistant_snapshot,
    )
    surface_integrity = _build_surface_integrity_snapshot(
        rendered_pages=rendered_pages,
        agent_web=agent_web,
        git_manifest=dict(peer_descriptor.get("git_federation", {})),
    )
    node_health = _build_node_health_snapshot(
        peer_descriptor=peer_descriptor,
        assistant_snapshot=assistant_snapshot,
        repo_quality=repo_quality,
        publication_status=publication_status,
        federation_status=federation_status,
        surface_integrity=surface_integrity,
    )
    return {
        "kind": "agent_internet_node_surface",
        "version": 1,
        "node_health": node_health,
        "publication_status": publication_status,
        "surface_integrity": surface_integrity,
        "repo_quality": repo_quality,
        "federation_status": federation_status,
    }


def render_node_health_page(snapshot: dict) -> str:
    health = dict(snapshot.get("node_health", {}))
    lines = [
        "# Node Health",
        "",
        f"- Status: `{health.get('status', 'unknown')}`",
        f"- Summary: {health.get('summary', 'no summary')}",
        f"- City: `{health.get('city_id', '')}`",
        f"- Repo: `{health.get('repo', '')}`",
        f"- Surface Pages: `{health.get('surface_page_count', 0)}`",
        f"- Known Cities: `{health.get('known_city_count', 0)}`",
        f"- Services: `{health.get('service_count', 0)}`",
        f"- Routes: `{health.get('route_count', 0)}`",
        f"- Assistant Published: `{health.get('assistant_published', False)}`",
        f"- Publication Status: `{health.get('publication_status', '')}`",
        f"- Published At (UTC): `{health.get('published_at_utc', '')}`",
        f"- Publication Source SHA: `{health.get('publication_source_sha', '')}`",
        f"- Stale After (s): `{health.get('stale_after_seconds')}`",
        f"- Worktree Dirty (tracked): `{health.get('tracked_worktree_dirty', False)}`",
        "",
        "## Anomalies",
        "",
    ]
    anomalies = list(health.get("anomalies", []))
    if anomalies:
        lines.extend(f"- `{item}`" for item in anomalies)
    else:
        lines.append("- none")
    lines.extend(["", "## Raw Snapshot", "", json.dumps(health, indent=2, sort_keys=True)])
    return "\n".join(lines).rstrip() + "\n"


def render_surface_integrity_page(snapshot: dict) -> str:
    integrity = dict(snapshot.get("surface_integrity", {}))
    lines = [
        "# Surface Integrity",
        "",
        f"- Status: `{integrity.get('status', 'unknown')}`",
        f"- Rendered Pages: `{integrity.get('rendered_page_count', 0)}`",
        f"- Declared Documents: `{integrity.get('declared_document_count', 0)}`",
        f"- Shared Pages: `{integrity.get('shared_page_count', 0)}`",
        f"- Missing Declared Documents: `{len(integrity.get('missing_declared_documents', []))}`",
        f"- Missing Shared Pages: `{len(integrity.get('missing_shared_pages', []))}`",
        f"- Empty Pages: `{len(integrity.get('empty_pages', []))}`",
        "",
        "## Missing Declared Documents",
        "",
    ]
    missing_docs = list(integrity.get("missing_declared_documents", []))
    if missing_docs:
        lines.extend(f"- `{item}`" for item in missing_docs)
    else:
        lines.append("- none")
    lines.extend(["", "## Rendered but Undeclared", ""])
    extra = list(integrity.get("rendered_but_undeclared", []))
    if extra:
        lines.extend(f"- `{item}`" for item in extra)
    else:
        lines.append("- none")
    lines.extend(["", "## Raw Snapshot", "", json.dumps(integrity, indent=2, sort_keys=True)])
    return "\n".join(lines).rstrip() + "\n"


def render_repo_quality_page(snapshot: dict) -> str:
    quality = dict(snapshot.get("repo_quality", {}))
    lines = [
        "# Repo Quality",
        "",
        f"- Status: `{quality.get('status', 'unknown')}`",
        f"- Branch: `{quality.get('branch', '')}`",
        f"- Source SHA: `{quality.get('source_sha', '')}`",
        f"- Tracked Files: `{quality.get('tracked_file_count', 0)}`",
        f"- Python Files: `{quality.get('python_file_count', 0)}`",
        f"- Package Files: `{quality.get('package_python_file_count', 0)}`",
        f"- Test Files: `{quality.get('test_file_count', 0)}`",
        f"- Workflow Files: `{quality.get('workflow_file_count', 0)}`",
        f"- Markdown Files: `{quality.get('markdown_file_count', 0)}`",
        f"- Has pyproject: `{quality.get('has_pyproject', False)}`",
        f"- Has tests: `{quality.get('has_tests', False)}`",
        f"- Has workflows: `{quality.get('has_workflows', False)}`",
        f"- Worktree Dirty (tracked): `{quality.get('tracked_worktree_dirty', False)}`",
        "",
        "## Raw Snapshot",
        "",
        json.dumps(quality, indent=2, sort_keys=True),
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_federation_status_page(snapshot: dict) -> str:
    status = dict(snapshot.get("federation_status", {}))
    lines = [
        "# Federation Status",
        "",
        f"- Status: `{status.get('status', 'unknown')}`",
        f"- City: `{status.get('city_id', '')}`",
        f"- Repo: `{status.get('repo', '')}`",
        f"- Origin: `{status.get('origin_url', '')}`",
        f"- Wiki: `{status.get('wiki_repo_url', '')}`",
        f"- Capabilities: `{status.get('capability_count', 0)}`",
        f"- Shared Pages: `{status.get('shared_page_count', 0)}`",
        f"- Known Cities: `{status.get('known_city_count', 0)}`",
        f"- Services: `{status.get('service_count', 0)}`",
        f"- Routes: `{status.get('route_count', 0)}`",
        f"- Lineage Records: `{status.get('lineage_count', 0)}`",
        "",
        "## Shared Surface Pages",
        "",
    ]
    shared_pages = list(status.get("shared_pages", []))
    if shared_pages:
        lines.extend(f"- `{item}`" for item in shared_pages)
    else:
        lines.append("- none")
    lines.extend(["", "## Raw Snapshot", "", json.dumps(status, indent=2, sort_keys=True)])
    return "\n".join(lines).rstrip() + "\n"


def _build_publication_status_snapshot(snapshot: dict | None) -> dict:
    status = dict(snapshot or {})
    published_at_utc = str(status.get("published_at_utc", ""))
    stale_after_seconds = status.get("stale_after_seconds")
    return {
        "status": str(status.get("status", "unknown")),
        "published_at_utc": published_at_utc,
        "source_sha": str(status.get("source_sha", "")),
        "workflow_name": str(status.get("workflow_name", "")),
        "push_requested": bool(status.get("push_requested", False)),
        "prune_generated": bool(status.get("prune_generated", False)),
        "heartbeat_enabled": bool(status.get("heartbeat_enabled", False)),
        "schedule_interval_seconds": status.get("schedule_interval_seconds"),
        "stale_after_seconds": stale_after_seconds,
        "wiki_repo_url": str(status.get("wiki_repo_url", "")),
        "commit_message": str(status.get("commit_message", "")),
        "has_staleness_contract": bool(published_at_utc and stale_after_seconds),
    }


def _build_node_health_snapshot(
    *,
    peer_descriptor: dict,
    assistant_snapshot: dict | None,
    repo_quality: dict,
    publication_status: dict,
    federation_status: dict,
    surface_integrity: dict,
) -> dict:
    identity = dict(peer_descriptor.get("identity", {}))
    anomalies: list[str] = []
    if surface_integrity.get("missing_declared_documents"):
        anomalies.append("surface_missing_declared_documents")
    if surface_integrity.get("missing_shared_pages"):
        anomalies.append("surface_missing_shared_pages")
    if surface_integrity.get("empty_pages"):
        anomalies.append("surface_empty_pages")
    if not federation_status.get("wiki_repo_configured", False):
        anomalies.append("federation_wiki_repo_unconfigured")

    assistant_published = bool(str((assistant_snapshot or {}).get("assistant_id", "")).strip())
    known_city_count = int(federation_status.get("known_city_count", 0))
    service_count = int(federation_status.get("service_count", 0))
    route_count = int(federation_status.get("route_count", 0))
    if anomalies:
        status = "degraded"
    elif not assistant_published and known_city_count == 0 and service_count == 0 and route_count == 0:
        status = "quiet"
    else:
        status = "healthy"
    return {
        "status": status,
        "summary": f"{status}; {surface_integrity.get('rendered_page_count', 0)} pages, {service_count} services, {route_count} routes",
        "city_id": str(identity.get("city_id", "")),
        "repo": str(identity.get("repo", "")),
        "surface_page_count": int(surface_integrity.get("rendered_page_count", 0)),
        "known_city_count": known_city_count,
        "service_count": service_count,
        "route_count": route_count,
        "assistant_published": assistant_published,
        "publication_status": str(publication_status.get("status", "unknown")),
        "published_at_utc": str(publication_status.get("published_at_utc", "")),
        "publication_source_sha": str(publication_status.get("source_sha", "")),
        "stale_after_seconds": publication_status.get("stale_after_seconds"),
        "tracked_worktree_dirty": bool(repo_quality.get("tracked_worktree_dirty", False)),
        "anomalies": anomalies,
    }


def _build_surface_integrity_snapshot(*, rendered_pages: dict[str, str], agent_web: dict, git_manifest: dict) -> dict:
    rendered_paths = sorted(rendered_pages)
    declared_documents = sorted(
        {
            str(document.get("href", ""))
            for document in agent_web.get("documents", [])
            if str(document.get("href", "")).endswith(".md")
        },
    )
    shared_pages = sorted(
        {
            str(item)
            for item in git_manifest.get("shared_pages", [])
            if str(item).endswith(".md")
        },
    )
    missing_declared_documents = sorted(set(declared_documents) - set(rendered_paths))
    missing_shared_pages = sorted(set(shared_pages) - set(rendered_paths))
    rendered_but_undeclared = sorted(
        path for path in rendered_paths if path.endswith(".md") and not path.startswith("_") and path not in declared_documents
    )
    empty_pages = sorted(path for path, content in rendered_pages.items() if not str(content).strip())
    compact_pages = sorted(
        path for path, content in rendered_pages.items() if path.endswith(".md") and _nonempty_line_count(content) <= 4
    )
    status = "degraded" if missing_declared_documents or missing_shared_pages or empty_pages else "healthy"
    return {
        "status": status,
        "rendered_page_count": len(rendered_paths),
        "rendered_pages": rendered_paths,
        "declared_document_count": len(declared_documents),
        "declared_documents": declared_documents,
        "shared_page_count": len(shared_pages),
        "shared_pages": shared_pages,
        "missing_declared_documents": missing_declared_documents,
        "missing_shared_pages": missing_shared_pages,
        "rendered_but_undeclared": rendered_but_undeclared,
        "empty_pages": empty_pages,
        "compact_pages": compact_pages,
    }


def _build_repo_quality_snapshot(repo_root: Path | None) -> dict:
    if repo_root is None:
        return {
            "status": "unknown",
            "branch": "",
            "source_sha": "",
            "tracked_file_count": 0,
            "python_file_count": 0,
            "package_python_file_count": 0,
            "test_file_count": 0,
            "workflow_file_count": 0,
            "markdown_file_count": 0,
            "has_pyproject": False,
            "has_tests": False,
            "has_workflows": False,
            "tracked_worktree_dirty": False,
        }
    tracked_files = _git_lines(repo_root, "ls-files")
    python_files = [path for path in tracked_files if path.endswith(".py")]
    package_python_files = [path for path in python_files if path.startswith("agent_internet/")]
    test_files = [path for path in python_files if path.startswith("tests/")]
    workflow_files = [
        path for path in tracked_files if path.startswith(".github/workflows/") and (path.endswith(".yml") or path.endswith(".yaml"))
    ]
    markdown_files = [path for path in tracked_files if path.endswith(".md")]
    tracked_worktree_dirty = bool(_git_output(repo_root, "status", "--porcelain", "--untracked-files=no"))
    status = "instrumented" if test_files and workflow_files else "minimal"
    return {
        "status": status,
        "branch": _git_output(repo_root, "branch", "--show-current"),
        "source_sha": _git_output(repo_root, "rev-parse", "HEAD"),
        "tracked_file_count": len(tracked_files),
        "python_file_count": len(python_files),
        "package_python_file_count": len(package_python_files),
        "test_file_count": len(test_files),
        "workflow_file_count": len(workflow_files),
        "markdown_file_count": len(markdown_files),
        "has_pyproject": "pyproject.toml" in tracked_files,
        "has_tests": bool(test_files),
        "has_workflows": bool(workflow_files),
        "tracked_worktree_dirty": tracked_worktree_dirty,
    }


def _build_federation_status_snapshot(*, peer_descriptor: dict, state_snapshot: dict, assistant_snapshot: dict | None) -> dict:
    identity = dict(peer_descriptor.get("identity", {}))
    git_manifest = dict(peer_descriptor.get("git_federation", {}))
    capabilities = [str(item) for item in peer_descriptor.get("capabilities", [])]
    shared_pages = [str(item) for item in git_manifest.get("shared_pages", []) if str(item).endswith(".md")]
    known_city_count = len(list(state_snapshot.get("identities", [])))
    service_count = len(list(state_snapshot.get("service_addresses", [])))
    route_count = len(list(state_snapshot.get("routes", [])))
    lineage_count = len(list(state_snapshot.get("fork_lineage", [])))
    assistant_published = bool(str((assistant_snapshot or {}).get("assistant_id", "")).strip())
    if service_count or route_count or known_city_count > 1:
        status = "networked"
    elif assistant_published:
        status = "active"
    else:
        status = "standalone"
    return {
        "status": status,
        "city_id": str(identity.get("city_id", "")),
        "repo": str(identity.get("repo", "")),
        "origin_url": str(git_manifest.get("origin_url", "")),
        "wiki_repo_url": str(git_manifest.get("wiki_repo_url", "")),
        "wiki_repo_configured": bool(str(git_manifest.get("wiki_repo_url", "")).strip()),
        "capability_count": len(capabilities),
        "capabilities": capabilities,
        "shared_page_count": len(shared_pages),
        "shared_pages": shared_pages,
        "known_city_count": known_city_count,
        "service_count": service_count,
        "route_count": route_count,
        "lineage_count": lineage_count,
    }


def _git_lines(repo_root: Path, *args: str) -> list[str]:
    output = _git_output(repo_root, *args)
    return [line for line in output.splitlines() if line.strip()]


def _git_output(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=str(repo_root), check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _nonempty_line_count(content: str) -> int:
    return len([line for line in str(content).splitlines() if line.strip()])