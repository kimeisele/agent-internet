from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .models import AuthorityFeedTransport, SourceAuthorityFeedRecord
from .snapshot import ControlPlaneStateStore


AUTHORITY_FEED_CONTRACT_VERSION = 1


@dataclass(frozen=True, slots=True)
class SyncedAuthorityFeedBundle:
    feed: SourceAuthorityFeedRecord
    bundle_path: Path
    source_sha: str
    bundle_sha256: str
    manifest_url: str
    changed: bool
    imported: bool


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _download_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "agent-internet-authority-feed/0.1"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def _load_json_bytes(payload: bytes, *, source: str) -> dict[str, object]:
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"expected_json_object:{source}")
    return data


def _cache_root_for(store: ControlPlaneStateStore) -> Path:
    return store.path.parent / ".authority-feed-cache"


def _resolve_manifest_bundle(feed: SourceAuthorityFeedRecord, *, cache_root: Path, force: bool) -> tuple[Path, str, str, str, bool]:
    manifest_url = str(feed.locator)
    manifest = _load_json_bytes(_download_bytes(manifest_url), source=manifest_url)
    if str(manifest.get("kind", "")) != "source_authority_feed_manifest":
        raise ValueError("invalid_authority_feed_manifest_kind")
    try:
        contract_version = int(manifest.get("contract_version", 0))
    except Exception as exc:
        raise ValueError("invalid_authority_feed_contract_version") from exc
    if contract_version != AUTHORITY_FEED_CONTRACT_VERSION:
        raise ValueError(f"unsupported_authority_feed_contract_version:{feed.feed_id}:{contract_version}")
    source_repo_id = str(manifest.get("source_repo_id", ""))
    if source_repo_id != feed.source_repo_id:
        raise ValueError(f"authority_feed_repo_mismatch:{feed.feed_id}:{source_repo_id}")
    source_sha = str(manifest.get("source_sha", "")).strip()
    bundle_meta = dict(manifest.get("bundle") or {})
    bundle_relpath = str(bundle_meta.get("path", "")).strip()
    bundle_sha256 = str(bundle_meta.get("sha256", "")).strip()
    if not source_sha or not bundle_relpath or not bundle_sha256:
        raise ValueError("invalid_authority_feed_manifest_bundle")
    cache_dir = cache_root / feed.source_repo_id / source_sha
    bundle_path = cache_dir / "source-authority-bundle.json"
    artifacts_meta = {str(key): dict(value) for key, value in dict(manifest.get("artifacts") or {}).items()}
    unchanged = (
        not force
        and feed.labels.get("source_sha", "") == source_sha
        and feed.labels.get("bundle_sha256", "") == bundle_sha256
        and bundle_path.exists()
        and all((cache_dir / artifact_relpath).exists() for artifact_relpath in artifacts_meta)
    )
    if unchanged:
        return bundle_path, source_sha, bundle_sha256, manifest_url, False
    bundle_url = urljoin(manifest_url, bundle_relpath)
    bundle_bytes = _download_bytes(bundle_url)
    if _sha256_bytes(bundle_bytes) != bundle_sha256:
        raise ValueError(f"authority_feed_bundle_digest_mismatch:{feed.feed_id}")
    bundle_payload = _load_json_bytes(bundle_bytes, source=bundle_url)
    repo_role = dict(bundle_payload.get("repo_role") or {})
    if str(bundle_payload.get("kind", "")) != "source_authority_bundle":
        raise ValueError("invalid_authority_bundle_kind")
    if str(repo_role.get("repo_id", "")) != feed.source_repo_id:
        raise ValueError(f"authority_bundle_repo_mismatch:{feed.feed_id}")
    if str(bundle_payload.get("source_sha", "")).strip() != source_sha:
        raise ValueError(f"authority_bundle_source_sha_mismatch:{feed.feed_id}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    bundle_path.write_bytes(bundle_bytes)
    for artifact_relpath, metadata in artifacts_meta.items():
        artifact_url = urljoin(manifest_url, str(metadata.get("path", "")))
        artifact_bytes = _download_bytes(artifact_url)
        if _sha256_bytes(artifact_bytes) != str(metadata.get("sha256", "")):
            raise ValueError(f"authority_feed_artifact_digest_mismatch:{feed.feed_id}:{artifact_relpath}")
        target = cache_dir / artifact_relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact_bytes)
    return bundle_path, source_sha, bundle_sha256, manifest_url, True


def sync_source_authority_feed(store: ControlPlaneStateStore, *, feed_id: str, force: bool = False, now: float | None = None) -> SyncedAuthorityFeedBundle:
    checked_at = float(time.time() if now is None else now)
    feed = store.load().registry.get_source_authority_feed(feed_id)
    if feed is None:
        raise ValueError(f"unknown_source_authority_feed:{feed_id}")
    if feed.transport == AuthorityFeedTransport.FILESYSTEM_BUNDLE:
        bundle_path = Path(feed.locator).resolve()
        source_sha = feed.labels.get("source_sha", "")
        bundle_sha256 = feed.labels.get("bundle_sha256", "")
        manifest_url = feed.labels.get("manifest_url", "")
        changed = True
    elif feed.transport == AuthorityFeedTransport.MANIFEST_URL:
        bundle_path, source_sha, bundle_sha256, manifest_url, changed = _resolve_manifest_bundle(
            feed,
            cache_root=_cache_root_for(store),
            force=force,
        )
    else:
        raise ValueError(f"unsupported_authority_feed_transport:{feed.transport.value}")

    def _update(plane):
        current = plane.registry.get_source_authority_feed(feed_id)
        if current is None:
            raise ValueError(f"unknown_source_authority_feed:{feed_id}")
        updated_feed = replace(
            current,
            labels={
                **dict(current.labels),
                "manifest_url": manifest_url,
                "source_sha": source_sha,
                "bundle_sha256": bundle_sha256,
                "bundle_path": str(bundle_path),
            },
        )
        plane.upsert_source_authority_feed(updated_feed)
        has_existing_exports = any(record.repo_id == updated_feed.source_repo_id for record in plane.registry.list_authority_exports())
        imported = False
        if changed or force or not has_existing_exports:
            plane.ingest_authority_bundle_path(bundle_path, now=checked_at)
            imported = True
        return updated_feed, imported

    updated_feed, imported = store.update(_update)
    return SyncedAuthorityFeedBundle(
        feed=updated_feed,
        bundle_path=bundle_path,
        source_sha=source_sha,
        bundle_sha256=bundle_sha256,
        manifest_url=manifest_url,
        changed=changed,
        imported=imported,
    )