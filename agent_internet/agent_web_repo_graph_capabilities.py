from __future__ import annotations

import json

from .agent_web_repo_graph_contracts import build_agent_web_repo_graph_contract_reference


def build_agent_web_repo_graph_capability_manifest(*, base_url: str | None = None) -> dict:
    root = str(base_url or "").rstrip("/")
    capabilities = [
        _capability(
            capability_id="repo_graph_snapshot",
            summary="Read a filtered snapshot of the published repository knowledge graph.",
            path="/v1/lotus/agent-web-repo-graph",
            action="agent_web_repo_graph_snapshot",
            cli_command="agent-web-repo-graph",
            http_query_params=["root", "node_type?", "domain?", "query?", "limit?"],
            lotus_params=["root", "node_type?", "domain?", "query?", "limit?"],
            stable_response_subset={
                "top_level_fields": ["kind", "source", "selector", "summary", "nodes", "edges", "metrics", "constraints", "stats"],
                "node_fields": ["node_id", "type", "name", "domain", "description", "properties"],
                "edge_fields": ["source_id", "target_id", "relation", "weight", "properties"],
            },
            base_url=root,
        ),
        _capability(
            capability_id="repo_graph_neighbors",
            summary="Traverse local repository graph neighbors from a node id.",
            path="/v1/lotus/agent-web-repo-graph-neighbors",
            action="agent_web_repo_graph_neighbors",
            cli_command="agent-web-repo-graph-neighbors",
            http_query_params=["root", "node_id", "relation?", "depth?", "limit?"],
            lotus_params=["root", "node_id", "relation?", "depth?", "limit?"],
            stable_response_subset={
                "top_level_fields": ["kind", "source", "record", "neighbors", "edges", "traversal", "stats"],
                "record_fields": ["node_id", "type", "name", "domain"],
                "neighbor_fields": ["node_id", "type", "name", "domain", "description", "properties"],
            },
            base_url=root,
        ),
        _capability(
            capability_id="repo_graph_context",
            summary="Compile prompt-ready context from the local repository knowledge graph for a concept.",
            path="/v1/lotus/agent-web-repo-graph-context",
            action="agent_web_repo_graph_context",
            cli_command="agent-web-repo-graph-context",
            http_query_params=["root", "concept"],
            lotus_params=["root", "concept"],
            stable_response_subset={
                "top_level_fields": ["kind", "source", "concept", "context", "stats"],
            },
            base_url=root,
        ),
    ]
    return {
        "kind": "agent_web_repo_graph_capability_manifest",
        "version": 1,
        "surface_kind": "consumer_agnostic_repo_graph_read_surface",
        "consumer_model": "generic_read_only",
        "federation_surface": {
            "surface_role": "canonical_public_read_surface",
            "canonical_for_public_federation": True,
            "publication_model": "github_published_projection_plus_authenticated_read_api",
            "carrier_document": "agent_web_manifest",
            "operator_companion_surface": "lotus_control_plane_operator_surface",
        },
        "standard_profile": {
            "profile_id": "agent_web_repo_graph_read_standard.v1",
            "source_system": "steward_protocol",
            "provider_runtime": "agent_internet",
            "provider_role": "derived_repo_graph_membrane",
            "consumer_roles": ["direct_consumer", "proxy_wrapper"],
            "wrapper_rule": "Wrappers may proxy or cache this surface but should not redefine the underlying repo-graph contract.",
            "primary_authority_rule": "The source repository and its native knowledge graph remain the primary authority; agent-internet only publishes a derived read surface.",
            "initial_repo_targets": ["steward-protocol"],
        },
        "discovery": {
            "manifest_document_id": "repo_graph_capabilities",
            "manifest_rel": "repo_graph_capabilities",
            "manifest_http_path": _href(root, "/v1/lotus/agent-web-repo-graph-capabilities"),
            "manifest_lotus_action": "agent_web_repo_graph_capabilities",
        },
        "contracts_discovery": {
            "document_id": "repo_graph_contracts",
            "rel": "repo_graph_contracts",
            "collection_http_path": _href(root, "/v1/lotus/agent-web-repo-graph-contracts"),
            "collection_lotus_action": "agent_web_repo_graph_contracts",
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
            "No new repository ontology is introduced here; this surface reuses the underlying graph substrate.",
            "No mutable graph database is exposed through this read surface.",
            "No claim is made that every repository already supports this surface; the initial target is steward-protocol.",
        ],
        "stats": {"capability_count": len(capabilities)},
    }


def render_agent_web_repo_graph_capability_page(manifest: dict) -> str:
    auth = dict(manifest.get("auth", {}))
    discovery = dict(manifest.get("discovery", {}))
    lines = [
        "# Repo Graph Capabilities",
        "",
        f"- Standard Profile: `{dict(manifest.get('standard_profile', {})).get('profile_id', '')}`",
        f"- Surface Kind: `{manifest.get('surface_kind', '')}`",
        f"- Consumer Model: `{manifest.get('consumer_model', '')}`",
        f"- Manifest Action: `{discovery.get('manifest_lotus_action', '')}`",
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
        "contract_descriptor": build_agent_web_repo_graph_contract_reference(capability_id, base_url=base_url),
        "stable_response_subset": dict(stable_response_subset),
    }


def _href(base_url: str, path: str) -> str:
    return f"{base_url}{path}" if base_url else path