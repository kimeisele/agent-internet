from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import AuthorityExportKind


@dataclass(frozen=True, slots=True)
class PublicAuthoritySourceContract:
    key: str
    label: str
    source_repo_id: str
    binding_id: str
    feed_id: str
    target_locator: str
    owner_boundary: str
    source_exports: tuple[str, ...]
    public_surface_label: str


STEWARD_PUBLIC_AUTHORITY_CONTRACT = PublicAuthoritySourceContract(
    key="steward",
    label="Steward",
    source_repo_id="steward-protocol",
    binding_id="steward-public-wiki",
    feed_id="steward-authority-bundle",
    target_locator="github.com/kimeisele/agent-internet.wiki.git",
    owner_boundary="normative_protocol_surface",
    source_exports=(
        AuthorityExportKind.CANONICAL_SURFACE.value,
        AuthorityExportKind.PUBLIC_SUMMARY_REGISTRY.value,
        AuthorityExportKind.SOURCE_SURFACE_REGISTRY.value,
        AuthorityExportKind.REPO_GRAPH.value,
        AuthorityExportKind.SURFACE_METADATA.value,
    ),
    public_surface_label="steward-wiki",
)

AGENT_WORLD_PUBLIC_AUTHORITY_CONTRACT = PublicAuthoritySourceContract(
    key="agent_world",
    label="Agent World",
    source_repo_id="agent-world",
    binding_id="agent-world-public-wiki",
    feed_id="agent-world-authority-bundle",
    target_locator="github.com/kimeisele/agent-internet.wiki.git",
    owner_boundary="world_governance_surface",
    source_exports=(
        AuthorityExportKind.CANONICAL_SURFACE.value,
        AuthorityExportKind.PUBLIC_SUMMARY_REGISTRY.value,
        AuthorityExportKind.SOURCE_SURFACE_REGISTRY.value,
        AuthorityExportKind.SURFACE_METADATA.value,
    ),
    public_surface_label="agent-world-wiki",
)


PUBLIC_AUTHORITY_SOURCE_CONTRACTS = (AGENT_WORLD_PUBLIC_AUTHORITY_CONTRACT, STEWARD_PUBLIC_AUTHORITY_CONTRACT)


def iter_public_authority_source_contracts() -> tuple[PublicAuthoritySourceContract, ...]:
    return PUBLIC_AUTHORITY_SOURCE_CONTRACTS


def default_public_authority_source_contract() -> PublicAuthoritySourceContract:
    return STEWARD_PUBLIC_AUTHORITY_CONTRACT


def get_public_authority_source_contract_by_repo_id(repo_id: str) -> PublicAuthoritySourceContract | None:
    return next((item for item in PUBLIC_AUTHORITY_SOURCE_CONTRACTS if item.source_repo_id == str(repo_id)), None)


def get_public_authority_source_contract_by_binding_id(binding_id: str) -> PublicAuthoritySourceContract | None:
    return next((item for item in PUBLIC_AUTHORITY_SOURCE_CONTRACTS if item.binding_id == str(binding_id)), None)


def get_public_authority_source_contract_by_feed_id(feed_id: str) -> PublicAuthoritySourceContract | None:
    return next((item for item in PUBLIC_AUTHORITY_SOURCE_CONTRACTS if item.feed_id == str(feed_id)), None)


def build_authority_document_specs(state_snapshot: dict[str, Any]) -> tuple[tuple[str, str, str, str, str, bool], ...]:
    return tuple(
        (doc["document_id"], doc["rel"], doc["kind"], doc["title"], doc["href"], doc["entrypoint"])
        for doc in build_authority_projection_documents(state_snapshot)
    )


