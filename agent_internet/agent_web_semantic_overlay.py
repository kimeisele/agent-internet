from __future__ import annotations

import re
import time
from pathlib import Path

from .file_locking import read_locked_json_value, update_locked_json_value, write_locked_json_value
from .agent_web_wordnet_bridge import load_agent_web_wordnet_bridge, wordnet_phrase_score

DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH = "data/control_plane/agent_web_semantic_overlay.json"


def load_agent_web_semantic_overlay(path: Path | str = DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH) -> dict:
    payload = read_locked_json_value(Path(path), default=_default_semantic_overlay())
    return _normalize_semantic_overlay(payload)


def refresh_agent_web_semantic_overlay(
    path: Path | str = DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH,
    *,
    now: float | None = None,
) -> dict:
    overlay = load_agent_web_semantic_overlay(path)
    refreshed = _normalize_semantic_overlay({**overlay, "refreshed_at": float(time.time() if now is None else now)})
    write_locked_json_value(Path(path), refreshed)
    return refreshed


def upsert_agent_web_semantic_bridge(
    path: Path | str = DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH,
    *,
    bridge_kind: str,
    terms: list[str] | tuple[str, ...],
    expansions: list[str] | tuple[str, ...],
    bridge_id: str | None = None,
    weight: float | None = None,
    notes: str = "",
    enabled: bool = True,
) -> dict:
    bridge_kind_value = str(bridge_kind).strip() or "concept"
    normalized_terms = _clean_phrase_list(terms)
    if not normalized_terms:
        raise ValueError("missing_bridge_terms")
    normalized_expansions = _clean_phrase_list(expansions)
    if not normalized_expansions:
        raise ValueError("missing_bridge_expansions")

    def updater(current: dict) -> dict:
        overlay = _normalize_semantic_overlay(current)
        bridges = [dict(item) for item in overlay.get("bridges", [])]
        preferred_bridge_id = str(bridge_id or _suggest_bridge_id(bridge_kind_value, normalized_terms[0])).strip()
        match_index = next(
            (
                index
                for index, item in enumerate(bridges)
                if str(item.get("bridge_id", "")) == preferred_bridge_id
            ),
            None,
        )
        candidate = {
            "bridge_id": preferred_bridge_id,
            "bridge_kind": bridge_kind_value,
            "terms": normalized_terms,
            "expansions": normalized_expansions,
            "weight": _normalize_weight(weight if weight is not None else _default_bridge_weight(bridge_kind_value)),
            "enabled": bool(enabled),
            "notes": str(notes),
        }
        if match_index is None:
            bridges.append(candidate)
        else:
            existing = dict(bridges[match_index])
            bridges[match_index] = {
                **existing,
                **candidate,
                "terms": _clean_phrase_list([*existing.get("terms", []), *candidate["terms"]]),
                "expansions": _clean_phrase_list([*existing.get("expansions", []), *candidate["expansions"]]),
                "notes": candidate["notes"] or str(existing.get("notes", "")),
            }
        return _normalize_semantic_overlay({"kind": "agent_web_semantic_overlay", "version": 1, "refreshed_at": overlay.get("refreshed_at", 0.0), "bridges": bridges})

    return update_locked_json_value(Path(path), default=_default_semantic_overlay(), updater=updater)


def remove_agent_web_semantic_bridge(
    path: Path | str = DEFAULT_AGENT_WEB_SEMANTIC_OVERLAY_PATH,
    *,
    bridge_id: str,
) -> dict:
    bridge_id_value = str(bridge_id).strip()
    if not bridge_id_value:
        raise ValueError("missing_bridge_id")

    def updater(current: dict) -> dict:
        overlay = _normalize_semantic_overlay(current)
        bridges = [dict(item) for item in overlay.get("bridges", []) if str(item.get("bridge_id", "")) != bridge_id_value]
        return _normalize_semantic_overlay({"kind": "agent_web_semantic_overlay", "version": 1, "refreshed_at": overlay.get("refreshed_at", 0.0), "bridges": bridges})

    return update_locked_json_value(Path(path), default=_default_semantic_overlay(), updater=updater)


