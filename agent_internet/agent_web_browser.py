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
import os
import platform
from html.parser import HTMLParser
from secrets import token_hex
from typing import Protocol
from urllib.parse import urljoin, urlencode

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


# ---------------------------------------------------------------------------
# Content compression — CBR-inspired token budget for agent browsing
# ---------------------------------------------------------------------------

# Nav-chrome patterns: menus, headers, footers, cookie banners, etc.
_NAV_PATTERNS = re.compile(
    r"(?i)^("
    r"skip to (?:main )?content|toggle (?:navigation|menu)|"
    r"navigation menu|search\.\.\.|sign (?:in|up|out)|"
    r"log (?:in|out)|register|cookie|accept all|"
    r"privacy policy|terms of (?:service|use)|"
    r"follow us|subscribe|newsletter|"
    r"all rights reserved|copyright ©|"
    r"\[image:.*?\]|switch to mobile.*|"
    r"search pypi|search$|menu$|help$|docs$|sponsors?$|"
    r"copy pip instructions|latest version|navigation|"
    r"verified details|unverified details|"
    r"report project as malware|"
    r"these details have (?:not )?been verified"
    r")$"
)

# Short repeated noise lines (single words that are navigation items)
_SHORT_NAV_LEN = 4


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token (GPT/Claude average)."""
    return max(1, len(text) // 4)


def compress_page(
    page: "BrowserPage",
    *,
    token_budget: int = 1024,
    link_budget: int = 20,
    keep_meta: bool = True,
) -> "BrowserPage":
    """Compress a BrowserPage to fit within a token budget.

    Inspired by steward's CBR (Constant Bitrate) signal chain:
    - Strip nav chrome (menus, footers, cookie banners)
    - Deduplicate repeated lines
    - Collapse whitespace aggressively
    - Truncate to token budget with sentence-boundary awareness
    - Trim links to the most relevant subset

    Returns a new BrowserPage with compressed content.
    """
    if not page.ok or not page.content_text:
        return page

    # Stage 1: Strip nav chrome
    lines = page.content_text.split("\n")
    filtered: list[str] = []
    seen: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if filtered and filtered[-1] != "":
                filtered.append("")
            continue
        # Skip nav patterns
        if _NAV_PATTERNS.match(stripped):
            continue
        # Skip very short repeated items (nav menu items like "Help", "Docs")
        if len(stripped) <= _SHORT_NAV_LEN and stripped.lower() in seen:
            continue
        # Deduplicate
        norm = stripped.lower()
        if norm in seen and len(stripped) < 80:
            continue
        seen.add(norm)
        filtered.append(stripped)

    # Stage 2: Collapse to text
    text = "\n".join(filtered).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Stage 3: Token-budget truncation
    current_tokens = _estimate_tokens(text)
    if current_tokens > token_budget:
        # Target chars ≈ token_budget × 4
        target_chars = token_budget * 4
        if len(text) > target_chars:
            # Try to cut at paragraph boundary
            cut = text[:target_chars]
            last_para = cut.rfind("\n\n")
            if last_para > target_chars // 2:
                text = cut[:last_para]
            else:
                # Cut at sentence boundary
                last_dot = cut.rfind(". ")
                if last_dot > target_chars // 2:
                    text = cut[: last_dot + 1]
                else:
                    text = cut + "…"

    # Stage 4: Compress links — keep most relevant
    links = page.links
    if link_budget > 0 and len(links) > link_budget:
        # Prioritize: content links over nav/sponsor. Score by informativeness.
        scored: list[tuple[float, PageLink]] = []
        seen_hrefs: set[str] = set()
        page_domain = page.url.split("/")[2] if "/" in page.url else ""
        for link in links:
            if link.href in seen_hrefs or not link.text.strip():
                continue
            seen_hrefs.add(link.href)
            text_clean = " ".join(link.text.split()).strip()
            score = len(text_clean)
            # Bonus: same-domain links (actual content, not external sponsors)
            link_domain = link.href.split("/")[2] if link.href.startswith("http") and "/" in link.href else ""
            if link_domain == page_domain:
                score += 15
            # Bonus: informative keywords
            tl = text_clean.lower()
            if any(kw in tl for kw in ("article", "doc", "guide", "section", "chapter", "readme", "overview")):
                score += 20
            # Penalty: sponsor/ad links
            if any(kw in tl for kw in ("sponsor", "advertis", "cookie", "privacy", "terms")):
                score -= 50
            if any(ad in link.href for ad in ("careers.", "ads.", "sponsor", "utm_")):
                score -= 30
            scored.append((score, link))
        scored.sort(key=lambda x: x[0], reverse=True)
        kept = [lnk for _, lnk in scored[:link_budget]]
        # Re-index
        links = tuple(
            PageLink(href=lnk.href, text=lnk.text, rel=lnk.rel, index=i)
            for i, lnk in enumerate(kept)
        )

    # Build header with meta if requested
    header_parts: list[str] = []
    if keep_meta and page.title:
        header_parts.append(f"# {page.title}")
    if keep_meta and page.meta.description:
        header_parts.append(f"> {page.meta.description}")
    if header_parts:
        text = "\n".join(header_parts) + "\n\n" + text

    return BrowserPage(
        url=page.url,
        status_code=page.status_code,
        title=page.title,
        content_text=text,
        links=links,
        forms=page.forms,
        meta=page.meta,
        headers=page.headers,
        fetched_at=page.fetched_at,
        content_type=page.content_type,
        encoding=page.encoding,
        raw_html=page.raw_html,
    )


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

    user_agent: str = "Mozilla/5.0 (compatible; AgentWebBrowser/1.0; +https://github.com/kimeisele/agent-internet)"
    connect_timeout_s: float = 10.0
    read_timeout_s: float = 30.0
    max_redirects: int = 10
    max_response_bytes: int = 5_242_880  # 5 MiB
    max_page_cache: int = 64
    accept: str = "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8"
    accept_language: str = "en-US,en;q=0.9"
    default_encoding: str = "utf-8"
    respect_proxy: bool = True  # Honor HTTP_PROXY / HTTPS_PROXY env vars
    # CBR-inspired content compression
    token_budget: int = 0  # 0 = no compression (raw). >0 = target token count
    compress_links: int = 0  # 0 = keep all. >0 = max links to keep


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

    Uses ``urllib.request`` which natively respects ``HTTP_PROXY`` /
    ``HTTPS_PROXY`` environment variables — critical for containerized and
    sandboxed agent environments.  Returns an error page (with ``error``
    set) on network failures rather than raising.
    """
    import urllib.error
    import urllib.request

    cfg = config or BrowserConfig()

    # Validate URL before attempting network I/O
    if not url or not url.strip():
        return _error_page(url, 0, "empty_url")
    if not url.startswith(("http://", "https://")):
        return _error_page(url, 0, f"unsupported_scheme:{url.split(':')[0] if ':' in url else 'none'}")

    request_headers = {
        "User-Agent": cfg.user_agent,
        "Accept": cfg.accept,
        "Accept-Language": cfg.accept_language,
    }
    if extra_headers:
        request_headers.update(extra_headers)

    req = urllib.request.Request(url, data=body, headers=request_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=cfg.connect_timeout_s) as resp:
            raw_body = resp.read(cfg.max_response_bytes)
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}
            status = resp.status
            final_url = resp.url or url
    except urllib.error.HTTPError as exc:
        resp_headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
        raw_body = exc.read(cfg.max_response_bytes) if exc.fp else b""
        status = exc.code
        final_url = url
    except Exception as exc:
        return _error_page(url, 0, f"{type(exc).__name__}: {exc}")

    encoding = _detect_encoding(resp_headers, raw_body)
    try:
        decoded = raw_body.decode(encoding, errors="replace")
    except (LookupError, UnicodeDecodeError):
        decoded = raw_body.decode("utf-8", errors="replace")

    content_type = resp_headers.get("content-type", "text/html")

    # Handle JSON responses
    if "application/json" in content_type:
        return _json_page(final_url, status, decoded, resp_headers, content_type)

    # Handle plain text
    if "text/plain" in content_type:
        return BrowserPage(
            url=final_url,
            status_code=status,
            title=final_url.split("/")[-1] or final_url,
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
    title, content_text, links, forms, meta = parse_html(decoded, final_url)
    return BrowserPage(
        url=final_url,
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

    def open(self, url: str, *, use_cache: bool = True, token_budget: int = 0) -> BrowserPage:
        """Navigate the active tab to *url* and return the page.

        If *token_budget* > 0 (or ``config.token_budget`` > 0), compress the
        page content to fit within that token budget — stripping nav chrome,
        deduplicating, and truncating with sentence-boundary awareness.
        """
        if use_cache and url in self._page_cache:
            page = self._page_cache[url]
        else:
            page = self._fetch(url)
            self._cache_page(url, page)

        # Apply CBR-inspired content compression
        budget = token_budget or self.config.token_budget
        if budget > 0 and page.ok:
            page = compress_page(
                page,
                token_budget=budget,
                link_budget=self.config.compress_links or 20,
            )

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
        """Fetch a URL, trying about: pages, registered sources, then HTTP."""
        self._request_count += 1

        # Handle about: protocol — built-in browser pages
        if url.startswith("about:"):
            return self._handle_about(url)

        for source in self._sources:
            if source.can_handle(url):
                return source.fetch(url, config=self.config)
        return fetch_url(url, config=self.config)

    def _handle_about(self, url: str) -> BrowserPage:
        """Render built-in about: pages for agent self-knowledge."""
        page_name = url.removeprefix("about:").strip().lower()

        if page_name in ("", "blank"):
            return BrowserPage(
                url=url, status_code=200, title="about:blank",
                content_text="", links=(), forms=(), meta=PageMeta(),
                fetched_at=time.time(),
            )

        if page_name == "environment":
            env = self.environment()
            conn = env.get("connectivity", {})
            gh = env.get("github", {})
            rt = env.get("runtime", {})
            text = "\n".join([
                "# Agent Web Browser — Environment",
                "",
                "## Connectivity",
                f"  Internet: {'yes' if conn.get('has_internet') else 'NO'}",
                f"  Proxy: {conn.get('proxy_endpoint') or 'none'}",
                "",
                "## GitHub",
                f"  Authenticated: {'yes' if gh.get('authenticated') else 'no'}",
                f"  User: {gh.get('user') or 'anonymous'}",
                f"  API: {'reachable' if gh.get('api_reachable') else 'unreachable'}",
                "",
                "## Sources",
                *[f"  - {s}" for s in env.get("sources", [])],
                "",
                "## Runtime",
                f"  Python: {rt.get('python', '?')}",
                f"  Platform: {rt.get('platform', '?')}",
                f"  CWD: {rt.get('cwd', '?')}",
            ])
            links = (
                PageLink(href="about:capabilities", text="Capabilities", index=0),
                PageLink(href="about:federation", text="Federation", index=1),
            )
            return BrowserPage(
                url=url, status_code=200, title="Environment — Agent Web Browser",
                content_text=text, links=links, forms=(), meta=PageMeta(),
                fetched_at=time.time(),
            )

        if page_name == "capabilities":
            manifest = self.capability_manifest()
            text_parts = [
                "# Agent Web Browser — Capabilities",
                f"Standard: {manifest['standard_profile']['profile_id']}",
                f"GAD: {manifest['standard_profile']['gad_conformance']}",
                "",
            ]
            for cap in manifest.get("capabilities", []):
                text_parts.append(f"## {cap['capability_id']}")
                text_parts.append(f"  {cap['summary']}")
                text_parts.append(f"  Mode: {cap['mode']}  Contract: v{cap['contract_version']}")
                text_parts.append("")
            return BrowserPage(
                url=url, status_code=200, title="Capabilities — Agent Web Browser",
                content_text="\n".join(text_parts), links=(
                    PageLink(href="about:environment", text="Environment", index=0),
                    PageLink(href="about:federation", text="Federation", index=1),
                ), forms=(), meta=PageMeta(), fetched_at=time.time(),
            )

        if page_name == "federation":
            text_parts = [
                "# Agent Web Browser — Federation Discovery",
                "",
                "Scanning known federation peers...",
                "",
            ]
            links: list[PageLink] = []
            descriptors = _discover_federation_descriptors(config=self.config)
            for desc in descriptors:
                text_parts.append(f"## {desc.get('display_name', desc.get('repo_id', '?'))}")
                text_parts.append(f"  Repo: {desc.get('repo_id', '?')}")
                text_parts.append(f"  Layer: {desc.get('layer', '?')}")
                text_parts.append(f"  Status: {desc.get('status', '?')}")
                caps = desc.get("capabilities", [])
                if caps:
                    text_parts.append(f"  Capabilities: {', '.join(caps)}")
                text_parts.append("")
                repo_id = desc.get("repo_id", "")
                if repo_id:
                    links.append(PageLink(
                        href=f"https://github.com/{repo_id}",
                        text=desc.get("display_name", repo_id),
                        index=len(links),
                    ))

            if not descriptors:
                text_parts.append("(no federation peers discovered)")

            links.append(PageLink(href="about:environment", text="Environment", index=len(links)))
            links.append(PageLink(href="about:capabilities", text="Capabilities", index=len(links)))

            return BrowserPage(
                url=url, status_code=200, title="Federation — Agent Web Browser",
                content_text="\n".join(text_parts), links=tuple(links),
                forms=(), meta=PageMeta(), fetched_at=time.time(),
            )

        return _error_page(url, 404, f"unknown_about_page:{page_name}")

    def _cache_page(self, url: str, page: BrowserPage) -> None:
        """Add a page to the LRU cache."""
        if len(self._page_cache) >= self.config.max_page_cache:
            # Evict oldest entry
            oldest_key = next(iter(self._page_cache))
            del self._page_cache[oldest_key]
        self._page_cache[url] = page

    # -- Environment awareness --

    def environment(self) -> dict:
        """Report the browser's runtime environment — what it can reach and how.

        Agents should call this on startup to understand their connectivity,
        available credentials, proxy configuration, and registered sources.
        """
        return probe_environment(config=self.config, sources=self._sources)

    # -- GAD-000 capability manifest --

    def capability_manifest(self, *, base_url: str = "") -> dict:
        """Return a GAD-000-conformant capability manifest for this browser.

        Follows the same structure as ``agent_web_semantic_capabilities`` so
        consumers can discover, introspect, and invoke browser capabilities
        through a stable, versioned contract.
        """
        return build_browser_capability_manifest(
            base_url=base_url, sources=self._sources,
        )


# ---------------------------------------------------------------------------
# Environment probe — self-knowledge for agents
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class EnvironmentProbe:
    """Result of probing the runtime network environment."""

    has_internet: bool
    has_proxy: bool
    proxy_url: str
    has_github_token: bool
    github_api_reachable: bool
    github_user: str
    registered_sources: tuple[str, ...]
    python_version: str
    platform: str
    hostname: str
    working_directory: str
    probed_at: float


def probe_environment(
    *,
    config: BrowserConfig | None = None,
    sources: list[PageSource] | None = None,
) -> dict:
    """Probe and report the agent's runtime network environment.

    Returns a structured dict agents can use to understand what they can
    reach and with what credentials — so they never fly blind.
    """
    cfg = config or BrowserConfig()
    proxy = os.environ.get("HTTPS_PROXY", os.environ.get("HTTP_PROXY", ""))
    github_token = os.environ.get("GITHUB_TOKEN", "")

    # Probe GitHub API reachability + identity
    github_user = ""
    github_reachable = False
    if github_token:
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"token {github_token}",
                    "User-Agent": cfg.user_agent,
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                github_user = data.get("login", "")
                github_reachable = True
        except Exception:
            # Token present but API unreachable or invalid
            try:
                import urllib.request
                req = urllib.request.Request(
                    "https://api.github.com",
                    headers={"User-Agent": cfg.user_agent},
                )
                with urllib.request.urlopen(req, timeout=5):
                    github_reachable = True
            except Exception:
                pass

    # Probe general internet
    has_internet = False
    if github_reachable:
        has_internet = True
    else:
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://example.com",
                headers={"User-Agent": cfg.user_agent},
                method="HEAD",
            )
            with urllib.request.urlopen(req, timeout=5):
                has_internet = True
        except Exception:
            pass

    source_names = tuple(type(s).__name__ for s in (sources or []))

    probe = EnvironmentProbe(
        has_internet=has_internet,
        has_proxy=bool(proxy),
        proxy_url=proxy.split("@")[-1] if "@" in proxy else proxy[:50] if proxy else "",
        has_github_token=bool(github_token),
        github_api_reachable=github_reachable,
        github_user=github_user,
        registered_sources=source_names,
        python_version=platform.python_version(),
        platform=f"{platform.system()} {platform.release()}",
        hostname=platform.node(),
        working_directory=os.getcwd(),
        probed_at=time.time(),
    )

    return {
        "kind": "agent_web_browser_environment",
        "version": 1,
        "connectivity": {
            "has_internet": probe.has_internet,
            "has_proxy": probe.has_proxy,
            "proxy_endpoint": probe.proxy_url,
        },
        "github": {
            "authenticated": probe.has_github_token,
            "api_reachable": probe.github_api_reachable,
            "user": probe.github_user,
        },
        "sources": list(probe.registered_sources),
        "runtime": {
            "python": probe.python_version,
            "platform": probe.platform,
            "hostname": probe.hostname,
            "cwd": probe.working_directory,
        },
        "probed_at": probe.probed_at,
    }


# ---------------------------------------------------------------------------
# GAD-000 capability manifest — browser as a discoverable agent surface
# ---------------------------------------------------------------------------

def build_browser_capability_manifest(
    *,
    base_url: str = "",
    sources: list[PageSource] | None = None,
) -> dict:
    """Build a GAD-000-conformant capability manifest for the agent web browser.

    Follows the ``agent_web_semantic_capability_manifest`` pattern: typed
    capabilities, stable response subsets, versioned contracts, and
    discovery metadata.
    """
    source_names = [type(s).__name__ for s in (sources or [])]

    capabilities = [
        {
            "capability_id": "web_browse",
            "summary": "Fetch a URL and return structured, agent-readable page content.",
            "mode": "read_only",
            "contract_version": 1,
            "input_schema": {
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "use_cache": {"type": "boolean", "default": True},
                },
            },
            "stable_response_subset": {
                "top_level_fields": [
                    "url", "status_code", "title", "content_text",
                    "links", "forms", "meta", "ok", "error",
                ],
                "link_fields": ["href", "text", "rel", "index"],
                "form_fields": ["action", "method", "fields", "form_id", "index"],
                "meta_fields": [
                    "description", "keywords", "author", "canonical_url",
                    "og_title", "og_description",
                ],
            },
        },
        {
            "capability_id": "web_follow_link",
            "summary": "Follow a link on the current page by index or text search.",
            "mode": "read_only",
            "contract_version": 1,
            "input_schema": {
                "required": ["index_or_query"],
                "properties": {
                    "index_or_query": {
                        "type": ["integer", "string"],
                        "description": "Link index (int) or text/href search query (str)",
                    },
                },
            },
            "stable_response_subset": {
                "top_level_fields": [
                    "url", "status_code", "title", "content_text",
                    "links", "forms", "meta", "ok", "error",
                ],
            },
        },
        {
            "capability_id": "web_navigate",
            "summary": "Navigate back/forward in tab history.",
            "mode": "read_only",
            "contract_version": 1,
            "input_schema": {
                "required": ["direction"],
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["back", "forward", "refresh"],
                    },
                },
            },
        },
        {
            "capability_id": "web_search_links",
            "summary": "Search links on the current page by keyword.",
            "mode": "read_only",
            "contract_version": 1,
            "input_schema": {
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                },
            },
            "stable_response_subset": {
                "result_fields": ["href", "text", "rel", "index"],
            },
        },
        {
            "capability_id": "web_submit_form",
            "summary": "Submit a form on the current page with provided values.",
            "mode": "write",
            "contract_version": 1,
            "input_schema": {
                "required": ["index_or_id"],
                "properties": {
                    "index_or_id": {"type": ["integer", "string"]},
                    "values": {"type": "object", "description": "Field name → value overrides"},
                },
            },
        },
        {
            "capability_id": "web_environment",
            "summary": "Probe the runtime environment: connectivity, proxy, credentials, sources.",
            "mode": "read_only",
            "contract_version": 1,
            "input_schema": {"properties": {}},
            "stable_response_subset": {
                "top_level_fields": [
                    "connectivity", "github", "sources", "runtime", "probed_at",
                ],
            },
        },
        {
            "capability_id": "web_tab_management",
            "summary": "Create, switch, close, and list browser tabs.",
            "mode": "read_write",
            "contract_version": 1,
            "input_schema": {
                "required": ["action"],
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["new", "switch", "close", "list"],
                    },
                    "tab_id": {"type": "string"},
                    "label": {"type": "string"},
                },
            },
        },
    ]

    return {
        "kind": "agent_web_browser_capability_manifest",
        "version": 1,
        "standard_profile": {
            "profile_id": "agent_web_browser_standard.v1",
            "gad_conformance": "gad_000_plus",
            "source_system": "agent_internet",
            "provider_role": "public_web_transport_adapter",
            "consumer_roles": ["autonomous_agent", "orchestrator", "proxy_wrapper"],
        },
        "surface_kind": "agent_web_browser_surface",
        "consumer_model": "stateful_session",
        "federation_surface": {
            "surface_role": "public_web_transport_adapter",
            "canonical_for_public_federation": False,
            "transport_boundary": "Per ADR-0003: external protocols are transport, not substrate.",
        },
        "sources": {
            "registered": source_names,
            "available": ["GitHubBrowserSource", "custom PageSource implementations"],
        },
        "capabilities": capabilities,
        "non_goals": [
            "The browser does not execute JavaScript or render CSS.",
            "External web identity is not imported into the federation identity model.",
            "Page content is transport-level projection, not substrate truth.",
        ],
        "stats": {"capability_count": len(capabilities)},
    }


