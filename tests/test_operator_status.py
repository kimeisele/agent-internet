from __future__ import annotations

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
    TrustLevel,
    TrustRecord,
)
from agent_internet.operator_status import build_operator_dashboard, format_dashboard_text


def test_empty_dashboard():
    plane = AgentInternetControlPlane()
    dashboard = build_operator_dashboard(plane)
    assert dashboard.total_cities == 0
    assert "No cities registered" in dashboard.warnings


def test_dashboard_with_cities():
    plane = AgentInternetControlPlane()
    plane.register_city(
        CityIdentity(city_id="alpha", slug="alpha-city", repo="test/alpha"),
        CityEndpoint(city_id="alpha", transport="filesystem", location="/data/alpha"),
    )
    plane.announce_city(CityPresence(city_id="alpha", health=HealthStatus.HEALTHY))
    plane.register_city(
        CityIdentity(city_id="beta", slug="beta-city", repo="test/beta"),
        CityEndpoint(city_id="beta", transport="filesystem", location="/data/beta"),
    )
    plane.announce_city(CityPresence(city_id="beta", health=HealthStatus.DEGRADED))

    dashboard = build_operator_dashboard(plane)
    assert dashboard.total_cities == 2
    assert dashboard.healthy_cities == 1
    assert dashboard.degraded_cities == 1
    assert len(dashboard.cities) == 2


def test_dashboard_trust():
    plane = AgentInternetControlPlane()
    plane.register_city(
        CityIdentity(city_id="alpha", slug="a", repo=""),
        CityEndpoint(city_id="alpha", transport="fs", location=""),
    )
    plane.register_city(
        CityIdentity(city_id="beta", slug="b", repo=""),
        CityEndpoint(city_id="beta", transport="fs", location=""),
    )
    plane.record_trust(TrustRecord(
        issuer_city_id="alpha",
        subject_city_id="beta",
        level=TrustLevel.VERIFIED,
    ))

    dashboard = build_operator_dashboard(plane)
    assert dashboard.total_trust_records == 1
    assert len(dashboard.trust_edges) == 1


def test_dashboard_intents():
    plane = AgentInternetControlPlane()
    plane.upsert_intent(IntentRecord(
        intent_id="i-1",
        intent_type=IntentType.REQUEST_ISSUE,
        status=IntentStatus.PENDING,
        title="Test issue",
    ))
    dashboard = build_operator_dashboard(plane)
    assert dashboard.pending_intents == 1
    assert len(dashboard.intent_queue) == 1


def test_format_dashboard_text():
    plane = AgentInternetControlPlane()
    plane.register_city(
        CityIdentity(city_id="alpha", slug="alpha-city", repo="test/alpha"),
        CityEndpoint(city_id="alpha", transport="filesystem", location="/data/alpha"),
    )
    plane.announce_city(CityPresence(city_id="alpha", health=HealthStatus.HEALTHY))

    dashboard = build_operator_dashboard(plane)
    text = format_dashboard_text(dashboard)
    assert "AGENT INTERNET CONTROL PLANE STATUS" in text
    assert "alpha" in text
    assert "1 total" in text


def test_dashboard_counts_only_active_slots():
    plane = AgentInternetControlPlane()
    plane.upsert_slot(SlotDescriptor(slot_id="slot-1", space_id="space-1", slot_kind="assistant", holder_subject_id="assistant-a", status=SlotStatus.ACTIVE))
    plane.upsert_slot(SlotDescriptor(slot_id="slot-2", space_id="space-1", slot_kind="assistant", holder_subject_id="assistant-b", status=SlotStatus.DORMANT))

    dashboard = build_operator_dashboard(plane)

    assert dashboard.active_slots == 1
