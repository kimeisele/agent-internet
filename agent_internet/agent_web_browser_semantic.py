"""Agent Web Browser ↔ Semantic Layer bridge.

Converts :class:`BrowserPage` objects into semantic records that can be fed
into the federated semantic index, enabling agents to discover and search
crawled web content through the semantic layer.

Design (per ADR-0003):
  - Web content enters via the browser (transport adapter).
  - This bridge converts it into *records* the semantic layer understands.
  - No foreign identity or governance is imported — just structured knowledge.

Zero external dependencies — stdlib only.

Usage::

    from agent_internet.agent_web_browser import AgentWebBrowser
    from agent_internet.agent_web_browser_semantic import (
        BrowsedPageIndex,
        page_to_semantic_record,
        search_browsed_pages,
    )

    browser = AgentWebBrowser()
    page = browser.open("https://example.com")

    index = BrowsedPageIndex()
    index.ingest(page)
    results = index.search("example query")
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_web_browser import BrowserPage

logger = logging.getLogger("AGENT_INTERNET.WEB_BROWSER_SEMANTIC")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during", "before",
    "after", "above", "below", "this", "that", "these", "those", "it", "its",
    "not", "no", "nor", "so", "if", "then", "than", "too", "very", "just",
    "about", "also", "how", "what", "when", "where", "which", "who", "whom",
    "all", "each", "every", "any", "some", "such", "only", "own", "same",
    "more", "most", "other", "up", "out", "over",
})

_MIN_TERM_LEN = 4


# ---------------------------------------------------------------------------
# Page → Semantic Record
# ---------------------------------------------------------------------------

def _extract_terms(text: str, *, limit: int = 50) -> list[str]:
    """Extract meaningful terms from text for semantic scoring."""
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{3,}", text.lower())
    seen: set[str] = set()
    terms: list[str] = []
    for tok in tokens:
        if tok in _STOP_WORDS or tok in seen:
            continue
        seen.add(tok)
        terms.append(tok)
        if len(terms) >= limit:
            break
    return terms


def _stable_record_id(url: str) -> str:
    """Produce a deterministic record_id from a URL."""
    return "web:" + hashlib.sha256(url.encode()).hexdigest()[:16]


def _summarize(text: str, *, max_len: int = 300) -> str:
    """Extract a short summary from page text."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_len:
        return cleaned
    # Try to cut at sentence boundary
    cut = cleaned[:max_len]
    last_dot = cut.rfind(".")
    if last_dot > max_len // 2:
        return cut[: last_dot + 1]
    return cut + "…"


def page_to_semantic_record(page: "BrowserPage", *, source_id: str = "agent_web_browser") -> dict:
    """Convert a :class:`BrowserPage` into a semantic record.

    The returned dict follows the record schema expected by
    :func:`build_agent_web_semantic_graph` and the federated index.
    """
    tags: list[str] = []
    if page.meta.keywords:
        tags.extend(page.meta.keywords)
    if page.content_type and "/" in page.content_type:
        tags.append(page.content_type.split(";")[0].strip())

    summary = page.meta.description or page.meta.og_description or _summarize(page.content_text)
    terms = _extract_terms(f"{page.title} {summary} {page.content_text}")

    return {
        "record_id": _stable_record_id(page.url),
        "kind": "web_page",
        "title": page.title or page.url,
        "summary": summary,
        "tags": tags,
        "terms": terms,
        "source_city_id": source_id,
        "source_id": source_id,
        "href": page.url,
        "indexed_at": page.fetched_at or time.time(),
        # Extra fields for richer browsing context
        "link_count": page.link_count,
        "form_count": page.form_count,
        "status_code": page.status_code,
        "content_type": page.content_type,
    }


def pages_to_semantic_records(
    pages: list["BrowserPage"],
    *,
    source_id: str = "agent_web_browser",
) -> list[dict]:
    """Batch-convert pages to semantic records, skipping error pages."""
    return [
        page_to_semantic_record(page, source_id=source_id)
        for page in pages
        if page.ok
    ]


# ---------------------------------------------------------------------------
# Browsed Page Index — lightweight in-memory semantic index
# ---------------------------------------------------------------------------

