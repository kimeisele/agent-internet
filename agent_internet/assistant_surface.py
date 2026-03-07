from __future__ import annotations

import time
from pathlib import Path

from .agent_city_bridge import AgentCityBridge
from .agent_city_contract import AgentCityFilesystemContract
from .file_locking import read_locked_json_value
from .filesystem_transport import FilesystemFederationTransport
from .git_federation import detect_git_remote_metadata
from .models import AssistantSurfaceSnapshot, HealthStatus


def assistant_surface_snapshot_from_repo_root(
    root: Path | str,
    *,
    city_id: str | None = None,
    assistant_id: str = "moltbook_assistant",
    heartbeat_source: str = "steward-protocol/mahamantra",
) -> AssistantSurfaceSnapshot:
    repo_root = Path(root).resolve()
    contract = AgentCityFilesystemContract(root=repo_root)
    peer_raw = read_locked_json_value(contract.peer_descriptor_path, default={})
    identity_raw = peer_raw.get("identity", {}) if isinstance(peer_raw, dict) else {}
    capabilities_raw = peer_raw.get("capabilities", ()) if isinstance(peer_raw, dict) else ()
    resolved_city_id = str(city_id or identity_raw.get("city_id") or repo_root.name)
    repo_ref = str(identity_raw.get("repo", ""))
    if not repo_ref:
        try:
            repo_ref = detect_git_remote_metadata(repo_root).repo_ref
        except Exception:
            repo_ref = ""

    state = read_locked_json_value(contract.assistant_state_path, default={})
    if not isinstance(state, dict):
        state = {}
    presence = AgentCityBridge(
        city_id=resolved_city_id,
        transport=FilesystemFederationTransport(contract=contract),
        capabilities=tuple(str(item) for item in capabilities_raw),
    ).latest_presence()
    ops = state.get("ops", state.get("metrics", {}))
    if not isinstance(ops, dict):
        ops = {}
    last_post_time = float(state.get("last_post_time", 0.0) or 0.0)

    return AssistantSurfaceSnapshot(
        assistant_id=assistant_id,
        assistant_kind="moltbook_assistant",
        city_id=resolved_city_id,
        city_slug=str(identity_raw.get("slug", "")),
        repo=repo_ref,
        repo_root=str(repo_root),
        heartbeat_source=heartbeat_source,
        heartbeat=presence.heartbeat if presence is not None else None,
        last_seen_at=presence.last_seen_at if presence is not None else None,
        city_health=presence.health if presence is not None else HealthStatus.UNKNOWN,
        capabilities=tuple(str(item) for item in capabilities_raw),
        state_present=contract.assistant_state_path.exists(),
        following=_count_entries(state.get("followed", state.get("followed_agents", []))),
        invited=_count_entries(state.get("invited", state.get("invited_agents", []))),
        spotlighted=_count_entries(state.get("spotlighted", state.get("upvoted_post_ids", []))),
        total_follows=int(ops.get("follows", ops.get("total_follows", 0)) or 0),
        total_invites=int(ops.get("invites", ops.get("total_invites", 0)) or 0),
        total_posts=int(ops.get("posts", ops.get("total_posts", 0)) or 0),
        last_post_age_s=round(time.time() - last_post_time) if last_post_time > 0 else None,
        series_cursor=int(state.get("series_cursor", state.get("last_series_idx", -1)) or -1),
    )


def _count_entries(value: object) -> int:
    if isinstance(value, (list, tuple, set, frozenset)):
        return len(value)
    if isinstance(value, int):
        return value
    return 0