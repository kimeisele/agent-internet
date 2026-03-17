"""Tests for agent_web_browser_github — GitHub API PageSource.

These tests verify URL routing and response rendering without making real API
calls.  The GitHubBrowserSource._api_get method is monkey-patched to return
canned responses.
"""

from __future__ import annotations

import pytest

from agent_internet.agent_web_browser import AgentWebBrowser, BrowserConfig
from agent_internet.agent_web_browser_github import (
    GitHubBrowserSource,
    _human_size,
    _REPO_PAT,
    _ISSUES_PAT,
    _ISSUE_PAT,
    _PULLS_PAT,
    _PULL_PAT,
    _TREE_PAT,
    _BLOB_PAT,
    _USER_PAT,
    create_github_browser,
)


# ---------------------------------------------------------------------------
# URL routing regex tests
# ---------------------------------------------------------------------------

def test_repo_pattern():
    m = _REPO_PAT.match("/owner/repo")
    assert m is not None
    assert m.group(1) == "owner"
    assert m.group(2) == "repo"

    m2 = _REPO_PAT.match("/owner/repo/")
    assert m2 is not None


def test_issues_pattern():
    m = _ISSUES_PAT.match("/owner/repo/issues")
    assert m is not None
    assert m.group(1) == "owner"


def test_issue_pattern():
    m = _ISSUE_PAT.match("/owner/repo/issues/42")
    assert m is not None
    assert m.group(3) == "42"


def test_pulls_pattern():
    assert _PULLS_PAT.match("/owner/repo/pulls") is not None
    assert _PULLS_PAT.match("/owner/repo/pull") is not None


def test_pull_pattern():
    m = _PULL_PAT.match("/owner/repo/pull/7")
    assert m is not None
    assert m.group(3) == "7"


def test_tree_pattern():
    m = _TREE_PAT.match("/owner/repo/tree/main")
    assert m is not None
    assert m.group(3) == "main"
    assert m.group(4) is None

    m2 = _TREE_PAT.match("/owner/repo/tree/main/src/lib")
    assert m2 is not None
    assert m2.group(4) == "src/lib"


def test_blob_pattern():
    m = _BLOB_PAT.match("/owner/repo/blob/main/README.md")
    assert m is not None
    assert m.group(4) == "README.md"


def test_user_pattern():
    m = _USER_PAT.match("/octocat")
    assert m is not None
    assert m.group(1) == "octocat"


# ---------------------------------------------------------------------------
# _human_size
# ---------------------------------------------------------------------------

def test_human_size():
    assert _human_size(512) == "512 B"
    assert _human_size(2048) == "2.0 KB"
    assert _human_size(3_500_000) == "3.3 MB"


# ---------------------------------------------------------------------------
# GitHubBrowserSource with mocked API
# ---------------------------------------------------------------------------

class _MockGitHubSource(GitHubBrowserSource):
    """GitHubBrowserSource with canned API responses."""

    def __init__(self, responses: dict[str, tuple[int, object]]) -> None:
        super().__init__(_token="fake-token")
        self._responses = responses

    def _api_get(self, endpoint: str, *, config: BrowserConfig) -> tuple[int, dict | list | str]:
        if endpoint in self._responses:
            return self._responses[endpoint]
        return 404, {"message": "Not Found"}

    def _api_get_raw(self, endpoint: str, *, config: BrowserConfig) -> tuple[int, str]:
        if endpoint in self._responses:
            status, data = self._responses[endpoint]
            return status, data if isinstance(data, str) else str(data)
        return 404, "Not Found"


def test_can_handle_github():
    source = GitHubBrowserSource(_token="x")
    assert source.can_handle("https://github.com/owner/repo") is True
    assert source.can_handle("https://www.github.com/owner/repo") is True
    assert source.can_handle("https://gitlab.com/owner/repo") is False
    assert source.can_handle("https://example.com") is False


