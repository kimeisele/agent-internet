import json
import subprocess

from agent_internet.agent_city_peer import AgentCityPeer
from agent_internet.control_plane import AgentInternetControlPlane
from agent_internet.git_federation import GitWikiFederationSync, detect_git_remote_metadata, ensure_git_checkout
from agent_internet.models import ForkLineageRecord, ForkMode, UpstreamSyncPolicy
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
    (work_root / "data" / "assistant_state.json").write_text(
        json.dumps({"followed": ["alice"], "ops": {"posts": 1}}),
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
    plane.upsert_fork_lineage(
        ForkLineageRecord(
            lineage_id="lineage:city-a",
            repo="org/agent-city",
            upstream_repo="org/agent-city-root",
            line_root_repo="org/agent-city-root",
            fork_mode=ForkMode.EXPERIMENT,
            sync_policy=UpstreamSyncPolicy.ADVISORY,
            space_id="space:city-a:moltbook_assistant",
            upstream_space_id="space:city-root:moltbook_assistant",
        ),
    )

    result = GitWikiFederationSync(
        repo_root=work_root,
        wiki_repo_url=str(wiki_remote),
        checkout_path=tmp_path / "wiki-checkout",
    ).sync(
        peer_descriptor=peer_descriptor,
        state_snapshot=snapshot_control_plane(plane),
        heartbeat_label="test",
        assistant_snapshot={
            "assistant_id": "moltbook_assistant",
            "assistant_kind": "moltbook_assistant",
            "city_id": "city-a",
            "repo": "org/agent-city",
            "heartbeat_source": "steward-protocol/mahamantra",
            "heartbeat": 1,
            "city_health": "healthy",
            "following": 1,
            "invited": 0,
            "spotlighted": 0,
            "total_follows": 1,
            "total_invites": 0,
            "total_posts": 1,
            "last_post_age_s": None,
            "series_cursor": -1,
            "active_campaigns": [
                {
                    "id": "internet-adaptation",
                    "title": "Internet adaptation",
                    "north_star": "Continuously adapt to relevant new protocols and standards.",
                    "status": "active",
                    "last_gap_summary": ["keep execution bounded"],
                }
            ],
        },
    )

    assert result["committed"] is True
    clone_path = tmp_path / "wiki-clone"
    _git(tmp_path, "clone", str(wiki_remote), str(clone_path))
    assert "Connected City: city-a" in (clone_path / "Home.md").read_text()
    assert "Assistant: `moltbook_assistant`" in (clone_path / "Home.md").read_text()
    assert "Active Campaigns: `1`" in (clone_path / "Home.md").read_text()
    assert "Campaign Focus: `Internet adaptation` (active)" in (clone_path / "Home.md").read_text()
    assert "Upstream Repo: `org/agent-city-root`" in (clone_path / "Home.md").read_text()
    assert "api.forum.city-a.lotus" in (clone_path / "Services.md").read_text()
    assert "service:city-z/forum" in (clone_path / "Routes.md").read_text()
    assert "Total Posts: `1`" in (clone_path / "Assistant-Surface.md").read_text()
    assert "## Active Campaigns" in (clone_path / "Assistant-Surface.md").read_text()
    assert "North Star: Continuously adapt to relevant new protocols and standards." in (clone_path / "Assistant-Surface.md").read_text()
    assert "Gaps: keep execution bounded" in (clone_path / "Assistant-Surface.md").read_text()
    assert "# Agent Web" in (clone_path / "Agent-Web.md").read_text()
    assert "## Documents" in (clone_path / "Agent-Web.md").read_text()
    assert "`agent_web` → `Agent-Web.md` (manifest, entrypoint=True)" in (clone_path / "Agent-Web.md").read_text()
    assert "## Entrypoints" in (clone_path / "Agent-Web.md").read_text()
    assert '"kind": "agent_web_manifest"' in (clone_path / "Agent-Web.md").read_text()
    assert "# Repo Graph Capabilities" in (clone_path / "Repo-Graph-Capabilities.md").read_text()
    assert "# Repo Graph Contracts" in (clone_path / "Repo-Graph-Contracts.md").read_text()
    assert "# Public Graph" in (clone_path / "Public-Graph.md").read_text()
    assert '"kind": "agent_web_public_graph"' in (clone_path / "Public-Graph.md").read_text()
    assert "# Search Index" in (clone_path / "Search-Index.md").read_text()
    assert '"kind": "agent_web_search_index"' in (clone_path / "Search-Index.md").read_text()
    assert "# Lineage" in (clone_path / "Lineage.md").read_text()
    assert "Sync Policy: `advisory`" in (clone_path / "Lineage.md").read_text()
    assert "# Node Health" in (clone_path / "Node-Health.md").read_text()
    assert "Status: `healthy`" in (clone_path / "Node-Health.md").read_text()
    assert "# Publication Status" in (clone_path / "Publication-Status.md").read_text()
    assert "# Federation Status" in (clone_path / "Federation-Status.md").read_text()
    assert "Status: `networked`" in (clone_path / "Federation-Status.md").read_text()
    assert "Missing Declared Documents: `0`" in (clone_path / "Surface-Integrity.md").read_text()
    assert "# Repo Quality" in (clone_path / "Repo-Quality.md").read_text()
    assert "Tracked Files: `" in (clone_path / "Repo-Quality.md").read_text()
    assert "Has tests: `" in (clone_path / "Repo-Quality.md").read_text()
    assert "[[Assistant Surface|Assistant-Surface]]" in (clone_path / "_Sidebar.md").read_text()
    assert "[[Node Health|Node-Health]]" in (clone_path / "_Sidebar.md").read_text()
    assert "[[Publication Status|Publication-Status]]" in (clone_path / "_Sidebar.md").read_text()
    assert "generated public membrane" in (clone_path / "_Footer.md").read_text()


def test_ensure_git_checkout_clones_and_pulls_repo(tmp_path):
    work_root, _wiki_remote = _init_git_workspace(tmp_path)
    peer = AgentCityPeer.from_repo_root(work_root, city_id="city-checkout")
    peer.publish_self_description()
    _git(work_root, "add", ".")
    _git(work_root, "commit", "-m", "publish peer")
    _git(work_root, "push", str(work_root.parent / "remotes" / "agent-city.git"), "HEAD:refs/heads/master")

    checkout_path = tmp_path / "checkout"
    cloned = ensure_git_checkout(str(work_root.parent / "remotes" / "agent-city.git"), checkout_path)
    discovered = AgentCityPeer.discover_from_repo_root(cloned)
    assert discovered.identity.city_id == "city-checkout"

    (work_root / "SECOND.md").write_text("second\n")
    _git(work_root, "add", ".")
    _git(work_root, "commit", "-m", "second")
    _git(work_root, "push", str(work_root.parent / "remotes" / "agent-city.git"), "HEAD:refs/heads/master")

    pulled = ensure_git_checkout(str(work_root.parent / "remotes" / "agent-city.git"), checkout_path)
    assert (pulled / "SECOND.md").exists()

