from __future__ import annotations

from dataclasses import asdict
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from .agent_web import build_document_specs
from .git_federation import detect_git_remote_metadata, ensure_git_checkout, render_wiki_projection
from .models import PublicationState, PublicationStatusRecord
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
            "shared_pages": [href for _document_id, _rel, _kind, _title, href, _entrypoint in build_document_specs({})],
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
    source_sha = _git_output(["rev-parse", "HEAD"], cwd=repo_root).strip() or "unknown"
    commit_message = f"agent-web: publish surfaces from {source_sha}"
    projection_context = _prepare_projection_publication(
        state_path=state_path,
        wiki_repo_url=effective_wiki_repo_url,
        operator_source_sha=source_sha,
        push_requested=push,
        commit_message=commit_message,
    )
    if projection_context is not None and projection_context["status"] == PublicationState.BLOCKED:
        raise RuntimeError(str(projection_context["failure_reason"]))
    try:
        probe = probe_wiki_remote(effective_wiki_repo_url)
        if not probe["reachable"]:
            raise RuntimeError(f"wiki_remote_unavailable:{effective_wiki_repo_url}:{probe['stderr'] or 'git ls-remote failed'}")
        checkout = ensure_git_checkout(effective_wiki_repo_url, wiki_path or (repo_root / ".agent_internet" / "wiki"))
        _ensure_local_git_identity(checkout)
        publication_snapshot = build_publication_snapshot(
            source_sha=source_sha,
            wiki_repo_url=effective_wiki_repo_url,
            status="published",
            workflow_name=DEFAULT_PUBLICATION_WORKFLOW_NAME,
            push_requested=push,
            prune_generated=prune_generated,
            commit_message=commit_message,
        )
        success_status_preview = _preview_projection_publication_outcome(
            state_path=state_path,
            wiki_repo_url=effective_wiki_repo_url,
            operator_source_sha=source_sha,
            push_requested=push,
            commit_message=commit_message,
            status=PublicationState.SUCCESS,
        )
        pages = _render_pages(
            root=repo_root,
            state_path=state_path,
            city_id=city_id,
            publication_snapshot=publication_snapshot,
            publication_status_overrides=success_status_preview,
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
    except Exception as exc:
        failure_statuses = _record_projection_publication_outcome(
            state_path=state_path,
            wiki_repo_url=effective_wiki_repo_url,
            operator_source_sha=source_sha,
            push_requested=push,
            commit_message=commit_message,
            status=PublicationState.FAILED,
            failure_reason=f"projection_publish_failed:{type(exc).__name__}:{exc}",
        )
        if failure_statuses:
            raise RuntimeError(f"{exc} [binding={failure_statuses[0].binding_id}]") from exc
        raise
    success_statuses = _record_projection_publication_outcome(
        state_path=state_path,
        wiki_repo_url=effective_wiki_repo_url,
        operator_source_sha=source_sha,
        push_requested=push,
        commit_message=commit_message,
        status=PublicationState.SUCCESS,
    )
    result = {
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
    if success_statuses:
        result["updated_binding_ids"] = [record.binding_id for record in success_statuses]
        result["publication_states"] = {record.binding_id: record.status.value for record in success_statuses}
        if len(success_statuses) == 1:
            result["binding_id"] = success_statuses[0].binding_id
            result["publication_state"] = success_statuses[0].status.value
    return result


def write_publication_result(path: Path | str, result: dict) -> Path:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return target


def _render_pages(*, root: Path | str, state_path: Path | str, city_id: str, publication_snapshot: dict | None, publication_status_overrides: list[PublicationStatusRecord] | None = None) -> dict[str, str]:
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
    state_snapshot = snapshot_control_plane(store.load())
    if publication_status_overrides:
        override_payloads = {record.binding_id: asdict(record) for record in publication_status_overrides}
        merged_statuses: list[dict] = []
        seen_binding_ids: set[str] = set()
        for record in list(state_snapshot.get("publication_statuses", [])):
            if not isinstance(record, dict):
                continue
            binding_id = str(record.get("binding_id", ""))
            override = override_payloads.get(binding_id)
            if override is not None:
                merged_statuses.append(override)
                seen_binding_ids.add(binding_id)
            else:
                merged_statuses.append(record)
        for binding_id, override in override_payloads.items():
            if binding_id not in seen_binding_ids:
                merged_statuses.append(override)
        state_snapshot["publication_statuses"] = merged_statuses
    return render_wiki_projection(
        peer_descriptor=peer_descriptor,
        state_snapshot=state_snapshot,
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


def _normalize_target_locator(locator: str | None) -> str:
    value = sanitize_remote_url(locator).strip()
    if not value:
        return ""
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme == "file":
            return str(Path(parsed.path).resolve())
        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return f"{host}/{parsed.path.lstrip('/')}".strip("/")
    if "@" in value and ":" in value and not value.startswith(("/", "./", "../")):
        prefix, path = value.split(":", 1)
        return f"{prefix.split('@', 1)[-1]}/{path.lstrip('/')}".strip("/")
    candidate = Path(value)
    if candidate.is_absolute():
        return str(candidate.resolve())
    return value.strip("/")


def _matching_projection_bindings(plane, *, wiki_repo_url: str):
    normalized_target = _normalize_target_locator(wiki_repo_url)
    if not normalized_target:
        return []
    matches = []
    for binding in plane.registry.list_projection_bindings():
        if binding.target_kind != "github_wiki":
            continue
        if _normalize_target_locator(binding.target_locator) == normalized_target:
            matches.append(binding)
    return matches


def _publication_status_labels(*, existing: PublicationStatusRecord | None, export, operator_source_sha: str, wiki_repo_url: str, push_requested: bool, commit_message: str) -> dict[str, str]:
    labels = dict(existing.labels if existing is not None else {})
    labels.update(
        {
            "operator_source_sha": operator_source_sha,
            "projection_target_locator": _normalize_target_locator(wiki_repo_url),
            "projection_target_url": sanitize_remote_url(wiki_repo_url),
            "push_requested": "true" if push_requested else "false",
            "operator_commit_message": commit_message,
        },
    )
    if export is not None:
        labels["source_export_version"] = export.version
        labels["source_export_sha256"] = export.content_sha256
    else:
        labels.pop("source_export_version", None)
        labels.pop("source_export_sha256", None)
    return labels


def _prepare_projection_publication(*, state_path: Path | str, wiki_repo_url: str, operator_source_sha: str, push_requested: bool, commit_message: str):
    store = ControlPlaneStateStore(path=Path(state_path))
    checked_at = time.time()

    def _update(plane):
        if not plane.registry.list_projection_bindings():
            plane.bootstrap_default_public_wiki_contracts(now=checked_at)
        bindings = _matching_projection_bindings(plane, wiki_repo_url=wiki_repo_url)
        if not bindings:
            return None
        stale_bindings: list[str] = []
        blocked_bindings: list[str] = []
        blocked_reasons: list[str] = []
        for binding in bindings:
            export = plane.registry.find_authority_export(binding.source_repo_id, binding.required_export_kind.value)
            existing = plane.registry.get_publication_status(binding.binding_id)
            labels = _publication_status_labels(
                existing=existing,
                export=export,
                operator_source_sha=operator_source_sha,
                wiki_repo_url=wiki_repo_url,
                push_requested=push_requested,
                commit_message=commit_message,
            )
            if export is None:
                status = PublicationStatusRecord(
                    binding_id=binding.binding_id,
                    status=PublicationState.BLOCKED,
                    projected_from_export_id="",
                    target_kind=binding.target_kind,
                    target_locator=binding.target_locator,
                    checked_at=checked_at,
                    stale=False,
                    failure_reason=f"missing_authority_export:{binding.source_repo_id}:{binding.required_export_kind.value}",
                    labels=labels,
                )
                plane.upsert_publication_status(status)
                blocked_bindings.append(binding.binding_id)
                blocked_reasons.append(status.failure_reason)
            else:
                stale_bindings.append(binding.binding_id)
        if stale_bindings:
            return {
                "binding_ids": stale_bindings,
                "blocked_binding_ids": blocked_bindings,
                "status": PublicationState.STALE,
            }
        return {
            "binding_ids": blocked_bindings,
            "status": PublicationState.BLOCKED,
            "failure_reason": ";".join(blocked_reasons),
        }

    return store.update(_update)


def _record_projection_publication_outcome(*, state_path: Path | str, wiki_repo_url: str, operator_source_sha: str, push_requested: bool, commit_message: str, status: PublicationState, failure_reason: str = "") -> list[PublicationStatusRecord]:
    store = ControlPlaneStateStore(path=Path(state_path))
    checked_at = time.time()

    def _update(plane):
        if not plane.registry.list_projection_bindings():
            plane.bootstrap_default_public_wiki_contracts(now=checked_at)
        records = _build_projection_publication_records(
            plane,
            wiki_repo_url=wiki_repo_url,
            operator_source_sha=operator_source_sha,
            push_requested=push_requested,
            commit_message=commit_message,
            status=status,
            failure_reason=failure_reason,
            checked_at=checked_at,
        )
        for record in records:
            plane.upsert_publication_status(record)
        return records

    return store.update(_update)


def _preview_projection_publication_outcome(*, state_path: Path | str, wiki_repo_url: str, operator_source_sha: str, push_requested: bool, commit_message: str, status: PublicationState, failure_reason: str = "") -> list[PublicationStatusRecord]:
    plane = ControlPlaneStateStore(path=Path(state_path)).load()
    checked_at = time.time()
    if not plane.registry.list_projection_bindings():
        plane.bootstrap_default_public_wiki_contracts(now=checked_at)
    return _build_projection_publication_records(
        plane,
        wiki_repo_url=wiki_repo_url,
        operator_source_sha=operator_source_sha,
        push_requested=push_requested,
        commit_message=commit_message,
        status=status,
        failure_reason=failure_reason,
        checked_at=checked_at,
    )


def _build_projection_publication_records(plane, *, wiki_repo_url: str, operator_source_sha: str, push_requested: bool, commit_message: str, status: PublicationState, failure_reason: str, checked_at: float) -> list[PublicationStatusRecord]:
    bindings = _matching_projection_bindings(plane, wiki_repo_url=wiki_repo_url)
    if not bindings:
        return []
    records: list[PublicationStatusRecord] = []
    for binding in bindings:
        export = plane.registry.find_authority_export(binding.source_repo_id, binding.required_export_kind.value)
        existing = plane.registry.get_publication_status(binding.binding_id)
        labels = _publication_status_labels(
            existing=existing,
            export=export,
            operator_source_sha=operator_source_sha,
            wiki_repo_url=wiki_repo_url,
            push_requested=push_requested,
            commit_message=commit_message,
        )
        if export is None:
            records.append(
                PublicationStatusRecord(
                    binding_id=binding.binding_id,
                    status=PublicationState.BLOCKED,
                    projected_from_export_id="",
                    target_kind=binding.target_kind,
                    target_locator=binding.target_locator,
                    checked_at=checked_at,
                    stale=False,
                    failure_reason=f"missing_authority_export:{binding.source_repo_id}:{binding.required_export_kind.value}",
                    labels=labels,
                ),
            )
        elif status == PublicationState.SUCCESS:
            records.append(
                PublicationStatusRecord(
                    binding_id=binding.binding_id,
                    status=PublicationState.SUCCESS,
                    projected_from_export_id=export.export_id,
                    target_kind=binding.target_kind,
                    target_locator=binding.target_locator,
                    published_at=checked_at,
                    checked_at=checked_at,
                    stale=False,
                    failure_reason="",
                    labels=labels,
                ),
            )
        else:
            membrane_current = bool(
                existing is not None
                and existing.status == PublicationState.SUCCESS
                and existing.projected_from_export_id == export.export_id
                and existing.labels.get("source_export_version", "") == export.version
                and existing.labels.get("source_export_sha256", "") == export.content_sha256
            )
            records.append(
                PublicationStatusRecord(
                    binding_id=binding.binding_id,
                    status=PublicationState.FAILED,
                    projected_from_export_id=export.export_id,
                    target_kind=binding.target_kind,
                    target_locator=binding.target_locator,
                    published_at=(existing.published_at if existing is not None else None),
                    checked_at=checked_at,
                    stale=not membrane_current,
                    failure_reason=failure_reason,
                    labels=labels,
                ),
            )
    return records


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