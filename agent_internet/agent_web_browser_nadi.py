"""NadiSource — PageSource for agent-to-agent messaging via ``nadi://`` URLs.

URL scheme::

    nadi://{city_id}/inbox     → messages received by this city
    nadi://{city_id}/outbox    → delivery receipts for messages sent from this city
    nadi://{city_id}/send      → form to compose and send a message
    nadi://                    → overview of registered cities and transports

The browser NAVIGATES, the relay DELIVERS.  This module is the bridge.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .transport import DeliveryEnvelope


@dataclass(slots=True)
class NadiSource:
    """PageSource that handles ``nadi://`` URLs for agent messaging."""

    _control_plane: object = field(repr=False)

    def can_handle(self, url: str) -> bool:
        return url.startswith("nadi://")

    def fetch(self, url: str, *, config: object = None) -> object:
        """Route nadi:// URLs to messaging views."""
        path = url.removeprefix("nadi://").strip("/")

        # nadi:// root — overview
        if not path:
            return self._render_overview(url)

        parts = path.split("/", 1)
        city_id = parts[0]
        sub = parts[1] if len(parts) > 1 else ""

        if sub == "inbox":
            return self._render_inbox(url, city_id)
        elif sub == "outbox":
            return self._render_outbox(url, city_id)
        elif sub == "send":
            return self._render_send(url, city_id)
        elif sub == "":
            return self._render_city_hub(url, city_id)
        else:
            return _build_nadi_page(url, status=404,
                                    error=f"unknown_nadi_path:{path}")

    def submit(self, url: str, data: dict[str, str]) -> tuple[str, str]:
        """Handle a POST to a nadi:// action URL.

        Returns (redirect_url, error).
        """
        path = url.removeprefix("nadi://").strip("/")

        # nadi://{city_id}/send
        parts = path.split("/", 1)
        if len(parts) == 2 and parts[1] == "send":
            return self._handle_send(parts[0], data)

        return "", f"Unknown nadi submit action: {path}"

    # -- Renderers --

    def _render_overview(self, url: str) -> object:
        cp = self._control_plane
        identities = cp.registry.list_identities()  # type: ignore[attr-defined]
        city_ids = [i.city_id for i in identities]
        schemes = cp.transports.schemes() if hasattr(cp, "transports") else ()  # type: ignore[attr-defined]

        parts = ["# Nadi Messaging", "",
                 f"Registered cities: {len(city_ids)}",
                 f"Transports: {', '.join(schemes) or 'none'}", ""]

        links: list[tuple[str, str]] = []
        for cid in city_ids:
            links.append((f"nadi://{cid}", cid))
            links.append((f"nadi://{cid}/inbox", f"{cid}/inbox"))
            links.append((f"nadi://{cid}/send", f"{cid}/send"))

        links.append(("about:relay", "Relay"))
        links.append(("about:cities", "Cities"))

        return _build_nadi_page(url, title="Nadi Messaging",
                                text="\n".join(parts), raw_links=links)

    def _render_city_hub(self, url: str, city_id: str) -> object:
        parts = [f"# Nadi: {city_id}", "",
                 "Message hub for this city.", ""]
        links = [
            (f"nadi://{city_id}/inbox", "Inbox"),
            (f"nadi://{city_id}/outbox", "Outbox"),
            (f"nadi://{city_id}/send", "Send Message"),
            (f"cp://cities/{city_id}", f"City: {city_id}"),
            ("nadi://", "All Cities"),
        ]
        return _build_nadi_page(url, title=f"Nadi: {city_id}",
                                text="\n".join(parts), raw_links=links)

    def _render_inbox(self, url: str, city_id: str) -> object:
        cp = self._control_plane
        messages: list[DeliveryEnvelope] = []

        # Try to read from LoopbackTransport queues (non-destructive peek)
        for scheme in (cp.transports.schemes() if hasattr(cp, "transports") else ()):  # type: ignore[attr-defined]
            transport = cp.transports.get(scheme)  # type: ignore[attr-defined]
            if hasattr(transport, "_queues"):
                queue = transport._queues.get(city_id, [])
                messages.extend(queue)

        parts = [f"# Inbox: {city_id}", "",
                 f"Messages: {len(messages)}", ""]

        for i, env in enumerate(messages):
            parts.append(f"## Message {i + 1}")
            parts.append(f"  From: {env.source_city_id}")
            parts.append(f"  Operation: {env.operation}")
            parts.append(f"  Envelope: {env.envelope_id}")
            if env.payload:
                payload_str = json.dumps(env.payload, indent=2, default=str)
                parts.append(f"  Payload: {payload_str}")
            parts.append("")

        if not messages:
            parts.append("(no messages in inbox)")

        links = [
            (f"nadi://{city_id}", f"Hub: {city_id}"),
            (f"nadi://{city_id}/send", "Send Message"),
            (f"nadi://{city_id}/outbox", "Outbox"),
            ("nadi://", "All Cities"),
        ]
        return _build_nadi_page(url, title=f"Inbox: {city_id}",
                                text="\n".join(parts), raw_links=links)

    def _render_outbox(self, url: str, city_id: str) -> object:
        cp = self._control_plane
        receipts = []

        # Collect delivery receipts from all transports
        for scheme in (cp.transports.schemes() if hasattr(cp, "transports") else ()):  # type: ignore[attr-defined]
            transport = cp.transports.get(scheme)  # type: ignore[attr-defined]
            if hasattr(transport, "receipts"):
                for r in transport.receipts():
                    receipts.append(r)

        # Filter to receipts where the target is relevant or all if city-specific
        # (receipts don't track source, so we show all)
        parts = [f"# Outbox: {city_id}", "",
                 f"Delivery receipts: {len(receipts)}", ""]

        for r in receipts:
            status = r.status.name if hasattr(r.status, "name") else r.status
            parts.append(f"  {r.envelope_id}: {status} → {r.target_city_id} "
                         f"via {r.transport}")
            if r.detail:
                parts.append(f"    Detail: {r.detail}")

        if not receipts:
            parts.append("(no delivery receipts)")

        links = [
            (f"nadi://{city_id}", f"Hub: {city_id}"),
            (f"nadi://{city_id}/inbox", "Inbox"),
            (f"nadi://{city_id}/send", "Send Message"),
            ("nadi://", "All Cities"),
        ]
        return _build_nadi_page(url, title=f"Outbox: {city_id}",
                                text="\n".join(parts), raw_links=links)

    def _render_send(self, url: str, city_id: str) -> object:
        cp = self._control_plane
        identities = cp.registry.list_identities()  # type: ignore[attr-defined]
        other_cities = [i.city_id for i in identities if i.city_id != city_id]

        parts = [f"# Send Message from: {city_id}", "",
                 f"Available targets: {', '.join(other_cities) or 'none'}", ""]

        links = [
            (f"nadi://{city_id}", f"Hub: {city_id}"),
            (f"nadi://{city_id}/inbox", "Inbox"),
            (f"nadi://{city_id}/outbox", "Outbox"),
            ("nadi://", "All Cities"),
        ]

        forms = [{
            "action": f"nadi://{city_id}/send", "method": "POST",
            "form_id": "nadi_send",
            "fields": [
                {"name": "target_city_id", "required": True, "value": ""},
                {"name": "operation", "required": True, "value": "sync"},
                {"name": "payload", "required": False, "value": "{}",
                 "field_type": "text"},
            ],
        }]

        return _build_nadi_page(url, title=f"Send: {city_id}",
                                text="\n".join(parts), raw_links=links,
                                raw_forms=forms)

    def _handle_send(self, city_id: str, data: dict[str, str]) -> tuple[str, str]:
        """Submit a message from city_id to target."""
        target = data.get("target_city_id", "").strip()
        operation = data.get("operation", "").strip()
        if not target:
            return "", "Missing required field: target_city_id"
        if not operation:
            return "", "Missing required field: operation"

        payload_str = data.get("payload", "{}").strip() or "{}"
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError as exc:
            return "", f"Invalid JSON payload: {exc}"

        envelope = DeliveryEnvelope(
            source_city_id=city_id,
            target_city_id=target,
            operation=operation,
            payload=payload if isinstance(payload, dict) else {"data": payload},
        )

        cp = self._control_plane
        try:
            receipt = cp.relay_envelope(envelope)  # type: ignore[attr-defined]
        except Exception as exc:
            return "", f"Relay failed: {exc}"

        status = receipt.status.name if hasattr(receipt.status, "name") else receipt.status
        if status in ("DELIVERED", "delivered"):
            return f"nadi://{city_id}/outbox", ""
        return "", f"Relay status: {status} — {receipt.detail}"


