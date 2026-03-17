# AGENTS.md — agent-internet

Guidelines for coding agents working on this repository.

## Architecture

`agent-internet` is the control plane, transport, and federation layer for
autonomous agents. It provides identity, routing, trust, discovery, and a
web browser — all in pure Python stdlib.

### Core Principles

- **Zero external dependencies.** Only Python stdlib. No exceptions.
  No `requests`, no `aiohttp`, no `playwright`. `urllib.request` for HTTP,
  `html.parser` for HTML, `json` for serialization, `sqlite3` for persistence.
- **Frozen dataclasses with `slots=True`** for all data models.
  `@dataclass(frozen=True, slots=True)` — immutable, memory-efficient, hashable.
- **Protocol-based interfaces** (`typing.Protocol`), not `abc.ABC`.
  Structural subtyping — implementations don't inherit from the interface.
- **ADR-0003 rule:** External web content is *transport*, not substrate.
  The browser projects the public web into agent-consumable structures without
  importing foreign identity or governance.

## Code Standards

### Style

- Ruff for linting (`ruff check`).
- All public functions: docstring + return type annotation.
- No `except Exception:` without a specific exception class. Always log caught
  exceptions with at least `logger.debug()`.
- No magic numbers — use `BrowserConfig` fields or named constants.
- Imports at module top, sorted. No lazy imports inside functions.
- Each file < 500 lines (hard limit), < 400 (target).

### Patterns

- `_make_page()` factory for all `BrowserPage` construction.
- `PageSource` protocol for pluggable browser sources (GitHub, federation, etc.).
- CBR-inspired compression via `compress_page()` for token-budget control.
- llms.txt discovery: check `/llms.txt` before HTML scraping (strangler fig).
- agents.json discovery: enrich pages with `/.well-known/agents.json` metadata.

### Testing

- `pytest` with stdlib `unittest.mock` for mocking.
- No test fixtures that require network access. All HTTP calls mocked.
- Tests in `tests/` mirror the source module structure.
- Run: `python -m pytest tests/ -x -q`

### What NOT to Do

- No JavaScript rendering, no CSS parsing, no browser engine dependencies.
- No Lotus/IPv7 integration (Phase 5 — design doc only for now).
- No plugin systems, middleware stacks, or event pipelines. KISS.
- No new external dependencies. If you think you need one, you don't.

## Module Map

| Module | Responsibility | Lines |
|--------|---------------|-------|
| `agent_web_browser.py` | Models, config, browser class, session management | ~860 |
| `agent_web_browser_parser.py` | HTML parser, `parse_html`, `_clean_text` | ~265 |
| `agent_web_browser_http.py` | HTTP fetch, JSON rendering, llms.txt/agents.json discovery | ~385 |
| `agent_web_browser_compress.py` | CBR compression, token budgets, nav-chrome stripping | ~155 |
| `agent_web_browser_env.py` | Environment probe, GAD-000 manifest, federation discovery | ~355 |
| `agent_web_browser_github.py` | GitHub API PageSource (repos, issues, PRs, releases) | ~740 |
| `agent_web_browser_semantic.py` | Semantic layer bridge (page → record → index) | ~280 |

## Quick Start

```python
from agent_internet import AgentWebBrowser, GitHubBrowserSource

browser = AgentWebBrowser()
browser.register_source(GitHubBrowserSource())

# Browse — llms.txt auto-discovered when available
page = browser.open("https://docs.stripe.com")
print(page.headers.get("x-content-source"))  # "llms.txt"

# GitHub repos via API, not HTML scraping
page = browser.open("https://github.com/kimeisele/agent-internet")
print(page.title, page.link_count)
```
