"""Tests for NadiSource — agent-to-agent messaging via nadi:// URLs.

Uses REAL AgentInternetControlPlane with LoopbackTransport.
Tests cover: factory, nadi:// pages, inbox/outbox, send form, cross-navigation.
"""

from __future__ import annotations

from agent_internet.agent_web_browser import AgentWebBrowser, BrowserConfig
from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.models import (
    CityEndpoint,
    CityIdentity,
    CityPresence,
    HealthStatus,
    TrustLevel,
    TrustRecord,
)
from agent_internet.transport import LoopbackTransport


# ---------------------------------------------------------------------------
# Fixture: control plane with loopback transport
# ---------------------------------------------------------------------------

def _make_cp_with_loopback() -> tuple[AgentInternetControlPlane, LoopbackTransport]:
    """Build a real CP with 2 cities, a route, and a LoopbackTransport."""
    cp = AgentInternetControlPlane()
    loopback = LoopbackTransport()
    cp.transports.register("https", loopback)

    for city_id, slug, repo in [
        ("alpha", "alpha", "org/alpha"),
        ("beta", "beta", "org/beta"),
    ]:
        cp.register_city(
            CityIdentity(city_id=city_id, slug=slug, repo=repo),
            CityEndpoint(city_id=city_id, transport="https",
                         location=f"https://example.com/{city_id}"),
        )
        cp.announce_city(CityPresence(
            city_id=city_id, health=HealthStatus.HEALTHY, capabilities=(),
        ))

    # Trust so routing works
    cp.record_trust(TrustRecord(
        issuer_city_id="alpha", subject_city_id="beta",
        level=TrustLevel.VERIFIED, reason="test",
    ))
    cp.record_trust(TrustRecord(
        issuer_city_id="beta", subject_city_id="alpha",
        level=TrustLevel.VERIFIED, reason="test",
    ))

    # Route: alpha → beta
    cp.publish_route(
        owner_city_id="alpha",
        destination_prefix="service:beta/",
        target_city_id="beta",
        next_hop_city_id="beta",
        metric=10,
    )

    return cp, loopback


def _make_nadi_browser() -> tuple[AgentWebBrowser, LoopbackTransport]:
    """Create browser with all sources including NadiSource."""
    cp, loopback = _make_cp_with_loopback()
    browser = AgentWebBrowser.from_control_plane(cp)
    return browser, loopback


# ---------------------------------------------------------------------------
# Factory: from_control_plane
# ---------------------------------------------------------------------------

def test_from_control_plane_creates_browser():
    """Factory should produce a fully configured browser."""
    cp, _ = _make_cp_with_loopback()
    browser = AgentWebBrowser.from_control_plane(cp)
    # Should have control plane attached
    assert browser._control_plane is cp
    # cp:// URLs should work
    page = browser.open("cp://cities")
    assert page.ok
    assert "Total: 2" in page.content_text


def test_from_control_plane_has_nadi_source():
    """Factory should register NadiSource."""
    cp, _ = _make_cp_with_loopback()
    browser = AgentWebBrowser.from_control_plane(cp)
    page = browser.open("nadi://")
    assert page.ok
    assert "Nadi Messaging" in page.content_text


def test_from_control_plane_has_github_source():
    """Factory should register GitHubBrowserSource."""
    cp, _ = _make_cp_with_loopback()
    browser = AgentWebBrowser.from_control_plane(cp)
    from agent_internet.agent_web_browser_github import GitHubBrowserSource
    assert any(isinstance(s, GitHubBrowserSource) for s in browser._sources)


def test_from_control_plane_disable_github():
    """Factory with github=False should not register GitHubBrowserSource."""
    cp, _ = _make_cp_with_loopback()
    browser = AgentWebBrowser.from_control_plane(cp, github=False)
    from agent_internet.agent_web_browser_github import GitHubBrowserSource
    assert not any(isinstance(s, GitHubBrowserSource) for s in browser._sources)


def test_from_control_plane_disable_nadi():
    """Factory with nadi=False should not register NadiSource."""
    cp, _ = _make_cp_with_loopback()
    browser = AgentWebBrowser.from_control_plane(cp, nadi=False)
    page = browser.open("nadi://")
    assert not page.ok  # 404 because no source handles it


def test_from_control_plane_custom_config():
    """Factory should accept custom config."""
    cp, _ = _make_cp_with_loopback()
    config = BrowserConfig(max_page_cache=5)
    browser = AgentWebBrowser.from_control_plane(cp, config=config)
    assert browser.config.max_page_cache == 5


# ---------------------------------------------------------------------------
# create_agent_browser top-level export
# ---------------------------------------------------------------------------

