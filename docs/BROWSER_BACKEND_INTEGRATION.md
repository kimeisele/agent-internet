# Browser ↔ Backend Integration Map

## What Exists

### Backend Modules (9 modules, ~80K chars)

| Module | Purpose | Key API | Data Shape |
|--------|---------|---------|------------|
| `agent_web_semantic_graph` | Knowledge graph — nodes + weighted edges | `build_agent_web_semantic_graph(records)` → adjacency list | `neighbors_by_record_id` dict, edges scored by lexical/wordnet/bridge |
| `agent_web_federated_index` | Federated search index across all sources | `search_agent_web_federated_index(index, query)` → ranked results | Records from source registry + federation snapshot, semantic expansion |
| `agent_web_repo_graph` | Repository structure as knowledge graph | `build_agent_web_repo_graph_snapshot(root)` → nodes/edges | Uses `vibe_core.knowledge.graph`, node types + relations + metrics |
| `agent_web_semantic_overlay` | Query expansion via semantic bridges | `expand_query_with_agent_web_semantic_overlay(overlay, query=q)` | Bridges: alias/synonym/concept/wordnet/resonance with weighted expansions |
| `agent_web_semantic_capabilities` | Capability discovery manifest | `build_agent_web_semantic_capability_manifest()` | 3 capabilities: federated_search, neighbors, expand |
| `agent_web_semantic_consumer` | Client for invoking semantic capabilities remotely | `invoke_agent_web_semantic_consumer(capability_id=..., input_payload=...)` | HTTP transport to Lotus daemon endpoints |
| `agent_web_source_registry` | Persistent registry of content sources | `load_agent_web_source_registry()`, `upsert_...()` | JSON file with source entries (root, labels, enabled) |
| `agent_web_index` | Core search index builder + scorer | `search_agent_web_index(index, query=q)` → scored results | Records from manifest/graph, term-weighted scoring |
| `agent_web_navigation` | Document resolution from manifests | `read_agent_web_document_from_repo_root(root, rel=...)` | Resolves links → documents → markdown content |

### Browser Bridge (existing)

`agent_web_browser_semantic.py` — `BrowsedPageIndex`:
- Converts `BrowserPage` → semantic records via `page_to_semantic_record()`
- Has `search()` with optional semantic expansion
- Has `inject_into_federated_index()` to merge into the federated index
- Has `build_semantic_graph()` — delegates to `build_agent_web_semantic_graph()`
- Record ID scheme: `"web:" + sha256(url)[:16]`
- Scoring: title (3.0) > summary (1.5) > tags (1.2) > terms (1.0)

### Browser about: Pages (existing + new)

| Page | Status | Backend |
|------|--------|---------|
| `about:blank` | Built-in | — |
| `about:environment` | Built-in | `agent_web_browser_env` |
| `about:capabilities` | Built-in | GAD-000 manifest |
| `about:federation` | Built-in | Peer descriptor scanning |
| `about:bookmarks` | Built-in | In-memory |
| `about:history` | Built-in | In-memory |
| `about:graph` | **NEW** | `agent_web_semantic_graph` via `BrowsedPageIndex` |
| `about:search` | **NEW** | `agent_web_federated_index` → `BrowsedPageIndex` fallback |

## Module Deep Dive

### agent_web_semantic_graph.py

Pure functional, no classes. Builds graphs from records using 4 scoring dimensions:
- **Lexical overlap**: +0.15 per shared term (max +0.45), terms ≥4 chars, stop words excluded
- **Same title**: score = max(score, 0.65)
- **Semantic bridge match**: +0.12 per bridge (max +0.3), via overlay
- **WordNet similarity**: +(wordnet_score × 0.4) (max +0.25)
- Minimum threshold: 0.2

Output: `{neighbors_by_record_id: {record_id: [{record_id, score, reason_kinds, shared_terms}]}, stats: {node_count, edge_count, connected_record_count}}`

### agent_web_federated_index.py

Full refresh from source registry + control plane state. Creates records for:
- `federation_health_report` — per-city health/heartbeat/capabilities
- `federation_trust_summary` — aggregated trust distribution
- `federation_peer_registry` — all registered city_ids
- `federation_lotus_services` — per-city lotus service addresses

Search: `search_agent_web_federated_index(index, query=q, limit=10, semantic_overlay=..., wordnet_bridge=...)` → enriched results with `why_matched` annotation (title/summary exact match, direct/expanded term matches, bridge matches, semantic neighbors).

### agent_web_index.py

Builds search index from agent-web manifests. Record kinds: city, assistant, campaign, document, service, route, capability, graph_node. Scoring: title match (+30), summary (+12), tag (+15×w), term (+6×w), partial term (+3×w), coverage bonus (+5×ratio). Supports expanded terms with weights from semantic overlay.

### agent_web_semantic_overlay.py