def build_authority_projection_documents(state_snapshot: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    documents: list[dict[str, Any]] = []
    for contract in PUBLIC_AUTHORITY_SOURCE_CONTRACTS:
        artifacts_by_kind = _artifacts_by_kind_for_repo(state_snapshot, contract.source_repo_id)
        config = _public_surface_config(contract, artifacts_by_kind)
        documents.extend(
            [
                {
                    **config["overview_page"],
                    "render_mode": "overview",
                    "sidebar": True,
                    "source_repo_id": contract.source_repo_id,
                    "source_label": config["repo_label"],
                    "binding_id": contract.binding_id,
                    "empty_message": f"No imported {contract.source_repo_id} authority exports have been imported yet.",
                },
                {
                    **config["canonical_index_page"],
                    "render_mode": "canonical_index",
                    "sidebar": True,
                    "source_repo_id": contract.source_repo_id,
                    "source_label": config["repo_label"],
                    "binding_id": contract.binding_id,
                    "empty_message": f"No imported {contract.source_repo_id} canonical documents are available yet.",
                },
            ],
        )
        documents.extend(_canonical_document_projection_docs(contract, artifacts_by_kind, config))
    return tuple(documents)


def _artifacts_by_kind_for_repo(state_snapshot: dict[str, Any], source_repo_id: str) -> dict[str, dict[str, Any]]:
    exports_by_kind = {
        str(record.get("export_kind", "")): dict(record)
        for record in list(state_snapshot.get("authority_exports", []))
        if isinstance(record, dict) and str(record.get("repo_id", "")) == source_repo_id and str(record.get("export_kind", ""))
    }
    artifacts_by_export_id = {
        str(record.get("export_id", "")): dict(record)
        for record in list(state_snapshot.get("authority_artifacts", []))
        if isinstance(record, dict)
    }
    artifacts_by_kind: dict[str, dict[str, Any]] = {}
    for export_kind, export_record in exports_by_kind.items():
        payload = dict(artifacts_by_export_id.get(str(export_record.get("export_id", "")), {}).get("payload") or {})
        if payload:
            artifacts_by_kind[export_kind] = payload
    return artifacts_by_kind


def _public_surface_config(contract: PublicAuthoritySourceContract, artifacts_by_kind: dict[str, dict[str, Any]]) -> dict[str, Any]:
    metadata = dict(artifacts_by_kind.get("surface_metadata", {}))
    public_surface = dict(metadata.get("public_surface", {}))
    repo_label = str(public_surface.get("repo_label") or contract.label)
    document_prefix = str(public_surface.get("document_prefix") or contract.key)
    return {
        "repo_label": repo_label,
        "document_prefix": document_prefix,
        "overview_page": _page_config(
            public_surface.get("overview_page"),
            default_document_id=f"{contract.key}_authority",
            default_rel=f"{contract.key}_authority",
            default_kind=f"{contract.key}_authority",
            default_title=f"{repo_label} Authority",
            default_wiki_name=f"{repo_label.replace(' ', '-')}-Authority",
            default_entrypoint=True,
        ),
        "canonical_index_page": _page_config(
            public_surface.get("canonical_index_page"),
            default_document_id=f"{contract.key}_canonical_surface",
            default_rel=f"{contract.key}_canonical_surface",
            default_kind=f"{contract.key}_canonical_surface",
            default_title=f"{repo_label} Canonical Surface",
            default_wiki_name=f"{repo_label.replace(' ', '-')}-Canonical-Surface",
            default_entrypoint=False,
        ),
    }


def _page_config(payload: object, **defaults: object) -> dict[str, Any]:
    record = dict(payload) if isinstance(payload, dict) else {}
    wiki_name = str(record.get("wiki_name") or defaults["default_wiki_name"])
    return {
        "document_id": str(record.get("document_id") or defaults["default_document_id"]),
        "rel": str(record.get("rel") or defaults["default_rel"]),
        "kind": str(record.get("kind") or defaults["default_kind"]),
        "title": str(record.get("title") or defaults["default_title"]),
        "href": str(record.get("href") or f"{wiki_name}.md"),
        "entrypoint": _truthy(record.get("entrypoint"), default=bool(defaults["default_entrypoint"])),
    }


def _canonical_document_projection_docs(
    contract: PublicAuthoritySourceContract,
    artifacts_by_kind: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    source_records = _source_surface_records(artifacts_by_kind.get("source_surface_registry", {}))
    canonical_documents = _source_surface_records(artifacts_by_kind.get("canonical_surface", {}))
    summary_records = _source_surface_records(artifacts_by_kind.get("public_summary_registry", {}))
    registry_by_id = {_record_id(record): record for record in source_records if _record_id(record)}
    canonical_by_id = {_record_id(record): record for record in canonical_documents if _record_id(record)}
    summary_by_id = {_record_id(record): record for record in summary_records if _record_id(record)}
    ordered_ids = [record_id for record_id in (_record_id(record) for record in source_records) if record_id]
    for record_id in canonical_by_id:
        if record_id not in ordered_ids:
            ordered_ids.append(record_id)
    projected: list[dict[str, Any]] = []
    for record_id in ordered_ids:
        registry_record = registry_by_id.get(record_id, {})
        canonical_record = canonical_by_id.get(record_id, {})
        summary_record = summary_by_id.get(record_id, {})
        labels = _merged_labels(summary_record, registry_record, canonical_record)
        title = str(canonical_record.get("title") or registry_record.get("title") or summary_record.get("title") or record_id)
        wiki_name = str(canonical_record.get("wiki_name") or registry_record.get("wiki_name") or summary_record.get("wiki_name") or title.replace(" ", "-"))
        entrypoint = str(labels.get("source_role", "")).strip().lower() == "entrypoint" or _truthy(labels.get("entrypoint"))
        projected.append(
            {
                "document_id": f"{config['document_prefix']}_{record_id}",
                "rel": f"{config['document_prefix']}_{record_id}",
                "kind": "source_authority_document",
                "title": title,
                "href": f"{wiki_name}.md",
                "entrypoint": entrypoint,
                "sidebar": entrypoint or _truthy(labels.get("include_in_sidebar")) or _truthy(labels.get("featured")),
                "sidebar_title": str(labels.get("nav_label") or title),
                "render_mode": "canonical_document",
                "source_repo_id": contract.source_repo_id,
                "source_label": config["repo_label"],
                "binding_id": contract.binding_id,
                "source_document_id": record_id,
            },
        )
    return projected


def _source_surface_records(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    candidates = payload.get("documents") or payload.get("records") or payload.get("pages") or []
    return [dict(record) for record in list(candidates) if isinstance(record, dict)]


def _record_id(record: dict[str, Any]) -> str:
    return str(record.get("document_id") or record.get("id") or "").strip()


def _merged_labels(*records: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for record in records:
        payload = record.get("labels") if isinstance(record, dict) else None
        if isinstance(payload, dict):
            labels.update({str(key): str(value) for key, value in payload.items()})
    return labels


def _truthy(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}