def expand_query_with_agent_web_semantic_overlay(overlay: dict, *, query: str, wordnet_bridge: dict | None = None) -> dict:
    query_value = str(query).strip()
    query_terms = _term_tokens(query_value)
    active_wordnet_bridge = wordnet_bridge or load_agent_web_wordnet_bridge()
    weighted_terms: dict[str, dict[str, object]] = {}
    matched_bridges: list[dict[str, object]] = []

    for bridge in overlay.get("bridges", []):
        if not bool(bridge.get("enabled", True)):
            continue
        bridge_terms = _clean_phrase_list(bridge.get("terms", []))
        bridge_expansions = _clean_phrase_list(bridge.get("expansions", []))
        if not bridge_terms or not bridge_expansions:
            continue
        lexical_score = _bridge_match_score(query_value, query_terms, bridge_terms)
        wordnet_score = max((wordnet_phrase_score(query_value, term, bridge=active_wordnet_bridge) for term in bridge_terms), default=0.0)
        match_score = max(lexical_score, wordnet_score)
        if match_score <= 0:
            continue
        bridge_weight = _normalize_weight(bridge.get("weight", _default_bridge_weight(str(bridge.get("bridge_kind", "concept")))))
        effective_weight = _normalize_weight(bridge_weight * match_score)
        for candidate_term in _clean_phrase_list([*bridge_terms, *bridge_expansions]):
            candidate_score = max(match_score, _bridge_match_score(query_value, query_terms, [candidate_term]), wordnet_phrase_score(query_value, candidate_term, bridge=active_wordnet_bridge))
            term_weight = _normalize_weight(bridge_weight * candidate_score)
            slot = weighted_terms.setdefault(candidate_term, {"term": candidate_term, "weight": 0.0, "source_bridge_ids": []})
            slot["weight"] = max(float(slot["weight"]), term_weight)
            if str(bridge.get("bridge_id", "")) and str(bridge.get("bridge_id", "")) not in slot["source_bridge_ids"]:
                slot["source_bridge_ids"].append(str(bridge.get("bridge_id", "")))
        matched_bridges.append(
            {
                "bridge_id": str(bridge.get("bridge_id", "")),
                "bridge_kind": str(bridge.get("bridge_kind", "concept")),
                "terms": bridge_terms,
                "expansions": bridge_expansions,
                "bridge_weight": bridge_weight,
                "lexical_score": lexical_score,
                "wordnet_score": wordnet_score,
                "effective_weight": effective_weight,
            },
        )

    weighted_expanded_terms = sorted(
        (
            {
                "term": str(item["term"]),
                "weight": _normalize_weight(item["weight"]),
                "source_bridge_ids": sorted({str(source) for source in item.get("source_bridge_ids", []) if str(source)}),
            }
            for item in weighted_terms.values()
        ),
        key=lambda item: (-float(item.get("weight", 0.0)), str(item.get("term", ""))),
    )
    expanded_terms = _clean_phrase_list([query_value, *query_terms, *[str(item.get("term", "")) for item in weighted_expanded_terms]])
    return {
        "kind": "agent_web_semantic_query_expansion",
        "version": 1,
        "raw_query": query_value,
        "input_terms": query_terms,
        "expanded_terms": expanded_terms,
        "weighted_expanded_terms": weighted_expanded_terms,
        "matched_bridges": sorted(matched_bridges, key=lambda item: (-float(item.get("effective_weight", 0.0)), str(item.get("bridge_id", "")))),
        "wordnet_bridge": {
            "available": bool(active_wordnet_bridge.get("available", False)),
            "path": str(active_wordnet_bridge.get("path", "")),
            "source": str(active_wordnet_bridge.get("source", "unavailable")),
            "stats": dict(active_wordnet_bridge.get("stats", {})),
        },
        "stats": {
            "matched_bridge_count": len(matched_bridges),
            "expanded_term_count": len(expanded_terms),
            "weighted_term_count": len(weighted_expanded_terms),
        },
    }


def _default_semantic_overlay() -> dict:
    return {
        "kind": "agent_web_semantic_overlay",
        "version": 1,
        "refreshed_at": 0.0,
        "bridges": [],
    }


