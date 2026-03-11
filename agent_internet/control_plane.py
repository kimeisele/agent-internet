from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .authority_contracts import (
    AGENT_WORLD_PUBLIC_AUTHORITY_CONTRACT,
    STEWARD_PUBLIC_AUTHORITY_CONTRACT,
    default_public_authority_source_contract,
    get_public_authority_source_contract_by_repo_id,
    iter_public_authority_source_contracts,
)
from .agent_city_bridge import AgentCityBridge
from .assistant_surface import assistant_social_slot_from_snapshot, assistant_space_from_snapshot
from .memory_registry import InMemoryCityRegistry
from .models import (
    AssistantSurfaceSnapshot,
    AuthorityFeedTransport,
    AuthorityArtifactRecord,
    AuthorityExportKind,
    AuthorityExportRecord,
    CityEndpoint,
    CityIdentity,
    CityPresence,
    EndpointVisibility,
    ForkLineageRecord,
    HostedEndpoint,
    IntentRecord,
    IntentStatus,
    LotusApiToken,
    LotusLinkAddress,
    LotusNetworkAddress,
    LotusRoute,
    LotusRouteResolution,
    LotusServiceAddress,
    ProjectionBindingRecord,
    ProjectionFailurePolicy,
    ProjectionMode,
    ProjectionReconcileStatusRecord,
    PublicationState,
    PublicationStatusRecord,
    RepoRole,
    RepoRoleRecord,
    SourceAuthorityFeedRecord,
    SlotDescriptor,
    SpaceDescriptor,
    TrustLevel,
    TrustRecord,
)
from .router import RegistryRouter
from .steward_protocol_compat import build_maha_route_header_hex, load_steward_protocol_bindings
from .transport import DeliveryEnvelope, DeliveryReceipt, RelayService, TransportRegistry
from .trust import InMemoryTrustEngine


STEWARD_PROTOCOL_REPO_ID = STEWARD_PUBLIC_AUTHORITY_CONTRACT.source_repo_id
AGENT_WORLD_REPO_ID = AGENT_WORLD_PUBLIC_AUTHORITY_CONTRACT.source_repo_id
AGENT_INTERNET_REPO_ID = "agent-internet"
STEWARD_PUBLIC_WIKI_BINDING_ID = STEWARD_PUBLIC_AUTHORITY_CONTRACT.binding_id
STEWARD_AUTHORITY_BUNDLE_FEED_ID = STEWARD_PUBLIC_AUTHORITY_CONTRACT.feed_id
AGENT_WORLD_PUBLIC_WIKI_BINDING_ID = AGENT_WORLD_PUBLIC_AUTHORITY_CONTRACT.binding_id
AGENT_WORLD_AUTHORITY_BUNDLE_FEED_ID = AGENT_WORLD_PUBLIC_AUTHORITY_CONTRACT.feed_id


def _json_sha256(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise TypeError(f"expected_json_object:{path}")
    return payload


def _resolve_bundle_artifact_path(bundle_dir: Path, relative_path: str) -> Path:
    candidate = (bundle_dir / relative_path).resolve()
    root = bundle_dir.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"unsafe_authority_artifact_path:{relative_path}") from exc
    return candidate


def _merge_tuple(existing: tuple[str, ...], *values: str) -> tuple[str, ...]:
    merged = list(existing)
    for value in values:
        if value and value not in merged:
            merged.append(value)
    return tuple(merged)


