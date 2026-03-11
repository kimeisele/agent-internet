from __future__ import annotations

import threading
from pathlib import Path

from agent_internet.models import (
    CityEndpoint,
    CityIdentity,
    CityPresence,
    EndpointVisibility,
    ForkLineageRecord,
    HealthStatus,
    HostedEndpoint,
    IntentRecord,
    IntentStatus,
    IntentType,
    LotusApiToken,
    LotusRoute,
    LotusServiceAddress,
    SlotDescriptor,
    SlotStatus,
    SpaceDescriptor,
    SpaceKind,
)
from agent_internet.sqlite_registry import SqliteCityRegistry


def test_identity_roundtrip():
    reg = SqliteCityRegistry()
    identity = CityIdentity(city_id="alpha", slug="alpha-city", repo="test/alpha", labels={"env": "dev"})
    reg.upsert_identity(identity)
    result = reg.get_identity("alpha")
    assert result is not None
    assert result.slug == "alpha-city"
    assert result.labels == {"env": "dev"}


def test_list_identities():
    reg = SqliteCityRegistry()
    for i in range(3):
        reg.upsert_identity(CityIdentity(city_id=f"city-{i}", slug=f"slug-{i}", repo=""))
    assert len(reg.list_identities()) == 3


def test_endpoint_roundtrip():
    reg = SqliteCityRegistry()
    endpoint = CityEndpoint(city_id="alpha", transport="filesystem", location="/data")
    reg.upsert_endpoint(endpoint)
    result = reg.get_endpoint("alpha")
    assert result is not None
    assert result.transport == "filesystem"


def test_assign_link_address():
    reg = SqliteCityRegistry()
    addr = reg.assign_link_address("alpha")
    assert addr.city_id == "alpha"
    assert addr.mac_address.startswith("02:00:")
    same = reg.assign_link_address("alpha")
    assert same.mac_address == addr.mac_address


def test_assign_network_address():
    reg = SqliteCityRegistry()
    addr = reg.assign_network_address("alpha")
    assert addr.city_id == "alpha"
    assert addr.ip_address.startswith("fd10:")


def test_hosted_endpoint():
    reg = SqliteCityRegistry()
    ep = HostedEndpoint(
        endpoint_id="ep-1",
        owner_city_id="alpha",
        public_handle="alpha.web",
        transport="https",
        location="https://alpha.example.com",
        link_address="02:00:00:00:00:01",
        network_address="fd10:0001:0001:0000::1",
        labels={"tier": "public"},
    )
    reg.upsert_hosted_endpoint(ep)
    assert reg.get_hosted_endpoint("ep-1") is not None
    assert reg.get_hosted_endpoint_by_handle("alpha.web") is not None
    assert len(reg.list_hosted_endpoints()) == 1


def test_service_address():
    reg = SqliteCityRegistry()
    svc = LotusServiceAddress(
        service_id="svc-1",
        owner_city_id="alpha",
        service_name="search",
        public_handle="alpha.search",
        transport="https",
        location="https://alpha.example.com/search",
        network_address="fd10::1",
    )
    reg.upsert_service_address(svc)
    assert reg.get_service_address("svc-1") is not None
    assert reg.get_service_address_by_name("alpha", "search") is not None


def test_route():
    reg = SqliteCityRegistry()
    route = LotusRoute(
        route_id="r-1",
        owner_city_id="alpha",
        destination_prefix="beta:",
        target_city_id="beta",
        next_hop_city_id="beta",
    )
    reg.upsert_route(route)
    assert reg.get_route("r-1") is not None
    assert len(reg.list_routes()) == 1


def test_api_token():
    reg = SqliteCityRegistry()
    token = LotusApiToken(
        token_id="t-1",
        subject="alpha",
        token_hint="abc...",
        token_sha256="deadbeef",
        scopes=("lotus.read",),
    )
    reg.upsert_api_token(token)
    assert reg.get_api_token("t-1") is not None
    assert reg.get_api_token_by_sha256("deadbeef") is not None


def test_space_and_slot():
    reg = SqliteCityRegistry()
    space = SpaceDescriptor(
        space_id="sp-1",
        kind=SpaceKind.CITY,
        owner_subject_id="operator",
        display_name="Main Space",
        last_seen_at=100.0,
    )
    reg.upsert_space(space)
    stored_space = reg.get_space("sp-1")
    assert stored_space is not None
    assert stored_space.last_seen_at == 100.0

    slot = SlotDescriptor(
        slot_id="sl-1",
        space_id="sp-1",
        slot_kind="general",
        holder_subject_id="agent-1",
        status=SlotStatus.ACTIVE,
        last_seen_at=100.0,
        lease_expires_at=200.0,
        reclaimable_since_at=200.0,
    )
    reg.upsert_slot(slot)
    stored_slot = reg.get_slot("sl-1")
    assert stored_slot is not None
    assert stored_slot.last_seen_at == 100.0
    assert stored_slot.lease_expires_at == 200.0
    assert stored_slot.reclaimable_since_at == 200.0


def test_fork_lineage():
    reg = SqliteCityRegistry()
    lineage = ForkLineageRecord(
        lineage_id="fl-1",
        repo="fork/repo",
        upstream_repo="origin/repo",
        line_root_repo="origin/repo",
    )
    reg.upsert_fork_lineage(lineage)
    assert reg.get_fork_lineage("fl-1") is not None


def test_intent():
    reg = SqliteCityRegistry()
    intent = IntentRecord(
        intent_id="i-1",
        intent_type=IntentType.REQUEST_ISSUE,
        status=IntentStatus.PENDING,
        title="Test",
    )
    reg.upsert_intent(intent)
    assert reg.get_intent("i-1") is not None
    assert len(reg.list_intents()) == 1


def test_presence():
    reg = SqliteCityRegistry()
    presence = CityPresence(city_id="alpha", health=HealthStatus.HEALTHY, capabilities=("search",))
    reg.announce(presence)
    result = reg.get_presence("alpha")
    assert result is not None
    assert result.health == HealthStatus.HEALTHY
    assert result.capabilities == ("search",)


def test_allocation_state():
    reg = SqliteCityRegistry()
    reg.assign_link_address("alpha")
    reg.assign_network_address("alpha")
    state = reg.allocation_state()
    assert state["next_link_id"] == 2
    assert state["next_network_id"] == 2


def test_persistent_storage(tmp_path: Path):
    db_file = str(tmp_path / "test.db")
    reg1 = SqliteCityRegistry(db_path=db_file)
    reg1.upsert_identity(CityIdentity(city_id="alpha", slug="alpha", repo=""))
    del reg1

    reg2 = SqliteCityRegistry(db_path=db_file)
    result = reg2.get_identity("alpha")
    assert result is not None
    assert result.slug == "alpha"


def test_concurrent_access():
    reg = SqliteCityRegistry()

    def writer(prefix: str):
        for i in range(20):
            reg.upsert_identity(CityIdentity(city_id=f"{prefix}-{i}", slug=f"{prefix}-{i}", repo=""))

    threads = [threading.Thread(target=writer, args=(f"t{j}",)) for j in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(reg.list_identities()) == 80
