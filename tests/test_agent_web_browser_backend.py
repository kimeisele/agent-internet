"""Tests for browser ↔ backend integration.

Covers:
- about:graph page rendering
- about:search page rendering
- Auto-ingest pipeline (browse → index → search → browse)
- Semantic graph navigation via about:graph?node=...
"""

from __future__ import annotations

from agent_internet.agent_web_browser import (
    AgentWebBrowser,
    BrowserConfig,
    BrowserPage,
    PageLink,
    PageMeta,
)


def _fake_page(url: str, title: str = "Test", content: str = "test content") -> BrowserPage:
    """Create a minimal BrowserPage for testing."""
    import time
    return BrowserPage(
        url=url,
        status_code=200,
        title=title,
        content_text=content,
        links=(),
        forms=(),
        meta=PageMeta(description=content[:50]),
        headers={},
        fetched_at=time.time(),
        content_type="text/html",
        encoding="utf-8",
        raw_html=content,
        error="",
    )


# ---------------------------------------------------------------------------
# about:graph — empty state
# ---------------------------------------------------------------------------

def test_about_graph_empty():
    browser = AgentWebBrowser()
    page = browser.open("about:graph")
    assert page.ok
    assert "Knowledge Graph" in page.title
    assert "Nodes: 0" in page.content_text
    assert "browse some pages first" in page.content_text


def test_about_graph_links_to_search():
    browser = AgentWebBrowser()
    page = browser.open("about:graph")
    assert any(link.href == "about:search" for link in page.links)


# ---------------------------------------------------------------------------
# about:search — empty state
# ---------------------------------------------------------------------------

def test_about_search_landing():
    browser = AgentWebBrowser()
    page = browser.open("about:search")
    assert page.ok
    assert "Search" in page.title
    assert "about:search?q=" in page.content_text


def test_about_search_no_results():
    browser = AgentWebBrowser()
    page = browser.open("about:search?q=nonexistent")
    assert page.ok
    assert "no results" in page.content_text


def test_about_search_links_to_graph():
    browser = AgentWebBrowser()
    page = browser.open("about:search?q=test")
    assert any(link.href == "about:graph" for link in page.links)


# ---------------------------------------------------------------------------
# Auto-ingest pipeline
# ---------------------------------------------------------------------------

def test_auto_ingest_on_open(monkeypatch):
    """Browsing a page should auto-ingest it into the semantic index."""
    browser = AgentWebBrowser()

    # Patch _fetch to return a fake page
    fake = _fake_page("https://example.com", title="Example Site", content="Hello world from example")
    monkeypatch.setattr(AgentWebBrowser, "_fetch", lambda self, url: fake)

    browser.open("https://example.com")

    # The page should now be in the browsed index
    assert browser.browsed_index.page_count == 1
    assert browser.browsed_index.records[0]["title"] == "Example Site"


def test_auto_ingest_skips_about_pages():
    """about: pages should NOT be ingested into the semantic index."""
    browser = AgentWebBrowser()
    browser.open("about:environment")
    browser.open("about:graph")
    browser.open("about:search")
    assert browser.browsed_index.page_count == 0


def test_auto_ingest_skips_failed_pages(monkeypatch):
    """Failed pages (non-200) should not be ingested."""
    import time
    browser = AgentWebBrowser()
    fail_page = BrowserPage(
        url="https://fail.example.com", status_code=404,
        title="Not Found", content_text="", links=(), forms=(),
        meta=PageMeta(), headers={}, fetched_at=time.time(),
        content_type="text/html", encoding="utf-8", raw_html="",
        error="not_found",
    )
    monkeypatch.setattr(AgentWebBrowser, "_fetch", lambda self, url: fail_page)
    browser.open("https://fail.example.com")
    assert browser.browsed_index.page_count == 0


# ---------------------------------------------------------------------------
# Browse → Search loop
# ---------------------------------------------------------------------------

def _patched_fetch(pages):
    """Return a _fetch replacement that handles about: normally."""
    original_handle_about = AgentWebBrowser._handle_about

    def _fetch(self, url):
        if url.startswith("about:"):
            return original_handle_about(self, url)
        return pages.get(url, _fake_page(url))
    return _fetch


