from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .agent_city_contract import AgentCityFilesystemContract
from .file_locking import read_locked_json_value


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

    spaces = [item for item in state_snapshot.get("spaces", []) if str(item.get("city_id", "")) == city_id]
    space_ids = {str(item.get("space_id", "")) for item in spaces}
    slots = [item for item in state_snapshot.get("slots", []) if str(item.get("space_id", "")) in space_ids]
    services = [item for item in state_snapshot.get("service_addresses", []) if str(item.get("owner_city_id", "")) == city_id]
    routes = [item for item in state_snapshot.get("routes", []) if str(item.get("owner_city_id", "")) == city_id]
    campaigns = list(assistant.get("active_campaigns", []))

    links = [
        {"rel": "wiki_home", "href": "Home.md", "media_type": "text/markdown"},
        {"rel": "assistant_surface", "href": "Assistant-Surface.md", "media_type": "text/markdown"},
        {"rel": "agent_web", "href": "Agent-Web.md", "media_type": "text/markdown"},
        {"rel": "services", "href": "Services.md", "media_type": "text/markdown"},
        {"rel": "routes", "href": "Routes.md", "media_type": "text/markdown"},
        {"rel": "cities", "href": "Cities.md", "media_type": "text/markdown"},
        {"rel": "lineage", "href": "Lineage.md", "media_type": "text/markdown"},
    ]
    wiki_repo_url = str(git_manifest.get("wiki_repo_url", ""))
    if wiki_repo_url:
        links.append({"rel": "wiki_repo", "href": wiki_repo_url, "media_type": "application/git"})

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
        "campaigns": campaigns,
        "spaces": spaces,
        "slots": slots,
        "services": services,
        "routes": routes,
        "links": links,
        "stats": {
            "campaign_count": len(campaigns),
            "space_count": len(spaces),
            "slot_count": len(slots),
            "service_count": len(services),
            "route_count": len(routes),
        },
    }