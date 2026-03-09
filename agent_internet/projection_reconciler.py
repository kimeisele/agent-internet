from __future__ import annotations

from dataclasses import asdict
import json
import time
from pathlib import Path

from .authority_contracts import (
    default_public_authority_source_contract,
    get_public_authority_source_contract_by_feed_id,
    get_public_authority_source_contract_by_repo_id,
)
from .control_plane import AgentInternetControlPlane
from .file_locking import locked_file
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


def build_projection_reconcile_snapshot(plane: AgentInternetControlPlane, *, now: float | None = None) -> dict[str, object]:
    checked_at = float(time.time() if now is None else now)
    status_by_binding = {record.binding_id: record for record in plane.registry.list_projection_reconcile_statuses()}
    feeds: list[dict[str, object]] = []
    for feed in plane.registry.list_source_authority_feeds():
        binding_states: list[dict[str, object]] = []
        for binding_id in feed.binding_ids:
            status = status_by_binding.get(binding_id)
            due = bool(feed.enabled and (status is None or status.next_retry_at is None or status.next_retry_at <= checked_at))
            binding_states.append(
                {
                    "binding_id": binding_id,
                    "due": due,
                    "projection_reconcile_status": None if status is None else asdict(status),
                    "publication_status": (
                        None
                        if plane.registry.get_publication_status(binding_id) is None
                        else asdict(plane.registry.get_publication_status(binding_id))
                    ),
                },
            )
        feeds.append(
            {
                **asdict(feed),
                "paused": not feed.enabled,
                "due": any(bool(binding_state["due"]) for binding_state in binding_states),
                "bindings": binding_states,
            },
        )
    return {
        "generated_at": checked_at,
        "source_authority_feeds": feeds,
        "projection_reconcile_statuses": [asdict(record) for record in plane.registry.list_projection_reconcile_statuses()],
    }


