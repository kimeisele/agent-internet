from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .agent_city_contract import AgentCityFilesystemContract
from .authority_contracts import build_authority_document_specs
from .agent_web_repo_graph_capabilities import build_agent_web_repo_graph_capability_manifest
from .agent_web_repo_graph_contracts import build_agent_web_repo_graph_contract_manifest
from .agent_web_semantic_capabilities import build_agent_web_semantic_capability_manifest
from .agent_web_semantic_contracts import build_agent_web_semantic_contract_manifest
from .file_locking import read_locked_json_value


BASE_DOCUMENT_SPECS = (
    ("home", "wiki_home", "summary", "Home", "Home.md", True),
    ("node_health", "node_health", "node_health", "Node Health", "Node-Health.md", True),
    ("publication_status", "publication_status", "publication_status", "Publication Status", "Publication-Status.md", True),
    ("federation_status", "federation_status", "federation_status", "Federation Status", "Federation-Status.md", True),
    ("surface_integrity", "surface_integrity", "surface_integrity", "Surface Integrity", "Surface-Integrity.md", False),
    ("repo_quality", "repo_quality", "repo_quality", "Repo Quality", "Repo-Quality.md", False),
    ("assistant_surface", "assistant_surface", "assistant_surface", "Assistant Surface", "Assistant-Surface.md", True),
    ("agent_web", "agent_web", "manifest", "Agent Web", "Agent-Web.md", True),
)


TAIL_DOCUMENT_SPECS = (
    ("git_federation", "git_federation", "federation_manifest", "Git Federation", "Git-Federation.md", False),
    ("semantic_capabilities", "semantic_capabilities", "semantic_capability_manifest", "Semantic Capabilities", "Semantic-Capabilities.md", True),
    ("semantic_contracts", "semantic_contracts", "semantic_contract_manifest", "Semantic Contracts", "Semantic-Contracts.md", True),
    ("repo_graph_capabilities", "repo_graph_capabilities", "repo_graph_capability_manifest", "Repo Graph Capabilities", "Repo-Graph-Capabilities.md", True),
    ("repo_graph_contracts", "repo_graph_contracts", "repo_graph_contract_manifest", "Repo Graph Contracts", "Repo-Graph-Contracts.md", True),
    ("public_graph", "public_graph", "public_graph", "Public Graph", "Public-Graph.md", True),
    ("search_index", "search_index", "search_index", "Search Index", "Search-Index.md", False),
    ("services", "services", "service_index", "Services", "Services.md", True),
    ("routes", "routes", "route_index", "Routes", "Routes.md", False),
    ("cities", "cities", "city_index", "Cities", "Cities.md", False),
    ("lineage", "lineage", "lineage", "Lineage", "Lineage.md", False),
)


def build_document_specs(state_snapshot: dict) -> tuple[tuple[str, str, str, str, str, bool], ...]:
    return BASE_DOCUMENT_SPECS + build_authority_document_specs(state_snapshot) + TAIL_DOCUMENT_SPECS


def build_agent_web_manifest_from_repo_root(
    root: Path | str,
    *,
    state_snapshot: dict,
    city_id: str | None = None,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
) -> dict:
    from .assistant_surface import assistant_surface_snapshot_from_repo_root

    repo_root = Path(root).resolve()
    contract = AgentCityFilesystemContract(root=repo_root)
    peer_descriptor = read_locked_json_value(contract.peer_descriptor_path, default={})
    if not isinstance(peer_descriptor, dict):
        peer_descriptor = {}
    assistant_snapshot = asdict(
        assistant_surface_snapshot_from_repo_root(
            repo_root,
            city_id=city_id,
            assistant_id=assistant_id,
            heartbeat_source=heartbeat_source,
        ),
    )
    return build_agent_web_manifest(
        peer_descriptor=peer_descriptor,
        state_snapshot=state_snapshot,
        assistant_snapshot=assistant_snapshot,
    )


def build_agent_web_manifest_for_plane(
    root: Path | str,
    *,
    plane: object,
    city_id: str | None = None,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
) -> dict:
    from .snapshot import snapshot_control_plane

    return build_agent_web_manifest_from_repo_root(
        root,
        state_snapshot=snapshot_control_plane(plane),
        city_id=city_id,
        assistant_id=assistant_id,
        heartbeat_source=heartbeat_source,
    )


