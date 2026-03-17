"""Tests for browser ↔ control plane integration.

Uses REAL AgentInternetControlPlane with 5 federation peers,
trust records, routes, spaces, and intents.  No mocks.
"""

from __future__ import annotations

from agent_internet.agent_web_browser import AgentWebBrowser
from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.models import (
    CityEndpoint,
    CityIdentity,
    CityPresence,
    HealthStatus,
    IntentRecord,
    IntentStatus,
    IntentType,
    SlotDescriptor,
    SlotStatus,
    SpaceDescriptor,
    SpaceKind,
    TrustLevel,
    TrustRecord,
)


# ---------------------------------------------------------------------------
# Fixture: real control plane with 5 federation peers
# ---------------------------------------------------------------------------

_PEERS = [
    ("agent-internet", "agent-internet", "kimeisele/agent-internet",
     ("nadi-relay", "federation-discovery", "semantic-search")),
    ("steward-protocol", "steward-protocol", "kimeisele/steward-protocol",
     ("code_analysis", "protocol_substrate")),
    ("agent-city", "agent-city", "kimeisele/agent-city",
     ("runtime", "governance", "economy")),
    ("agent-world", "agent-world", "kimeisele/agent-world",
     ("world-authority", "graph-projection")),
    ("steward", "steward", "kimeisele/steward",
     ("autonomous_daemon", "ci_automation")),
]


def _make_control_plane() -> AgentInternetControlPlane:
    """Build a real control plane with 5 peers, trust, routes, spaces."""
    cp = AgentInternetControlPlane()

    # Register 5 federation peers
    for city_id, slug, repo, caps in _PEERS:
        cp.register_city(
            CityIdentity(city_id=city_id, slug=slug, repo=repo),
            CityEndpoint(city_id=city_id, transport="https",
                         location=f"https://github.com/{repo}"),
        )
        cp.announce_city(CityPresence(
            city_id=city_id, health=HealthStatus.HEALTHY,
            capabilities=caps,
        ))

    # Trust: agent-internet trusts everyone at VERIFIED,
    # steward-protocol trusts agent-internet at TRUSTED
    for _, slug, _, _ in _PEERS:
        if slug != "agent-internet":
            cp.record_trust(TrustRecord(
                issuer_city_id="agent-internet", subject_city_id=slug,
                level=TrustLevel.VERIFIED, reason="federation peer",
            ))
    cp.record_trust(TrustRecord(
        issuer_city_id="steward-protocol", subject_city_id="agent-internet",
        level=TrustLevel.TRUSTED, reason="substrate provider",
    ))

    # Routes: agent-internet → steward-protocol via direct hop
    cp.publish_route(
        owner_city_id="agent-internet",
        destination_prefix="service:steward-protocol/",
        target_city_id="steward-protocol",
        next_hop_city_id="steward-protocol",
        metric=10,
    )
    cp.publish_route(
        owner_city_id="agent-internet",
        destination_prefix="service:agent-city/",
        target_city_id="agent-city",
        next_hop_city_id="agent-city",
        metric=20,
    )

    # Space + Slot
    cp.upsert_space(SpaceDescriptor(
        space_id="space:federation-commons",
        kind=SpaceKind.PUBLIC_SURFACE,
        owner_subject_id="agent-internet",
        display_name="Federation Commons",
        city_id="agent-internet",
    ))
    cp.upsert_slot(SlotDescriptor(
        slot_id="slot:steward-protocol-bridge",
        space_id="space:federation-commons",
        slot_kind="bridge",
        holder_subject_id="steward-protocol",
        status=SlotStatus.ACTIVE,
    ))

    # Intent
    cp.upsert_intent(IntentRecord(
        intent_id="intent-001",
        intent_type=IntentType.REQUEST_SPACE_CLAIM,
        status=IntentStatus.PENDING,
        title="Request commons access for agent-world",
        requested_by_subject_id="agent-world",
        city_id="agent-internet",
        space_id="space:federation-commons",
    ))

    return cp


def _make_browser() -> AgentWebBrowser:
    """Create browser with attached control plane."""
    browser = AgentWebBrowser()
    cp = _make_control_plane()
    browser.attach_control_plane(cp)
    return browser


# ---------------------------------------------------------------------------
# about:cities
# ---------------------------------------------------------------------------

def test_about_cities_lists_all_peers():
    browser = _make_browser()
    page = browser.open("about:cities")
    assert page.ok
    assert "Cities" in page.title
    assert "Total: 5" in page.content_text
    for city_id, _, _, _ in _PEERS:
        assert city_id in page.content_text


def test_about_cities_has_links_to_detail():
    browser = _make_browser()
    page = browser.open("about:cities")
    cp_links = [l for l in page.links if l.href.startswith("cp://cities/")]
    assert len(cp_links) >= 5


def test_about_cities_links_to_trust():
    browser = _make_browser()
    page = browser.open("about:cities")
    assert any("about:trust" in l.href for l in page.links)


# ---------------------------------------------------------------------------
# about:cities?city=X (detail via about:)
# ---------------------------------------------------------------------------

def test_about_city_detail():
    browser = _make_browser()
    page = browser.open("about:cities?city=agent-internet")
    assert page.ok
    assert "agent-internet" in page.content_text
    assert "kimeisele/agent-internet" in page.content_text
    # Should show trust relationships
    assert "Trust Relationships" in page.content_text


def test_about_city_detail_not_found():
    browser = _make_browser()
    page = browser.open("about:cities?city=nonexistent")
    assert page.ok  # 200 but shows "not found" message
    assert "Not Found" in page.content_text


# ---------------------------------------------------------------------------
# cp://cities/{id} (detail via ControlPlaneSource)
# ---------------------------------------------------------------------------

