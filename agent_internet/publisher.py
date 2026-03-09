from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .agent_web import DOCUMENT_SPECS
from .git_federation import detect_git_remote_metadata, ensure_git_checkout, render_wiki_projection
from .publication_status import DEFAULT_PUBLICATION_WORKFLOW_NAME, build_publication_snapshot, sanitize_remote_url
from .snapshot import ControlPlaneStateStore, snapshot_control_plane

DEFAULT_AGENT_INTERNET_CAPABILITIES = (
    "agent_web_manifest",
    "semantic_capability_manifest",
    "semantic_contract_manifest",
    "repo_graph_capability_manifest",
    "repo_graph_contract_manifest",
    "git_federation",
    "node_health_surface",
)

WIKI_GENERATED_INVENTORY = ".wiki-generated-inventory.json"
PUBLICATION_METADATA_PATH = ".agent-web-publication.json"


def probe_wiki_remote(wiki_repo_url: str) -> dict:
    result = subprocess.run(["git", "ls-remote", wiki_repo_url], capture_output=True, text=True)
    return {
        "kind": "agent_internet_wiki_remote_probe",
        "wiki_repo_url": wiki_repo_url,
        "reachable": result.returncode == 0,
        "stderr": result.stderr.strip(),
    }


def build_agent_internet_peer_descriptor(root: Path | str, *, city_id: str = "agent-internet") -> dict:
    remote = detect_git_remote_metadata(root)
    return {
        "identity": {"city_id": city_id, "slug": city_id, "repo": remote.repo_ref, "public_key": ""},
        "endpoint": {"city_id": city_id, "transport": "git", "location": str(remote.repo_root)},
        "capabilities": list(DEFAULT_AGENT_INTERNET_CAPABILITIES),
        "git_federation": {
            "repo_root": str(remote.repo_root),
            "origin_url": remote.origin_url,
            "repo_ref": remote.repo_ref,
            "wiki_repo_url": remote.wiki_repo_url,
            "city_id": city_id,
            "shared_pages": [href for _document_id, _rel, _kind, _title, href, _entrypoint in DOCUMENT_SPECS],
        },
    }


def build_agent_internet_wiki(
    *,
    root: Path | str,
    output_dir: Path | str,
    state_path: Path | str,
    city_id: str = "agent-internet",
) -> list[Path]:
    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    pages = _render_pages(root=root, state_path=state_path, city_id=city_id, publication_snapshot=None)
    built: list[Path] = []
    for relative_path, content in pages.items():
        path = target / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        built.append(path)
    return built


def publish_agent_internet_wiki(
    *,
    root: Path | str,
    state_path: Path | str,
    wiki_path: Path | None = None,
    wiki_repo_url: str | None = None,
    push: bool = False,
    prune_generated: bool = False,
    city_id: str = "agent-internet",
) -> dict:
    repo_root = Path(root).resolve()
    peer_descriptor = build_agent_internet_peer_descriptor(repo_root, city_id=city_id)
    effective_wiki_repo_url = wiki_repo_url or str(peer_descriptor["git_federation"]["wiki_repo_url"])
    probe = probe_wiki_remote(effective_wiki_repo_url)
    if not probe["reachable"]:
        raise RuntimeError(f"wiki_remote_unavailable:{effective_wiki_repo_url}:{probe['stderr'] or 'git ls-remote failed'}")
    checkout = ensure_git_checkout(effective_wiki_repo_url, wiki_path or (repo_root / ".agent_internet" / "wiki"))
    _ensure_local_git_identity(checkout)
    source_sha = _git_output(["rev-parse", "HEAD"], cwd=repo_root).strip() or "unknown"
    commit_message = f"agent-web: publish surfaces from {source_sha}"
    publication_snapshot = build_publication_snapshot(
        source_sha=source_sha,
        wiki_repo_url=effective_wiki_repo_url,
        status="published",
        workflow_name=DEFAULT_PUBLICATION_WORKFLOW_NAME,
        push_requested=push,
        prune_generated=prune_generated,
        commit_message=commit_message,
    )
    pages = _render_pages(
        root=repo_root,
        state_path=state_path,
        city_id=city_id,
        publication_snapshot=publication_snapshot,
    )
    generated_paths = sorted(_normalize_relative_paths(pages) + [PUBLICATION_METADATA_PATH])
    for relative_path, content in pages.items():
        target = checkout / _normalize_relative_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    write_publication_result(checkout / PUBLICATION_METADATA_PATH, publication_snapshot)
    pruned = _prune_generated_paths(checkout, keep_paths=generated_paths) if prune_generated else []
    _write_generated_inventory(checkout, generated_paths)
    changed = _git_commit_all(checkout, commit_message, push=push)
    return {
        "changed": changed,
        "built": len(pages),
        "generated_inventory": str(checkout / WIKI_GENERATED_INVENTORY),
        "prune_generated": prune_generated,
        "pruned": len(pruned),
        "pruned_paths": pruned,
        "wiki_path": str(checkout),
        "wiki_repo_url": sanitize_remote_url(effective_wiki_repo_url),
        "pushed": bool(push and changed),
        "source_sha": source_sha,
        "published_at_utc": publication_snapshot["published_at_utc"],
        "commit_message": commit_message,
    }