def build_agent_web_manifest(*, peer_descriptor: dict, state_snapshot: dict, assistant_snapshot: dict | None = None) -> dict:
    identity = dict(peer_descriptor.get("identity", {}))
    git_manifest = dict(peer_descriptor.get("git_federation", {}))
    assistant = dict(assistant_snapshot or {})
    city_id = str(identity.get("city_id") or assistant.get("city_id") or "")
    peer_capabilities = [str(item) for item in peer_descriptor.get("capabilities", [])]
    assistant_capabilities = [str(item) for item in assistant.get("capabilities", [])]

    spaces = [item for item in state_snapshot.get("spaces", []) if str(item.get("city_id", "")) == city_id]
    space_ids = {str(item.get("space_id", "")) for item in spaces}
    slots = [item for item in state_snapshot.get("slots", []) if str(item.get("space_id", "")) in space_ids]
    services = [item for item in state_snapshot.get("service_addresses", []) if str(item.get("owner_city_id", "")) == city_id]
    routes = [item for item in state_snapshot.get("routes", []) if str(item.get("owner_city_id", "")) == city_id]
    campaigns = list(assistant.get("active_campaigns", []))
    documents = _build_documents(state_snapshot)
    wiki_repo_url = str(git_manifest.get("wiki_repo_url", ""))
    links = _build_links(documents, wiki_repo_url=wiki_repo_url)
    semantic_capabilities = build_agent_web_semantic_capability_manifest()
    semantic_contracts = build_agent_web_semantic_contract_manifest()
    repo_graph_capabilities = build_agent_web_repo_graph_capability_manifest()
    repo_graph_contracts = build_agent_web_repo_graph_contract_manifest()

    return {
        "kind": "agent_web_manifest",
        "version": 1,
        "identity": {
            "city_id": city_id,
            "slug": str(identity.get("slug", "")),
            "repo": str(identity.get("repo", assistant.get("repo", ""))),
        },
        "assistant": {
            "assistant_id": str(assistant.get("assistant_id", "")),
            "assistant_kind": str(assistant.get("assistant_kind", "")),
            "heartbeat": assistant.get("heartbeat"),
            "heartbeat_source": str(assistant.get("heartbeat_source", "")),
            "city_health": str(assistant.get("city_health", "")),
        },
        "capabilities": {
            "city": peer_capabilities,
            "assistant": assistant_capabilities,
        },
        "documents": documents,
        "entrypoints": _build_entrypoints(state_snapshot),
        "semantic_capabilities": semantic_capabilities,
        "semantic_contracts": semantic_contracts,
        "repo_graph_capabilities": repo_graph_capabilities,
        "repo_graph_contracts": repo_graph_contracts,
        "campaigns": campaigns,
        "spaces": spaces,
        "slots": slots,
        "services": services,
        "routes": routes,
        "service_affordances": [_normalize_service_affordance(item) for item in services],
        "route_affordances": [_normalize_route_affordance(item) for item in routes],
        "links": links,
        "stats": {
            "campaign_count": len(campaigns),
            "space_count": len(spaces),
            "slot_count": len(slots),
            "service_count": len(services),
            "route_count": len(routes),
        },
    }


def _build_documents(state_snapshot: dict) -> list[dict[str, object]]:
    return [
        {
            "document_id": document_id,
            "rel": rel,
            "kind": kind,
            "title": title,
            "href": href,
            "media_type": "text/markdown",
            "entrypoint": entrypoint,
        }
        for document_id, rel, kind, title, href, entrypoint in build_document_specs(state_snapshot)
    ]


def _build_links(documents: list[dict[str, object]], *, wiki_repo_url: str) -> list[dict[str, object]]:
    links = [
        {
            "rel": str(document["rel"]),
            "href": str(document["href"]),
            "media_type": str(document["media_type"]),
            "kind": "document",
            "document_id": str(document["document_id"]),
            "document_kind": str(document["kind"]),
            "entrypoint": bool(document.get("entrypoint", False)),
        }
        for document in documents
    ]
    if wiki_repo_url:
        links.append({"rel": "wiki_repo", "href": wiki_repo_url, "media_type": "application/git", "kind": "repository"})
    return links


def _build_entrypoints(state_snapshot: dict) -> dict[str, dict[str, str]]:
    entrypoints = {"default": {"document_id": "agent_web", "rel": "agent_web"}}
    for document_id, rel, _kind, _title, _href, entrypoint in build_document_specs(state_snapshot):
        if entrypoint and document_id != "agent_web":
            entrypoints[document_id] = {"document_id": document_id, "rel": rel}
    return entrypoints


def _normalize_service_affordance(service: dict) -> dict[str, object]:
    return {
        "kind": "service_endpoint",
        "service_id": str(service.get("service_id", "")),
        "service_name": str(service.get("service_name", "")),
        "public_handle": str(service.get("public_handle", "")),
        "transport": str(service.get("transport", "")),
        "href": str(service.get("location", "")),
        "visibility": str(service.get("visibility", "")),
        "auth_required": bool(service.get("auth_required", False)),
        "required_scopes": [str(item) for item in service.get("required_scopes", [])],
        "document_id": "services",
    }


def _normalize_route_affordance(route: dict) -> dict[str, object]:
    return {
        "kind": "route_resolution",
        "destination_prefix": str(route.get("destination_prefix", "")),
        "next_hop_city_id": str(route.get("next_hop_city_id", "")),
        "nadi_type": str(route.get("nadi_type", "")),
        "priority": str(route.get("priority", "")),
        "document_id": "routes",
    }