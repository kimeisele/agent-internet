"""GitHub API Browser Source — navigate GitHub repos, issues, and PRs as web pages.

Plugs into ``AgentWebBrowser`` as a ``PageSource`` so that agents can browse
GitHub URLs and the browser transparently fetches structured data from the
GitHub REST API instead of scraping HTML.

Uses only stdlib (``urllib.request``) and authenticates via ``GITHUB_TOKEN``
or the ``gh`` CLI, exactly like ``github_api_transport.py``.

Usage::

    from agent_internet.agent_web_browser import AgentWebBrowser
    from agent_internet.agent_web_browser_github import GitHubBrowserSource

    browser = AgentWebBrowser()
    browser.register_source(GitHubBrowserSource())
    page = browser.open("https://github.com/owner/repo")
    print(page.title, page.content_text[:200])
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse, quote

from .agent_web_browser import (
    BrowserConfig,
    BrowserPage,
    PageLink,
    PageMeta,
    _error_page,
)

logger = logging.getLogger("AGENT_INTERNET.WEB_BROWSER.GITHUB")

GITHUB_API = "https://api.github.com"

# Patterns for GitHub URL routing
_REPO_PAT = re.compile(r"^/([^/]+)/([^/]+)/?$")
_ISSUES_PAT = re.compile(r"^/([^/]+)/([^/]+)/issues/?$")
_ISSUE_PAT = re.compile(r"^/([^/]+)/([^/]+)/issues/(\d+)/?$")
_PULLS_PAT = re.compile(r"^/([^/]+)/([^/]+)/pulls?/?$")
_PULL_PAT = re.compile(r"^/([^/]+)/([^/]+)/pull/(\d+)/?$")
_TREE_PAT = re.compile(r"^/([^/]+)/([^/]+)/tree/([^/]+)(?:/(.+))?$")
_BLOB_PAT = re.compile(r"^/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$")
_RELEASES_PAT = re.compile(r"^/([^/]+)/([^/]+)/releases/?$")
_ACTIONS_PAT = re.compile(r"^/([^/]+)/([^/]+)/actions/?$")
_USER_PAT = re.compile(r"^/([^/]+)/?$")


def _load_github_token() -> str:
    """Load GitHub token from environment or gh CLI."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        try:
            import subprocess
            result = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                token = result.stdout.strip()
        except Exception:
            pass
    return token


