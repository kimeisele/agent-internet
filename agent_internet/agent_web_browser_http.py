"""HTTP fetcher and agent-native content discovery for the Agent Web Browser.

Handles URL fetching (stdlib ``urllib``), JSON rendering, encoding detection,
llms.txt parsing, and the llms.txt / agents.json discovery helpers.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .agent_web_browser import (
    BrowserConfig,
    BrowserPage,
    PageLink,
    PageMeta,
    _make_page,
)
from .agent_web_browser_parser import parse_html

logger = logging.getLogger("AGENT_INTERNET.WEB_BROWSER.HTTP")


# ---------------------------------------------------------------------------
# Encoding detection
# ---------------------------------------------------------------------------

def _detect_encoding(headers: dict[str, str], body: bytes) -> str:
    """Best-effort encoding detection from Content-Type header or BOM."""
    ct = headers.get("content-type", "")
    if "charset=" in ct.lower():
        for part in ct.split(";"):
            if "charset=" in part.lower():
                return part.split("=", 1)[1].strip().strip('"')
    if body[:3] == b"\xef\xbb\xbf":
        return "utf-8"
    return "utf-8"


# ---------------------------------------------------------------------------
# URL fetcher
# ---------------------------------------------------------------------------

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
    ``HTTPS_PROXY`` environment variables.  Returns an error page (with
    ``error`` set) on network failures rather than raising.
    """
    cfg = config or BrowserConfig()

    if not url or not url.strip():
        return _make_page(url, status=0, error="empty_url")
    if not url.startswith(("http://", "https://")):
        scheme = url.split(":")[0] if ":" in url else "none"
        return _make_page(url, status=0, error=f"unsupported_scheme:{scheme}")

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
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return _make_page(url, status=0, error=f"{type(exc).__name__}: {exc}")

    encoding = _detect_encoding(resp_headers, raw_body)
    try:
        decoded = raw_body.decode(encoding, errors="replace")
    except (LookupError, UnicodeDecodeError):
        decoded = raw_body.decode("utf-8", errors="replace")

    content_type = resp_headers.get("content-type", "text/html")

    if "application/json" in content_type:
        return _json_page(final_url, status, decoded, resp_headers, content_type)

    if "text/plain" in content_type:
        return _make_page(
            final_url, status=status,
            title=final_url.split("/")[-1] or final_url,
            content=decoded.strip(),
            headers=resp_headers, content_type=content_type,
            encoding=encoding, raw_html=decoded,
        )

    title, content_text, links, forms, meta = parse_html(decoded, final_url)
    return _make_page(
        final_url, status=status, title=title, content=content_text,
        links=links, forms=forms, meta=meta, headers=resp_headers,
        content_type=content_type, encoding=encoding, raw_html=decoded,
    )


# ---------------------------------------------------------------------------
# JSON page rendering
# ---------------------------------------------------------------------------