class ProjectionReconciler:
    def __init__(self, *, root: Path | str, state_path: Path | str):
        self.root = Path(root).resolve()
        self.state_path = Path(state_path)
        self.store = ControlPlaneStateStore(path=self.state_path)

    def run_once(
        self,
        *,
        bundle_path: Path | str | None = None,
        feed_id: str | None = None,
        poll_interval_seconds: int = 300,
        wiki_repo_url: str | None = None,
        wiki_path: Path | None = None,
        push: bool = False,
        prune_generated: bool = False,
        force: bool = False,
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
        existing = self.store.load().registry.get_projection_reconcile_status(binding_id)
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
                    preserve_failures=True,
                    preserve_next_retry=True,
                ),
            )
            return self._result(feed=feed, publication_status=self.store.load().registry.get_publication_status(binding_id), reconcile_status=record, publish_required=False, publish_result=None)
        if (
            not force
            and existing is not None
            and existing.consecutive_failures > 0
            and existing.next_retry_at is not None
            and existing.next_retry_at > checked_at
        ):
            record = self.store.update(
                lambda plane: self._record_status(
                    plane,
                    binding_id=binding_id,
                    feed=feed,
                    checked_at=checked_at,
                    status=ProjectionReconcileState.SKIPPED,
                    last_error="backoff_active",
                    imported=False,
                    preserve_failures=True,
                    preserve_next_retry=True,
                ),
            )
            return self._result(feed=feed, publication_status=self.store.load().registry.get_publication_status(binding_id), reconcile_status=record, publish_required=False, publish_result=None)
        try:
            with locked_file(self._binding_lock_path(binding_id), exclusive=True, blocking=False):
                return self._run_locked(
                    feed=feed,
                    binding_id=binding_id,
                    checked_at=checked_at,
                    wiki_repo_url=wiki_repo_url,
                    wiki_path=wiki_path,
                    push=push,
                    prune_generated=prune_generated,
                )
        except BlockingIOError:
            record = self.store.update(
                lambda plane: self._record_status(
                    plane,
                    binding_id=binding_id,
                    feed=feed,
                    checked_at=checked_at,
                    status=ProjectionReconcileState.SKIPPED,
                    last_error="reconcile_locked",
                    imported=False,
                    preserve_failures=True,
                    preserve_next_retry=True,
                ),
            )
            return self._result(feed=feed, publication_status=self.store.load().registry.get_publication_status(binding_id), reconcile_status=record, publish_required=False, publish_result=None)

    def run_due_feeds(
        self,
        *,
        bundle_path: Path | str | None = None,
        feed_id: str | None = None,
        poll_interval_seconds: int = 300,
        wiki_repo_url: str | None = None,
        wiki_path: Path | None = None,
        push: bool = False,
        prune_generated: bool = False,
        force: bool = False,
    ) -> dict[str, object]:
        target_feed_ids: list[str]
        if bundle_path is not None:
            target_feed_ids = [self._default_feed_id(bundle_path=bundle_path, feed_id=feed_id)]
        elif feed_id is not None:
            target_feed_ids = [str(feed_id)]
        else:
            target_feed_ids = [record.feed_id for record in self.store.load().registry.list_source_authority_feeds()]
        results: list[dict[str, object]] = []
        for index, current_feed_id in enumerate(target_feed_ids):
            configured_bundle_path = bundle_path if index == 0 else None
            if not force and configured_bundle_path is None:
                plane = self.store.load()
                feed = plane.registry.get_source_authority_feed(current_feed_id)
                if feed is not None:
                    binding_id = _resolve_binding_id(feed)
                    existing = plane.registry.get_projection_reconcile_status(binding_id)
                    if existing is not None and existing.next_retry_at is not None and existing.next_retry_at > time.time():
                        publication_status = plane.registry.get_publication_status(binding_id)
                        record = self.store.update(
                            lambda current: self._record_status(
                                current,
                                binding_id=binding_id,
                                feed=feed,
                                checked_at=float(time.time()),
                                status=ProjectionReconcileState.SKIPPED,
                                last_error=("backoff_active" if existing.consecutive_failures > 0 else "not_due"),
                                imported=False,
                                publication_status=publication_status,
                                preserve_failures=True,
                                preserve_next_retry=True,
                            ),
                        )
                        results.append(
                            self._result(
                                feed=feed,
                                publication_status=publication_status,
                                reconcile_status=record,
                                publish_required=False,
                                publish_result=None,
                            ),
                        )
                        continue
            results.append(
                self.run_once(
                    bundle_path=configured_bundle_path,
                    feed_id=current_feed_id,
                    poll_interval_seconds=poll_interval_seconds,
                    wiki_repo_url=wiki_repo_url,
                    wiki_path=wiki_path,
                    push=push,
                    prune_generated=prune_generated,
                    force=force,
                ),
            )
        return {
            "run_count": len(results),
            "published_count": sum(1 for result in results if bool(result.get("published"))),
            "failed_count": sum(1 for result in results if result.get("reconcile_state") == ProjectionReconcileState.FAILED.value),
            "results": results,
        }

    def _run_locked(
        self,
        *,
        feed: SourceAuthorityFeedRecord,
        binding_id: str,
        checked_at: float,
        wiki_repo_url: str | None,
        wiki_path: Path | None,
        push: bool,
        prune_generated: bool,
    ) -> dict[str, object]:
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

    def _binding_lock_path(self, binding_id: str) -> Path:
        safe_binding_id = binding_id.replace(":", "_").replace("/", "_")
        return self.state_path.parent / f".projection-reconcile-{safe_binding_id}"

    def _ensure_feed(
        self,
        plane: AgentInternetControlPlane,
        *,
        feed_id: str | None,
        bundle_path: Path | str | None,
        poll_interval_seconds: int,
        checked_at: float,
    ) -> SourceAuthorityFeedRecord:
        if bundle_path is not None:
            resolved_bundle_path = str(Path(bundle_path).resolve())
            contract = self._resolve_contract(bundle_path=resolved_bundle_path, feed_id=feed_id)
            return plane.bootstrap_public_wiki_feed_for_repo_id(
                contract.source_repo_id,
                bundle_path=resolved_bundle_path,
                feed_id=contract.feed_id,
                poll_interval_seconds=poll_interval_seconds,
                now=checked_at,
            )
        resolved_feed_id = str(feed_id or default_public_authority_source_contract().feed_id)
        feed = plane.registry.get_source_authority_feed(resolved_feed_id)
        if feed is None:
            raise ValueError(f"unknown_source_authority_feed:{resolved_feed_id}")
        return feed

    def _default_feed_id(self, *, bundle_path: Path | str, feed_id: str | None) -> str:
        return self._resolve_contract(bundle_path=bundle_path, feed_id=feed_id).feed_id

    def _resolve_contract(self, *, bundle_path: Path | str, feed_id: str | None):
        if feed_id:
            contract = get_public_authority_source_contract_by_feed_id(str(feed_id))
            if contract is None:
                raise ValueError(f"unknown_public_authority_feed:{feed_id}")
            return contract
        try:
            bundle = json.loads(Path(bundle_path).resolve().read_text())
        except Exception:
            return default_public_authority_source_contract()
        repo_role = bundle.get("repo_role") if isinstance(bundle, dict) else None
        repo_id = str(repo_role.get("repo_id", "")) if isinstance(repo_role, dict) else ""
        return get_public_authority_source_contract_by_repo_id(repo_id) or default_public_authority_source_contract()

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
        preserve_failures: bool = False,
        preserve_next_retry: bool = False,
    ) -> ProjectionReconcileStatusRecord:
        existing = plane.registry.get_projection_reconcile_status(binding_id)
        if status == ProjectionReconcileState.FAILED:
            consecutive_failures = (existing.consecutive_failures if existing is not None else 0) + 1
        elif preserve_failures and existing is not None:
            consecutive_failures = existing.consecutive_failures
        else:
            consecutive_failures = 0
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
            next_retry_at=(
                existing.next_retry_at
                if preserve_next_retry and existing is not None
                else _retry_at(checked_at=checked_at, poll_interval_seconds=feed.poll_interval_seconds, consecutive_failures=consecutive_failures)
            ),
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
            "paused": not feed.enabled,
            "publication_state": publication_status.status.value if publication_status is not None else "",
            "reconcile_state": reconcile_status.status.value,
            "last_error": reconcile_status.last_error,
            "source_export_version": reconcile_status.last_imported_export_version,
            "source_bundle_sha": reconcile_status.last_imported_source_sha,
            "publish_result": publish_result,
        }