def test_fetch_repo():
    source = _MockGitHubSource({
        "/repos/octo/cat": (200, {
            "full_name": "octo/cat",
            "description": "A test repo",
            "language": "Python",
            "stargazers_count": 42,
            "forks_count": 5,
            "open_issues_count": 3,
            "default_branch": "main",
            "license": {"spdx_id": "MIT"},
            "created_at": "2024-01-01",
            "updated_at": "2024-06-01",
            "topics": ["agent", "federation"],
        }),
        "/repos/octo/cat/readme": (200, "# Hello\nThis is a README."),
    })

    page = source.fetch("https://github.com/octo/cat", config=BrowserConfig())
    assert page.ok
    assert "octo/cat" in page.title
    assert "A test repo" in page.content_text
    assert "Python" in page.content_text
    assert "42" in page.content_text  # Stars
    assert len(page.links) >= 4  # Issues, PRs, Code, Releases, Actions
    assert page.meta.keywords == ("agent", "federation")
    assert "README" in page.content_text
    assert "Hello" in page.content_text


def test_fetch_issues():
    source = _MockGitHubSource({
        "/repos/octo/cat/issues?state=open&per_page=30": (200, [
            {
                "number": 1,
                "title": "Bug in parser",
                "state": "open",
                "labels": [{"name": "bug"}],
                "user": {"login": "alice"},
            },
            {
                "number": 2,
                "title": "Add feature X",
                "state": "open",
                "labels": [],
                "user": {"login": "bob"},
            },
        ]),
    })

    page = source.fetch("https://github.com/octo/cat/issues", config=BrowserConfig())
    assert page.ok
    assert "Bug in parser" in page.content_text
    assert "Add feature X" in page.content_text
    assert len(page.links) >= 2  # Two issues + back link


def test_fetch_single_issue():
    source = _MockGitHubSource({
        "/repos/octo/cat/issues/1": (200, {
            "number": 1,
            "title": "Bug in parser",
            "state": "open",
            "body": "The parser crashes on empty input.",
            "user": {"login": "alice"},
            "labels": [{"name": "bug"}, {"name": "priority:high"}],
            "assignees": [{"login": "bob"}],
        }),
        "/repos/octo/cat/issues/1/comments?per_page=30": (200, [
            {
                "user": {"login": "bob"},
                "body": "I'll fix this.",
                "created_at": "2024-02-01",
            },
        ]),
    })

    page = source.fetch("https://github.com/octo/cat/issues/1", config=BrowserConfig())
    assert page.ok
    assert "Bug in parser" in page.title
    assert "parser crashes" in page.content_text
    assert "bob" in page.content_text
    assert "I'll fix this" in page.content_text


def test_fetch_pulls():
    source = _MockGitHubSource({
        "/repos/octo/cat/pulls?state=open&per_page=30": (200, [
            {
                "number": 10,
                "title": "Add browser module",
                "state": "open",
                "draft": True,
                "user": {"login": "alice"},
            },
        ]),
    })

    page = source.fetch("https://github.com/octo/cat/pulls", config=BrowserConfig())
    assert page.ok
    assert "Add browser module" in page.content_text
    assert "DRAFT" in page.content_text


def test_fetch_single_pull():
    source = _MockGitHubSource({
        "/repos/octo/cat/pulls/10": (200, {
            "number": 10,
            "title": "Add browser module",
            "state": "open",
            "merged": False,
            "draft": False,
            "body": "This PR adds a web browser for agents.",
            "user": {"login": "alice"},
            "base": {"ref": "main"},
            "head": {"ref": "feature/browser"},
            "additions": 500,
            "deletions": 10,
            "changed_files": 5,
        }),
        "/repos/octo/cat/issues/10/comments?per_page=20": (200, []),
    })

    page = source.fetch("https://github.com/octo/cat/pull/10", config=BrowserConfig())
    assert page.ok
    assert "feature/browser" in page.content_text
    assert "+500" in page.content_text


def test_fetch_tree():
    source = _MockGitHubSource({
        "/repos/octo/cat/contents/?ref=main": (200, [
            {"name": "src", "type": "dir", "size": 0},
            {"name": "README.md", "type": "file", "size": 1234},
            {"name": "setup.py", "type": "file", "size": 567},
        ]),
    })

    page = source.fetch("https://github.com/octo/cat/tree/main", config=BrowserConfig())
    assert page.ok
    assert "src/" in page.content_text
    assert "README.md" in page.content_text
    assert len(page.links) >= 3  # src, README, setup.py + back


