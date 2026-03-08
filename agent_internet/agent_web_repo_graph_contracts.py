from __future__ import annotations

import json


def build_agent_web_repo_graph_contract_manifest(*, base_url: str | None = None) -> dict:
    root = str(base_url or "").rstrip("/")
    descriptors = [
        read_agent_web_repo_graph_contract_descriptor(
            capability_id=capability_id,
            version=_latest_contract_version(capability_id),
            base_url=root,
        )
        for capability_id in _descriptor_specs()
    ]
    return {
        "kind": "agent_web_repo_graph_contract_manifest",
        "version": 1,
        "surface_kind": "repo_graph_contract_descriptor_collection",
        "standard_profile": {
            "profile_id": "agent_web_repo_graph_read_standard.v1",
            "source_system": "steward_protocol",
            "provider_runtime": "agent_internet",
            "provider_role": "derived_repo_graph_membrane",
            "consumer_roles": ["direct_consumer", "proxy_wrapper"],
            "wrapper_rule": "Proxy servers and wrappers should expose or forward these descriptors rather than inventing parallel repo-graph contracts.",
        },
        "discovery": {
            "document_id": "repo_graph_contracts",
            "rel": "repo_graph_contracts",
            "collection_http_path": _href(root, "/v1/lotus/agent-web-repo-graph-contracts"),
            "collection_lotus_action": "agent_web_repo_graph_contracts",
            "detail_query_parameters": ["capability_id?", "contract_id?", "version?"],
            "selector_precedence": ["contract_id", "capability_id+version", "capability_id"],
        },
        "selection": {
            "default_behavior": "When capability_id is provided without version, resolve the latest supported contract for that capability.",
            "supports_contract_id_lookup": True,
            "supports_capability_version_lookup": True,
        },
        "descriptors": descriptors,
        "stats": {"descriptor_count": len(descriptors)},
    }


def read_agent_web_repo_graph_contract_descriptor(
    *,
    capability_id: str | None = None,
    contract_id: str | None = None,
    version: int | str | None = None,
    base_url: str | None = None,
) -> dict:
    root = str(base_url or "").rstrip("/")
    selection = _resolve_contract_selection(capability_id=capability_id, contract_id=contract_id, version=version)
    key = str(selection["capability_id"])
    spec = _descriptor_specs().get(key)
    if spec is None:
        raise ValueError(f"unknown_capability:{key}")
    return {
        "kind": "agent_web_repo_graph_contract_descriptor",
        "version": int(selection["version"]),
        "contract_id": str(selection["contract_id"]),
        "capability_id": key,
        "latest_version": _latest_contract_version(key),
        "supported_versions": _supported_contract_versions(key),
        "latest_for_capability": int(selection["version"]) == _latest_contract_version(key),
        "standard_profile_id": "agent_web_repo_graph_read_standard.v1",
        "summary": str(spec["summary"]),
        "stability": "stable_subset_v1",
        "mode": "read_only",
        "auth": {
            "kind": "lotus_bearer_token",
            "required_scopes": ["lotus.read"],
            "env": {
                "base_url": "AGENT_INTERNET_LOTUS_BASE_URL",
                "token": "AGENT_INTERNET_LOTUS_TOKEN",
                "timeout_s": "AGENT_INTERNET_LOTUS_TIMEOUT_S",
            },
        },
        "selector_examples": {
            "by_capability": {"capability_id": key},
            "by_capability_and_version": {"capability_id": key, "version": int(selection["version"])},
            "by_contract_id": {"contract_id": str(selection["contract_id"])} ,
        },
        "request_schema": dict(spec["request_schema"]),
        "response_schema": dict(spec["response_schema"]),
        "transport": {
            "http": {
                "method": "GET",
                "path": str(spec["http_path"]),
                "href": _href(root, str(spec["http_path"])),
                "query_params": list(spec["http_query_params"]),
            },
            "lotus": {
                "action": str(spec["lotus_action"]),
                "params": list(spec["lotus_params"]),
            },
            "cli": {
                "command": str(spec["cli_command"]),
            },
        },
        "descriptor_transport": build_agent_web_repo_graph_contract_reference(
            capability_id=key,
            version=int(selection["version"]),
            contract_id=str(selection["contract_id"]),
            base_url=root,
        ),
    }


