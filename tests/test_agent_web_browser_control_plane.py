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


# ---------------------------------------------------------------------------
# Forms: pages should expose forms
# ---------------------------------------------------------------------------

def test_cities_page_has_register_form():
    browser = _make_browser()
    page = browser.open("about:cities")
    assert len(page.forms) == 1
    form = page.forms[0]
    assert form.form_id == "register_city"
    assert form.action == "cp://cities/register"
    assert form.method == "POST"
    field_names = [f.name for f in form.fields]
    assert "city_id" in field_names
    assert "location" in field_names


def test_trust_page_has_record_form():
    browser = _make_browser()
    page = browser.open("about:trust")
    assert len(page.forms) == 1
    assert page.forms[0].form_id == "record_trust"


def test_routes_page_has_publish_form():
    browser = _make_browser()
    page = browser.open("about:routes")
    assert len(page.forms) == 1
    assert page.forms[0].form_id == "publish_route"


def test_spaces_page_has_claim_and_lease_forms():
    browser = _make_browser()
    page = browser.open("about:spaces")
    assert len(page.forms) == 2
    form_ids = {f.form_id for f in page.forms}
    assert "claim_space" in form_ids
    assert "request_slot_lease" in form_ids


def test_intents_page_has_submit_form():
    browser = _make_browser()
    page = browser.open("about:intents")
    assert len(page.forms) == 1
    assert page.forms[0].form_id == "submit_intent"


# ---------------------------------------------------------------------------
# Form submission roundtrips — submit → verify in control plane → verify in page
# ---------------------------------------------------------------------------

def test_submit_register_city():
    """Register a new city via form and verify it appears."""
    browser = _make_browser()
    browser.open("about:cities")

    result = browser.submit_form("register_city", values={
        "city_id": "new-city",
        "slug": "new-city",
        "repo": "kimeisele/new-city",
        "transport": "https",
        "location": "https://github.com/kimeisele/new-city",
    })
    assert result.ok
    # Should redirect to city detail
    assert "new-city" in result.content_text
    assert "kimeisele/new-city" in result.content_text

    # Verify in cities list (bypass cache to see the update)
    cities = browser.open("about:cities", use_cache=False)
    assert "Total: 6" in cities.content_text
    assert "new-city" in cities.content_text


def test_submit_register_city_missing_fields():
    """Missing required fields should return error, not crash."""
    browser = _make_browser()
    browser.open("about:cities")

    result = browser.submit_form("register_city", values={
        "city_id": "x",
        # location is missing
    })
    assert not result.ok
    assert "Missing required fields" in result.error


def test_submit_record_trust():
    """Record trust between two cities via form."""
    browser = _make_browser()
    browser.open("about:trust")

    result = browser.submit_form("record_trust", values={
        "issuer_city_id": "agent-city",
        "subject_city_id": "agent-world",
        "level": "trusted",
        "reason": "test trust",
    })
    assert result.ok
    # Should show updated trust
    assert "TRUSTED" in result.content_text


def test_submit_record_trust_invalid_level():
    browser = _make_browser()
    browser.open("about:trust")

    result = browser.submit_form("record_trust", values={
        "issuer_city_id": "agent-city",
        "subject_city_id": "agent-world",
        "level": "invalid_level",
    })
    assert not result.ok
    assert "Invalid trust level" in result.error


def test_submit_publish_route():
    """Publish a route via form and verify it appears."""
    browser = _make_browser()
    browser.open("about:routes")

    result = browser.submit_form("publish_route", values={
        "owner_city_id": "agent-world",
        "destination_prefix": "service:steward/",
        "target_city_id": "steward",
        "next_hop_city_id": "steward",
        "metric": "50",
    })
    assert result.ok
    assert "Total: 3" in result.content_text
    assert "steward" in result.content_text


def test_submit_claim_space():
    """Claim a space via form and verify it appears."""
    browser = _make_browser()
    browser.open("about:spaces")

    result = browser.submit_form("claim_space", values={
        "space_id": "space:federation-commons",
        "subject_id": "agent-world",
    })
    assert result.ok
    assert "agent-world" in result.content_text
    assert "Claims: 1" in result.content_text or "Active Claims" in result.content_text


