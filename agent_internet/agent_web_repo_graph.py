from __future__ import annotations

import subprocess
from pathlib import Path

from .steward_protocol_compat import _ensure_local_steward_protocol_repo_on_path


def build_agent_web_repo_graph_snapshot(
    root: Path | str,
    *,
    node_type: str | None = None,
    domain: str | None = None,
    query: str | None = None,
    limit: int = 25,
) -> dict:
    graph, source = _load_repo_graph(root)
    selected_nodes = _select_nodes(graph, node_type=node_type, domain=domain, query=query, limit=limit)
    selected_node_ids = {node["node_id"] for node in selected_nodes}
    selected_edges = _edges_touching(graph, selected_node_ids)
    selected_metrics = _metrics_for_nodes(graph, selected_node_ids)
    payload = _source_payload(root=root, source=source)
    return {
        "kind": "agent_web_repo_graph_snapshot",
        "version": 1,
        "source": payload,
        "selector": {
            "node_type": node_type or "",
            "domain": domain or "",
            "query": query or "",
            "limit": int(limit),
        },
        "summary": _graph_summary(graph),
        "nodes": selected_nodes,
        "edges": selected_edges,
        "metrics": selected_metrics,
        "constraints": [_serialize_constraint(constraint) for constraint in graph.constraints.values()],
        "stats": {
            "returned_node_count": len(selected_nodes),
            "returned_edge_count": len(selected_edges),
            "returned_metric_count": len(selected_metrics),
            "returned_constraint_count": len(graph.constraints),
        },
    }


def read_agent_web_repo_graph_neighbors(
    root: Path | str,
    *,
    node_id: str,
    relation: str | None = None,
    depth: int = 1,
    limit: int = 25,
) -> dict:
    graph, source = _load_repo_graph(root)
    anchor = graph.get_node(node_id)
    if anchor is None:
        raise ValueError(f"unknown_node:{node_id}")
    edges = _neighbor_edges(graph, node_id=node_id, relation=relation, depth=depth)
    nodes: list[dict] = []
    seen: set[str] = set()
    for edge in edges:
        for neighbor_id in (edge.source, edge.target):
            if neighbor_id == node_id or neighbor_id in seen:
                continue
            neighbor = graph.get_node(neighbor_id)
            if neighbor is None:
                continue
            seen.add(neighbor_id)
            nodes.append(_serialize_node(neighbor))
            if len(nodes) >= max(1, int(limit)):
                break
        if len(nodes) >= max(1, int(limit)):
            break
    allowed = {node_id, *[node["node_id"] for node in nodes]}
    filtered_edges = [edge for edge in (_serialize_edge(item) for item in edges) if edge["source_id"] in allowed and edge["target_id"] in allowed]
    return {
        "kind": "agent_web_repo_graph_neighbors",
        "version": 1,
        "source": _source_payload(root=root, source=source),
        "record": _serialize_node(anchor),
        "neighbors": nodes,
        "edges": filtered_edges,
        "traversal": {
            "relation": relation or "*",
            "depth": max(1, int(depth)),
            "limit": max(1, int(limit)),
        },
        "stats": {"neighbor_count": len(nodes), "edge_count": len(filtered_edges)},
    }


def read_agent_web_repo_graph_context(root: Path | str, *, concept: str) -> dict:
    graph, source = _load_repo_graph(root)
    context = graph.compile_prompt_context(str(concept)) or _fallback_context(graph, str(concept))
    return {
        "kind": "agent_web_repo_graph_context",
        "version": 1,
        "source": _source_payload(root=root, source=source),
        "concept": str(concept),
        "context": context,
        "stats": {"character_count": len(context), "line_count": len(context.splitlines())},
    }


def _load_repo_graph(root: Path | str):
    path = Path(root).resolve()
    if not path.exists():
        raise ValueError(f"missing_root:{path}")
    if path.name != "steward-protocol":
        raise ValueError(f"unsupported_repo_graph_root:{path.name}")
    source = _ensure_local_steward_protocol_repo_on_path() or "installed"
    from vibe_core.knowledge.graph import get_knowledge_graph

    return get_knowledge_graph(), source


def _select_nodes(graph, *, node_type: str | None, domain: str | None, query: str | None, limit: int) -> list[dict]:
    if query:
        nodes = list(graph.search_nodes(str(query)))
    else:
        nodes = list(graph.nodes.values())
    if node_type:
        expected = str(node_type)
        nodes = [node for node in nodes if getattr(node.type, "value", "") == expected]
        if not nodes and expected not in {getattr(node.type, "value", "") for node in graph.nodes.values()}:
            raise ValueError(f"unknown_node_type:{expected}")
    if domain:
        nodes = [node for node in nodes if str(node.domain) == str(domain)]
    nodes = sorted(nodes, key=lambda item: _node_sort_key(graph, item))
    return [_serialize_node(node) for node in nodes[: max(1, int(limit))]]


def _edges_touching(graph, node_ids: set[str]) -> list[dict]:
    payload = []
    for edges in graph.edges.values():
        for edge in edges:
            if edge.source in node_ids or edge.target in node_ids:
                payload.append(_serialize_edge(edge))
    return payload


def _metrics_for_nodes(graph, node_ids: set[str]) -> list[dict]:
    payload = []
    for node_id in sorted(node_ids):
        metric_map = graph.metrics.get(node_id, {})
        for metric in metric_map.values():
            payload.append(_serialize_metric(metric))
    return payload


