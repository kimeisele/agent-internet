from __future__ import annotations

from pathlib import Path

from .agent_web import build_agent_web_manifest_from_repo_root
from .agent_web_graph import build_agent_web_public_graph
from .agent_web_index import build_agent_web_search_index, search_agent_web_index
from .snapshot import snapshot_control_plane


def build_agent_web_crawl_bootstrap(
    repo_roots: list[str] | tuple[str, ...],
    *,
    state_snapshot: dict,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
) -> dict:
    sources: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    aggregate_records: list[dict[str, object]] = []
    source_ids: set[str] = set()

    for index, repo_root in enumerate(_normalize_repo_roots(repo_roots), start=1):
        try:
            _validate_repo_root(repo_root)
            manifest = build_agent_web_manifest_from_repo_root(
                repo_root,
                state_snapshot=state_snapshot,
                assistant_id=assistant_id,
                heartbeat_source=heartbeat_source,
            )
            graph = build_agent_web_public_graph(manifest)
            search_index = build_agent_web_search_index(manifest, graph)
            source_id = _allocate_source_id(
                preferred=str(manifest.get("identity", {}).get("city_id", "")) or repo_root.name,
                seen=source_ids,
                ordinal=index,
            )
            source = {
                "source_id": source_id,
                "root": str(repo_root),
                "city_id": str(manifest.get("identity", {}).get("city_id", "")),
                "repo": str(manifest.get("identity", {}).get("repo", "")),
                "assistant_id": str(manifest.get("assistant", {}).get("assistant_id", "")),
                "document_count": len(manifest.get("documents", [])),
                "campaign_count": int(manifest.get("stats", {}).get("campaign_count", 0)),
                "service_count": int(manifest.get("stats", {}).get("service_count", 0)),
                "graph_node_count": int(graph.get("stats", {}).get("node_count", 0)),
                "graph_edge_count": int(graph.get("stats", {}).get("edge_count", 0)),
                "indexed_record_count": int(search_index.get("stats", {}).get("record_count", 0)),
                "status": "ok",
            }
            sources.append(source)
            aggregate_records.extend(_scoped_records(search_index, source=source))
        except Exception as exc:
            errors.append({"root": str(repo_root), "error": f"{type(exc).__name__}:{exc}"})

    aggregate_index = {
        "kind": "agent_web_crawl_index",
        "version": 1,
        "records": aggregate_records,
        "stats": {"record_count": len(aggregate_records), "kind_counts": _count_by_kind(aggregate_records)},
    }
    return {
        "kind": "agent_web_crawl_bootstrap",
        "version": 1,
        "sources": sources,
        "errors": errors,
        "aggregate_index": aggregate_index,
        "stats": {
            "requested_root_count": len(_normalize_repo_roots(repo_roots)),
            "source_count": len(sources),
            "error_count": len(errors),
            "aggregate_record_count": len(aggregate_records),
        },
    }


def build_agent_web_crawl_bootstrap_for_plane(
    repo_roots: list[str] | tuple[str, ...],
    *,
    plane: object,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
) -> dict:
    return build_agent_web_crawl_bootstrap(
        list(repo_roots),
        state_snapshot=snapshot_control_plane(plane),
        assistant_id=assistant_id,
        heartbeat_source=heartbeat_source,
    )


def search_agent_web_crawl_bootstrap(crawl: dict, *, query: str, limit: int = 10) -> dict:
    search = search_agent_web_index(crawl.get("aggregate_index", {}), query=query, limit=limit)
    return {
        "kind": "agent_web_crawl_search_results",
        "version": 1,
        "query": str(search.get("query", "")),
        "results": list(search.get("results", [])),
        "stats": {
            "result_count": int(search.get("stats", {}).get("result_count", 0)),
            "indexed_record_count": int(search.get("stats", {}).get("indexed_record_count", 0)),
            "source_count": int(crawl.get("stats", {}).get("source_count", 0)),
            "error_count": int(crawl.get("stats", {}).get("error_count", 0)),
        },
    }


def _normalize_repo_roots(repo_roots: list[str] | tuple[str, ...]) -> list[Path]:
    normalized: list[Path] = []
    seen: set[Path] = set()
    for item in repo_roots:
        candidate = Path(str(item)).resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _allocate_source_id(*, preferred: str, seen: set[str], ordinal: int) -> str:
    base = preferred.strip() or f"source-{ordinal}"
    candidate = base
    suffix = 1
    while candidate in seen:
        suffix += 1
        candidate = f"{base}-{suffix}"
    seen.add(candidate)
    return candidate


def _validate_repo_root(repo_root: Path) -> None:
    if not repo_root.exists():
        raise FileNotFoundError(f"missing_repo_root:{repo_root}")
    peer_descriptor_path = repo_root / "data" / "federation" / "peer.json"
    if not peer_descriptor_path.exists():
        raise FileNotFoundError(f"missing_peer_descriptor:{peer_descriptor_path}")


def _scoped_records(index: dict, *, source: dict[str, object]) -> list[dict[str, object]]:
    scoped: list[dict[str, object]] = []
    source_id = str(source.get("source_id", ""))
    for record in index.get("records", []):
        scoped.append(
            {
                **dict(record),
                "record_id": f"{source_id}:{record.get('record_id', '')}",
                "source_id": source_id,
                "source_city_id": str(source.get("city_id", "")),
                "source_repo": str(source.get("repo", "")),
                "source_root": str(source.get("root", "")),
            },
        )
    return scoped


def _count_by_kind(records: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        kind = str(record.get("kind", "unknown"))
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))