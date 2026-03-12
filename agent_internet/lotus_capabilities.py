from __future__ import annotations


def build_lotus_capability_manifest(*, base_url: str | None = None) -> dict:
    root = str(base_url or "").rstrip("/")
    capabilities = [
        _capability("control_plane_state", "Read the full persisted control-plane snapshot.", "GET", "/v1/lotus/state", "show_state", ["lotus.read"], "read_only", []),
        _capability("steward_protocol", "Read the steward-protocol-compatible summary of authority and routing bindings.", "GET", "/v1/lotus/steward-protocol", "show_steward_protocol", ["lotus.read"], "read_only", []),
        _capability("operation_receipts", "Read a persisted mutation receipt by operation id or by action plus request id for replay-safe orchestration recovery.", "GET", "/v1/lotus/operations/{operation_id}", "show_operation_receipt", ["lotus.read"], "read_only_lookup", ["operation_id | (action + request_id)"]),
        _capability("mutation_preflight", "Dry-run supported Lotus mutations to learn whether they would apply, replay, conflict, or block before changing state.", "POST", "/v1/lotus/preflight", "preflight_mutation", ["action-specific write scope"], "read_only_dry_run", ["target_action", "params"]),
        _capability("commons_inventory", "List spaces, slots, claims, and leases from the typed commons model.", "GET", "/v1/lotus/space-claims", "list_space_claims", ["lotus.read"], "read_only", []),
        _capability("intent_workflow", "Create intents with optional request-id replay protection for AI-safe retries.", "POST", "/v1/lotus/intents", "create_intent", ["lotus.write.intent"], "request_id_replay_safe", ["request_id?", "intent_id", "intent_type", "title"]),
        _capability("claim_lifecycle", "Release or expire granted claims through typed lifecycle transitions with optional request-id replay protection.", "POST", "/v1/lotus/space-claims/{claim_id}/release", "release_space_claim", ["lotus.write.contract"], "request_id_replay_safe", ["request_id?", "claim_id", "now?"]),
        _capability("lease_lifecycle", "Release or expire active leases with optional request-id replay protection; expired or released leases degrade live slots to dormant+reclaimable.", "POST", "/v1/lotus/slot-leases/{lease_id}/expire", "expire_slot_lease", ["lotus.write.contract"], "request_id_replay_safe", ["request_id?", "lease_id", "now?"]),
        _capability("grant_recovery", "Run the deterministic expired-grant sweep manually with optional request-id replay protection.", "POST", "/v1/lotus/grants/sweep-expired", "sweep_expired_grants", ["lotus.write.contract"], "request_id_replay_safe", ["request_id?", "now?"]),
        _capability("service_publication", "Publish endpoints, services, and routes into the Lotus control plane with optional request-id replay protection.", "POST", "/v1/lotus/services", "publish_service", ["lotus.write.service"], "request_id_replay_safe", ["request_id?", "city_id", "service_name", "public_handle", "transport", "location"]),
        _capability("authority_feed_controls", "List and toggle source-authority feed enablement for reconcile-driven ingestion.", "POST", "/v1/lotus/source-authority-feeds/{feed_id}/enable", "set_source_authority_feed_enabled", ["lotus.write.repo_sync"], "set_desired_state", ["feed_id", "enabled"]),
        _capability("token_issuance", "Issue scoped Lotus bearer tokens for AI operators and delegated workflows.", "POST", "/v1/lotus/tokens", "issue_token", ["lotus.write.token"], "caller_supplied_token_id", ["subject", "scopes"]),
    ]
    return {
        "kind": "lotus_capability_manifest",
        "version": 1,
        "surface_kind": "lotus_control_plane_operator_surface",
        "operator_model": "ai_operator_with_scoped_bearer_token",
        "discovery": {
            "manifest_http_path": _href(root, "/v1/lotus/capabilities"),
            "manifest_lotus_action": "lotus_capabilities",
            "generic_http_call_path": _href(root, "/v1/lotus/call"),
            "generic_cli_entrypoint": "python -m agent_internet.cli lotus-api-call",
        },
        "auth": {
            "kind": "lotus_bearer_token",
            "baseline_read_scope": "lotus.read",
            "write_scopes_are_action_specific": True,
            "current_identity_holder": "token subject",
            "sovereign_signature_status": "not_yet_gad_1000",
        },
        "parseability": {
            "http_error_envelope_fields": ["error", "error_code", "error_kind", "recoverable", "retryable", "context"],
            "health_http_path": _href(root, "/healthz"),
            "state_http_path": _href(root, "/v1/lotus/state"),
            "operation_receipt_http_paths": [_href(root, "/v1/lotus/operations/{operation_id}"), _href(root, "/v1/lotus/operations/by-request?action=...&request_id=...")],
            "preflight_http_path": _href(root, "/v1/lotus/preflight"),
            "preflight_response_fields": ["kind", "target_action", "ok", "would_apply", "effect_kind", "blockers", "idempotency", "preview", "remediation_hints"],
            "preflight_remediation_hint_fields": ["hint_code", "summary", "lotus_action?", "http_path?", "params", "suggested_change?"],
        },
        "recoverability": {
            "manual_sweep_action": "sweep_expired_grants",
            "manual_sweep_http_path": _href(root, "/v1/lotus/grants/sweep-expired"),
            "daemon_interval_flag": "--grant-sweep-interval-seconds",
            "request_id_supported_actions": ["create_intent", "publish_endpoint", "publish_service", "publish_route", "release_space_claim", "expire_space_claim", "release_slot_lease", "expire_slot_lease", "sweep_expired_grants"],
            "preflight_supported_actions": ["create_intent", "publish_endpoint", "publish_service", "publish_route", "release_space_claim", "expire_space_claim", "release_slot_lease", "expire_slot_lease", "sweep_expired_grants"],
        },
        "delegated_manifests": [
            {"manifest_http_path": _href(root, "/v1/lotus/agent-web-semantic-capabilities"), "manifest_lotus_action": "agent_web_semantic_capabilities"},
            {"manifest_http_path": _href(root, "/v1/lotus/agent-web-repo-graph-capabilities"), "manifest_lotus_action": "agent_web_repo_graph_capabilities"},
        ],
        "capabilities": capabilities,
        "stats": {"capability_count": len(capabilities)},
    }


def _capability(
    capability_id: str,
    summary: str,
    method: str,
    http_path: str,
    lotus_action: str,
    required_scopes: list[str],
    idempotency: str,
    params: list[str],
) -> dict:
    return {
        "capability_id": capability_id,
        "summary": summary,
        "http": {"method": method, "path": http_path},
        "lotus_action": lotus_action,
        "required_scopes": required_scopes,
        "idempotency": idempotency,
        "params": params,
    }


def _href(root: str, path: str) -> str:
    return f"{root}{path}" if root else path