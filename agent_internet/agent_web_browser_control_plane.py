"""Browser ↔ Control Plane integration.

Provides:
- ``ControlPlaneSource`` — a ``PageSource`` that intercepts ``cp://`` URLs
  and renders data from ``AgentInternetControlPlane``.
- ``render_about_*`` helpers that power the ``about:cities``, ``about:trust``,
  ``about:routes``, ``about:spaces``, and ``about:intents`` pages.

The browser SHOWS, the control plane KNOWS.  This module is the lens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("AGENT_INTERNET.WEB_BROWSER.CONTROL_PLANE")


# ---------------------------------------------------------------------------
# about: page renderers — each ≤ 50 lines of rendering code
# ---------------------------------------------------------------------------

def render_about_cities(cp: object) -> tuple[str, str, list[tuple[str, str]]]:
    """Render about:cities content.  Returns (title, text, [(href, label)])."""
    identities = cp.registry.list_identities()  # type: ignore[attr-defined]
    endpoints = {e.city_id: e for e in cp.registry.list_endpoints()}  # type: ignore[attr-defined]
    presences = {p.city_id: p for p in cp.registry.list_cities()}  # type: ignore[attr-defined]

    parts = ["# Registered Cities", "", f"Total: {len(identities)}", ""]
    links: list[tuple[str, str]] = []

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

    links.append(("about:routes", "Routes"))
    links.append(("about:spaces", "Spaces"))
    links.append(("about:intents", "Intents"))
    links.append(("about:environment", "Environment"))
    return "Cities — Agent Web Browser", "\n".join(parts), links


def render_about_city_detail(cp: object, city_id: str) -> tuple[str, str, list[tuple[str, str]]]:
    """Render detail for a single city."""
    ident = cp.registry.get_identity(city_id)  # type: ignore[attr-defined]
    if not ident:
        return f"City Not Found: {city_id}", f"# City Not Found\n\nNo city with ID: {city_id}", []

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
        parts.extend(["", "## Endpoint", f"  Transport: {ep.transport}", f"  Location: {ep.location}"])

    if pr:
        parts.extend(["", "## Presence",
                       f"  Health: {pr.health.name if hasattr(pr.health, 'name') else pr.health}"])
        if pr.capabilities:
            parts.append(f"  Capabilities: {', '.join(pr.capabilities)}")

    if link_addr:
        parts.extend(["", "## Lotus Link Address",
                       f"  MAC: {link_addr.mac_address}", f"  Interface: {link_addr.interface}"])
    if net_addr:
        parts.extend(["", "## Lotus Network Address",
                       f"  IP: {net_addr.ip_address}/{net_addr.prefix_length}"])

    # Trust this city has with others
    all_identities = cp.registry.list_identities()  # type: ignore[attr-defined]
    trust_parts = []
    for other in all_identities:
        if other.city_id == city_id:
            continue
        level = cp.trust_engine.evaluate(city_id, other.city_id)  # type: ignore[attr-defined]
        trust_parts.append(f"  {city_id} → {other.city_id}: {level.name if hasattr(level, 'name') else level}")
    if trust_parts:
        parts.extend(["", "## Trust Relationships", *trust_parts])

    parts.append("")
    links: list[tuple[str, str]] = []
    if ident.repo:
        links.append((f"https://github.com/{ident.repo}", f"GitHub: {ident.repo}"))
    links.append(("about:cities", "All Cities"))
    links.append(("about:routes", "Routes"))
    links.append(("about:trust", "Trust"))
    return f"City: {city_id}", "\n".join(parts), links


def render_about_trust(cp: object, city_filter: str = "") -> tuple[str, str, list[tuple[str, str]]]:
    """Render about:trust — trust matrix between known cities."""
    identities = cp.registry.list_identities()  # type: ignore[attr-defined]
    city_ids = [i.city_id for i in identities]

    parts = ["# Trust Matrix", "", f"Cities: {len(city_ids)}", ""]
    links: list[tuple[str, str]] = []

    if city_filter:
        # Show trust for one specific city
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
        # Full matrix
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
    return "Trust — Agent Web Browser", "\n".join(parts), links


def render_about_routes(cp: object) -> tuple[str, str, list[tuple[str, str]]]:
    """Render about:routes — all Lotus routes."""
    routes = cp.registry.list_routes()  # type: ignore[attr-defined]

    parts = ["# Lotus Routes", "", f"Total: {len(routes)}", ""]
    links: list[tuple[str, str]] = []

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
    return "Routes — Agent Web Browser", "\n".join(parts), links


def render_about_spaces(cp: object) -> tuple[str, str, list[tuple[str, str]]]:
    """Render about:spaces — spaces, slots, claims, leases."""
    spaces = cp.registry.list_spaces()  # type: ignore[attr-defined]
    slots = cp.registry.list_slots()  # type: ignore[attr-defined]
    claims = cp.registry.list_space_claims()  # type: ignore[attr-defined]
    leases = cp.registry.list_slot_leases()  # type: ignore[attr-defined]

    parts = ["# Spaces & Slots", "",
             f"Spaces: {len(spaces)}  Slots: {len(slots)}  "
             f"Claims: {len(claims)}  Leases: {len(leases)}", ""]
    links: list[tuple[str, str]] = []

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

        # Slots in this space
        space_slots = [sl for sl in slots if sl.space_id == s.space_id]
        if space_slots:
            parts.append(f"  Slots ({len(space_slots)}):")
            for sl in space_slots:
                status = sl.status.name if hasattr(sl.status, "name") else sl.status
                parts.append(f"    - {sl.slot_id}: {status} (holder: {sl.holder_subject_id or 'none'})")
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
            parts.append(f"  {le.lease_id}: {status} — {le.holder_subject_id} on {le.slot_id}")

    links.append(("about:cities", "Cities"))
    links.append(("about:routes", "Routes"))
    links.append(("about:intents", "Intents"))
    return "Spaces — Agent Web Browser", "\n".join(parts), links


def render_about_intents(cp: object) -> tuple[str, str, list[tuple[str, str]]]:
    """Render about:intents — intent queue and operation receipts."""
    intents = cp.registry.list_intents() if hasattr(cp.registry, "list_intents") else []  # type: ignore[attr-defined]
    receipts = cp.registry.list_operation_receipts()  # type: ignore[attr-defined]

    parts = ["# Intents & Operations", "",
             f"Intents: {len(intents)}  Operation Receipts: {len(receipts)}", ""]
    links: list[tuple[str, str]] = []

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
    return "Intents — Agent Web Browser", "\n".join(parts), links


# ---------------------------------------------------------------------------
# ControlPlaneSource — PageSource for cp:// URLs
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ControlPlaneSource:
    """PageSource that intercepts ``cp://`` URLs and renders control plane data.

    URL scheme::

        cp://cities              → list all cities
        cp://cities/{city_id}    → city detail
        cp://trust               → trust matrix
        cp://trust?city=X        → trust for one city
        cp://routes              → route table
        cp://spaces              → spaces + slots
        cp://intents             → intent queue
    """

    _control_plane: object = field(repr=False)

    def can_handle(self, url: str) -> bool:
        return url.startswith("cp://")

    def fetch(self, url: str, *, config: object = None) -> object:
        """Route cp:// URLs to control plane renderers."""
        from .agent_web_browser import BrowserPage, PageLink, PageMeta

        path = url.removeprefix("cp://").strip("/")

        # Route
        if path.startswith("cities/"):
            city_id = path.removeprefix("cities/").strip("/")
            title, text, raw_links = render_about_city_detail(self._control_plane, city_id)
        elif path == "cities" or path == "":
            title, text, raw_links = render_about_cities(self._control_plane)
        elif path.startswith("trust"):
            city_filter = ""
            if "?" in path:
                for param in path.split("?", 1)[1].split("&"):
                    if param.startswith("city="):
                        city_filter = param.removeprefix("city=").strip()
            title, text, raw_links = render_about_trust(self._control_plane, city_filter)
        elif path == "routes":
            title, text, raw_links = render_about_routes(self._control_plane)
        elif path == "spaces":
            title, text, raw_links = render_about_spaces(self._control_plane)
        elif path == "intents":
            title, text, raw_links = render_about_intents(self._control_plane)
        else:
            return BrowserPage(
                url=url, status_code=404, title="Not Found",
                content_text=f"Unknown control plane path: {path}",
                links=(), forms=(), meta=PageMeta(), headers={},
                fetched_at=0.0, content_type="text/plain", encoding="utf-8",
                raw_html="", error=f"unknown_cp_path:{path}",
            )

        links = tuple(
            PageLink(href=href, text=label, index=i)
            for i, (href, label) in enumerate(raw_links)
        )
        import time
        return BrowserPage(
            url=url, status_code=200, title=title,
            content_text=text, links=links, forms=(), meta=PageMeta(),
            headers={}, fetched_at=time.time(), content_type="text/plain",
            encoding="utf-8", raw_html=text, error="",
        )
