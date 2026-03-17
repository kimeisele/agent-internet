"""Tests for agent_web_browser_semantic — Browser ↔ Semantic Layer bridge.

Verifies page-to-record conversion, in-memory indexing, search scoring,
persistence, and semantic graph integration.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agent_internet.agent_web_browser import BrowserPage, PageLink, PageMeta
from agent_internet.agent_web_browser_semantic import (
    BrowsedPageIndex,
    _extract_terms,
    _stable_record_id,
    _summarize,
    build_browser_semantic_capability_manifest,
    page_to_semantic_record,
    pages_to_semantic_records,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_page(
    url: str = "https://example.com",
    title: str = "Example Page",
    content: str = "This is example content about Python programming.",
    *,
    status_code: int = 200,
    keywords: tuple[str, ...] = ("python", "example"),
    description: str = "An example page",
    links: tuple[PageLink, ...] = (),
    error: str = "",
) -> BrowserPage:
    return BrowserPage(
        url=url,
        status_code=status_code,
        title=title,
        content_text=content,
        links=links,
        forms=(),
        meta=PageMeta(
            description=description,
            keywords=keywords,
        ),
        fetched_at=1000.0,
        error=error,
    )


# ---------------------------------------------------------------------------
# Term extraction
# ---------------------------------------------------------------------------

def test_extract_terms_filters_stopwords():
    terms = _extract_terms("the quick brown fox and the lazy dog")
    assert "the" not in terms
    assert "quick" in terms
    assert "brown" in terms
    assert "lazy" in terms


def test_extract_terms_deduplicates():
    terms = _extract_terms("python python python ruby ruby")
    assert terms.count("python") == 1
    assert terms.count("ruby") == 1


def test_extract_terms_respects_limit():
    long_text = " ".join(f"word{i}" for i in range(200))
    terms = _extract_terms(long_text, limit=10)
    assert len(terms) <= 10


def test_extract_terms_min_length():
    terms = _extract_terms("a an the cat dog run")
    # "cat", "dog", "run" are only 3 chars → filtered
    assert "cat" not in terms
    assert "dog" not in terms


# ---------------------------------------------------------------------------
# Stable record ID
# ---------------------------------------------------------------------------

def test_stable_record_id_deterministic():
    id1 = _stable_record_id("https://example.com")
    id2 = _stable_record_id("https://example.com")
    assert id1 == id2
    assert id1.startswith("web:")


def test_stable_record_id_different_urls():
    id1 = _stable_record_id("https://example.com")
    id2 = _stable_record_id("https://other.com")
    assert id1 != id2


# ---------------------------------------------------------------------------
# Summarize
# ---------------------------------------------------------------------------

def test_summarize_short_text():
    assert _summarize("Hello world.") == "Hello world."


def test_summarize_long_text():
    text = "This is a long sentence. " * 30
    result = _summarize(text, max_len=100)
    assert len(result) <= 101  # +1 for potential trailing char


# ---------------------------------------------------------------------------
# page_to_semantic_record
# ---------------------------------------------------------------------------

def test_page_to_record_basic():
    page = _make_page()
    record = page_to_semantic_record(page)

    assert record["kind"] == "web_page"
    assert record["title"] == "Example Page"
    assert record["summary"] == "An example page"
    assert record["href"] == "https://example.com"
    assert "python" in record["tags"]
    assert record["source_city_id"] == "agent_web_browser"
    assert record["record_id"].startswith("web:")
    assert len(record["terms"]) > 0


def test_page_to_record_custom_source():
    page = _make_page()
    record = page_to_semantic_record(page, source_id="my_crawler")
    assert record["source_id"] == "my_crawler"
    assert record["source_city_id"] == "my_crawler"


def test_page_to_record_uses_og_description_fallback():
    page = BrowserPage(
        url="https://example.com",
        status_code=200,
        title="Test",
        content_text="Content here",
        links=(),
        forms=(),
        meta=PageMeta(og_description="OG description text"),
        fetched_at=1000.0,
    )
    record = page_to_semantic_record(page)
    assert record["summary"] == "OG description text"


# ---------------------------------------------------------------------------
# pages_to_semantic_records
# ---------------------------------------------------------------------------

def test_pages_to_records_skips_errors():
    ok_page = _make_page(url="https://example.com/ok")
    err_page = _make_page(url="https://example.com/err", status_code=404, error="not found")
    records = pages_to_semantic_records([ok_page, err_page])
    assert len(records) == 1
    assert records[0]["href"] == "https://example.com/ok"


# ---------------------------------------------------------------------------
# BrowsedPageIndex — ingest
# ---------------------------------------------------------------------------

def test_index_ingest():
    index = BrowsedPageIndex()
    page = _make_page()
    record = index.ingest(page)
    assert record["kind"] == "web_page"
    assert index.page_count == 1
    assert len(index) == 1


def test_index_ingest_deduplicates_by_url():
    index = BrowsedPageIndex()
    p1 = _make_page(title="Version 1")
    p2 = _make_page(title="Version 2")  # same URL
    index.ingest(p1)
    index.ingest(p2)
    assert index.page_count == 1
    assert index.records[0]["title"] == "Version 2"


def test_index_ingest_skips_error_pages():
    index = BrowsedPageIndex()
    page = _make_page(status_code=500, error="server error")
    result = index.ingest(page)
    assert result == {}
    assert index.page_count == 0


def test_index_ingest_many():
    index = BrowsedPageIndex()
    pages = [
        _make_page(url=f"https://example.com/{i}", title=f"Page {i}")
        for i in range(5)
    ]
    count = index.ingest_many(pages)
    assert count == 5
    assert index.page_count == 5


# ---------------------------------------------------------------------------
# BrowsedPageIndex — search
# ---------------------------------------------------------------------------

def test_index_search_basic():
    index = BrowsedPageIndex()
    index.ingest(_make_page(
        url="https://example.com/python",
        title="Python Guide",
        content="Learn Python programming language basics.",
    ))
    index.ingest(_make_page(
        url="https://example.com/rust",
        title="Rust Guide",
        content="Learn Rust programming language basics.",
    ))

    results = index.search("python")
    assert results["kind"] == "agent_web_browser_search_results"
    assert results["stats"]["result_count"] >= 1
    # Python page should score higher
    if results["stats"]["result_count"] >= 2:
        assert "python" in results["results"][0]["title"].lower()


def test_index_search_empty_index():
    index = BrowsedPageIndex()
    results = index.search("anything")
    assert results["stats"]["result_count"] == 0
    assert results["results"] == []


def test_index_search_respects_limit():
    index = BrowsedPageIndex()
    for i in range(20):
        index.ingest(_make_page(
            url=f"https://example.com/{i}",
            title=f"Programming Tutorial {i}",
            content="Programming is great.",
        ))
    results = index.search("programming", limit=5)
    assert results["stats"]["result_count"] <= 5


def test_index_search_returns_query_interpretation():
    index = BrowsedPageIndex()
    index.ingest(_make_page())
    results = index.search("example query")
    interp = results["query_interpretation"]
    assert interp["raw_query"] == "example query"
    assert "example" in interp["input_terms"]


# ---------------------------------------------------------------------------
# BrowsedPageIndex — persistence
# ---------------------------------------------------------------------------

def test_index_save_and_load():
    index = BrowsedPageIndex()
    index.ingest(_make_page(url="https://example.com/1", title="Page One"))
    index.ingest(_make_page(url="https://example.com/2", title="Page Two"))

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "index.json"
        index.save(path)

        loaded = BrowsedPageIndex.load(path)
        assert loaded.page_count == 2
        assert loaded.records[0]["title"] == "Page One"

        # URL dedup still works after load
        loaded.ingest(_make_page(url="https://example.com/1", title="Updated One"))
        assert loaded.page_count == 2
        assert loaded.records[0]["title"] == "Updated One"


def test_index_load_nonexistent():
    index = BrowsedPageIndex.load("/nonexistent/path.json")
    assert index.page_count == 0


# ---------------------------------------------------------------------------
# BrowsedPageIndex — semantic graph
# ---------------------------------------------------------------------------

def test_index_build_semantic_graph():
    index = BrowsedPageIndex()
    index.ingest(_make_page(
        url="https://example.com/python",
        title="Python Programming Guide",
        content="Python is a versatile programming language.",
    ))
    index.ingest(_make_page(
        url="https://example.com/java",
        title="Java Programming Guide",
        content="Java is a popular programming language.",
    ))

    graph = index.build_semantic_graph()
    # Should have some structure (may or may not have edges depending on
    # term overlap thresholds)
    assert "neighbors_by_record_id" in graph or "stats" in graph


# ---------------------------------------------------------------------------
# BrowsedPageIndex — federated index injection
# ---------------------------------------------------------------------------

def test_inject_into_federated_index():
    index = BrowsedPageIndex()
    index.ingest(_make_page(url="https://example.com/a", title="Page A"))
    index.ingest(_make_page(url="https://example.com/b", title="Page B"))

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "federated.json"
        result = index.inject_into_federated_index(index_path=path)
        assert result["injected"] == 2
        assert result["updated"] == 0
        assert result["total_records"] == 2

        # Inject again — should update, not duplicate
        result2 = index.inject_into_federated_index(index_path=path)
        assert result2["injected"] == 0
        assert result2["updated"] == 2
        assert result2["total_records"] == 2


def test_inject_merges_with_existing():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "federated.json"
        # Pre-populate with existing records
        existing = {
            "kind": "agent_web_federated_index",
            "version": 1,
            "records": [
                {"record_id": "existing:1", "title": "Existing Record", "kind": "city"},
            ],
        }
        path.write_text(json.dumps(existing))

        index = BrowsedPageIndex()
        index.ingest(_make_page(url="https://example.com/new", title="New Page"))
        result = index.inject_into_federated_index(index_path=path)
        assert result["injected"] == 1
        assert result["total_records"] == 2  # 1 existing + 1 new


# ---------------------------------------------------------------------------
# Capability manifest
# ---------------------------------------------------------------------------

def test_capability_manifest():
    manifest = build_browser_semantic_capability_manifest()
    assert manifest["kind"] == "capability_manifest"
    assert "gad_000" in manifest["gad_conformance"]
    assert "page_to_record" in manifest["capabilities"]
    assert "browsed_page_search" in manifest["capabilities"]
    assert "federated_index_injection" in manifest["capabilities"]
    assert "ADR-0003" in manifest["federation_surface"]["transport_boundary"]
