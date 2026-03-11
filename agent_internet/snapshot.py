from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, TypeVar

from .file_locking import read_locked_json_value, update_locked_json_value, write_locked_json_value
from .control_plane import AgentInternetControlPlane
from .models import (
    AuthorityFeedTransport,
    AuthorityArtifactRecord,
    AuthorityExportKind,
    AuthorityExportRecord,
    ClaimStatus,
    SlotDescriptor,
    SlotLeaseRecord,
    CityEndpoint,
    CityIdentity,
    CityPresence,
    EndpointVisibility,
    ForkLineageRecord,
    ForkMode,
    HealthStatus,
    HostedEndpoint,
    IntentRecord,
    IntentStatus,
    IntentType,
    LeaseStatus,
    LotusApiToken,
    LotusLinkAddress,
    LotusNetworkAddress,
    OperationReceiptRecord,
    LotusRoute,
    LotusServiceAddress,
    ProjectionBindingRecord,
    ProjectionFailurePolicy,
    ProjectionMode,
    ProjectionReconcileState,
    ProjectionReconcileStatusRecord,
    PublicationState,
    PublicationStatusRecord,
    RepoRole,
    RepoRoleRecord,
    SourceAuthorityFeedRecord,
    SpaceClaimRecord,
    SlotStatus,
    SpaceDescriptor,
    SpaceKind,
    TrustLevel,
    TrustRecord,
    UpstreamSyncPolicy,
)

_T = TypeVar("_T")


def snapshot_control_plane(plane: AgentInternetControlPlane) -> dict:
    return {
        "minimum_trust": plane.minimum_trust.value,
        "identities": [asdict(identity) for identity in plane.registry.list_identities()],
        "endpoints": [asdict(endpoint) for endpoint in plane.registry.list_endpoints()],
        "link_addresses": [asdict(address) for address in plane.registry.list_link_addresses()],
        "network_addresses": [asdict(address) for address in plane.registry.list_network_addresses()],
        "hosted_endpoints": [asdict(endpoint) for endpoint in plane.registry.list_hosted_endpoints()],
        "service_addresses": [asdict(service) for service in plane.registry.list_service_addresses()],
        "routes": [asdict(route) for route in plane.registry.list_routes()],
        "api_tokens": [asdict(token) for token in plane.registry.list_api_tokens()],
        "operation_receipts": [asdict(receipt) for receipt in plane.registry.list_operation_receipts()],
        "spaces": [asdict(space) for space in plane.registry.list_spaces()],
        "slots": [asdict(slot) for slot in plane.registry.list_slots()],
        "space_claims": [asdict(claim) for claim in plane.registry.list_space_claims()],
        "slot_leases": [asdict(lease) for lease in plane.registry.list_slot_leases()],
        "fork_lineage": [asdict(lineage) for lineage in plane.registry.list_fork_lineage()],
        "intents": [asdict(intent) for intent in plane.registry.list_intents()],
        "repo_roles": [asdict(record) for record in plane.registry.list_repo_roles()],
        "authority_exports": [asdict(record) for record in plane.registry.list_authority_exports()],
        "authority_artifacts": [asdict(record) for record in plane.registry.list_authority_artifacts()],
        "projection_bindings": [asdict(record) for record in plane.registry.list_projection_bindings()],
        "publication_statuses": [asdict(record) for record in plane.registry.list_publication_statuses()],
        "source_authority_feeds": [asdict(record) for record in plane.registry.list_source_authority_feeds()],
        "projection_reconcile_statuses": [asdict(record) for record in plane.registry.list_projection_reconcile_statuses()],
        "presence": [asdict(presence) for presence in plane.registry.list_cities()],
        "trust": [asdict(record) for record in plane.trust_engine.list_records()],
        "allocator": plane.registry.allocation_state(),
    }


