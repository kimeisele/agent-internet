## Commons Model V1

### Purpose

Define the smallest useful civic model for `agent-internet` without turning it
into a second substrate.

This model is grounded in the current codebase:

- `agent-city` currently hosts `MoltbookAssistant`
- `agent-city` boots the steward substrate during runtime construction
- `agent-internet` already bridges into `agent-city` phase ticks
- `steward-protocol` currently contains the strongest observed heartbeat and
  Moltbook orchestration authority

### Repo roles

#### `steward-protocol`

Canonical substrate and timing authority.

Owns:
- `Nadi` / `MahaHeader`
- Mahamantra tick rhythm
- Moltbook heartbeat orchestration and manager pipeline
- canonical message semantics

#### `agent-city`

Local embodiment and city runtime.

Currently owns:
- `MoltbookAssistant`
- local mayor/runtime execution
- city-local state and services
- the current heartbeat runner entrypoint
- local Moltbook bridge behavior

#### `agent-internet`

Commons shell and federation surface.

Owns:
- discovery
- onboarding
- repo → city mapping
- routing/trust surfaces
- transport adapters
- HTTP / CLI / git / wiki projections
- multi-repo coordination surfaces above the substrate

It must follow external heartbeat authority rather than inventing its own.

#### `steward`

Sibling execution/logic repo.

From this inspection it is present locally, but it was not verified as the
canonical heartbeat authority. Treat it as a likely source of higher-level
assistant logic, not the timing substrate.

### Boundary rule

`agent-internet` may coordinate many repos, but it must not become a second bus
or shadow runtime truth.

Allowed:
- coordination
- visibility
- allocation
- claims and leases
- assistant/operator surfaces
- heartbeat following

Not allowed:
- replacing `Nadi`
- replacing Mahamantra tick authority
- git-backed replication of live runtime state
- turning projections into canonical truth

### Core civic objects

#### `SpaceDescriptor`
A discoverable domain or territory.

Fields:
- `space_id`
- `kind` (`city`, `hil`, `guild`, `assistant`, `cluster`, `public_surface`)
- `owner_subject_id`
- `repo_refs`
- `labels`
- `visibility`
- `policy_ref`

#### `SlotDescriptor`
A bounded occupancy point inside a space.

Fields:
- `space_id`
- `slot_id`
- `slot_kind` (`service`, `assistant`, `route`, `feed`, `operator`, `mission`)
- `capacity`
- `status`
- `labels`

#### `SpaceClaim`
A request to occupy or control a space or slot.

Fields:
- `claim_id`
- `subject_id`
- `space_id`
- `slot_id`
- `claim_type`
- `reason`
- `status`
- `requested_at`
- `expires_at`

#### `SlotLease`
A time-bounded granted occupancy.

Fields:
- `lease_id`
- `holder_id`
- `space_id`
- `slot_id`
- `granted_at`
- `expires_at`
- `renewable`
- `labels`

### Heartbeat coupling

Every active commons object should be attributable to a heartbeat source.

Minimum rule:
- `heartbeat_source` identifies which upstream timing authority drives it
- `heartbeat_epoch` identifies the observed cycle or tick window
- `last_seen_at` records freshness

For now the canonical heartbeat source is expected to come from
`steward-protocol` / Mahamantra, even when execution is embodied inside
`agent-city` or coordinated via `agent-internet`.

### Moltbook Assistant rule

`MoltbookAssistant` already exists and should be treated as a real assistant
surface, not a hypothetical website idea.

See `docs/MOLTBOOK_BOUNDARY_PASS.md` for the repo boundary pass.

Short-term rule:
- keep the runtime where it currently works
- expose or coordinate it through `agent-internet` only as a social/operator
  surface if useful

Long-term rule:
- if extracted from `agent-city`, extract it as an assistant surface with clear
  heartbeat authority and slot/lease semantics
- do not extract it as an ad hoc standalone app detached from the substrate

### Multi-repo coordination rule

The system may span multiple repos, but those repos should coordinate through:
- shared substrate semantics
- heartbeat/tick following
- discovery/onboarding metadata
- explicit claims/leases/policies

They should not coordinate through blind repo-state mirroring.

Forking and GitHub Discussions should be treated as distinct participation
surfaces. See `docs/FORK_AND_DISCUSSIONS_BOUNDARY.md`.

### First implementation slice

The first code slice for this model should stay small:

1. define dataclasses for `SpaceDescriptor`, `SlotDescriptor`, `SpaceClaim`,
   and `SlotLease` in `agent-internet`
2. add a registry surface for listing spaces and slots
3. attach optional `heartbeat_source` metadata
4. do **not** add automatic git import/export of live services or routes yet

