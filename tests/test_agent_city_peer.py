import json

from agent_internet.agent_city_peer import AgentCityPeer
from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.models import HealthStatus, TrustLevel, TrustRecord


def test_peer_from_repo_root_builds_identity_endpoint_and_contract(tmp_path):
    peer = AgentCityPeer.from_repo_root(
        tmp_path,
        city_id="city-a",
        slug="alpha",
        repo="org/agent-city-a",
        capabilities=("federation",),
    )

    assert peer.identity.city_id == "city-a"
    assert peer.identity.slug == "alpha"
    assert peer.endpoint.location == str(tmp_path.resolve())
    assert peer.contract.nadi_outbox.name == "nadi_outbox.json"
    assert peer.bridge.capabilities == ("federation",)


def test_peer_onboard_registers_and_observes_city(tmp_path):
    reports_dir = tmp_path / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_3.json").write_text(
        json.dumps({
            "heartbeat": 3,
            "timestamp": 3.0,
            "population": 4,
            "alive": 4,
            "dead": 0,
            "chain_valid": True,
        }),
    )
    peer = AgentCityPeer.from_repo_root(tmp_path, city_id="city-b", repo="org/agent-city-b")
    plane = AgentInternetControlPlane()

    observed = peer.onboard(plane)
    plane.record_trust(TrustRecord("city-a", "city-b", TrustLevel.OBSERVED, reason="workspace link"))

    assert observed.health == HealthStatus.HEALTHY
    assert plane.registry.get_identity("city-b") == peer.identity
    assert plane.resolve_route("city-a", "city-b") == peer.endpoint
