"""Browser ↔ Control Plane integration.

Provides:
- ``ControlPlaneSource`` — a ``PageSource`` that intercepts ``cp://`` URLs
  and renders data from ``AgentInternetControlPlane``.
- ``render_about_*`` helpers that power the ``about:cities``, ``about:trust``,
  ``about:routes``, ``about:spaces``, and ``about:intents`` pages.
- ``handle_cp_submit`` — routes form submissions to control plane writes.

The browser SHOWS, the control plane KNOWS.  This module is the lens.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from secrets import token_hex

logger = logging.getLogger("AGENT_INTERNET.WEB_BROWSER.CONTROL_PLANE")

# Local type alias — keeps render functions decoupled from browser imports.
# Each renderer returns (title, text, links, forms).
_Links = list[tuple[str, str]]


def _F(name: str, *, required: bool = True, value: str = "",
       field_type: str = "text") -> dict:
    """Shorthand for form field dicts (converted to FormField in _build_page)."""
    return {"name": name, "field_type": field_type, "value": value,
            "required": required}


# ---------------------------------------------------------------------------
# about: page renderers — each returns (title, text, links, forms)
# ---------------------------------------------------------------------------

def render_about_cities(cp: object) -> tuple[str, str, _Links, list[dict]]:
    """Render about:cities with a Register City form and Browse Repo links."""
    identities = cp.registry.list_identities()  # type: ignore[attr-defined]
    endpoints = {e.city_id: e for e in cp.registry.list_endpoints()}  # type: ignore[attr-defined]
    presences = {p.city_id: p for p in cp.registry.list_cities()}  # type: ignore[attr-defined]

    parts = ["# Registered Cities", "", f"Total: {len(identities)}", ""]
    links: _Links = []

    for ident in identities:
        cid = ident.city_id
        ep = endpoints.get(cid)
        pr = presences.get(cid)
        parts.append(f"## {cid}")
        if ident.slug:
            parts.append(f"  Slug: {ident.slug}")
        if ident.repo:
            parts.append(f"  Repo: {ident.repo}")
        if ident.labels:
            parts.append(f"  Labels: {', '.join(f'{k}={v}' for k, v in ident.labels.items())}")
        if ep:
            parts.append(f"  Endpoint: {ep.transport}://{ep.location}")
        if pr:
            parts.append(f"  Health: {pr.health.name if hasattr(pr.health, 'name') else pr.health}")
            if pr.capabilities:
                parts.append(f"  Capabilities: {', '.join(pr.capabilities)}")
        parts.append("")
        links.append((f"cp://cities/{cid}", cid))
        links.append((f"about:trust?city={cid}", f"Trust: {cid}"))
        # Browse Repo link (System → Web bridge)
        if ident.repo:
            links.append((f"https://github.com/{ident.repo}",
                          f"Browse: {ident.repo}"))

    links.append(("about:routes", "Routes"))
    links.append(("about:spaces", "Spaces"))
    links.append(("about:intents", "Intents"))
    links.append(("about:relay", "Relay"))
    links.append(("about:environment", "Environment"))

    forms = [{
        "action": "cp://cities/register", "method": "POST",
        "form_id": "register_city",
        "fields": [
            _F("city_id"), _F("slug", required=False),
            _F("repo", required=False),
            _F("transport", value="https"), _F("location"),
        ],
    }]
    return "Cities — Agent Web Browser", "\n".join(parts), links, forms


def render_about_city_detail(cp: object, city_id: str) -> tuple[str, str, _Links, list[dict]]:
    """Render detail for a single city."""
    ident = cp.registry.get_identity(city_id)  # type: ignore[attr-defined]
    if not ident:
        return (f"City Not Found: {city_id}",
                f"# City Not Found\n\nNo city with ID: {city_id}", [], [])

    ep = cp.registry.get_endpoint(city_id)  # type: ignore[attr-defined]
    pr = cp.registry.get_presence(city_id)  # type: ignore[attr-defined]
    link_addr = cp.registry.get_link_address(city_id)  # type: ignore[attr-defined]
    net_addr = cp.registry.get_network_address(city_id)  # type: ignore[attr-defined]

    parts = [f"# City: {city_id}", ""]
    if ident.slug:
        parts.append(f"Slug: {ident.slug}")
    if ident.repo:
        parts.append(f"Repo: {ident.repo}")
    if ident.labels:
        parts.append(f"Labels: {', '.join(f'{k}={v}' for k, v in ident.labels.items())}")
    if ep:
        parts.extend(["", "## Endpoint",
                       f"  Transport: {ep.transport}", f"  Location: {ep.location}"])
    if pr:
        parts.extend(["", "## Presence",
                       f"  Health: {pr.health.name if hasattr(pr.health, 'name') else pr.health}"])
        if pr.capabilities:
            parts.append(f"  Capabilities: {', '.join(pr.capabilities)}")
    if link_addr:
        parts.extend(["", "## Lotus Link Address",
                       f"  MAC: {link_addr.mac_address}",
                       f"  Interface: {link_addr.interface}"])
    if net_addr:
        parts.extend(["", "## Lotus Network Address",
                       f"  IP: {net_addr.ip_address}/{net_addr.prefix_length}"])

    all_identities = cp.registry.list_identities()  # type: ignore[attr-defined]
    trust_parts = []
    for other in all_identities:
        if other.city_id == city_id:
            continue
        level = cp.trust_engine.evaluate(city_id, other.city_id)  # type: ignore[attr-defined]
        trust_parts.append(f"  {city_id} → {other.city_id}: "
                           f"{level.name if hasattr(level, 'name') else level}")
    if trust_parts:
        parts.extend(["", "## Trust Relationships", *trust_parts])

    parts.append("")
    links: _Links = []
    if ident.repo:
        links.append((f"https://github.com/{ident.repo}", f"Browse Repo: {ident.repo}"))
    links.append(("about:cities", "All Cities"))
    links.append(("about:routes", "Routes"))
    links.append(("about:trust", "Trust"))
    links.append(("about:relay", "Relay"))
    return f"City: {city_id}", "\n".join(parts), links, []


def render_about_trust(cp: object, city_filter: str = "") -> tuple[str, str, _Links, list[dict]]:
    """Render about:trust with a Record Trust form."""
    identities = cp.registry.list_identities()  # type: ignore[attr-defined]
    city_ids = [i.city_id for i in identities]

    parts = ["# Trust Matrix", "", f"Cities: {len(city_ids)}", ""]
    links: _Links = []

    if city_filter:
        parts.append(f"## Trust for: {city_filter}")
        for target in city_ids:
            if target == city_filter:
                continue
            level = cp.trust_engine.evaluate(city_filter, target)  # type: ignore[attr-defined]
            parts.append(f"  → {target}: {level.name if hasattr(level, 'name') else level}")
            links.append((f"cp://cities/{target}", target))
        parts.append("")
        for source in city_ids:
            if source == city_filter:
                continue
            level = cp.trust_engine.evaluate(source, city_filter)  # type: ignore[attr-defined]
            parts.append(f"  {source} →: {level.name if hasattr(level, 'name') else level}")
    else:
        for source in city_ids:
            parts.append(f"## {source}")
            for target in city_ids:
                if target == source:
                    continue
                level = cp.trust_engine.evaluate(source, target)  # type: ignore[attr-defined]
                parts.append(f"  → {target}: {level.name if hasattr(level, 'name') else level}")
            parts.append("")
            links.append((f"cp://cities/{source}", source))

    links.append(("about:cities", "Cities"))
    links.append(("about:routes", "Routes"))

    forms = [{
        "action": "cp://trust/record", "method": "POST",
        "form_id": "record_trust",
        "fields": [
            _F("issuer_city_id"), _F("subject_city_id"),
            _F("level", value="verified"),
            _F("reason", required=False),
        ],
    }]
    return "Trust — Agent Web Browser", "\n".join(parts), links, forms


def render_about_routes(cp: object) -> tuple[str, str, _Links, list[dict]]:
    """Render about:routes with a Publish Route form."""
    routes = cp.registry.list_routes()  # type: ignore[attr-defined]

    parts = ["# Lotus Routes", "", f"Total: {len(routes)}", ""]
    links: _Links = []

    for r in routes:
        parts.append(f"## {r.route_id}")
        parts.append(f"  Owner: {r.owner_city_id}")
        parts.append(f"  Destination: {r.destination_prefix}")
        parts.append(f"  Target: {r.target_city_id}")
        parts.append(f"  Next Hop: {r.next_hop_city_id}")
        parts.append(f"  Metric: {r.metric}")
        if r.nadi_type:
            parts.append(f"  Nadi Type: {r.nadi_type}")
        if r.priority:
            parts.append(f"  Priority: {r.priority}")
        parts.append("")
        links.append((f"cp://cities/{r.owner_city_id}", f"Owner: {r.owner_city_id}"))
        links.append((f"cp://cities/{r.target_city_id}", f"Target: {r.target_city_id}"))

    if not routes:
        parts.append("(no routes configured)")

    links.append(("about:cities", "Cities"))
    links.append(("about:trust", "Trust"))
    links.append(("about:spaces", "Spaces"))

    forms = [{
        "action": "cp://routes/publish", "method": "POST",
        "form_id": "publish_route",
        "fields": [
            _F("owner_city_id"), _F("destination_prefix"),
            _F("target_city_id"), _F("next_hop_city_id"),
            _F("metric", value="100", required=False),
        ],
    }]
    return "Routes — Agent Web Browser", "\n".join(parts), links, forms


def render_about_spaces(cp: object) -> tuple[str, str, _Links, list[dict]]:
    """Render about:spaces with Claim Space and Request Slot Lease forms."""
    spaces = cp.registry.list_spaces()  # type: ignore[attr-defined]
    slots = cp.registry.list_slots()  # type: ignore[attr-defined]
    claims = cp.registry.list_space_claims()  # type: ignore[attr-defined]
    leases = cp.registry.list_slot_leases()  # type: ignore[attr-defined]

    parts = ["# Spaces & Slots", "",
             f"Spaces: {len(spaces)}  Slots: {len(slots)}  "
             f"Claims: {len(claims)}  Leases: {len(leases)}", ""]
    links: _Links = []

    for s in spaces:
        kind = s.kind.name if hasattr(s.kind, "name") else s.kind
        parts.append(f"## {s.space_id}")
        parts.append(f"  Kind: {kind}")
        parts.append(f"  Owner: {s.owner_subject_id}")
        if s.display_name:
            parts.append(f"  Name: {s.display_name}")
        if s.city_id:
            parts.append(f"  City: {s.city_id}")
            links.append((f"cp://cities/{s.city_id}", s.city_id))
        space_slots = [sl for sl in slots if sl.space_id == s.space_id]
        if space_slots:
            parts.append(f"  Slots ({len(space_slots)}):")
            for sl in space_slots:
                status = sl.status.name if hasattr(sl.status, "name") else sl.status
                parts.append(f"    - {sl.slot_id}: {status} "
                             f"(holder: {sl.holder_subject_id or 'none'})")
        parts.append("")

    if not spaces:
        parts.append("(no spaces registered)")

    if claims:
        parts.extend(["", "## Active Claims"])
        for c in claims:
            status = c.status.name if hasattr(c.status, "name") else c.status
            parts.append(f"  {c.claim_id}: {status} — {c.subject_id} on {c.space_id}")
    if leases:
        parts.extend(["", "## Active Leases"])
        for le in leases:
            status = le.status.name if hasattr(le.status, "name") else le.status
            parts.append(f"  {le.lease_id}: {status} — "
                         f"{le.holder_subject_id} on {le.slot_id}")

    links.append(("about:cities", "Cities"))
    links.append(("about:routes", "Routes"))
    links.append(("about:intents", "Intents"))

    forms = [
        {
            "action": "cp://spaces/claim", "method": "POST",
            "form_id": "claim_space",
            "fields": [
                _F("space_id"), _F("subject_id"),
                _F("intent_id", required=False),
            ],
        },
        {
            "action": "cp://spaces/lease", "method": "POST",
            "form_id": "request_slot_lease",
            "fields": [
                _F("slot_id"), _F("space_id"), _F("holder_subject_id"),
                _F("intent_id", required=False),
            ],
        },
    ]
    return "Spaces — Agent Web Browser", "\n".join(parts), links, forms


def render_about_intents(cp: object) -> tuple[str, str, _Links, list[dict]]:
    """Render about:intents with a Submit Intent form."""
    intents = cp.registry.list_intents() if hasattr(cp.registry, "list_intents") else []  # type: ignore[attr-defined]
    receipts = cp.registry.list_operation_receipts()  # type: ignore[attr-defined]

    parts = ["# Intents & Operations", "",
             f"Intents: {len(intents)}  Operation Receipts: {len(receipts)}", ""]
    links: _Links = []

    if intents:
        parts.append("## Intents")
        for intent in intents:
            itype = intent.intent_type.name if hasattr(intent.intent_type, "name") else intent.intent_type
            status = intent.status.name if hasattr(intent.status, "name") else intent.status
            parts.append(f"  {intent.intent_id}: [{status}] {itype}")
            if intent.title:
                parts.append(f"    {intent.title}")
            if intent.city_id:
                links.append((f"cp://cities/{intent.city_id}", intent.city_id))
        parts.append("")

    if receipts:
        parts.append("## Operation Receipts")
        for r in receipts:
            parts.append(f"  {r.operation_id}: {r.action} ({r.status})")
            parts.append(f"    Operator: {r.operator_subject}")
        parts.append("")

    if not intents and not receipts:
        parts.append("(no intents or operations recorded)")

    links.append(("about:cities", "Cities"))
    links.append(("about:spaces", "Spaces"))
    links.append(("about:routes", "Routes"))

    forms = [{
        "action": "cp://intents/submit", "method": "POST",
        "form_id": "submit_intent",
        "fields": [
            _F("intent_type", value="request_space_claim"),
            _F("title"), _F("requested_by_subject_id"),
            _F("city_id", required=False), _F("space_id", required=False),
        ],
    }]
    return "Intents — Agent Web Browser", "\n".join(parts), links, forms


def render_about_relay(cp: object) -> tuple[str, str, _Links, list[dict]]:
    """Render about:relay — send messages through the federation."""
    identities = cp.registry.list_identities()  # type: ignore[attr-defined]
    city_ids = [i.city_id for i in identities]
    routes = cp.registry.list_routes()  # type: ignore[attr-defined]
    schemes = cp.transports.schemes() if hasattr(cp, "transports") else ()  # type: ignore[attr-defined]

    parts = ["# Federation Relay", "",
             f"Registered cities: {len(city_ids)}",
             f"Routes: {len(routes)}",
             f"Transports: {', '.join(schemes) or 'none'}", ""]
    links: _Links = []

    if not schemes:
        parts.append("(no transports registered — register a transport to relay messages)")
    if not routes:
        parts.append("(no routes configured — publish routes first)")

    links.append(("about:cities", "Cities"))
    links.append(("about:routes", "Routes"))

    forms = [{
        "action": "cp://relay/send", "method": "POST",
        "form_id": "relay_message",
        "fields": [
            _F("source_city_id"), _F("target_city_id"),
            _F("operation", value="sync"),
            _F("payload", value="{}", required=False),
        ],
    }]
    return "Relay — Agent Web Browser", "\n".join(parts), links, forms


def get_registered_city_ids(cp: object) -> set[str]:
    """Return set of city_ids currently registered in the control plane."""
    return {i.city_id for i in cp.registry.list_identities()}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Form submission handler — routes POSTs to control plane writes
# ---------------------------------------------------------------------------

def _missing_fields(data: dict[str, str], required: list[str]) -> list[str]:
    """Return list of required fields that are empty or missing."""
    return [f for f in required if not data.get(f, "").strip()]


def handle_cp_submit(cp: object, url: str, data: dict[str, str]) -> tuple[str, str]:
    """Handle a POST to a cp:// action URL.

    Returns (redirect_url, error_message).  If error_message is non-empty the
    write was rejected; otherwise redirect_url points to the updated view.
    """
    from .models import (
        CityEndpoint,
        CityIdentity,
        ClaimStatus,
        IntentRecord,
        IntentStatus,
        IntentType,
        SlotLeaseRecord,
        SpaceClaimRecord,
        TrustLevel,
        TrustRecord,
    )

    path = url.removeprefix("cp://").strip("/")

    # -- Register City --
    if path == "cities/register":
        missing = _missing_fields(data, ["city_id", "location"])
        if missing:
            return "", f"Missing required fields: {', '.join(missing)}"
        city_id = data["city_id"].strip()
        cp.register_city(  # type: ignore[attr-defined]
            CityIdentity(
                city_id=city_id,
                slug=data.get("slug", "").strip() or city_id,
                repo=data.get("repo", "").strip(),
            ),
            CityEndpoint(
                city_id=city_id,
                transport=data.get("transport", "https").strip(),
                location=data["location"].strip(),
            ),
        )
        return f"about:cities?city={city_id}", ""

    # -- Record Trust --
    if path == "trust/record":
        missing = _missing_fields(data, ["issuer_city_id", "subject_city_id", "level"])
        if missing:
            return "", f"Missing required fields: {', '.join(missing)}"
        level_str = data["level"].strip().upper()
        try:
            level = TrustLevel(level_str.lower())
        except ValueError:
            return "", f"Invalid trust level: {level_str}. Use: unknown, observed, verified, trusted"
        cp.record_trust(TrustRecord(  # type: ignore[attr-defined]
            issuer_city_id=data["issuer_city_id"].strip(),
            subject_city_id=data["subject_city_id"].strip(),
            level=level,
            reason=data.get("reason", "").strip(),
        ))
        return f"about:trust?city={data['issuer_city_id'].strip()}", ""

    # -- Publish Route --
    if path == "routes/publish":
        missing = _missing_fields(data, ["owner_city_id", "destination_prefix",
                                         "target_city_id", "next_hop_city_id"])
        if missing:
            return "", f"Missing required fields: {', '.join(missing)}"
        metric = 100
        if data.get("metric", "").strip():
            try:
                metric = int(data["metric"])
            except ValueError:
                return "", f"Invalid metric: {data['metric']}. Must be integer."
        cp.publish_route(  # type: ignore[attr-defined]
            owner_city_id=data["owner_city_id"].strip(),
            destination_prefix=data["destination_prefix"].strip(),
            target_city_id=data["target_city_id"].strip(),
            next_hop_city_id=data["next_hop_city_id"].strip(),
            metric=metric,
        )
        return "about:routes", ""

    # -- Claim Space --
    if path == "spaces/claim":
        missing = _missing_fields(data, ["space_id", "subject_id"])
        if missing:
            return "", f"Missing required fields: {', '.join(missing)}"
        claim_id = f"claim-{token_hex(4)}"
        intent_id = data.get("intent_id", "").strip() or f"auto-{claim_id}"
        claim = SpaceClaimRecord(
            claim_id=claim_id,
            source_intent_id=intent_id,
            subject_id=data["subject_id"].strip(),
            space_id=data["space_id"].strip(),
            status=ClaimStatus.PENDING,
            requested_at=time.time(),
        )
        cp.upsert_space_claim(claim)  # type: ignore[attr-defined]
        cp.grant_space_claim(claim)  # type: ignore[attr-defined]
        return "about:spaces", ""

    # -- Request Slot Lease --
    if path == "spaces/lease":
        missing = _missing_fields(data, ["slot_id", "space_id", "holder_subject_id"])
        if missing:
            return "", f"Missing required fields: {', '.join(missing)}"
        lease_id = f"lease-{token_hex(4)}"
        intent_id = data.get("intent_id", "").strip() or f"auto-{lease_id}"
        lease = SlotLeaseRecord(
            lease_id=lease_id,
            source_intent_id=intent_id,
            holder_subject_id=data["holder_subject_id"].strip(),
            space_id=data["space_id"].strip(),
            slot_id=data["slot_id"].strip(),
            granted_at=time.time(),
        )
        cp.upsert_slot_lease(lease)  # type: ignore[attr-defined]
        return "about:spaces", ""

    # -- Submit Intent --
    if path == "intents/submit":
        missing = _missing_fields(data, ["intent_type", "title",
                                         "requested_by_subject_id"])
        if missing:
            return "", f"Missing required fields: {', '.join(missing)}"
        itype_str = data["intent_type"].strip().lower()
        try:
            itype = IntentType(itype_str)
        except ValueError:
            valid = ", ".join(t.value for t in IntentType)
            return "", f"Invalid intent_type: {itype_str}. Use: {valid}"
        intent_id = f"intent-{token_hex(4)}"
        cp.upsert_intent(IntentRecord(  # type: ignore[attr-defined]
            intent_id=intent_id,
            intent_type=itype,
            status=IntentStatus.PENDING,
            title=data["title"].strip(),
            requested_by_subject_id=data["requested_by_subject_id"].strip(),
            city_id=data.get("city_id", "").strip(),
            space_id=data.get("space_id", "").strip(),
        ))
        return "about:intents", ""

    # -- Onboard Federation Peer --
    if path == "federation/onboard":
        missing = _missing_fields(data, ["city_id", "repo", "location"])
        if missing:
            return "", f"Missing required fields: {', '.join(missing)}"
        city_id = data["city_id"].strip()
        caps_str = data.get("capabilities", "").strip()
        caps = tuple(c.strip() for c in caps_str.split(",") if c.strip()) if caps_str else ()
        cp.register_federation_peer(  # type: ignore[attr-defined]
            city_id=city_id,
            slug=data.get("slug", "").strip() or city_id,
            repo=data["repo"].strip(),
            transport="https",
            location=data["location"].strip(),
            capabilities=caps,
        )
        return f"about:cities?city={city_id}", ""

    # -- Relay Message --
    if path == "relay/send":
        from .transport import DeliveryEnvelope
        import json as _json
        missing = _missing_fields(data, ["source_city_id", "target_city_id", "operation"])
        if missing:
            return "", f"Missing required fields: {', '.join(missing)}"
        payload_str = data.get("payload", "{}").strip() or "{}"
        try:
            payload = _json.loads(payload_str)
        except _json.JSONDecodeError as exc:
            return "", f"Invalid JSON payload: {exc}"
        envelope = DeliveryEnvelope(
            source_city_id=data["source_city_id"].strip(),
            target_city_id=data["target_city_id"].strip(),
            operation=data["operation"].strip(),
            payload=payload if isinstance(payload, dict) else {"data": payload},
        )
        try:
            receipt = cp.relay_envelope(envelope)  # type: ignore[attr-defined]
        except Exception as exc:
            return "", f"Relay failed: {exc}"
        status = receipt.status.name if hasattr(receipt.status, "name") else receipt.status
        if status in ("DELIVERED", "delivered"):
            return "about:relay", ""
        return "", f"Relay status: {status} — {receipt.detail}"

    return "", f"Unknown submit action: {path}"


# ---------------------------------------------------------------------------
# ControlPlaneSource — PageSource for cp:// URLs
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ControlPlaneSource:
    """PageSource that intercepts ``cp://`` URLs and renders control plane data.

    Read URLs::

        cp://cities              → list all cities
        cp://cities/{city_id}    → city detail
        cp://trust               → trust matrix
        cp://trust?city=X        → trust for one city
        cp://routes              → route table
        cp://spaces              → spaces + slots
        cp://intents             → intent queue

    Write URLs (POST via form submission)::

        cp://cities/register     → register_city()
        cp://trust/record        → record_trust()
        cp://routes/publish      → publish_route()
        cp://spaces/claim        → grant_space_claim()
        cp://spaces/lease        → upsert_slot_lease()
        cp://intents/submit      → upsert_intent()
    """

    _control_plane: object = field(repr=False)

    def can_handle(self, url: str) -> bool:
        return url.startswith("cp://")

    def fetch(self, url: str, *, config: object = None) -> object:
        """Route cp:// read URLs to control plane renderers."""
        path = url.removeprefix("cp://").strip("/")

        if path.startswith("cities/") and path != "cities/register":
            city_id = path.removeprefix("cities/").strip("/")
            title, text, raw_links, raw_forms = render_about_city_detail(
                self._control_plane, city_id)
        elif path == "cities" or path == "":
            title, text, raw_links, raw_forms = render_about_cities(
                self._control_plane)
        elif path.startswith("trust"):
            city_filter = ""
            if "?" in path:
                for param in path.split("?", 1)[1].split("&"):
                    if param.startswith("city="):
                        city_filter = param.removeprefix("city=").strip()
            title, text, raw_links, raw_forms = render_about_trust(
                self._control_plane, city_filter)
        elif path == "routes":
            title, text, raw_links, raw_forms = render_about_routes(
                self._control_plane)
        elif path == "spaces":
            title, text, raw_links, raw_forms = render_about_spaces(
                self._control_plane)
        elif path == "intents":
            title, text, raw_links, raw_forms = render_about_intents(
                self._control_plane)
        elif path == "relay":
            title, text, raw_links, raw_forms = render_about_relay(
                self._control_plane)
        else:
            return _build_page(url, status=404,
                               error=f"unknown_cp_path:{path}")

        return _build_page(url, title=title, text=text,
                           raw_links=raw_links, raw_forms=raw_forms)

    def submit(self, url: str, data: dict[str, str]) -> tuple[str, str]:
        """Handle a POST to a cp:// write URL.

        Returns ``(redirect_url, error)``.  The browser is responsible for
        navigating to the redirect URL on success or rendering the error.
        """
        return handle_cp_submit(self._control_plane, url, data)


# ---------------------------------------------------------------------------
# Page builder helper
# ---------------------------------------------------------------------------

def _build_page(
    url: str, *, title: str = "", text: str = "", status: int = 200,
    error: str = "", raw_links: _Links | None = None,
    raw_forms: list[dict] | None = None,
) -> object:
    """Build a BrowserPage from render output."""
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
