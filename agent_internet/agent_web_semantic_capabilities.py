from __future__ import annotations

import json

from .agent_web_semantic_contracts import build_agent_web_semantic_contract_reference


def build_agent_web_semantic_capability_manifest(*, base_url: str | None = None) -> dict:
    root = str(base_url or "").rstrip("/")
    capabilities = [
        _capability(
            capability_id="semantic_federated_search",
            summary="Search the persisted federated semantic index and return explainable ranked results.",
            path="/v1/lotus/agent-web-federated-search",
            action="agent_web_federated_search",
            cli_command="agent-web-federated-search",
            http_query_params=["index_path?", "overlay_path?", "wordnet_path?", "q", "limit?"],
            lotus_params=["index_path?", "overlay_path?", "wordnet_path?", "query", "limit?"],
            stable_response_subset={
                "top_level_fields": ["kind", "query", "results", "query_interpretation", "matched_semantic_bridges", "wordnet_bridge", "semantic_extensions", "stats"],
                "result_fields": ["record_id", "kind", "title", "summary", "source_city_id", "source_repo", "href", "score", "matched_terms", "why_matched"],
                "why_matched_fields": ["direct_term_matches", "expanded_term_matches", "semantic_bridge_matches", "semantic_neighbor_count", "top_semantic_neighbors"],
            },
            base_url=root,
        ),
        _capability(
            capability_id="semantic_neighbors",
            summary="Read persisted semantic neighbors for a known federated record id.",
            path="/v1/lotus/agent-web-semantic-neighbors",
            action="agent_web_semantic_neighbors",
            cli_command="agent-web-semantic-neighbors",
            http_query_params=["index_path?", "record_id", "limit?"],
            lotus_params=["index_path?", "record_id", "limit?"],
            stable_response_subset={
                "top_level_fields": ["kind", "record", "neighbors", "stats"],
                "record_fields": ["record_id", "kind", "title", "source_city_id", "href"],
                "neighbor_fields": ["record_id", "kind", "title", "source_city_id", "href", "score", "reason_kinds", "shared_terms", "bridge_ids", "wordnet_score"],
            },
            base_url=root,
        ),
        _capability(
            capability_id="semantic_expand",
            summary="Expand a query through the semantic overlay and optional WordNet bridge before reasoning or search.",
            path="/v1/lotus/agent-web-semantic-expand",
            action="agent_web_semantic_expand",
            cli_command="agent-web-semantic-expand",
            http_query_params=["overlay_path?", "wordnet_path?", "q"],
            lotus_params=["overlay_path?", "wordnet_path?", "query"],
            stable_response_subset={
                "top_level_fields": ["kind", "raw_query", "input_terms", "expanded_terms", "weighted_expanded_terms", "matched_bridges", "wordnet_bridge", "stats"],
                "weighted_term_fields": ["term", "weight", "source_bridge_ids"],
                "bridge_fields": ["bridge_id", "bridge_kind", "bridge_weight", "lexical_score", "wordnet_score", "effective_weight"],
            },
            base_url=root,
        ),
    ]
    return {
        "kind": "agent_web_semantic_capability_manifest",
        "version": 1,
        "surface_kind": "consumer_agnostic_semantic_read_surface",
        "consumer_model": "generic_read_only",
        "standard_profile": {
            "profile_id": "agent_web_semantic_read_standard.v1",
            "source_system": "agent_city",
            "provider_runtime": "agent_internet",
            "provider_role": "derived_semantic_membrane",
            "consumer_roles": ["direct_consumer", "proxy_wrapper"],
            "wrapper_rule": "Wrappers may proxy or cache this surface but should not redefine the semantic contract.",
            "primary_authority_rule": "Agent-city remains the primary execution and source-of-truth system; agent-internet publishes a derived read model.",
        },
        "discovery": {
            "manifest_document_id": "semantic_capabilities",
            "manifest_rel": "semantic_capabilities",
            "manifest_http_path": _href(root, "/v1/lotus/agent-web-semantic-capabilities"),
            "manifest_lotus_action": "agent_web_semantic_capabilities",
        },
        "contracts_discovery": {
            "document_id": "semantic_contracts",
            "rel": "semantic_contracts",
            "collection_http_path": _href(root, "/v1/lotus/agent-web-semantic-contracts"),
            "collection_lotus_action": "agent_web_semantic_contracts",
            "detail_query_parameters": ["capability_id?", "contract_id?", "version?"],
        },
        "auth": {
            "kind": "lotus_bearer_token",
            "required_scopes": ["lotus.read"],
            "env": {
                "base_url": "AGENT_INTERNET_LOTUS_BASE_URL",
                "token": "AGENT_INTERNET_LOTUS_TOKEN",
                "timeout_s": "AGENT_INTERNET_LOTUS_TIMEOUT_S",
            },
        },
        "capabilities": capabilities,
        "non_goals": [
            "No bespoke steward-agent-only glue is required to consume this surface.",
            "No transport or Nadi substrate logic should be reimplemented by consumers.",
            "No deep private user memory is exposed through this manifest.",
        ],
        "stats": {"capability_count": len(capabilities)},
    }


