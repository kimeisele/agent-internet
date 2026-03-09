from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

DEFAULT_PUBLICATION_WORKFLOW_NAME = "Publish Agent Web Wiki"
DEFAULT_PUBLICATION_SCHEDULE_INTERVAL_SECONDS = 3600
DEFAULT_PUBLICATION_STALE_AFTER_SECONDS = 7200


def build_publication_snapshot(
    *,
    source_sha: str,
    wiki_repo_url: str,
    status: str,
    workflow_name: str,
    push_requested: bool,
    prune_generated: bool,
    published_at_utc: str | None = None,
    schedule_interval_seconds: int | None = DEFAULT_PUBLICATION_SCHEDULE_INTERVAL_SECONDS,
    stale_after_seconds: int | None = DEFAULT_PUBLICATION_STALE_AFTER_SECONDS,
    commit_message: str | None = None,
) -> dict:
    timestamp = published_at_utc or current_utc_timestamp()
    return {
        "kind": "agent_internet_publication_status",
        "version": 1,
        "status": status,
        "published_at_utc": timestamp,
        "source_sha": str(source_sha or "unknown"),
        "wiki_repo_url": sanitize_remote_url(wiki_repo_url),
        "workflow_name": str(workflow_name or ""),
        "push_requested": bool(push_requested),
        "prune_generated": bool(prune_generated),
        "schedule_interval_seconds": schedule_interval_seconds,
        "stale_after_seconds": stale_after_seconds,
        "heartbeat_enabled": bool(schedule_interval_seconds),
        "commit_message": str(commit_message or ""),
    }


def current_utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sanitize_remote_url(url: str | None) -> str:
    value = str(url or "").strip()
    if not value or "://" not in value:
        return value
    parts = urlsplit(value)
    if not (parts.username or parts.password):
        return value
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def render_publication_status_page(snapshot: dict | None) -> str:
    status = dict(snapshot or {})
    lines = [
        "# Publication Status",
        "",
        f"- Status: `{status.get('status', 'unknown')}`",
        f"- Published At (UTC): `{status.get('published_at_utc', '')}`",
        f"- Source SHA: `{status.get('source_sha', '')}`",
        f"- Workflow: `{status.get('workflow_name', '')}`",
        f"- Push Requested: `{status.get('push_requested', False)}`",
        f"- Prune Generated: `{status.get('prune_generated', False)}`",
        f"- Heartbeat Enabled: `{status.get('heartbeat_enabled', False)}`",
        f"- Schedule Interval (s): `{status.get('schedule_interval_seconds')}`",
        f"- Stale After (s): `{status.get('stale_after_seconds')}`",
        f"- Wiki Repo: `{status.get('wiki_repo_url', '')}`",
        "",
        "## Freshness Contract",
        "",
    ]
    if status.get("published_at_utc") and status.get("stale_after_seconds"):
        lines.append("- Treat the membrane as stale when `now - published_at_utc > stale_after_seconds`.")
    else:
        lines.append("- No staleness contract is published yet.")
    commit_message = str(status.get("commit_message", "")).strip()
    if commit_message:
        lines.extend(["", "## Commit Intent", "", f"- `{commit_message}`"])
    lines.extend(["", "## Raw Snapshot", "", json.dumps(status, indent=2, sort_keys=True)])
    return "\n".join(lines).rstrip() + "\n"