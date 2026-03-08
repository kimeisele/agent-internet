## GitHub-Native Model

### Purpose

Define how `agent-internet` uses GitHub-native mechanics without reinventing a
parallel platform.

This model answers the scaling question:
- where is origin?
- when should a derivative line heal upstream?
- when should it stay sovereign?

### Core rule

GitHub remains the primary participation surface for:
- forks
- discussions
- issues
- pull requests
- human account identity

`agent-internet` should only interpret, project, and coordinate these mechanics
into typed commons/control-plane state.

It must not replace GitHub with a custom forum, PR system, or identity stack.

### Origin and upstream

#### `origin`
The repo a participant is currently operating in.

#### `upstream`
The canonical parent line that a fork derives from.

#### `line root`
The oldest still-relevant ancestor for a family of derivatives.

Important rule:
A fork has one immediate upstream, but a lineage may have many descendants.

### Scaling rule

A derivative world must **not** be assumed to heal upstream by default.

Default expectation:
- a fork is sovereign
- local adaptation stays local unless explicitly proposed upstream
- upstream healing is a governed contribution path, not an automatic duty

This is what keeps the system scalable.

If every fork is expected to continuously heal the root, the root becomes a
coordination bottleneck and the whole model collapses into noisy centralization.

### Upstream contribution classes

A derivative line may classify changes as:
- `local_only`
- `upstream_candidate`
- `upstream_required`
- `shared_pattern`

Meaning:
- `local_only` stays in the fork
- `upstream_candidate` may become an issue/PR upstream
- `upstream_required` indicates protocol or compatibility pressure
- `shared_pattern` should likely become a reusable module or documented pattern

### Practical upstream rule

A fork should only try to heal upstream when at least one of these is true:
- the change fixes a bug in the parent line
- the change restores protocol compatibility
- the change improves a shared abstraction rather than a local preference
- the parent project explicitly asked for derivative feedback

Otherwise, keep it local.

### GitHub object mapping

#### Fork → lineage event
GitHub fork becomes:
- lineage relationship
- possible new `SpaceDescriptor`
- optional default slots
- fork policy metadata

#### Discussion → typed intent
GitHub Discussion becomes:
- `DiscussionIntentRecord`
- only after classification into a bounded action type

#### Issue → tracked work item
GitHub Issue becomes:
- a reviewable work artifact
- optional linkage to a claim, slot, or operator queue

#### Pull Request → upstream proposal
GitHub PR becomes:
- a governed contribution artifact
- explicit evidence that a derivative line wants to affect another line

### Suggested future records

#### `ForkLineageRecord`
- `lineage_id`
- `repo`
- `upstream_repo`
- `line_root_repo`
- `fork_mode`
- `sync_policy`
- `space_id`
- `upstream_space_id`
- `forked_by_subject_id`
- `created_at`

#### `DiscussionIntentRecord`
- `intent_id`
- `repo`
- `discussion_id`
- `author_subject_id`
- `intent_type`
- `status`
- `linked_space_id`
- `linked_slot_id`
- `linked_issue_url`
- `linked_pr_url`
- `created_at`
- `updated_at`

### Safe participation flow

Recommended order:
1. a person/agent speaks in GitHub Discussion
2. the system classifies it into a bounded typed intent
3. the intent may suggest a fork, issue, or PR path
4. structural independence happens via fork
5. upstream influence happens via issue/PR, not direct runtime mutation

### Anti-pattern to avoid

Do not make this the default loop:
- discussion text arrives
- backend mutates state/code directly
- fork/upstream distinctions are ignored
- PR appears as an afterthought

That does not scale.

### What scales better

This does scale:
- GitHub as the human/agent collaboration surface
- forks for sovereignty
- PRs for upstream healing
- issues for explicit tracked work
- `agent-internet` for typed projection, policy, and visibility

### Practical interpretation

The right question is not:
- “should every fork heal origin?”

The right question is:
- “what kind of change is this, and does it belong locally, upstream, or as a reusable shared pattern?”

That is the decision boundary that keeps the model effective and scalable.
