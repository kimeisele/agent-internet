import json
import subprocess

from agent_internet.agent_city_peer import AgentCityPeer
from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.git_federation import GitWikiFederationSync, detect_git_remote_metadata
from agent_internet.snapshot import snapshot_control_plane


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_git_workspace(tmp_path):
    remote_root = tmp_path / "remotes"
    repo_remote = remote_root / "agent-city.git"
    wiki_remote = remote_root / "agent-city.wiki.git"
    work_root = tmp_path / "work"
    repo_remote.parent.mkdir(parents=True)
    _git(tmp_path, "init", "--bare", str(repo_remote))
    _git(tmp_path, "init", "--bare", str(wiki_remote))
    _git(tmp_path, "clone", str(repo_remote), str(work_root))
    _git(work_root, "config", "user.email", "test@example.com")
    _git(work_root, "config", "user.name", "Test User")
    (work_root / "README.md").write_text("# Agent City\n")
    _git(work_root, "add", ".")
    _git(work_root, "commit", "-m", "init")
    _git(work_root, "push", "origin", "HEAD")
    _git(work_root, "remote", "set-url", "origin", "git@github.com:org/agent-city.git")
    return work_root, wiki_remote


def test_detect_git_remote_metadata_from_origin_url(tmp_path):
    work_root, _wiki_remote = _init_git_workspace(tmp_path)

    remote = detect_git_remote_metadata(work_root)

    assert remote.repo_ref == "org/agent-city"
    assert remote.wiki_repo_url == "git@github.com:org/agent-city.wiki.git"


def test_git_wiki_sync_projects_pages_and_pushes(tmp_path):
    work_root, wiki_remote = _init_git_workspace(tmp_path)
    reports_dir = work_root / "data" / "federation" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "report_1.json").write_text(
        json.dumps({"heartbeat": 1, "timestamp": 1.0, "population": 1, "alive": 1, "dead": 0, "chain_valid": True}),
    )
    peer = AgentCityPeer.from_repo_root(work_root, city_id="city-a")
    peer_descriptor = peer.publish_self_description()
    plane = AgentInternetControlPlane()
    peer.onboard(plane)
    plane.publish_service_address(
        owner_city_id="city-a",
        service_name="forum-api",
        public_handle="api.forum.city-a.lotus",
        transport="https",
        location="https://forum.city-a.example/api",
    )
    plane.publish_route(
        owner_city_id="city-a",
        destination_prefix="service:city-z/forum",
        target_city_id="city-z",
        next_hop_city_id="city-a",
    )

    result = GitWikiFederationSync(
        repo_root=work_root,
        wiki_repo_url=str(wiki_remote),
        checkout_path=tmp_path / "wiki-checkout",
    ).sync(peer_descriptor=peer_descriptor, state_snapshot=snapshot_control_plane(plane), heartbeat_label="test")

    assert result["committed"] is True
    clone_path = tmp_path / "wiki-clone"
    _git(tmp_path, "clone", str(wiki_remote), str(clone_path))
    assert "Connected City: city-a" in (clone_path / "Home.md").read_text()
    assert "api.forum.city-a.lotus" in (clone_path / "Services.md").read_text()
    assert "service:city-z/forum" in (clone_path / "Routes.md").read_text()