def write_publication_result(path: Path | str, result: dict) -> Path:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return target


def _render_pages(*, root: Path | str, state_path: Path | str, city_id: str, publication_snapshot: dict | None) -> dict[str, str]:
    repo_root = Path(root).resolve()
    store = ControlPlaneStateStore(path=Path(state_path))
    peer_descriptor = build_agent_internet_peer_descriptor(root, city_id=city_id)
    effective_publication_snapshot = publication_snapshot or build_publication_snapshot(
        source_sha=_git_output(["rev-parse", "HEAD"], cwd=repo_root).strip() or "unknown",
        wiki_repo_url=str(peer_descriptor.get("git_federation", {}).get("wiki_repo_url", "")),
        status="build_preview",
        workflow_name="local_build",
        push_requested=False,
        prune_generated=False,
        commit_message="agent-web: local build preview",
    )
    return render_wiki_projection(
        peer_descriptor=peer_descriptor,
        state_snapshot=snapshot_control_plane(store.load()),
        assistant_snapshot=None,
        publication_snapshot=effective_publication_snapshot,
        repo_root=repo_root,
    )


def _ensure_local_git_identity(root: Path) -> None:
    email = subprocess.run(["git", "config", "--get", "user.email"], cwd=str(root), capture_output=True, text=True)
    name = subprocess.run(["git", "config", "--get", "user.name"], cwd=str(root), capture_output=True, text=True)
    if not email.stdout.strip():
        subprocess.run(["git", "config", "user.email", "agent-internet@example.test"], cwd=str(root), check=True)
    if not name.stdout.strip():
        subprocess.run(["git", "config", "user.name", "Agent Internet"], cwd=str(root), check=True)


def _git_commit_all(root: Path, message: str, *, push: bool) -> bool:
    subprocess.run(["git", "add", "."], cwd=str(root), check=True, capture_output=True, text=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(root), check=True, capture_output=True, text=True)
    if not status.stdout.strip():
        return False
    subprocess.run(["git", "commit", "-m", message], cwd=str(root), check=True, capture_output=True, text=True)
    if push:
        subprocess.run(["git", "push"], cwd=str(root), check=True, capture_output=True, text=True)
    return True


def _git_output(args: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)
    return completed.stdout


def _normalize_relative_paths(pages: dict[str, str]) -> list[str]:
    return [_normalize_relative_path(path) for path in pages]


def _normalize_relative_path(path: str) -> str:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe wiki relative path: {path}")
    return relative.as_posix()


def _read_generated_inventory(root: Path) -> list[str]:
    path = root / WIKI_GENERATED_INVENTORY
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    files = payload.get("files", [])
    return [_normalize_relative_path(str(item)) for item in files]


def _write_generated_inventory(root: Path, files: list[str]) -> Path:
    path = root / WIKI_GENERATED_INVENTORY
    payload = {
        "kind": "generated_wiki_inventory",
        "version": 1,
        "files": sorted({_normalize_relative_path(path) for path in files}),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _prune_generated_paths(root: Path, *, keep_paths: list[str]) -> list[str]:
    keep = set(_normalize_relative_path(path) for path in keep_paths)
    stale = [path for path in _read_generated_inventory(root) if path not in keep]
    removed: list[str] = []
    for relative_path in stale:
        target = root / relative_path
        if target.exists():
            target.unlink()
            _prune_empty_parent_dirs(target.parent, stop=root)
            removed.append(relative_path)
    return removed


def _prune_empty_parent_dirs(path: Path, *, stop: Path) -> None:
    current = path
    while current != stop and current.exists():
        if any(current.iterdir()):
            return
        current.rmdir()
        current = current.parent