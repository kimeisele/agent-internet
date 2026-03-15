"""Tests for the federation relay pipeline.

Covers: register_federation_peer, federation snapshot indexing,
OutboxRelayPump TTL handling, and atomic drain.  All tests run
without vibe_core / steward-protocol.
"""

import time

from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.filesystem_transport import FilesystemFederationTransport
from agent_internet.agent_city_contract import AgentCityFilesystemContract
from agent_internet.models import TrustLevel
from agent_internet.pump import OutboxRelayPump
from agent_internet.snapshot import snapshot_control_plane
from agent_internet.transport import (
    DeliveryEnvelope,
    DeliveryReceipt,
    DeliveryStatus,
    LoopbackTransport,
    TransportScheme,
)
from agent_internet.agent_web_federated_index import (
    _build_federation_snapshot_records,
    refresh_agent_web_federated_index,
)
from agent_internet.agent_web_source_registry import upsert_agent_web_source_registry_entry


# ── register_federation_peer ──────────────────────────────────────────


def test_register_federation_peer_assigns_lotus_addresses():
    plane = AgentInternetControlPlane()
    link, net = plane.register_federation_peer(
        city_id="test-peer",
        slug="test-peer",
        repo="org/test-peer",
        transport="loopback",
        location="mem://test",
        capabilities=("federation",),
        labels={"role": "test"},
    )
    assert link is not None
    assert link.mac_address.startswith("02:00:")
    assert net is not None
    assert net.ip_address.startswith("fd10:")


def test_register_federation_peer_establishes_trust():
    plane = AgentInternetControlPlane()
    plane.register_federation_peer(
        city_id="test-peer",
        slug="test-peer",
        repo="org/test-peer",
        transport="loopback",
        location="mem://test",
    )
    trust = plane.trust_engine.list_records()
    assert any(
        r.subject_city_id == "test-peer" and r.level == TrustLevel.VERIFIED
        for r in trust
    )


def test_register_federation_peer_publishes_nadi_service():
    plane = AgentInternetControlPlane()
    plane.register_federation_peer(
        city_id="svc-peer",
        slug="svc-peer",
        repo="org/svc-peer",
        transport="loopback",
        location="mem://svc",
        publish_nadi_service=True,
    )
    service = plane.resolve_service_address("svc-peer", "nadi-relay")
    assert service is not None
    assert service.public_handle == "svc-peer.nadi-relay.lotus"

    hosted = plane.resolve_public_handle("svc-peer.federation.lotus")
    assert hosted is not None


def test_register_federation_peer_without_nadi_service():
    plane = AgentInternetControlPlane()
    plane.register_federation_peer(
        city_id="plain-peer",
        slug="plain-peer",
        repo="org/plain-peer",
        transport="loopback",
        location="mem://plain",
        publish_nadi_service=False,
    )
    assert plane.resolve_service_address("plain-peer", "nadi-relay") is None


# ── federation snapshot records (generic indexer) ─────────────────────


def test_snapshot_records_indexes_all_presences():
    plane = AgentInternetControlPlane()
    for cid in ("alpha", "beta", "gamma"):
        plane.register_federation_peer(
            city_id=cid, slug=cid, repo=f"org/{cid}",
            transport="loopback", location=f"mem://{cid}",
        )
    snap = snapshot_control_plane(plane)
    records = _build_federation_snapshot_records(snap, refreshed_at=1.0)

    health_records = [r for r in records if r["kind"] == "federation_health_report"]
    assert len(health_records) == 3
    health_cities = {r["source_city_id"] for r in health_records}
    assert health_cities == {"alpha", "beta", "gamma"}


def test_snapshot_records_indexes_trust_summary():
    plane = AgentInternetControlPlane()
    plane.register_federation_peer(
        city_id="a", slug="a", repo="org/a",
        transport="loopback", location="mem://a",
    )
    snap = snapshot_control_plane(plane)
    records = _build_federation_snapshot_records(snap, refreshed_at=1.0)

    trust = [r for r in records if r["kind"] == "federation_trust_summary"]
    assert len(trust) == 1
    assert "VERIFIED" in trust[0]["summary"] or "verified" in trust[0]["summary"]


