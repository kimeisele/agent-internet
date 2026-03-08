from __future__ import annotations

import json
from pathlib import Path

from .agent_web_crawl import build_agent_web_crawl_bootstrap, search_agent_web_crawl_bootstrap
from .file_locking import read_locked_json_value, update_locked_json_value
from .snapshot import snapshot_control_plane

DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH = "data/control_plane/agent_web_source_registry.json"


def load_agent_web_source_registry(path: Path | str = DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH) -> dict:
    registry_path = Path(path)
    payload = read_locked_json_value(registry_path, default=_default_registry())
    return _normalize_registry(payload)


def upsert_agent_web_source_registry_entry(
    path: Path | str = DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH,
    *,
    root: Path | str,
    source_id: str | None = None,
    labels: list[str] | tuple[str, ...] = (),
    notes: str = "",
    enabled: bool = True,
) -> dict:
    registry_path = Path(path)
    raw_root = str(root).strip()
    if not raw_root:
        raise ValueError("missing_registry_root")
    root_value = str(Path(raw_root).resolve())

    def updater(current: dict) -> dict:
        registry = _normalize_registry(current)
        sources = [dict(item) for item in registry.get("sources", [])]
        match_index = next(
            (
                index
                for index, item in enumerate(sources)
                if str(item.get("root", "")) == root_value or (source_id and str(item.get("source_id", "")) == source_id)
            ),
            None,
        )
        suggested_source_id = source_id or _suggest_source_id(Path(root_value))
        source = {
            "source_id": suggested_source_id,
            "root": root_value,
            "seed_kind": "local_repo_root",
            "enabled": bool(enabled),
            "labels": [str(item) for item in labels],
            "notes": str(notes),
        }
        if match_index is None:
            sources.append(source)
        else:
            existing = dict(sources[match_index])
            sources[match_index] = {
                **existing,
                **source,
                "labels": [*existing.get("labels", []), *source.get("labels", [])],
                "notes": source["notes"] or str(existing.get("notes", "")),
            }
        return _normalize_registry({"kind": "agent_web_source_registry", "version": 1, "sources": sources})

    return update_locked_json_value(registry_path, default=_default_registry(), updater=updater)


def remove_agent_web_source_registry_entry(
    path: Path | str = DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH,
    *,
    root: Path | str | None = None,
    source_id: str | None = None,
) -> dict:
    if not root and not source_id:
        raise ValueError("missing_registry_source_selector")
    registry_path = Path(path)
    root_value = None if root is None else str(Path(root).resolve())

    def updater(current: dict) -> dict:
        registry = _normalize_registry(current)
        sources = [
            dict(item)
            for item in registry.get("sources", [])
            if not (
                (root_value and str(item.get("root", "")) == root_value)
                or (source_id and str(item.get("source_id", "")) == source_id)
            )
        ]
        return _normalize_registry({"kind": "agent_web_source_registry", "version": 1, "sources": sources})

    return update_locked_json_value(registry_path, default=_default_registry(), updater=updater)


def build_agent_web_crawl_bootstrap_from_registry(
    path: Path | str = DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH,
    *,
    state_snapshot: dict,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
) -> dict:
    registry = load_agent_web_source_registry(path)
    crawl = build_agent_web_crawl_bootstrap(
        [str(item.get("root", "")) for item in registry.get("sources", []) if bool(item.get("enabled", True))],
        state_snapshot=state_snapshot,
        assistant_id=assistant_id,
        heartbeat_source=heartbeat_source,
    )
    return {
        **crawl,
        "registry": _registry_summary(registry=registry, path=path),
    }


def build_agent_web_crawl_bootstrap_from_registry_for_plane(
    path: Path | str = DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH,
    *,
    plane: object,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
) -> dict:
    return build_agent_web_crawl_bootstrap_from_registry(
        path,
        state_snapshot=snapshot_control_plane(plane),
        assistant_id=assistant_id,
        heartbeat_source=heartbeat_source,
    )


def search_agent_web_crawl_bootstrap_from_registry(
    path: Path | str = DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH,
    *,
    state_snapshot: dict,
    query: str,
    limit: int = 10,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
) -> dict:
    crawl = build_agent_web_crawl_bootstrap_from_registry(
        path,
        state_snapshot=state_snapshot,
        assistant_id=assistant_id,
        heartbeat_source=heartbeat_source,
    )
    results = search_agent_web_crawl_bootstrap(crawl, query=query, limit=limit)
    return {**results, "registry": crawl.get("registry", {})}


def _default_registry() -> dict:
    return {"kind": "agent_web_source_registry", "version": 1, "sources": []}


def _normalize_registry(payload: object) -> dict:
    raw = dict(payload) if isinstance(payload, dict) else _default_registry()
    sources = []
    seen_roots: set[str] = set()
    seen_source_ids: set[str] = set()
    for ordinal, item in enumerate(raw.get("sources", []), start=1):
        if not isinstance(item, dict):
            continue
        raw_root = str(item.get("root", "")).strip()
        if not raw_root:
            continue
        root_value = str(Path(raw_root).resolve())
        if root_value in seen_roots:
            continue
        seen_roots.add(root_value)
        preferred_source_id = str(item.get("source_id", "")).strip() or _suggest_source_id(Path(root_value)) or f"source-{ordinal}"
        source_value = preferred_source_id
        suffix = 1
        while source_value in seen_source_ids:
            suffix += 1
            source_value = f"{preferred_source_id}-{suffix}"
        seen_source_ids.add(source_value)
        sources.append(
            {
                "source_id": source_value,
                "root": root_value,
                "seed_kind": str(item.get("seed_kind", "local_repo_root") or "local_repo_root"),
                "enabled": bool(item.get("enabled", True)),
                "labels": sorted({str(label).strip() for label in item.get("labels", []) if str(label).strip()}),
                "notes": str(item.get("notes", "")),
            },
        )
    enabled_count = sum(1 for item in sources if bool(item.get("enabled", True)))
    disabled_count = len(sources) - enabled_count
    return {
        "kind": "agent_web_source_registry",
        "version": 1,
        "sources": sources,
        "stats": {
            "source_count": len(sources),
            "enabled_source_count": enabled_count,
            "disabled_source_count": disabled_count,
        },
    }


def _registry_summary(*, registry: dict, path: Path | str) -> dict:
    stats = dict(registry.get("stats", {}))
    return {
        "path": str(Path(path).resolve()),
        "source_count": int(stats.get("source_count", 0)),
        "enabled_source_count": int(stats.get("enabled_source_count", 0)),
        "disabled_source_count": int(stats.get("disabled_source_count", 0)),
    }


def _suggest_source_id(root: Path) -> str:
    peer_descriptor_path = root / "data" / "federation" / "peer.json"
    if peer_descriptor_path.exists():
        try:
            payload = json.loads(peer_descriptor_path.read_text())
            city_id = str(payload.get("identity", {}).get("city_id", "")).strip()
            if city_id:
                return city_id
        except Exception:
            pass
    return root.name.strip()