class ProjectionReconcileDaemon:
    def __init__(self, *, root: Path | str, state_path: Path | str):
        self.reconciler = ProjectionReconciler(root=root, state_path=state_path)

    def run(
        self,
        *,
        bundle_path: Path | str | None = None,
        feed_id: str | None = None,
        poll_interval_seconds: int = 300,
        wiki_repo_url: str | None = None,
        wiki_path: Path | None = None,
        push: bool = False,
        prune_generated: bool = False,
        force: bool = False,
        max_cycles: int | None = None,
        idle_sleep_seconds: float = 1.0,
    ) -> dict[str, object]:
        cycles = 0
        history: list[dict[str, object]] = []
        while max_cycles is None or cycles < max_cycles:
            cycle = self.reconciler.run_due_feeds(
                bundle_path=(bundle_path if cycles == 0 else None),
                feed_id=feed_id,
                poll_interval_seconds=poll_interval_seconds,
                wiki_repo_url=wiki_repo_url,
                wiki_path=wiki_path,
                push=push,
                prune_generated=prune_generated,
                force=force,
            )
            history.append(cycle)
            cycles += 1
            if max_cycles is None or cycles < max_cycles:
                time.sleep(max(float(idle_sleep_seconds), 0.0))
        return {
            "cycles": cycles,
            "published_count": sum(int(cycle["published_count"]) for cycle in history),
            "failed_count": sum(int(cycle["failed_count"]) for cycle in history),
            "runs": history,
        }