def _normalize_semantic_overlay(payload: object) -> dict:
    raw = dict(payload) if isinstance(payload, dict) else _default_semantic_overlay()
    bridges: list[dict[str, object]] = []
    seen_bridge_ids: set[str] = set()
    for ordinal, item in enumerate(raw.get("bridges", []), start=1):
        if not isinstance(item, dict):
            continue
        terms = _clean_phrase_list(item.get("terms", []))
        expansions = _clean_phrase_list(item.get("expansions", []))
        if not terms or not expansions:
            continue
        bridge_kind = str(item.get("bridge_kind", "concept")).strip() or "concept"
        base_bridge_id = str(item.get("bridge_id", "")).strip() or _suggest_bridge_id(bridge_kind, terms[0]) or f"bridge-{ordinal}"
        bridge_value = base_bridge_id
        suffix = 1
        while bridge_value in seen_bridge_ids:
            suffix += 1
            bridge_value = f"{base_bridge_id}-{suffix}"
        seen_bridge_ids.add(bridge_value)
        bridges.append(
            {
                "bridge_id": bridge_value,
                "bridge_kind": bridge_kind,
                "terms": terms,
                "expansions": expansions,
                "weight": _normalize_weight(item.get("weight", _default_bridge_weight(bridge_kind))),
                "enabled": bool(item.get("enabled", True)),
                "notes": str(item.get("notes", "")),
            },
        )
    enabled_bridges = [item for item in bridges if bool(item.get("enabled", True))]
    return {
        "kind": "agent_web_semantic_overlay",
        "version": 1,
        "refreshed_at": float(raw.get("refreshed_at", 0.0) or 0.0),
        "bridges": sorted(bridges, key=lambda item: (str(item.get("bridge_kind", "")), str(item.get("bridge_id", "")))),
        "stats": {
            "bridge_count": len(bridges),
            "enabled_bridge_count": len(enabled_bridges),
            "disabled_bridge_count": len(bridges) - len(enabled_bridges),
            "bridge_kind_counts": _count_bridge_kinds(bridges),
            "term_count": len({term for item in bridges for term in item.get("terms", [])}),
            "expansion_count": len({term for item in bridges for term in item.get("expansions", [])}),
            "average_weight": round(sum(float(item.get("weight", 0.0)) for item in bridges) / len(bridges), 4) if bridges else 0.0,
        },
    }


def _clean_phrase_list(values: object) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in values if isinstance(values, (list, tuple)) else [values]:
        candidate = re.sub(r"\s+", " ", str(raw).strip().lower())
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        cleaned.append(candidate)
    return cleaned


def _term_tokens(value: str) -> list[str]:
    return sorted({term for term in re.findall(r"[a-z0-9_./:-]+", value.lower()) if term})


def _bridge_match_score(query_value: str, query_terms: list[str], bridge_terms: list[str]) -> float:
    query_term_set = set(query_terms)
    for term in bridge_terms:
        if term == query_value:
            return 1.0
        if term in query_term_set:
            return 0.95
        if term and term in query_value:
            return 0.75
        term_tokens = set(_term_tokens(term))
        if term_tokens and term_tokens.issubset(query_term_set):
            return 0.65
    return 0.0


def _suggest_bridge_id(bridge_kind: str, seed: str) -> str:
    safe_seed = re.sub(r"[^a-z0-9]+", "-", seed.lower()).strip("-")
    return f"{bridge_kind}:{safe_seed}".strip(":")


def _default_bridge_weight(bridge_kind: str) -> float:
    return {
        "alias": 1.0,
        "synonym": 0.9,
        "wordnet": 0.78,
        "concept": 0.65,
        "resonance": 0.55,
    }.get(str(bridge_kind).strip().lower(), 0.6)


def _normalize_weight(value: object) -> float:
    try:
        return max(0.0, min(1.0, round(float(value), 6)))
    except (TypeError, ValueError):
        return 0.0


def _count_bridge_kinds(bridges: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for bridge in bridges:
        kind = str(bridge.get("bridge_kind", "concept"))
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))