def test_create_agent_browser_import():
    """create_agent_browser should be importable from agent_internet."""
    from agent_internet import create_agent_browser
    cp, _ = _make_cp_with_loopback()
    browser = create_agent_browser(control_plane=cp)
    page = browser.open("about:environment")
    assert page.ok


# ---------------------------------------------------------------------------
# nadi:// overview
# ---------------------------------------------------------------------------

def test_nadi_overview():
    """nadi:// root should list cities and transports."""
    browser, _ = _make_nadi_browser()
    page = browser.open("nadi://")
    assert page.ok
    assert "Nadi Messaging" in page.title
    assert "Registered cities: 2" in page.content_text
    assert "https" in page.content_text  # transport
    # Links to each city
    assert any(l.href == "nadi://alpha" for l in page.links)
    assert any(l.href == "nadi://beta" for l in page.links)


# ---------------------------------------------------------------------------
# nadi://{city}/inbox
# ---------------------------------------------------------------------------

def test_nadi_inbox_empty():
    """Inbox should show zero messages initially."""
    browser, _ = _make_nadi_browser()
    page = browser.open("nadi://alpha/inbox")
    assert page.ok
    assert "Inbox: alpha" in page.title
    assert "Messages: 0" in page.content_text
    assert "no messages" in page.content_text


def test_nadi_inbox_with_messages():
    """Inbox should show messages after delivery."""
    browser, loopback = _make_nadi_browser()

    # Send a message to beta via browser form
    browser.open("nadi://alpha/send")
    browser.submit_form("nadi_send", values={
        "target_city_id": "beta",
        "operation": "ping",
        "payload": '{"msg": "hello"}',
    })

    # Check beta's inbox
    inbox = browser.open("nadi://beta/inbox")
    assert inbox.ok
    assert "Messages: 1" in inbox.content_text
    assert "alpha" in inbox.content_text  # source
    assert "ping" in inbox.content_text  # operation


# ---------------------------------------------------------------------------
# nadi://{city}/outbox
# ---------------------------------------------------------------------------

def test_nadi_outbox_empty():
    """Outbox should show no receipts initially."""
    browser, _ = _make_nadi_browser()
    page = browser.open("nadi://alpha/outbox")
    assert page.ok
    assert "Outbox: alpha" in page.title
    assert "Delivery receipts: 0" in page.content_text


def test_nadi_outbox_after_send():
    """Outbox should show delivery receipt after sending."""
    browser, _ = _make_nadi_browser()

    browser.open("nadi://alpha/send")
    result = browser.submit_form("nadi_send", values={
        "target_city_id": "beta",
        "operation": "sync",
        "payload": "{}",
    })
    assert result.ok
    # Should redirect to outbox
    assert "Outbox" in result.title
    assert "Delivery receipts: 1" in result.content_text
    assert "DELIVERED" in result.content_text


# ---------------------------------------------------------------------------
# nadi://{city}/send
# ---------------------------------------------------------------------------

def test_nadi_send_page():
    """Send page should show a form with target, operation, payload fields."""
    browser, _ = _make_nadi_browser()
    page = browser.open("nadi://alpha/send")
    assert page.ok
    assert "Send" in page.title
    assert len(page.forms) == 1
    form = page.forms[0]
    assert form.form_id == "nadi_send"
    assert form.action == "nadi://alpha/send"
    field_names = [f.name for f in form.fields]
    assert "target_city_id" in field_names
    assert "operation" in field_names
    assert "payload" in field_names


def test_nadi_send_lists_targets():
    """Send page should list available target cities."""
    browser, _ = _make_nadi_browser()
    page = browser.open("nadi://alpha/send")
    assert "beta" in page.content_text


# ---------------------------------------------------------------------------
# nadi://{city} hub
# ---------------------------------------------------------------------------

def test_nadi_city_hub():
    """nadi://{city} should show hub with inbox/outbox/send links."""
    browser, _ = _make_nadi_browser()
    page = browser.open("nadi://alpha")
    assert page.ok
    assert "Nadi: alpha" in page.title
    assert any(l.href == "nadi://alpha/inbox" for l in page.links)
    assert any(l.href == "nadi://alpha/outbox" for l in page.links)
    assert any(l.href == "nadi://alpha/send" for l in page.links)


# ---------------------------------------------------------------------------
# Form submission: send message
# ---------------------------------------------------------------------------

def test_nadi_send_delivers_message():
    """Submitting send form should deliver message via LoopbackTransport."""
    browser, loopback = _make_nadi_browser()
    browser.open("nadi://alpha/send")

    result = browser.submit_form("nadi_send", values={
        "target_city_id": "beta",
        "operation": "federation_sync",
        "payload": '{"action": "update", "version": 42}',
    })
    assert result.ok

    # Verify delivery in loopback
    messages = loopback.receive("beta")
    assert len(messages) == 1
    assert messages[0].source_city_id == "alpha"
    assert messages[0].target_city_id == "beta"
    assert messages[0].operation == "federation_sync"
    assert messages[0].payload == {"action": "update", "version": 42}