def build_agent_web_repo_graph_contract_reference(
    capability_id: str | None = None,
    *,
    contract_id: str | None = None,
    version: int | str | None = None,
    base_url: str | None = None,
) -> dict:
    root = str(base_url or "").rstrip("/")
    selection = _resolve_contract_selection(capability_id=capability_id, contract_id=contract_id, version=version)
    key = str(selection["capability_id"])
    selected_contract_id = str(selection["contract_id"])
    selected_version = int(selection["version"])
    return {
        "contract_id": selected_contract_id,
        "version": selected_version,
        "selector": {"capability_id": key, "contract_id": selected_contract_id, "version": selected_version},
        "document_id": "repo_graph_contracts",
        "rel": "repo_graph_contracts",
        "http": {
            "method": "GET",
            "path": "/v1/lotus/agent-web-repo-graph-contracts",
            "href": _href(root, f"/v1/lotus/agent-web-repo-graph-contracts?contract_id={selected_contract_id}"),
            "query_params": ["capability_id?", "contract_id?", "version?"],
        },
        "lotus": {
            "action": "agent_web_repo_graph_contracts",
            "params": ["capability_id?", "contract_id?", "version?"],
        },
        "cli": {
            "command": "agent-web-repo-graph-contracts",
            "args": ["--contract-id", selected_contract_id],
        },
    }


def render_agent_web_repo_graph_contract_page(manifest: dict) -> str:
    discovery = dict(manifest.get("discovery", {}))
    lines = [
        "# Repo Graph Contracts",
        "",
        f"- Standard Profile: `{dict(manifest.get('standard_profile', {})).get('profile_id', '')}`",
        f"- Surface Kind: `{manifest.get('surface_kind', '')}`",
        f"- Collection Action: `{discovery.get('collection_lotus_action', '')}`",
        f"- Detail Query Parameters: `{', '.join(str(item) for item in discovery.get('detail_query_parameters', []))}`",
        "",
        "## Contract Index",
        "",
    ]
    for descriptor in manifest.get("descriptors", []):
        payload = dict(descriptor)
        transport = dict(payload.get("transport", {}))
        http = dict(transport.get("http", {}))
        lines.extend(
            [
                f"### `{payload.get('contract_id', '')}`",
                "",
                f"- Capability: `{payload.get('capability_id', '')}`",
                f"- Version: `{payload.get('version', '')}` / Latest: `{payload.get('latest_version', '')}`",
                f"- Summary: {payload.get('summary', '')}",
                f"- HTTP: `{http.get('method', '')} {http.get('path', '')}`",
                f"- Descriptor: `{dict(payload.get('descriptor_transport', {})).get('http', {}).get('href', '')}`",
                "",
            ],
        )
    lines.extend(["## Raw Manifest", "", json.dumps(manifest, indent=2, sort_keys=True)])
    return "\n".join(lines).rstrip() + "\n"


def _resolve_contract_selection(*, capability_id: str | None, contract_id: str | None, version: int | str | None) -> dict[str, object]:
    key = str(capability_id or "").strip() or None
    selected_contract_id = str(contract_id or "").strip() or None
    selected_version = _coerce_optional_int(version)
    if selected_contract_id is not None:
        contract_capability_id, contract_version = _parse_contract_id(selected_contract_id)
        if key is not None and key != contract_capability_id:
            raise ValueError("contract_selector_conflict")
        if selected_version is not None and selected_version != contract_version:
            raise ValueError("contract_selector_conflict")
        key = contract_capability_id
        selected_version = contract_version
    if key is None:
        raise ValueError("missing_contract_selector")
    if key not in _descriptor_specs():
        raise ValueError(f"unknown_capability:{key}")
    supported_versions = _supported_contract_versions(key)
    effective_version = selected_version if selected_version is not None else _latest_contract_version(key)
    if effective_version not in supported_versions:
        raise ValueError(f"unknown_contract_version:{key}.v{effective_version}")
    return {"capability_id": key, "version": effective_version, "contract_id": f"{key}.v{effective_version}"}


def _parse_contract_id(contract_id: str) -> tuple[str, int]:
    if ".v" not in contract_id:
        raise ValueError(f"invalid_contract_id:{contract_id}")
    capability_id, version_text = contract_id.rsplit(".v", 1)
    if not capability_id or not version_text.isdigit():
        raise ValueError(f"invalid_contract_id:{contract_id}")
    return capability_id, int(version_text)


