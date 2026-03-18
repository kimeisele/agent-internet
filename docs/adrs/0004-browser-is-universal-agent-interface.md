## ADR 0004: The browser is the universal agent interface

### Status

Proposed.

### Context

The Agent Web Browser started as a transport adapter for reading web content.
Over five rounds of integration it has grown to handle four URL schemes
(`about:`, `https://`, `cp://`, `github.com`) through a single pair of
operations: `browser.open(url)` and `browser.submit_form(form_id, values)`.

This pair is already sufficient for an agent to:

- discover federation peers (`about:federation`)
- inspect and write to the control plane (`about:cities`, `cp://cities/register`)
- evaluate trust (`about:trust`, `cp://trust/record`)
- manage spaces and slots (`about:spaces`, `cp://spaces/claim`)
- relay messages (`about:relay`, `cp://relay/send`)
- onboard new peers (`cp://federation/onboard`)
- browse the open web (`https://...`)
- read GitHub repositories (`https://github.com/...`)

Meanwhile, the underlying system exposes 45+ dataclasses, 53+ control plane
methods, 5 protocol interfaces, separate transport/relay/router APIs, and
Nadi/Lotus semantics.  An agent that wants to send a message today must know
what a `DeliveryEnvelope` is, which fields it requires, how `RelayService`
works, which transport is registered, and how routing is resolved.  That is
six imports and fifteen lines of code for a single operation.

With the browser: two lines.

```python
browser.open("about:relay")
browser.submit_form("send_message", {"target": "agent-city", "message": "sync complete"})
```

The browser already IS the universal agent interface.  This ADR formalizes
that observation.

### Decision

`browser.open(url)` is the canonical way an agent perceives.
`browser.submit_form(form_id, values)` is the canonical way an agent acts.

Every system capability is projected through URL schemes and rendered as
`BrowserPage` objects.  Agents do not need to know internal APIs.  They
navigate.

### URL scheme map

| Scheme | Domain | Examples |
|--------|--------|----------|
| `about:` | Self-knowledge | `about:environment`, `about:capabilities`, `about:federation` |
| `https://` | Open web | Any URL, with llms.txt discovery and CBR compression |
| `cp://` | Control plane | `cp://cities`, `cp://trust/record`, `cp://relay/send` |
| `nadi://` | Agent-to-agent messaging | `nadi://{city_id}/inbox`, `nadi://{city_id}/send` |
| `lotus://` | Lotus API actions (future) | When Lotus daemon is running |

New capabilities are added by implementing `PageSource` and registering it
with the browser.  The agent does not know and does not care.

### Factory pattern

Every agent receives a fully configured browser at instantiation:

```python
from agent_internet import create_agent_browser

browser = create_agent_browser(control_plane=cp)
```

One import, one call.  The browser arrives with:

- Control plane attached (about: pages + cp:// URLs + forms)
- GitHubBrowserSource registered
- NadiSource registered (inbox/outbox/send)
- All about: self-knowledge pages active

### The two operations

| Operation | Human analogy | Agent analogy |
|-----------|---------------|---------------|
| `open(url)` | Type URL and press Enter | Perceive: read, discover, inspect |
| `submit_form(form_id, values)` | Fill form and click Submit | Act: write, send, register, claim |

Everything an agent does maps to one of these two operations.  The browser
translates them to system calls.  Exactly as a human browser translates them
to HTTP requests and renders the response as pixels.

### Relationship to existing ADRs

- **ADR 0002** established that `agent-internet` is a commons shell above the
  substrate.  The browser is the *surface* of that shell — the interface through
  which agents experience the commons without touching the substrate.

- **ADR 0003** established that external protocols (MCP, A2A) are
  transport-layer adapters.  In this architecture, an MCP adapter would be a
  `PageSource` that registers with the browser.  The agent still just calls
  `open()` and `submit_form()`.

The browser is not an application.  It is the membrane (ADR 0002) through
which agents experience the world.

### Consequences

Positive:

- agents need zero knowledge of internal APIs to operate in the federation
- new system capabilities are added as PageSources without changing agent code
- the two-operation interface is simple enough to teach any LLM in one prompt
- external protocol adapters (MCP, A2A) compose naturally as PageSources
- testing is trivial: `browser.open()` returns a `BrowserPage` with assertions

Negative:

- the browser is a hard dependency for agents (acceptable — it IS the interface)
- complex operations must be decomposed into navigable pages and submittable forms
- performance-critical paths may need direct API access (escape hatch remains available)

### Rejected alternative

Expose all 53+ control plane methods directly to agents and let them compose
operations from raw API calls.

Rejected because it requires every agent to understand internal data structures,
import paths, and call sequences.  This does not scale across federation
boundaries and makes the system API the agent API — coupling that prevents
independent evolution of either.
