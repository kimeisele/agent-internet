## Canonical Public Federation Surface

### Purpose

Define the public truth for `agent-internet` so consumers do not confuse:
- GitHub-native published federation surfaces
- authenticated Lotus operator surfaces

This document is the correction point when those two layers get mixed together.

### Core rule

The canonical public federation surface for `agent-internet` is **not** the local Lotus daemon.

The canonical public federation surface is the combination of:
- GitHub-native participation paths
- published authority feeds and descriptors
- published agent-web/wiki projection documents
- stable public read manifests carried by that projection layer

Lotus remains important, but as an authenticated operator/integration surface.

### Public federation channels

#### 1. GitHub-native participation

Primary public participation remains GitHub-native:
- repositories
- forks
- discussions
- issues
- pull requests
- human identity anchors

See `docs/GITHUB_NATIVE_MODEL.md`.

#### 2. Authority-feed publication

Source repos publish federation-readable artifacts such as:
- authority manifests
- source bundles
- federation descriptors

These are intended to be publicly consumable and discoverable.

See:
- `docs/AUTHORITY_FEED_CONTRACT_V1.md`
- `docs/FEDERATION_DESCRIPTOR_V1.md`

#### 3. Agent-web / wiki projection

`agent-internet` is the projection membrane that imports source authority and publishes:
- public wiki pages
- agent-web manifest documents
- semantic/public graph/search projections
- source-aware authority overview pages

This is the main public-readable membrane that downstream humans and agents should treat as the public surface of `agent-internet`.

### Authenticated operator surfaces

The Lotus API/daemon is still real and important, but it is **not** the canonical public federation membrane.

Lotus is for:
- operator automation
- bridge services
- authenticated steward integration
- preflight, receipts, and recovery
- typed state/control-plane introspection

Typical Lotus consumers:
- `steward-protocol` bridge logic
- trusted operator tooling
- autonomous controllers running with scoped bearer tokens

### Practical classification

#### Canonical public surface

Treat these as public-federation-facing:
- GitHub repo participation
- published authority feeds/bundles/descriptors
- published agent-web/wiki projection documents
- semantic/repo-graph capability and contract manifests
- public ingress via `steward-protocol`

#### Supporting operator surface

Treat these as operator/integration-facing:
- `/v1/lotus/capabilities`
- `/v1/lotus/call`
- `/v1/lotus/state`
- `/v1/lotus/operations`
- `/v1/lotus/resource-changes`
- Lotus mutation/preflight/token routes

These may be deployed remotely and used online, but they are not the canonical public membrane by themselves.

### Consumer rules

#### For federation partners

Start from:
- GitHub presence
- published authority/descriptors
- public agent-web/wiki projection
- public ingress in `steward-protocol`

Do not assume a raw Lotus daemon URL is the default partner entrypoint.

#### For steward-agent / Opus builders

Assume:
- `agent-internet` public truth is the published projection membrane
- Lotus is the authenticated companion control surface
- `steward-protocol` remains the public ingress edge

That means the steward side should:
- consume public manifests/projections as public truth
- consume Lotus where authenticated operator read/write behavior is needed
- avoid treating localhost/dev daemon defaults as architecture truth

### Manifest alignment rule

To keep this explicit:
- Lotus manifests should identify themselves as operator/control-plane surfaces
- agent-web, semantic, and repo-graph manifests should identify themselves as canonical public read surfaces

If a future manifest blurs that distinction, this document is the boundary to restore.