def _coerce_optional_int(value: int | str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _supported_contract_versions(capability_id: str) -> list[int]:
    return [1]


def _latest_contract_version(capability_id: str) -> int:
    return max(_supported_contract_versions(capability_id))


def _descriptor_specs() -> dict[str, dict[str, object]]:
    return {
        "repo_graph_snapshot": {
            "summary": "Stable request/response contract for filtered repository knowledge-graph snapshots.",
            "http_path": "/v1/lotus/agent-web-repo-graph",
            "http_query_params": ["root", "node_type?", "domain?", "query?", "limit?"],
            "lotus_action": "agent_web_repo_graph_snapshot",
            "lotus_params": ["root", "node_type?", "domain?", "query?", "limit?"],
            "cli_command": "agent-web-repo-graph",
            "request_schema": {
                "type": "object",
                "required": ["root"],
                "properties": {
                    "root": {"type": "string"},
                    "node_type": {"type": "string"},
                    "domain": {"type": "string"},
                    "query": {"type": "string", "http_name": "query"},
                    "limit": {"type": "integer", "minimum": 1},
                },
            },
            "response_schema": {
                "type": "object",
                "required": ["kind", "source", "summary", "nodes", "edges", "stats"],
                "properties": {
                    "kind": {"type": "string", "const": "agent_web_repo_graph_snapshot"},
                    "source": {"type": "object"},
                    "summary": {"type": "object"},
                    "nodes": {"type": "array", "items": {"type": "object"}},
                    "edges": {"type": "array", "items": {"type": "object"}},
                    "metrics": {"type": "array", "items": {"type": "object"}},
                    "constraints": {"type": "array", "items": {"type": "object"}},
                    "stats": {"type": "object"},
                },
            },
        },
        "repo_graph_neighbors": {
            "summary": "Stable request/response contract for node-centered repository graph traversal.",
            "http_path": "/v1/lotus/agent-web-repo-graph-neighbors",
            "http_query_params": ["root", "node_id", "relation?", "depth?", "limit?"],
            "lotus_action": "agent_web_repo_graph_neighbors",
            "lotus_params": ["root", "node_id", "relation?", "depth?", "limit?"],
            "cli_command": "agent-web-repo-graph-neighbors",
            "request_schema": {
                "type": "object",
                "required": ["root", "node_id"],
                "properties": {
                    "root": {"type": "string"},
                    "node_id": {"type": "string"},
                    "relation": {"type": "string"},
                    "depth": {"type": "integer", "minimum": 1},
                    "limit": {"type": "integer", "minimum": 1},
                },
            },
            "response_schema": {
                "type": "object",
                "required": ["kind", "source", "record", "neighbors", "edges", "stats"],
                "properties": {
                    "kind": {"type": "string", "const": "agent_web_repo_graph_neighbors"},
                    "source": {"type": "object"},
                    "record": {"type": "object"},
                    "neighbors": {"type": "array", "items": {"type": "object"}},
                    "edges": {"type": "array", "items": {"type": "object"}},
                    "traversal": {"type": "object"},
                    "stats": {"type": "object"},
                },
            },
        },
        "repo_graph_context": {
            "summary": "Stable request/response contract for prompt-ready context compiled from the repository knowledge graph.",
            "http_path": "/v1/lotus/agent-web-repo-graph-context",
            "http_query_params": ["root", "concept"],
            "lotus_action": "agent_web_repo_graph_context",
            "lotus_params": ["root", "concept"],
            "cli_command": "agent-web-repo-graph-context",
            "request_schema": {
                "type": "object",
                "required": ["root", "concept"],
                "properties": {
                    "root": {"type": "string"},
                    "concept": {"type": "string"},
                },
            },
            "response_schema": {
                "type": "object",
                "required": ["kind", "source", "concept", "context", "stats"],
                "properties": {
                    "kind": {"type": "string", "const": "agent_web_repo_graph_context"},
                    "source": {"type": "object"},
                    "concept": {"type": "string"},
                    "context": {"type": "string"},
                    "stats": {"type": "object"},
                },
            },
        },
    }


def _href(base_url: str, path: str) -> str:
    return f"{base_url}{path}" if base_url else path