# ---------------------------------------------------------------------------
# Page builder helper
# ---------------------------------------------------------------------------

def _build_nadi_page(
    url: str, *, title: str = "", text: str = "", status: int = 200,
    error: str = "", raw_links: list[tuple[str, str]] | None = None,
    raw_forms: list[dict] | None = None,
) -> object:
    """Build a BrowserPage from nadi render output."""
    from .agent_web_browser import BrowserPage, FormField, PageForm, PageLink, PageMeta

    links = tuple(
        PageLink(href=href, text=label, index=i)
        for i, (href, label) in enumerate(raw_links or [])
    )
    forms = tuple(
        PageForm(
            action=f["action"], method=f.get("method", "POST"),
            form_id=f.get("form_id", ""), index=i,
            fields=tuple(
                FormField(name=fd["name"], field_type=fd.get("field_type", "text"),
                          value=fd.get("value", ""), required=fd.get("required", True))
                for fd in f.get("fields", [])
            ),
        )
        for i, f in enumerate(raw_forms or [])
    )
    return BrowserPage(
        url=url, status_code=status, title=title,
        content_text=text, links=links, forms=forms, meta=PageMeta(),
        headers={}, fetched_at=time.time(), content_type="text/plain",
        encoding="utf-8", raw_html=text, error=error,
    )
