## ADR 0001: Agent Internet starts as a control plane, not a replacement runtime

### Status

Accepted.

### Context

`agent-city` already contains working federation edges:

- `city/federation.py` for reports and directives
- `city/federation_nadi.py` for file-based Nadi exchange

`steward-protocol` already contains canonical protocol primitives:

- `vibe_core.mahamantra.federation.types`
- `vibe_core.mahamantra.substrate.state.nadi`
- `vibe_core.mahamantra.protocols._header`

The risk is building `agent-internet` by duplicating protocol types or by pulling
all city-local behavior into a new repo.

### Decision

`agent-internet` will:

1. reuse canonical substrate symbols from `steward-protocol`
2. preserve compatibility with the current Agent City federation filesystem shape
3. define internet-layer interfaces for registry, discovery, routing, trust, and transport
4. avoid a hard dependency on a specific city runtime package at the core layer

### Consequences

Positive:

- no new duplicate message schema
- existing Agent City installations remain compatible
- internet-layer code can evolve without swallowing city-local logic

Negative:

- early versions still inherit the limits of file-based federation transport
- some integration stays adapter-based until a direct transport exists

### Rejected alternative

Make `agent-internet` depend directly on `agent-city` internals for its core model.

Rejected because that would invert the layer boundary: the internet should connect
cities, not be defined by one concrete city runtime.
