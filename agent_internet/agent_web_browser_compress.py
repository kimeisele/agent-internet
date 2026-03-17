"""CBR-inspired content compression for the Agent Web Browser.

Strips navigation chrome, deduplicates, and truncates to fit a token budget.
Inspired by steward's Constant Bitrate signal chain.
"""

from __future__ import annotations

import re

from .agent_web_browser import BrowserPage, PageLink, _make_page

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
    page: BrowserPage,
    *,
    token_budget: int = 1024,
    link_budget: int = 20,
    keep_meta: bool = True,
) -> BrowserPage:
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
        if _NAV_PATTERNS.match(stripped):
            continue
        if len(stripped) <= _SHORT_NAV_LEN and stripped.lower() in seen:
            continue
        norm = stripped.lower()
        if norm in seen and len(stripped) < 80:
            continue
        seen.add(norm)
        filtered.append(stripped)

    # Stage 2: Collapse to text
    text = "\n".join(filtered).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Stage 3: Token-budget truncation
    if _estimate_tokens(text) > token_budget:
        target_chars = token_budget * 4
        if len(text) > target_chars:
            cut = text[:target_chars]
            last_para = cut.rfind("\n\n")
            if last_para > target_chars // 2:
                text = cut[:last_para]
            else:
                last_dot = cut.rfind(". ")
                if last_dot > target_chars // 2:
                    text = cut[: last_dot + 1]
                else:
                    text = cut + "…"

    # Stage 4: Compress links — keep most relevant
    links = page.links
    if link_budget > 0 and len(links) > link_budget:
        scored: list[tuple[float, PageLink]] = []
        seen_hrefs: set[str] = set()
        page_domain = page.url.split("/")[2] if "/" in page.url else ""
        for link in links:
            if link.href in seen_hrefs or not link.text.strip():
                continue
            seen_hrefs.add(link.href)
            text_clean = " ".join(link.text.split()).strip()
            score = len(text_clean)
            link_domain = link.href.split("/")[2] if link.href.startswith("http") and "/" in link.href else ""
            if link_domain == page_domain:
                score += 15
            tl = text_clean.lower()
            if any(kw in tl for kw in ("article", "doc", "guide", "section", "chapter", "readme", "overview")):
                score += 20
            if any(kw in tl for kw in ("sponsor", "advertis", "cookie", "privacy", "terms")):
                score -= 50
            if any(ad in link.href for ad in ("careers.", "ads.", "sponsor", "utm_")):
                score -= 30
            scored.append((score, link))
        scored.sort(key=lambda x: x[0], reverse=True)
        kept = [lnk for _, lnk in scored[:link_budget]]
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

    return _make_page(
        page.url,
        status=page.status_code,
        title=page.title,
        content=text,
        links=links,
        forms=page.forms,
        meta=page.meta,
        headers=page.headers,
        content_type=page.content_type,
        encoding=page.encoding,
        raw_html=page.raw_html,
    )