def render_agent_web_semantic_capability_page(manifest: dict) -> str:
    auth = dict(manifest.get("auth", {}))
    discovery = dict(manifest.get("discovery", {}))
    lines = [
        "# Semantic Capabilities",
        "",
        f"- Standard Profile: `{dict(manifest.get('standard_profile', {})).get('profile_id', '')}`",
        f"- Surface Kind: `{manifest.get('surface_kind', '')}`",
        f"- Consumer Model: `{manifest.get('consumer_model', '')}`",
        f"- Manifest Action: `{discovery.get('manifest_lotus_action', '')}`",
        f"- Manifest Rel: `{discovery.get('manifest_rel', '')}`",
        f"- Required Scope: `{', '.join(str(item) for item in auth.get('required_scopes', []))}`",
        "",
        "## Capability Index",
        "",
    ]
    for capability in manifest.get("capabilities", []):
        payload = dict(capability)
        http = dict(payload.get("http", {}))
        lotus = dict(payload.get("lotus", {}))
        contract = dict(payload.get("contract_descriptor", {}))
        lines.extend(
            [
                f"### `{payload.get('capability_id', '')}`",
                "",
                f"- Summary: {payload.get('summary', '')}",
                f"- HTTP: `{http.get('method', '')} {http.get('path', '')}`",
                f"- Lotus Action: `{lotus.get('action', '')}`",
                f"- CLI: `{dict(payload.get('cli', {})).get('command', '')}`",
                f"- Contract Descriptor: `{dict(contract.get('http', {})).get('href', '')}`",
                f"- Stable Fields: `{', '.join(str(item) for item in dict(payload.get('stable_response_subset', {})).get('top_level_fields', []))}`",
                "",
            ],
        )
    lines.extend(["## Raw Manifest", "", json.dumps(manifest, indent=2, sort_keys=True)])
    return "\n".join(lines).rstrip() + "\n"


def _capability(
    *,
    capability_id: str,
    summary: str,
    path: str,
    action: str,
    cli_command: str,
    http_query_params: list[str],
    lotus_params: list[str],
    stable_response_subset: dict,
    base_url: str,
) -> dict:
    return {
        "capability_id": capability_id,
        "summary": summary,
        "mode": "read_only",
        "http": {"method": "GET", "path": path, "href": _href(base_url, path), "query_params": list(http_query_params)},
        "lotus": {"action": action, "params": list(lotus_params)},
        "cli": {"command": cli_command},
        "contract_descriptor": build_agent_web_semantic_contract_reference(capability_id, base_url=base_url),
        "stable_response_subset": dict(stable_response_subset),
    }


def _href(base_url: str, path: str) -> str:
    return f"{base_url}{path}" if base_url else path