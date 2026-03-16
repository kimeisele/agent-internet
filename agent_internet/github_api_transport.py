"""GitHub API Transport — deliver federation messages to remote repos.

Uses the GitHub Contents API to append messages to a target repo's
data/federation/nadi_inbox.json. No HTTP server required — works with
any GitHub-hosted federation peer.

The endpoint.location must be a GitHub repo URL like:
    https://github.com/kimeisele/agent-research

Requires GITHUB_TOKEN in environment (or gh CLI auth).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .models import CityEndpoint
from .steward_protocol_compat import build_maha_message_header_hex
from .steward_substrate import load_steward_substrate
from .transport import DeliveryEnvelope, DeliveryReceipt, DeliveryStatus

logger = logging.getLogger("AGENT_INTERNET.TRANSPORT.GITHUB_API")

NADI_INBOX_PATH = "data/federation/nadi_inbox.json"
NADI_BUFFER_SIZE = 144
GITHUB_API = "https://api.github.com"


def _extract_repo(location: str) -> str:
    """Extract owner/repo from a GitHub URL or direct repo reference."""
    # Direct owner/repo format
    if re.match(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$", location):
        return location
    # GitHub URL
    parsed = urlparse(location)
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return ""


@dataclass(slots=True)
class GitHubApiTransport:
    """Deliver federation envelopes to remote GitHub repos via Contents API.

    Atomic read-modify-write with SHA-based optimistic concurrency.
    GitHub rejects stale SHAs, preventing lost updates.
    """

    _token: str = field(default="", repr=False)
    _delivery_log: list[DeliveryReceipt] = field(default_factory=list)
    _last_delivery: dict[str, float] = field(default_factory=dict)
    _min_interval_s: float = 10.0  # Rate limit per target repo

    def __post_init__(self) -> None:
        if not self._token:
            self._token = self._load_token()

    @property
    def available(self) -> bool:
        return bool(self._token)

    def _load_token(self) -> str:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            # Try gh CLI auth
            try:
                import subprocess
                result = subprocess.run(
                    ["gh", "auth", "token"], capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    token = result.stdout.strip()
            except Exception:
                pass
        return token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"token {self._token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "agent-internet-federation-relay/1.0",
        }

    def send(self, endpoint: CityEndpoint, envelope: DeliveryEnvelope) -> DeliveryReceipt:
        """Deliver envelope to a remote repo's nadi_inbox.json via GitHub API."""
        if not self._token:
            return DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.REJECTED,
                transport="https",
                target_city_id=endpoint.city_id,
                detail="No GitHub token available",
            )

        if envelope.is_expired:
            return DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.EXPIRED,
                transport="https",
                target_city_id=endpoint.city_id,
                detail="Envelope TTL expired",
            )

        repo = _extract_repo(endpoint.location)
        if not repo:
            return DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.REJECTED,
                transport="https",
                target_city_id=endpoint.city_id,
                detail=f"Cannot extract repo from location: {endpoint.location}",
            )

        # Rate limit per target
        now = time.monotonic()
        last = self._last_delivery.get(repo, 0.0)
        if (now - last) < self._min_interval_s:
            return DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.REJECTED,
                transport="https",
                target_city_id=endpoint.city_id,
                detail=f"Rate limited ({self._min_interval_s}s between deliveries to same repo)",
            )

        # Build wire message
        message = self._envelope_to_nadi_message(envelope)

        # Read current inbox
        inbox, sha = self._get_file(repo, NADI_INBOX_PATH)

        if not sha:
            # File doesn't exist — create it
            success = self._create_file(
                repo, NADI_INBOX_PATH, [message],
                f"relay: deliver {envelope.operation} from {envelope.source_city_id}",
            )
        else:
            # Append and write back
            inbox.append(message)
            if len(inbox) > NADI_BUFFER_SIZE:
                inbox = inbox[-NADI_BUFFER_SIZE:]
            success = self._put_file(
                repo, NADI_INBOX_PATH, inbox, sha,
                f"relay: deliver {envelope.operation} from {envelope.source_city_id}",
            )

        self._last_delivery[repo] = time.monotonic()

        if success:
            receipt = DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.DELIVERED,
                transport="https",
                target_city_id=endpoint.city_id,
                detail=f"Delivered to {repo} via GitHub API",
            )
        else:
            receipt = DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                status=DeliveryStatus.REJECTED,
                transport="https",
                target_city_id=endpoint.city_id,
                detail=f"GitHub API write failed for {repo}",
            )

        self._delivery_log.append(receipt)
        return receipt

    def _envelope_to_nadi_message(self, envelope: DeliveryEnvelope) -> dict:
        """Convert envelope to NADI wire format."""
        semantics = envelope.nadi_semantics
        bindings = load_steward_substrate()
        priority_val = getattr(bindings.NadiPriority, semantics.priority.upper()).value
        msg = bindings.FederationMessage(
            source=envelope.source_city_id,
            target=envelope.target_city_id,
            operation=envelope.operation,
            payload=dict(envelope.payload),
            priority=priority_val,
            correlation_id=envelope.correlation_id,
            timestamp=envelope.created_at,
            ttl_s=semantics.ttl_s,
        )
        raw = msg.to_dict()
        raw["envelope_id"] = envelope.envelope_id
        raw["nadi_type"] = semantics.nadi_type
        raw["nadi_op"] = semantics.nadi_op
        raw["nadi_priority"] = semantics.priority
        raw["ttl_ms"] = semantics.ttl_ms
        raw["maha_header_hex"] = envelope.maha_header_hex or build_maha_message_header_hex(
            source_key=envelope.source_city_id,
            target_key=envelope.target_city_id,
            operation_key=envelope.operation,
            nadi_type=semantics.nadi_type,
            priority=semantics.priority,
            ttl_ms=semantics.ttl_ms,
        )
        return raw

    def _get_file(self, repo: str, path: str) -> tuple[list, str]:
        """Fetch a JSON file from a GitHub repo. Returns (content, sha)."""
        import urllib.request

        url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                content = json.loads(base64.b64decode(data["content"]).decode())
                return content if isinstance(content, list) else [], data["sha"]
        except Exception as e:
            logger.debug("GitHub read %s/%s failed: %s", repo, path, e)
            return [], ""

    def _put_file(self, repo: str, path: str, content: list, sha: str, message: str) -> bool:
        """Update a JSON file in a GitHub repo via Contents API."""
        import urllib.request

        url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
        encoded = base64.b64encode(json.dumps(content, indent=2).encode()).decode()
        body = json.dumps({"message": message, "content": encoded, "sha": sha}).encode()
        req = urllib.request.Request(url, data=body, headers=self._headers(), method="PUT")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning("GitHub write %s/%s failed: %s", repo, path, e)
            return False

    def _create_file(self, repo: str, path: str, content: list, message: str) -> bool:
        """Create a new JSON file in a GitHub repo."""
        import urllib.request

        url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
        encoded = base64.b64encode(json.dumps(content, indent=2).encode()).decode()
        body = json.dumps({"message": message, "content": encoded}).encode()
        req = urllib.request.Request(url, data=body, headers=self._headers(), method="PUT")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status in (200, 201)
        except Exception as e:
            logger.warning("GitHub create %s/%s failed: %s", repo, path, e)
            return False

    def delivery_log(self) -> list[DeliveryReceipt]:
        return list(self._delivery_log)
