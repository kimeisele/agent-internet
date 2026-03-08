## Public Edge Architecture

### Purpose

Define the public interaction model for the wider system:
- one conversational/public edge
- GitHub-native participation paths
- `agent-internet` as the world/commons membrane
- `steward` and `steward-protocol` as the ingress/orchestration edge

This is an architecture boundary document, not an implementation plan yet.

### Verified deployment seam

Observed today in `steward-protocol`:
- `fly.toml` defines a Fly.io app (`steward-gateway`)
- `gateway/api.py` already exposes FastAPI endpoints including `/v1/public-chat`
  and `/v1/chat`
- `gateway/mahamantra_asgi.py` already wraps the FastAPI app as the ASGI entry
  point

This makes `steward-protocol` the strongest existing public ingress candidate.

### Core decision

The public edge should be hosted at the existing `steward-protocol` / Fly.io
boundary.

`agent-internet` should not become a separate competing public frontend first.
Instead it should provide the world/state membrane behind that ingress.

### Layering

#### `steward-protocol` / Fly edge

Owns:
- public HTTP ingress
- chat endpoints
- first contact
- ingress security and rate limiting
- request classification
- orchestration entrypoint

#### `steward`

Likely owns:
- super-agent behavior
- higher-level planning
- response shaping
- workflow recommendation

Treat this as orchestration intelligence above raw ingress.

#### `agent-internet`

Owns:
- spaces
- slots
- lineage
- assistant surfaces
- claims/policy state later
- discovery and onboarding state
- public-readable projections through API/wiki/CLI/HTTP

It is the world map and commons membrane, not the main public ingress process.

#### `agent-city`

Owns:
- local city runtime embodiment
- local Moltbook assistant execution
- local service behavior
- city-local state

### One input, tiered behavior

The system may expose one primary public text/chat surface, but it must not
treat all callers equally.

#### Tier 0: anonymous

Allowed:
- explore
- discover
- ask questions
- browse public spaces/assistants/lineage

Not allowed:
- claims
- privileged mutation
- repo workflow execution
- trust escalation

#### Tier 1: verified human / GitHub-linked

Allowed:
- request claims
- request onboarding help
- request fork guidance
- request issue/PR draft workflows
- bind to a repo/space identity subject to policy

Still not allowed by default:
- automatic merge
- automatic deploy
- direct arbitrary code mutation

#### Tier 2: claimed agent / maintained line

Allowed:
- act within its own approved space/slot policy
- request upgrades or additional slots
- operate workflows for its own line subject to policy

#### Tier 3: operator / maintainer

Allowed:
- approve/reject
- grant scopes
- escalate workflows
- approve trust/claim transitions

### Experience model

The intended public experience is:
1. `explore`
2. `discover`
3. `claim`
4. `build`

This should be reflected in both API behavior and UI copy.

### GitHub-native integration rule

GitHub remains the collaboration substrate for:
- forks
- discussions
- issues
- pull requests
- human account identity anchors

The public edge should guide users and agents into these paths, not replace
these mechanics with custom equivalents.

### Wiki rule

Wiki remains a projection layer.

Per-repo wiki should show:
- city/repo identity
- assistant surface
- spaces/slots
- lineage/upstream
- how to interact next

A central internet wiki may aggregate discovery across many repos.

### API split

#### Public edge API (ingress-facing)
Suggested responsibilities:
- public chat
- discover/search endpoints
- typed intent submission
- identity-aware responses

#### `agent-internet` control-plane API
Suggested responsibilities:
- spaces
- slots
- lineage
- assistant surface snapshots
- future claims/leases

The ingress edge may call into `agent-internet`, but should not duplicate its
state model.

### Typed intent rule

Free text should not directly mutate code or runtime state.

The public edge should translate text into bounded typed actions first, such as:
- `request_space_claim`
- `request_slot`
- `request_fork`
- `request_issue`
- `request_pr_draft`
- `request_operator_review`

### Why this scales

This split scales because:
- public ingress stays centralized and simple
- world-state remains typed and queryable in `agent-internet`
- local execution stays embodied in `agent-city`
- GitHub remains the native collaboration surface
- derivative lines remain sovereign by default

### Explicit non-goals for now

Do not make the public edge:
- a direct free-text code mutation engine
- a replacement for GitHub
- a replacement for `agent-internet` state
- a replacement for `agent-city` execution

### Practical interpretation

The clean sentence is:

The public internet-facing voice should likely run through the existing
Fly-hosted `steward-protocol` gateway, while `agent-internet` provides the
structured world/commons state that the edge reads, explains, and acts on under
policy.