def test_submit_slot_lease():
    """Request a slot lease via form."""
    browser = _make_browser()
    browser.open("about:spaces")

    result = browser.submit_form("request_slot_lease", values={
        "slot_id": "slot:steward-protocol-bridge",
        "space_id": "space:federation-commons",
        "holder_subject_id": "agent-city",
    })
    assert result.ok
    assert "Active Leases" in result.content_text
    assert "agent-city" in result.content_text


def test_submit_intent():
    """Submit an intent via form and verify it appears."""
    browser = _make_browser()
    browser.open("about:intents")

    result = browser.submit_form("submit_intent", values={
        "intent_type": "request_space_claim",
        "title": "Give me a space",
        "requested_by_subject_id": "agent-42",
        "city_id": "agent-internet",
    })
    assert result.ok
    # Should now have 2 intents (1 from setup + 1 new)
    assert "Intents: 2" in result.content_text
    assert "Give me a space" in result.content_text


def test_submit_intent_invalid_type():
    browser = _make_browser()
    browser.open("about:intents")

    result = browser.submit_form("submit_intent", values={
        "intent_type": "does_not_exist",
        "title": "Bad intent",
        "requested_by_subject_id": "agent-42",
    })
    assert not result.ok
    assert "Invalid intent_type" in result.error


# ---------------------------------------------------------------------------
# Submit without control plane
# ---------------------------------------------------------------------------

def test_submit_without_control_plane():
    """Submitting a cp:// form without control plane gives clear error."""
    from agent_internet.agent_web_browser import FormField, PageForm

    browser = AgentWebBrowser()
    # Manually set a page with a cp:// form so we can submit it
    from agent_internet.agent_web_browser import BrowserPage, PageMeta
    import time
    fake_page = BrowserPage(
        url="about:cities", status_code=200, title="Test",
        content_text="test", links=(), meta=PageMeta(), headers={},
        fetched_at=time.time(), content_type="text/html", encoding="utf-8",
        raw_html="", error="",
        forms=(PageForm(
            action="cp://cities/register", method="POST", form_id="test",
            fields=(FormField(name="city_id"), FormField(name="location")),
        ),),
    )
    tab = browser.active_tab
    tab.current_page = fake_page
    tab.push_url("about:cities")

    result = browser.submit_form("test", values={
        "city_id": "x", "location": "y",
    })
    assert not result.ok
    assert result.status_code == 503


# ---------------------------------------------------------------------------
# Brief #5: Federation ↔ System Bridge
# ---------------------------------------------------------------------------

# -- about:federation sync status --

def test_federation_shows_sync_status(monkeypatch):
    """about:federation should show 'Registered' / 'Not registered' per peer."""
    browser = _make_browser()

    # Patch discover_federation_descriptors to return known peers
    fake_descriptors = [
        {"display_name": "Agent Internet", "repo_id": "agent-internet",
         "layer": "core", "status": "active", "capabilities": ["nadi-relay"]},
        {"display_name": "Unknown Repo", "repo_id": "kimeisele/unknown-repo",
         "layer": "extension", "status": "active", "capabilities": []},
    ]
    import agent_internet.agent_web_browser_env as _env_mod
    monkeypatch.setattr(_env_mod, "discover_federation_descriptors",
                        lambda config=None: fake_descriptors)

    page = browser.open("about:federation")
    assert page.ok
    # agent-internet is registered in _make_control_plane
    assert "Registered" in page.content_text
    # unknown-repo is NOT registered
    assert "Not registered" in page.content_text


def test_federation_shows_onboard_forms(monkeypatch):
    """about:federation should show onboard forms for unregistered peers."""
    browser = _make_browser()

    fake_descriptors = [
        {"display_name": "Agent Internet", "repo_id": "agent-internet",
         "layer": "core", "status": "active", "capabilities": ["nadi-relay"]},
        {"display_name": "New Peer", "repo_id": "kimeisele/new-peer",
         "layer": "extension", "status": "active",
         "capabilities": ["search", "relay"]},
    ]
    import agent_internet.agent_web_browser_env as _env_mod
    monkeypatch.setattr(_env_mod, "discover_federation_descriptors",
                        lambda config=None: fake_descriptors)

    page = browser.open("about:federation")
    assert page.ok
    # No onboard form for already-registered agent-internet
    assert not any(f.form_id == "onboard_agent-internet" for f in page.forms)
    # Onboard form for new-peer
    onboard_forms = [f for f in page.forms if "onboard" in f.form_id]
    assert len(onboard_forms) == 1
    form = onboard_forms[0]
    assert form.action == "cp://federation/onboard"
    # Pre-filled values
    field_vals = {f.name: f.value for f in form.fields}
    assert field_vals["city_id"] == "kimeisele/new-peer"
    assert field_vals["repo"] == "kimeisele/new-peer"
    assert "search" in field_vals["capabilities"]


