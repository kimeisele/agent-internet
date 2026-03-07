from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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
        subprocess.run(["git", "pull", "--rebase"], cwd=str(checkout), check=True, capture_output=True, text=True)
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

    def sync(self, *, peer_descriptor: dict, state_snapshot: dict, heartbeat_label: str = "manual") -> dict:
        wiki_path = self._ensure_checkout()
        pages = render_wiki_projection(peer_descriptor=peer_descriptor, state_snapshot=state_snapshot)
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


def render_wiki_projection(*, peer_descriptor: dict, state_snapshot: dict) -> dict[str, str]:
    identity = dict(peer_descriptor.get("identity", {}))
    git_manifest = dict(peer_descriptor.get("git_federation", {}))
    cities = list(state_snapshot.get("identities", []))
    services = list(state_snapshot.get("service_addresses", []))
    routes = list(state_snapshot.get("routes", []))
    summary = "\n".join(
        [
            f"## Connected City: {identity.get('city_id', 'unknown')}",
            f"- Repo: `{identity.get('repo', '')}`",
            f"- Origin: `{git_manifest.get('origin_url', '')}`",
            f"- Wiki: `{git_manifest.get('wiki_repo_url', '')}`",
            f"- Known Cities: `{len(cities)}`",
            f"- Services: `{len(services)}`",
            f"- Routes: `{len(routes)}`",
        ],
    )
    home = _replace_block("# Agent Internet Federation\n\n", HOME_SUMMARY_START, HOME_SUMMARY_END, summary)
    cities_md = "# Cities\n\n" + "\n".join(f"- `{item['city_id']}` → `{item['repo']}`" for item in cities)
    services_md = "# Services\n\n" + "\n".join(
        f"- `{item['service_id']}` → `{item['public_handle']}` @ `{item['location']}`" for item in services
    )
    routes_md = "# Routes\n\n" + "\n".join(
        f"- `{item['destination_prefix']}` via `{item['next_hop_city_id']}` ({item['nadi_type']}/{item['priority']})"
        for item in routes
    )
    manifest_md = "# Git Federation\n\n" + json.dumps(git_manifest, indent=2, sort_keys=True)
    return {
        "Home.md": home,
        "Cities.md": cities_md.rstrip() + "\n",
        "Services.md": services_md.rstrip() + "\n",
        "Routes.md": routes_md.rstrip() + "\n",
        "Git-Federation.md": manifest_md.rstrip() + "\n",
    }


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