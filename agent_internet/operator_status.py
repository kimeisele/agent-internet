"""Operator status dashboard — machine-readable and human-readable views.

Provides structured snapshots of the control plane state for operators,
including health summaries, trust topology, routing tables, and intent queues.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .models import (
    HealthStatus,
    IntentStatus,
    SlotStatus,
    TrustLevel,
)


@dataclass(frozen=True, slots=True)
class CityStatusEntry:
    """Status summary for a single city."""

    city_id: str
    slug: str = ""
    health: str = "unknown"
    trust_inbound: int = 0
    trust_outbound: int = 0
    endpoints: int = 0
    services: int = 0
    routes: int = 0
    last_seen_at: float | None = None
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TrustEdge:
    """A trust relationship between two cities."""

    issuer: str
    subject: str
    level: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class RouteEntry:
    """A route in the routing table."""

    route_id: str
    owner: str
    prefix: str
    target: str
    next_hop: str
    metric: int = 100
    nadi_type: str = ""


@dataclass(frozen=True, slots=True)
class IntentQueueEntry:
    """An intent in the pending/accepted queue."""

    intent_id: str
    intent_type: str
    status: str
    title: str = ""
    city_id: str = ""
    requested_by: str = ""
    created_at: float | None = None


@dataclass(frozen=True, slots=True)
class OperatorDashboard:
    """Complete operator-facing status dashboard."""

    generated_at: float = field(default_factory=time.time)
    total_cities: int = 0
    healthy_cities: int = 0
    degraded_cities: int = 0
    offline_cities: int = 0
    total_routes: int = 0
    total_services: int = 0
    total_endpoints: int = 0
    total_trust_records: int = 0
    pending_intents: int = 0
    active_spaces: int = 0
    active_slots: int = 0
    cities: tuple[CityStatusEntry, ...] = ()
    trust_edges: tuple[TrustEdge, ...] = ()
    routes: tuple[RouteEntry, ...] = ()
    intent_queue: tuple[IntentQueueEntry, ...] = ()
    transport_schemes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def build_operator_dashboard(plane: object) -> OperatorDashboard:
    """Build a complete dashboard from a control plane instance.

    Accepts ``object`` to avoid circular imports; expects an
    ``AgentInternetControlPlane`` instance.
    """
    registry = getattr(plane, "registry", None)
    trust_engine = getattr(plane, "trust_engine", None)
    transports = getattr(plane, "transports", None)

    if registry is None:
        return OperatorDashboard(warnings=("No registry available",))

    # Cities
    identities = registry.list_identities()
    presences = {p.city_id: p for p in registry.list_cities()}
    city_entries: list[CityStatusEntry] = []
    healthy = degraded = offline = 0

    for identity in identities:
        presence = presences.get(identity.city_id)
        health = presence.health if presence else HealthStatus.UNKNOWN
        if health == HealthStatus.HEALTHY:
            healthy += 1
        elif health == HealthStatus.DEGRADED:
            degraded += 1
        elif health == HealthStatus.OFFLINE:
            offline += 1

        city_entries.append(CityStatusEntry(
            city_id=identity.city_id,
            slug=identity.slug,
            health=health.value if isinstance(health, HealthStatus) else str(health),
            last_seen_at=presence.last_seen_at if presence else None,
            capabilities=presence.capabilities if presence else (),
        ))

    # Trust topology
    trust_edges: list[TrustEdge] = []
    trust_records = trust_engine.list_records() if trust_engine else []
    for record in trust_records:
        trust_edges.append(TrustEdge(
            issuer=record.issuer_city_id,
            subject=record.subject_city_id,
            level=record.level.value if isinstance(record.level, TrustLevel) else str(record.level),
        ))

    # Routes
    route_entries: list[RouteEntry] = []
    for route in registry.list_routes():
        route_entries.append(RouteEntry(
            route_id=route.route_id,
            owner=route.owner_city_id,
            prefix=route.destination_prefix,
            target=route.target_city_id,
            next_hop=route.next_hop_city_id,
            metric=route.metric,
            nadi_type=route.nadi_type,
        ))

    # Intents
    intent_entries: list[IntentQueueEntry] = []
    pending_count = 0
    for intent in registry.list_intents():
        if intent.status in (IntentStatus.PENDING, IntentStatus.ACCEPTED):
            pending_count += 1
        intent_entries.append(IntentQueueEntry(
            intent_id=intent.intent_id,
            intent_type=intent.intent_type.value,
            status=intent.status.value,
            title=intent.title,
            city_id=intent.city_id,
            requested_by=intent.requested_by_subject_id,
            created_at=intent.created_at,
        ))

    # Services & endpoints
    services = registry.list_service_addresses()
    hosted_endpoints = registry.list_hosted_endpoints()
    spaces = registry.list_spaces()
    slots = registry.list_slots()

    # Warnings
    warnings: list[str] = []
    if len(identities) == 0:
        warnings.append("No cities registered")
    if len(trust_records) == 0 and len(identities) > 1:
        warnings.append("No trust records between cities")
    if len(route_entries) == 0 and len(identities) > 1:
        warnings.append("No routes defined between cities")
    for city in city_entries:
        if city.health == "offline":
            warnings.append(f"City {city.city_id} ({city.slug}) is offline")

    schemes = transports.schemes() if transports else ()

    return OperatorDashboard(
        total_cities=len(identities),
        healthy_cities=healthy,
        degraded_cities=degraded,
        offline_cities=offline,
        total_routes=len(route_entries),
        total_services=len(services),
        total_endpoints=len(hosted_endpoints),
        total_trust_records=len(trust_records),
        pending_intents=pending_count,
        active_spaces=len(spaces),
        active_slots=sum(1 for slot in slots if slot.status == SlotStatus.ACTIVE),
        cities=tuple(city_entries),
        trust_edges=tuple(trust_edges),
        routes=tuple(route_entries),
        intent_queue=tuple(intent_entries),
        transport_schemes=schemes,
        warnings=tuple(warnings),
    )


def format_dashboard_text(dashboard: OperatorDashboard) -> str:
    """Render a dashboard as human-readable text."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("  AGENT INTERNET CONTROL PLANE STATUS")
    lines.append("=" * 60)
    lines.append("")

    # Overview
    lines.append(f"Cities:   {dashboard.total_cities} total "
                 f"({dashboard.healthy_cities} healthy, "
                 f"{dashboard.degraded_cities} degraded, "
                 f"{dashboard.offline_cities} offline)")
    lines.append(f"Routes:   {dashboard.total_routes}")
    lines.append(f"Services: {dashboard.total_services}")
    lines.append(f"Endpoints: {dashboard.total_endpoints}")
    lines.append(f"Trust:    {dashboard.total_trust_records} records")
    lines.append(f"Intents:  {dashboard.pending_intents} pending")
    lines.append(f"Spaces:   {dashboard.active_spaces}")
    lines.append(f"Slots:    {dashboard.active_slots}")
    lines.append(f"Transport: {', '.join(dashboard.transport_schemes) or 'none'}")
    lines.append("")

    # Cities
    if dashboard.cities:
        lines.append("-" * 40)
        lines.append("CITIES")
        lines.append("-" * 40)
        for city in dashboard.cities:
            health_icon = {"healthy": "+", "degraded": "~", "offline": "!", "unknown": "?"}.get(city.health, "?")
            lines.append(f"  [{health_icon}] {city.city_id} ({city.slug})")
            if city.capabilities:
                lines.append(f"      caps: {', '.join(city.capabilities)}")
        lines.append("")

    # Trust
    if dashboard.trust_edges:
        lines.append("-" * 40)
        lines.append("TRUST TOPOLOGY")
        lines.append("-" * 40)
        for edge in dashboard.trust_edges:
            lines.append(f"  {edge.issuer} -> {edge.subject} [{edge.level}]")
        lines.append("")

    # Routes
    if dashboard.routes:
        lines.append("-" * 40)
        lines.append("ROUTING TABLE")
        lines.append("-" * 40)
        for route in dashboard.routes:
            lines.append(f"  {route.prefix} -> {route.target} via {route.next_hop} (metric={route.metric})")
        lines.append("")

    # Intents
    active_intents = [i for i in dashboard.intent_queue if i.status in ("pending", "accepted")]
    if active_intents:
        lines.append("-" * 40)
        lines.append("INTENT QUEUE")
        lines.append("-" * 40)
        for intent in active_intents:
            lines.append(f"  [{intent.status}] {intent.intent_type}: {intent.title or intent.intent_id}")
        lines.append("")

    # Warnings
    if dashboard.warnings:
        lines.append("-" * 40)
        lines.append("WARNINGS")
        lines.append("-" * 40)
        for warning in dashboard.warnings:
            lines.append(f"  ! {warning}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)