def test_federation_no_forms_without_control_plane(monkeypatch):
    """Without control plane, federation should show no onboard forms."""
    browser = AgentWebBrowser()  # no control plane

    fake_descriptors = [
        {"display_name": "Some Peer", "repo_id": "kimeisele/some-peer",
         "layer": "core", "status": "active", "capabilities": []},
    ]
    import agent_internet.agent_web_browser_env as _env_mod
    monkeypatch.setattr(_env_mod, "discover_federation_descriptors",
                        lambda config=None: fake_descriptors)

    page = browser.open("about:federation")
    assert page.ok
    assert len(page.forms) == 0


# -- Onboard form submission --

def test_submit_onboard_federation_peer(monkeypatch):
    """Submitting onboard form registers the peer via register_federation_peer."""
    browser = _make_browser()

    fake_descriptors = [
        {"display_name": "New Peer", "repo_id": "kimeisele/new-peer",
         "layer": "extension", "status": "active",
         "capabilities": ["relay", "search"]},
    ]
    import agent_internet.agent_web_browser_env as _env_mod
    monkeypatch.setattr(_env_mod, "discover_federation_descriptors",
                        lambda config=None: fake_descriptors)

    page = browser.open("about:federation")
    assert len(page.forms) == 1

    result = browser.submit_form(page.forms[0].form_id, values={
        "city_id": "kimeisele/new-peer",
        "slug": "new-peer",
        "repo": "kimeisele/new-peer",
        "location": "https://github.com/kimeisele/new-peer",
        "capabilities": "relay, search",
    })
    assert result.ok
    # Should redirect to city detail
    assert "kimeisele/new-peer" in result.content_text

    # Verify it's now in the cities list
    cities = browser.open("about:cities", use_cache=False)
    assert "Total: 6" in cities.content_text
    assert "kimeisele/new-peer" in cities.content_text


def test_submit_onboard_missing_fields():
    """Onboard submission missing required fields should return error."""
    browser = _make_browser()
    # Manually set up a page with the onboard form
    from agent_internet.agent_web_browser import BrowserPage, FormField, PageForm, PageMeta
    import time as _time
    fake_page = BrowserPage(
        url="about:federation", status_code=200, title="Test",
        content_text="test", links=(), meta=PageMeta(), headers={},
        fetched_at=_time.time(), content_type="text/html", encoding="utf-8",
        raw_html="", error="",
        forms=(PageForm(
            action="cp://federation/onboard", method="POST",
            form_id="onboard_test",
            fields=(
                FormField(name="city_id", value="x"),
                FormField(name="repo"),
                FormField(name="location"),
            ),
        ),),
    )
    tab = browser.active_tab
    tab.current_page = fake_page
    tab.push_url("about:federation")

    result = browser.submit_form("onboard_test", values={
        "city_id": "x",
        # missing repo and location
    })
    assert not result.ok
    assert "Missing required fields" in result.error


# -- about:cities Browse Repo links --

def test_cities_has_browse_repo_links():
    """about:cities should include Browse Repo links for peers with repos."""
    browser = _make_browser()
    page = browser.open("about:cities")
    browse_links = [l for l in page.links if l.href.startswith("https://github.com/")]
    # All 5 peers have repos
    assert len(browse_links) == 5
    assert any("kimeisele/agent-internet" in l.href for l in browse_links)


def test_city_detail_has_browse_repo_link():
    """cp://cities/{id} detail should include a Browse Repo link."""
    browser = _make_browser()
    page = browser.open("cp://cities/agent-internet")
    browse_links = [l for l in page.links if l.href.startswith("https://github.com/")]
    assert len(browse_links) >= 1
    assert any("kimeisele/agent-internet" in l.href for l in browse_links)


# -- about:relay --

def test_about_relay_renders():
    """about:relay should render with relay form."""
    browser = _make_browser()
    page = browser.open("about:relay")
    assert page.ok
    assert "Relay" in page.title
    assert "Registered cities: 5" in page.content_text
    assert "Routes: 2" in page.content_text
    assert len(page.forms) == 1
    assert page.forms[0].form_id == "relay_message"
    assert page.forms[0].action == "cp://relay/send"
    field_names = [f.name for f in page.forms[0].fields]
    assert "source_city_id" in field_names
    assert "target_city_id" in field_names
    assert "operation" in field_names
    assert "payload" in field_names


