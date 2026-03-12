from __future__ import annotations

import json


def build_agent_web_semantic_contract_manifest(*, base_url: str | None = None) -> dict:
    root = str(base_url or "").rstrip("/")
    descriptors = [
        read_agent_web_semantic_contract_descriptor(
            capability_id=capability_id,
            version=_latest_contract_version(capability_id),
            base_url=root,
        )
        for capability_id in _descriptor_specs()
    ]
    return {
        "kind": "agent_web_semantic_contract_manifest",
        "version": 1,
        "surface_kind": "semantic_contract_descriptor_collection",
        "federation_surface": {
            "surface_role": "canonical_public_read_contracts",
            "canonical_for_public_federation": True,
            "publication_model": "github_published_projection_plus_authenticated_read_api",
            "carrier_document": "agent_web_manifest",
            "operator_companion_surface": "lotus_control_plane_operator_surface",
        },
        "standard_profile": {
            "profile_id": "agent_web_semantic_read_standard.v1",
            "source_system": "agent_city",
            "provider_runtime": "agent_internet",
            "provider_role": "derived_semantic_membrane",
            "consumer_roles": ["direct_consumer", "proxy_wrapper"],
            "wrapper_rule": "Proxy servers and wrappers should expose or forward these descriptors rather than inventing parallel semantic contracts.",
        },
        "discovery": {
            "document_id": "semantic_contracts",
            "rel": "semantic_contracts",
            "collection_http_path": _href(root, "/v1/lotus/agent-web-semantic-contracts"),
            "collection_lotus_action": "agent_web_semantic_contracts",
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


def read_agent_web_semantic_contract_descriptor(
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
        "kind": "agent_web_semantic_contract_descriptor",
        "version": int(selection["version"]),
        "contract_id": str(selection["contract_id"]),
        "capability_id": key,
        "latest_version": _latest_contract_version(key),
        "supported_versions": _supported_contract_versions(key),
        "latest_for_capability": int(selection["version"]) == _latest_contract_version(key),
        "standard_profile_id": "agent_web_semantic_read_standard.v1",
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
            "by_contract_id": {"contract_id": str(selection["contract_id"])},
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
        "descriptor_transport": build_agent_web_semantic_contract_reference(
            capability_id=key,
            version=int(selection["version"]),
            contract_id=str(selection["contract_id"]),
            base_url=root,
        ),
    }


def build_agent_web_semantic_contract_reference(
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
        "document_id": "semantic_contracts",
        "rel": "semantic_contracts",
        "http": {
            "method": "GET",
            "path": "/v1/lotus/agent-web-semantic-contracts",
            "href": _href(root, f"/v1/lotus/agent-web-semantic-contracts?contract_id={selected_contract_id}"),
            "query_params": ["capability_id?", "contract_id?", "version?"],
        },
        "lotus": {
            "action": "agent_web_semantic_contracts",
            "params": ["capability_id?", "contract_id?", "version?"],
        },
        "cli": {
            "command": "agent-web-semantic-contracts",
            "args": ["--contract-id", selected_contract_id],
        },
    }


def render_agent_web_semantic_contract_page(manifest: dict) -> str:
    discovery = dict(manifest.get("discovery", {}))
    lines = [
        "# Semantic Contracts",
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
    return {
        "capability_id": key,
        "version": effective_version,
        "contract_id": f"{key}.v{effective_version}",
    }


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
        "semantic_federated_search": {
            "summary": "Stable request/response contract for explainable federated semantic search.",
            "http_path": "/v1/lotus/agent-web-federated-search",
            "http_query_params": ["index_path?", "overlay_path?", "wordnet_path?", "q", "limit?"],
            "lotus_action": "agent_web_federated_search",
            "lotus_params": ["index_path?", "overlay_path?", "wordnet_path?", "query", "limit?"],
            "cli_command": "agent-web-federated-search",
            "request_schema": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "index_path": {"type": "string"},
                    "overlay_path": {"type": "string"},
                    "wordnet_path": {"type": "string"},
                    "query": {"type": "string", "min_length": 1, "http_name": "q"},
                    "limit": {"type": "integer", "minimum": 1},
                },
            },
            "response_schema": {
                "type": "object",
                "required": ["kind", "query", "results", "query_interpretation", "stats"],
                "properties": {
                    "kind": {"type": "string", "const": "agent_web_federated_search_results"},
                    "query": {"type": "string"},
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["record_id", "kind", "title", "source_city_id", "href", "score", "why_matched"],
                            "properties": {
                                "record_id": {"type": "string"},
                                "kind": {"type": "string"},
                                "title": {"type": "string"},
                                "summary": {"type": "string"},
                                "source_city_id": {"type": "string"},
                                "source_repo": {"type": "string"},
                                "href": {"type": "string"},
                                "score": {"type": "number"},
                                "matched_terms": {"type": "array", "items": {"type": "string"}},
                                "why_matched": {
                                    "type": "object",
                                    "properties": {
                                        "direct_term_matches": {"type": "array", "items": {"type": "string"}},
                                        "expanded_term_matches": {"type": "array", "items": {"type": "object"}},
                                        "semantic_bridge_matches": {"type": "array", "items": {"type": "object"}},
                                        "semantic_neighbor_count": {"type": "integer"},
                                        "top_semantic_neighbors": {"type": "array", "items": {"type": "object"}},
                                    },
                                },
                            },
                        },
                    },
                    "query_interpretation": {"type": "object"},
                    "matched_semantic_bridges": {"type": "array", "items": {"type": "object"}},
                    "wordnet_bridge": {"type": "object"},
                    "semantic_extensions": {"type": "object"},
                    "stats": {"type": "object"},
                },
            },
        },
        "semantic_neighbors": {
            "summary": "Stable request/response contract for persisted semantic neighbors of a federated record.",
            "http_path": "/v1/lotus/agent-web-semantic-neighbors",
            "http_query_params": ["index_path?", "record_id", "limit?"],
            "lotus_action": "agent_web_semantic_neighbors",
            "lotus_params": ["index_path?", "record_id", "limit?"],
            "cli_command": "agent-web-semantic-neighbors",
            "request_schema": {
                "type": "object",
                "required": ["record_id"],
                "properties": {
                    "index_path": {"type": "string"},
                    "record_id": {"type": "string", "min_length": 1},
                    "limit": {"type": "integer", "minimum": 1},
                },
            },
            "response_schema": {
                "type": "object",
                "required": ["kind", "record", "neighbors", "stats"],
                "properties": {
                    "kind": {"type": "string", "const": "agent_web_semantic_neighbors"},
                    "record": {
                        "type": "object",
                        "required": ["record_id", "kind", "title", "source_city_id", "href"],
                        "properties": {
                            "record_id": {"type": "string"},
                            "kind": {"type": "string"},
                            "title": {"type": "string"},
                            "source_city_id": {"type": "string"},
                            "href": {"type": "string"},
                        },
                    },
                    "neighbors": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["record_id", "kind", "title", "source_city_id", "href", "score", "reason_kinds"],
                            "properties": {
                                "record_id": {"type": "string"},
                                "kind": {"type": "string"},
                                "title": {"type": "string"},
                                "source_city_id": {"type": "string"},
                                "href": {"type": "string"},
                                "score": {"type": "number"},
                                "reason_kinds": {"type": "array", "items": {"type": "string"}},
                                "shared_terms": {"type": "array", "items": {"type": "string"}},
                                "bridge_ids": {"type": "array", "items": {"type": "string"}},
                                "wordnet_score": {"type": "number"},
                            },
                        },
                    },
                    "stats": {"type": "object"},
                },
            },
        },
        "semantic_expand": {
            "summary": "Stable request/response contract for semantic overlay and WordNet query expansion.",
            "http_path": "/v1/lotus/agent-web-semantic-expand",
            "http_query_params": ["overlay_path?", "wordnet_path?", "q"],
            "lotus_action": "agent_web_semantic_expand",
            "lotus_params": ["overlay_path?", "wordnet_path?", "query"],
            "cli_command": "agent-web-semantic-expand",
            "request_schema": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "overlay_path": {"type": "string"},
                    "wordnet_path": {"type": "string"},
                    "query": {"type": "string", "min_length": 1, "http_name": "q"},
                },
            },
            "response_schema": {
                "type": "object",
                "required": ["kind", "raw_query", "input_terms", "expanded_terms", "weighted_expanded_terms", "stats"],
                "properties": {
                    "kind": {"type": "string", "const": "agent_web_semantic_expansion"},
                    "raw_query": {"type": "string"},
                    "input_terms": {"type": "array", "items": {"type": "string"}},
                    "expanded_terms": {"type": "array", "items": {"type": "string"}},
                    "weighted_expanded_terms": {"type": "array", "items": {"type": "object"}},
                    "matched_bridges": {"type": "array", "items": {"type": "object"}},
                    "wordnet_bridge": {"type": "object"},
                    "stats": {"type": "object"},
                },
            },
        },
    }


def _href(base_url: str, path: str) -> str:
    return f"{base_url}{path}" if base_url else path