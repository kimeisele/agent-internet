## ADR 0003: External agent protocols are transport-layer concerns, not substrate peers

### Status

Proposed.

### Context

Multiple external standards now address agent interoperability:

- Anthropic's Model Context Protocol (MCP) standardizes how agents connect to
  external tools, databases, and APIs
- Google's Agent-to-Agent Protocol (A2A) standardizes how agents from different
  vendors communicate
- NIST launched the AI Agent Standards Initiative for interoperable agent
  ecosystems
- Additional protocols (ACP, vendor-specific agent buses) continue to emerge

As these standards gain adoption, a recurring question will arise: should
`agent-internet` adopt, implement, or integrate with them?

The answer depends on recognizing that these protocols and this stack solve
problems at different layers.

### Observation

MCP, A2A, and similar protocols are **communication protocols**. They answer:

- how does an agent call a tool? (MCP)
- how do two agents exchange messages? (A2A)
- how do agents from different vendors interoperate? (ACP, NIST goals)

This stack answers a different set of questions:

- where does an agent exist? (spaces, slots, cities)
- who owns it? (subject ids, claims, leases)
- how do sovereign worlds federate? (federation descriptors, trust ledger)
- how is meaning routed with intent? (Nadi semantics, typed intents)
- how does a fork remain sovereign? (fork lineage, sync policies)
- how is liveness established? (heartbeat coupling)

These are **existence and sovereignty concerns**, not communication concerns.

### Decision

External agent protocols (MCP, A2A, ACP, and future equivalents) are
transport-layer adapters in the `agent-internet` layering. They are not
substrate peers and must not be promoted to that role.

Concretely:

1. External protocols may be consumed through **bridge adapters** in the
   transport layer, alongside existing filesystem and HTTPS transports
2. An MCP tool-call may resolve to a Lotus API action internally
3. An A2A message may arrive as a Nadi envelope internally
4. External protocol semantics must not replace or duplicate Nadi routing
   semantics, Lotus API typed actions, or commons model objects
5. External protocol identity must not replace the existing subject/city/space
   identity model

### Layering

```
agent behavior / applications
─────────────────────────────────────
MCP adapter │ A2A adapter │ future    ← bridge adapters (transport)
─────────────────────────────────────
Lotus Protocol                        ← typed API (60+ actions, scoped auth)
─────────────────────────────────────
Nadi semantics + MahaHeader           ← message routing with intent
─────────────────────────────────────
commons model (spaces/slots/claims)   ← existence and sovereignty
+ trust engine + heartbeat coupling
─────────────────────────────────────
cities (sovereign runtimes)           ← embodiment
```

An MCP adapter translates an MCP tool invocation into a Lotus action.
An A2A adapter translates an A2A agent message into a Nadi envelope.

The adapter owns the translation. It does not promote external semantics
into the layers below it.

### Absorption rule

When integrating an external protocol:

- the adapter lives in `agent_internet/adapters/` or equivalent
- the adapter imports Lotus API actions and transport interfaces
- the adapter does not import or re-expose external protocol types in core
  modules
- the adapter does not require core modules to know about the external protocol
- external protocol dependencies remain optional package extras, not core
  requirements

### What this stack provides that external protocols do not

| Concern | External protocols | This stack |
|---------|-------------------|------------|
| Tool connection | MCP | Lotus API typed actions |
| Agent-to-agent messaging | A2A | Nadi envelope with semantic routing |
| Identity | token/key per protocol | subject → city → space → slot |
| Sovereignty | not addressed | fork lineage, sync policy, claims |
| World state | not addressed | spaces, slots, leases, heartbeat |
| Trust | per-connection | trust ledger (UNKNOWN → TRUSTED) |
| Discovery | per-protocol registry | federated semantic index, federation descriptors |
| Governance | not addressed | typed intents → review → execution |
| Liveness | health checks | heartbeat coupling to upstream authority |
| Federation | not addressed | authority feeds, projection bindings, descriptor seeds |

The bottom six rows are not communication concerns. No external communication
protocol needs to address them, and no communication protocol should be expected
to replace them.

### Why not a unified replacement standard

Creating a single standard that replaces MCP, A2A, and all others would:

- compete instead of compose
- force external ecosystems to abandon working tools
- turn `agent-internet` into a communication protocol instead of an existence
  layer

The correct relationship is: external protocols bring agents to the door.
This stack gives them a world to exist in once they arrive.

### Consequences

Positive:

- prevents accidental promotion of external protocols into substrate concerns
- keeps the core independent of any single external standard's lifecycle
- allows adoption of new external protocols as they emerge without core rewrites
- preserves Nadi/Lotus as the internal semantic layer

Negative:

- each external protocol requires a dedicated adapter
- adapter maintenance tracks external protocol evolution
- early adopters must use Lotus/Nadi directly until adapters exist

### Rejected alternative

Adopt MCP or A2A as the primary inter-city communication standard, replacing
or reducing Nadi/Lotus.

Rejected because MCP and A2A do not model sovereignty, world state, heartbeat
coupling, trust federation, or semantic routing with intent classification.
Adopting them as primary would require either extending them beyond their design
scope or abandoning concerns that define this system's identity.

### Rejected alternative

Create a new protocol that unifies MCP, A2A, Nadi, and Lotus into a single
specification.

Rejected because that conflates communication (how agents talk) with existence
(where agents live). These are separate concerns and should remain separate
layers. A unified specification would be too broad to implement cleanly and
would compete with established standards instead of composing with them.
