#!/usr/bin/env python3
"""Live demo — Agent Web Browser in 30 seconds.

No Chromium. No Playwright. No external dependencies. Pure Python.

Starts a browser, discovers the federation, reads every peer repo,
searches across everything it learned, and navigates the knowledge graph.

Usage:
    python scripts/demo_browser.py
"""

from __future__ import annotations

import sys
import time

# ---------------------------------------------------------------------------
# Pretty output helpers
# ---------------------------------------------------------------------------

_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"


def _step(n: int, label: str) -> None:
    print(f"\n{_BOLD}{_CYAN}[{n}/7]{_RESET} {_BOLD}{label}{_RESET}")


def _ok(msg: str) -> None:
    print(f"  {_GREEN}OK{_RESET}  {msg}")


def _info(msg: str) -> None:
    print(f"  {_DIM}..{_RESET}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}!!{_RESET}  {msg}")


def _fail(msg: str) -> None:
    print(f"  {_RED}FAIL{_RESET}  {msg}")


def _page_line(page) -> str:  # type: ignore[override]
    """One-line summary of a BrowserPage."""
    status = f"{page.status_code}"
    title = page.title[:60] if page.title else "(no title)"
    links = f"{len(page.links)} links"
    chars = f"{len(page.content_text):,} chars"
    return f"[{status}] {title}  ({links}, {chars})"


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

def main() -> None:
    t0 = time.monotonic()

    print(f"{_BOLD}{'=' * 60}{_RESET}")
    print(f"{_BOLD}  Agent Web Browser — Live Demo{_RESET}")
    print(f"{_BOLD}  Pure Python. Zero external dependencies.{_RESET}")
    print(f"{_BOLD}{'=' * 60}{_RESET}")

    # ------------------------------------------------------------------
    # Step 1: Start browser with GitHub source
    # ------------------------------------------------------------------
    _step(1, "Starting browser with GitHub API source")

    from agent_internet.agent_web_browser_github import create_github_browser

    browser, gh_source = create_github_browser()
    auth = "authenticated" if gh_source.authenticated else "unauthenticated"
    _ok(f"Browser ready ({auth})")

    # ------------------------------------------------------------------
    # Step 2: Probe environment
    # ------------------------------------------------------------------
    _step(2, "Probing environment — about:environment")

    env_page = browser.open("about:environment")
    if env_page.ok:
        # Extract key lines
        for line in env_page.content_text.splitlines():
            line = line.strip()
            if line.startswith("Internet:"):
                _ok(f"Connectivity: {line}")
            elif line.startswith("Authenticated:"):
                _ok(f"GitHub: {line}")
            elif line.startswith("User:"):
                _info(f"GitHub user: {line.split(':', 1)[1].strip()}")
    else:
        _fail("Environment probe failed")

    # ------------------------------------------------------------------
    # Step 3: Discover federation — about:federation
    # ------------------------------------------------------------------
    _step(3, "Discovering federation peers — about:federation")

    fed_page = browser.open("about:federation")
    if fed_page.ok:
        peer_links = [l for l in fed_page.links if l.href.startswith("https://github.com/")]
        peer_count = len(peer_links)
        _ok(f"Found {peer_count} federation peers")
        for pl in peer_links:
            _info(pl.text)
    else:
        _fail("Federation discovery failed")
        peer_links = []

    # ------------------------------------------------------------------
    # Step 4: Browse every peer repo (auto-ingest)
    # ------------------------------------------------------------------
    _step(4, "Reading peer repos (auto-ingest into semantic index)")

    pages_read = 0
    pages_failed = 0

    for link in peer_links:
        try:
            page = browser.open(link.href)
            if page.ok:
                _ok(_page_line(page))
                pages_read += 1
            else:
                _warn(f"[{page.status_code}] {link.text}: {page.error}")
                pages_failed += 1
        except Exception as exc:
            _fail(f"{link.text}: {exc}")
            pages_failed += 1

    _info(f"Read {pages_read} repos, {pages_failed} failed")
    _info(f"Semantic index: {browser.browsed_index.page_count} pages indexed")

    # ------------------------------------------------------------------
    # Step 5: Check wikis
    # ------------------------------------------------------------------
    _step(5, "Checking peer wikis")

    wikis_with_content = 0
    for link in peer_links:
        wiki_url = link.href + "/wiki"
        try:
            wiki_page = browser.open(wiki_url)
            if wiki_page.ok and "could not list" not in wiki_page.content_text:
                _ok(f"{link.text}: wiki has content")
                wikis_with_content += 1
                # Try to follow wiki links and ingest
                for wl in wiki_page.links:
                    if "/wiki/" in wl.href and wl.href != wiki_url:
                        try:
                            wp = browser.open(wl.href)
                            if wp.ok:
                                _info(f"  Read wiki page: {wp.title[:50]}")
                        except Exception:
                            pass
            else:
                _info(f"{link.text}: wiki empty or disabled")
        except Exception:
            _info(f"{link.text}: wiki unavailable")

    if wikis_with_content == 0:
        _info("No wikis with content found (repos have READMEs instead)")

    # ------------------------------------------------------------------
    # Step 6: Search the index
    # ------------------------------------------------------------------
    _step(6, "Searching — about:search?q=federation+routing")

    search_page = browser.open("about:search?q=federation+routing")
    if search_page.ok:
        for line in search_page.content_text.splitlines():
            line = line.strip()
            if line.startswith("Source:"):
                _info(line)
            elif line.startswith("Results:"):
                _ok(line)
            elif line and line[0].isdigit() and "]" in line:
                # Result line like "1. [5.000] title"
                _info(f"  {line.strip()}")
        # Show searchable links
        result_links = [l for l in search_page.links
                        if l.href.startswith("https://")]
        if result_links:
            _ok(f"Top result: {result_links[0].text}")
    else:
        _fail("Search failed")
        result_links = []

    # ------------------------------------------------------------------
    # Step 7: Follow top result + show graph
    # ------------------------------------------------------------------
    _step(7, "Knowledge graph — about:graph")

    graph_page = browser.open("about:graph")
    if graph_page.ok:
        for line in graph_page.content_text.splitlines():
            line = line.strip()
            if line.startswith("Nodes:"):
                _ok(line)
            elif line.startswith("[web_page]"):
                _info(f"  {line}")
    else:
        _fail("Graph unavailable")

    # Follow top search result if available
    if result_links:
        _info(f"Following top result: {result_links[0].href}")
        follow_page = browser.open(result_links[0].href)
        if follow_page.ok:
            _ok(_page_line(follow_page))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    elapsed = time.monotonic() - t0

    print(f"\n{_BOLD}{'=' * 60}{_RESET}")
    print(f"{_BOLD}  Summary{_RESET}")
    print(f"{_BOLD}{'=' * 60}{_RESET}")
    print(f"  Pages read:       {browser.browsed_index.page_count}")

    graph = browser.browsed_index.build_semantic_graph()
    stats = graph.get("stats", {})
    print(f"  Graph nodes:      {stats.get('node_count', 0)}")
    print(f"  Graph edges:      {stats.get('edge_count', 0)}")
    print(f"  Connected nodes:  {stats.get('connected_record_count', 0)}")
    print(f"  Federation peers: {len(peer_links)}")
    print(f"  Time:             {elapsed:.1f}s")
    print(f"  External deps:    0")
    print(f"  Browser engine:   Python stdlib (urllib + html.parser)")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        sys.exit(1)
    except Exception as exc:
        print(f"\n{_RED}Fatal: {exc}{_RESET}", file=sys.stderr)
        sys.exit(1)
