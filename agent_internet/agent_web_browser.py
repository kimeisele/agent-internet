"""Agent Web Browser — Internet explorer for autonomous agents.

Provides a pure-Python, stateful web browser that agents can use to navigate
the public internet, federation surfaces, and GitHub repositories.  The browser
converts HTML into structured, agent-readable content (text, links, forms,
metadata) and maintains navigation state (history, tabs).

Design principles (per ADR 0003):
  - External web content is *transport*, not substrate.
  - The browser is a *transport adapter* that projects the public web into
    agent-consumable structures without importing foreign identity or governance.
  - Zero external dependencies — stdlib only (urllib, html.parser).

Usage::

    browser = AgentWebBrowser()
    page = browser.open("https://example.com")
    print(page.title, page.content_text[:200])
    for link in page.links:
        print(link.href, link.text)
    page2 = browser.follow_link(0)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from secrets import token_hex
from typing import Protocol
from urllib.parse import quote_plus, urlencode

logger = logging.getLogger("AGENT_INTERNET.WEB_BROWSER")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PageLink:
    """A hyperlink extracted from a page."""

    href: str
    text: str
    rel: str = ""
    index: int = 0


@dataclass(frozen=True, slots=True)
class FormField:
    """A single form input field."""

    name: str
    field_type: str = "text"
    value: str = ""
    required: bool = False


@dataclass(frozen=True, slots=True)
class PageForm:
    """An HTML form extracted from a page."""

    action: str
    method: str = "GET"
    fields: tuple[FormField, ...] = ()
    form_id: str = ""
    index: int = 0


@dataclass(frozen=True, slots=True)
class PageMeta:
    """Structured metadata extracted from <head>."""

    charset: str = "utf-8"
    description: str = ""
    keywords: tuple[str, ...] = ()
    author: str = ""
    robots: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    og_url: str = ""
    canonical_url: str = ""
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BrowserPage:
    """A fetched and parsed web page — the core unit of browser output."""

    url: str
    status_code: int
    title: str
    content_text: str
    links: tuple[PageLink, ...]
    forms: tuple[PageForm, ...]
    meta: PageMeta
    headers: dict[str, str] = field(default_factory=dict)
    fetched_at: float = 0.0
    content_type: str = "text/html"
    encoding: str = "utf-8"
    raw_html: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400 and not self.error

    @property
    def link_count(self) -> int:
        return len(self.links)

    @property
    def form_count(self) -> int:
        return len(self.forms)

    def find_links(self, query: str) -> tuple[PageLink, ...]:
        """Find links whose text or href contains *query* (case-insensitive)."""
        q = query.lower()
        return tuple(
            link for link in self.links
            if q in link.text.lower() or q in link.href.lower()
        )

    def summary(self, max_text: int = 500) -> dict:
        """Return a compact summary suitable for agent context windows."""
        return {
            "url": self.url, "status": self.status_code, "title": self.title,
            "text_preview": self.content_text[:max_text],
            "link_count": self.link_count, "form_count": self.form_count,
            "meta_description": self.meta.description,
            "ok": self.ok, "error": self.error,
        }


@dataclass(slots=True)
class BrowserTab:
    """A single browser tab with forward/back history."""

    tab_id: str
    history: list[str] = field(default_factory=list)
    cursor: int = -1
    current_page: BrowserPage | None = None
    label: str = ""

    @property
    def can_go_back(self) -> bool:
        return self.cursor > 0

    @property
    def can_go_forward(self) -> bool:
        return self.cursor < len(self.history) - 1

    @property
    def current_url(self) -> str:
        if 0 <= self.cursor < len(self.history):
            return self.history[self.cursor]
        return ""

    def push_url(self, url: str) -> None:
        self.history = self.history[: self.cursor + 1]
        self.history.append(url)
        self.cursor = len(self.history) - 1


@dataclass(frozen=True, slots=True)
class Bookmark:
    """A saved bookmark."""

    url: str
    title: str
    folder: str = ""
    tags: tuple[str, ...] = ()
    added_at: float = 0.0
    notes: str = ""


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """A single browsing history entry."""

    url: str
    title: str
    visited_at: float = 0.0
    status_code: int = 200


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class BrowserConfig:
    """Tuning knobs for the agent web browser."""

    user_agent: str = "Mozilla/5.0 (compatible; AgentWebBrowser/1.0; +https://github.com/kimeisele/agent-internet)"
    connect_timeout_s: float = 10.0
    read_timeout_s: float = 30.0
    max_redirects: int = 10
    max_response_bytes: int = 5_242_880  # 5 MiB
    max_page_cache: int = 64
    accept: str = "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8"
    accept_language: str = "en-US,en;q=0.9"
    default_encoding: str = "utf-8"
    respect_proxy: bool = True
    # CBR-inspired content compression
    token_budget: int = 0  # 0 = no compression. >0 = target token count
    compress_links: int = 0  # 0 = keep all. >0 = max links to keep
    # Agent-native discovery
    llms_txt_discovery: bool = True
    agents_json_discovery: bool = True
    llms_txt_timeout: float = 3.0
    agents_json_timeout: float = 3.0
    probe_timeout: float = 5.0
    max_history: int = 500


# ---------------------------------------------------------------------------
# BrowserPage factory
# ---------------------------------------------------------------------------

def _error_page(url: str, status: int, error: str) -> BrowserPage:
    """Construct an error BrowserPage."""
    return _make_page(url, status=status, error=error)


def _make_page(
    url: str,
    *,
    status: int = 200,
    title: str = "",
    content: str = "",
    links: tuple[PageLink, ...] = (),
    forms: tuple[PageForm, ...] = (),
    meta: PageMeta | None = None,
    headers: dict[str, str] | None = None,
    content_type: str = "text/html",
    encoding: str = "utf-8",
    raw_html: str = "",
    error: str = "",
) -> BrowserPage:
    """Single factory for all BrowserPage creation."""
    return BrowserPage(
        url=url,
        status_code=status,
        title=title or ("Error" if error else ""),
        content_text=content,
        links=links,
        forms=forms,
        meta=meta or PageMeta(),
        headers=headers or {},
        fetched_at=time.time(),
        content_type=content_type,
        encoding=encoding,
        raw_html=raw_html,
        error=error,
    )


# ---------------------------------------------------------------------------
# Protocol — pluggable page sources
# ---------------------------------------------------------------------------

class PageSource(Protocol):
    """Protocol for pluggable page fetchers (web, GitHub API, federation, etc.)."""

    def can_handle(self, url: str) -> bool: ...
    def fetch(self, url: str, *, config: BrowserConfig) -> BrowserPage: ...


# ---------------------------------------------------------------------------
# Agent Web Browser — stateful session manager
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class AgentWebBrowser:
    """Stateful web browser for autonomous agents.

    Manages tabs, history, and a page cache.  Delegates fetching to pluggable
    ``PageSource`` implementations (default: stdlib HTTP).
    """

    config: BrowserConfig = field(default_factory=BrowserConfig)
    _tabs: dict[str, BrowserTab] = field(default_factory=dict)
    _active_tab_id: str = ""
    _page_cache: dict[str, BrowserPage] = field(default_factory=dict)
    _sources: list[PageSource] = field(default_factory=list)
    _request_count: int = 0
    _bookmarks: list[Bookmark] = field(default_factory=list)
    _history: list[HistoryEntry] = field(default_factory=list)
    _llms_txt_cache: dict[str, dict | None] = field(default_factory=dict)
    _agents_json_cache: dict[str, dict | None] = field(default_factory=dict)
    _browsed_index: object | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self._tabs:
            tab = BrowserTab(tab_id=f"tab_{token_hex(4)}", label="main")
            self._tabs[tab.tab_id] = tab
            self._active_tab_id = tab.tab_id

    # -- Source registration --

    def register_source(self, source: PageSource) -> None:
        """Register a pluggable page source (e.g. GitHubBrowserSource)."""
        self._sources.append(source)

    # -- Tab management --

    @property
    def active_tab(self) -> BrowserTab:
        return self._tabs[self._active_tab_id]

    @property
    def current_page(self) -> BrowserPage | None:
        return self.active_tab.current_page

    def new_tab(self, label: str = "") -> str:
        """Open a new tab and switch to it.  Returns the tab ID."""
        tab = BrowserTab(tab_id=f"tab_{token_hex(4)}", label=label)
        self._tabs[tab.tab_id] = tab
        self._active_tab_id = tab.tab_id
        return tab.tab_id

    def switch_tab(self, tab_id: str) -> BrowserTab:
        """Switch to an existing tab."""
        if tab_id not in self._tabs:
            raise ValueError(f"unknown_tab:{tab_id}")
        self._active_tab_id = tab_id
        return self._tabs[tab_id]

    def close_tab(self, tab_id: str | None = None) -> None:
        """Close a tab.  Cannot close the last tab."""
        tid = tab_id or self._active_tab_id
        if tid not in self._tabs:
            raise ValueError(f"unknown_tab:{tid}")
        if len(self._tabs) <= 1:
            raise ValueError("cannot_close_last_tab")
        del self._tabs[tid]
        if self._active_tab_id == tid:
            self._active_tab_id = next(iter(self._tabs))

    def list_tabs(self) -> list[dict]:
        """Return a summary of all open tabs."""
        return [
            {
                "tab_id": tab.tab_id, "label": tab.label, "url": tab.current_url,
                "title": tab.current_page.title if tab.current_page else "",
                "active": tab.tab_id == self._active_tab_id,
                "history_length": len(tab.history),
            }
            for tab in self._tabs.values()
        ]

    # -- Navigation --

    def open(self, url: str, *, use_cache: bool = True, token_budget: int = 0) -> BrowserPage:
        """Navigate the active tab to *url* and return the page."""
        from .agent_web_browser_compress import compress_page

        if use_cache and url in self._page_cache:
            page = self._page_cache[url]
        else:
            page = self._fetch(url)
            self._cache_page(url, page)

        budget = token_budget or self.config.token_budget
        if budget > 0 and page.ok:
            page = compress_page(
                page, token_budget=budget,
                link_budget=self.config.compress_links or 20,
            )

        tab = self.active_tab
        tab.push_url(url)
        tab.current_page = page
        self._record_history(page)

        # Auto-ingest into semantic index (skip about: pages)
        if page.ok and not url.startswith("about:"):
            self._auto_ingest(page)

        logger.info("open %s → %d %s", url, page.status_code, page.title[:60])
        return page

    def back(self) -> BrowserPage | None:
        """Navigate back in the active tab's history."""
        tab = self.active_tab
        if not tab.can_go_back:
            return None
        tab.cursor -= 1
        url = tab.current_url
        page = self._page_cache.get(url) or self._fetch(url)
        tab.current_page = page
        return page

    def forward(self) -> BrowserPage | None:
        """Navigate forward in the active tab's history."""
        tab = self.active_tab
        if not tab.can_go_forward:
            return None
        tab.cursor += 1
        url = tab.current_url
        page = self._page_cache.get(url) or self._fetch(url)
        tab.current_page = page
        return page

    def follow_link(self, index_or_query: int | str) -> BrowserPage:
        """Follow a link on the current page by index or text search."""
        page = self.current_page
        if page is None:
            raise ValueError("no_current_page")
        if isinstance(index_or_query, int):
            if index_or_query < 0 or index_or_query >= len(page.links):
                raise IndexError(f"link_index_out_of_range:{index_or_query}")
            link = page.links[index_or_query]
        else:
            matches = page.find_links(index_or_query)
            if not matches:
                raise ValueError(f"no_link_matching:{index_or_query}")
            link = matches[0]
        return self.open(link.href)

    def submit_form(
        self, index_or_id: int | str, *, values: dict[str, str] | None = None,
    ) -> BrowserPage:
        """Submit a form on the current page."""
        from .agent_web_browser_http import fetch_url

        page = self.current_page
        if page is None:
            raise ValueError("no_current_page")
        if isinstance(index_or_id, int):
            if index_or_id < 0 or index_or_id >= len(page.forms):
                raise IndexError(f"form_index_out_of_range:{index_or_id}")
            form = page.forms[index_or_id]
        else:
            matching = [f for f in page.forms if f.form_id == index_or_id]
            if not matching:
                raise ValueError(f"no_form_matching:{index_or_id}")
            form = matching[0]

        data: dict[str, str] = {}
        for fld in form.fields:
            if fld.name:
                data[fld.name] = fld.value
        if values:
            data.update(values)

        if form.method == "GET":
            sep = "&" if "?" in form.action else "?"
            url = f"{form.action}{sep}{urlencode(data)}"
            return self.open(url)

        body = urlencode(data).encode("utf-8")
        page = fetch_url(
            form.action, config=self.config, method="POST", body=body,
            extra_headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self._request_count += 1
        tab = self.active_tab
        tab.push_url(form.action)
        tab.current_page = page
        self._cache_page(form.action, page)
        return page

    def refresh(self) -> BrowserPage | None:
        """Re-fetch the current page, bypassing cache."""
        tab = self.active_tab
        url = tab.current_url
        if not url:
            return None
        page = self._fetch(url)
        self._cache_page(url, page)
        tab.current_page = page
        return page

    def get_text(self, *, max_length: int = 0) -> str:
        """Return the text content of the current page."""
        page = self.current_page
        if page is None:
            return ""
        text = page.content_text
        return text[:max_length] if max_length > 0 else text

    def get_links(self, *, query: str = "") -> tuple[PageLink, ...]:
        """Return links from the current page, optionally filtered."""
        page = self.current_page
        if page is None:
            return ()
        return page.find_links(query) if query else page.links

    # -- Bookmarks --

    def bookmark(
        self, url: str = "", *, title: str = "", folder: str = "",
        tags: tuple[str, ...] | list[str] = (), notes: str = "",
    ) -> Bookmark:
        """Add a bookmark.  Defaults to current page if no URL given."""
        if not url:
            page = self.current_page
            if page is None:
                raise ValueError("no_current_page")
            url = page.url
            title = title or page.title
        self._bookmarks = [bm for bm in self._bookmarks if bm.url != url]
        bm = Bookmark(url=url, title=title or url, folder=folder,
                       tags=tuple(tags), added_at=time.time(), notes=notes)
        self._bookmarks.append(bm)
        return bm

    def remove_bookmark(self, url: str) -> bool:
        """Remove a bookmark by URL.  Returns True if found."""
        before = len(self._bookmarks)
        self._bookmarks = [bm for bm in self._bookmarks if bm.url != url]
        return len(self._bookmarks) < before

    def list_bookmarks(self, *, folder: str = "", query: str = "") -> list[Bookmark]:
        """List bookmarks, optionally filtered by folder or search query."""
        results = self._bookmarks
        if folder:
            results = [bm for bm in results if bm.folder == folder]
        if query:
            q = query.lower()
            results = [
                bm for bm in results
                if q in bm.title.lower() or q in bm.url.lower()
                or any(q in t.lower() for t in bm.tags)
                or q in bm.notes.lower()
            ]
        return results

    def bookmark_folders(self) -> list[str]:
        """Return sorted unique bookmark folder names."""
        return sorted({bm.folder for bm in self._bookmarks if bm.folder})

    @property
    def bookmark_count(self) -> int:
        return len(self._bookmarks)

    # -- History --

    def _record_history(self, page: BrowserPage) -> None:
        """Record a page visit in history."""
        entry = HistoryEntry(
            url=page.url, title=page.title,
            visited_at=time.time(), status_code=page.status_code,
        )
        self._history.append(entry)
        if len(self._history) > self.config.max_history:
            self._history = self._history[-self.config.max_history:]

    def history(self, *, limit: int = 50, query: str = "") -> list[HistoryEntry]:
        """Return browsing history, most recent first."""
        entries = list(reversed(self._history))
        if query:
            q = query.lower()
            entries = [e for e in entries if q in e.title.lower() or q in e.url.lower()]
        return entries[:limit]

    def clear_history(self) -> int:
        """Clear all history.  Returns count of entries cleared."""
        count = len(self._history)
        self._history.clear()
        return count

    @property
    def history_count(self) -> int:
        return len(self._history)

    # -- Reader mode --

    def reader(self, *, token_budget: int = 1024) -> BrowserPage:
        """Return current page in reader mode — stripped to pure content."""
        from .agent_web_browser_compress import compress_page

        page = self.current_page
        if page is None:
            raise ValueError("no_current_page")
        return compress_page(page, token_budget=token_budget, link_budget=5, keep_meta=True)

    # -- Web search --

    def search(self, query: str, *, engine: str = "duckduckgo") -> BrowserPage:
        """Search the web using a search engine."""
        if engine == "google":
            url = f"https://www.google.com/search?q={quote_plus(query)}"
        else:
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        return self.open(url)

    # -- Session save/restore --

    def save_session(self, path: str) -> dict:
        """Save browser state (bookmarks, history, tabs) to a JSON file."""
        session = {
            "kind": "agent_web_browser_session", "version": 1, "saved_at": time.time(),
            "config": {
                "token_budget": self.config.token_budget,
                "compress_links": self.config.compress_links,
                "user_agent": self.config.user_agent,
            },
            "bookmarks": [
                {"url": bm.url, "title": bm.title, "folder": bm.folder,
                 "tags": list(bm.tags), "added_at": bm.added_at, "notes": bm.notes}
                for bm in self._bookmarks
            ],
            "history": [
                {"url": e.url, "title": e.title, "visited_at": e.visited_at,
                 "status_code": e.status_code}
                for e in self._history
            ],
            "tabs": [
                {"tab_id": tab.tab_id, "label": tab.label,
                 "history": tab.history, "cursor": tab.cursor}
                for tab in self._tabs.values()
            ],
            "active_tab_id": self._active_tab_id,
            "request_count": self._request_count,
        }
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(session, indent=2, default=str), encoding="utf-8")
        return {"saved": True, "path": str(p),
                "bookmarks": len(self._bookmarks), "history": len(self._history)}

    def restore_session(self, path: str) -> dict:
        """Restore browser state from a saved session file."""
        p = Path(path)
        if not p.exists():
            return {"restored": False, "error": "file_not_found"}
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("kind") != "agent_web_browser_session":
            return {"restored": False, "error": "invalid_session_file"}

        self._bookmarks = [
            Bookmark(url=bm["url"], title=bm.get("title", ""), folder=bm.get("folder", ""),
                     tags=tuple(bm.get("tags", ())), added_at=bm.get("added_at", 0.0),
                     notes=bm.get("notes", ""))
            for bm in data.get("bookmarks", [])
        ]
        self._history = [
            HistoryEntry(url=e["url"], title=e.get("title", ""),
                         visited_at=e.get("visited_at", 0.0),
                         status_code=e.get("status_code", 200))
            for e in data.get("history", [])
        ]
        self._tabs.clear()
        for tab_data in data.get("tabs", []):
            tab = BrowserTab(
                tab_id=tab_data["tab_id"], label=tab_data.get("label", ""),
                history=tab_data.get("history", []), cursor=tab_data.get("cursor", -1),
            )
            self._tabs[tab.tab_id] = tab

        self._active_tab_id = data.get("active_tab_id", "")
        if self._active_tab_id not in self._tabs and self._tabs:
            self._active_tab_id = next(iter(self._tabs))
        if not self._tabs:
            tab = BrowserTab(tab_id=f"tab_{token_hex(4)}", label="main")
            self._tabs[tab.tab_id] = tab
            self._active_tab_id = tab.tab_id

        self._request_count = data.get("request_count", 0)
        return {"restored": True, "bookmarks": len(self._bookmarks),
                "history": len(self._history), "tabs": len(self._tabs)}

    # -- Snapshot --

    def snapshot(self) -> dict:
        """Export browser state as a JSON-serializable dict."""
        return {
            "kind": "agent_web_browser_snapshot", "version": 1,
            "active_tab_id": self._active_tab_id,
            "request_count": self._request_count,
            "cache_size": len(self._page_cache),
            "tabs": self.list_tabs(),
            "bookmark_count": len(self._bookmarks),
            "history_count": len(self._history),
        }

    # -- Internal: fetch pipeline --

    def _fetch(self, url: str) -> BrowserPage:
        """Fetch a URL with agent-native discovery.

        Resolution order:
        1. about: pages (built-in self-knowledge)
        2. Registered sources (GitHub API, etc.)
        3. /llms.txt discovery (curated agent content)
        4. Plain HTML fetch + agents.json enrichment (fallback)
        """
        from .agent_web_browser_http import (
            enrich_with_agents_json,
            fetch_url,
            try_llms_txt,
        )

        self._request_count += 1

        if url.startswith("about:"):
            return self._handle_about(url)

        for source in self._sources:
            if source.can_handle(url):
                return source.fetch(url, config=self.config)

        if self.config.llms_txt_discovery and url.startswith("https://"):
            llms_page = try_llms_txt(
                url, config=self.config, cache=self._llms_txt_cache,
            )
            if llms_page is not None:
                return llms_page

        page = fetch_url(url, config=self.config)

        if self.config.agents_json_discovery and page.ok and url.startswith("https://"):
            page = enrich_with_agents_json(
                url, page, config=self.config, cache=self._agents_json_cache,
            )

        return page

    def _handle_about(self, url: str) -> BrowserPage:
        """Render built-in about: pages for agent self-knowledge."""
        from .agent_web_browser_env import (
            build_browser_capability_manifest,
            discover_federation_descriptors,
            probe_environment,
        )

        page_name = url.removeprefix("about:").strip().lower()

        if page_name in ("", "blank"):
            return _make_page(url, title="about:blank")

        if page_name == "environment":
            env = probe_environment(config=self.config, sources=self._sources)
            conn, gh, rt = env["connectivity"], env["github"], env["runtime"]
            text = "\n".join([
                "# Agent Web Browser — Environment", "",
                "## Connectivity",
                f"  Internet: {'yes' if conn.get('has_internet') else 'NO'}",
                f"  Proxy: {conn.get('proxy_endpoint') or 'none'}", "",
                "## GitHub",
                f"  Authenticated: {'yes' if gh.get('authenticated') else 'no'}",
                f"  User: {gh.get('user') or 'anonymous'}",
                f"  API: {'reachable' if gh.get('api_reachable') else 'unreachable'}", "",
                "## Sources", *[f"  - {s}" for s in env.get("sources", [])], "",
                "## Runtime",
                f"  Python: {rt.get('python', '?')}",
                f"  Platform: {rt.get('platform', '?')}",
                f"  CWD: {rt.get('cwd', '?')}",
            ])
            return _make_page(
                url, title="Environment — Agent Web Browser", content=text,
                links=(PageLink(href="about:capabilities", text="Capabilities", index=0),
                       PageLink(href="about:federation", text="Federation", index=1),
                       PageLink(href="about:graph", text="Knowledge Graph", index=2),
                       PageLink(href="about:search", text="Search", index=3)),
            )

        if page_name == "capabilities":
            manifest = build_browser_capability_manifest(sources=self._sources)
            parts = [
                "# Agent Web Browser — Capabilities",
                f"Standard: {manifest['standard_profile']['profile_id']}",
                f"GAD: {manifest['standard_profile']['gad_conformance']}", "",
            ]
            for cap in manifest.get("capabilities", []):
                parts.append(f"## {cap['capability_id']}")
                parts.append(f"  {cap['summary']}")
                parts.append(f"  Mode: {cap['mode']}  Contract: v{cap['contract_version']}")
                parts.append("")
            return _make_page(
                url, title="Capabilities — Agent Web Browser",
                content="\n".join(parts),
                links=(PageLink(href="about:environment", text="Environment", index=0),
                       PageLink(href="about:federation", text="Federation", index=1)),
            )

        if page_name == "federation":
            parts = ["# Agent Web Browser — Federation Discovery", "",
                      "Scanning known federation peers...", ""]
            links: list[PageLink] = []
            for desc in discover_federation_descriptors(config=self.config):
                name = desc.get("display_name", desc.get("repo_id", "?"))
                parts.append(f"## {name}")
                parts.append(f"  Repo: {desc.get('repo_id', '?')}")
                parts.append(f"  Layer: {desc.get('layer', '?')}")
                parts.append(f"  Status: {desc.get('status', '?')}")
                caps = desc.get("capabilities", [])
                if caps:
                    parts.append(f"  Capabilities: {', '.join(caps)}")
                parts.append("")
                repo_id = desc.get("repo_id", "")
                if repo_id:
                    links.append(PageLink(href=f"https://github.com/{repo_id}",
                                          text=name, index=len(links)))
            if not links:
                parts.append("(no federation peers discovered)")
            links.append(PageLink(href="about:environment", text="Environment", index=len(links)))
            links.append(PageLink(href="about:capabilities", text="Capabilities", index=len(links)))
            return _make_page(url, title="Federation — Agent Web Browser",
                              content="\n".join(parts), links=tuple(links))

        if page_name.startswith("graph"):
            return self._handle_about_graph(url, page_name)

        if page_name.startswith("search"):
            return self._handle_about_search(url, page_name)

        if page_name == "bookmarks":
            parts = ["# Bookmarks", ""]
            links: list[PageLink] = []
            if not self._bookmarks:
                parts.append("(no bookmarks saved)")
            else:
                for folder in self.bookmark_folders():
                    parts.append(f"## {folder}")
                    for bm in self._bookmarks:
                        if bm.folder == folder:
                            parts.append(f"  [{bm.title}]({bm.url})")
                            if bm.tags:
                                parts.append(f"    tags: {', '.join(bm.tags)}")
                            links.append(PageLink(href=bm.url, text=bm.title, index=len(links)))
                    parts.append("")
                unfiled = [bm for bm in self._bookmarks if not bm.folder]
                if unfiled:
                    if self.bookmark_folders():
                        parts.append("## Unfiled")
                    for bm in unfiled:
                        parts.append(f"  [{bm.title}]({bm.url})")
                        if bm.tags:
                            parts.append(f"    tags: {', '.join(bm.tags)}")
                        links.append(PageLink(href=bm.url, text=bm.title, index=len(links)))
                parts.extend(["", f"Total: {len(self._bookmarks)} bookmarks"])
            return _make_page(url, title="Bookmarks — Agent Web Browser",
                              content="\n".join(parts), links=tuple(links))

        if page_name == "history":
            parts = ["# Browsing History", ""]
            links: list[PageLink] = []
            entries = self.history(limit=100)
            if not entries:
                parts.append("(no history)")
            else:
                for entry in entries:
                    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.visited_at))
                    parts.append(f"  {ts}  [{entry.status_code}] {entry.title[:60]}")
                    parts.append(f"         {entry.url}")
                    links.append(PageLink(href=entry.url, text=entry.title, index=len(links)))
                parts.extend(["", f"Total: {len(self._history)} entries"])
            return _make_page(url, title="History — Agent Web Browser",
                              content="\n".join(parts), links=tuple(links))

        return _make_page(url, status=404, error=f"unknown_about_page:{page_name}")

    def _handle_about_graph(self, url: str, page_name: str) -> BrowserPage:
        """Render about:graph — semantic knowledge graph browser.

        about:graph          → all nodes in the graph
        about:graph?query=X  → filter nodes by term
        about:graph?node=ID  → show a specific node and its neighbors
        """
        query = ""
        node_id = ""
        if "?" in page_name:
            for param in page_name.split("?", 1)[1].split("&"):
                if param.startswith("query="):
                    query = param.removeprefix("query=").replace("+", " ").strip()
                elif param.startswith("node="):
                    node_id = param.removeprefix("node=").replace("+", " ").strip()

        idx = self.browsed_index
        graph = idx.build_semantic_graph()
        neighbors_map: dict[str, list[dict]] = graph.get("neighbors_by_record_id", {})
        stats = graph.get("stats", {})

        links: list[PageLink] = []

        # Node detail view
        if node_id:
            record = None
            for r in idx.records:
                if r.get("record_id") == node_id:
                    record = r
                    break
            if not record:
                return _make_page(url, status=404, error=f"node_not_found:{node_id}")

            parts = [
                f"# Graph Node: {record.get('title', node_id)}",
                f"ID: {node_id}",
                f"Kind: {record.get('kind', '?')}",
                f"Source: {record.get('source_city_id', '?')}",
            ]
            summary = record.get("summary", "")
            if summary:
                parts.append(f"Summary: {summary}")

            href = record.get("href", "")
            if href:
                links.append(PageLink(href=href, text="Open page", index=len(links)))

            neighbors = neighbors_map.get(node_id, [])
            if neighbors:
                parts.extend(["", f"--- Neighbors ({len(neighbors)}) ---", ""])
                for nb in sorted(neighbors, key=lambda n: n.get("score", 0), reverse=True):
                    nb_title = nb.get("title", nb.get("record_id", "?"))
                    score = nb.get("score", 0)
                    reasons = ", ".join(nb.get("reason_kinds", []))
                    parts.append(f"  [{score:.3f}] {nb_title}")
                    if reasons:
                        parts.append(f"          via: {reasons}")
                    nb_href = nb.get("href", "")
                    if nb_href:
                        links.append(PageLink(href=nb_href, text=nb_title, index=len(links)))
                    nb_rid = nb.get("record_id", "")
                    if nb_rid:
                        links.append(PageLink(
                            href=f"about:graph?node={nb_rid}",
                            text=f"Node: {nb_title}", index=len(links),
                        ))

            links.append(PageLink(href="about:graph", text="All Nodes", index=len(links)))
            links.append(PageLink(href="about:search", text="Search", index=len(links)))
            return _make_page(url, title=f"Graph: {record.get('title', node_id)}",
                              content="\n".join(parts), links=tuple(links))

        # List / filter view
        parts = [
            "# Semantic Knowledge Graph", "",
            f"Nodes: {stats.get('node_count', len(idx.records))}  "
            f"Edges: {stats.get('edge_count', 0)}  "
            f"Connected: {stats.get('connected_record_count', 0)}",
        ]

        records = idx.records
        if query:
            parts.append(f"Filter: \"{query}\"")
            q_lower = query.lower()
            records = [
                r for r in records
                if q_lower in r.get("title", "").lower()
                or q_lower in r.get("summary", "").lower()
                or any(q_lower in t for t in r.get("tags", []))
            ]
            parts.append(f"Matching: {len(records)} nodes")

        parts.append("")
        for record in records[:50]:
            rid = record.get("record_id", "")
            title = record.get("title", rid)
            kind = record.get("kind", "?")
            nb_count = len(neighbors_map.get(rid, []))
            parts.append(f"  [{kind}] {title} ({nb_count} neighbors)")

            href = record.get("href", "")
            if href:
                links.append(PageLink(href=href, text=title, index=len(links)))
            links.append(PageLink(
                href=f"about:graph?node={rid}",
                text=f"Node: {title}", index=len(links),
            ))

        if len(records) > 50:
            parts.append(f"  ... and {len(records) - 50} more (use ?query= to filter)")

        if not records:
            parts.append("(no nodes — browse some pages first to populate the graph)")

        parts.extend(["", "--- Navigation ---"])
        links.append(PageLink(href="about:search", text="Search Index", index=len(links)))
        links.append(PageLink(href="about:environment", text="Environment", index=len(links)))
        links.append(PageLink(href="about:federation", text="Federation", index=len(links)))

        title = "Knowledge Graph — Agent Web Browser"
        if query:
            title = f"Graph: \"{query}\" — Agent Web Browser"
        return _make_page(url, title=title, content="\n".join(parts), links=tuple(links))

    def _handle_about_search(self, url: str, page_name: str) -> BrowserPage:
        """Render about:search — federated search over all indexed content.

        about:search       → search prompt / stats
        about:search?q=X   → execute search
        """
        query = ""
        if "?" in page_name:
            for param in page_name.split("?", 1)[1].split("&"):
                if param.startswith("q="):
                    query = param.removeprefix("q=").replace("+", " ").strip()

        idx = self.browsed_index
        links: list[PageLink] = []

        if not query:
            # Landing page — show index stats
            parts = [
                "# Federated Search — Agent Web Browser", "",
                f"Indexed pages: {len(idx.records)}",
                "",
                "Usage: open about:search?q=YOUR+QUERY to search.", "",
                "--- Navigation ---",
            ]
            links.append(PageLink(href="about:graph", text="Knowledge Graph", index=len(links)))
            links.append(PageLink(href="about:environment", text="Environment", index=len(links)))
            links.append(PageLink(href="about:federation", text="Federation", index=len(links)))
            return _make_page(url, title="Search — Agent Web Browser",
                              content="\n".join(parts), links=tuple(links))

        # Try federated index first, fall back to browsed page index
        results = None
        search_source = "browsed_pages"
        try:
            from .agent_web_federated_index import (
                load_agent_web_federated_index,
                search_agent_web_federated_index,
            )
            fed_index = load_agent_web_federated_index()
            if fed_index.get("records"):
                results = search_agent_web_federated_index(
                    fed_index, query=query, limit=20,
                )
                search_source = "federated_index"
        except Exception:
            logger.debug("federated index search unavailable", exc_info=True)

        if results is None:
            results = idx.search(query, limit=20)
            search_source = "browsed_pages"

        result_list = results.get("results", [])
        qi = results.get("query_interpretation", {})
        input_terms = qi.get("input_terms", [])
        expanded_terms = qi.get("expanded_terms", [])
        bridges = qi.get("semantic_bridges_applied", [])

        parts = [
            f"# Search: \"{query}\"", "",
            f"Source: {search_source}",
            f"Results: {len(result_list)}",
        ]

        if expanded_terms:
            parts.append(f"Terms: {', '.join(input_terms)} → expanded: {', '.join(expanded_terms)}")
        if bridges:
            parts.append(f"Bridges: {', '.join(str(b) for b in bridges)}")

        parts.append("")
        for i, result in enumerate(result_list):
            title = result.get("title", "?")
            href = result.get("href", "")
            score = result.get("score", 0)
            kind = result.get("kind", "?")
            summary = result.get("summary", "")[:100]
            matched = result.get("matched_terms", [])

            parts.append(f"  {i+1}. [{score:.3f}] {title}")
            parts.append(f"     Kind: {kind}")
            if summary:
                parts.append(f"     {summary}")
            if matched:
                parts.append(f"     Matched: {', '.join(matched[:8])}")
            parts.append("")

            if href:
                links.append(PageLink(href=href, text=title, index=len(links)))

        if not result_list:
            parts.append("(no results — try a different query or browse more pages)")

        stats = results.get("stats", {})
        indexed_count = stats.get("indexed_record_count", len(idx.records))
        parts.extend([
            "--- Index Stats ---",
            f"Indexed records: {indexed_count}",
            "",
        ])

        links.append(PageLink(href="about:graph", text="Knowledge Graph", index=len(links)))
        links.append(PageLink(href="about:search", text="New Search", index=len(links)))
        links.append(PageLink(href="about:environment", text="Environment", index=len(links)))

        return _make_page(url, title=f"Search: \"{query}\" — Agent Web Browser",
                          content="\n".join(parts), links=tuple(links))

    def _cache_page(self, url: str, page: BrowserPage) -> None:
        """Add a page to the LRU cache."""
        if len(self._page_cache) >= self.config.max_page_cache:
            oldest_key = next(iter(self._page_cache))
            del self._page_cache[oldest_key]
        self._page_cache[url] = page

    # -- Semantic index (auto-ingest) --

    @property
    def browsed_index(self) -> "BrowsedPageIndex":
        """Lazy-loaded semantic index over browsed pages."""
        if self._browsed_index is None:
            from .agent_web_browser_semantic import BrowsedPageIndex
            self._browsed_index = BrowsedPageIndex()
        return self._browsed_index  # type: ignore[return-value]

    def _auto_ingest(self, page: BrowserPage) -> None:
        """Ingest a page into the browsed page index.  Silent on error."""
        try:
            self.browsed_index.ingest(page)
        except Exception:
            logger.debug("auto-ingest failed for %s", page.url, exc_info=True)

    # -- Environment awareness --

    def environment(self) -> dict:
        """Report the browser's runtime environment."""
        from .agent_web_browser_env import probe_environment
        return probe_environment(config=self.config, sources=self._sources)

    def capability_manifest(self, *, base_url: str = "") -> dict:
        """Return a GAD-000-conformant capability manifest."""
        from .agent_web_browser_env import build_browser_capability_manifest
        return build_browser_capability_manifest(base_url=base_url, sources=self._sources)
