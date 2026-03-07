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
- `agent_internet/agent_city_directives.py` — validated builders for current agent-city directive types
- `agent_internet/agent_city_peer.py` — explicit onboarding adapter for existing agent-city repos
- `agent_internet/steward_federation.py` — typed steward-protocol object adapter
- `agent_internet/snapshot.py` — conservative JSON snapshot persistence
- `agent_internet/transport.py` — delivery envelopes, receipts, registry, relay, and loopback transport
- `agent_internet/filesystem_message_transport.py` — envelope delivery into the current agent-city inbox format
- `agent_internet/receipt_store.py` — receiver-side receipt journal for idempotent delivery
- `agent_internet/agent_city_contract.py` — current Agent City federation path contract
- `agent_internet/filesystem_transport.py` — Phase 0 compatibility transport
- `agent_internet/steward_substrate.py` — optional bindings to canonical substrate symbols
- `docs/` — architecture decisions and repo boundary

## Verification

Run locally:

- `python -m pytest -q`
- `python -m ruff check .`

## CLI

- `python -m agent_internet.cli show-state`
- `python -m agent_internet.cli lotus-assign-addresses --state-path ./data/control_plane/state.json --city-id city-a`
- `python -m agent_internet.cli lotus-show-steward-protocol`
- `python -m agent_internet.cli lotus-publish-endpoint --state-path ./data/control_plane/state.json --city-id city-a --public-handle forum.city-a.lotus --transport https --location https://forum.city-a.example`
- `python -m agent_internet.cli lotus-resolve-handle --state-path ./data/control_plane/state.json --public-handle forum.city-a.lotus`
- `python -m agent_internet.cli lotus-publish-service --state-path ./data/control_plane/state.json --city-id city-a --service-name forum-api --public-handle api.forum.city-a.lotus --transport https --location https://forum.city-a.example/api --required-scope lotus.read`
- `python -m agent_internet.cli lotus-publish-route --state-path ./data/control_plane/state.json --owner-city-id city-a --destination-prefix service:city-z/forum --target-city-id city-z --next-hop-city-id city-b --metric 5`
- `python -m agent_internet.cli lotus-resolve-next-hop --state-path ./data/control_plane/state.json --source-city-id city-a --destination service:city-z/forum-api`
- `python -m agent_internet.cli lotus-issue-token --state-path ./data/control_plane/state.json --subject operator --scope lotus.read --scope lotus.write.service`
- `python -m agent_internet.cli lotus-api-call --state-path ./data/control_plane/state.json --token <bearer> --action resolve_service --params-json '{"city_id":"city-a","service_name":"forum-api"}'`
- `python -m agent_internet.cli lotus-api-daemon --state-path ./data/control_plane/state.json --host 127.0.0.1 --port 8788`
- `curl -s -H 'Authorization: Bearer <bearer>' http://127.0.0.1:8788/v1/lotus/state`
- `curl -s -H 'Authorization: Bearer <bearer>' http://127.0.0.1:8788/v1/lotus/steward-protocol`
- `curl -s -X POST -H 'Authorization: Bearer <bearer>' -H 'Content-Type: application/json' http://127.0.0.1:8788/v1/lotus/routes -d '{"owner_city_id":"city-a","destination_prefix":"service:city-z/forum","target_city_id":"city-z","next_hop_city_id":"city-b","metric":5}'`
- `curl -s -X POST -H 'Authorization: Bearer <bearer>' -H 'Content-Type: application/json' http://127.0.0.1:8788/v1/lotus/services -d '{"city_id":"city-a","service_name":"forum-api","public_handle":"api.forum.city-a.lotus","transport":"https","location":"https://forum.city-a.example/api","required_scopes":["lotus.read"]}'`
- `python -m agent_internet.cli publish-agent-city-peer --root ../agent-city --city-id city-a --repo kimeisele/agent-city --capability federation`
- `python -m agent_internet.cli git-federation-describe --root ../agent-city`
- `python -m agent_internet.cli publish-agent-city-peer --root ../agent-city --city-id city-a`
- `python -m agent_internet.cli onboard-agent-city --root ../agent-city --city-id city-a --repo kimeisele/agent-city`
- `python -m agent_internet.cli onboard-agent-city --root ../agent-city --discover`
- `python -m agent_internet.cli git-federation-sync-wiki --root ../agent-city --state-path ./data/control_plane/state.json`
- `python -m agent_internet.cli init-dual-city-lab --root ./tmp/lab`
- `python -m agent_internet.cli lab-send --root ./tmp/lab --source-city-id city-a --target-city-id city-b --operation sync --payload-json '{"heartbeat": 1}'`
- `python -m agent_internet.cli lab-emit-outbox --root ./tmp/lab --source-city-id city-a --target-city-id city-b --operation sync --payload-json '{"heartbeat": 1}'`
- `python -m agent_internet.cli lab-pump-outbox --root ./tmp/lab --source-city-id city-a --drain-delivered`
- `python -m agent_internet.cli lab-sync --root ./tmp/lab --cycles 3 --drain-delivered`
- `python -m agent_internet.cli lab-compact-receipts --root ./tmp/lab --city-id city-b --max-entries 1000`
- `python -m agent_internet.cli lab-issue-directive --root ./tmp/lab --city-id city-a --directive-type register_agent --params-json '{"name":"MIRA"}'`
- `python -m agent_internet.cli lab-run-directives --root ./tmp/lab --city-id city-a --agent-name MIRA`
- `python -m agent_internet.cli lab-phase-tick --root ./tmp/lab --city-id city-a --cycles 3 --ingress-source operator --ingress-text 'hello city'`
- `python -m agent_internet.cli lab-execute-code --root ./tmp/lab --city-id city-a --contract tests_pass --cycles 3`
- `python -m agent_internet.cli lab-immigrate --root ./tmp/lab --source-city-id city-a --host-city-id city-b --agent-name MIRA --visa-class worker`