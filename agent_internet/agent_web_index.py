from __future__ import annotations

import re
from pathlib import Path

from .agent_web import build_agent_web_manifest_for_plane, build_agent_web_manifest_from_repo_root
from .agent_web_graph import build_agent_web_public_graph


def build_agent_web_search_index(manifest: dict, graph: dict) -> dict:
    city_id = str(manifest.get("identity", {}).get("city_id", ""))
    records: list[dict[str, object]] = []

    records.append(
        _make_record(
            record_id=f"city:{city_id}",
            kind="city",
            title=city_id or "unknown-city",
            summary=f"City {city_id} published via {manifest.get('identity', {}).get('repo', '')}",
            href="Home.md",
            tags=[city_id, str(manifest.get("identity", {}).get("slug", "")), str(manifest.get("identity", {}).get("repo", ""))],
        ),
    )

    assistant = dict(manifest.get("assistant", {}))
    assistant_id = str(assistant.get("assistant_id", ""))
    if assistant_id:
        records.append(
            _make_record(
                record_id=f"assistant:{city_id}:{assistant_id}",
                kind="assistant",
                title=assistant_id,
                summary=f"Assistant {assistant.get('assistant_kind', '')} in city {city_id}",
                href="Assistant-Surface.md",
                tags=[assistant_id, str(assistant.get("assistant_kind", "")), str(assistant.get("city_health", ""))],
            ),
        )

    for campaign in manifest.get("campaigns", []):
        records.append(
            _make_record(
                record_id=f"campaign:{city_id}:{campaign.get('id', '')}",
                kind="campaign",
                title=str(campaign.get("title") or campaign.get("id", "")),
                summary=str(campaign.get("north_star", "") or "Campaign"),
                href="Assistant-Surface.md",
                tags=[
                    str(campaign.get("id", "")),
                    str(campaign.get("status", "")),
                    *[str(item) for item in campaign.get("last_gap_summary", [])[:3]],
                ],
            ),
        )

    for document in manifest.get("documents", []):
        records.append(
            _make_record(
                record_id=f"document:{document.get('document_id', '')}",
                kind="document",
                title=str(document.get("title") or document.get("document_id", "")),
                summary=f"{document.get('kind', '')} document",
                href=str(document.get("href", "")),
                tags=[str(document.get("document_id", "")), str(document.get("kind", "")), str(document.get("rel", ""))],
            ),
        )

    for service in manifest.get("service_affordances", []):
        records.append(
            _make_record(
                record_id=f"service:{service.get('service_id', '')}",
                kind="service",
                title=str(service.get("service_id", "")),
                summary=str(service.get("href", "") or service.get("public_handle", "") or "service"),
                href="Services.md",
                tags=[
                    str(service.get("service_name", "")),
                    str(service.get("transport", "")),
                    str(service.get("public_handle", "")),
                    str(service.get("visibility", "")),
                ],
            ),
        )

    for route in manifest.get("route_affordances", []):
        records.append(
            _make_record(
                record_id=f"route:{city_id}:{route.get('destination_prefix', '')}",
                kind="route",
                title=str(route.get("destination_prefix", "")),
                summary=f"next hop {route.get('next_hop_city_id', '')}",
                href="Routes.md",
                tags=[str(route.get("next_hop_city_id", "")), str(route.get("nadi_type", "")), str(route.get("priority", ""))],
            ),
        )

    for capability_scope, items in dict(manifest.get("capabilities", {})).items():
        for capability in items:
            records.append(
                _make_record(
                    record_id=f"capability:{capability_scope}:{capability}",
                    kind="capability",
                    title=str(capability),
                    summary=f"{capability_scope} capability",
                    href="Agent-Web.md",
                    tags=[capability_scope, str(capability)],
                ),
            )

    for node in graph.get("nodes", []):
        records.append(
            _make_record(
                record_id=f"graph-node:{node.get('node_id', '')}",
                kind="graph_node",
                title=str(node.get("label") or node.get("node_id", "")),
                summary=f"public graph node {node.get('kind', '')}",
                href="Public-Graph.md",
                tags=[str(node.get("node_id", "")), str(node.get("kind", ""))],
            ),
        )

    deduped = _dedupe_records(records)
    return {
        "kind": "agent_web_search_index",
        "version": 1,
        "city_id": city_id,
        "records": deduped,
        "stats": {
            "record_count": len(deduped),
            "kind_counts": _count_by_kind(deduped),
        },
    }


