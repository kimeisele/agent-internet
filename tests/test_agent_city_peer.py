import json
import subprocess

from agent_internet.agent_city_peer import AgentCityPeer
from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.models import HealthStatus, TrustLevel, TrustRecord


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


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


def test_peer_can_publish_and_discover_self_description(tmp_path):
    peer = AgentCityPeer.from_repo_root(
        tmp_path,
        city_id="city-c",
        repo="org/agent-city-c",
        slug="gamma",
        capabilities=("federation", "lotus"),
    )

    payload = peer.publish_self_description()
    discovered = AgentCityPeer.discover_from_repo_root(tmp_path)

    assert payload["identity"]["city_id"] == "city-c"
    assert discovered.identity.repo == "org/agent-city-c"
    assert discovered.bridge.capabilities == ("federation", "lotus")


def test_peer_auto_detects_repo_ref_from_git_origin(tmp_path):
    remote = tmp_path / "remote.git"
    repo_root = tmp_path / "repo"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "clone", str(remote), str(repo_root))
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test User")
    (repo_root / "README.md").write_text("# repo\n")
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-m", "init")
    _git(repo_root, "push", "origin", "HEAD")
    _git(repo_root, "remote", "set-url", "origin", "git@github.com:org/agent-city-d.git")

    peer = AgentCityPeer.from_repo_root(repo_root, city_id="city-d")

    assert peer.identity.repo == "org/agent-city-d"
