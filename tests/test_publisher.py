import json
import subprocess

from agent_internet.publisher import build_agent_internet_peer_descriptor, build_agent_internet_wiki, probe_wiki_remote, publish_agent_internet_wiki


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_git_workspace(tmp_path):
    remote_root = tmp_path / "remotes"
    repo_remote = remote_root / "agent-internet.git"
    wiki_remote = remote_root / "agent-internet.wiki.git"
    work_root = tmp_path / "work"
    repo_remote.parent.mkdir(parents=True)
    _git(tmp_path, "init", "--bare", str(repo_remote))
    _git(tmp_path, "init", "--bare", str(wiki_remote))
    _git(tmp_path, "clone", str(repo_remote), str(work_root))
    _git(work_root, "config", "user.email", "test@example.com")
    _git(work_root, "config", "user.name", "Test User")
    (work_root / "README.md").write_text("# Agent Internet\n")
    _git(work_root, "add", ".")
    _git(work_root, "commit", "-m", "init")
    _git(work_root, "push", "origin", "HEAD")
    _git(work_root, "remote", "set-url", "origin", "git@github.com:org/agent-internet.git")
    return work_root, wiki_remote


def test_build_agent_internet_peer_descriptor_detects_git_metadata(tmp_path):
    work_root, _wiki_remote = _init_git_workspace(tmp_path)
    payload = build_agent_internet_peer_descriptor(work_root)
    assert payload["identity"]["repo"] == "org/agent-internet"
    assert payload["git_federation"]["wiki_repo_url"] == "git@github.com:org/agent-internet.wiki.git"


def test_build_agent_internet_wiki_materializes_pages(tmp_path):
    work_root, _wiki_remote = _init_git_workspace(tmp_path)
    built = build_agent_internet_wiki(root=work_root, output_dir=tmp_path / "wiki-build", state_path=tmp_path / "state.json")
    assert any(path.name == "Agent-Web.md" for path in built)
    assert any(path.name == "Assistant-Surface.md" for path in built)
    assert any(path.name == "Node-Health.md" for path in built)
    assert any(path.name == "Federation-Status.md" for path in built)
    assert any(path.name == "Surface-Integrity.md" for path in built)
    assert any(path.name == "Repo-Quality.md" for path in built)
    assert any(path.name == "_Sidebar.md" for path in built)
    assert "# Repo Graph Capabilities" in (tmp_path / "wiki-build" / "Repo-Graph-Capabilities.md").read_text()
    assert "No assistant snapshot is published yet for this city." in (tmp_path / "wiki-build" / "Assistant-Surface.md").read_text()
    assert "No services are published yet." in (tmp_path / "wiki-build" / "Services.md").read_text()
    assert "# Node Health" in (tmp_path / "wiki-build" / "Node-Health.md").read_text()
    assert "# Federation Status" in (tmp_path / "wiki-build" / "Federation-Status.md").read_text()
    assert "Missing Declared Documents: `0`" in (tmp_path / "wiki-build" / "Surface-Integrity.md").read_text()
    assert "# Repo Quality" in (tmp_path / "wiki-build" / "Repo-Quality.md").read_text()
    assert "Tracked Files: `" in (tmp_path / "wiki-build" / "Repo-Quality.md").read_text()
    assert "Has tests: `" in (tmp_path / "wiki-build" / "Repo-Quality.md").read_text()


def test_publish_agent_internet_wiki_commits_without_push(tmp_path):
    work_root, wiki_remote = _init_git_workspace(tmp_path)
    result = publish_agent_internet_wiki(
        root=work_root,
        state_path=tmp_path / "state.json",
        wiki_path=tmp_path / "wiki-checkout",
        wiki_repo_url=str(wiki_remote),
        push=False,
    )
    assert result["changed"] is True
    assert result["pushed"] is False
    assert result["pruned"] == 0
    log = _git(tmp_path / "wiki-checkout", "log", "-1", "--pretty=%s").stdout.strip()
    assert log.startswith("agent-web: publish surfaces from ")
    assert (tmp_path / "wiki-checkout" / ".wiki-generated-inventory.json").exists()


def test_publish_agent_internet_wiki_prunes_only_stale_generated_pages(tmp_path):
    work_root, wiki_remote = _init_git_workspace(tmp_path)
    checkout = tmp_path / "wiki-checkout"
    first = publish_agent_internet_wiki(
        root=work_root,
        state_path=tmp_path / "state.json",
        wiki_path=checkout,
        wiki_repo_url=str(wiki_remote),
        push=False,
        prune_generated=True,
    )

    assert first["pruned"] == 0
    stale_generated = checkout / "Semantic-Contracts.md"
    assert stale_generated.exists()
    (checkout / "Welcome-to-the-Agent-Internet.md").write_text("# Manual page\n")
    inventory = checkout / ".wiki-generated-inventory.json"
    payload = json.loads(inventory.read_text())
    payload["files"] = [path for path in payload["files"] if path != "Semantic-Contracts.md"]
    inventory.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-m", "mutate inventory without ownership")

    result = publish_agent_internet_wiki(
        root=work_root,
        state_path=tmp_path / "state.json",
        wiki_path=checkout,
        wiki_repo_url=str(wiki_remote),
        push=False,
        prune_generated=True,
    )

    assert result["pruned"] == 0
    assert stale_generated.exists()
    assert (checkout / "Welcome-to-the-Agent-Internet.md").exists()


def test_publish_agent_internet_wiki_prunes_stale_generated_from_previous_inventory(tmp_path):
    work_root, wiki_remote = _init_git_workspace(tmp_path)
    checkout = tmp_path / "wiki-checkout"
    publish_agent_internet_wiki(
        root=work_root,
        state_path=tmp_path / "state.json",
        wiki_path=checkout,
        wiki_repo_url=str(wiki_remote),
        push=False,
        prune_generated=True,
    )

    stale_generated = checkout / "Legacy-Generated.md"
    stale_generated.write_text("# Legacy\n")
    inventory = checkout / ".wiki-generated-inventory.json"
    payload = json.loads(inventory.read_text())
    payload["files"].append("Legacy-Generated.md")
    inventory.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (checkout / "Welcome-to-the-Agent-Internet.md").write_text("# Manual page\n")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-m", "add stale generated and manual pages")

    result = publish_agent_internet_wiki(
        root=work_root,
        state_path=tmp_path / "state.json",
        wiki_path=checkout,
        wiki_repo_url=str(wiki_remote),
        push=False,
        prune_generated=True,
    )

    assert result["pruned"] == 1
    assert result["pruned_paths"] == ["Legacy-Generated.md"]
    assert not stale_generated.exists()
    assert (checkout / "Welcome-to-the-Agent-Internet.md").exists()


def test_probe_wiki_remote_reports_missing_remote(tmp_path):
    missing = probe_wiki_remote(str(tmp_path / "missing.wiki.git"))

    assert missing["reachable"] is False


def test_probe_wiki_remote_reports_existing_remote(tmp_path):
    _work_root, wiki_remote = _init_git_workspace(tmp_path)

    payload = probe_wiki_remote(str(wiki_remote))

    assert payload["reachable"] is True