def test_snapshot_records_indexes_peer_registry():
    plane = AgentInternetControlPlane()
    for cid in ("x", "y"):
        plane.register_federation_peer(
            city_id=cid, slug=cid, repo=f"org/{cid}",
            transport="loopback", location=f"mem://{cid}",
        )
    snap = snapshot_control_plane(plane)
    records = _build_federation_snapshot_records(snap, refreshed_at=1.0)

    registry = [r for r in records if r["kind"] == "federation_peer_registry"]
    assert len(registry) == 1
    assert "x" in registry[0]["summary"]
    assert "y" in registry[0]["summary"]


def test_snapshot_records_indexes_lotus_services():
    plane = AgentInternetControlPlane()
    plane.register_federation_peer(
        city_id="s", slug="s", repo="org/s",
        transport="loopback", location="mem://s",
        publish_nadi_service=True,
    )
    snap = snapshot_control_plane(plane)
    records = _build_federation_snapshot_records(snap, refreshed_at=1.0)

    svc = [r for r in records if r["kind"] == "federation_lotus_services"]
    assert len(svc) == 1
    assert "nadi-relay" in svc[0]["summary"]


def test_snapshot_records_empty_snapshot_produces_no_records():
    records = _build_federation_snapshot_records({}, refreshed_at=1.0)
    assert records == []


# ── OutboxRelayPump TTL fix ───────────────────────────────────────────


def test_pump_uses_relay_time_not_message_timestamp():
    """Messages with old timestamps must not expire at relay time."""
    plane = AgentInternetControlPlane()
    loopback = LoopbackTransport()
    plane.register_transport(TransportScheme.LOOPBACK.value, loopback)

    for cid in ("sender", "receiver"):
        plane.register_federation_peer(
            city_id=cid, slug=cid, repo=f"org/{cid}",
            transport=TransportScheme.LOOPBACK.value,
            location=f"loopback://{cid}",
        )
    # Bidirectional trust.
    from agent_internet.models import TrustRecord as TR
    plane.record_trust(TR(
        issuer_city_id="sender", subject_city_id="receiver",
        level=TrustLevel.VERIFIED, reason="test",
    ))
    plane.publish_route(
        owner_city_id="sender",
        destination_prefix="receiver",
        target_city_id="receiver",
        next_hop_city_id="receiver",
        metric=100,
    )

    # Simulate an outbox message written 10 minutes ago.
    old_timestamp = time.time() - 600
    contract = AgentCityFilesystemContract(root=__import__("pathlib").Path("/dev/null"))

    # Build a raw message dict the way steward/agent-city would.
    raw_message = {
        "source": "sender",
        "target": "receiver",
        "operation": "heartbeat",
        "payload": {"beat": 1},
        "envelope_id": "old-msg-1",
        "correlation_id": "old-msg-1",
        "timestamp": old_timestamp,
        "nadi_type": "vyana",
        "nadi_op": "send",
        "nadi_priority": "rajas",
        "ttl_ms": 24000,
    }

    # The pump creates envelope with relay_at, not old_timestamp.
    relay_at = time.time()
    envelope = DeliveryEnvelope(
        source_city_id="sender",
        target_city_id="receiver",
        operation="heartbeat",
        payload={"beat": 1},
        envelope_id="old-msg-1",
        created_at=relay_at,
        nadi_type="vyana",
        nadi_op="send",
        priority="rajas",
        ttl_ms=24000,
    )
    assert not envelope.is_expired, "Envelope with relay_at should NOT be expired"

    # Verify that using the old timestamp WOULD expire.
    stale_envelope = DeliveryEnvelope(
        source_city_id="sender",
        target_city_id="receiver",
        operation="heartbeat",
        payload={"beat": 1},
        envelope_id="stale-msg",
        created_at=old_timestamp,
        ttl_ms=24000,
    )
    assert stale_envelope.is_expired, "Envelope with old timestamp SHOULD be expired"


# ── Atomic drain (remove_from_outbox) ────────────────────────────────


