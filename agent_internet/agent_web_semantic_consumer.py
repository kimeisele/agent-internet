from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def bootstrap_agent_web_semantic_consumer(
    *,
    base_url: str | None = None,
    bearer_token: str | None = None,
    timeout_s: int | None = None,
    capability_id: str | None = None,
    contract_id: str | None = None,
    version: int | None = None,
    transport: str = "http",
) -> dict:
    config = _resolve_config(base_url=base_url, bearer_token=bearer_token, timeout_s=timeout_s)
    manifest = _fetch_json(config, "/v1/lotus/agent-web-semantic-capabilities")["agent_web_semantic_capabilities"]
    selector = {"capability_id": capability_id, "contract_id": contract_id, "version": version}
    contract = _fetch_json(config, f"/v1/lotus/agent-web-semantic-contracts?{urlencode(_query(selector))}")["agent_web_semantic_contracts"]
    capability = _find_capability(manifest=manifest, capability_id=str(contract["capability_id"]))
    invocation_plan = _build_invocation_plan(contract=contract, transport=transport)
    return {
        "kind": "agent_web_semantic_consumer_bootstrap",
        "version": 1,
        "standard_profile_id": dict(manifest.get("standard_profile", {})).get("profile_id"),
        "provider": {"base_url": config["base_url"]},
        "selector": {"capability_id": contract["capability_id"], "contract_id": contract["contract_id"], "version": contract["version"]},
        "capability": {"capability_id": capability["capability_id"], "summary": capability["summary"], "mode": capability["mode"]},
        "contract": {
            "contract_id": contract["contract_id"],
            "latest_version": contract["latest_version"],
            "supported_versions": contract["supported_versions"],
            "request_schema": contract["request_schema"],
            "response_schema": contract["response_schema"],
            "auth": contract["auth"],
        },
        "invocation_plan": invocation_plan,
        "discovery_trace": {
            "capability_manifest_path": "/v1/lotus/agent-web-semantic-capabilities",
            "contract_descriptor_path": dict(contract.get("descriptor_transport", {})).get("http", {}).get("href", ""),
        },
    }


def invoke_agent_web_semantic_consumer(
    *,
    base_url: str | None = None,
    bearer_token: str | None = None,
    timeout_s: int | None = None,
    capability_id: str | None = None,
    contract_id: str | None = None,
    version: int | None = None,
    input_payload: dict | None = None,
) -> dict:
    config = _resolve_config(base_url=base_url, bearer_token=bearer_token, timeout_s=timeout_s)
    bootstrap = bootstrap_agent_web_semantic_consumer(
        base_url=config["base_url"],
        bearer_token=config["bearer_token"],
        timeout_s=int(config["timeout_s"]),
        capability_id=capability_id,
        contract_id=contract_id,
        version=version,
        transport="http",
    )
    plan = dict(bootstrap.get("invocation_plan", {}))
    http = dict(plan.get("http", {}))
    query = _http_query(plan=plan, input_payload=dict(input_payload or {}))
    response = _fetch_json(config, f"{http.get('path', '')}?{urlencode(query, doseq=True)}")
    return {
        "kind": "agent_web_semantic_consumer_invocation",
        "version": 1,
        "bootstrap": bootstrap,
        "request": {"transport_kind": "http", "path": str(http.get("path", "")), "query": query},
        "response": response,
    }


def _resolve_config(*, base_url: str | None, bearer_token: str | None, timeout_s: int | None) -> dict:
    resolved_base_url = str(base_url or os.environ.get("AGENT_INTERNET_LOTUS_BASE_URL", "")).rstrip("/")
    resolved_token = str(bearer_token or os.environ.get("AGENT_INTERNET_LOTUS_TOKEN", ""))
    resolved_timeout_s = int(timeout_s or os.environ.get("AGENT_INTERNET_LOTUS_TIMEOUT_S", "5"))
    if not resolved_base_url:
        raise ValueError("missing_base_url")
    if not resolved_token:
        raise ValueError("missing_bearer_token")
    return {"base_url": resolved_base_url, "bearer_token": resolved_token, "timeout_s": resolved_timeout_s}


def _fetch_json(config: dict, path: str) -> dict:
    request = Request(f"{config['base_url']}{path}", method="GET")
    request.add_header("Authorization", f"Bearer {config['bearer_token']}")
    request.add_header("Content-Type", "application/json")
    with urlopen(request, timeout=int(config["timeout_s"])) as response:
        return json.loads(response.read().decode("utf-8"))


def _query(values: dict) -> dict[str, str]:
    return {str(key): str(value) for key, value in values.items() if value not in (None, "")}


def _find_capability(*, manifest: dict, capability_id: str) -> dict:
    for capability in manifest.get("capabilities", []):
        payload = dict(capability)
        if payload.get("capability_id") == capability_id:
            return payload
    raise ValueError(f"unknown_capability:{capability_id}")


def _build_invocation_plan(*, contract: dict, transport: str) -> dict:
    payload = dict(contract.get("transport", {})).get(transport)
    if payload is None:
        raise ValueError(f"unsupported_transport:{transport}")
    request_schema = dict(contract.get("request_schema", {}))
    properties = dict(request_schema.get("properties", {}))
    required = set(request_schema.get("required", []))
    return {
        "transport_kind": transport,
        transport: dict(payload),
        "input_bindings": [
            {
                "name": name,
                "required": name in required,
                "transport_name": dict(schema).get("http_name", name) if transport == "http" else name,
                "type": dict(schema).get("type", "object"),
            }
            for name, schema in properties.items()
        ],
    }


def _http_query(*, plan: dict, input_payload: dict) -> dict[str, list[str] | str]:
    query: dict[str, list[str] | str] = {}
    for binding in plan.get("input_bindings", []):
        name = str(binding.get("name", ""))
        if name in input_payload:
            query[str(binding.get("transport_name", name))] = _stringify_query_value(input_payload[name])
        elif bool(binding.get("required", False)):
            raise ValueError(f"missing_input:{name}")
    return query


def _stringify_query_value(value: object) -> list[str] | str:
    if isinstance(value, list):
        return [json.dumps(item, sort_keys=True) if isinstance(item, (dict, list)) else str(item) for item in value]
    if isinstance(value, (dict, tuple)):
        return json.dumps(value, sort_keys=True)
    return str(value)