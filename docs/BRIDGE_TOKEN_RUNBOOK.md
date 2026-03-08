## Bridge Token Runbook

### Purpose

Operate the `steward-protocol` ↔ `agent-internet` intent membrane without guesswork.

This runbook covers:
- public bridge token scopes
- verified bridge token scopes
- `steward-protocol` env wiring
- quick validation steps

### Required token split

#### Public bridge token

Use for:
- `POST /v1/public-intents`
- `GET /v1/public-intents/{intent_id}`

Required scopes:
- `lotus.read`
- `lotus.write.intent`

#### Verified bridge token

Use for:
- `POST /v1/intents`
- `POST /v1/intents/status`

Required scopes:
- `lotus.read`
- `lotus.write.intent`
- `lotus.write.intent.subject`

The extra `lotus.write.intent.subject` scope is what allows verified edge
requests to persist `requested_by_subject_id=verified_agent:{agent_id}`.

### Issue tokens from local control-plane state

From `agent-internet`:

- public bridge token
  - `python -m agent_internet.cli lotus-issue-token --state-path ./data/control_plane/state.json --subject steward-protocol-public-bridge --token-id tok-public-bridge --scope lotus.read --scope lotus.write.intent`
- verified bridge token
  - `python -m agent_internet.cli lotus-issue-token --state-path ./data/control_plane/state.json --subject steward-protocol-verified-bridge --token-id tok-verified-bridge --scope lotus.read --scope lotus.write.intent --scope lotus.write.intent.subject`

Each command prints JSON containing a `secret`. Store that secret safely.

### Issue tokens through the Lotus HTTP daemon

You need an existing bearer token with:
- `lotus.write.token`

Example verified bridge issuance:

- `curl -sS -X POST "$AGENT_INTERNET_BASE_URL/v1/lotus/tokens" -H "Authorization: Bearer $LOTUS_ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"subject":"steward-protocol-verified-bridge","token_id":"tok-verified-bridge","scopes":["lotus.read","lotus.write.intent","lotus.write.intent.subject"]}'`

Example public bridge issuance:

- `curl -sS -X POST "$AGENT_INTERNET_BASE_URL/v1/lotus/tokens" -H "Authorization: Bearer $LOTUS_ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"subject":"steward-protocol-public-bridge","token_id":"tok-public-bridge","scopes":["lotus.read","lotus.write.intent"]}'`

### `steward-protocol` env wiring

Set:
- `AGENT_INTERNET_LOTUS_BASE_URL`
- `AGENT_INTERNET_LOTUS_TOKEN`
- `AGENT_INTERNET_VERIFIED_LOTUS_TOKEN`
- `AGENT_INTERNET_LOTUS_TIMEOUT_S`
- `VIBE_API_KEY`

Suggested mapping:
- `AGENT_INTERNET_LOTUS_TOKEN` → public bridge token secret
- `AGENT_INTERNET_VERIFIED_LOTUS_TOKEN` → verified bridge token secret

### Quick validation

For a single end-to-end check through the edge, run:

- `cd ../steward-protocol && .venv/bin/python scripts/testing/smoke_intent_membrane.py --base-url "$STEWARD_PROTOCOL_BASE_URL" --api-key "$VIBE_API_KEY"`

#### Public path

- `POST /v1/public-intents`
- confirm intent is created in `agent-internet`
- `GET /v1/public-intents/{intent_id}`

#### Verified path

- `POST /v1/intents`
- confirm stored `requested_by_subject_id` is `verified_agent:{agent_id}`
- `POST /v1/intents/status`

### Failure mode to watch for

If the verified token is missing `lotus.write.intent.subject`, verified intent
creation will fail with:

- `missing_scopes:lotus.write.intent.subject`