def test_nadi_send_missing_target():
    """Missing target should return error."""
    browser, _ = _make_nadi_browser()
    browser.open("nadi://alpha/send")

    result = browser.submit_form("nadi_send", values={
        "operation": "sync",
    })
    assert not result.ok
    assert "target_city_id" in result.error


def test_nadi_send_missing_operation():
    """Missing operation should return error."""
    browser, _ = _make_nadi_browser()
    browser.open("nadi://alpha/send")

    result = browser.submit_form("nadi_send", values={
        "target_city_id": "beta",
        "operation": "",
    })
    assert not result.ok
    assert "operation" in result.error


def test_nadi_send_invalid_json():
    """Invalid JSON payload should return error."""
    browser, _ = _make_nadi_browser()
    browser.open("nadi://alpha/send")

    result = browser.submit_form("nadi_send", values={
        "target_city_id": "beta",
        "operation": "sync",
        "payload": "{bad json",
    })
    assert not result.ok
    assert "Invalid JSON" in result.error


# ---------------------------------------------------------------------------
# Cross-navigation: nadi:// ↔ cp:// ↔ about:
# ---------------------------------------------------------------------------

def test_nadi_overview_links_to_relay():
    """nadi:// overview should link to about:relay."""
    browser, _ = _make_nadi_browser()
    page = browser.open("nadi://")
    assert any(l.href == "about:relay" for l in page.links)


def test_nadi_overview_links_to_cities():
    """nadi:// overview should link to about:cities."""
    browser, _ = _make_nadi_browser()
    page = browser.open("nadi://")
    assert any(l.href == "about:cities" for l in page.links)


def test_nadi_city_hub_links_to_cp_city():
    """nadi://{city} hub should link to cp://cities/{city}."""
    browser, _ = _make_nadi_browser()
    page = browser.open("nadi://alpha")
    assert any(l.href == "cp://cities/alpha" for l in page.links)


def test_full_navigation_loop():
    """Navigate: nadi:// → send → outbox → hub → cp://cities → about:cities."""
    browser, _ = _make_nadi_browser()

    # 1. Start at nadi overview
    overview = browser.open("nadi://")
    assert overview.ok

    # 2. Go to alpha send
    send = browser.open("nadi://alpha/send")
    assert send.ok

    # 3. Send a message
    result = browser.submit_form("nadi_send", values={
        "target_city_id": "beta",
        "operation": "hello",
        "payload": "{}",
    })
    assert result.ok
    assert "Outbox" in result.title

    # 4. Navigate to hub
    hub_link = next(l for l in result.links if l.href == "nadi://alpha")
    hub = browser.open(hub_link.href)
    assert "Nadi: alpha" in hub.title

    # 5. Follow cp://cities link
    cp_link = next(l for l in hub.links if l.href.startswith("cp://cities/"))
    city = browser.open(cp_link.href)
    assert city.ok
    assert "alpha" in city.content_text

    # 6. Navigate to all cities
    all_link = next(l for l in city.links if l.href == "about:cities")
    cities = browser.open(all_link.href)
    assert cities.ok
    assert "Total: 2" in cities.content_text


# ---------------------------------------------------------------------------
# nadi:// unknown path
# ---------------------------------------------------------------------------

def test_nadi_unknown_path():
    """Unknown nadi:// sub-path should return 404."""
    browser, _ = _make_nadi_browser()
    page = browser.open("nadi://alpha/unknown")
    assert not page.ok
    assert page.status_code == 404


# ---------------------------------------------------------------------------
# No NadiSource registered
# ---------------------------------------------------------------------------

def test_nadi_submit_without_source():
    """Submitting nadi:// form without NadiSource gives clear error."""
    from agent_internet.agent_web_browser import BrowserPage, FormField, PageForm, PageMeta
    import time

    browser = AgentWebBrowser()
    fake_page = BrowserPage(
        url="nadi://alpha/send", status_code=200, title="Test",
        content_text="test", links=(), meta=PageMeta(), headers={},
        fetched_at=time.time(), content_type="text/html", encoding="utf-8",
        raw_html="", error="",
        forms=(PageForm(
            action="nadi://alpha/send", method="POST", form_id="nadi_send",
            fields=(
                FormField(name="target_city_id"),
                FormField(name="operation"),
            ),
        ),),
    )
    tab = browser.active_tab
    tab.current_page = fake_page
    tab.push_url("nadi://alpha/send")

    result = browser.submit_form("nadi_send", values={
        "target_city_id": "beta", "operation": "sync",
    })
    assert not result.ok
    assert result.status_code == 503
