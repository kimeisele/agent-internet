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
    assert "# Repo Graph Capabilities" in (tmp_path / "wiki-build" / "Repo-Graph-Capabilities.md").read_text()


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
    log = _git(tmp_path / "wiki-checkout", "log", "-1", "--pretty=%s").stdout.strip()
    assert log.startswith("agent-web: publish surfaces from ")


def test_probe_wiki_remote_reports_missing_remote(tmp_path):
    missing = probe_wiki_remote(str(tmp_path / "missing.wiki.git"))

    assert missing["reachable"] is False


def test_probe_wiki_remote_reports_existing_remote(tmp_path):
    _work_root, wiki_remote = _init_git_workspace(tmp_path)

    payload = probe_wiki_remote(str(wiki_remote))

    assert payload["reachable"] is True