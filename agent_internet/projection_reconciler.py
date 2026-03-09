from __future__ import annotations

import time
from pathlib import Path

from .control_plane import STEWARD_AUTHORITY_BUNDLE_FEED_ID, AgentInternetControlPlane
from .models import ProjectionReconcileState, ProjectionReconcileStatusRecord, PublicationState, PublicationStatusRecord, SourceAuthorityFeedRecord
from .publisher import publish_agent_internet_wiki
from .snapshot import ControlPlaneStateStore


def _retry_at(*, checked_at: float, poll_interval_seconds: int, consecutive_failures: int) -> float:
    backoff = 0 if consecutive_failures <= 0 else min(3600, 60 * (2 ** (consecutive_failures - 1)))
    return checked_at + max(int(poll_interval_seconds), backoff)


def _publication_requires_publish(status: PublicationStatusRecord | None) -> bool:
    return status is not None and (status.status in {PublicationState.STALE, PublicationState.FAILED} or bool(status.stale))


def _resolve_binding_id(feed: SourceAuthorityFeedRecord) -> str:
    if len(feed.binding_ids) != 1:
        raise ValueError(f"unsupported_reconcile_binding_count:{feed.feed_id}:{len(feed.binding_ids)}")
    return str(feed.binding_ids[0])


class ProjectionReconciler:
    def __init__(self, *, root: Path | str, state_path: Path | str):
        self.root = Path(root).resolve()
        self.state_path = Path(state_path)
        self.store = ControlPlaneStateStore(path=self.state_path)

    def run_once(
        self,
        *,
        bundle_path: Path | str | None = None,
        feed_id: str = STEWARD_AUTHORITY_BUNDLE_FEED_ID,
        poll_interval_seconds: int = 300,
        wiki_repo_url: str | None = None,
        wiki_path: Path | None = None,
        push: bool = False,
        prune_generated: bool = False,
    ) -> dict[str, object]:
        checked_at = float(time.time())
        feed = self.store.update(
            lambda plane: self._ensure_feed(
                plane,
                feed_id=feed_id,
                bundle_path=bundle_path,
                poll_interval_seconds=poll_interval_seconds,
                checked_at=checked_at,
            ),
        )
        binding_id = _resolve_binding_id(feed)
        if not feed.enabled:
            record = self.store.update(
                lambda plane: self._record_status(
                    plane,
                    binding_id=binding_id,
                    feed=feed,
                    checked_at=checked_at,
                    status=ProjectionReconcileState.SKIPPED,
                    last_error="feed_disabled",
                    imported=False,
                ),
            )
            return self._result(feed=feed, publication_status=self.store.load().registry.get_publication_status(binding_id), reconcile_status=record, publish_required=False, publish_result=None)
        try:
            self.store.update(lambda plane: plane.ingest_authority_bundle_path(feed.locator, now=checked_at))
        except Exception as exc:
            record = self.store.update(
                lambda plane: self._record_status(
                    plane,
                    binding_id=binding_id,
                    feed=feed,
                    checked_at=checked_at,
                    status=ProjectionReconcileState.FAILED,
                    last_error=f"authority_bundle_import_failed:{type(exc).__name__}:{exc}",
                    imported=False,
                ),
            )
            return self._result(feed=feed, publication_status=self.store.load().registry.get_publication_status(binding_id), reconcile_status=record, publish_required=False, publish_result=None)
        plane = self.store.load()
        publication_status = plane.registry.get_publication_status(binding_id)
        if publication_status is None:
            record = self.store.update(
                lambda current: self._record_status(
                    current,
                    binding_id=binding_id,
                    feed=feed,
                    checked_at=checked_at,
                    status=ProjectionReconcileState.FAILED,
                    last_error=f"missing_publication_status:{binding_id}",
                    imported=True,
                ),
            )
            return self._result(feed=feed, publication_status=None, reconcile_status=record, publish_required=False, publish_result=None)
        if publication_status.status == PublicationState.BLOCKED:
            record = self.store.update(
                lambda current: self._record_status(
                    current,
                    binding_id=binding_id,
                    feed=feed,
                    checked_at=checked_at,
                    status=ProjectionReconcileState.BLOCKED,
                    last_error=publication_status.failure_reason,
                    imported=True,
                    publication_status=publication_status,
                ),
            )
            return self._result(feed=feed, publication_status=publication_status, reconcile_status=record, publish_required=False, publish_result=None)
        publish_required = _publication_requires_publish(publication_status)
        if not publish_required:
            record = self.store.update(
                lambda current: self._record_status(
                    current,
                    binding_id=binding_id,
                    feed=feed,
                    checked_at=checked_at,
                    status=ProjectionReconcileState.SUCCESS,
                    last_error="",
                    imported=True,
                    publication_status=publication_status,
                ),
            )
            return self._result(feed=feed, publication_status=publication_status, reconcile_status=record, publish_required=False, publish_result=None)
        publish_started_at = float(time.time())
        try:
            publish_result = publish_agent_internet_wiki(
                root=self.root,
                state_path=self.state_path,
                wiki_path=wiki_path,
                wiki_repo_url=wiki_repo_url or publication_status.target_locator,
                push=push,
                prune_generated=prune_generated,
            )
        except Exception as exc:
            failed_status = self.store.load().registry.get_publication_status(binding_id)
            record = self.store.update(
                lambda current: self._record_status(
                    current,
                    binding_id=binding_id,
                    feed=feed,
                    checked_at=checked_at,
                    status=ProjectionReconcileState.FAILED,
                    last_error=f"projection_publish_failed:{type(exc).__name__}:{exc}",
                    imported=True,
                    publication_status=failed_status,
                    last_publish_attempt_at=publish_started_at,
                ),
            )
            return self._result(feed=feed, publication_status=failed_status, reconcile_status=record, publish_required=True, publish_result=None)
        success_status = self.store.load().registry.get_publication_status(binding_id)
        record = self.store.update(
            lambda current: self._record_status(
                current,
                binding_id=binding_id,
                feed=feed,
                checked_at=checked_at,
                status=ProjectionReconcileState.SUCCESS,
                last_error="",
                imported=True,
                publication_status=success_status,
                last_publish_attempt_at=publish_started_at,
            ),
        )
        return self._result(feed=feed, publication_status=success_status, reconcile_status=record, publish_required=True, publish_result=publish_result)

    def _ensure_feed(
        self,
        plane: AgentInternetControlPlane,
        *,
        feed_id: str,
        bundle_path: Path | str | None,
        poll_interval_seconds: int,
        checked_at: float,
    ) -> SourceAuthorityFeedRecord:
        if bundle_path is not None:
            return plane.bootstrap_steward_public_wiki_feed(
                bundle_path=str(Path(bundle_path).resolve()),
                feed_id=feed_id,
                poll_interval_seconds=poll_interval_seconds,
                now=checked_at,
            )
        feed = plane.registry.get_source_authority_feed(feed_id)
        if feed is None:
            raise ValueError(f"unknown_source_authority_feed:{feed_id}")
        return feed

    def _record_status(
        self,
        plane: AgentInternetControlPlane,
        *,
        binding_id: str,
        feed: SourceAuthorityFeedRecord,
        checked_at: float,
        status: ProjectionReconcileState,
        last_error: str,
        imported: bool,
        publication_status: PublicationStatusRecord | None = None,
        last_publish_attempt_at: float | None = None,
    ) -> ProjectionReconcileStatusRecord:
        existing = plane.registry.get_projection_reconcile_status(binding_id)
        consecutive_failures = (existing.consecutive_failures if existing is not None else 0) + 1 if status == ProjectionReconcileState.FAILED else 0
        labels = dict(existing.labels if existing is not None else {})
        labels.update(
            {
                "source_repo_id": feed.source_repo_id,
                "locator": feed.locator,
                "publication_state": publication_status.status.value if publication_status is not None else "",
                "target_locator": publication_status.target_locator if publication_status is not None else "",
            },
        )
        record = ProjectionReconcileStatusRecord(
            binding_id=binding_id,
            feed_id=feed.feed_id,
            status=status,
            last_checked_at=checked_at,
            last_imported_at=checked_at if imported else (existing.last_imported_at if existing is not None else None),
            last_imported_source_sha=(publication_status.labels.get("authority_bundle_source_sha", "") if publication_status is not None else (existing.last_imported_source_sha if existing is not None else "")),
            last_imported_export_version=(publication_status.labels.get("source_export_version", "") if publication_status is not None else (existing.last_imported_export_version if existing is not None else "")),
            last_publish_attempt_at=last_publish_attempt_at if last_publish_attempt_at is not None else (existing.last_publish_attempt_at if existing is not None else None),
            last_success_at=(publication_status.published_at if publication_status is not None and publication_status.published_at is not None else (existing.last_success_at if existing is not None else None)),
            consecutive_failures=consecutive_failures,
            next_retry_at=_retry_at(checked_at=checked_at, poll_interval_seconds=feed.poll_interval_seconds, consecutive_failures=consecutive_failures),
            last_error=last_error,
            labels=labels,
        )
        plane.upsert_projection_reconcile_status(record)
        return record

    def _result(
        self,
        *,
        feed: SourceAuthorityFeedRecord,
        publication_status: PublicationStatusRecord | None,
        reconcile_status: ProjectionReconcileStatusRecord,
        publish_required: bool,
        publish_result: dict[str, object] | None,
    ) -> dict[str, object]:
        return {
            "feed_id": feed.feed_id,
            "binding_id": reconcile_status.binding_id,
            "locator": feed.locator,
            "publish_required": publish_required,
            "published": publish_result is not None,
            "publication_state": publication_status.status.value if publication_status is not None else "",
            "reconcile_state": reconcile_status.status.value,
            "last_error": reconcile_status.last_error,
            "source_export_version": reconcile_status.last_imported_export_version,
            "source_bundle_sha": reconcile_status.last_imported_source_sha,
            "publish_result": publish_result,
        }