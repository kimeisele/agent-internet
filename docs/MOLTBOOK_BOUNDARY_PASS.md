## Moltbook Boundary Pass

### Purpose

Define the clean boundary for `MoltbookAssistant` across `agent-city`,
`agent-internet`, `steward`, and `steward-protocol`.

This is a boundary pass, not an extraction plan yet.

### Verified current state

#### `agent-city`

`MoltbookAssistant` already exists and is wired as a city-local service.

Verified in:
- `city/factory.py` → `_build_moltbook_assistant()`
- `city/runtime.py` → `build_city_runtime()` / `persist_city_runtime()`
- `city/phases/__init__.py` → `PhaseContext.moltbook_assistant`
- `city/hooks/dharma/contracts_issues.py` → `on_dharma(ctx.heartbeat_count)`
- `city/karma_handlers/assistant.py` → `on_karma(...)`
- `city/hooks/moksha/outbound.py` → `on_moksha()`
- `city/moltbook_assistant.py` → phase methods + snapshot/restore

Current role inside `agent-city`:
- follow discovered agents during GENESIS
- plan invites/content during DHARMA
- execute invites/posts during KARMA
- return engagement metrics during MOKSHA
- use local `Pokedex` data and city stats
- persist assistant-local state across runtime restarts

#### `agent-city` Moltbook bridge

`MoltbookBridge` is also city-local today.

Verified in:
- `city/runtime.py` → `_wire_moltbook_bridge()`
- `city/hooks/genesis/moltbook_scan.py` → `scan_submolt()`
- `city/hooks/moksha/outbound.py` → `post_city_update()` / `post_mission_results()`
- `city/moltbook_bridge.py` → scan/post/snapshot/restore

Current role:
- read `m/agent-city` and DM/feed surfaces
- discover agents and code signals
- post city updates, mission summaries, and agent insight posts

#### `steward-protocol`

Heartbeat authority is strongest here.

Verified in:
- `vibe_core/plugins/moltbook/plugin_main.py`
- `vibe_core/plugins/moltbook/managers/heartbeat.py`

Current role:
- Mahamantra tick wiring
- Moltbook heartbeat orchestration
- phase-aware heartbeat dispatch
- heartbeat counters and snapshot state

#### `agent-internet`

`agent-internet` already bridges into city ticks but does not own heartbeat
authority.

Verified in:
- `agent_internet/agent_city_phase_tick_bridge.py`

Current role:
- call into `agent-city` runtime cycles
- collect tick outputs
- operate as federation/coordination shell above the runtime

#### `steward`

Present locally, but not verified here as canonical timing authority.
Treat it as a likely source of higher-level assistant logic, not the substrate.

### Boundary decision

#### What stays in `agent-city` for now

Keep these local for now:
- `MoltbookAssistant` phase methods (`on_genesis`, `on_dharma`, `on_karma`, `on_moksha`)
- direct dependence on local `Pokedex` and city stats
- `MoltbookBridge` scan/post behavior tied to city heartbeat reflections
- local assistant and bridge persistence

Reason:
- the assistant currently acts on city-local state
- the bridge currently posts city-local reports and mission summaries
- extraction right now would cut through working runtime seams

#### What belongs to `steward-protocol`

Keep canonical heartbeat authority there:
- tick rhythm
- heartbeat sequencing
- Moltbook heartbeat orchestration
- substrate semantics

Rule:
`agent-internet` and `agent-city` may follow or embody the heartbeat,
but should not redefine it.

#### What belongs to `agent-internet`

`agent-internet` should become the outer assistant surface, not the inner
heartbeat brain.

Good future responsibilities:
- public/operator view of assistant state
- multi-repo discovery of assistant-bearing cities/spaces
- commons-level claims/leases for assistant presence
- HTTP/CLI/git/wiki surfaces for assistant visibility
- federation-safe coordination of social/operator tasks

This means `agent-internet` can host a Moltbook-facing social shell later,
without immediately moving all posting logic out of `agent-city`.

### Recommended short-term shape

Do **not** extract `MoltbookAssistant` yet.

Instead:
1. treat `agent-city` as the current runtime embodiment
2. treat `agent-internet` as the visibility / coordination shell
3. treat heartbeat as upstream from `steward-protocol`
4. expose assistant state through adapters before moving behavior

### First safe implementation slice

The next code slice should be small:

1. define an `AssistantSurfaceSnapshot` model in `agent-internet`
2. let `agent-internet` read/export assistant state from an `agent-city` runtime
3. expose that snapshot through CLI/HTTP/git/wiki projections
4. do **not** move phase execution or content generation yet

### Explicit non-goals for now

Do not do these yet:
- rewrite `MoltbookAssistant` into `agent-internet`
- duplicate heartbeat orchestration in `agent-internet`
- replace city-local `Pokedex` planning with multi-repo heuristics
- build PR-writing/code-writing automation into the assistant before claims,
  slots, and access policy are modeled

### Practical interpretation

Right now the clean sentence is:

`MoltbookAssistant` lives in `agent-city`, follows heartbeat authority from
`steward-protocol`, and should later be surfaced through `agent-internet`
as a federation-visible social/operator shell rather than being prematurely
ripped out of the city runtime.