@dataclass(slots=True)
class AgentInternetControlPlane:
    registry: InMemoryCityRegistry = field(default_factory=InMemoryCityRegistry)
    trust_engine: InMemoryTrustEngine = field(default_factory=InMemoryTrustEngine)
    minimum_trust: TrustLevel = TrustLevel.OBSERVED
    router: RegistryRouter = field(init=False)
    transports: TransportRegistry = field(default_factory=TransportRegistry)
    relay: RelayService = field(init=False)

    def __post_init__(self) -> None:
        self.router = RegistryRouter(
            registry=self.registry,
            discovery=self.registry,
            trust_engine=self.trust_engine,
            minimum_trust=self.minimum_trust,
        )
        self.relay = RelayService(router=self.router, registry=self.transports)

    def register_city(self, identity: CityIdentity, endpoint: CityEndpoint) -> None:
        self.registry.upsert_identity(identity)
        self.registry.upsert_endpoint(endpoint)
        self.assign_lotus_addresses(identity.city_id)

    def announce_city(self, presence: CityPresence) -> None:
        self.registry.announce(presence)

    def record_trust(self, trust: TrustRecord) -> None:
        self.trust_engine.record(trust)

    def resolve_route(self, source_city_id: str, target_city_id: str) -> CityEndpoint | None:
        return self.router.resolve(source_city_id, target_city_id)

    def assign_lotus_addresses(
        self,
        city_id: str,
        *,
        ttl_s: float | None = None,
    ) -> tuple[LotusLinkAddress, LotusNetworkAddress]:
        return (
            self.registry.assign_link_address(city_id, ttl_s=ttl_s),
            self.registry.assign_network_address(city_id, ttl_s=ttl_s),
        )

    def publish_hosted_endpoint(
        self,
        *,
        owner_city_id: str,
        public_handle: str,
        transport: str,
        location: str,
        visibility: EndpointVisibility = EndpointVisibility.PUBLIC,
        ttl_s: float | None = None,
        endpoint_id: str = "",
        labels: dict[str, str] | None = None,
        now: float | None = None,
    ) -> HostedEndpoint:
        link_address, network_address = self.assign_lotus_addresses(owner_city_id)
        started_at = float(time.time() if now is None else now)
        hosted = HostedEndpoint(
            endpoint_id=endpoint_id or f"{owner_city_id}:{public_handle}",
            owner_city_id=owner_city_id,
            public_handle=public_handle,
            transport=transport,
            location=location,
            link_address=link_address.mac_address,
            network_address=network_address.ip_address,
            visibility=visibility,
            lease_started_at=started_at,
            lease_expires_at=None if ttl_s is None else started_at + max(ttl_s, 0.0),
            labels=dict(labels or {}),
        )
        self.registry.upsert_hosted_endpoint(hosted)
        return hosted

    def resolve_public_handle(self, public_handle: str, *, now: float | None = None) -> HostedEndpoint | None:
        return self.router.resolve_public_handle(public_handle, now=now)

    def publish_service_address(
        self,
        *,
        owner_city_id: str,
        service_name: str,
        public_handle: str,
        transport: str,
        location: str,
        visibility: EndpointVisibility = EndpointVisibility.FEDERATED,
        auth_required: bool = True,
        required_scopes: tuple[str, ...] = (),
        ttl_s: float | None = None,
        service_id: str = "",
        labels: dict[str, str] | None = None,
        now: float | None = None,
    ) -> LotusServiceAddress:
        _, network_address = self.assign_lotus_addresses(owner_city_id)
        started_at = float(time.time() if now is None else now)
        service = LotusServiceAddress(
            service_id=service_id or f"{owner_city_id}:{service_name}",
            owner_city_id=owner_city_id,
            service_name=service_name,
            public_handle=public_handle,
            transport=transport,
            location=location,
            network_address=network_address.ip_address,
            visibility=visibility,
            auth_required=auth_required,
            required_scopes=tuple(required_scopes),
            lease_started_at=started_at,
            lease_expires_at=None if ttl_s is None else started_at + max(ttl_s, 0.0),
            labels=dict(labels or {}),
        )
        self.registry.upsert_service_address(service)
        return service

    def resolve_service_address(self, owner_city_id: str, service_name: str, *, now: float | None = None) -> LotusServiceAddress | None:
        return self.router.resolve_service(owner_city_id, service_name, now=now)

    def publish_route(
        self,
        *,
        owner_city_id: str,
        destination_prefix: str,
        target_city_id: str,
        next_hop_city_id: str,
        metric: int = 100,
        nadi_type: str = "",
        priority: str = "",
        ttl_ms: int | None = None,
        ttl_s: float | None = None,
        route_id: str = "",
        labels: dict[str, str] | None = None,
        now: float | None = None,
    ) -> LotusRoute:
        bindings = load_steward_protocol_bindings()
        selected_nadi_type = nadi_type or bindings.default_route_nadi_type
        selected_priority = priority or bindings.default_route_priority
        if selected_nadi_type not in bindings.allowed_nadi_types:
            raise ValueError(f"invalid_nadi_type:{selected_nadi_type}")
        if selected_priority not in bindings.allowed_priorities:
            raise ValueError(f"invalid_priority:{selected_priority}")

        effective_ttl_ms = int(
            ttl_ms if ttl_ms is not None else (ttl_s * 1000 if ttl_s is not None else bindings.default_timeout_ms),
        )
        started_at = float(time.time() if now is None else now)
        route = LotusRoute(
            route_id=route_id or f"{owner_city_id}:{destination_prefix}:{next_hop_city_id}",
            owner_city_id=owner_city_id,
            destination_prefix=destination_prefix,
            target_city_id=target_city_id,
            next_hop_city_id=next_hop_city_id,
            metric=int(metric),
            nadi_type=selected_nadi_type,
            priority=selected_priority,
            ttl_ms=max(0, effective_ttl_ms),
            maha_header_hex=build_maha_route_header_hex(
                source_key=owner_city_id,
                target_key=target_city_id,
                ttl_ms=max(0, effective_ttl_ms),
                metric=int(metric),
            ),
            lease_started_at=started_at,
            lease_expires_at=None if ttl_s is None else started_at + max(ttl_s, 0.0),
            labels=dict(labels or {}),
        )
        self.registry.upsert_route(route)
        return route

    def resolve_next_hop(self, source_city_id: str, destination: str, *, now: float | None = None) -> LotusRouteResolution | None:
        return self.router.resolve_next_hop(source_city_id, destination, now=now)

    def store_api_token(self, token: LotusApiToken) -> None:
        self.registry.upsert_api_token(token)

    def upsert_space(self, space: SpaceDescriptor) -> None:
        self.registry.upsert_space(space)

    def upsert_slot(self, slot: SlotDescriptor) -> None:
        self.registry.upsert_slot(slot)

    def upsert_fork_lineage(self, lineage: ForkLineageRecord) -> None:
        self.registry.upsert_fork_lineage(lineage)

    def upsert_intent(self, intent: IntentRecord) -> None:
        self.registry.upsert_intent(intent)

    def upsert_repo_role(self, record: RepoRoleRecord) -> None:
        self.registry.upsert_repo_role(record)

    def upsert_authority_export(self, record: AuthorityExportRecord) -> None:
        self.registry.upsert_authority_export(record)

    def upsert_authority_artifact(self, record: AuthorityArtifactRecord) -> None:
        self.registry.upsert_authority_artifact(record)

    def upsert_projection_binding(self, record: ProjectionBindingRecord) -> None:
        self.registry.upsert_projection_binding(record)

    def upsert_publication_status(self, record: PublicationStatusRecord) -> None:
        self.registry.upsert_publication_status(record)

    def upsert_source_authority_feed(self, record: SourceAuthorityFeedRecord) -> None:
        self.registry.upsert_source_authority_feed(record)

    def set_source_authority_feed_enabled(self, feed_id: str, *, enabled: bool) -> SourceAuthorityFeedRecord:
        existing = self.registry.get_source_authority_feed(feed_id)
        if existing is None:
            raise ValueError(f"unknown_source_authority_feed:{feed_id}")
        updated = replace(existing, enabled=bool(enabled))
        self.registry.upsert_source_authority_feed(updated)
        return updated

    def configure_source_authority_feed(
        self,
        source_repo_id: str,
        *,
        transport: AuthorityFeedTransport,
        locator: str,
        feed_id: str | None = None,
        poll_interval_seconds: int = 300,
        enabled: bool | None = None,
        labels: dict[str, str] | None = None,
        now: float | None = None,
    ) -> SourceAuthorityFeedRecord:
        contract = get_public_authority_source_contract_by_repo_id(source_repo_id)
        if contract is None:
            contract = default_public_authority_source_contract()
            if source_repo_id != contract.source_repo_id:
                raise ValueError(f"unknown_public_authority_source:{source_repo_id}")
        self._bootstrap_public_wiki_contract(contract=contract, now=now)
        resolved_feed_id = str(feed_id or contract.feed_id)
        existing = self.registry.get_source_authority_feed(resolved_feed_id)
        resolved_locator = str(Path(locator).resolve()) if transport == AuthorityFeedTransport.FILESYSTEM_BUNDLE else str(locator)
        record = SourceAuthorityFeedRecord(
            feed_id=resolved_feed_id,
            source_repo_id=contract.source_repo_id,
            transport=transport,
            locator=resolved_locator,
            binding_ids=(contract.binding_id,),
            enabled=(True if existing is None else existing.enabled) if enabled is None else bool(enabled),
            poll_interval_seconds=max(int(poll_interval_seconds), 1),
            labels={
                "bundle_kind": "source_authority_bundle",
                "source_repo_id": contract.source_repo_id,
                **(dict(existing.labels) if existing is not None else {}),
                **{str(key): str(value) for key, value in dict(labels or {}).items()},
            },
        )
        self.registry.upsert_source_authority_feed(record)
        return record

    def upsert_projection_reconcile_status(self, record: ProjectionReconcileStatusRecord) -> None:
        self.registry.upsert_projection_reconcile_status(record)

    def ingest_authority_bundle(self, bundle: dict[str, Any], *, artifacts: dict[str, dict[str, Any]] | None = None, now: float | None = None) -> dict[str, object]:
        checked_at = float(time.time() if now is None else now)
        if str(bundle.get("kind", "")) != "source_authority_bundle":
            raise ValueError("invalid_authority_bundle_kind")

        role_payload = bundle.get("repo_role")
        if not isinstance(role_payload, dict):
            raise TypeError("invalid_authority_bundle_repo_role")
        repo_role = RepoRoleRecord(
            repo_id=str(role_payload["repo_id"]),
            role=RepoRole(str(role_payload.get("role", RepoRole.RUNTIME_CITY_OPERATOR.value))),
            owner_boundary=str(role_payload.get("owner_boundary", "")),
            exports=tuple(str(item) for item in role_payload.get("exports", ())),
            consumes=tuple(str(item) for item in role_payload.get("consumes", ())),
            publication_targets=tuple(str(item) for item in role_payload.get("publication_targets", ())),
            labels={str(key): str(value) for key, value in dict(role_payload.get("labels", {})).items()},
        )
        contract = get_public_authority_source_contract_by_repo_id(repo_role.repo_id)
        if contract is not None:
            self._bootstrap_public_wiki_contract(contract=contract, now=checked_at)
        self.registry.upsert_repo_role(repo_role)

        artifact_payloads = {str(path): payload for path, payload in (artifacts or {}).items()}
        imported_exports: list[AuthorityExportRecord] = []
        for item in bundle.get("authority_exports", []):
            if not isinstance(item, dict):
                raise TypeError("invalid_authority_export_record")
            record = AuthorityExportRecord(
                export_id=str(item["export_id"]),
                repo_id=str(item["repo_id"]),
                export_kind=AuthorityExportKind(str(item["export_kind"])),
                version=str(item.get("version", "")),
                artifact_uri=str(item.get("artifact_uri", "")),
                generated_at=(None if item.get("generated_at") is None else float(item["generated_at"])),
                contract_version=int(item.get("contract_version", 1)),
                content_sha256=str(item.get("content_sha256", "")),
                labels={str(key): str(value) for key, value in dict(item.get("labels", {})).items()},
            )
            artifact_payload = artifact_payloads.get(record.artifact_uri)
            if artifact_payload is not None and record.content_sha256 and _json_sha256(artifact_payload) != record.content_sha256:
                raise ValueError(f"authority_export_digest_mismatch:{record.export_id}")
            self.registry.upsert_authority_export(record)
            if artifact_payload is not None:
                self.registry.upsert_authority_artifact(
                    AuthorityArtifactRecord(
                        export_id=record.export_id,
                        artifact_uri=record.artifact_uri,
                        payload=dict(artifact_payload),
                        imported_at=checked_at,
                    ),
                )
            imported_exports.append(record)

        publication_statuses = [self._reconcile_projection_binding(binding.binding_id, checked_at=checked_at, bundle=bundle) for binding in self.registry.list_projection_bindings()]
        return {
            "repo_role": repo_role,
            "authority_exports": imported_exports,
            "publication_statuses": publication_statuses,
            "artifact_count": len(artifact_payloads),
        }

    def ingest_authority_bundle_path(self, bundle_path: str | Path, *, now: float | None = None) -> dict[str, object]:
        path = Path(bundle_path).resolve()
        bundle = _load_json_object(path)
        artifact_paths_payload = bundle.get("artifact_paths", {})
        if not isinstance(artifact_paths_payload, dict):
            raise TypeError("invalid_authority_bundle_artifact_paths")
        artifacts = {
            str(relative_path): _load_json_object(_resolve_bundle_artifact_path(path.parent, str(relative_path)))
            for relative_path in artifact_paths_payload.values()
        }
        imported = self.ingest_authority_bundle(bundle, artifacts=artifacts, now=now)
        return imported | {"bundle_path": str(path), "artifact_paths": tuple(sorted(artifacts))}

    def _reconcile_projection_binding(self, binding_id: str, *, checked_at: float, bundle: dict[str, Any]) -> PublicationStatusRecord:
        binding = self.registry.get_projection_binding(binding_id)
        if binding is None:
            raise ValueError(f"unknown_projection_binding:{binding_id}")
        export = self.registry.find_authority_export(binding.source_repo_id, binding.required_export_kind.value)
        existing = self.registry.get_publication_status(binding.binding_id)
        labels = dict(existing.labels if existing is not None else {})
        if export is not None:
            labels.update(
                {
                    "source_export_version": export.version,
                    "source_export_sha256": export.content_sha256,
                },
            )
            bundle_source_sha = str(bundle.get("source_sha", "")).strip()
            if bundle_source_sha:
                labels["authority_bundle_source_sha"] = bundle_source_sha
            if bundle.get("generated_at") is not None:
                labels["authority_bundle_generated_at"] = str(bundle["generated_at"])
        else:
            for key in ("source_export_version", "source_export_sha256", "authority_bundle_source_sha", "authority_bundle_generated_at"):
                labels.pop(key, None)

        if export is None:
            status = PublicationStatusRecord(
                binding_id=binding.binding_id,
                status=PublicationState.BLOCKED,
                projected_from_export_id="",
                target_kind=binding.target_kind,
                target_locator=binding.target_locator,
                checked_at=checked_at,
                stale=False,
                failure_reason=f"missing_authority_export:{binding.source_repo_id}:{binding.required_export_kind.value}",
                labels=labels,
            )
        else:
            matches_current_source = (
                existing is not None
                and existing.projected_from_export_id == export.export_id
                and existing.labels.get("source_export_version", "") == export.version
                and existing.labels.get("source_export_sha256", "") == export.content_sha256
            )
            if matches_current_source and existing.status in {PublicationState.SUCCESS, PublicationState.FAILED, PublicationState.STALE}:
                status = replace(existing, target_kind=binding.target_kind, target_locator=binding.target_locator, checked_at=checked_at, labels=labels)
            else:
                status = PublicationStatusRecord(
                    binding_id=binding.binding_id,
                    status=PublicationState.STALE,
                    projected_from_export_id=export.export_id,
                    target_kind=binding.target_kind,
                    target_locator=binding.target_locator,
                    checked_at=checked_at,
                    stale=True,
                    failure_reason="projection_out_of_date" if existing is not None and existing.published_at is not None else "projection_not_published",
                    labels=labels,
                )
        self.registry.upsert_publication_status(status)
        return status

    def _bootstrap_public_wiki_contract(
        self,
        *,
        contract,
        now: float | None = None,
    ) -> dict[str, object]:
        checked_at = float(time.time() if now is None else now)
        source_repo_id = contract.source_repo_id
        binding_id = contract.binding_id
        existing_source_role = self.registry.get_repo_role(source_repo_id)
        source_role = RepoRoleRecord(
            repo_id=source_repo_id,
            role=RepoRole.NORMATIVE_SOURCE,
            owner_boundary=contract.owner_boundary,
            exports=tuple(contract.source_exports),
            publication_targets=_merge_tuple(existing_source_role.publication_targets if existing_source_role is not None else (), binding_id),
            labels={
                **(dict(existing_source_role.labels) if existing_source_role is not None else {}),
                "public_surface_owner": AGENT_INTERNET_REPO_ID,
            },
        )
        existing_operator_role = self.registry.get_repo_role(AGENT_INTERNET_REPO_ID)
        existing_projects = {
            item.strip()
            for item in str((existing_operator_role.labels if existing_operator_role is not None else {}).get("projects", "")).split(",")
            if item.strip()
        }
        existing_projects.add(source_repo_id)
        operator_role = RepoRoleRecord(
            repo_id=AGENT_INTERNET_REPO_ID,
            role=RepoRole.PUBLIC_MEMBRANE_OPERATOR,
            owner_boundary="public_membrane",
            exports=(
                AuthorityExportKind.AGENT_WEB_MANIFEST.value,
                AuthorityExportKind.PUBLIC_GRAPH.value,
                AuthorityExportKind.SEARCH_INDEX.value,
            ),
            consumes=(
                AuthorityExportKind.CANONICAL_SURFACE.value,
                AuthorityExportKind.PUBLIC_SUMMARY_REGISTRY.value,
                AuthorityExportKind.SOURCE_SURFACE_REGISTRY.value,
                AuthorityExportKind.REPO_GRAPH.value,
                AuthorityExportKind.SURFACE_METADATA.value,
            ),
            publication_targets=_merge_tuple(existing_operator_role.publication_targets if existing_operator_role is not None else (), binding_id),
            labels={
                **(dict(existing_operator_role.labels) if existing_operator_role is not None else {}),
                "projects": ",".join(sorted(existing_projects)),
            },
        )
        existing_binding = self.registry.get_projection_binding(binding_id)
        binding = existing_binding or ProjectionBindingRecord(
            binding_id=binding_id,
            source_repo_id=source_repo_id,
            required_export_kind=AuthorityExportKind.CANONICAL_SURFACE,
            operator_repo_id=AGENT_INTERNET_REPO_ID,
            target_kind="github_wiki",
            target_locator=contract.target_locator,
            projection_mode=ProjectionMode.REQUIRED,
            failure_policy=ProjectionFailurePolicy.FAIL_CLOSED,
            freshness_sla_seconds=3600,
            labels={"public_surface": contract.public_surface_label},
        )
        export = self.registry.find_authority_export(binding.source_repo_id, binding.required_export_kind.value)
        existing_status = self.registry.get_publication_status(binding.binding_id)
        status = existing_status or PublicationStatusRecord(
            binding_id=binding.binding_id,
            status=PublicationState.BLOCKED if export is None else PublicationState.STALE,
            projected_from_export_id="" if export is None else export.export_id,
            target_kind=binding.target_kind,
            target_locator=binding.target_locator,
            checked_at=checked_at,
            stale=export is not None,
            failure_reason=(
                f"missing_authority_export:{binding.source_repo_id}:{binding.required_export_kind.value}"
                if export is None
                else "projection_not_published"
            ),
        )

        self.registry.upsert_repo_role(source_role)
        self.registry.upsert_repo_role(operator_role)
        self.registry.upsert_projection_binding(binding)
        if existing_status is None:
            self.registry.upsert_publication_status(status)
        return {
            "source_repo_role": source_role,
            "operator_repo_role": operator_role,
            "binding": binding,
            "publication_status": self.registry.get_publication_status(binding.binding_id) or status,
        }

    def bootstrap_steward_public_wiki_contract(self, *, now: float | None = None) -> dict[str, object]:
        return self._bootstrap_public_wiki_contract(contract=STEWARD_PUBLIC_AUTHORITY_CONTRACT, now=now)

    def bootstrap_agent_world_public_wiki_contract(self, *, now: float | None = None) -> dict[str, object]:
        return self._bootstrap_public_wiki_contract(contract=AGENT_WORLD_PUBLIC_AUTHORITY_CONTRACT, now=now)

    def bootstrap_public_wiki_contract_for_repo_id(self, source_repo_id: str, *, now: float | None = None) -> dict[str, object]:
        contract = get_public_authority_source_contract_by_repo_id(source_repo_id)
        if contract is None:
            raise ValueError(f"unknown_public_authority_source:{source_repo_id}")
        return self._bootstrap_public_wiki_contract(contract=contract, now=now)

    def bootstrap_default_public_wiki_contracts(self, *, now: float | None = None) -> dict[str, object]:
        return {contract.key: self._bootstrap_public_wiki_contract(contract=contract, now=now) for contract in iter_public_authority_source_contracts()}

    def _bootstrap_public_wiki_feed(
        self,
        *,
        contract,
        bundle_path: str | Path,
        feed_id: str,
        poll_interval_seconds: int = 300,
        now: float | None = None,
    ) -> SourceAuthorityFeedRecord:
        return self.configure_source_authority_feed(
            contract.source_repo_id,
            transport=AuthorityFeedTransport.FILESYSTEM_BUNDLE,
            locator=str(bundle_path),
            feed_id=feed_id,
            poll_interval_seconds=poll_interval_seconds,
            now=now,
        )

    def bootstrap_steward_public_wiki_feed(
        self,
        *,
        bundle_path: str | Path,
        feed_id: str = STEWARD_AUTHORITY_BUNDLE_FEED_ID,
        poll_interval_seconds: int = 300,
        now: float | None = None,
    ) -> SourceAuthorityFeedRecord:
        return self._bootstrap_public_wiki_feed(
            contract=STEWARD_PUBLIC_AUTHORITY_CONTRACT,
            bundle_path=bundle_path,
            feed_id=feed_id,
            poll_interval_seconds=poll_interval_seconds,
            now=now,
        )

    def bootstrap_agent_world_public_wiki_feed(
        self,
        *,
        bundle_path: str | Path,
        feed_id: str = AGENT_WORLD_AUTHORITY_BUNDLE_FEED_ID,
        poll_interval_seconds: int = 300,
        now: float | None = None,
    ) -> SourceAuthorityFeedRecord:
        return self._bootstrap_public_wiki_feed(
            contract=AGENT_WORLD_PUBLIC_AUTHORITY_CONTRACT,
            bundle_path=bundle_path,
            feed_id=feed_id,
            poll_interval_seconds=poll_interval_seconds,
            now=now,
        )

    def bootstrap_public_wiki_feed_for_repo_id(
        self,
        source_repo_id: str,
        *,
        bundle_path: str | Path,
        feed_id: str | None = None,
        poll_interval_seconds: int = 300,
        now: float | None = None,
    ) -> SourceAuthorityFeedRecord:
        contract = get_public_authority_source_contract_by_repo_id(source_repo_id)
        if contract is None:
            contract = default_public_authority_source_contract()
            if source_repo_id != contract.source_repo_id:
                raise ValueError(f"unknown_public_authority_source:{source_repo_id}")
        return self._bootstrap_public_wiki_feed(
            contract=contract,
            bundle_path=bundle_path,
            feed_id=str(feed_id or contract.feed_id),
            poll_interval_seconds=poll_interval_seconds,
            now=now,
        )

    def transition_intent(self, *, intent_id: str, status: IntentStatus, updated_at: float | None = None) -> IntentRecord:
        intent = self.registry.get_intent(intent_id)
        if intent is None:
            raise ValueError(f"unknown_intent:{intent_id}")
        allowed_transitions = {
            IntentStatus.PENDING: {IntentStatus.ACCEPTED, IntentStatus.REJECTED, IntentStatus.CANCELLED},
            IntentStatus.ACCEPTED: {IntentStatus.FULFILLED, IntentStatus.CANCELLED},
        }
        if status not in allowed_transitions.get(intent.status, set()):
            raise ValueError(f"invalid_intent_transition:{intent.status.value}->{status.value}")
        updated = replace(intent, status=status, updated_at=updated_at)
        self.registry.upsert_intent(updated)
        return updated

    def publish_assistant_surface(self, snapshot: AssistantSurfaceSnapshot) -> tuple[SpaceDescriptor, SlotDescriptor]:
        space = assistant_space_from_snapshot(snapshot)
        slot = assistant_social_slot_from_snapshot(snapshot)
        self.registry.upsert_space(space)
        self.registry.upsert_slot(slot)
        return space, slot

    def register_transport(self, scheme: str, transport: object) -> None:
        self.transports.register(scheme, transport)

    def relay_envelope(self, envelope: DeliveryEnvelope) -> DeliveryReceipt:
        return self.relay.relay(envelope)

    def observe_agent_city(
        self,
        bridge: AgentCityBridge,
        *,
        identity: CityIdentity | None = None,
        endpoint: CityEndpoint | None = None,
    ) -> CityPresence | None:
        if identity is not None:
            self.registry.upsert_identity(identity)
        if endpoint is not None:
            self.registry.upsert_endpoint(endpoint)
        presence = bridge.latest_presence()
        if presence is not None:
            self.registry.announce(presence)
        return presence
