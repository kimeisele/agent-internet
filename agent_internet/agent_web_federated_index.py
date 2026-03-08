from __future__ import annotations

import time
from pathlib import Path

from .agent_web_index import search_agent_web_index
from .agent_web_source_registry import (
    DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH,
    build_agent_web_crawl_bootstrap_from_registry,
)
from .file_locking import read_locked_json_value, write_locked_json_value
from .snapshot import snapshot_control_plane

DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH = "data/control_plane/agent_web_federated_index.json"


def load_agent_web_federated_index(path: Path | str = DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH) -> dict:
    payload = read_locked_json_value(Path(path), default=_default_federated_index())
    return _normalize_federated_index(payload)


def refresh_agent_web_federated_index(
    path: Path | str = DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH,
    *,
    registry_path: Path | str = DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH,
    state_snapshot: dict,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
    now: float | None = None,
) -> dict:
    crawl = build_agent_web_crawl_bootstrap_from_registry(
        registry_path,
        state_snapshot=state_snapshot,
        assistant_id=assistant_id,
        heartbeat_source=heartbeat_source,
    )
    refreshed_at = float(time.time() if now is None else now)
    payload = _normalize_federated_index(
        {
            "kind": "agent_web_federated_index",
            "version": 1,
            "refreshed_at": refreshed_at,
            "registry": dict(crawl.get("registry", {})),
            "sources": [dict(item) for item in crawl.get("sources", [])],
            "errors": [dict(item) for item in crawl.get("errors", [])],
            "records": [dict(item) for item in crawl.get("aggregate_index", {}).get("records", [])],
            "semantic_extensions": _default_semantic_extensions(),
        },
    )
    write_locked_json_value(Path(path), payload)
    return payload


def refresh_agent_web_federated_index_for_plane(
    path: Path | str = DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH,
    *,
    registry_path: Path | str = DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH,
    plane: object,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
    now: float | None = None,
) -> dict:
    return refresh_agent_web_federated_index(
        path,
        registry_path=registry_path,
        state_snapshot=snapshot_control_plane(plane),
        assistant_id=assistant_id,
        heartbeat_source=heartbeat_source,
        now=now,
    )


def search_agent_web_federated_index(index: dict, *, query: str, limit: int = 10) -> dict:
    search = search_agent_web_index(index, query=query, limit=limit)
    semantic_extensions = dict(index.get("semantic_extensions", {}))
    return {
        "kind": "agent_web_federated_search_results",
        "version": 1,
        "query": str(search.get("query", "")),
        "results": list(search.get("results", [])),
        "query_interpretation": {
            "raw_query": str(query),
            "expanded_terms": [str(query).strip()] if str(query).strip() else [],
            "semantic_bridges_applied": list(semantic_extensions.get("bridges", [])),
        },
        "semantic_extensions": semantic_extensions,
        "stats": {
            "result_count": int(search.get("stats", {}).get("result_count", 0)),
            "indexed_record_count": int(search.get("stats", {}).get("indexed_record_count", 0)),
            "source_count": int(index.get("stats", {}).get("source_count", 0)),
            "error_count": int(index.get("stats", {}).get("error_count", 0)),
        },
    }


def search_agent_web_federated_index_from_path(
    path: Path | str = DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH,
    *,
    query: str,
    limit: int = 10,
) -> dict:
    return search_agent_web_federated_index(load_agent_web_federated_index(path), query=query, limit=limit)


def _default_federated_index() -> dict:
    return {
        "kind": "agent_web_federated_index",
        "version": 1,
        "refreshed_at": 0.0,
        "registry": {"path": str(Path(DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH).resolve()), "source_count": 0, "enabled_source_count": 0, "disabled_source_count": 0},
        "sources": [],
        "errors": [],
        "records": [],
        "semantic_extensions": _default_semantic_extensions(),
        "stats": {"record_count": 0, "source_count": 0, "error_count": 0, "kind_counts": {}, "source_city_ids": []},
    }


def _default_semantic_extensions() -> dict:
    return {
        "status": "ready_for_overlay",
        "bridges": [],
        "notes": "Attach synonym, concept, resonance, or WordNet-style bridges later without changing record shape.",
        "semantic_fields": ["title", "summary", "tags", "terms", "kind", "source_city_id", "source_repo"],
    }


def _normalize_federated_index(payload: object) -> dict:
    raw = dict(payload) if isinstance(payload, dict) else _default_federated_index()
    records = [dict(item) for item in raw.get("records", []) if isinstance(item, dict)]
    sources = [dict(item) for item in raw.get("sources", []) if isinstance(item, dict)]
    errors = [dict(item) for item in raw.get("errors", []) if isinstance(item, dict)]
    registry = dict(raw.get("registry", {})) if isinstance(raw.get("registry", {}), dict) else {}
    semantic_extensions = dict(raw.get("semantic_extensions", {})) if isinstance(raw.get("semantic_extensions", {}), dict) else {}
    return {
        "kind": "agent_web_federated_index",
        "version": 1,
        "refreshed_at": float(raw.get("refreshed_at", 0.0) or 0.0),
        "registry": {
            "path": str(registry.get("path", Path(DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH).resolve())),
            "source_count": int(registry.get("source_count", len(sources)) or 0),
            "enabled_source_count": int(registry.get("enabled_source_count", len(sources)) or 0),
            "disabled_source_count": int(registry.get("disabled_source_count", 0) or 0),
        },
        "sources": sorted(sources, key=lambda item: (str(item.get("city_id", "")), str(item.get("source_id", "")))),
        "errors": sorted(errors, key=lambda item: (str(item.get("root", "")), str(item.get("error", "")))),
        "records": sorted(
            records,
            key=lambda item: (
                str(item.get("source_city_id", "")),
                str(item.get("kind", "")),
                str(item.get("title", "")),
                str(item.get("record_id", "")),
            ),
        ),
        "semantic_extensions": {
            **_default_semantic_extensions(),
            **semantic_extensions,
            "bridges": [str(item) for item in semantic_extensions.get("bridges", [])],
            "semantic_fields": [str(item) for item in semantic_extensions.get("semantic_fields", _default_semantic_extensions()["semantic_fields"])],
        },
        "stats": {
            "record_count": len(records),
            "source_count": len(sources),
            "error_count": len(errors),
            "kind_counts": _count_by_kind(records),
            "source_city_ids": sorted({str(item.get("source_city_id", "")) for item in records if str(item.get("source_city_id", ""))}),
        },
    }


def _count_by_kind(records: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        kind = str(record.get("kind", "unknown"))
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))