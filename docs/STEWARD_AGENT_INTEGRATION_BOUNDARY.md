## Steward-Agent Integration Boundary

### Purpose

Define the clean integration seam between:
- `steward-protocol` as substrate
- `agent-internet` as semantic commons membrane
- `steward` / `steward-agent` as reasoning consumer

This document exists to prevent spaghetti integration.

### Verified package and repo mapping

Observed locally:
- GitHub repo `steward-protocol` publishes PyPI package `steward-protocol`
- GitHub repo `steward` publishes PyPI package `steward-agent`
- Python import for the superagent repo is `steward`
- GitHub repo `agent-internet` publishes Python package/import `agent_internet`

Important consequence:
- `steward-protocol` should be broadly installable
- `steward-agent` should be broadly installable
- `agent-internet` does **not** need to be a general-purpose PyPI dependency for the world to use the system

`agent-internet` should be understood first as a GitHub-native published
federation membrane, with typed Lotus HTTP/API surfaces acting as authenticated
operator/integration seams rather than the canonical public surface.

### Core decision

Do **not** begin by modifying `steward`.

First stabilize the contract that `steward-agent` is allowed to consume from
`agent-internet`.

Only after that should a small adapter be added in `steward`, and that adapter
must be read-oriented and minimal.

### Agent-city primacy and derived-surface rule

`agent-city` remains the primary living/execution system.

`agent-internet` is derived from that world as a typed public/commons membrane:
- discovery
- read models
- semantic/public index state
- typed API/HTTP/CLI surfaces

This means `agent-internet` is not a rival brain or alternate root of truth.

It is best understood as a separated-but-derived layer in the broader
`agent-city` system boundary.

### Wrapper rule for future steward server mode

If `steward` later adds an HTTP/FastAPI server mode so `agent-city` or other
systems can call through `steward`, that wrapper should prefer one of these
roles:

- consume `agent-internet` directly as a client
- proxy `agent-internet` contracts outward
- add auth/caching/composition around the same contracts

It should **not** invent a second private semantic contract when the provider
contract already exists in `agent-internet`.

In other words:
- `agent-internet` should publish the semantic standard
- `steward` may consume, proxy, or compose that standard
- `steward-protocol` remains the substrate and ingress/plumbing layer

### Layer ownership

#### `steward-protocol`

Owns:
- Nadi semantics
- transport/envelope shape
- public ingress patterns
- gateway and relay-facing substrate concerns
- provider and platform plumbing

Must not be reimplemented in `agent-internet` or `steward-agent`.

#### `agent-internet`

Owns:
- typed public/commons state
- federated discovery and index state
- semantic overlay and WordNet bridge weighting
- semantic graph neighbors
- explainable semantic search results
- Lotus API / daemon surfaces for this world-state

It is a world/commons membrane, not the superagent brain.

#### `steward` / `steward-agent`

Owns:
- reasoning
- planning
- synthesis across cities/repos
- use of external semantic context
- optional decision and action recommendation

It consumes `agent-internet`; it does not replace it.

### Integration rule

The first `steward-agent` integration should be **read-only**.

Allowed first-step consumption:
- semantic search
- semantic neighbors
- query expansion metadata
- explainable match context

Disallowed first-step coupling:
- direct free-text mutation through `agent-internet`
- duplicating control-plane state inside `steward`
- re-implementing Nadi routing or Lotus state logic inside `steward`
- deep identity/user modeling inside `agent-internet`

### Stable authenticated `agent-internet` read surfaces

The following Lotus daemon endpoints are the current read contract for a future
`steward-agent` adapter:

- `GET /v1/lotus/agent-web-federated-search`
- `GET /v1/lotus/agent-web-semantic-neighbors`
- `GET /v1/lotus/agent-web-semantic-expand`
- optionally `GET /v1/lotus/agent-web-federated-index`

The refresh endpoint exists, but is not the first consumer seam:
- `POST /v1/lotus/agent-web-federated-index/refresh`

That refresh path should remain an operator/control-plane concern unless a later
design explicitly delegates it.

These Lotus seams are companion read surfaces for authenticated steward
integration. The canonical public membrane still lives in GitHub-published
authority artifacts plus agent-web/wiki projection documents.

### Minimal search contract for `steward-agent`

For `agent-web-federated-search`, a future consumer may rely on these fields:

- top-level:
  - `kind`
  - `query`
  - `results`
  - `query_interpretation`
  - `matched_semantic_bridges`
  - `wordnet_bridge`
  - `semantic_extensions`
  - `stats`
- per result:
  - `record_id`
  - `kind`
  - `title`
  - `summary`
  - `source_city_id`
  - `source_repo`
  - `href`
  - `score`
  - `matched_terms`
  - `why_matched`

Within `why_matched`, the consumer may rely on:
- `direct_term_matches`
- `expanded_term_matches`
- `semantic_bridge_matches`
- `semantic_neighbor_count`
- `top_semantic_neighbors`

`steward-agent` should not assume more than this subset is stable.

### Minimal semantic-neighbor contract for `steward-agent`

For `agent-web-semantic-neighbors`, a future consumer may rely on:

- top-level:
  - `kind`
  - `record`
  - `neighbors`
  - `stats`
- in `record`:
  - `record_id`
  - `kind`
  - `title`
  - `source_city_id`
  - `href`
- per neighbor:
  - `record_id`
  - `kind`
  - `title`
  - `source_city_id`
  - `href`
  - `score`
  - `reason_kinds`
  - `shared_terms`
  - `bridge_ids`
  - `wordnet_score`

This is enough for reasoning and explanation without coupling the consumer to
internal graph-building heuristics.

### Auth rule

Current Lotus daemon surfaces are authenticated.

The minimal read integration should use:
- `AGENT_INTERNET_LOTUS_BASE_URL`
- `AGENT_INTERNET_LOTUS_TOKEN`
- optional `AGENT_INTERNET_LOTUS_TIMEOUT_S`

Required scope for the read token:
- `lotus.read`

For consistency, future `steward-agent` integration should prefer reusing the
same env naming already used around the `steward-protocol` bridge rather than
inventing a second naming scheme.

### Nadi and relay rule

`steward-agent` may sit above Nadi-aware substrate layers, but it should not
rebuild transport semantics just to consume semantic search.

Meaning:
- Nadi stays a substrate concern in `steward-protocol`
- Lotus/HTTP is an acceptable read seam into `agent-internet`
- semantic search payloads are business/context objects, not transport objects

If public ingress later forwards search/context through a Nadi-aware path, that
forwarding should still terminate in the same typed `agent-internet` read model.

### Identity rule

`agent-internet` should know actors only at typed public/operational depth, for
example:
- city ids
- subject ids
- spaces
- slots
- service handles
- token scopes
- typed intents and lineage records

It should **not** become the place that stores detailed inner user psychology or
private agent memory.

That deeper memory/reasoning layer belongs in `steward-agent` or local city-side
state, not in the commons membrane.

### Recommended first adapter behavior

When a later adapter is added in `steward`, it should do only this:
1. issue a federated semantic search query
2. read top results plus `why_matched`
3. optionally fetch semantic neighbors for the best record ids
4. transform those payloads into local reasoning context
5. keep inference local to `steward-agent`

It should not:
- mutate `agent-internet` state from free text
- mirror the whole federated index locally
- depend on internal implementation details beyond the stable subset above

### Practical interpretation

The clean sentence is:

`steward-agent` should consume `agent-internet` as a typed semantic world-memory
surface over authenticated Lotus reads, while `steward-protocol` remains the
transport/public-ingress substrate and `agent-internet` remains ignorant of deep
private user detail.