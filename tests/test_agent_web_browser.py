"""Tests for agent_web_browser — core HTML parser, models, and browser session."""

from __future__ import annotations

import pytest

from agent_internet.agent_web_browser import (
    AgentWebBrowser,
    BrowserConfig,
    BrowserPage,
    BrowserTab,
    EnvironmentProbe,
    FormField,
    PageForm,
    PageLink,
    PageMeta,
    _clean_text,
    build_browser_capability_manifest,
    parse_html,
    probe_environment,
)


# ---------------------------------------------------------------------------
# HTML parser tests
# ---------------------------------------------------------------------------

SIMPLE_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <title>Test Page</title>
  <meta name="description" content="A test page for agents">
  <meta name="keywords" content="test, agent, browser">
  <meta property="og:title" content="OG Test Page">
  <link rel="canonical" href="https://example.com/canonical">
</head>
<body>
  <h1>Hello World</h1>
  <p>This is a <a href="/about">link to about</a> page.</p>
  <p>And <a href="https://external.com/page" rel="nofollow">an external link</a>.</p>
  <form id="search" action="/search" method="GET">
    <input type="text" name="q" required>
    <input type="submit" value="Search">
  </form>
  <img alt="logo" src="/logo.png">
</body>
</html>"""


def test_parse_html_extracts_title():
    title, _, _, _, _ = parse_html(SIMPLE_HTML, "https://example.com/")
    assert title == "Test Page"


def test_parse_html_extracts_text():
    _, text, _, _, _ = parse_html(SIMPLE_HTML, "https://example.com/")
    assert "Hello World" in text
    assert "This is a" in text
    assert "link to about" in text


def test_parse_html_extracts_links():
    _, _, links, _, _ = parse_html(SIMPLE_HTML, "https://example.com/")
    assert len(links) == 2
    assert links[0].href == "https://example.com/about"
    assert links[0].text == "link to about"
    assert links[1].href == "https://external.com/page"
    assert links[1].rel == "nofollow"


def test_parse_html_extracts_forms():
    _, _, _, forms, _ = parse_html(SIMPLE_HTML, "https://example.com/")
    assert len(forms) == 1
    form = forms[0]
    assert form.action == "https://example.com/search"
    assert form.method == "GET"
    assert form.form_id == "search"
    assert len(form.fields) == 2
    assert form.fields[0].name == "q"
    assert form.fields[0].required is True


def test_parse_html_extracts_meta():
    _, _, _, _, meta = parse_html(SIMPLE_HTML, "https://example.com/")
    assert meta.description == "A test page for agents"
    assert meta.keywords == ("test", "agent", "browser")
    assert meta.og_title == "OG Test Page"
    assert meta.canonical_url == "https://example.com/canonical"


def test_parse_html_extracts_image_alt():
    _, text, _, _, _ = parse_html(SIMPLE_HTML, "https://example.com/")
    assert "[image: logo]" in text


def test_parse_html_skips_script_and_style():
    html_with_scripts = """\
    <html><body>
    <p>Visible text</p>
    <script>alert('hidden');</script>
    <style>.hidden { display: none; }</style>
    <p>Also visible</p>
    </body></html>"""
    _, text, _, _, _ = parse_html(html_with_scripts, "https://example.com/")
    assert "Visible text" in text
    assert "Also visible" in text
    assert "alert" not in text
    assert "display" not in text


def test_parse_html_resolves_relative_urls():
    html = '<html><body><a href="../other">link</a></body></html>'
    _, _, links, _, _ = parse_html(html, "https://example.com/path/page")
    assert links[0].href == "https://example.com/other"


def test_parse_html_handles_empty_html():
    title, text, links, forms, meta = parse_html("", "https://example.com/")
    assert title == ""
    assert text == ""
    assert links == ()
    assert forms == ()


def test_parse_html_handles_malformed_html():
    html = "<html><body><p>Unclosed paragraph<div>Nested<a href='/x'>link</a>"
    title, text, links, _, _ = parse_html(html, "https://example.com/")
    assert "Unclosed paragraph" in text
    assert len(links) == 1
    assert links[0].href == "https://example.com/x"


def test_parse_html_textarea_and_select_in_form():
    html = """\
    <form action="/submit" method="POST">
      <textarea name="body"></textarea>
      <select name="category"></select>
      <input type="hidden" name="token" value="abc123">
    </form>"""
    _, _, _, forms, _ = parse_html(html, "https://example.com/")
    assert len(forms) == 1
    fields = forms[0].fields
    assert len(fields) == 3
    assert fields[0].field_type == "textarea"
    assert fields[1].field_type == "select"
    assert fields[2].field_type == "hidden"
    assert fields[2].value == "abc123"


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

def test_clean_text_collapses_whitespace():
    assert _clean_text("  hello   world  ") == "hello world"


def test_clean_text_preserves_paragraph_breaks():
    result = _clean_text("first\n\nsecond")
    assert "first" in result
    assert "second" in result


def test_clean_text_collapses_many_newlines():
    result = _clean_text("a\n\n\n\n\nb")
    assert result.count("\n") <= 2


# ---------------------------------------------------------------------------
# BrowserPage model
# ---------------------------------------------------------------------------

def _make_page(**overrides) -> BrowserPage:
    defaults = dict(
        url="https://example.com",
        status_code=200,
        title="Test",
        content_text="Hello",
        links=(PageLink(href="https://example.com/a", text="A", index=0),),
        forms=(),
        meta=PageMeta(),
    )
    defaults.update(overrides)
    return BrowserPage(**defaults)


def test_browser_page_ok():
    assert _make_page().ok is True
    assert _make_page(status_code=404).ok is False
    assert _make_page(error="timeout").ok is False


def test_browser_page_find_links():
    page = _make_page(links=(
        PageLink(href="https://example.com/about", text="About Us", index=0),
        PageLink(href="https://example.com/contact", text="Contact", index=1),
        PageLink(href="https://example.com/blog", text="Blog", index=2),
    ))
    assert len(page.find_links("about")) == 1
    assert page.find_links("about")[0].text == "About Us"
    assert len(page.find_links("example")) == 3
    assert len(page.find_links("nonexistent")) == 0


def test_browser_page_summary():
    page = _make_page(meta=PageMeta(description="test desc"))
    s = page.summary()
    assert s["url"] == "https://example.com"
    assert s["title"] == "Test"
    assert s["ok"] is True
    assert s["meta_description"] == "test desc"


# ---------------------------------------------------------------------------
# BrowserTab model
# ---------------------------------------------------------------------------

def test_browser_tab_history():
    tab = BrowserTab(tab_id="t1")
    assert not tab.can_go_back
    assert not tab.can_go_forward

    tab.push_url("https://a.com")
    assert tab.current_url == "https://a.com"
    assert not tab.can_go_back

    tab.push_url("https://b.com")
    assert tab.current_url == "https://b.com"
    assert tab.can_go_back

    tab.cursor -= 1
    assert tab.current_url == "https://a.com"
    assert tab.can_go_forward


def test_browser_tab_push_trims_forward_history():
    tab = BrowserTab(tab_id="t1")
    tab.push_url("https://a.com")
    tab.push_url("https://b.com")
    tab.push_url("https://c.com")

    # Go back to b
    tab.cursor -= 1
    assert tab.current_url == "https://b.com"

    # Navigate to d — should remove c from history
    tab.push_url("https://d.com")
    assert tab.current_url == "https://d.com"
    assert len(tab.history) == 3  # a, b, d
    assert not tab.can_go_forward


# ---------------------------------------------------------------------------
# Fake PageSource for testing
# ---------------------------------------------------------------------------

class _FakeSource:
    """Fake PageSource that returns canned pages for specific domains."""

    def __init__(self, pages: dict[str, BrowserPage]) -> None:
        self._pages = pages

    def can_handle(self, url: str) -> bool:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        return any(host in urlparse(key).hostname for key in self._pages if urlparse(key).hostname)

    def fetch(self, url: str, *, config: BrowserConfig) -> BrowserPage:
        return self._pages.get(url, _make_page(url=url, status_code=404, title="Not Found"))


# ---------------------------------------------------------------------------
# AgentWebBrowser tests
# ---------------------------------------------------------------------------

def test_browser_default_tab():
    browser = AgentWebBrowser()
    tabs = browser.list_tabs()
    assert len(tabs) == 1
    assert tabs[0]["active"] is True
    assert tabs[0]["label"] == "main"


def test_browser_new_tab_and_switch():
    browser = AgentWebBrowser()
    original_tab = browser.active_tab.tab_id
    new_id = browser.new_tab(label="research")
    assert browser.active_tab.tab_id == new_id
    assert len(browser.list_tabs()) == 2

    browser.switch_tab(original_tab)
    assert browser.active_tab.tab_id == original_tab


def test_browser_close_tab():
    browser = AgentWebBrowser()
    t2 = browser.new_tab()
    assert len(browser.list_tabs()) == 2
    browser.close_tab(t2)
    assert len(browser.list_tabs()) == 1


def test_browser_cannot_close_last_tab():
    browser = AgentWebBrowser()
    with pytest.raises(ValueError, match="cannot_close_last_tab"):
        browser.close_tab()


def test_browser_open_with_fake_source():
    fake_page = _make_page(
        url="https://fake.test/page",
        title="Fake Page",
        content_text="Hello from fake source",
    )
    source = _FakeSource({"https://fake.test/page": fake_page})

    browser = AgentWebBrowser()
    browser.register_source(source)
    page = browser.open("https://fake.test/page")

    assert page.title == "Fake Page"
    assert page.content_text == "Hello from fake source"
    assert browser.active_tab.current_url == "https://fake.test/page"


def test_browser_follow_link_by_index():
    target = _make_page(url="https://fake.test/about", title="About")
    main = _make_page(
        url="https://fake.test/",
        title="Home",
        links=(PageLink(href="https://fake.test/about", text="About", index=0),),
    )

    source = _FakeSource({
        "https://fake.test/": main,
        "https://fake.test/about": target,
    })

    browser = AgentWebBrowser()
    browser.register_source(source)
    browser.open("https://fake.test/")
    page = browser.follow_link(0)
    assert page.title == "About"


def test_browser_follow_link_by_query():
    target = _make_page(url="https://fake.test/docs", title="Docs")
    main = _make_page(
        url="https://fake.test/",
        links=(
            PageLink(href="https://fake.test/about", text="About Us", index=0),
            PageLink(href="https://fake.test/docs", text="Documentation", index=1),
        ),
    )

    source = _FakeSource({
        "https://fake.test/": main,
        "https://fake.test/docs": target,
    })

    browser = AgentWebBrowser()
    browser.register_source(source)
    browser.open("https://fake.test/")
    page = browser.follow_link("doc")
    assert page.title == "Docs"


def test_browser_follow_link_raises_on_no_match():
    browser = AgentWebBrowser()
    browser.register_source(_FakeSource({
        "https://fake.test/": _make_page(url="https://fake.test/", links=()),
    }))
    browser.open("https://fake.test/")

    with pytest.raises(ValueError, match="no_link_matching"):
        browser.follow_link("nonexistent")


def test_browser_back_and_forward():
    pages = {
        "https://fake.test/a": _make_page(url="https://fake.test/a", title="A"),
        "https://fake.test/b": _make_page(url="https://fake.test/b", title="B"),
    }
    browser = AgentWebBrowser()
    browser.register_source(_FakeSource(pages))

    browser.open("https://fake.test/a")
    browser.open("https://fake.test/b")

    page = browser.back()
    assert page is not None
    assert page.title == "A"

    page = browser.forward()
    assert page is not None
    assert page.title == "B"

    # Can't go further forward
    assert browser.forward() is None


def test_browser_back_returns_none_at_start():
    browser = AgentWebBrowser()
    assert browser.back() is None


def test_browser_get_text_and_links():
    page = _make_page(
        url="https://fake.test/",
        content_text="Test content here",
        links=(
            PageLink(href="https://fake.test/a", text="Link A", index=0),
            PageLink(href="https://fake.test/b", text="Link B", index=1),
        ),
    )
    browser = AgentWebBrowser()
    browser.register_source(_FakeSource({"https://fake.test/": page}))
    browser.open("https://fake.test/")

    assert browser.get_text() == "Test content here"
    assert browser.get_text(max_length=4) == "Test"
    links = browser.get_links()
    assert len(links) == 2
    filtered = browser.get_links(query="Link A")
    assert len(filtered) == 1


def test_browser_snapshot():
    browser = AgentWebBrowser()
    browser.register_source(_FakeSource({
        "https://fake.test/": _make_page(url="https://fake.test/"),
    }))
    browser.open("https://fake.test/")

    snap = browser.snapshot()
    assert snap["kind"] == "agent_web_browser_snapshot"
    assert snap["version"] == 1
    assert snap["request_count"] == 1
    assert len(snap["tabs"]) == 1


def test_browser_cache_reuse():
    call_count = 0

    class _CountingSource:
        def can_handle(self, url: str) -> bool:
            return "counting.test" in url

        def fetch(self, url: str, *, config: BrowserConfig) -> BrowserPage:
            nonlocal call_count
            call_count += 1
            return _make_page(url=url)

    browser = AgentWebBrowser()
    browser.register_source(_CountingSource())

    browser.open("https://counting.test/page")
    browser.open("https://counting.test/page")  # Should use cache
    assert call_count == 1

    browser.open("https://counting.test/page", use_cache=False)  # Bypass cache
    assert call_count == 2


def test_browser_submit_get_form():
    result_page = _make_page(url="https://fake.test/search?q=hello", title="Search Results")
    form_page = _make_page(
        url="https://fake.test/",
        forms=(PageForm(
            action="https://fake.test/search",
            method="GET",
            fields=(FormField(name="q"),),
            form_id="search",
            index=0,
        ),),
    )

    source = _FakeSource({
        "https://fake.test/": form_page,
        "https://fake.test/search?q=hello": result_page,
    })

    browser = AgentWebBrowser()
    browser.register_source(source)
    browser.open("https://fake.test/")
    page = browser.submit_form(0, values={"q": "hello"})
    assert page.title == "Search Results"


def test_browser_submit_form_by_id():
    form_page = _make_page(
        url="https://fake.test/",
        forms=(
            PageForm(action="https://fake.test/a", method="GET", form_id="form_a", index=0,
                     fields=(FormField(name="q", value="x"),)),
            PageForm(action="https://fake.test/b", method="GET", form_id="form_b", index=1,
                     fields=(FormField(name="q", value="y"),)),
        ),
    )

    source = _FakeSource({
        "https://fake.test/": form_page,
        "https://fake.test/b?q=y": _make_page(url="https://fake.test/b?q=y", title="Form B"),
    })

    browser = AgentWebBrowser()
    browser.register_source(source)
    browser.open("https://fake.test/")
    page = browser.submit_form("form_b")
    assert page.title == "Form B"


# ---------------------------------------------------------------------------
# PageMeta model
# ---------------------------------------------------------------------------

def test_page_meta_defaults():
    meta = PageMeta()
    assert meta.charset == "utf-8"
    assert meta.description == ""
    assert meta.keywords == ()
    assert meta.extra == {}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_browser_no_current_page_raises():
    browser = AgentWebBrowser()
    with pytest.raises(ValueError, match="no_current_page"):
        browser.follow_link(0)


def test_browser_link_index_out_of_range():
    page = _make_page(url="https://fake.test/", links=())
    browser = AgentWebBrowser()
    browser.register_source(_FakeSource({"https://fake.test/": page}))
    browser.open("https://fake.test/")

    with pytest.raises(IndexError, match="link_index_out_of_range"):
        browser.follow_link(99)


def test_browser_unknown_tab():
    browser = AgentWebBrowser()
    with pytest.raises(ValueError, match="unknown_tab"):
        browser.switch_tab("nonexistent")


def test_browser_refresh():
    call_count = 0

    class _CountingSource:
        def can_handle(self, url: str) -> bool:
            return True

        def fetch(self, url: str, *, config: BrowserConfig) -> BrowserPage:
            nonlocal call_count
            call_count += 1
            return _make_page(url=url, content_text=f"version {call_count}")

    browser = AgentWebBrowser()
    browser.register_source(_CountingSource())
    browser.open("https://fake.test/")
    assert "version 1" in browser.get_text()

    browser.refresh()
    assert "version 2" in browser.get_text()


# ---------------------------------------------------------------------------
# Environment probe
# ---------------------------------------------------------------------------

def test_probe_environment_returns_structured_dict():
    env = probe_environment()
    assert env["kind"] == "agent_web_browser_environment"
    assert env["version"] == 1
    assert "connectivity" in env
    assert "github" in env
    assert "sources" in env
    assert "runtime" in env
    assert "probed_at" in env
    assert isinstance(env["connectivity"]["has_internet"], bool)
    assert isinstance(env["runtime"]["python"], str)


def test_browser_environment_includes_sources():
    class _DummySource:
        def can_handle(self, url: str) -> bool:
            return False
        def fetch(self, url: str, *, config: BrowserConfig) -> BrowserPage:
            return _make_page(url=url)

    browser = AgentWebBrowser()
    browser.register_source(_DummySource())
    env = browser.environment()
    assert "_DummySource" in env["sources"]


# ---------------------------------------------------------------------------
# GAD-000 capability manifest
# ---------------------------------------------------------------------------

def test_capability_manifest_structure():
    manifest = build_browser_capability_manifest()
    assert manifest["kind"] == "agent_web_browser_capability_manifest"
    assert manifest["version"] == 1
    assert manifest["standard_profile"]["gad_conformance"] == "gad_000_plus"
    assert manifest["standard_profile"]["profile_id"] == "agent_web_browser_standard.v1"
    assert manifest["surface_kind"] == "agent_web_browser_surface"
    assert isinstance(manifest["capabilities"], list)
    assert manifest["stats"]["capability_count"] == len(manifest["capabilities"])


def test_capability_manifest_has_required_capabilities():
    manifest = build_browser_capability_manifest()
    cap_ids = {cap["capability_id"] for cap in manifest["capabilities"]}
    assert "web_browse" in cap_ids
    assert "web_follow_link" in cap_ids
    assert "web_navigate" in cap_ids
    assert "web_search_links" in cap_ids
    assert "web_submit_form" in cap_ids
    assert "web_environment" in cap_ids
    assert "web_tab_management" in cap_ids


def test_capability_manifest_includes_sources():
    class _TestSource:
        def can_handle(self, url: str) -> bool:
            return False
        def fetch(self, url: str, *, config: BrowserConfig) -> BrowserPage:
            return _make_page(url=url)

    manifest = build_browser_capability_manifest(sources=[_TestSource()])
    assert "_TestSource" in manifest["sources"]["registered"]


def test_browser_capability_manifest_method():
    browser = AgentWebBrowser()
    manifest = browser.capability_manifest()
    assert manifest["kind"] == "agent_web_browser_capability_manifest"


def test_capability_manifest_follows_federation_boundary():
    manifest = build_browser_capability_manifest()
    assert manifest["federation_surface"]["canonical_for_public_federation"] is False
    assert "ADR-0003" in manifest["federation_surface"]["transport_boundary"]


# ---------------------------------------------------------------------------
# EnvironmentProbe dataclass
# ---------------------------------------------------------------------------

def test_environment_probe_dataclass():
    probe = EnvironmentProbe(
        has_internet=True,
        has_proxy=False,
        proxy_url="",
        has_github_token=True,
        github_api_reachable=True,
        github_user="testuser",
        registered_sources=("GitHubBrowserSource",),
        python_version="3.11.0",
        platform="Linux 6.0",
        hostname="testhost",
        working_directory="/tmp",
        probed_at=1000.0,
    )
    assert probe.has_internet is True
    assert probe.github_user == "testuser"
    assert probe.registered_sources == ("GitHubBrowserSource",)


# ---------------------------------------------------------------------------
# URL validation edge cases
# ---------------------------------------------------------------------------

def test_empty_url_returns_error_page():
    browser = AgentWebBrowser()
    page = browser.open("")
    assert not page.ok
    assert "empty_url" in page.error


def test_whitespace_url_returns_error_page():
    browser = AgentWebBrowser()
    page = browser.open("   ")
    assert not page.ok
    assert "empty_url" in page.error


def test_ftp_url_returns_unsupported_scheme():
    browser = AgentWebBrowser()
    page = browser.open("ftp://example.com")
    assert not page.ok
    assert "unsupported_scheme" in page.error


def test_no_scheme_url_returns_error():
    browser = AgentWebBrowser()
    page = browser.open("example.com")
    assert not page.ok


# ---------------------------------------------------------------------------
# about: protocol
# ---------------------------------------------------------------------------

def test_about_blank():
    browser = AgentWebBrowser()
    page = browser.open("about:blank")
    assert page.ok
    assert page.title == "about:blank"
    assert page.content_text == ""


def test_about_environment():
    browser = AgentWebBrowser()
    page = browser.open("about:environment")
    assert page.ok
    assert "Environment" in page.title
    assert "Python" in page.content_text
    assert "Platform" in page.content_text


def test_about_capabilities():
    browser = AgentWebBrowser()
    page = browser.open("about:capabilities")
    assert page.ok
    assert "Capabilities" in page.title
    assert "gad_000" in page.content_text.lower() or "GAD" in page.content_text
    assert "web_browse" in page.content_text


def test_about_unknown_returns_error():
    browser = AgentWebBrowser()
    page = browser.open("about:foobar")
    assert not page.ok
    assert "unknown_about_page" in page.error


def test_about_federation():
    """about:federation should return a page (may have no peers in test env)."""
    browser = AgentWebBrowser()
    page = browser.open("about:federation")
    assert page.ok
    assert "Federation" in page.title
