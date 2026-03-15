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
    records.extend(_build_federation_snapshot_records(state_snapshot, refreshed_at=refreshed_at))
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


def _build_federation_snapshot_records(state_snapshot: dict, *, refreshed_at: float) -> list[dict]:
    """Build index records from the control plane snapshot.

    Peer-agnostic: indexes ALL registered presences, trust relationships,
    identities, and service addresses — no hardcoded city knowledge.
    """
    records: list[dict] = []

    # Per-city health reports from presences.
    # Key is "presence" in snapshot_control_plane().
    for presence in state_snapshot.get("presence", []):
        if not isinstance(presence, dict):
            continue
        city_id = str(presence.get("city_id", ""))
        if not city_id:
            continue
        health = str(presence.get("health", "unknown"))
        heartbeat = int(presence.get("heartbeat", 0) or 0)
        capabilities = [str(c) for c in presence.get("capabilities", [])]
        records.append({
            "record_id": f"federation:health:{city_id}",
            "kind": "federation_health_report",
            "title": f"Health: {city_id}",
            "summary": f"{city_id} health={health} heartbeat={heartbeat} caps={','.join(capabilities)}",
            "tags": ["health", "federation", health, city_id, *capabilities],
            "terms": ["health", "heartbeat", "federation", city_id, health, *capabilities],
            "source_city_id": city_id,
            "source_id": "federation-snapshot",
            "indexed_at": refreshed_at,
        })

    # Trust distribution — aggregate, not per-peer.
    # Key is "trust" in snapshot_control_plane().
    trust_rows = [r for r in state_snapshot.get("trust", []) if isinstance(r, dict)]
    if trust_rows:
        levels: dict[str, int] = {}
        peers_seen: set[str] = set()
        for row in trust_rows:
            level = str(row.get("level", "unknown"))
            levels[level] = levels.get(level, 0) + 1
            peers_seen.add(str(row.get("subject_city_id", "")))
        level_summary = ", ".join(f"{k}={v}" for k, v in sorted(levels.items()))
        records.append({
            "record_id": "federation:trust-summary",
            "kind": "federation_trust_summary",
            "title": "Federation Trust Summary",
            "summary": f"{len(trust_rows)} trust links across {len(peers_seen)} peers: {level_summary}",
            "tags": ["trust", "federation", "security", *list(levels.keys())],
            "terms": ["trust", "federation", "security", "verification", *list(levels.keys()), *sorted(peers_seen)],
            "source_city_id": "federation",
            "source_id": "federation-snapshot",
            "indexed_at": refreshed_at,
        })

    # Peer registry — one record with all registered identities.
    identities = [r for r in state_snapshot.get("identities", []) if isinstance(r, dict)]
    if identities:
        city_ids = sorted(str(r.get("city_id", "")) for r in identities if str(r.get("city_id", "")))
        records.append({
            "record_id": "federation:peer-registry",
            "kind": "federation_peer_registry",
            "title": "Federation Peer Registry",
            "summary": f"{len(city_ids)} peers: {', '.join(city_ids)}",
            "tags": ["peers", "federation", "registry", *city_ids],
            "terms": ["peer", "registry", "federation", *city_ids],
            "source_city_id": "federation",
            "source_id": "federation-snapshot",
            "indexed_at": refreshed_at,
        })

    # Per-city Lotus service addresses.
    services_by_city: dict[str, list[str]] = {}
    for svc in state_snapshot.get("service_addresses", []):
        if not isinstance(svc, dict):
            continue
        owner = str(svc.get("owner_city_id", ""))
        name = str(svc.get("service_name", ""))
        if owner and name:
            services_by_city.setdefault(owner, []).append(name)
    for city_id, svc_names in sorted(services_by_city.items()):
        records.append({
            "record_id": f"federation:lotus-services:{city_id}",
            "kind": "federation_lotus_services",
            "title": f"Lotus Services: {city_id}",
            "summary": f"{city_id} services: {', '.join(sorted(svc_names))}",
            "tags": ["lotus", "service", "federation", city_id, *svc_names],
            "terms": ["lotus", "service", "address", "federation", city_id, *svc_names],
            "source_city_id": city_id,
            "source_id": "federation-snapshot",
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