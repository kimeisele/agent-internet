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

import html
import json
import logging
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPSConnection
from secrets import token_hex
from typing import Protocol
from urllib.parse import urljoin, urlparse, urlencode

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
            "url": self.url,
            "status": self.status_code,
            "title": self.title,
            "text_preview": self.content_text[:max_text],
            "link_count": self.link_count,
            "form_count": self.form_count,
            "meta_description": self.meta.description,
            "ok": self.ok,
            "error": self.error,
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
        # Trim forward history when navigating to a new page
        self.history = self.history[: self.cursor + 1]
        self.history.append(url)
        self.cursor = len(self.history) - 1


# ---------------------------------------------------------------------------
# HTML Parser
# ---------------------------------------------------------------------------

_BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "header", "footer", "nav", "main",
    "aside", "h1", "h2", "h3", "h4", "h5", "h6", "li", "dt", "dd",
    "blockquote", "pre", "table", "tr", "br", "hr",
})

_SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "template"})


class _PageParser(HTMLParser):
    """Stateful HTML parser that extracts text, links, forms, and metadata."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.title = ""
        self.text_parts: list[str] = []
        self.links: list[PageLink] = []
        self.forms: list[PageForm] = []
        self.meta = PageMeta()

        # Internal parser state
        self._in_title = False
        self._title_parts: list[str] = []
        self._skip_depth = 0
        self._current_link_href = ""
        self._current_link_rel = ""
        self._link_text_parts: list[str] = []
        self._in_link = False
        self._current_form_action = ""
        self._current_form_method = "GET"
        self._current_form_id = ""
        self._current_form_fields: list[FormField] = []
        self._in_form = False
        self._meta_extra: dict[str, str] = {}
        self._meta_description = ""
        self._meta_keywords: tuple[str, ...] = ()
        self._meta_author = ""
        self._meta_robots = ""
        self._meta_og_title = ""
        self._meta_og_description = ""
        self._meta_og_image = ""
        self._meta_og_url = ""
        self._meta_canonical = ""
        self._meta_charset = "utf-8"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
        tag_lower = tag.lower()

        if tag_lower in _SKIP_TAGS:
            self._skip_depth += 1
            return

        if self._skip_depth > 0:
            return

        if tag_lower in _BLOCK_TAGS:
            self.text_parts.append("\n")

        if tag_lower == "title":
            self._in_title = True
            self._title_parts = []

        elif tag_lower == "a":
            href = attr_dict.get("href", "")
            if href:
                self._in_link = True
                self._current_link_href = urljoin(self.base_url, href)
                self._current_link_rel = attr_dict.get("rel", "")
                self._link_text_parts = []

        elif tag_lower == "form":
            self._in_form = True
            action = attr_dict.get("action", "")
            self._current_form_action = urljoin(self.base_url, action) if action else self.base_url
            self._current_form_method = attr_dict.get("method", "GET").upper()
            self._current_form_id = attr_dict.get("id", "")
            self._current_form_fields = []

        elif tag_lower == "input" and self._in_form:
            self._current_form_fields.append(FormField(
                name=attr_dict.get("name", ""),
                field_type=attr_dict.get("type", "text"),
                value=attr_dict.get("value", ""),
                required="required" in attr_dict,
            ))

        elif tag_lower == "textarea" and self._in_form:
            self._current_form_fields.append(FormField(
                name=attr_dict.get("name", ""),
                field_type="textarea",
                required="required" in attr_dict,
            ))

        elif tag_lower == "select" and self._in_form:
            self._current_form_fields.append(FormField(
                name=attr_dict.get("name", ""),
                field_type="select",
            ))

        elif tag_lower == "meta":
            name = attr_dict.get("name", "").lower()
            prop = attr_dict.get("property", "").lower()
            content = attr_dict.get("content", "")
            http_equiv = attr_dict.get("http-equiv", "").lower()
            charset = attr_dict.get("charset", "")

            if charset:
                self._meta_charset = charset
            elif http_equiv == "content-type" and "charset=" in content.lower():
                parts = content.lower().split("charset=")
                if len(parts) > 1:
                    self._meta_charset = parts[1].strip().rstrip(";")

            if name == "description":
                self._meta_description = content
            elif name == "keywords":
                self._meta_keywords = tuple(k.strip() for k in content.split(",") if k.strip())
            elif name == "author":
                self._meta_author = content
            elif name == "robots":
                self._meta_robots = content
            elif prop == "og:title":
                self._meta_og_title = content
            elif prop == "og:description":
                self._meta_og_description = content
            elif prop == "og:image":
                self._meta_og_image = content
            elif prop == "og:url":
                self._meta_og_url = content
            elif name or prop:
                key = name or prop
                self._meta_extra[key] = content

        elif tag_lower == "link":
            rel = attr_dict.get("rel", "").lower()
            href = attr_dict.get("href", "")
            if rel == "canonical" and href:
                self._meta_canonical = urljoin(self.base_url, href)

        elif tag_lower == "img":
            alt = attr_dict.get("alt", "")
            if alt:
                self.text_parts.append(f"[image: {alt}]")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()

        if tag_lower in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return

        if self._skip_depth > 0:
            return

        if tag_lower == "title":
            self._in_title = False
            self.title = " ".join(self._title_parts).strip()

        elif tag_lower == "a" and self._in_link:
            self._in_link = False
            link_text = " ".join(self._link_text_parts).strip()
            if self._current_link_href:
                self.links.append(PageLink(
                    href=self._current_link_href,
                    text=link_text,
                    rel=self._current_link_rel,
                    index=len(self.links),
                ))

        elif tag_lower == "form" and self._in_form:
            self._in_form = False
            self.forms.append(PageForm(
                action=self._current_form_action,
                method=self._current_form_method,
                fields=tuple(self._current_form_fields),
                form_id=self._current_form_id,
                index=len(self.forms),
            ))

        if tag_lower in _BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
        if self._in_link:
            self._link_text_parts.append(data)
        self.text_parts.append(data)

    def handle_entityref(self, name: str) -> None:
        char = html.unescape(f"&{name};")
        self.handle_data(char)

    def handle_charref(self, name: str) -> None:
        char = html.unescape(f"&#{name};")
        self.handle_data(char)

    def build_meta(self) -> PageMeta:
        return PageMeta(
            charset=self._meta_charset,
            description=self._meta_description,
            keywords=self._meta_keywords,
            author=self._meta_author,
            robots=self._meta_robots,
            og_title=self._meta_og_title,
            og_description=self._meta_og_description,
            og_image=self._meta_og_image,
            og_url=self._meta_og_url,
            canonical_url=self._meta_canonical,
            extra=dict(self._meta_extra),
        )


def _clean_text(raw: str) -> str:
    """Collapse whitespace, preserve paragraph breaks."""
    # Normalize line endings
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse runs of whitespace within lines
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = " ".join(line.split())
        cleaned.append(stripped)
    # Collapse multiple blank lines into at most two newlines
    result = "\n".join(cleaned)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def parse_html(raw_html: str, base_url: str) -> tuple[str, str, tuple[PageLink, ...], tuple[PageForm, ...], PageMeta]:
    """Parse raw HTML into structured components.

    Returns (title, content_text, links, forms, meta).
    """
    parser = _PageParser(base_url)
    try:
        parser.feed(raw_html)
    except Exception as exc:
        logger.debug("HTML parse warning for %s: %s", base_url, exc)
    content_text = _clean_text("".join(parser.text_parts))
    return (
        parser.title,
        content_text,
        tuple(parser.links),
        tuple(parser.forms),
        parser.build_meta(),
    )


# ---------------------------------------------------------------------------
# HTTP Fetcher (stdlib only)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class BrowserConfig:
    """Tuning knobs for the agent web browser."""

    user_agent: str = "AgentWebBrowser/1.0 (agent-internet federation)"
    connect_timeout_s: float = 10.0
    read_timeout_s: float = 30.0
    max_redirects: int = 10
    max_response_bytes: int = 5_242_880  # 5 MiB
    max_page_cache: int = 64
    accept: str = "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8"
    accept_language: str = "en-US,en;q=0.9"
    default_encoding: str = "utf-8"


def _detect_encoding(headers: dict[str, str], body: bytes) -> str:
    """Best-effort encoding detection from Content-Type header or BOM."""
    ct = headers.get("content-type", "")
    if "charset=" in ct.lower():
        for part in ct.split(";"):
            if "charset=" in part.lower():
                return part.split("=", 1)[1].strip().strip('"')
    # UTF-8 BOM
    if body[:3] == b"\xef\xbb\xbf":
        return "utf-8"
    return "utf-8"


def fetch_url(
    url: str,
    *,
    config: BrowserConfig | None = None,
    method: str = "GET",
    body: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> BrowserPage:
    """Fetch a URL and return a parsed BrowserPage.

    Follows redirects (up to ``config.max_redirects``).  Returns an error
    page (with ``error`` set) on network failures rather than raising.
    """
    cfg = config or BrowserConfig()
    current_url = url
    visited: set[str] = set()

    for _redirect in range(cfg.max_redirects + 1):
        if current_url in visited:
            return _error_page(current_url, 0, "Redirect loop detected")
        visited.add(current_url)

        parsed = urlparse(current_url)
        is_https = parsed.scheme == "https"
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if is_https else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        request_headers = {
            "Host": host,
            "User-Agent": cfg.user_agent,
            "Accept": cfg.accept,
            "Accept-Language": cfg.accept_language,
            "Connection": "close",
        }
        if extra_headers:
            request_headers.update(extra_headers)

        try:
            conn_cls = HTTPSConnection if is_https else HTTPConnection
            conn = conn_cls(host, port, timeout=cfg.connect_timeout_s)
            try:
                conn.request(method, path, body=body, headers=request_headers)
                resp = conn.getresponse()
                resp_headers = {k.lower(): v for k, v in resp.getheaders()}
                status = resp.status

                # Follow redirects
                if status in (301, 302, 303, 307, 308) and "location" in resp_headers:
                    current_url = urljoin(current_url, resp_headers["location"])
                    if status == 303:
                        method = "GET"
                        body = None
                    resp.read()  # drain
                    continue

                raw_body = resp.read(cfg.max_response_bytes)
            finally:
                conn.close()

        except Exception as exc:
            return _error_page(current_url, 0, f"{type(exc).__name__}: {exc}")

        encoding = _detect_encoding(resp_headers, raw_body)
        try:
            decoded = raw_body.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            decoded = raw_body.decode("utf-8", errors="replace")

        content_type = resp_headers.get("content-type", "text/html")

        # Handle JSON responses
        if "application/json" in content_type:
            return _json_page(current_url, status, decoded, resp_headers, content_type)

        # Handle plain text
        if "text/plain" in content_type:
            return BrowserPage(
                url=current_url,
                status_code=status,
                title=current_url.split("/")[-1] or current_url,
                content_text=decoded.strip(),
                links=(),
                forms=(),
                meta=PageMeta(),
                headers=resp_headers,
                fetched_at=time.time(),
                content_type=content_type,
                encoding=encoding,
                raw_html=decoded,
            )

        # Parse HTML
        title, content_text, links, forms, meta = parse_html(decoded, current_url)
        return BrowserPage(
            url=current_url,
            status_code=status,
            title=title,
            content_text=content_text,
            links=links,
            forms=forms,
            meta=meta,
            headers=resp_headers,
            fetched_at=time.time(),
            content_type=content_type,
            encoding=encoding,
            raw_html=decoded,
        )

    return _error_page(url, 0, f"Too many redirects (>{cfg.max_redirects})")


def _json_page(url: str, status: int, body: str, headers: dict[str, str], content_type: str) -> BrowserPage:
    """Render a JSON response as a readable BrowserPage."""
    try:
        data = json.loads(body)
        formatted = json.dumps(data, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        formatted = body

    # Extract links from JSON (common patterns)
    links: list[PageLink] = []
    _extract_json_links(data if isinstance(data, (dict, list)) else {}, links, base_url=url)

    return BrowserPage(
        url=url,
        status_code=status,
        title=f"JSON: {url.split('/')[-1] or url}",
        content_text=formatted,
        links=tuple(links),
        forms=(),
        meta=PageMeta(),
        headers=headers,
        fetched_at=time.time(),
        content_type=content_type,
        encoding="utf-8",
        raw_html=body,
    )


def _extract_json_links(
    data: dict | list,
    links: list[PageLink],
    *,
    base_url: str,
    depth: int = 0,
    max_depth: int = 3,
) -> None:
    """Recursively extract URL-like values from JSON structures."""
    if depth > max_depth:
        return
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
                links.append(PageLink(
                    href=value,
                    text=str(key),
                    index=len(links),
                ))
            elif isinstance(value, (dict, list)):
                _extract_json_links(value, links, base_url=base_url, depth=depth + 1)
    elif isinstance(data, list):
        for item in data[:50]:  # Cap list traversal
            if isinstance(item, (dict, list)):
                _extract_json_links(item, links, base_url=base_url, depth=depth + 1)


def _error_page(url: str, status: int, error: str) -> BrowserPage:
    """Construct an error BrowserPage."""
    return BrowserPage(
        url=url,
        status_code=status,
        title="Error",
        content_text="",
        links=(),
        forms=(),
        meta=PageMeta(),
        fetched_at=time.time(),
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

    Usage::

        browser = AgentWebBrowser()
        page = browser.open("https://example.com")
        page2 = browser.follow_link(0)
        browser.back()
    """

    config: BrowserConfig = field(default_factory=BrowserConfig)
    _tabs: dict[str, BrowserTab] = field(default_factory=dict)
    _active_tab_id: str = ""
    _page_cache: dict[str, BrowserPage] = field(default_factory=dict)
    _sources: list[PageSource] = field(default_factory=list)
    _request_count: int = 0

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
                "tab_id": tab.tab_id,
                "label": tab.label,
                "url": tab.current_url,
                "title": tab.current_page.title if tab.current_page else "",
                "active": tab.tab_id == self._active_tab_id,
                "history_length": len(tab.history),
            }
            for tab in self._tabs.values()
        ]

    # -- Navigation --

    def open(self, url: str, *, use_cache: bool = True) -> BrowserPage:
        """Navigate the active tab to *url* and return the page."""
        if use_cache and url in self._page_cache:
            page = self._page_cache[url]
        else:
            page = self._fetch(url)
            self._cache_page(url, page)

        tab = self.active_tab
        tab.push_url(url)
        tab.current_page = page
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
        """Follow a link on the current page by index or text search.

        - ``int``:  Follow the link at that index.
        - ``str``:  Find the first link whose text or href contains the query.
        """
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
        self,
        index_or_id: int | str,
        *,
        values: dict[str, str] | None = None,
    ) -> BrowserPage:
        """Submit a form on the current page.

        ``values`` maps field names to values, overriding defaults.
        """
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

        # Build form data
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
        else:
            body = urlencode(data).encode("utf-8")
            page = fetch_url(
                form.action,
                config=self.config,
                method="POST",
                body=body,
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
        if max_length > 0:
            text = text[:max_length]
        return text

    def get_links(self, *, query: str = "") -> tuple[PageLink, ...]:
        """Return links from the current page, optionally filtered."""
        page = self.current_page
        if page is None:
            return ()
        if query:
            return page.find_links(query)
        return page.links

    # -- Snapshot / serialization --

    def snapshot(self) -> dict:
        """Export browser state as a JSON-serializable dict."""
        return {
            "kind": "agent_web_browser_snapshot",
            "version": 1,
            "active_tab_id": self._active_tab_id,
            "request_count": self._request_count,
            "cache_size": len(self._page_cache),
            "tabs": self.list_tabs(),
        }

    # -- Internal --

    def _fetch(self, url: str) -> BrowserPage:
        """Fetch a URL, trying registered sources first."""
        self._request_count += 1
        for source in self._sources:
            if source.can_handle(url):
                return source.fetch(url, config=self.config)
        return fetch_url(url, config=self.config)

    def _cache_page(self, url: str, page: BrowserPage) -> None:
        """Add a page to the LRU cache."""
        if len(self._page_cache) >= self.config.max_page_cache:
            # Evict oldest entry
            oldest_key = next(iter(self._page_cache))
            del self._page_cache[oldest_key]
        self._page_cache[url] = page
