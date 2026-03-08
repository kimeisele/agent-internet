from __future__ import annotations

import re
from collections import Counter

from .agent_web_wordnet_bridge import wordnet_phrase_score

_TOKEN_RE = re.compile(r"[a-z0-9_./:-]+")
_STOP_TERMS = frozenset(
    {
        "active",
        "agent",
        "assistant",
        "bounded",
        "city",
        "document",
        "execution",
        "graph",
        "healthy",
        "home",
        "keep",
        "moltbook_assistant",
        "node",
        "public",
        "service",
    },
)


def build_agent_web_semantic_graph(
    records: list[dict[str, object]],
    *,
    semantic_overlay: dict | None = None,
    wordnet_bridge: dict | None = None,
    neighbor_limit: int = 5,
) -> dict:
    overlay_bridges = [dict(item) for item in dict(semantic_overlay or {}).get("bridges", []) if isinstance(item, dict) and bool(item.get("enabled", True))]
    record_views: list[dict[str, object]] = []
    term_frequency: Counter[str] = Counter()
    for record in [dict(item) for item in records if isinstance(item, dict)]:
        terms = _record_terms(record)
        term_frequency.update(terms)
        record_views.append({"record": record, "record_id": str(record.get("record_id", "")), "title": str(record.get("title", "")).strip().lower(), "summary": str(record.get("summary", "")).strip().lower(), "text": _record_text(record), "terms": terms})
    neighbors_by_record_id = {str(item["record_id"]): [] for item in record_views if str(item["record_id"])}
    max_term_frequency = max(2, len(record_views) // 2)
    for index, left in enumerate(record_views):
        for right in record_views[index + 1 :]:
            candidate = _score_pair(left, right, term_frequency=term_frequency, max_term_frequency=max_term_frequency, overlay_bridges=overlay_bridges, wordnet_bridge=wordnet_bridge)
            if candidate is None:
                continue
            neighbors_by_record_id[str(left["record_id"])] .append(_neighbor_entry(dict(right["record"]), candidate))
            neighbors_by_record_id[str(right["record_id"])] .append(_neighbor_entry(dict(left["record"]), candidate))
    return normalize_agent_web_semantic_graph({"kind": "agent_web_semantic_graph", "version": 1, "neighbor_limit": int(neighbor_limit), "neighbors_by_record_id": neighbors_by_record_id, "sources": {"overlay_bridge_count": len(overlay_bridges), "wordnet_bridge_available": bool(dict(wordnet_bridge or {}).get("available", False))}}, records=records)


def normalize_agent_web_semantic_graph(payload: object, *, records: list[dict[str, object]]) -> dict:
    raw = dict(payload) if isinstance(payload, dict) else {}
    record_map = {str(item.get("record_id", "")): dict(item) for item in records if isinstance(item, dict) and str(item.get("record_id", ""))}
    neighbor_limit = max(1, int(raw.get("neighbor_limit", 5) or 5))
    raw_neighbors = dict(raw.get("neighbors_by_record_id", {})) if isinstance(raw.get("neighbors_by_record_id", {}), dict) else {}
    edge_keys: set[tuple[str, str]] = set()
    neighbors_by_record_id: dict[str, list[dict[str, object]]] = {}
    for record_id in sorted(record_map):
        normalized: list[dict[str, object]] = []
        seen_neighbor_ids: set[str] = set()
        for item in raw_neighbors.get(record_id, []):
            if not isinstance(item, dict):
                continue
            neighbor_id = str(item.get("record_id", "")).strip()
            if not neighbor_id or neighbor_id == record_id or neighbor_id not in record_map or neighbor_id in seen_neighbor_ids:
                continue
            seen_neighbor_ids.add(neighbor_id)
            neighbor_record = record_map[neighbor_id]
            normalized.append({"record_id": neighbor_id, "kind": str(item.get("kind", neighbor_record.get("kind", ""))), "title": str(item.get("title", neighbor_record.get("title", ""))), "source_city_id": str(item.get("source_city_id", neighbor_record.get("source_city_id", ""))), "href": str(item.get("href", neighbor_record.get("href", ""))), "score": round(float(item.get("score", 0.0) or 0.0), 6), "reason_kinds": sorted({str(value) for value in item.get("reason_kinds", []) if str(value)}), "shared_terms": sorted({str(value) for value in item.get("shared_terms", []) if str(value)})[:6], "bridge_ids": sorted({str(value) for value in item.get("bridge_ids", []) if str(value)}), "wordnet_score": round(float(item.get("wordnet_score", 0.0) or 0.0), 6)})
            edge_keys.add(tuple(sorted((record_id, neighbor_id))))
        neighbors_by_record_id[record_id] = sorted(normalized, key=lambda item: (-float(item.get("score", 0.0)), str(item.get("source_city_id", "")), str(item.get("kind", "")), str(item.get("title", "")), str(item.get("record_id", ""))))[:neighbor_limit]
    return {"kind": "agent_web_semantic_graph", "version": 1, "neighbor_limit": neighbor_limit, "neighbors_by_record_id": neighbors_by_record_id, "sources": {"overlay_bridge_count": int(dict(raw.get("sources", {})).get("overlay_bridge_count", 0) or 0), "wordnet_bridge_available": bool(dict(raw.get("sources", {})).get("wordnet_bridge_available", False))}, "stats": {"node_count": len(record_map), "connected_record_count": sum(1 for items in neighbors_by_record_id.values() if items), "edge_count": len(edge_keys)}}


def read_agent_web_semantic_neighbors(index: dict, *, record_id: str, limit: int = 5) -> dict:
    record_id_value = str(record_id).strip()
    records = [dict(item) for item in index.get("records", []) if isinstance(item, dict)]
    record_map = {str(item.get("record_id", "")): item for item in records if str(item.get("record_id", ""))}
    if record_id_value not in record_map:
        raise ValueError(f"unknown_record:{record_id_value}")
    graph = normalize_agent_web_semantic_graph(index.get("semantic_graph", {}), records=records)
    neighbors = list(graph.get("neighbors_by_record_id", {}).get(record_id_value, []))[: max(1, int(limit))]
    record = record_map[record_id_value]
    return {"kind": "agent_web_semantic_neighbors", "version": 1, "record": {"record_id": record_id_value, "kind": str(record.get("kind", "")), "title": str(record.get("title", "")), "source_city_id": str(record.get("source_city_id", "")), "href": str(record.get("href", ""))}, "neighbors": neighbors, "stats": {"neighbor_count": len(neighbors), "semantic_edge_count": int(graph.get("stats", {}).get("edge_count", 0)), "connected_record_count": int(graph.get("stats", {}).get("connected_record_count", 0))}}


def _score_pair(left: dict[str, object], right: dict[str, object], *, term_frequency: Counter[str], max_term_frequency: int, overlay_bridges: list[dict[str, object]], wordnet_bridge: dict | None) -> dict[str, object] | None:
    shared_terms = sorted(term for term in (set(left.get("terms", set())) & set(right.get("terms", set()))) if term_frequency.get(str(term), 0) <= max_term_frequency)
    bridge_ids = _matching_bridge_ids(str(left.get("text", "")), str(right.get("text", "")), overlay_bridges)
    same_title = bool(left.get("title")) and str(left.get("title", "")) == str(right.get("title", ""))
    wordnet_score = 0.0
    if wordnet_bridge is not None and bool(dict(wordnet_bridge).get("available", False)):
        wordnet_score = max(wordnet_phrase_score(str(left.get("title", "")), str(right.get("title", "")), bridge=wordnet_bridge), wordnet_phrase_score(str(left.get("summary", "")), str(right.get("summary", "")), bridge=wordnet_bridge))
    score = 0.0
    reason_kinds: list[str] = []
    if shared_terms:
        score += min(0.45, 0.15 * len(shared_terms))
        reason_kinds.append("lexical_overlap")
    if same_title:
        score = max(score, 0.65)
        reason_kinds.append("same_title")
    if bridge_ids:
        score += min(0.3, 0.12 * len(bridge_ids))
        reason_kinds.append("semantic_bridge")
    if wordnet_score > 0.15:
        score += min(0.25, wordnet_score * 0.4)
        reason_kinds.append("wordnet")
    if score < 0.2:
        return None
    return {"score": round(score, 6), "reason_kinds": sorted(set(reason_kinds)), "shared_terms": shared_terms[:6], "bridge_ids": bridge_ids, "wordnet_score": round(wordnet_score, 6)}


def _neighbor_entry(record: dict[str, object], candidate: dict[str, object]) -> dict[str, object]:
    return {"record_id": str(record.get("record_id", "")), "kind": str(record.get("kind", "")), "title": str(record.get("title", "")), "source_city_id": str(record.get("source_city_id", "")), "href": str(record.get("href", "")), **candidate}


def _record_terms(record: dict[str, object]) -> set[str]:
    values = [str(record.get("title", "")), str(record.get("summary", "")), *[str(item) for item in record.get("tags", [])], *[str(item) for item in record.get("terms", [])]]
    return {term for term in _tokens(" ".join(values)) if len(term) >= 4 and term not in _STOP_TERMS}


def _record_text(record: dict[str, object]) -> str:
    return " ".join([str(record.get("title", "")).lower(), str(record.get("summary", "")).lower(), *[str(item).lower() for item in record.get("tags", [])], *[str(item).lower() for item in record.get("terms", [])]])


def _matching_bridge_ids(left_text: str, right_text: str, bridges: list[dict[str, object]]) -> list[str]:
    matched: list[str] = []
    for bridge in bridges:
        terms = [str(item).strip().lower() for item in bridge.get("terms", []) if str(item).strip()]
        expansions = [str(item).strip().lower() for item in bridge.get("expansions", []) if str(item).strip()]
        if not terms or not expansions:
            continue
        if (_contains_any(left_text, terms) and _contains_any(right_text, expansions)) or (_contains_any(right_text, terms) and _contains_any(left_text, expansions)):
            matched.append(str(bridge.get("bridge_id", "")))
    return sorted({item for item in matched if item})


def _contains_any(text: str, phrases: list[str]) -> bool:
    return any(phrase in text for phrase in phrases if phrase)


def _tokens(value: str) -> set[str]:
    return {match.group(0) for match in _TOKEN_RE.finditer(value.lower())}