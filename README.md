# agent-internet

Federation control plane for the Agent City ecosystem.

## Mission

`agent-internet` is the layer above a single city runtime.

- `steward-protocol` provides the substrate and canonical protocol primitives
- `agent-city` provides the single-city runtime and local governance
- `agent-internet` provides the inter-city control plane

This repository starts conservatively:

1. reuse existing protocol primitives from `steward-protocol`
2. preserve compatibility with `agent-city`'s current file-based federation paths
3. define stable interfaces for discovery, routing, trust, and transport
4. avoid pulling city-local behavior down into the internet layer

## Phase 0 scope

Phase 0 does **not** replace the existing city runtime.

It establishes:

- architecture boundaries
- agent-city filesystem federation contract
- optional substrate bindings into `steward-protocol`
- initial transport, registry, routing, and trust interfaces

## Non-goals

- reimplementing `Nadi`, `MahaHeader`, or federation message types
- embedding `agent-city` governance into the network layer
- forcing a hard dependency on a specific city implementation

## Initial structure

- `agent_internet/models.py` — internet-layer domain models
- `agent_internet/interfaces.py` — core protocols for registry/routing/trust/transport
- `agent_internet/memory_registry.py` — concrete in-memory city state registry
- `agent_internet/trust.py` — explicit city-to-city trust ledger
- `agent_internet/router.py` — trust-aware route resolution
- `agent_internet/control_plane.py` — composed control-plane service
- `agent_internet/agent_city_bridge.py` — projection from current Agent City reports
- `agent_internet/agent_city_contract.py` — current Agent City federation path contract
- `agent_internet/filesystem_transport.py` — Phase 0 compatibility transport
- `agent_internet/steward_substrate.py` — optional bindings to canonical substrate symbols
- `docs/` — architecture decisions and repo boundary

## Verification

Run locally:

- `python -m pytest -q`
- `python -m ruff check .`