def _neighbor_edges(graph, *, node_id: str, relation: str | None, depth: int) -> list:
    frontier = [(node_id, 0)]
    seen_nodes = {node_id}
    seen_edges: set[tuple[str, str, str]] = set()
    payload = []
    relation_filter = str(relation or "")
    while frontier:
        current_id, current_depth = frontier.pop(0)
        if current_depth >= max(1, int(depth)):
            continue
        for edge in graph.edges.get(current_id, []):
            if relation_filter and getattr(edge.relation, "value", "") != relation_filter:
                continue
            edge_key = (edge.source, edge.target, getattr(edge.relation, "value", ""))
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            payload.append(edge)
            if edge.target not in seen_nodes:
                seen_nodes.add(edge.target)
                frontier.append((edge.target, current_depth + 1))
    if relation_filter and payload == []:
        known = {getattr(edge.relation, "value", "") for edges in graph.edges.values() for edge in edges}
        if relation_filter not in known:
            raise ValueError(f"unknown_relation:{relation_filter}")
    return payload


def _fallback_context(graph, concept: str) -> str:
    matches = _select_nodes(graph, node_type=None, domain=None, query=concept, limit=5)
    if not matches:
        summary = _graph_summary(graph)
        return (
            f"No direct repository graph matches for `{concept}`. "
            f"Graph currently exposes {summary['node_count']} nodes, {summary['edge_count']} edges, and {summary['constraint_count']} constraints."
        )
    lines = [f"Repository graph matches for `{concept}`:"]
    for match in matches:
        lines.append(f"- {match['node_id']} ({match['type']}/{match['domain']}): {match['description']}")
        neighbor_edges = [edge for edge in _neighbor_edges(graph, node_id=match["node_id"], relation=None, depth=1)[:3]]
        for edge in neighbor_edges:
            lines.append(f"  - {edge.source} -[{getattr(edge.relation, 'value', '')}]-> {edge.target}")
    return "\n".join(lines)


def _node_sort_key(graph, node) -> tuple[int, int, str]:
    degree = _node_degree(graph, str(node.id))
    metric_count = len(graph.metrics.get(str(node.id), {}))
    return (-degree, -metric_count, str(node.id))


def _node_degree(graph, node_id: str) -> int:
    outgoing = len(graph.edges.get(node_id, []))
    incoming = sum(1 for edges in graph.edges.values() for edge in edges if edge.target == node_id)
    return outgoing + incoming


def _graph_summary(graph) -> dict:
    node_type_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}
    relation_counts: dict[str, int] = {}
    for node in graph.nodes.values():
        node_type = getattr(node.type, "value", "unknown")
        node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1
        domain_counts[str(node.domain)] = domain_counts.get(str(node.domain), 0) + 1
    edge_count = 0
    for edges in graph.edges.values():
        edge_count += len(edges)
        for edge in edges:
            relation = getattr(edge.relation, "value", "unknown")
            relation_counts[relation] = relation_counts.get(relation, 0) + 1
    return {
        "node_count": len(graph.nodes),
        "edge_count": edge_count,
        "constraint_count": len(graph.constraints),
        "metric_count": sum(len(item) for item in graph.metrics.values()),
        "node_type_counts": dict(sorted(node_type_counts.items())),
        "domain_counts": dict(sorted(domain_counts.items())),
        "relation_counts": dict(sorted(relation_counts.items())),
    }


def _source_payload(*, root: Path | str, source: str) -> dict:
    path = Path(root).resolve()
    return {
        "root": str(path),
        "repo_name": path.name,
        "repo_slug": _repo_slug(path),
        "adapter_kind": "steward_protocol_unified_knowledge_graph",
        "graph_source": source,
    }


def _repo_slug(root: Path) -> str:
    try:
        remote = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=root, text=True).strip()
    except Exception:
        return root.name
    trimmed = remote[:-4] if remote.endswith(".git") else remote
    if trimmed.startswith("git@github.com:"):
        return trimmed.split(":", 1)[1]
    if "github.com/" in trimmed:
        return trimmed.split("github.com/", 1)[1]
    return root.name


def _serialize_node(node) -> dict:
    return {
        "node_id": str(node.id),
        "type": getattr(node.type, "value", str(node.type)),
        "name": str(node.name),
        "domain": str(node.domain),
        "description": str(node.description),
        "properties": dict(node.properties),
    }


def _serialize_edge(edge) -> dict:
    return {
        "source_id": str(edge.source),
        "target_id": str(edge.target),
        "relation": getattr(edge.relation, "value", str(edge.relation)),
        "weight": float(edge.weight),
        "properties": dict(edge.properties),
    }


def _serialize_constraint(constraint) -> dict:
    return {
        "constraint_id": str(constraint.id),
        "type": getattr(constraint.type, "value", str(constraint.type)),
        "condition": str(constraint.condition),
        "action": getattr(constraint.action, "value", str(constraint.action)),
        "message": str(constraint.message),
        "applies_to": list(constraint.applies_to),
    }


def _serialize_metric(metric) -> dict:
    return {
        "node_id": str(metric.node_id),
        "metric_type": getattr(metric.metric_type, "value", str(metric.metric_type)),
        "value": float(metric.value),
        "scale_min": float(metric.scale_min),
        "scale_max": float(metric.scale_max),
    }