@dataclass
class BrowsedPageIndex:
    """In-memory semantic index over browsed pages.

    Provides term-based search with optional semantic overlay expansion.
    Persists to JSON for cross-session continuity.
    """

    records: list[dict] = field(default_factory=list)
    _url_map: dict[str, int] = field(default_factory=dict, repr=False)

    # -- Ingest --

    def ingest(self, page: "BrowserPage", *, source_id: str = "agent_web_browser") -> dict:
        """Ingest a single page.  Returns the created record."""
        if not page.ok:
            return {}
        record = page_to_semantic_record(page, source_id=source_id)
        # Deduplicate by URL
        existing_idx = self._url_map.get(page.url)
        if existing_idx is not None:
            self.records[existing_idx] = record
        else:
            self._url_map[page.url] = len(self.records)
            self.records.append(record)
        return record

    def ingest_many(self, pages: list["BrowserPage"], *, source_id: str = "agent_web_browser") -> int:
        """Ingest multiple pages.  Returns count of records added/updated."""
        count = 0
        for page in pages:
            if self.ingest(page, source_id=source_id):
                count += 1
        return count

    # -- Search --

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        semantic_overlay: dict | None = None,
        wordnet_bridge: dict | None = None,
    ) -> dict:
        """Search indexed pages using term matching with optional semantic expansion.

        Returns a result dict compatible with federated search output.
        """
        # Expand query if overlay available
        expanded_terms: list[str] = []
        matched_bridges: list[dict] = []
        query_terms = _extract_terms(query, limit=20) or [query.lower().strip()]

        if semantic_overlay:
            try:
                from .agent_web_semantic_overlay import expand_query_with_agent_web_semantic_overlay
                expansion = expand_query_with_agent_web_semantic_overlay(
                    semantic_overlay, query, wordnet_bridge=wordnet_bridge,
                )
                expanded_terms = expansion.get("expanded_terms", [])
                matched_bridges = expansion.get("matched_bridges", [])
            except Exception:
                logger.debug("semantic overlay expansion failed", exc_info=True)

        all_terms = set(query_terms) | set(expanded_terms)

        # Score each record
        scored: list[tuple[float, dict]] = []
        for record in self.records:
            score = _score_record(record, all_terms, query_terms)
            if score > 0:
                scored.append((score, record))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, record in scored[:limit]:
            results.append({
                **record,
                "score": round(score, 4),
                "matched_terms": [t for t in all_terms if _term_in_record(record, t)],
            })

        return {
            "kind": "agent_web_browser_search_results",
            "version": 1,
            "query": query,
            "results": results,
            "query_interpretation": {
                "raw_query": query,
                "input_terms": query_terms,
                "expanded_terms": expanded_terms,
                "semantic_bridges_applied": [b.get("bridge_id", "") for b in matched_bridges],
            },
            "stats": {
                "result_count": len(results),
                "indexed_page_count": len(self.records),
            },
        }

    # -- Persistence --

    def save(self, path: str | Path) -> None:
        """Persist index to JSON file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "kind": "agent_web_browser_index",
            "version": 1,
            "saved_at": time.time(),
            "records": self.records,
        }
        p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "BrowsedPageIndex":
        """Load index from JSON file."""
        p = Path(path)
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        records = data.get("records", [])
        idx = cls(records=records)
        for i, rec in enumerate(records):
            href = rec.get("href", "")
            if href:
                idx._url_map[href] = i
        return idx

    # -- Semantic Graph Integration --

    def build_semantic_graph(
        self,
        *,
        semantic_overlay: dict | None = None,
        wordnet_bridge: dict | None = None,
        neighbor_limit: int = 5,
    ) -> dict:
        """Build a semantic graph over all indexed pages.

        Delegates to :func:`build_agent_web_semantic_graph` from the semantic
        layer.  Returns the graph dict or an empty stub if the semantic layer
        is unavailable.
        """
        try:
            from .agent_web_semantic_graph import build_agent_web_semantic_graph
            return build_agent_web_semantic_graph(
                self.records,
                semantic_overlay=semantic_overlay,
                wordnet_bridge=wordnet_bridge,
                neighbor_limit=neighbor_limit,
            )
        except Exception:
            logger.debug("semantic graph build failed", exc_info=True)
            return {"neighbors_by_record_id": {}, "stats": {"node_count": 0, "edge_count": 0}}

    def inject_into_federated_index(
        self,
        index_path: str | Path | None = None,
    ) -> dict:
        """Inject browsed-page records into an existing federated index.

        Merges records into the federated index JSON, preserving existing
        records from other sources.  Returns summary of what was injected.
        """
        default_path = Path("data/control_plane/agent_web_federated_index.json")
        p = Path(index_path) if index_path else default_path

        existing: dict = {}
        if p.exists():
            try:
                existing = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                existing = {}

        existing_records: list[dict] = existing.get("records", [])
        existing_ids = {r.get("record_id") for r in existing_records}

        injected = 0
        updated = 0
        for rec in self.records:
            rid = rec.get("record_id", "")
            if rid in existing_ids:
                # Update in place
                for i, er in enumerate(existing_records):
                    if er.get("record_id") == rid:
                        existing_records[i] = rec
                        updated += 1
                        break
            else:
                existing_records.append(rec)
                existing_ids.add(rid)
                injected += 1

        existing["records"] = existing_records
        existing.setdefault("kind", "agent_web_federated_index")
        existing.setdefault("version", 1)
        existing["last_browser_injection_at"] = time.time()

        stats = existing.setdefault("stats", {})
        stats["record_count"] = len(existing_records)

        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")

        return {
            "injected": injected,
            "updated": updated,
            "total_records": len(existing_records),
            "index_path": str(p),
        }

    @property
    def page_count(self) -> int:
        return len(self.records)

    def __len__(self) -> int:
        return len(self.records)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _term_in_record(record: dict, term: str) -> bool:
    """Check whether *term* appears in any searchable field of *record*."""
    for fld in ("title", "summary", "href"):
        if term in record.get(fld, "").lower():
            return True
    if term in record.get("tags", []):
        return True
    if term in record.get("terms", []):
        return True
    return False


def _score_record(record: dict, all_terms: set[str], query_terms: list[str]) -> float:
    """Score a record against search terms.  Higher = better match."""
    score = 0.0
    title = record.get("title", "").lower()
    summary = record.get("summary", "").lower()
    terms = set(record.get("terms", []))
    tags = set(record.get("tags", []))

    for qt in query_terms:
        if qt in title:
            score += 3.0  # Title match is strongest
        if qt in summary:
            score += 1.5
        if qt in terms:
            score += 1.0
        if qt in tags:
            score += 1.2

    # Expanded terms contribute less
    expanded_only = all_terms - set(query_terms)
    for et in expanded_only:
        if et in title:
            score += 1.0
        if et in summary:
            score += 0.5
        if et in terms:
            score += 0.4
        if et in tags:
            score += 0.5

    return score


# ---------------------------------------------------------------------------
# GAD-000+ capability manifest
# ---------------------------------------------------------------------------

def build_browser_semantic_capability_manifest() -> dict:
    """GAD-000+ capability manifest for the browser ↔ semantic bridge."""
    return {
        "kind": "capability_manifest",
        "standard": "agent_web_browser_semantic.v1",
        "gad_conformance": "gad_000_plus",
        "capabilities": {
            "page_to_record": {
                "description": "Convert a BrowserPage into a semantic record for indexing.",
                "mode": "read_only",
                "contract": "v1",
            },
            "browsed_page_search": {
                "description": "Search indexed browsed pages with semantic expansion.",
                "mode": "read_only",
                "contract": "v1",
            },
            "semantic_graph_build": {
                "description": "Build semantic neighbor graph over browsed pages.",
                "mode": "read_only",
                "contract": "v1",
            },
            "federated_index_injection": {
                "description": "Inject browsed-page records into the federated index.",
                "mode": "write",
                "contract": "v1",
            },
        },
        "federation_surface": {
            "transport_boundary": "ADR-0003: web content enters as transport, semantic records stay local",
            "identity_boundary": "No foreign identity imported — pages keyed by URL hash",
        },
    }