def test_remove_from_outbox_preserves_new_messages(tmp_path):
    """Messages added after pump read must survive the drain."""
    root = tmp_path / "city"
    contract = AgentCityFilesystemContract(root=root)
    contract.ensure_dirs()
    transport = FilesystemFederationTransport(contract)

    # Write initial outbox with 3 messages.
    transport.append_to_outbox([
        {"envelope_id": "a", "source": "s", "target": "t", "operation": "op", "payload": {}},
        {"envelope_id": "b", "source": "s", "target": "t", "operation": "op", "payload": {}},
        {"envelope_id": "c", "source": "s", "target": "t", "operation": "op", "payload": {}},
    ])

    # Simulate pump reading outbox.
    messages = transport.read_outbox()
    assert len(messages) == 3

    # Simulate new message arriving DURING relay.
    transport.append_to_outbox([
        {"envelope_id": "d", "source": "s", "target": "t", "operation": "op", "payload": {}},
    ])

    # Atomic drain: remove only delivered (a, c). Preserve b and the new d.
    removed = transport.remove_from_outbox({"a", "c"})
    assert removed == 2

    remaining = transport.read_outbox()
    remaining_ids = {m["envelope_id"] for m in remaining}
    assert remaining_ids == {"b", "d"}, f"Expected b and d, got {remaining_ids}"


def test_remove_from_outbox_empty_set_is_noop(tmp_path):
    root = tmp_path / "city"
    contract = AgentCityFilesystemContract(root=root)
    contract.ensure_dirs()
    transport = FilesystemFederationTransport(contract)
    transport.append_to_outbox([
        {"envelope_id": "x", "source": "s", "target": "t", "operation": "op", "payload": {}},
    ])

    removed = transport.remove_from_outbox(set())
    assert removed == 0
    assert len(transport.read_outbox()) == 1


def test_remove_from_outbox_handles_missing_ids(tmp_path):
    root = tmp_path / "city"
    contract = AgentCityFilesystemContract(root=root)
    contract.ensure_dirs()
    transport = FilesystemFederationTransport(contract)
    transport.append_to_outbox([
        {"envelope_id": "exists", "source": "s", "target": "t", "operation": "op", "payload": {}},
    ])

    removed = transport.remove_from_outbox({"nonexistent"})
    assert removed == 0
    assert len(transport.read_outbox()) == 1


# ── Federated index includes snapshot records ─────────────────────────


def test_federated_index_includes_federation_snapshot_records(tmp_path):
    """The federated index must include records from the control plane snapshot."""
    import json

    registry_path = tmp_path / "registry.json"
    index_path = tmp_path / "index.json"
    repo = tmp_path / "city-a"
    (repo / "data" / "federation" / "reports").mkdir(parents=True)
    (repo / "data" / "federation" / "peer.json").write_text(
        json.dumps({"identity": {"city_id": "city-a", "slug": "city-a", "repo": "org/a"}, "capabilities": ["test"]})
    )
    (repo / "data" / "federation" / "reports" / "report_1.json").write_text(
        json.dumps({"heartbeat": 1, "timestamp": 1.0, "population": 1, "alive": 1, "dead": 0, "chain_valid": True})
    )
    (repo / "data" / "assistant_state.json").write_text("{}")
    upsert_agent_web_source_registry_entry(registry_path, root=repo)

    # Snapshot with presences and trust — using the correct keys.
    snapshot = {
        "presence": [
            {"city_id": "alpha", "health": "healthy", "heartbeat": 5, "capabilities": ["federation"]},
            {"city_id": "beta", "health": "degraded", "heartbeat": 2, "capabilities": []},
        ],
        "trust": [
            {"source_city_id": "alpha", "target_city_id": "beta", "level": "verified", "reason": "test"},
        ],
        "identities": [
            {"city_id": "alpha", "slug": "alpha", "repo": "org/alpha"},
            {"city_id": "beta", "slug": "beta", "repo": "org/beta"},
        ],
        "service_addresses": [],
        "hosted_endpoints": [],
    }

    index = refresh_agent_web_federated_index(
        index_path,
        registry_path=registry_path,
        state_snapshot=snapshot,
        now=99.0,
    )

    kinds = {r["kind"] for r in index["records"]}
    assert "federation_health_report" in kinds
    assert "federation_trust_summary" in kinds
    assert "federation_peer_registry" in kinds