def test_cp_city_detail():
    browser = _make_browser()
    page = browser.open("cp://cities/steward-protocol")
    assert page.ok
    assert "steward-protocol" in page.content_text
    assert "Lotus" in page.content_text  # Should show Lotus addresses


def test_cp_city_not_found():
    browser = _make_browser()
    page = browser.open("cp://cities/nonexistent")
    assert page.ok  # renders "not found" content
    assert "Not Found" in page.content_text


def test_cp_cities_list():
    browser = _make_browser()
    page = browser.open("cp://cities")
    assert page.ok
    assert "Total: 5" in page.content_text


# ---------------------------------------------------------------------------
# about:trust
# ---------------------------------------------------------------------------

def test_about_trust_matrix():
    browser = _make_browser()
    page = browser.open("about:trust")
    assert page.ok
    assert "Trust" in page.title
    assert "Cities: 5" in page.content_text
    # agent-internet → steward-protocol should be VERIFIED
    assert "VERIFIED" in page.content_text


def test_about_trust_for_city():
    browser = _make_browser()
    page = browser.open("about:trust?city=agent-internet")
    assert page.ok
    # Should show outgoing trust
    assert "VERIFIED" in page.content_text
    # steward-protocol → agent-internet is TRUSTED
    assert "TRUSTED" in page.content_text


# ---------------------------------------------------------------------------
# about:routes
# ---------------------------------------------------------------------------

def test_about_routes():
    browser = _make_browser()
    page = browser.open("about:routes")
    assert page.ok
    assert "Routes" in page.title
    assert "Total: 2" in page.content_text
    assert "steward-protocol" in page.content_text
    assert "agent-city" in page.content_text


def test_about_routes_links_to_cities():
    browser = _make_browser()
    page = browser.open("about:routes")
    cp_links = [l for l in page.links if l.href.startswith("cp://cities/")]
    assert len(cp_links) >= 2


# ---------------------------------------------------------------------------
# about:spaces
# ---------------------------------------------------------------------------

def test_about_spaces():
    browser = _make_browser()
    page = browser.open("about:spaces")
    assert page.ok
    assert "Spaces" in page.title
    assert "Federation Commons" in page.content_text
    assert "slot:steward-protocol-bridge" in page.content_text
    assert "ACTIVE" in page.content_text


# ---------------------------------------------------------------------------
# about:intents
# ---------------------------------------------------------------------------

def test_about_intents():
    browser = _make_browser()
    page = browser.open("about:intents")
    assert page.ok
    assert "Intents" in page.title
    assert "intent-001" in page.content_text
    assert "PENDING" in page.content_text
    assert "REQUEST_SPACE_CLAIM" in page.content_text


# ---------------------------------------------------------------------------
# cp:// URL routing
# ---------------------------------------------------------------------------

def test_cp_trust():
    browser = _make_browser()
    page = browser.open("cp://trust")
    assert page.ok
    assert "Trust Matrix" in page.content_text


def test_cp_routes():
    browser = _make_browser()
    page = browser.open("cp://routes")
    assert page.ok
    assert "Lotus Routes" in page.content_text


def test_cp_spaces():
    browser = _make_browser()
    page = browser.open("cp://spaces")
    assert page.ok
    assert "Spaces & Slots" in page.content_text


def test_cp_intents():
    browser = _make_browser()
    page = browser.open("cp://intents")
    assert page.ok
    assert "Intents" in page.content_text


def test_cp_unknown_path():
    browser = _make_browser()
    page = browser.open("cp://nonexistent")
    assert not page.ok
    assert page.status_code == 404


# ---------------------------------------------------------------------------
# No control plane attached
# ---------------------------------------------------------------------------

def test_about_cities_without_control_plane():
    browser = AgentWebBrowser()
    page = browser.open("about:cities")
    assert not page.ok
    assert page.status_code == 503
    assert "no_control_plane" in page.error


# ---------------------------------------------------------------------------
# Environment shows control plane when attached
# ---------------------------------------------------------------------------

def test_environment_shows_control_plane():
    browser = _make_browser()
    page = browser.open("about:environment")
    assert page.ok
    assert "Control Plane" in page.content_text
    assert any(l.href == "about:cities" for l in page.links)
    assert any(l.href == "about:trust" for l in page.links)
    assert any(l.href == "about:routes" for l in page.links)


def test_environment_no_control_plane():
    browser = AgentWebBrowser()
    page = browser.open("about:environment")
    assert page.ok
    # Should NOT show control plane section
    assert "Control Plane" not in page.content_text
    assert not any(l.href == "about:cities" for l in page.links)


# ---------------------------------------------------------------------------
# Cross-navigation: about: → cp:// → about:
# ---------------------------------------------------------------------------

def test_navigate_cities_to_detail_to_trust():
    """Full navigation loop through control plane pages."""
    browser = _make_browser()

    # Start at cities
    page = browser.open("about:cities")
    assert page.ok

    # Follow cp:// link to a city detail
    cp_link = next(l for l in page.links if l.href.startswith("cp://cities/agent-internet"))
    detail = browser.open(cp_link.href)
    assert detail.ok
    assert "agent-internet" in detail.content_text

    # Navigate to trust
    trust_link = next((l for l in detail.links if l.href == "about:trust"), None)
    if trust_link:
        trust = browser.open(trust_link.href)
        assert trust.ok
        assert "VERIFIED" in trust.content_text


def test_navigate_routes_to_city():
    """From routes, follow link to city detail."""
    browser = _make_browser()

    routes = browser.open("about:routes")
    assert routes.ok

    # Follow a city link
    cp_link = next(l for l in routes.links if l.href.startswith("cp://cities/"))
    detail = browser.open(cp_link.href)
    assert detail.ok