@dataclass(slots=True)
class GitHubBrowserSource:
    """PageSource that intercepts github.com URLs and fetches via the GitHub API.

    Converts API responses into agent-readable ``BrowserPage`` objects with
    structured text content and navigable links.
    """

    _token: str = field(default="", repr=False)
    _rate_remaining: int = -1
    _rate_reset: float = 0.0

    def __post_init__(self) -> None:
        if not self._token:
            self._token = _load_github_token()

    @property
    def authenticated(self) -> bool:
        return bool(self._token)

    # -- PageSource protocol --

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.hostname in ("github.com", "www.github.com")

    def fetch(self, url: str, *, config: BrowserConfig) -> BrowserPage:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/"

        # Route to the appropriate handler
        handlers: list[tuple[re.Pattern, object]] = [
            (_ISSUE_PAT, self._fetch_issue),
            (_PULL_PAT, self._fetch_pull),
            (_ISSUES_PAT, self._fetch_issues),
            (_PULLS_PAT, self._fetch_pulls),
            (_BLOB_PAT, self._fetch_blob),
            (_TREE_PAT, self._fetch_tree),
            (_RELEASES_PAT, self._fetch_releases),
            (_ACTIONS_PAT, self._fetch_actions),
            (_REPO_PAT, self._fetch_repo),
            (_USER_PAT, self._fetch_user),
        ]

        for pattern, handler in handlers:
            match = pattern.match(path)
            if match:
                return handler(url, match, config=config)

        # Fallback: fetch the URL normally (GitHub HTML)
        return _error_page(url, 0, f"Unrecognized GitHub path: {path}")

    # -- GitHub API helpers --

    def _api_get(self, endpoint: str, *, config: BrowserConfig) -> tuple[int, dict | list | str]:
        """GET from GitHub API.  Returns (status_code, parsed_json_or_error)."""
        import urllib.request

        url = f"{GITHUB_API}{endpoint}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": config.user_agent,
        }
        if self._token:
            headers["Authorization"] = f"token {self._token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=config.connect_timeout_s) as resp:
                # Track rate limits
                self._rate_remaining = int(resp.headers.get("X-RateLimit-Remaining", -1))
                self._rate_reset = float(resp.headers.get("X-RateLimit-Reset", 0))
                body = resp.read().decode("utf-8", errors="replace")
                return resp.status, json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            try:
                return exc.code, json.loads(body)
            except (json.JSONDecodeError, ValueError):
                return exc.code, body
        except Exception as exc:
            return 0, f"{type(exc).__name__}: {exc}"

    def _api_get_raw(self, endpoint: str, *, config: BrowserConfig) -> tuple[int, str]:
        """GET raw content from GitHub API (e.g. file contents)."""
        import urllib.request

        url = f"{GITHUB_API}{endpoint}"
        headers = {
            "Accept": "application/vnd.github.v3.raw",
            "User-Agent": config.user_agent,
        }
        if self._token:
            headers["Authorization"] = f"token {self._token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=config.connect_timeout_s) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            return exc.code, body
        except Exception as exc:
            return 0, f"{type(exc).__name__}: {exc}"

    # -- Route handlers --

    def _fetch_repo(self, url: str, match: re.Match, *, config: BrowserConfig) -> BrowserPage:
        owner, repo = match.group(1), match.group(2)
        status, data = self._api_get(f"/repos/{owner}/{repo}", config=config)

        if not isinstance(data, dict) or status >= 400:
            detail = data if isinstance(data, str) else data.get("message", str(data)) if isinstance(data, dict) else str(data)
            return _error_page(url, status, f"GitHub API error: {detail}")

        # Also fetch README
        _, readme_text = self._api_get_raw(
            f"/repos/{owner}/{repo}/readme", config=config,
        )

        text_parts = [
            f"# {data.get('full_name', f'{owner}/{repo}')}",
            "",
            data.get("description", "") or "(no description)",
            "",
            f"Language: {data.get('language', 'unknown')}",
            f"Stars: {data.get('stargazers_count', 0)}  Forks: {data.get('forks_count', 0)}  "
            f"Open Issues: {data.get('open_issues_count', 0)}",
            f"Default Branch: {data.get('default_branch', 'main')}",
            f"License: {(data.get('license') or {}).get('spdx_id', 'none')}",
            f"Created: {data.get('created_at', '')}  Updated: {data.get('updated_at', '')}",
        ]

        if data.get("topics"):
            text_parts.append(f"Topics: {', '.join(data['topics'])}")

        if readme_text and not readme_text.startswith("{"):
            text_parts.extend(["", "--- README ---", "", readme_text[:4000]])

        links = [
            PageLink(href=f"https://github.com/{owner}/{repo}/issues", text="Issues", index=0),
            PageLink(href=f"https://github.com/{owner}/{repo}/pulls", text="Pull Requests", index=1),
            PageLink(href=f"https://github.com/{owner}/{repo}/tree/{data.get('default_branch', 'main')}", text="Browse Code", index=2),
            PageLink(href=f"https://github.com/{owner}/{repo}/releases", text="Releases", index=3),
            PageLink(href=f"https://github.com/{owner}/{repo}/actions", text="Actions", index=4),
        ]

        if data.get("homepage"):
            links.append(PageLink(href=data["homepage"], text="Homepage", index=len(links)))

        if data.get("parent"):
            parent = data["parent"]
            links.append(PageLink(
                href=f"https://github.com/{parent.get('full_name', '')}",
                text=f"Fork of {parent.get('full_name', '')}",
                index=len(links),
            ))

        return BrowserPage(
            url=url,
            status_code=status,
            title=f"{owner}/{repo} — GitHub",
            content_text="\n".join(text_parts),
            links=tuple(links),
            forms=(),
            meta=PageMeta(
                description=data.get("description", ""),
                keywords=tuple(data.get("topics", [])),
            ),
            fetched_at=time.time(),
            content_type="application/json",
        )

    def _fetch_issues(self, url: str, match: re.Match, *, config: BrowserConfig) -> BrowserPage:
        owner, repo = match.group(1), match.group(2)
        status, data = self._api_get(
            f"/repos/{owner}/{repo}/issues?state=open&per_page=30", config=config,
        )

        if not isinstance(data, list):
            return _error_page(url, status, f"GitHub API error: {data}")

        text_parts = [f"# Issues — {owner}/{repo}", ""]
        links: list[PageLink] = []

        for i, issue in enumerate(data):
            if issue.get("pull_request"):
                continue  # Skip PRs in issue list
            number = issue.get("number", 0)
            title = issue.get("title", "")
            state = issue.get("state", "")
            labels = ", ".join(lb.get("name", "") for lb in issue.get("labels", []))
            user = (issue.get("user") or {}).get("login", "")
            text_parts.append(
                f"#{number} [{state}] {title}"
                + (f"  (labels: {labels})" if labels else "")
                + (f"  by {user}" if user else "")
            )
            links.append(PageLink(
                href=f"https://github.com/{owner}/{repo}/issues/{number}",
                text=f"#{number}: {title}",
                index=len(links),
            ))

        if not links:
            text_parts.append("(no open issues)")

        links.append(PageLink(
            href=f"https://github.com/{owner}/{repo}",
            text=f"Back to {owner}/{repo}",
            index=len(links),
        ))

        return BrowserPage(
            url=url,
            status_code=status,
            title=f"Issues — {owner}/{repo}",
            content_text="\n".join(text_parts),
            links=tuple(links),
            forms=(),
            meta=PageMeta(),
            fetched_at=time.time(),
            content_type="application/json",
        )

    def _fetch_issue(self, url: str, match: re.Match, *, config: BrowserConfig) -> BrowserPage:
        owner, repo, number = match.group(1), match.group(2), match.group(3)
        status, data = self._api_get(
            f"/repos/{owner}/{repo}/issues/{number}", config=config,
        )

        if not isinstance(data, dict):
            return _error_page(url, status, f"GitHub API error: {data}")

        # Fetch comments
        _, comments = self._api_get(
            f"/repos/{owner}/{repo}/issues/{number}/comments?per_page=30", config=config,
        )

        title = data.get("title", "")
        state = data.get("state", "")
        user = (data.get("user") or {}).get("login", "")
        body = data.get("body", "") or ""
        labels = ", ".join(lb.get("name", "") for lb in data.get("labels", []))
        assignees = ", ".join(a.get("login", "") for a in data.get("assignees", []))

        text_parts = [
            f"# #{number}: {title}",
            f"State: {state}  Author: {user}",
        ]
        if labels:
            text_parts.append(f"Labels: {labels}")
        if assignees:
            text_parts.append(f"Assignees: {assignees}")
        text_parts.extend(["", body[:4000]])

        if isinstance(comments, list) and comments:
            text_parts.extend(["", "--- Comments ---", ""])
            for comment in comments[:20]:
                c_user = (comment.get("user") or {}).get("login", "")
                c_body = comment.get("body", "")[:800]
                c_date = comment.get("created_at", "")
                text_parts.append(f"@{c_user} ({c_date}):\n{c_body}\n")

        links = [
            PageLink(
                href=f"https://github.com/{owner}/{repo}/issues",
                text="All Issues",
                index=0,
            ),
            PageLink(
                href=f"https://github.com/{owner}/{repo}",
                text=f"Back to {owner}/{repo}",
                index=1,
            ),
        ]

        return BrowserPage(
            url=url,
            status_code=status,
            title=f"#{number}: {title} — {owner}/{repo}",
            content_text="\n".join(text_parts),
            links=tuple(links),
            forms=(),
            meta=PageMeta(description=body[:200]),
            fetched_at=time.time(),
            content_type="application/json",
        )

    def _fetch_pulls(self, url: str, match: re.Match, *, config: BrowserConfig) -> BrowserPage:
        owner, repo = match.group(1), match.group(2)
        status, data = self._api_get(
            f"/repos/{owner}/{repo}/pulls?state=open&per_page=30", config=config,
        )

        if not isinstance(data, list):
            return _error_page(url, status, f"GitHub API error: {data}")

        text_parts = [f"# Pull Requests — {owner}/{repo}", ""]
        links: list[PageLink] = []

        for pr in data:
            number = pr.get("number", 0)
            title = pr.get("title", "")
            state = pr.get("state", "")
            user = (pr.get("user") or {}).get("login", "")
            draft = " [DRAFT]" if pr.get("draft") else ""
            text_parts.append(f"#{number} [{state}{draft}] {title}  by {user}")
            links.append(PageLink(
                href=f"https://github.com/{owner}/{repo}/pull/{number}",
                text=f"#{number}: {title}",
                index=len(links),
            ))

        if not links:
            text_parts.append("(no open pull requests)")

        links.append(PageLink(
            href=f"https://github.com/{owner}/{repo}",
            text=f"Back to {owner}/{repo}",
            index=len(links),
        ))

        return BrowserPage(
            url=url,
            status_code=status,
            title=f"Pull Requests — {owner}/{repo}",
            content_text="\n".join(text_parts),
            links=tuple(links),
            forms=(),
            meta=PageMeta(),
            fetched_at=time.time(),
            content_type="application/json",
        )

    def _fetch_pull(self, url: str, match: re.Match, *, config: BrowserConfig) -> BrowserPage:
        owner, repo, number = match.group(1), match.group(2), match.group(3)
        status, data = self._api_get(
            f"/repos/{owner}/{repo}/pulls/{number}", config=config,
        )

        if not isinstance(data, dict):
            return _error_page(url, status, f"GitHub API error: {data}")

        # Fetch review comments
        _, comments = self._api_get(
            f"/repos/{owner}/{repo}/issues/{number}/comments?per_page=20", config=config,
        )

        title = data.get("title", "")
        state = data.get("state", "")
        merged = data.get("merged", False)
        user = (data.get("user") or {}).get("login", "")
        body = data.get("body", "") or ""
        base = (data.get("base") or {}).get("ref", "")
        head = (data.get("head") or {}).get("ref", "")
        additions = data.get("additions", 0)
        deletions = data.get("deletions", 0)
        changed_files = data.get("changed_files", 0)
        draft = " [DRAFT]" if data.get("draft") else ""
        merge_state = "MERGED" if merged else state.upper()

        text_parts = [
            f"# PR #{number}: {title}{draft}",
            f"State: {merge_state}  Author: {user}",
            f"Branch: {head} → {base}",
            f"Changes: +{additions} -{deletions} in {changed_files} files",
            "",
            body[:4000],
        ]

        if isinstance(comments, list) and comments:
            text_parts.extend(["", "--- Comments ---", ""])
            for comment in comments[:15]:
                c_user = (comment.get("user") or {}).get("login", "")
                c_body = comment.get("body", "")[:800]
                text_parts.append(f"@{c_user}:\n{c_body}\n")

        links = [
            PageLink(
                href=f"https://github.com/{owner}/{repo}/pulls",
                text="All Pull Requests",
                index=0,
            ),
            PageLink(
                href=f"https://github.com/{owner}/{repo}",
                text=f"Back to {owner}/{repo}",
                index=1,
            ),
        ]

        return BrowserPage(
            url=url,
            status_code=status,
            title=f"PR #{number}: {title} — {owner}/{repo}",
            content_text="\n".join(text_parts),
            links=tuple(links),
            forms=(),
            meta=PageMeta(description=body[:200]),
            fetched_at=time.time(),
            content_type="application/json",
        )

    def _fetch_tree(self, url: str, match: re.Match, *, config: BrowserConfig) -> BrowserPage:
        owner, repo = match.group(1), match.group(2)
        ref = match.group(3)
        subpath = match.group(4) or ""

        endpoint = f"/repos/{owner}/{repo}/contents/{quote(subpath, safe='/')}?ref={ref}"
        status, data = self._api_get(endpoint, config=config)

        if not isinstance(data, list):
            # Might be a single file
            if isinstance(data, dict) and data.get("type") == "file":
                return self._render_file(url, owner, repo, ref, subpath, data, config=config)
            return _error_page(url, status, f"GitHub API error: {data}")

        path_display = f"{owner}/{repo}/{subpath}" if subpath else f"{owner}/{repo}"
        text_parts = [f"# {path_display} (branch: {ref})", ""]
        links: list[PageLink] = []

        # Sort: dirs first, then files
        dirs = sorted((item for item in data if item.get("type") == "dir"), key=lambda x: x.get("name", ""))
        files = sorted((item for item in data if item.get("type") != "dir"), key=lambda x: x.get("name", ""))

        for item in dirs:
            name = item.get("name", "")
            text_parts.append(f"  📁 {name}/")
            item_path = f"{subpath}/{name}" if subpath else name
            links.append(PageLink(
                href=f"https://github.com/{owner}/{repo}/tree/{ref}/{item_path}",
                text=f"{name}/",
                index=len(links),
            ))

        for item in files:
            name = item.get("name", "")
            size = item.get("size", 0)
            text_parts.append(f"  📄 {name}  ({_human_size(size)})")
            item_path = f"{subpath}/{name}" if subpath else name
            links.append(PageLink(
                href=f"https://github.com/{owner}/{repo}/blob/{ref}/{item_path}",
                text=name,
                index=len(links),
            ))

        # Navigation links
        if subpath:
            parent = "/".join(subpath.split("/")[:-1])
            if parent:
                links.append(PageLink(
                    href=f"https://github.com/{owner}/{repo}/tree/{ref}/{parent}",
                    text="Parent Directory",
                    index=len(links),
                ))
            else:
                links.append(PageLink(
                    href=f"https://github.com/{owner}/{repo}/tree/{ref}",
                    text="Root Directory",
                    index=len(links),
                ))

        links.append(PageLink(
            href=f"https://github.com/{owner}/{repo}",
            text=f"Back to {owner}/{repo}",
            index=len(links),
        ))

        return BrowserPage(
            url=url,
            status_code=status,
            title=f"{path_display} — GitHub",
            content_text="\n".join(text_parts),
            links=tuple(links),
            forms=(),
            meta=PageMeta(),
            fetched_at=time.time(),
            content_type="application/json",
        )

    def _fetch_blob(self, url: str, match: re.Match, *, config: BrowserConfig) -> BrowserPage:
        owner, repo = match.group(1), match.group(2)
        ref = match.group(3)
        filepath = match.group(4) or ""

        endpoint = f"/repos/{owner}/{repo}/contents/{quote(filepath, safe='/')}?ref={ref}"
        status, data = self._api_get(endpoint, config=config)

        if not isinstance(data, dict):
            return _error_page(url, status, f"GitHub API error: {data}")

        return self._render_file(url, owner, repo, ref, filepath, data, config=config)

    def _render_file(
        self,
        url: str,
        owner: str,
        repo: str,
        ref: str,
        filepath: str,
        data: dict,
        *,
        config: BrowserConfig,
    ) -> BrowserPage:
        """Render a single file as a BrowserPage."""
        name = data.get("name", filepath.split("/")[-1])
        size = data.get("size", 0)

        # Fetch raw content
        _, raw_content = self._api_get_raw(
            f"/repos/{owner}/{repo}/contents/{quote(filepath, safe='/')}?ref={ref}",
            config=config,
        )

        text_parts = [
            f"# {filepath}",
            f"Size: {_human_size(size)}  Branch: {ref}",
            "",
            raw_content[:8000] if raw_content else "(binary or empty file)",
        ]

        parent_dir = "/".join(filepath.split("/")[:-1])
        links = [
            PageLink(
                href=f"https://github.com/{owner}/{repo}/tree/{ref}/{parent_dir}" if parent_dir
                else f"https://github.com/{owner}/{repo}/tree/{ref}",
                text="Parent Directory",
                index=0,
            ),
            PageLink(
                href=f"https://github.com/{owner}/{repo}",
                text=f"Back to {owner}/{repo}",
                index=1,
            ),
        ]

        return BrowserPage(
            url=url,
            status_code=200,
            title=f"{name} — {owner}/{repo}",
            content_text="\n".join(text_parts),
            links=tuple(links),
            forms=(),
            meta=PageMeta(),
            fetched_at=time.time(),
            content_type="text/plain",
        )

    def _fetch_releases(self, url: str, match: re.Match, *, config: BrowserConfig) -> BrowserPage:
        owner, repo = match.group(1), match.group(2)
        status, data = self._api_get(
            f"/repos/{owner}/{repo}/releases?per_page=20", config=config,
        )

        if not isinstance(data, list):
            return _error_page(url, status, f"GitHub API error: {data}")

        text_parts = [f"# Releases — {owner}/{repo}", ""]
        links: list[PageLink] = []

        for release in data:
            tag = release.get("tag_name", "")
            name = release.get("name", "") or tag
            prerelease = " [pre-release]" if release.get("prerelease") else ""
            draft = " [draft]" if release.get("draft") else ""
            published = release.get("published_at", "")
            body = (release.get("body", "") or "")[:200]
            text_parts.append(f"## {name}{prerelease}{draft}  ({published})")
            if body:
                text_parts.append(f"  {body}")
            text_parts.append("")

            html_url = release.get("html_url", "")
            if html_url:
                links.append(PageLink(href=html_url, text=name, index=len(links)))

        if not data:
            text_parts.append("(no releases)")

        links.append(PageLink(
            href=f"https://github.com/{owner}/{repo}",
            text=f"Back to {owner}/{repo}",
            index=len(links),
        ))

        return BrowserPage(
            url=url,
            status_code=status,
            title=f"Releases — {owner}/{repo}",
            content_text="\n".join(text_parts),
            links=tuple(links),
            forms=(),
            meta=PageMeta(),
            fetched_at=time.time(),
            content_type="application/json",
        )

    def _fetch_actions(self, url: str, match: re.Match, *, config: BrowserConfig) -> BrowserPage:
        owner, repo = match.group(1), match.group(2)
        status, data = self._api_get(
            f"/repos/{owner}/{repo}/actions/runs?per_page=20", config=config,
        )

        if not isinstance(data, dict):
            return _error_page(url, status, f"GitHub API error: {data}")

        runs = data.get("workflow_runs", [])
        text_parts = [f"# Actions — {owner}/{repo}", ""]
        links: list[PageLink] = []

        for run in runs:
            name = run.get("name", "")
            conclusion = run.get("conclusion", run.get("status", ""))
            branch = run.get("head_branch", "")
            created = run.get("created_at", "")
            text_parts.append(f"  [{conclusion or 'running'}] {name} on {branch}  ({created})")

            html_url = run.get("html_url", "")
            if html_url:
                links.append(PageLink(href=html_url, text=f"{name} ({conclusion})", index=len(links)))

        if not runs:
            text_parts.append("(no workflow runs)")

        links.append(PageLink(
            href=f"https://github.com/{owner}/{repo}",
            text=f"Back to {owner}/{repo}",
            index=len(links),
        ))

        return BrowserPage(
            url=url,
            status_code=status,
            title=f"Actions — {owner}/{repo}",
            content_text="\n".join(text_parts),
            links=tuple(links),
            forms=(),
            meta=PageMeta(),
            fetched_at=time.time(),
            content_type="application/json",
        )

    def _fetch_user(self, url: str, match: re.Match, *, config: BrowserConfig) -> BrowserPage:
        username = match.group(1)

        # Skip known GitHub paths
        if username in ("settings", "notifications", "explore", "marketplace", "topics", "search"):
            return _error_page(url, 0, f"Not a user path: /{username}")

        status, data = self._api_get(f"/users/{username}", config=config)

        if not isinstance(data, dict):
            return _error_page(url, status, f"GitHub API error: {data}")

        # Fetch repos
        _, repos = self._api_get(
            f"/users/{username}/repos?sort=updated&per_page=20", config=config,
        )

        name = data.get("name", "") or username
        bio = data.get("bio", "") or ""
        company = data.get("company", "") or ""
        location = data.get("location", "") or ""
        public_repos = data.get("public_repos", 0)
        followers = data.get("followers", 0)
        following = data.get("following", 0)
        user_type = data.get("type", "User")

        text_parts = [
            f"# {name} (@{username})",
            f"Type: {user_type}",
        ]
        if bio:
            text_parts.append(f"Bio: {bio}")
        if company:
            text_parts.append(f"Company: {company}")
        if location:
            text_parts.append(f"Location: {location}")
        text_parts.append(
            f"Public repos: {public_repos}  Followers: {followers}  Following: {following}"
        )

        links: list[PageLink] = []
        if isinstance(repos, list):
            text_parts.extend(["", "--- Repositories ---", ""])
            for repo_data in repos:
                repo_name = repo_data.get("name", "")
                desc = repo_data.get("description", "") or ""
                stars = repo_data.get("stargazers_count", 0)
                lang = repo_data.get("language", "") or ""
                text_parts.append(
                    f"  {repo_name}"
                    + (f" ({lang})" if lang else "")
                    + (f" ★{stars}" if stars else "")
                    + (f" — {desc[:80]}" if desc else "")
                )
                links.append(PageLink(
                    href=f"https://github.com/{username}/{repo_name}",
                    text=repo_name,
                    index=len(links),
                ))

        return BrowserPage(
            url=url,
            status_code=status,
            title=f"{name} (@{username}) — GitHub",
            content_text="\n".join(text_parts),
            links=tuple(links),
            forms=(),
            meta=PageMeta(description=bio),
            fetched_at=time.time(),
            content_type="application/json",
        )


# -- Helpers --

def _human_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1_048_576:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1_048_576:.1f} MB"


# -- Convenience factory --

def create_github_browser(*, token: str = "") -> tuple:
    """Create an AgentWebBrowser with GitHub source pre-registered.

    Returns (browser, github_source) for convenience.
    """
    from .agent_web_browser import AgentWebBrowser

    source = GitHubBrowserSource(_token=token)
    browser = AgentWebBrowser()
    browser.register_source(source)
    return browser, source