def _json_page(
    url: str, status: int, body: str, headers: dict[str, str], content_type: str,
) -> BrowserPage:
    """Render a JSON response as a readable BrowserPage."""
    try:
        data = json.loads(body)
        formatted = json.dumps(data, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        formatted = body
        data = {}

    links: list[PageLink] = []
    if isinstance(data, (dict, list)):
        _extract_json_links(data, links, base_url=url)

    return _make_page(
        url, status=status,
        title=f"JSON: {url.split('/')[-1] or url}",
        content=formatted, links=tuple(links),
        headers=headers, content_type=content_type,
        encoding="utf-8", raw_html=body,
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
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                links.append(PageLink(href=value, text=str(key), index=len(links)))
            elif isinstance(value, (dict, list)):
                _extract_json_links(value, links, base_url=base_url, depth=depth + 1)
    elif isinstance(data, list):
        for item in data[:50]:
            if isinstance(item, (dict, list)):
                _extract_json_links(item, links, base_url=base_url, depth=depth + 1)


# ---------------------------------------------------------------------------
# llms.txt parser — agent-native content discovery
# ---------------------------------------------------------------------------

_LLMS_TXT_LINK_RE = re.compile(r"^\s*-\s*\[([^\]]+)\]\(([^)]+)\)\s*(?::\s*(.*))?$")


def _parse_llms_txt(content: str, base_url: str) -> dict:
    """Parse an llms.txt file per the spec at https://llmstxt.org/.

    Structure:
      - H1: project/site name (required)
      - Blockquote: short summary
      - Body paragraphs: description
      - H2 sections: file lists (``- [name](url): notes``)
      - H2 "Optional": lower-priority URLs
    """
    lines = content.strip().split("\n")
    title = ""
    summary = ""
    description_parts: list[str] = []
    sections: dict[str, list[dict]] = {}
    current_section: str = ""

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("# ") and not stripped.startswith("## "):
            title = stripped[2:].strip()
            continue

        if stripped.startswith("> ") and not summary:
            summary = stripped[2:].strip()
            continue

        if stripped.startswith("## "):
            current_section = stripped[3:].strip()
            if current_section not in sections:
                sections[current_section] = []
            continue

        if current_section:
            match = _LLMS_TXT_LINK_RE.match(line)
            if match:
                name, url, notes = match.group(1), match.group(2), match.group(3) or ""
                if not url.startswith(("http://", "https://")):
                    url = f"{base_url.rstrip('/')}/{url.lstrip('/')}"
                sections[current_section].append({"name": name, "url": url, "notes": notes.strip()})
                continue

        if not current_section and stripped and not stripped.startswith("#"):
            description_parts.append(stripped)

    return {
        "title": title or "Unknown",
        "summary": summary,
        "description": "\n".join(description_parts),
        "sections": sections,
        "keywords": [],
    }


# ---------------------------------------------------------------------------
# llms.txt + agents.json discovery helpers (called by AgentWebBrowser)
# ---------------------------------------------------------------------------

def try_llms_txt(
    url: str,
    *,
    config: BrowserConfig,
    cache: dict[str, dict | None],
) -> BrowserPage | None:
    """Check if the domain serves /llms.txt — curated content for agents.

    Per the llms.txt spec: sites can provide a Markdown file at /llms.txt with
    structured, agent-optimized content.  If found, we return it instead of
    scraping HTML (strangler fig pattern).
    """
    parsed = urlparse(url)
    domain_root = f"{parsed.scheme}://{parsed.netloc}"
    llms_url = f"{domain_root}/llms.txt"

    if llms_url in cache:
        cached = cache[llms_url]
        if cached is None:
            return None
        return render_llms_txt(url, cached)

    try:
        req = urllib.request.Request(
            llms_url,
            headers={"User-Agent": config.user_agent, "Accept": "text/plain,text/markdown"},
        )
        with urllib.request.urlopen(req, timeout=config.llms_txt_timeout) as resp:
            if resp.status == 200:
                body = resp.read(config.max_response_bytes).decode("utf-8", errors="replace")
                if body.strip() and body.strip().startswith("#"):
                    parsed_data = _parse_llms_txt(body, domain_root)
                    cache[llms_url] = parsed_data
                    logger.info("llms.txt found for %s", parsed.netloc)
                    return render_llms_txt(url, parsed_data)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("llms.txt fetch failed for %s: %s", parsed.netloc, exc)

    cache[llms_url] = None
    return None


def render_llms_txt(original_url: str, data: dict) -> BrowserPage:
    """Render parsed llms.txt data as a BrowserPage."""
    text_parts = [f"# {data['title']}"]
    if data.get("summary"):
        text_parts.append(f"> {data['summary']}")
    text_parts.append("")
    if data.get("description"):
        text_parts.append(data["description"])
        text_parts.append("")

    links: list[PageLink] = []
    for section_name, items in data.get("sections", {}).items():
        text_parts.append(f"## {section_name}")
        for item in items:
            text_parts.append(f"  [{item['name']}]({item['url']})")
            if item.get("notes"):
                text_parts.append(f"    {item['notes']}")
            links.append(PageLink(href=item["url"], text=item["name"], index=len(links)))
        text_parts.append("")

    text_parts.append("")
    text_parts.append("[source: llms.txt — agent-optimized content]")

    return _make_page(
        original_url, status=200, title=data["title"],
        content="\n".join(text_parts), links=tuple(links),
        meta=PageMeta(
            description=data.get("summary", ""),
            keywords=tuple(data.get("keywords", ())),
        ),
        headers={"x-content-source": "llms.txt"},
        content_type="text/markdown",
    )


def enrich_with_agents_json(
    url: str,
    page: BrowserPage,
    *,
    config: BrowserConfig,
    cache: dict[str, dict | None],
) -> BrowserPage:
    """Check /.well-known/agents.json and enrich page metadata if found."""
    parsed = urlparse(url)
    domain_root = f"{parsed.scheme}://{parsed.netloc}"
    agents_url = f"{domain_root}/.well-known/agents.json"

    if agents_url in cache:
        cached = cache[agents_url]
        if cached is None:
            return page
        return _apply_agents_json(page, cached)

    try:
        req = urllib.request.Request(
            agents_url,
            headers={"User-Agent": config.user_agent, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=config.agents_json_timeout) as resp:
            if resp.status == 200:
                body = resp.read(config.max_response_bytes).decode("utf-8", errors="replace")
                data = json.loads(body)
                if isinstance(data, dict):
                    cache[agents_url] = data
                    logger.info("agents.json found for %s", parsed.netloc)
                    return _apply_agents_json(page, data)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.debug("agents.json fetch failed for %s: %s", parsed.netloc, exc)

    cache[agents_url] = None
    return page


def _apply_agents_json(page: BrowserPage, agents_data: dict) -> BrowserPage:
    """Enrich a page's metadata with agents.json capabilities info."""
    extra = dict(page.meta.extra)
    extra["agents_json"] = json.dumps(agents_data, default=str)[:2000]

    caps = agents_data.get("capabilities", [])
    if isinstance(caps, list):
        extra["agent_capabilities"] = ", ".join(str(c) for c in caps[:10])

    new_meta = PageMeta(
        charset=page.meta.charset,
        description=page.meta.description,
        keywords=page.meta.keywords,
        author=page.meta.author,
        robots=page.meta.robots,
        og_title=page.meta.og_title,
        og_description=page.meta.og_description,
        og_image=page.meta.og_image,
        og_url=page.meta.og_url,
        canonical_url=page.meta.canonical_url,
        extra=extra,
    )
    return _make_page(
        page.url, status=page.status_code, title=page.title,
        content=page.content_text, links=page.links, forms=page.forms,
        meta=new_meta, headers=page.headers, content_type=page.content_type,
        encoding=page.encoding, raw_html=page.raw_html,
    )
