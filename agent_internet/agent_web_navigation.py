from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .agent_city_contract import AgentCityFilesystemContract
from .agent_web import build_agent_web_manifest, build_agent_web_manifest_from_repo_root
from .assistant_surface import assistant_surface_snapshot_from_repo_root
from .file_locking import read_locked_json_value
from .git_federation import render_wiki_projection


def resolve_agent_web_link(
    manifest: dict,
    *,
    rel: str | None = None,
    href: str | None = None,
    document_id: str | None = None,
) -> dict:
    links = [dict(item) for item in manifest.get("links", []) if isinstance(item, dict)]
    if document_id:
        for link in links:
            if str(link.get("document_id", "")) == document_id:
                return link
        raise ValueError("unknown_agent_web_document_id")
    if href:
        for link in links:
            if str(link.get("href", "")) == href:
                return link
        raise ValueError("unknown_agent_web_href")

    wanted_rel = rel or "agent_web"
    for link in links:
        if str(link.get("rel", "")) == wanted_rel:
            return link
    raise ValueError("unknown_agent_web_rel")


def resolve_agent_web_document(
    manifest: dict,
    *,
    rel: str | None = None,
    href: str | None = None,
    document_id: str | None = None,
) -> tuple[dict, dict]:
    documents = [dict(item) for item in manifest.get("documents", []) if isinstance(item, dict)]
    if document_id:
        for document in documents:
            if str(document.get("document_id", "")) == document_id:
                return document, resolve_agent_web_link(manifest, document_id=document_id)
        raise ValueError("unknown_agent_web_document_id")
    if href:
        for document in documents:
            if str(document.get("href", "")) == href:
                return document, resolve_agent_web_link(manifest, href=href)
    wanted_rel = rel or "agent_web"
    for document in documents:
        if str(document.get("rel", "")) == wanted_rel:
            return document, resolve_agent_web_link(manifest, rel=wanted_rel)
    link = resolve_agent_web_link(manifest, rel=rel, href=href, document_id=document_id)
    return {}, link


def read_agent_web_document_from_repo_root(
    root: Path | str,
    *,
    state_snapshot: dict,
    rel: str | None = None,
    href: str | None = None,
    document_id: str | None = None,
    city_id: str | None = None,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
) -> dict:
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
    manifest = build_agent_web_manifest(
        peer_descriptor=peer_descriptor,
        state_snapshot=state_snapshot,
        assistant_snapshot=assistant_snapshot,
    )
    document_descriptor, link = resolve_agent_web_document(manifest, rel=rel, href=href, document_id=document_id)
    if str(link.get("media_type", "")) != "text/markdown":
        raise ValueError("unsupported_agent_web_link_media_type")

    pages = render_wiki_projection(
        peer_descriptor=peer_descriptor,
        state_snapshot=state_snapshot,
        assistant_snapshot=assistant_snapshot,
        repo_root=repo_root,
    )
    document_path = str(document_descriptor.get("href", link.get("href", "")))
    if document_path not in pages:
        raise ValueError("unresolved_agent_web_document")
    return {
        "manifest": manifest,
        "link": link,
        "document": {
            **document_descriptor,
            "path": document_path,
            "media_type": str(link.get("media_type", "text/markdown")),
            "content": pages[document_path],
        },
    }


def read_agent_web_document_for_plane(
    root: Path | str,
    *,
    plane: object,
    rel: str | None = None,
    href: str | None = None,
    document_id: str | None = None,
    city_id: str | None = None,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
) -> dict:
    from .snapshot import snapshot_control_plane

    return read_agent_web_document_from_repo_root(
        root,
        state_snapshot=snapshot_control_plane(plane),
        rel=rel,
        href=href,
        document_id=document_id,
        city_id=city_id,
        assistant_id=assistant_id,
        heartbeat_source=heartbeat_source,
    )


def discover_agent_web_from_repo_root(
    root: Path | str,
    *,
    state_snapshot: dict,
    city_id: str | None = None,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
) -> dict:
    return build_agent_web_manifest_from_repo_root(
        root,
        state_snapshot=state_snapshot,
        city_id=city_id,
        assistant_id=assistant_id,
        heartbeat_source=heartbeat_source,
    )