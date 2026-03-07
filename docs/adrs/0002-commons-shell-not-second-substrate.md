## ADR 0002: Agent Internet acts as a commons shell, not a second substrate

### Status

Accepted.

### Context

`steward-protocol` already defines the canonical communication substrate:

- `Nadi`
- `MahaHeader`
- federation message primitives

`agent-city` already hosts the local runtime where city behavior, governance, and
agent life actually occur.

As `agent-internet` gained git, wiki, HTTP, onboarding, routing, and projection
surfaces, a new risk became visible: accidentally turning it into a second
distributed substrate or a git-backed shadow control plane.

At the same time, there is a valid need for a broader federation commons:

- repo-to-city discovery
- onboarding and visibility
- public/operator surfaces
- future claimable shared spaces or slots
- policy-bearing access surfaces for many participants, not just one operator

### Decision

`agent-internet` remains a federation commons and control shell above the real
substrate, not a replacement for it.

It will own:

1. bootstrap and onboarding
2. discovery and repo-to-city mapping
3. inter-city routing and trust surfaces
4. transport adapters and operator-facing projections
5. optional civic allocation objects such as `space`, `slot`, `claim`, and `lease`

It will not own:

1. a new universal message bus
2. a replacement for `Nadi` / `Maha`
3. git-backed replicated truth for live routes, services, or runtime state
4. city-local governance, economy, or agent lifecycle logic

### Boundary rule

The canonical layering is:

- `steward-protocol` = substrate and canonical communication semantics
- `agent-city` = local runtime and city behavior
- `agent-internet` = discovery, onboarding, routing, trust, adapters, and projections

Git, wiki, CLI, and HTTP surfaces inside `agent-internet` are views,
onboarding channels, and operator tools. They are not the underlying
communication substrate and must not silently become a second one.

### Future commons model

If `agent-internet` grows toward a broader commons, it should do so through a
small civic model instead of protocol duplication.

Initial concepts:

- `space` = a discoverable claimable domain or territory
- `slot` = a bounded occupancy point inside a space
- `claim` = a request to occupy or control a space/slot
- `lease` = a time-bounded grant, renewal, or delegation

These concepts belong to discovery, allocation, visibility, and policy. They do
not replace message transport.

### Consequences

Positive:

- prevents `agent-internet` from drifting into a shadow substrate
- keeps git/wiki/HTTP useful without making them truth replicas
- gives a clean place for future commons or territory mechanics
- preserves `steward-protocol` as the canonical communication layer

Negative:

- some tempting repo-import ideas should be rejected or delayed
- human-readable projections stay secondary to live runtime state
- future commons features need explicit modeling instead of ad hoc sync files

### Rejected alternative

Promote git projections, wiki content, or repo-exported state into a general
replication layer for routes, services, and runtime truth.

Rejected because that would duplicate the substrate boundary, create confusing
multiple sources of truth, and make the system harder to reason about.
