from __future__ import annotations

from pathlib import Path

from .agent_web import build_agent_web_manifest_for_plane, build_agent_web_manifest_from_repo_root


def build_agent_web_public_graph(manifest: dict) -> dict:
    identity = dict(manifest.get("identity", {}))
    assistant = dict(manifest.get("assistant", {}))
    city_id = str(identity.get("city_id", ""))

    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    node_ids: set[str] = set()
    edge_ids: set[str] = set()

    def add_node(node_id: str, kind: str, label: str, **attrs: object) -> None:
        if not node_id or node_id in node_ids:
            return
        node_ids.add(node_id)
        nodes.append({"node_id": node_id, "kind": kind, "label": label, **attrs})

    def add_edge(kind: str, source_id: str, target_id: str, **attrs: object) -> None:
        if not source_id or not target_id:
            return
        edge_id = f"{kind}:{source_id}->{target_id}"
        if edge_id in edge_ids:
            return
        edge_ids.add(edge_id)
        edges.append({"edge_id": edge_id, "kind": kind, "source_id": source_id, "target_id": target_id, **attrs})

    city_node_id = f"city:{city_id}"
    add_node(city_node_id, "city", city_id or "unknown-city", slug=str(identity.get("slug", "")))

    repo = str(identity.get("repo", ""))
    if repo:
        repo_node_id = f"repo:{repo}"
        add_node(repo_node_id, "repository", repo, repo=repo)
        add_edge("published_from_repo", city_node_id, repo_node_id)

    assistant_id = str(assistant.get("assistant_id", ""))
    assistant_node_id = f"assistant:{city_id}:{assistant_id}" if city_id or assistant_id else ""
    if assistant_node_id:
        add_node(
            assistant_node_id,
            "assistant",
            assistant_id or "assistant",
            assistant_kind=str(assistant.get("assistant_kind", "")),
            city_health=str(assistant.get("city_health", "")),
        )
        add_edge("hosts_assistant", city_node_id, assistant_node_id)

    for campaign in manifest.get("campaigns", []):
        campaign_id = str(campaign.get("id", ""))
        campaign_node_id = f"campaign:{city_id}:{campaign_id}"
        add_node(
            campaign_node_id,
            "campaign",
            str(campaign.get("title") or campaign_id),
            status=str(campaign.get("status", "unknown")),
        )
        add_edge("runs_campaign", city_node_id, campaign_node_id)
        if assistant_node_id:
            add_edge("focuses_on", assistant_node_id, campaign_node_id)

    manifest_document_id = "document:agent_web"
    for document in manifest.get("documents", []):
        document_id = str(document.get("document_id", ""))
        document_node_id = f"document:{document_id}"
        add_node(
            document_node_id,
            "document",
            str(document.get("title") or document_id),
            document_kind=str(document.get("kind", "")),
            href=str(document.get("href", "")),
            entrypoint=bool(document.get("entrypoint", False)),
        )
        add_edge("publishes_document", city_node_id, document_node_id)
        if bool(document.get("entrypoint", False)):
            add_edge("entrypoint", city_node_id, document_node_id)
        if document_id != "agent_web":
            add_edge("links_to", manifest_document_id, document_node_id)

    add_node(manifest_document_id, "document", "Agent Web", document_kind="manifest", href="Agent-Web.md", entrypoint=True)
    add_edge("publishes_document", city_node_id, manifest_document_id)
    add_edge("entrypoint", city_node_id, manifest_document_id)

    for link in manifest.get("links", []):
        kind = str(link.get("kind", ""))
        if kind == "document":
            target_document_id = str(link.get("document_id", ""))
            if target_document_id and target_document_id != "agent_web":
                add_edge("links_to", manifest_document_id, f"document:{target_document_id}", rel=str(link.get("rel", "")))
        elif kind == "repository":
            href = str(link.get("href", ""))
            repo_target_id = f"repository_link:{href}"
            add_node(repo_target_id, "repository_link", href, href=href)
            add_edge("links_to_repository", manifest_document_id, repo_target_id, rel=str(link.get("rel", "")))

    for service in manifest.get("service_affordances", []):
        service_id = str(service.get("service_id", ""))
        service_node_id = f"service:{service_id}"
        add_node(
            service_node_id,
            "service",
            service_id,
            transport=str(service.get("transport", "")),
            href=str(service.get("href", "")),
            auth_required=bool(service.get("auth_required", False)),
        )
        add_edge("offers_service", city_node_id, service_node_id)
        add_edge("documents_service", "document:services", service_node_id)

    for route in manifest.get("route_affordances", []):
        destination_prefix = str(route.get("destination_prefix", ""))
        route_node_id = f"route:{city_id}:{destination_prefix}"
        add_node(
            route_node_id,
            "route",
            destination_prefix,
            next_hop_city_id=str(route.get("next_hop_city_id", "")),
            nadi_type=str(route.get("nadi_type", "")),
            priority=str(route.get("priority", "")),
        )
        add_edge("publishes_route", city_node_id, route_node_id)
        add_edge("documents_route", "document:routes", route_node_id)

    for space in manifest.get("spaces", []):
        space_id = str(space.get("space_id", ""))
        space_node_id = f"space:{space_id}"
        add_node(space_node_id, "space", str(space.get("display_name") or space_id), space_kind=str(space.get("kind", "")))
        add_edge("hosts_space", city_node_id, space_node_id)

    for slot in manifest.get("slots", []):
        slot_id = str(slot.get("slot_id", ""))
        slot_node_id = f"slot:{slot_id}"
        add_node(slot_node_id, "slot", slot_id, slot_kind=str(slot.get("slot_kind", "")), status=str(slot.get("status", "")))
        space_id = str(slot.get("space_id", ""))
        if space_id:
            add_edge("contains_slot", f"space:{space_id}", slot_node_id)

    return {
        "kind": "agent_web_public_graph",
        "version": 1,
        "city_id": city_id,
        "root_node_id": city_node_id,
        "nodes": nodes,
        "edges": edges,
        "stats": {"node_count": len(nodes), "edge_count": len(edges)},
    }


def build_agent_web_public_graph_from_repo_root(
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
    return build_agent_web_public_graph(manifest)


def build_agent_web_public_graph_for_plane(
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
    return build_agent_web_public_graph(manifest)