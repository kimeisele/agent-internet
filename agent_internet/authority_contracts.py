from __future__ import annotations

from dataclasses import dataclass

from .models import AuthorityExportKind


@dataclass(frozen=True, slots=True)
class AuthorityPageSpec:
    document_id: str
    rel: str
    kind: str
    title: str
    href: str
    entrypoint: bool
    empty_message: str


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
    authority_page: AuthorityPageSpec
    canonical_page: AuthorityPageSpec


STEWARD_PUBLIC_AUTHORITY_CONTRACT = PublicAuthoritySourceContract(
    key="steward",
    label="Steward",
    source_repo_id="steward-protocol",
    binding_id="steward-public-wiki",
    feed_id="steward-authority-bundle",
    target_locator="github.com/kimeisele/steward-protocol.wiki.git",
    owner_boundary="normative_protocol_surface",
    source_exports=(
        AuthorityExportKind.CANONICAL_SURFACE.value,
        AuthorityExportKind.PUBLIC_SUMMARY_REGISTRY.value,
        AuthorityExportKind.SOURCE_SURFACE_REGISTRY.value,
        AuthorityExportKind.REPO_GRAPH.value,
        AuthorityExportKind.SURFACE_METADATA.value,
    ),
    public_surface_label="steward-wiki",
    authority_page=AuthorityPageSpec(
        document_id="steward_authority",
        rel="steward_authority",
        kind="steward_authority",
        title="Steward Authority",
        href="Steward-Authority.md",
        entrypoint=True,
        empty_message="No steward authority exports have been imported yet.",
    ),
    canonical_page=AuthorityPageSpec(
        document_id="steward_canonical_surface",
        rel="steward_canonical_surface",
        kind="steward_canonical_surface",
        title="Steward Canonical Surface",
        href="Steward-Canonical-Surface.md",
        entrypoint=False,
        empty_message="No imported steward canonical documents are available yet.",
    ),
)

AGENT_WORLD_PUBLIC_AUTHORITY_CONTRACT = PublicAuthoritySourceContract(
    key="agent_world",
    label="Agent World",
    source_repo_id="agent-world",
    binding_id="agent-world-public-wiki",
    feed_id="agent-world-authority-bundle",
    target_locator="github.com/kimeisele/agent-world.wiki.git",
    owner_boundary="world_governance_surface",
    source_exports=(
        AuthorityExportKind.CANONICAL_SURFACE.value,
        AuthorityExportKind.PUBLIC_SUMMARY_REGISTRY.value,
        AuthorityExportKind.SOURCE_SURFACE_REGISTRY.value,
        AuthorityExportKind.SURFACE_METADATA.value,
    ),
    public_surface_label="agent-world-wiki",
    authority_page=AuthorityPageSpec(
        document_id="agent_world_authority",
        rel="agent_world_authority",
        kind="agent_world_authority",
        title="Agent World Authority",
        href="Agent-World-Authority.md",
        entrypoint=True,
        empty_message="No imported agent-world authority exports have been imported yet.",
    ),
    canonical_page=AuthorityPageSpec(
        document_id="agent_world_canonical_surface",
        rel="agent_world_canonical_surface",
        kind="agent_world_canonical_surface",
        title="Agent World Canonical Surface",
        href="Agent-World-Canonical-Surface.md",
        entrypoint=False,
        empty_message="No imported agent-world canonical documents are available yet.",
    ),
)


PUBLIC_AUTHORITY_SOURCE_CONTRACTS = (
    AGENT_WORLD_PUBLIC_AUTHORITY_CONTRACT,
    STEWARD_PUBLIC_AUTHORITY_CONTRACT,
)


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


def build_authority_document_specs() -> tuple[tuple[str, str, str, str, str, bool], ...]:
    specs: list[tuple[str, str, str, str, str, bool]] = []
    for contract in PUBLIC_AUTHORITY_SOURCE_CONTRACTS:
        for page in (contract.authority_page, contract.canonical_page):
            specs.append((page.document_id, page.rel, page.kind, page.title, page.href, page.entrypoint))
    return tuple(specs)