# ---------------------------------------------------------------------------
# Federation discovery — scan known peers for agent-federation.json
# ---------------------------------------------------------------------------

_FEDERATION_DESCRIPTOR_SEEDS = (
    "kimeisele/agent-internet",
    "kimeisele/steward-protocol",
    "kimeisele/agent-city",
    "kimeisele/agent-world",
    "kimeisele/steward",
)


def _discover_federation_descriptors(*, config: BrowserConfig | None = None) -> list[dict]:
    """Fetch .well-known/agent-federation.json from known federation peers.

    Used by ``about:federation`` to give agents a live map of the ecosystem.
    """
    cfg = config or BrowserConfig()
    descriptors: list[dict] = []

    # Also try loading local seeds
    try:
        from pathlib import Path
        seed_path = Path("data/federation/authority-descriptor-seeds.json")
        if seed_path.exists():
            seed_data = json.loads(seed_path.read_text())
            if isinstance(seed_data, list):
                for seed in seed_data:
                    url = seed.get("descriptor_url", "") if isinstance(seed, dict) else ""
                    if url and "/agent-federation.json" in url:
                        # Extract repo_id from URL
                        parts = url.split("githubusercontent.com/")
                        if len(parts) > 1:
                            repo_parts = parts[1].split("/")
                            if len(repo_parts) >= 2:
                                repo_id = f"{repo_parts[0]}/{repo_parts[1]}"
                                if repo_id not in _FEDERATION_DESCRIPTOR_SEEDS:
                                    _fetch_descriptor(url, repo_id, descriptors, cfg)
    except Exception:
        pass

    for repo_id in _FEDERATION_DESCRIPTOR_SEEDS:
        url = f"https://raw.githubusercontent.com/{repo_id}/main/.well-known/agent-federation.json"
        _fetch_descriptor(url, repo_id, descriptors, cfg)

    return descriptors


def _fetch_descriptor(url: str, repo_id: str, descriptors: list[dict], cfg: BrowserConfig) -> None:
    """Fetch a single federation descriptor and append to the list."""
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={"User-Agent": cfg.user_agent})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and data.get("kind") == "agent_federation_descriptor":
                data.setdefault("repo_id", repo_id)
                descriptors.append(data)
    except Exception:
        pass