def test_browse_then_search(monkeypatch):
    """Full loop: browse pages → search finds them."""
    browser = AgentWebBrowser()

    pages = {
        "https://a.com": _fake_page("https://a.com", "Alpha Project", "Alpha is a Python framework for web apps"),
        "https://b.com": _fake_page("https://b.com", "Beta Library", "Beta provides REST API utilities"),
        "https://c.com": _fake_page("https://c.com", "Gamma Toolkit", "Gamma is for data processing and ETL"),
    }
    monkeypatch.setattr(AgentWebBrowser, "_fetch", _patched_fetch(pages))

    # Browse
    for url in pages:
        browser.open(url)

    assert browser.browsed_index.page_count == 3

    # Search via about:search
    page = browser.open("about:search?q=Python+framework")
    assert page.ok
    assert "Alpha" in page.content_text
    assert len(page.links) > 0


def test_browse_then_search_finds_specific(monkeypatch):
    """Search should rank relevant results higher."""
    browser = AgentWebBrowser()
    pages = {
        "https://a.com": _fake_page("https://a.com", "REST API Guide", "Building REST APIs with Python"),
        "https://b.com": _fake_page("https://b.com", "Cat Pictures", "Cute cats from the internet"),
    }
    monkeypatch.setattr(AgentWebBrowser, "_fetch", lambda self, url: pages.get(url, _fake_page(url)))
    for url in pages:
        browser.open(url)

    page = browser.open("about:search?q=REST+API")
    assert page.ok
    # REST API Guide should appear before Cat Pictures
    rest_pos = page.content_text.find("REST API Guide")
    cat_pos = page.content_text.find("Cat Pictures")
    if rest_pos >= 0 and cat_pos >= 0:
        assert rest_pos < cat_pos


# ---------------------------------------------------------------------------
# about:graph with data
# ---------------------------------------------------------------------------

def test_graph_with_browsed_pages(monkeypatch):
    """Graph should show nodes after browsing."""
    browser = AgentWebBrowser()
    pages = {
        "https://a.com": _fake_page("https://a.com", "Project Alpha", "A framework for agents"),
        "https://b.com": _fake_page("https://b.com", "Project Beta", "Another framework for agents"),
    }
    monkeypatch.setattr(AgentWebBrowser, "_fetch", _patched_fetch(pages))
    for url in pages:
        browser.open(url)

    page = browser.open("about:graph")
    assert page.ok
    assert "Project Alpha" in page.content_text
    assert "Project Beta" in page.content_text


def test_graph_query_filter(monkeypatch):
    """about:graph?query=X should filter nodes."""
    browser = AgentWebBrowser()
    pages = {
        "https://a.com": _fake_page("https://a.com", "Python Framework", "Python web framework"),
        "https://b.com": _fake_page("https://b.com", "Rust Toolkit", "Rust system programming"),
    }
    monkeypatch.setattr(AgentWebBrowser, "_fetch", _patched_fetch(pages))
    for url in pages:
        browser.open(url)

    page = browser.open("about:graph?query=Python")
    assert page.ok
    assert "Python Framework" in page.content_text
    # Rust Toolkit should be filtered out
    assert "Rust Toolkit" not in page.content_text


def test_graph_node_detail(monkeypatch):
    """about:graph?node=ID should show node details."""
    browser = AgentWebBrowser()
    pages = {"https://a.com": _fake_page("https://a.com", "Test Page", "Test content for node detail view")}
    monkeypatch.setattr(AgentWebBrowser, "_fetch", _patched_fetch(pages))
    browser.open("https://a.com")

    # Get the record ID
    record = browser.browsed_index.records[0]
    rid = record["record_id"]

    page = browser.open(f"about:graph?node={rid}")
    assert page.ok
    assert "Test Page" in page.content_text
    assert rid in page.content_text


def test_graph_node_not_found():
    """about:graph?node=INVALID should 404."""
    browser = AgentWebBrowser()
    page = browser.open("about:graph?node=nonexistent_id")
    assert not page.ok
    assert "node_not_found" in page.error


# ---------------------------------------------------------------------------
# Cross-page navigation
# ---------------------------------------------------------------------------

def test_environment_links_to_graph_and_search():
    """about:environment should link to graph and search."""
    browser = AgentWebBrowser()
    page = browser.open("about:environment")
    assert any(link.href == "about:graph" for link in page.links)
    assert any(link.href == "about:search" for link in page.links)


def test_graph_links_are_browsable():
    """Links from about:graph should be valid about: URLs."""
    browser = AgentWebBrowser()
    page = browser.open("about:graph")
    for link in page.links:
        if link.href.startswith("about:"):
            linked_page = browser.open(link.href)
            assert linked_page.ok, f"Broken link: {link.href}"
