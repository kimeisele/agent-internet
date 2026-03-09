from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .git_federation import detect_git_remote_metadata, ensure_git_checkout, render_wiki_projection
from .snapshot import ControlPlaneStateStore, snapshot_control_plane

DEFAULT_AGENT_INTERNET_CAPABILITIES = (
    "agent_web_manifest",
    "semantic_capability_manifest",
    "semantic_contract_manifest",
    "repo_graph_capability_manifest",
    "repo_graph_contract_manifest",
    "git_federation",
)

WIKI_GENERATED_INVENTORY = ".wiki-generated-inventory.json"


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
            "shared_pages": [
                "Home.md",
                "Assistant-Surface.md",
                "Git-Federation.md",
                "Agent-Web.md",
                "Semantic-Capabilities.md",
                "Semantic-Contracts.md",
                "Repo-Graph-Capabilities.md",
                "Repo-Graph-Contracts.md",
                "Public-Graph.md",
                "Search-Index.md",
                "Lineage.md",
            ],
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
    pages = _render_pages(root=root, state_path=state_path, city_id=city_id)
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
    pages = _render_pages(root=repo_root, state_path=state_path, city_id=city_id)
    generated_paths = sorted(_normalize_relative_paths(pages))
    for relative_path, content in pages.items():
        target = checkout / _normalize_relative_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    pruned = _prune_generated_paths(checkout, keep_paths=generated_paths) if prune_generated else []
    _write_generated_inventory(checkout, generated_paths)
    source_sha = _git_output(["rev-parse", "HEAD"], cwd=repo_root).strip() or "unknown"
    commit_message = f"agent-web: publish surfaces from {source_sha}"
    changed = _git_commit_all(checkout, commit_message, push=push)
    return {
        "changed": changed,
        "built": len(pages),
        "generated_inventory": str(checkout / WIKI_GENERATED_INVENTORY),
        "prune_generated": prune_generated,
        "pruned": len(pruned),
        "pruned_paths": pruned,
        "wiki_path": str(checkout),
        "wiki_repo_url": effective_wiki_repo_url,
        "pushed": bool(push and changed),
        "source_sha": source_sha,
        "commit_message": commit_message,
    }


def write_publication_result(path: Path | str, result: dict) -> Path:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return target


def _render_pages(*, root: Path | str, state_path: Path | str, city_id: str) -> dict[str, str]:
    store = ControlPlaneStateStore(path=Path(state_path))
    peer_descriptor = build_agent_internet_peer_descriptor(root, city_id=city_id)
    return render_wiki_projection(
        peer_descriptor=peer_descriptor,
        state_snapshot=snapshot_control_plane(store.load()),
        assistant_snapshot=None,
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