def restore_control_plane(payload: dict) -> AgentInternetControlPlane:
    plane = AgentInternetControlPlane(minimum_trust=TrustLevel(payload.get("minimum_trust", "observed")))

    for data in payload.get("identities", []):
        plane.registry.upsert_identity(CityIdentity(**data))
    for data in payload.get("endpoints", []):
        plane.registry.upsert_endpoint(CityEndpoint(**data))
    for data in payload.get("link_addresses", []):
        plane.registry._link_addresses[data["city_id"]] = LotusLinkAddress(**data)
    for data in payload.get("network_addresses", []):
        plane.registry._network_addresses[data["city_id"]] = LotusNetworkAddress(**data)
    for data in payload.get("hosted_endpoints", []):
        hosted = HostedEndpoint(
            endpoint_id=data["endpoint_id"],
            owner_city_id=data["owner_city_id"],
            public_handle=data["public_handle"],
            transport=data["transport"],
            location=data["location"],
            link_address=data["link_address"],
            network_address=data["network_address"],
            visibility=EndpointVisibility(data.get("visibility", "public")),
            lease_started_at=data.get("lease_started_at"),
            lease_expires_at=data.get("lease_expires_at"),
            labels=dict(data.get("labels", {})),
        )
        plane.registry.upsert_hosted_endpoint(hosted)
    for data in payload.get("service_addresses", []):
        plane.registry.upsert_service_address(
            LotusServiceAddress(
                service_id=data["service_id"],
                owner_city_id=data["owner_city_id"],
                service_name=data["service_name"],
                public_handle=data["public_handle"],
                transport=data["transport"],
                location=data["location"],
                network_address=data["network_address"],
                visibility=EndpointVisibility(data.get("visibility", "federated")),
                auth_required=bool(data.get("auth_required", True)),
                required_scopes=tuple(data.get("required_scopes", ())),
                lease_started_at=data.get("lease_started_at"),
                lease_expires_at=data.get("lease_expires_at"),
                labels=dict(data.get("labels", {})),
            ),
        )
    for data in payload.get("routes", []):
        plane.registry.upsert_route(
            LotusRoute(
                route_id=data["route_id"],
                owner_city_id=data["owner_city_id"],
                destination_prefix=data["destination_prefix"],
                target_city_id=data["target_city_id"],
                next_hop_city_id=data["next_hop_city_id"],
                metric=int(data.get("metric", 100)),
                nadi_type=data.get("nadi_type", "vyana"),
                priority=data.get("priority", "rajas"),
                ttl_ms=int(data.get("ttl_ms", 24_000)),
                maha_header_hex=data.get("maha_header_hex", ""),
                lease_started_at=data.get("lease_started_at"),
                lease_expires_at=data.get("lease_expires_at"),
                labels=dict(data.get("labels", {})),
            ),
        )
    for data in payload.get("api_tokens", []):
        plane.registry.upsert_api_token(
            LotusApiToken(
                token_id=data["token_id"],
                subject=data["subject"],
                token_hint=data["token_hint"],
                token_sha256=data["token_sha256"],
                scopes=tuple(data.get("scopes", ())),
                issued_at=data.get("issued_at"),
                revoked_at=data.get("revoked_at"),
            ),
        )
    for data in payload.get("operation_receipts", []):
        plane.registry.upsert_operation_receipt(
            OperationReceiptRecord(
                operation_id=data["operation_id"],
                request_id=data["request_id"],
                action=data["action"],
                operator_subject=data.get("operator_subject", ""),
                request_sha256=data.get("request_sha256", ""),
                status=data.get("status", "applied"),
                response_payload=dict(data.get("response_payload", {})),
                created_at=data.get("created_at"),
                last_replayed_at=data.get("last_replayed_at"),
                replay_count=int(data.get("replay_count", 0)),
            ),
        )
    for data in payload.get("spaces", []):
        plane.registry.upsert_space(
            SpaceDescriptor(
                space_id=data["space_id"],
                kind=SpaceKind(data.get("kind", SpaceKind.PUBLIC_SURFACE.value)),
                owner_subject_id=data["owner_subject_id"],
                display_name=data.get("display_name", ""),
                city_id=data.get("city_id", ""),
                repo=data.get("repo", ""),
                heartbeat_source=data.get("heartbeat_source", ""),
                heartbeat=data.get("heartbeat"),
                last_seen_at=data.get("last_seen_at"),
                labels=dict(data.get("labels", {})),
            ),
        )
    for data in payload.get("slots", []):
        plane.registry.upsert_slot(
            SlotDescriptor(
                slot_id=data["slot_id"],
                space_id=data["space_id"],
                slot_kind=data.get("slot_kind", ""),
                holder_subject_id=data.get("holder_subject_id", ""),
                status=SlotStatus(data.get("status", SlotStatus.UNKNOWN.value)),
                capacity=int(data.get("capacity", 1)),
                heartbeat_source=data.get("heartbeat_source", ""),
                heartbeat=data.get("heartbeat"),
                last_seen_at=data.get("last_seen_at"),
                lease_expires_at=data.get("lease_expires_at"),
                reclaimable_since_at=data.get("reclaimable_since_at"),
                labels=dict(data.get("labels", {})),
            ),
        )
    for data in payload.get("space_claims", []):
        plane.registry.upsert_space_claim(
            SpaceClaimRecord(
                claim_id=data["claim_id"],
                source_intent_id=data.get("source_intent_id", ""),
                subject_id=data.get("subject_id", ""),
                space_id=data.get("space_id", ""),
                slot_id=data.get("slot_id", ""),
                claim_type=data.get("claim_type", "space_claim"),
                status=ClaimStatus(data.get("status", ClaimStatus.GRANTED.value)),
                requested_at=data.get("requested_at"),
                granted_at=data.get("granted_at"),
                released_at=data.get("released_at"),
                expires_at=data.get("expires_at"),
                supersedes_claim_id=data.get("supersedes_claim_id", ""),
                superseded_by_claim_id=data.get("superseded_by_claim_id", ""),
                labels=dict(data.get("labels", {})),
            )
        )
    for data in payload.get("slot_leases", []):
        plane.registry.upsert_slot_lease(
            SlotLeaseRecord(
                lease_id=data["lease_id"],
                source_intent_id=data.get("source_intent_id", ""),
                holder_subject_id=data.get("holder_subject_id", ""),
                space_id=data.get("space_id", ""),
                slot_id=data.get("slot_id", ""),
                status=LeaseStatus(data.get("status", LeaseStatus.ACTIVE.value)),
                granted_at=data.get("granted_at"),
                released_at=data.get("released_at"),
                expires_at=data.get("expires_at"),
                reclaimable_since_at=data.get("reclaimable_since_at"),
                supersedes_lease_id=data.get("supersedes_lease_id", ""),
                superseded_by_lease_id=data.get("superseded_by_lease_id", ""),
                labels=dict(data.get("labels", {})),
            )
        )
    for data in payload.get("fork_lineage", []):
        plane.registry.upsert_fork_lineage(
            ForkLineageRecord(
                lineage_id=data["lineage_id"],
                repo=data["repo"],
                upstream_repo=data.get("upstream_repo", ""),
                line_root_repo=data.get("line_root_repo", ""),
                fork_mode=ForkMode(data.get("fork_mode", ForkMode.EXPERIMENT.value)),
                sync_policy=UpstreamSyncPolicy(data.get("sync_policy", UpstreamSyncPolicy.MANUAL_ONLY.value)),
                space_id=data.get("space_id", ""),
                upstream_space_id=data.get("upstream_space_id", ""),
                forked_by_subject_id=data.get("forked_by_subject_id", ""),
                created_at=data.get("created_at"),
                labels=dict(data.get("labels", {})),
            ),
        )
    for data in payload.get("intents", []):
        plane.registry.upsert_intent(
            IntentRecord(
                intent_id=data["intent_id"],
                intent_type=IntentType(data.get("intent_type", IntentType.REQUEST_OPERATOR_REVIEW.value)),
                status=IntentStatus(data.get("status", IntentStatus.PENDING.value)),
                title=data.get("title", ""),
                description=data.get("description", ""),
                requested_by_subject_id=data.get("requested_by_subject_id", ""),
                repo=data.get("repo", ""),
                city_id=data.get("city_id", ""),
                space_id=data.get("space_id", ""),
                slot_id=data.get("slot_id", ""),
                lineage_id=data.get("lineage_id", ""),
                discussion_id=data.get("discussion_id", ""),
                linked_issue_url=data.get("linked_issue_url", ""),
                linked_pr_url=data.get("linked_pr_url", ""),
                created_at=data.get("created_at"),
                updated_at=data.get("updated_at"),
                labels=dict(data.get("labels", {})),
            ),
        )
    for data in payload.get("repo_roles", []):
        plane.registry.upsert_repo_role(
            RepoRoleRecord(
                repo_id=data["repo_id"],
                role=RepoRole(data.get("role", RepoRole.RUNTIME_CITY_OPERATOR.value)),
                owner_boundary=data.get("owner_boundary", ""),
                exports=tuple(data.get("exports", ())),
                consumes=tuple(data.get("consumes", ())),
                publication_targets=tuple(data.get("publication_targets", ())),
                labels=dict(data.get("labels", {})),
            ),
        )
    for data in payload.get("authority_exports", []):
        plane.registry.upsert_authority_export(
            AuthorityExportRecord(
                export_id=data["export_id"],
                repo_id=data["repo_id"],
                export_kind=AuthorityExportKind(data.get("export_kind", AuthorityExportKind.CANONICAL_SURFACE.value)),
                version=data.get("version", ""),
                artifact_uri=data.get("artifact_uri", ""),
                generated_at=data.get("generated_at"),
                contract_version=int(data.get("contract_version", 1)),
                content_sha256=data.get("content_sha256", ""),
                labels=dict(data.get("labels", {})),
            ),
        )
    for data in payload.get("authority_artifacts", []):
        plane.registry.upsert_authority_artifact(
            AuthorityArtifactRecord(
                export_id=data["export_id"],
                artifact_uri=data.get("artifact_uri", ""),
                payload=dict(data.get("payload", {})),
                imported_at=data.get("imported_at"),
            ),
        )
    for data in payload.get("projection_bindings", []):
        plane.registry.upsert_projection_binding(
            ProjectionBindingRecord(
                binding_id=data["binding_id"],
                source_repo_id=data["source_repo_id"],
                required_export_kind=AuthorityExportKind(data.get("required_export_kind", AuthorityExportKind.CANONICAL_SURFACE.value)),
                operator_repo_id=data["operator_repo_id"],
                target_kind=data.get("target_kind", ""),
                target_locator=data.get("target_locator", ""),
                projection_mode=ProjectionMode(data.get("projection_mode", ProjectionMode.REQUIRED.value)),
                failure_policy=ProjectionFailurePolicy(data.get("failure_policy", ProjectionFailurePolicy.FAIL_CLOSED.value)),
                freshness_sla_seconds=int(data.get("freshness_sla_seconds", 3600)),
                labels=dict(data.get("labels", {})),
            ),
        )
    for data in payload.get("publication_statuses", []):
        plane.registry.upsert_publication_status(
            PublicationStatusRecord(
                binding_id=data["binding_id"],
                status=PublicationState(data.get("status", PublicationState.BLOCKED.value)),
                projected_from_export_id=data.get("projected_from_export_id", ""),
                target_kind=data.get("target_kind", ""),
                target_locator=data.get("target_locator", ""),
                published_at=data.get("published_at"),
                checked_at=data.get("checked_at"),
                stale=bool(data.get("stale", False)),
                failure_reason=data.get("failure_reason", ""),
                labels=dict(data.get("labels", {})),
            ),
        )
    for data in payload.get("source_authority_feeds", []):
        plane.registry.upsert_source_authority_feed(
            SourceAuthorityFeedRecord(
                feed_id=data["feed_id"],
                source_repo_id=data["source_repo_id"],
                transport=AuthorityFeedTransport(data.get("transport", AuthorityFeedTransport.FILESYSTEM_BUNDLE.value)),
                locator=data.get("locator", ""),
                binding_ids=tuple(str(item) for item in data.get("binding_ids", ())),
                enabled=bool(data.get("enabled", True)),
                poll_interval_seconds=int(data.get("poll_interval_seconds", 300)),
                labels=dict(data.get("labels", {})),
            ),
        )
    for data in payload.get("projection_reconcile_statuses", []):
        plane.registry.upsert_projection_reconcile_status(
            ProjectionReconcileStatusRecord(
                binding_id=data["binding_id"],
                feed_id=data["feed_id"],
                status=ProjectionReconcileState(data.get("status", ProjectionReconcileState.SKIPPED.value)),
                last_checked_at=data.get("last_checked_at"),
                last_imported_at=data.get("last_imported_at"),
                last_imported_source_sha=data.get("last_imported_source_sha", ""),
                last_imported_export_version=data.get("last_imported_export_version", ""),
                last_publish_attempt_at=data.get("last_publish_attempt_at"),
                last_success_at=data.get("last_success_at"),
                consecutive_failures=int(data.get("consecutive_failures", 0)),
                next_retry_at=data.get("next_retry_at"),
                last_error=data.get("last_error", ""),
                labels=dict(data.get("labels", {})),
            ),
        )
    for data in payload.get("presence", []):
        plane.registry.announce(
            CityPresence(
                city_id=data["city_id"],
                health=HealthStatus(data.get("health", "unknown")),
                last_seen_at=data.get("last_seen_at"),
                heartbeat=data.get("heartbeat"),
                capabilities=tuple(data.get("capabilities", ())),
            ),
        )
    for data in payload.get("trust", []):
        plane.trust_engine.record(
            TrustRecord(
                issuer_city_id=data["issuer_city_id"],
                subject_city_id=data["subject_city_id"],
                level=TrustLevel(data.get("level", "unknown")),
                reason=data.get("reason", ""),
            ),
        )
    allocator = payload.get("allocator", {})
    plane.registry.restore_allocation_state(
        next_link_id=allocator.get("next_link_id", len(payload.get("link_addresses", [])) + 1),
        next_network_id=allocator.get("next_network_id", len(payload.get("network_addresses", [])) + 1),
    )

    return plane


@dataclass(slots=True)
class ControlPlaneStateStore:
    path: Path

    def load(self) -> AgentInternetControlPlane:
        data = read_locked_json_value(self.path, default={})
        if not data:
            return AgentInternetControlPlane()
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict payload in {self.path}")
        return restore_control_plane(data)

    def save(self, plane: AgentInternetControlPlane) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_locked_json_value(self.path, snapshot_control_plane(plane))

    def update(self, updater: Callable[[AgentInternetControlPlane], _T]) -> _T:
        result: list[_T] = []

        def _update_payload(current: dict) -> dict:
            if not isinstance(current, dict):
                raise TypeError(f"Expected dict payload in {self.path}")
            plane = restore_control_plane(current)
            result.append(updater(plane))
            return snapshot_control_plane(plane)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        update_locked_json_value(
            self.path,
            default=snapshot_control_plane(AgentInternetControlPlane()),
            updater=_update_payload,
        )
        return result[0]