def test_fetch_blob():
    source = _MockGitHubSource({
        "/repos/octo/cat/contents/README.md?ref=main": (200, {
            "name": "README.md",
            "type": "file",
            "size": 100,
        }),
    })
    # Also mock raw content
    original_api_get_raw = source._api_get_raw
    source._api_get_raw = lambda endpoint, *, config: (200, "# Hello World\nContent here.")

    page = source.fetch("https://github.com/octo/cat/blob/main/README.md", config=BrowserConfig())
    assert page.ok
    assert "README.md" in page.title
    assert "Hello World" in page.content_text


def test_fetch_user():
    source = _MockGitHubSource({
        "/users/octocat": (200, {
            "login": "octocat",
            "name": "The Octocat",
            "bio": "GitHub mascot",
            "type": "User",
            "public_repos": 10,
            "followers": 1000,
            "following": 5,
        }),
        "/users/octocat/repos?sort=updated&per_page=20": (200, [
            {
                "name": "hello-world",
                "description": "A hello world repo",
                "stargazers_count": 100,
                "language": "Ruby",
            },
        ]),
    })

    page = source.fetch("https://github.com/octocat", config=BrowserConfig())
    assert page.ok
    assert "The Octocat" in page.title
    assert "GitHub mascot" in page.content_text
    assert "hello-world" in page.content_text


def test_fetch_releases():
    source = _MockGitHubSource({
        "/repos/octo/cat/releases?per_page=20": (200, [
            {
                "tag_name": "v1.0.0",
                "name": "Version 1.0",
                "prerelease": False,
                "draft": False,
                "published_at": "2024-01-15",
                "body": "First stable release.",
                "html_url": "https://github.com/octo/cat/releases/tag/v1.0.0",
            },
        ]),
    })

    page = source.fetch("https://github.com/octo/cat/releases", config=BrowserConfig())
    assert page.ok
    assert "Version 1.0" in page.content_text
    assert "First stable release" in page.content_text


def test_fetch_actions():
    source = _MockGitHubSource({
        "/repos/octo/cat/actions/runs?per_page=20": (200, {
            "workflow_runs": [
                {
                    "name": "CI",
                    "conclusion": "success",
                    "head_branch": "main",
                    "created_at": "2024-06-01",
                    "html_url": "https://github.com/octo/cat/actions/runs/123",
                },
            ],
        }),
    })

    page = source.fetch("https://github.com/octo/cat/actions", config=BrowserConfig())
    assert page.ok
    assert "CI" in page.content_text
    assert "success" in page.content_text


def test_api_error_handling():
    source = _MockGitHubSource({
        "/repos/octo/missing": (404, {"message": "Not Found"}),
    })

    page = source.fetch("https://github.com/octo/missing", config=BrowserConfig())
    assert not page.ok
    assert "error" in page.error.lower() or "not found" in page.error.lower()


# ---------------------------------------------------------------------------
# Integration: browser + GitHub source
# ---------------------------------------------------------------------------

def test_browser_with_github_source():
    source = _MockGitHubSource({
        "/repos/octo/cat": (200, {
            "full_name": "octo/cat",
            "description": "Test repo",
            "language": "Python",
            "stargazers_count": 1,
            "forks_count": 0,
            "open_issues_count": 0,
            "default_branch": "main",
            "topics": [],
        }),
        "/repos/octo/cat/readme": (200, "# README"),
    })

    browser = AgentWebBrowser()
    browser.register_source(source)
    page = browser.open("https://github.com/octo/cat")
    assert page.ok
    assert "octo/cat" in page.title


def test_create_github_browser_factory():
    browser, source = create_github_browser(token="test-token")
    assert isinstance(browser, AgentWebBrowser)
    assert isinstance(source, GitHubBrowserSource)
    assert source.authenticated is True


def test_github_skips_non_user_paths():
    source = _MockGitHubSource({})
    page = source.fetch("https://github.com/settings", config=BrowserConfig())
    assert not page.ok
    assert "Not a user path" in page.error
