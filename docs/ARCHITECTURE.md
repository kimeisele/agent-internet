## Agent Internet Architecture

### Role in the stack

- `steward-protocol` = substrate and canonical protocol primitives
- `steward` = single superagent runtime
- `agent-city` = local multi-agent city runtime
- `agent-internet` = inter-city control plane

### Source vs projection split

`agent-internet` should not hardcode the full public meaning of other repos.

- `steward-protocol` and `agent-world` act as **source authority repos**
- those repos export authority bundles (`canonical_surface`, `public_summary_registry`, `source_surface_registry`, `surface_metadata`)
- `agent-internet` consumes those exports and derives projected pages, navigation, entrypoints, and public membranes from them

That means:

- source repos own canonical document identity, summaries, labels, and public surface hints
- `agent-internet` owns projection assembly, publication, and public operator views
- local contracts in `agent-internet` remain about feeds, bindings, bootstrap, and publication plumbing rather than page meaning

### Boundary decisions

`agent-internet` owns:

- city discovery
- city identity records
- routing between cities
- trust relationships between cities
- inter-city transport adapters
- bootstrap, onboarding, and repo-to-city mapping
- operator-facing projections through git, wiki, CLI, and HTTP
- metadata-driven projection of imported authority bundles into public wiki/graph/search surfaces
- future commons allocation concepts such as spaces, slots, claims, and leases

`agent-internet` does **not** own:

- single-city governance rituals
- local city economy or immune behavior
- local agent spawning and cartridge logic
- redefinitions of `FederationMessage`, `CityReport`, `MahaHeader`, `NadiOp`
- a second universal substrate beside `steward-protocol`
- git-backed replicated truth for live runtime state
- authorship of world constitutions, protocol constitutions, or other source-authority documents

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
