import json

from agent_internet.agent_city_bridge import AgentCityBridge, city_presence_from_report
from agent_internet.agent_city_contract import AgentCityFilesystemContract
from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.filesystem_transport import FilesystemFederationTransport
from agent_internet.models import CityEndpoint, CityIdentity, HealthStatus, TrustLevel, TrustRecord


def test_city_presence_from_report_maps_health_states():
    report = {
        "heartbeat": 7,
        "timestamp": 100.0,
        "population": 10,
        "alive": 10,
        "dead": 0,
        "chain_valid": True,
    }

    presence = city_presence_from_report("city-a", report, capabilities=("federation",))

    assert presence.city_id == "city-a"
    assert presence.health == HealthStatus.HEALTHY
    assert presence.capabilities == ("federation",)


def test_agent_city_bridge_uses_latest_report_and_writes_directives(tmp_path):
    contract = AgentCityFilesystemContract(root=tmp_path)
    transport = FilesystemFederationTransport(contract=contract)
    contract.ensure_dirs()
    (contract.reports_dir / "report_1.json").write_text(json.dumps({"heartbeat": 1, "timestamp": 1.0}))
    (contract.reports_dir / "report_2.json").write_text(
        json.dumps({"heartbeat": 2, "timestamp": 2.0, "population": 4, "alive": 3, "dead": 1, "chain_valid": True}),
    )
    bridge = AgentCityBridge(city_id="city-a", transport=transport)

    assert bridge.latest_report()["heartbeat"] == 2
    assert bridge.latest_presence().health == HealthStatus.DEGRADED

    bridge.write_directive({"directive_type": "sync"}, directive_id="dir-1")
    assert json.loads(contract.directive_path("dir-1").read_text())["directive_type"] == "sync"


def test_control_plane_registers_observes_and_routes(tmp_path):
    contract = AgentCityFilesystemContract(root=tmp_path)
    transport = FilesystemFederationTransport(contract=contract)
    contract.ensure_dirs()
    (contract.reports_dir / "report_4.json").write_text(
        json.dumps({"heartbeat": 4, "timestamp": 4.0, "population": 2, "alive": 2, "dead": 0, "chain_valid": True}),
    )

    plane = AgentInternetControlPlane()
    identity = CityIdentity(city_id="city-b", slug="b", repo="org/city-b")
    endpoint = CityEndpoint(city_id="city-b", transport="git", location="https://example/city-b.git")

    plane.register_city(identity, endpoint)
    observed = plane.observe_agent_city(
        AgentCityBridge(city_id="city-b", transport=transport),
        identity=identity,
        endpoint=endpoint,
    )
    plane.record_trust(TrustRecord("city-a", "city-b", TrustLevel.OBSERVED, reason="federation seed"))

    assert observed.health == HealthStatus.HEALTHY
    assert plane.resolve_route("city-a", "city-b") == endpoint