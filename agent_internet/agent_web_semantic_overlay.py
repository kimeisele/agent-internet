from __future__ import annotations

import re
import time
from pathlib import Path

from .file_locking import read_locked_json_value, update_locked_json_value, write_locked_json_value

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


def expand_query_with_agent_web_semantic_overlay(overlay: dict, *, query: str) -> dict:
    query_value = str(query).strip()
    query_terms = _term_tokens(query_value)
    expanded_phrases: list[str] = []
    matched_bridges: list[dict[str, object]] = []

    for bridge in overlay.get("bridges", []):
        if not bool(bridge.get("enabled", True)):
            continue
        bridge_terms = _clean_phrase_list(bridge.get("terms", []))
        bridge_expansions = _clean_phrase_list(bridge.get("expansions", []))
        if not bridge_terms or not bridge_expansions:
            continue
        if not _bridge_matches_query(query_value, query_terms, bridge_terms):
            continue
        expanded_phrases.extend(bridge_expansions)
        matched_bridges.append(
            {
                "bridge_id": str(bridge.get("bridge_id", "")),
                "bridge_kind": str(bridge.get("bridge_kind", "concept")),
                "terms": bridge_terms,
                "expansions": bridge_expansions,
            },
        )

    expanded_terms = _clean_phrase_list([query_value, *query_terms, *expanded_phrases])
    return {
        "kind": "agent_web_semantic_query_expansion",
        "version": 1,
        "raw_query": query_value,
        "input_terms": query_terms,
        "expanded_terms": expanded_terms,
        "matched_bridges": matched_bridges,
        "stats": {
            "matched_bridge_count": len(matched_bridges),
            "expanded_term_count": len(expanded_terms),
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


def _bridge_matches_query(query_value: str, query_terms: list[str], bridge_terms: list[str]) -> bool:
    query_term_set = set(query_terms)
    for term in bridge_terms:
        if term == query_value:
            return True
        if term in query_term_set:
            return True
        if term and term in query_value:
            return True
        term_tokens = set(_term_tokens(term))
        if term_tokens and term_tokens.issubset(query_term_set):
            return True
    return False


def _suggest_bridge_id(bridge_kind: str, seed: str) -> str:
    safe_seed = re.sub(r"[^a-z0-9]+", "-", seed.lower()).strip("-")
    return f"{bridge_kind}:{safe_seed}".strip(":")


def _count_bridge_kinds(bridges: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for bridge in bridges:
        kind = str(bridge.get("bridge_kind", "concept"))
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))