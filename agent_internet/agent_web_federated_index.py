from __future__ import annotations

import time
from pathlib import Path

from .agent_web_index import search_agent_web_index
from .agent_web_semantic_graph import build_agent_web_semantic_graph, normalize_agent_web_semantic_graph
from .agent_web_semantic_overlay import expand_query_with_agent_web_semantic_overlay, load_agent_web_semantic_overlay
from .agent_web_source_registry import (
    DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH,
    build_agent_web_crawl_bootstrap_from_registry,
)
from .agent_web_wordnet_bridge import load_agent_web_wordnet_bridge
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
    semantic_overlay: dict | None = None,
    wordnet_bridge: dict | None = None,
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
    records = [dict(item) for item in crawl.get("aggregate_index", {}).get("records", [])]
    records.extend(_build_steward_federation_records(state_snapshot, refreshed_at=refreshed_at))
    payload = _normalize_federated_index(
        {
            "kind": "agent_web_federated_index",
            "version": 1,
            "refreshed_at": refreshed_at,
            "registry": dict(crawl.get("registry", {})),
            "sources": [dict(item) for item in crawl.get("sources", [])],
            "errors": [dict(item) for item in crawl.get("errors", [])],
            "records": records,
            "semantic_graph": build_agent_web_semantic_graph(records, semantic_overlay=semantic_overlay, wordnet_bridge=wordnet_bridge),
            "semantic_extensions": {
                **_default_semantic_extensions(),
                "overlay_bridge_count": int(dict(semantic_overlay or {}).get("stats", {}).get("bridge_count", 0)),
                "wordnet_bridge_available": bool(dict(wordnet_bridge or {}).get("available", False)),
            },
        },
    )
    write_locked_json_value(Path(path), payload)
    return payload


def refresh_agent_web_federated_index_for_plane(
    path: Path | str = DEFAULT_AGENT_WEB_FEDERATED_INDEX_PATH,
    *,
    registry_path: Path | str = DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH,
    plane: object,
    semantic_overlay: dict | None = None,
    wordnet_bridge: dict | None = None,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
    now: float | None = None,
) -> dict:
    return refresh_agent_web_federated_index(
        path,
        registry_path=registry_path,
        state_snapshot=snapshot_control_plane(plane),
        semantic_overlay=semantic_overlay,
        wordnet_bridge=wordnet_bridge,
        assistant_id=assistant_id,
        heartbeat_source=heartbeat_source,
        now=now,
    )


