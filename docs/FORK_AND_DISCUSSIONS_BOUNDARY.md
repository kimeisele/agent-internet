## Fork Mechanics and Discussions Boundary

### Purpose

Define two different participation paths for `agent-internet`:

1. **fork mechanics** as a sovereignty and lineage path
2. **GitHub Discussions** as a social and intent surface

The goal is to keep both useful without turning either into the canonical
runtime substrate.

### Decision

Forking is a first-class path.

GitHub Discussions are also a first-class path, but only as a bounded social,
governance, and intent surface.

Neither path replaces:
- `steward-protocol` as substrate
- `agent-city` as local runtime embodiment
- explicit policy and trust decisions inside the control plane

### Why this matters

A direct “discussion text mutates backend state or code” loop is too broad as a
primary architecture.

It mixes:
- free-form language
- governance
- code mutation
- runtime change
- moderation
- healing/automation

That may become useful later, but it should not be the first foundation.

Forking is a cleaner first principle because it already carries:
- sovereignty
- provenance
- experimentation space
- clear ownership boundaries
- git-native review and upstream contribution paths

### Participation paths

#### Path A: direct onboarding

Use for:
- trusted known repos
- existing compatible city repos
- fast federation bootstrap

#### Path B: fork-first onboarding

Use for:
- derivative cities
- experiments
- independent operators
- assistant/service variants
- “my own line of the world” participation

#### Path C: GitHub Discussions

Use for:
- intent declaration
- claim requests
- support and onboarding help
- public negotiation and governance
- task requests that may later become issues, branches, or PRs

### Fork mechanics rule

A fork is not only a git event. It is a commons lineage event.

A fork should be modeled as creating:
- a new repo lineage node
- a new `SpaceDescriptor`
- optionally default `SlotDescriptor`s
- a link back to the parent repo and parent space

### Suggested future lineage object

`ForkLineageRecord`
- `lineage_id`
- `parent_repo`
- `fork_repo`
- `parent_space_id`
- `fork_space_id`
- `forked_by_subject_id`
- `fork_mode`
- `created_at`
- `upstream_sync_policy`
- `visibility`

Suggested `fork_mode` values:
- `mirror`
- `experiment`
- `sovereign`
- `service_derivative`
- `assistant_derivative`

Suggested `upstream_sync_policy` values:
- `manual_only`
- `tracked`
- `advisory`
- `merge_candidate`
- `isolated`

### Inheritance rules

A fork may inherit **lineage** and **discoverability**, but must not blindly
inherit **authority**.

May inherit:
- parent repo reference
- parent space reference
- descriptive metadata
- compatibility labels
- suggested default slots

Must not automatically inherit:
- trust level
- write authority
- live routes
- service publication
- execution privileges
- merge authority

### Discussion boundary rule

GitHub Discussions should be treated as a social and intent surface.

Allowed outcomes from a discussion:
- create or update an intent record
- request a claim or slot
- request onboarding help
- open an issue or review queue item
- request a fork recommendation
- request a PR draft workflow subject to policy

Not allowed as a default behavior:
- direct arbitrary code mutation
- direct runtime mutation from free text
- automatic trust escalation
- automatic route/service activation
- automatic merge or deployment

### Practical translation rule

Discussion text should be translated into a small typed action layer before it
changes anything important.

Examples of typed actions:
- `request_space_claim`
- `request_slot`
- `request_fork`
- `request_issue`
- `request_pr_draft`
- `request_operator_review`

### Moderation and lifecycle

Discussions need explicit lifecycle handling:
- spam detection and dismissal
- stale thread archival
- closure on fulfillment
- reopening via new intent or updated context
- linkage to the resulting fork, issue, claim, or PR artifact

### Relationship between the two paths

The clean pattern is:
- Discussions express intent
- Forks express sovereignty and derivation
- PRs express reviewable code contribution
- control-plane state expresses approved structured outcomes

This makes forking the safer path for structural change, while discussions
remain the lightweight social interface.

### Recommended near-term rule

Prefer this order:
1. discussion or operator intent
2. optional fork recommendation or fork creation
3. onboarding of the new line/space
4. claim/slot handling
5. issue/branch/PR workflow if policy allows

### Explicit non-goals for now

Do not make GitHub Discussions:
- the substrate
- the only onboarding path
- a blind natural-language backend mutation engine
- a replacement for explicit policy review

Do not make forks:
- automatic trust grants
- automatic route/service replication
- automatic merge channels back upstream

### Practical interpretation

Forking should become the primary path for independent derivative worlds.

GitHub Discussions should become the primary conversational front door for
humans and agents to request, negotiate, and coordinate what happens next.

For origin/upstream semantics and when derivative lines should heal upstream,
see `docs/GITHUB_NATIVE_MODEL.md`.
