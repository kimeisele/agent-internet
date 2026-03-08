## Agent Internet Architecture

### Role in the stack

- `steward-protocol` = substrate and canonical protocol primitives
- `steward` = single superagent runtime
- `agent-city` = local multi-agent city runtime
- `agent-internet` = inter-city control plane

### Boundary decisions

`agent-internet` owns:

- city discovery
- city identity records
- routing between cities
- trust relationships between cities
- inter-city transport adapters
- bootstrap, onboarding, and repo-to-city mapping
- operator-facing projections through git, wiki, CLI, and HTTP
- future commons allocation concepts such as spaces, slots, claims, and leases

`agent-internet` does **not** own:

- single-city governance rituals
- local city economy or immune behavior
- local agent spawning and cartridge logic
- redefinitions of `FederationMessage`, `CityReport`, `MahaHeader`, `NadiOp`
- a second universal substrate beside `steward-protocol`
- git-backed replicated truth for live runtime state

### Commons shell rule

`agent-internet` may grow into a federation commons layer, but only as a shell
around the canonical substrate.

- `space` = a discoverable claimable domain
- `slot` = a bounded occupancy point inside a space
- `claim` = a request to occupy or control a space/slot
- `lease` = a time-bounded grant or delegation

These concepts belong to discovery, allocation, visibility, and policy.
They do **not** replace `Nadi`, `MahaHeader`, or the underlying message bus.

See `docs/COMMONS_MODEL_V1.md` for the first concrete civic model draft.
See `docs/PUBLIC_EDGE_ARCHITECTURE.md` for the public ingress split.

### Phase 0

Phase 0 preserves the current federation contract already present in `agent-city`:

- `data/federation/nadi_outbox.json`
- `data/federation/nadi_inbox.json`
- `data/federation/reports/`
- `data/federation/directives/`

This allows `agent-internet` to begin as a compatibility control plane while the
transport remains file-based and git-friendly.

### Reuse policy

Import from `steward-protocol` when the symbol is canonical substrate:

- federation message types
- Nadi enums and constants
- `MahaHeader`

Adapt from `agent-city` when the concern is city-specific boundary shape:

- filesystem federation paths
- report and directive persistence semantics

### Next implementation layers

1. in-memory registry implementation
2. route resolution implementation
3. city trust ledger implementation
4. direct city-to-city transport beyond file relay
5. migration and treaty protocols on top of the same contracts