def search_agent_web_federated_index(
    index: dict,
    *,
    query: str,
    limit: int = 10,
    semantic_overlay: dict | None = None,
    wordnet_bridge: dict | None = None,
) -> dict:
    overlay = semantic_overlay or _empty_semantic_overlay()
    active_wordnet_bridge = wordnet_bridge or load_agent_web_wordnet_bridge()
    expansion = expand_query_with_agent_web_semantic_overlay(overlay, query=query, wordnet_bridge=active_wordnet_bridge)
    search = search_agent_web_index(
        index,
        query=query,
        limit=limit,
        expanded_terms=list(expansion.get("expanded_terms", [])),
        expanded_term_weights={str(item.get("term", "")): float(item.get("weight", 0.0)) for item in expansion.get("weighted_expanded_terms", [])},
    )
    semantic_graph = normalize_agent_web_semantic_graph(index.get("semantic_graph", {}), records=[dict(item) for item in index.get("records", []) if isinstance(item, dict)])
    annotated_results = [_annotate_federated_search_result(dict(result), query=str(query), expansion=expansion, semantic_graph=semantic_graph) for result in search.get("results", [])]
    semantic_extensions = {
        **dict(index.get("semantic_extensions", {})),
        "overlay_bridge_count": int(dict(overlay.get("stats", {})).get("bridge_count", 0)),
        "overlay_enabled_bridge_count": int(dict(overlay.get("stats", {})).get("enabled_bridge_count", 0)),
        "wordnet_bridge_available": bool(active_wordnet_bridge.get("available", False)),
        "wordnet_bridge_source": str(active_wordnet_bridge.get("source", "unavailable")),
        "semantic_graph_edge_count": int(semantic_graph.get("stats", {}).get("edge_count", 0)),
        "semantic_graph_connected_record_count": int(semantic_graph.get("stats", {}).get("connected_record_count", 0)),
    }
    return {
        "kind": "agent_web_federated_search_results",
        "version": 1,
        "query": str(search.get("query", "")),
        "results": annotated_results,
        "query_interpretation": {
            "raw_query": str(query),
            "input_terms": list(expansion.get("input_terms", [])),
            "expanded_terms": list(expansion.get("expanded_terms", [])),
            "weighted_expanded_terms": list(expansion.get("weighted_expanded_terms", [])),
            "semantic_bridges_applied": [str(item.get("bridge_id", "")) for item in expansion.get("matched_bridges", [])],
        },
        "matched_semantic_bridges": list(expansion.get("matched_bridges", [])),
        "wordnet_bridge": dict(expansion.get("wordnet_bridge", {})),
        "semantic_extensions": semantic_extensions,
        "stats": {
            "result_count": len(annotated_results),
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
    semantic_overlay_path: Path | str | None = None,
    wordnet_bridge_path: Path | str | None = None,
) -> dict:
    overlay = _empty_semantic_overlay() if semantic_overlay_path is None else load_agent_web_semantic_overlay(semantic_overlay_path)
    return search_agent_web_federated_index(
        load_agent_web_federated_index(path),
        query=query,
        limit=limit,
        semantic_overlay=overlay,
        wordnet_bridge=load_agent_web_wordnet_bridge(wordnet_bridge_path),
    )


def _build_steward_federation_records(state_snapshot: dict, *, refreshed_at: float) -> list[dict]:
    """Extract steward's federation data from the control plane snapshot and build index records.

    Indexes: health reports (presence), immune stats (trust records),
    and peer-status (registered cities with steward trust).
    """
    records: list[dict] = []
    source_city_id = "steward"
    source_repo = "kimeisele/steward-protocol"

    # Health reports from city presences.
    for presence in state_snapshot.get("presences", []):
        if not isinstance(presence, dict):
            continue
        city_id = str(presence.get("city_id", ""))
        health = str(presence.get("health", "unknown"))
        heartbeat = int(presence.get("heartbeat", 0) or 0)
        capabilities = list(presence.get("capabilities", []))
        records.append({
            "record_id": f"steward:health-report:{city_id}",
            "kind": "steward_health_report",
            "title": f"Health Report: {city_id}",
            "summary": f"City {city_id} health={health} heartbeat={heartbeat} capabilities={','.join(capabilities)}",
            "tags": ["health-report", "steward", "federation", health, city_id],
            "terms": ["health", "heartbeat", "steward", "federation", "monitoring", city_id, health],
            "source_city_id": source_city_id,
            "source_repo": source_repo,
            "source_id": source_city_id,
            "indexed_at": refreshed_at,
        })

    # Immune stats from trust records.
    trust_records = [r for r in state_snapshot.get("trust_records", []) if isinstance(r, dict)]
    if trust_records:
        trust_levels: dict[str, int] = {}
        for record in trust_records:
            level = str(record.get("level", "unknown"))
            trust_levels[level] = trust_levels.get(level, 0) + 1
        trust_summary = ", ".join(f"{level}={count}" for level, count in sorted(trust_levels.items()))
        records.append({
            "record_id": "steward:immune-stats",
            "kind": "steward_immune_stats",
            "title": "Federation Immune Stats",
            "summary": f"Trust distribution across {len(trust_records)} relationships: {trust_summary}",
            "tags": ["immune-stats", "steward", "trust", "federation", "security"],
            "terms": ["immune", "trust", "verification", "steward", "security", "federation", *list(trust_levels.keys())],
            "source_city_id": source_city_id,
            "source_repo": source_repo,
            "source_id": source_city_id,
            "indexed_at": refreshed_at,
        })

    # Peer-status from registered identities.
    identities = [r for r in state_snapshot.get("identities", []) if isinstance(r, dict)]
    if identities:
        city_ids = [str(r.get("city_id", "")) for r in identities if str(r.get("city_id", ""))]
        records.append({
            "record_id": "steward:peer-status",
            "kind": "steward_peer_status",
            "title": "Federation Peer Status",
            "summary": f"{len(city_ids)} registered peers: {', '.join(sorted(city_ids))}",
            "tags": ["peer-status", "steward", "federation", "registry", "peers"],
            "terms": ["peer", "status", "federation", "registry", "steward", *city_ids],
            "source_city_id": source_city_id,
            "source_repo": source_repo,
            "source_id": source_city_id,
            "indexed_at": refreshed_at,
        })

    # Lotus addressing summary for steward.
    services = [r for r in state_snapshot.get("service_addresses", []) if isinstance(r, dict) and str(r.get("owner_city_id", "")) == "steward"]
    endpoints = [r for r in state_snapshot.get("hosted_endpoints", []) if isinstance(r, dict) and str(r.get("owner_city_id", "")) == "steward"]
    if services or endpoints:
        service_names = [str(s.get("service_name", "")) for s in services]
        endpoint_handles = [str(e.get("public_handle", "")) for e in endpoints]
        records.append({
            "record_id": "steward:lotus-addressing",
            "kind": "steward_lotus_addressing",
            "title": "Steward Lotus Addressing",
            "summary": f"Steward Lotus services: {', '.join(service_names)}; endpoints: {', '.join(endpoint_handles)}",
            "tags": ["lotus", "addressing", "steward", "service", "endpoint"],
            "terms": ["lotus", "address", "service", "endpoint", "steward", "nadi", *service_names, *endpoint_handles],
            "source_city_id": source_city_id,
            "source_repo": source_repo,
            "source_id": source_city_id,
            "indexed_at": refreshed_at,
        })

    return records


def _default_federated_index() -> dict:
    return {
        "kind": "agent_web_federated_index",
        "version": 1,
        "refreshed_at": 0.0,
        "registry": {"path": str(Path(DEFAULT_AGENT_WEB_SOURCE_REGISTRY_PATH).resolve()), "source_count": 0, "enabled_source_count": 0, "disabled_source_count": 0},
        "sources": [],
        "errors": [],
        "records": [],
        "semantic_graph": normalize_agent_web_semantic_graph({}, records=[]),
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
    semantic_graph = normalize_agent_web_semantic_graph(raw.get("semantic_graph", {}), records=records)
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
        "semantic_graph": semantic_graph,
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


def _annotate_federated_search_result(result: dict[str, object], *, query: str, expansion: dict, semantic_graph: dict) -> dict[str, object]:
    record_text = _record_text(result)
    record_terms = _tokenize_text(record_text)
    input_terms = {str(item) for item in expansion.get("input_terms", []) if str(item)}
    direct_matches = sorted({str(term) for term in result.get("matched_terms", []) if str(term) in input_terms})
    expanded_term_matches = []
    for item in expansion.get("weighted_expanded_terms", []):
        term = str(dict(item).get("term", "")).strip().lower()
        if not term:
            continue
        term_tokens = _tokenize_text(term)
        if term in record_text or (term_tokens and term_tokens & record_terms):
            expanded_term_matches.append({"term": term, "weight": round(float(dict(item).get("weight", 0.0) or 0.0), 6), "source_bridge_ids": list(dict(item).get("source_bridge_ids", []))})
    semantic_bridge_matches = []
    for bridge in expansion.get("matched_bridges", []):
        bridge_payload = dict(bridge)
        matched_phrases = sorted({phrase for phrase in [*bridge_payload.get("terms", []), *bridge_payload.get("expansions", [])] if str(phrase).strip() and str(phrase).strip().lower() in record_text})
        if matched_phrases:
            semantic_bridge_matches.append({"bridge_id": str(bridge_payload.get("bridge_id", "")), "bridge_kind": str(bridge_payload.get("bridge_kind", "")), "matched_phrases": matched_phrases, "effective_weight": round(float(bridge_payload.get("effective_weight", 0.0) or 0.0), 6)})
    semantic_neighbors = list(dict(semantic_graph.get("neighbors_by_record_id", {})).get(str(result.get("record_id", "")), []))
    return {**result, "why_matched": {"title_exact_match": bool(query and query.lower() in str(result.get("title", "")).lower()), "summary_exact_match": bool(query and query.lower() in str(result.get("summary", "")).lower()), "direct_term_matches": direct_matches, "expanded_term_matches": expanded_term_matches[:4], "semantic_bridge_matches": semantic_bridge_matches[:3], "semantic_neighbor_count": len(semantic_neighbors), "top_semantic_neighbors": semantic_neighbors[:2]}}


def _record_text(record: dict[str, object]) -> str:
    return " ".join([str(record.get("title", "")).lower(), str(record.get("summary", "")).lower(), *[str(item).lower() for item in record.get("tags", [])], *[str(item).lower() for item in record.get("terms", [])]])


def _tokenize_text(value: str) -> set[str]:
    return {token for token in value.lower().split() if token}


def _count_by_kind(records: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        kind = str(record.get("kind", "unknown"))
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def _empty_semantic_overlay() -> dict:
    return {
        "kind": "agent_web_semantic_overlay",
        "version": 1,
        "refreshed_at": 0.0,
        "bridges": [],
        "stats": {
            "bridge_count": 0,
            "enabled_bridge_count": 0,
            "disabled_bridge_count": 0,
            "bridge_kind_counts": {},
            "term_count": 0,
            "expansion_count": 0,
        },
    }