def build_agent_web_search_index_from_repo_root(
    root: Path | str,
    *,
    state_snapshot: dict,
    city_id: str | None = None,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
) -> dict:
    manifest = build_agent_web_manifest_from_repo_root(
        root,
        state_snapshot=state_snapshot,
        city_id=city_id,
        assistant_id=assistant_id,
        heartbeat_source=heartbeat_source,
    )
    graph = build_agent_web_public_graph(manifest)
    return build_agent_web_search_index(manifest, graph)


def build_agent_web_search_index_for_plane(
    root: Path | str,
    *,
    plane: object,
    city_id: str | None = None,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
) -> dict:
    manifest = build_agent_web_manifest_for_plane(
        root,
        plane=plane,
        city_id=city_id,
        assistant_id=assistant_id,
        heartbeat_source=heartbeat_source,
    )
    graph = build_agent_web_public_graph(manifest)
    return build_agent_web_search_index(manifest, graph)


def search_agent_web_index(index: dict, *, query: str, limit: int = 10, expanded_terms: list[str] | tuple[str, ...] = ()) -> dict:
    query_value = str(query).strip()
    query_terms = set(_terms(query_value))
    normalized_expanded_terms = [str(item).strip() for item in expanded_terms if str(item).strip()]
    for term in normalized_expanded_terms:
        query_terms.update(_terms(term))
    scored: list[tuple[int, dict[str, object], list[str]]] = []
    for record in index.get("records", []):
        score, matched_terms = _score_record(record, query_value, query_terms)
        if score <= 0:
            continue
        scored.append((score, record, matched_terms))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("kind", "")), str(item[1].get("title", ""))))
    results = [
        {**record, "score": score, "matched_terms": matched_terms}
        for score, record, matched_terms in scored[: max(1, int(limit))]
    ]
    return {
        "kind": "agent_web_search_results",
        "version": 1,
        "query": query_value,
        "results": results,
        "expanded_terms": normalized_expanded_terms,
        "stats": {"result_count": len(results), "indexed_record_count": int(index.get("stats", {}).get("record_count", 0))},
    }


def _make_record(*, record_id: str, kind: str, title: str, summary: str, href: str, tags: list[str]) -> dict[str, object]:
    normalized_tags = [tag for tag in (str(item).strip() for item in tags) if tag]
    term_source = " ".join([title, summary, *normalized_tags])
    return {
        "record_id": record_id,
        "kind": kind,
        "title": title,
        "summary": summary,
        "href": href,
        "tags": normalized_tags,
        "terms": sorted(_terms(term_source)),
    }


def _terms(value: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9_./:-]+", value.lower()) if term}


def _score_record(record: dict, query_value: str, query_terms: set[str]) -> tuple[int, list[str]]:
    title = str(record.get("title", "")).lower()
    summary = str(record.get("summary", "")).lower()
    tags = {str(item).lower() for item in record.get("tags", [])}
    terms = {str(item).lower() for item in record.get("terms", [])}
    score = 0
    matched_terms: list[str] = []
    if query_value and query_value.lower() in title:
        score += 30
    if query_value and query_value.lower() in summary:
        score += 12
    for term in query_terms:
        matched = False
        if term in tags:
            score += 15
            matched = True
        elif term in terms:
            score += 6
            matched = True
        elif any(term in candidate for candidate in tags | terms):
            score += 3
            matched = True
        if matched:
            matched_terms.append(term)
    if query_terms and len(matched_terms) == len(query_terms):
        score += 5
    return score, matched_terms


def _dedupe_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    deduped: list[dict[str, object]] = []
    for record in records:
        record_id = str(record.get("record_id", ""))
        if not record_id or record_id in seen:
            continue
        seen.add(record_id)
        deduped.append(record)
    return deduped


def _count_by_kind(records: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        kind = str(record.get("kind", "unknown"))
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))