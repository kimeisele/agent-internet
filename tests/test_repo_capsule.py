import subprocess

from agent_internet.repo_capsule import extract_repo_capsule


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def test_extract_repo_capsule_summarizes_repo(tmp_path):
    root = tmp_path / "sample-repo"
    pkg = root / "sample_pkg"
    tests = root / "tests"
    workflows = root / ".github" / "workflows"
    docs = root / "docs"
    workflows.mkdir(parents=True)
    pkg.mkdir(parents=True)
    tests.mkdir(parents=True)
    docs.mkdir(parents=True)
    (root / "README.md").write_text("# Sample Repo\n\nMachine-readable repo for agents.\n")
    (root / "pyproject.toml").write_text(
        "[project]\nname='sample-repo'\ndescription='Capsule test repo'\n[project.scripts]\nsample='sample_pkg.cli:main'\n",
    )
    (pkg / "__init__.py").write_text('"""Sample package."""\n')
    (pkg / "cli.py").write_text('"""CLI entrypoint."""\n')
    (tests / "test_smoke.py").write_text("def test_smoke():\n    assert True\n")
    (workflows / "ci.yml").write_text("name: ci\n")
    (docs / "Overview.md").write_text("# Overview\n")
    _git(tmp_path, "init", str(root))
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "remote", "add", "origin", "git@github.com:org/sample-repo.git")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")

    payload = extract_repo_capsule(root)

    assert payload["identity"]["repo_name"] == "sample-repo"
    assert payload["identity"]["git"]["origin_url"] == "git@github.com:org/sample-repo.git"
    assert payload["interfaces"]["cli_entrypoints"][0]["name"] == "sample"
    assert "sample_pkg" in payload["architecture"]["package_roots"]
    assert any(module["path"] == "sample_pkg/cli.py" for module in payload["architecture"]["key_modules"])
    assert payload["audit"]["counts"]["test_file_count"] == 1