Bridge-based query expansion. Bridge kinds and default weights: alias (1.0), synonym (0.9), wordnet (0.78), concept (0.65), resonance (0.55). Lexical match scoring: exact (1.0), token match (0.95), substring (0.75), subset (0.65). Expansion: `expand_query_with_agent_web_semantic_overlay(overlay, query=q)` → `{input_terms, expanded_terms, weighted_expanded_terms, matched_bridges}`.

### agent_web_navigation.py

Resolves documents from manifests using link resolution (by document_id > href > rel). Reads markdown content via wiki projection (`render_wiki_projection()`). Only supports `text/markdown` media type. Uses `AgentCityFilesystemContract` for peer descriptor location.

### agent_web_source_registry.py

Persistent JSON registry of content sources (repo roots). CRUD: `load`, `upsert`, `remove`. Builds crawl bootstrap from registry. Default path: `data/control_plane/agent_web_source_registry.json`. Auto-generates `source_id` from `peer.json` city_id or directory name.

### agent_web_semantic_capabilities.py

Defines 3 Lotus API capabilities: `semantic_federated_search`, `semantic_neighbors`, `semantic_expand`. Each with path, query params, response schema. Auth: lotus bearer token.

### agent_web_semantic_consumer.py

HTTP client for Lotus API. Bootstrap → discover manifest → resolve contract → build invocation plan → invoke. Resolves auth from params or env vars (`AGENT_INTERNET_LOTUS_BASE_URL`, `AGENT_INTERNET_LOTUS_TOKEN`).

### agent_web_repo_graph.py

Steward-protocol specific. Loads knowledge graph from `vibe_core`, serializes nodes/edges/metrics/constraints. BFS neighbor traversal. Only supports repos named "steward-protocol".

## What Was Built

### 1. `about:graph` — Semantic Knowledge Graph Browser

Routes:
- `about:graph` → all nodes, stats (node count, edge count, connected)
- `about:graph?query=X` → filter nodes by term in title/summary/tags
- `about:graph?node=ID` → node detail with neighbors, scores, reason kinds

Data source: `BrowsedPageIndex.build_semantic_graph()` → delegates to `build_agent_web_semantic_graph()`. Every browsed page becomes a graph node. Neighbors linked by lexical overlap, shared terms, bridges.

### 2. `about:search` — Federated Search

Routes:
- `about:search` → landing page with index stats
- `about:search?q=X` → execute search

Resolution order:
1. Try `load_agent_web_federated_index()` + `search_agent_web_federated_index()` (if records exist)
2. Fall back to `BrowsedPageIndex.search()` (always available)

Results show: score, kind, summary, matched terms, query interpretation (raw/expanded terms, bridges).

### 3. Auto-Ingest Pipeline

Every `browser.open(url)` call auto-ingests into `BrowsedPageIndex` (unless `about:` page or failed page). Silent on error. Lazy-loaded index. The loop: Browse → Ingest → Search → Browse.

### 4. Cross-Navigation

`about:environment` → links to `about:graph` and `about:search`
`about:graph` → links to node detail, node hrefs (open page), `about:search`
`about:search` → links to result hrefs (open page), `about:graph`

## Source Registry vs Browser register_source()

**Decision: Keep separate.** Different layers, different purposes:

| | Browser `register_source()` | Source Registry |
|---|---|---|
| **What** | Transport adapters | Content inventory |
| **Protocol** | `PageSource(Protocol)` — `can_handle(url) + fetch(url)` | JSON file with repo roots |
| **Purpose** | "How to fetch" (GitHub API, HTTP, etc.) | "What to crawl" (repo paths, labels, enabled flags) |
| **Scope** | Runtime, in-memory | Persistent, on-disk |
| **Growth** | New adapters for new transports | New entries for new repos |

They complement each other: the source registry tells you *what* to crawl, the browser sources tell you *how*. The registry could be exposed via `about:sources` in the future for visibility, but merging the mechanisms would conflate transport with inventory.

## Federation Wiki Reading

The browser already supports wiki-style content via its content-type intelligence and wiki navigation support (commit dd6ab3e). Federation peers are discovered via `about:federation`. The navigation module (`agent_web_navigation.py`) can resolve wiki documents from manifests.

To browse federation wikis: open the GitHub wiki URL for each peer repo. The browser's HTTP fetcher handles it. With auto-ingest, every wiki page browsed is immediately indexed and searchable via `about:search`. The closed loop:

```
about:federation → discover peers → open wiki URL → auto-ingest → about:search?q=... → find content
```

The `agent_web_navigation` module provides deeper integration if we ever need to resolve documents from manifests directly (via `read_agent_web_document_from_repo_root()`), but for now the HTTP wiki path is simpler and works.

## What's Next (Not in This PR)

- `about:sources` — expose source registry for visibility
- Semantic overlay pass-through in about:search (currently searches without expansion)
- Repo graph integration (requires steward-protocol + vibe_core, out of scope)
- Lotus API consumer integration (requires running Lotus daemon)
- `inject_into_federated_index()` call after browsing sessions to persist index to disk