def test_about_relay_links():
    """about:relay should link to cities and routes."""
    browser = _make_browser()
    page = browser.open("about:relay")
    assert any(l.href == "about:cities" for l in page.links)
    assert any(l.href == "about:routes" for l in page.links)


def test_cp_relay():
    """cp://relay should render the relay page."""
    browser = _make_browser()
    page = browser.open("cp://relay")
    assert page.ok
    assert "Federation Relay" in page.content_text


# -- Relay message submission with LoopbackTransport --

def test_submit_relay_message_with_loopback():
    """Relay a message through LoopbackTransport and verify delivery."""
    from agent_internet.transport import LoopbackTransport

    browser = AgentWebBrowser()
    cp = _make_control_plane()
    # Register a loopback transport for the 'https' scheme
    loopback = LoopbackTransport()
    cp.transports.register("https", loopback)
    browser.attach_control_plane(cp)

    # Open relay page first (needed for form context)
    browser.open("about:relay")

    result = browser.submit_form("relay_message", values={
        "source_city_id": "agent-internet",
        "target_city_id": "steward-protocol",
        "operation": "sync",
        "payload": '{"action": "ping"}',
    })
    assert result.ok
    # Should redirect back to relay page
    assert "Relay" in result.title

    # Verify the message was delivered via loopback
    messages = loopback.receive("steward-protocol")
    assert len(messages) == 1
    assert messages[0].operation == "sync"
    assert messages[0].payload == {"action": "ping"}


def test_submit_relay_invalid_json():
    """Relay with invalid JSON payload should return error."""
    browser = _make_browser()
    browser.open("about:relay")

    result = browser.submit_form("relay_message", values={
        "source_city_id": "agent-internet",
        "target_city_id": "steward-protocol",
        "operation": "sync",
        "payload": "not valid json{",
    })
    assert not result.ok
    assert "Invalid JSON" in result.error


def test_submit_relay_missing_fields():
    """Relay with missing required fields should return error."""
    browser = _make_browser()
    browser.open("about:relay")

    result = browser.submit_form("relay_message", values={
        "source_city_id": "agent-internet",
        # missing target_city_id and operation
    })
    assert not result.ok
    assert "Missing required fields" in result.error


# -- Cross-navigation: Web ↔ System bridge --

def test_navigate_federation_onboard_to_cities(monkeypatch):
    """Full loop: federation → onboard → cities detail → browse repo."""
    browser = _make_browser()

    fake_descriptors = [
        {"display_name": "New Peer", "repo_id": "kimeisele/new-peer",
         "layer": "extension", "status": "active", "capabilities": ["search"]},
    ]
    import agent_internet.agent_web_browser_env as _env_mod
    monkeypatch.setattr(_env_mod, "discover_federation_descriptors",
                        lambda config=None: fake_descriptors)

    # 1. Start at federation
    fed_page = browser.open("about:federation")
    assert "Not registered" in fed_page.content_text

    # 2. Submit onboard form
    result = browser.submit_form(fed_page.forms[0].form_id, values={
        "city_id": "kimeisele/new-peer",
        "slug": "new-peer",
        "repo": "kimeisele/new-peer",
        "location": "https://github.com/kimeisele/new-peer",
        "capabilities": "search",
    })
    assert result.ok
    # Should be on city detail page
    assert "kimeisele/new-peer" in result.content_text

    # 3. Navigate to all cities
    cities_link = next((l for l in result.links if l.href == "about:cities"), None)
    assert cities_link is not None
    cities_page = browser.open(cities_link.href, use_cache=False)
    assert "Total: 6" in cities_page.content_text

    # 4. Find Browse Repo link for new peer
    browse_links = [l for l in cities_page.links
                    if "kimeisele/new-peer" in l.href
                    and l.href.startswith("https://")]
    assert len(browse_links) >= 1


def test_navigate_cities_to_relay():
    """about:cities should link to relay, and relay should be navigable."""
    browser = _make_browser()
    cities = browser.open("about:cities")
    relay_link = next((l for l in cities.links if l.href == "about:relay"), None)
    assert relay_link is not None
    relay_page = browser.open(relay_link.href)
    assert relay_page.ok
    assert "Federation Relay" in relay_page.content_text
