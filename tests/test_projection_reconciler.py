import json
import subprocess
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from agent_internet.control_plane import AGENT_WORLD_AUTHORITY_BUNDLE_FEED_ID, AGENT_WORLD_PUBLIC_WIKI_BINDING_ID, AGENT_WORLD_REPO_ID, STEWARD_AUTHORITY_BUNDLE_FEED_ID, STEWARD_PROTOCOL_REPO_ID, STEWARD_PUBLIC_WIKI_BINDING_ID
from agent_internet.models import AuthorityExportKind, AuthorityFeedTransport, PublicationState
from agent_internet.projection_reconciler import ProjectionReconcileDaemon, ProjectionReconciler
from agent_internet.snapshot import ControlPlaneStateStore


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_git_workspace(tmp_path):
    repo_remote = tmp_path / "agent-internet.git"
    wiki_remote = tmp_path / "steward-protocol.wiki.git"
    repo_root = tmp_path / "agent-internet"
    _git(tmp_path, "init", "--bare", str(repo_remote))
    _git(tmp_path, "init", "--bare", str(wiki_remote))
    _git(tmp_path, "clone", str(repo_remote), str(repo_root))
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test User")
    (repo_root / "README.md").write_text("# agent internet\n")
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-m", "init")
    _git(repo_root, "push", "origin", "HEAD")
    return repo_root, wiki_remote


def _write_steward_authority_bundle(tmp_path, *, version="v1", source_sha="bundle-v1"):
    bundle_dir = tmp_path / "bundle"
    artifacts_dir = bundle_dir / ".authority-exports"
    artifacts_dir.mkdir(parents=True)
    canonical_payload = {"kind": "canonical_surface", "documents": [{"document_id": "constitution", "content": "Steward content"}]}
    relative_path = ".authority-exports/canonical-surface.json"
    (bundle_dir / relative_path).write_text(json.dumps(canonical_payload, indent=2, sort_keys=True) + "\n")
    digest = sha256(json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    bundle = {
        "kind": "source_authority_bundle",
        "generated_at": 171.0,
        "source_sha": source_sha,
        "repo_role": {
            "repo_id": STEWARD_PROTOCOL_REPO_ID,
            "role": "normative_source",
            "owner_boundary": "normative_protocol_surface",
            "exports": [AuthorityExportKind.CANONICAL_SURFACE.value],
            "consumes": [],
            "publication_targets": [STEWARD_PUBLIC_WIKI_BINDING_ID],
            "labels": {"public_surface_owner": "agent-internet"},
        },
        "authority_exports": [
            {
                "export_id": f"{STEWARD_PROTOCOL_REPO_ID}/canonical_surface",
                "repo_id": STEWARD_PROTOCOL_REPO_ID,
                "export_kind": AuthorityExportKind.CANONICAL_SURFACE.value,
                "version": version,
                "artifact_uri": relative_path,
                "generated_at": 170.0,
                "contract_version": 1,
                "content_sha256": digest,
                "labels": {"source_sha": source_sha},
            },
        ],
        "artifact_paths": {AuthorityExportKind.CANONICAL_SURFACE.value: relative_path},
    }
    bundle_path = bundle_dir / ".authority-export-bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    return bundle_path


def _write_agent_world_authority_bundle(tmp_path, *, version="world-v1", source_sha="world-bundle-v1"):
    bundle_dir = tmp_path / "world-bundle"
    artifacts_dir = bundle_dir / ".authority-exports"
    artifacts_dir.mkdir(parents=True)
    canonical_payload = {"kind": "canonical_surface", "documents": [{"document_id": "world_constitution", "content": "Agent World content"}]}
    relative_path = ".authority-exports/canonical-surface.json"
    (bundle_dir / relative_path).write_text(json.dumps(canonical_payload, indent=2, sort_keys=True) + "\n")
    digest = sha256(json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    bundle = {
        "kind": "source_authority_bundle",
        "generated_at": 271.0,
        "source_sha": source_sha,
        "repo_role": {
            "repo_id": AGENT_WORLD_REPO_ID,
            "role": "normative_source",
            "owner_boundary": "world_governance_surface",
            "exports": [AuthorityExportKind.CANONICAL_SURFACE.value],
            "consumes": [],
            "publication_targets": [AGENT_WORLD_PUBLIC_WIKI_BINDING_ID],
            "labels": {"public_surface_owner": "agent-internet"},
        },
        "authority_exports": [
            {
                "export_id": f"{AGENT_WORLD_REPO_ID}/canonical_surface",
                "repo_id": AGENT_WORLD_REPO_ID,
                "export_kind": AuthorityExportKind.CANONICAL_SURFACE.value,
                "version": version,
                "artifact_uri": relative_path,
                "generated_at": 270.0,
                "contract_version": 1,
                "content_sha256": digest,
                "labels": {"source_sha": source_sha},
            },
        ],
        "artifact_paths": {AuthorityExportKind.CANONICAL_SURFACE.value: relative_path},
    }
    bundle_path = bundle_dir / ".authority-export-bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    return bundle_path


def _write_authority_feed_manifest(tmp_path, *, source_repo_id, bundle_path):
    bundle_payload = json.loads(Path(bundle_path).read_text())
    source_sha = str(bundle_payload["source_sha"])
    feed_root = tmp_path / f"{source_repo_id}-feed"
    version_root = feed_root / "bundles" / source_sha
    version_root.mkdir(parents=True)
    persisted_bundle_path = version_root / "source-authority-bundle.json"
    persisted_bundle_path.write_text(Path(bundle_path).read_text())
    artifacts = {}
    for relative_path in bundle_payload["artifact_paths"].values():
        source_artifact = Path(bundle_path).parent / relative_path
        target_artifact = version_root / relative_path
        target_artifact.parent.mkdir(parents=True, exist_ok=True)
        target_artifact.write_text(source_artifact.read_text())
        artifacts[relative_path] = {
            "path": str(Path("bundles") / source_sha / relative_path),
            "sha256": sha256(target_artifact.read_bytes()).hexdigest(),
        }
    manifest = {
        "kind": "source_authority_feed_manifest",
        "contract_version": 1,
        "generated_at": bundle_payload["generated_at"],
        "source_repo_id": source_repo_id,
        "source_sha": source_sha,
        "bundle": {
            "kind": "source_authority_bundle",
            "path": str(Path("bundles") / source_sha / "source-authority-bundle.json"),
            "sha256": sha256(persisted_bundle_path.read_bytes()).hexdigest(),
        },
        "artifacts": artifacts,
    }
    manifest_path = feed_root / "latest-authority-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest_path


def _bind_local_wiki(state_path, wiki_remote):
    store = ControlPlaneStateStore(path=state_path)

    def _update(plane):
        plane.bootstrap_steward_public_wiki_contract(now=100.0)
        binding = plane.registry.get_projection_binding(STEWARD_PUBLIC_WIKI_BINDING_ID)
        plane.upsert_projection_binding(replace(binding, target_locator=str(wiki_remote)))

    store.update(_update)
    return store


def _bind_local_world_wiki(state_path, wiki_remote):
    store = ControlPlaneStateStore(path=state_path)

    def _update(plane):
        plane.bootstrap_agent_world_public_wiki_contract(now=100.0)
        binding = plane.registry.get_projection_binding(AGENT_WORLD_PUBLIC_WIKI_BINDING_ID)
        plane.upsert_projection_binding(replace(binding, target_locator=str(wiki_remote)))

    store.update(_update)
    return store


def test_projection_reconciler_run_once_imports_and_publishes(tmp_path):
    repo_root, wiki_remote = _init_git_workspace(tmp_path)
    state_path = tmp_path / "state.json"
    store = _bind_local_wiki(state_path, wiki_remote)
    bundle_path = _write_steward_authority_bundle(tmp_path)

    result = ProjectionReconciler(root=repo_root, state_path=state_path).run_once(
        bundle_path=bundle_path,
        wiki_repo_url=str(wiki_remote),
        wiki_path=tmp_path / "wiki-checkout",
    )

    feed = store.load().registry.get_source_authority_feed(STEWARD_AUTHORITY_BUNDLE_FEED_ID)
    reconcile_status = store.load().registry.get_projection_reconcile_status(STEWARD_PUBLIC_WIKI_BINDING_ID)
    publication_status = store.load().registry.get_publication_status(STEWARD_PUBLIC_WIKI_BINDING_ID)

    assert result["reconcile_state"] == "success"
    assert result["published"] is True
    assert result["publication_state"] == PublicationState.SUCCESS.value
    assert feed.locator == str(bundle_path.resolve())
    assert reconcile_status.last_imported_source_sha == "bundle-v1"
    assert reconcile_status.last_imported_export_version == "v1"
    assert reconcile_status.last_publish_attempt_at is not None
    assert publication_status.status == PublicationState.SUCCESS


def test_projection_reconciler_run_once_skips_publish_when_projection_current(tmp_path, monkeypatch):
    repo_root, wiki_remote = _init_git_workspace(tmp_path)
    state_path = tmp_path / "state.json"
    _bind_local_wiki(state_path, wiki_remote)
    bundle_path = _write_steward_authority_bundle(tmp_path)
    reconciler = ProjectionReconciler(root=repo_root, state_path=state_path)

    first = reconciler.run_once(bundle_path=bundle_path, wiki_repo_url=str(wiki_remote), wiki_path=tmp_path / "wiki-checkout")

    monkeypatch.setattr("agent_internet.projection_reconciler.publish_agent_internet_wiki", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("should-not-publish")))
    second = reconciler.run_once(wiki_repo_url=str(wiki_remote), wiki_path=tmp_path / "wiki-checkout")

    assert first["published"] is True
    assert second["reconcile_state"] == "success"
    assert second["publish_required"] is False
    assert second["published"] is False


def test_projection_reconciler_infers_agent_world_feed_from_bundle_path(tmp_path):
    repo_root, wiki_remote = _init_git_workspace(tmp_path)
    state_path = tmp_path / "state.json"
    store = _bind_local_world_wiki(state_path, wiki_remote)
    bundle_path = _write_agent_world_authority_bundle(tmp_path)

    result = ProjectionReconciler(root=repo_root, state_path=state_path).run_once(
        bundle_path=bundle_path,
        wiki_repo_url=str(wiki_remote),
        wiki_path=tmp_path / "wiki-checkout-world",
    )

    feed = store.load().registry.get_source_authority_feed(AGENT_WORLD_AUTHORITY_BUNDLE_FEED_ID)
    reconcile_status = store.load().registry.get_projection_reconcile_status(AGENT_WORLD_PUBLIC_WIKI_BINDING_ID)

    assert result["reconcile_state"] == "success"
    assert result["published"] is True
    assert result["binding_id"] == AGENT_WORLD_PUBLIC_WIKI_BINDING_ID
    assert feed is not None
    assert feed.locator == str(bundle_path.resolve())
    assert reconcile_status.last_imported_source_sha == "world-bundle-v1"
    assert reconcile_status.last_imported_export_version == "world-v1"


def test_projection_reconciler_imports_manifest_feed_and_publishes(tmp_path):
    repo_root, wiki_remote = _init_git_workspace(tmp_path)
    state_path = tmp_path / "state.json"
    store = _bind_local_wiki(state_path, wiki_remote)
    bundle_path = _write_steward_authority_bundle(tmp_path, version="v-manifest", source_sha="manifest-bundle-v1")
    manifest_path = _write_authority_feed_manifest(tmp_path, source_repo_id=STEWARD_PROTOCOL_REPO_ID, bundle_path=bundle_path)

    store.update(
        lambda plane: plane.configure_source_authority_feed(
            STEWARD_PROTOCOL_REPO_ID,
            transport=AuthorityFeedTransport.MANIFEST_URL,
            locator=manifest_path.resolve().as_uri(),
            feed_id=STEWARD_AUTHORITY_BUNDLE_FEED_ID,
            now=100.0,
        ),
    )

    result = ProjectionReconciler(root=repo_root, state_path=state_path).run_once(
        feed_id=STEWARD_AUTHORITY_BUNDLE_FEED_ID,
        wiki_repo_url=str(wiki_remote),
        wiki_path=tmp_path / "wiki-checkout-manifest",
    )

    feed = store.load().registry.get_source_authority_feed(STEWARD_AUTHORITY_BUNDLE_FEED_ID)
    publication_status = store.load().registry.get_publication_status(STEWARD_PUBLIC_WIKI_BINDING_ID)

    assert result["reconcile_state"] == "success"
    assert result["publication_state"] == PublicationState.SUCCESS.value
    assert result["manifest_url"] == manifest_path.resolve().as_uri()
    assert result["bundle_sha256"] == feed.labels["bundle_sha256"]
    assert feed.transport == AuthorityFeedTransport.MANIFEST_URL
    assert feed.labels["source_sha"] == "manifest-bundle-v1"
    assert publication_status is not None
    assert publication_status.labels["source_export_version"] == "v-manifest"


def test_projection_reconciler_respects_backoff_and_force(tmp_path):
    repo_root, _wiki_remote = _init_git_workspace(tmp_path)
    state_path = tmp_path / "state.json"
    missing_bundle = tmp_path / "missing-bundle.json"
    store = ControlPlaneStateStore(path=state_path)
    store.update(lambda plane: plane.bootstrap_steward_public_wiki_feed(bundle_path=missing_bundle, now=100.0))
    reconciler = ProjectionReconciler(root=repo_root, state_path=state_path)

    first = reconciler.run_once()
    second = reconciler.run_once()
    forced = reconciler.run_once(force=True)
    status = store.load().registry.get_projection_reconcile_status(STEWARD_PUBLIC_WIKI_BINDING_ID)

    assert first["reconcile_state"] == "failed"
    assert second["reconcile_state"] == "skipped"
    assert second["last_error"] == "backoff_active"
    assert forced["reconcile_state"] == "failed"
    assert status.consecutive_failures == 2


def test_projection_reconciler_skips_when_lock_held(tmp_path, monkeypatch):
    repo_root, _wiki_remote = _init_git_workspace(tmp_path)
    state_path = tmp_path / "state.json"
    bundle_path = _write_steward_authority_bundle(tmp_path)
    store = ControlPlaneStateStore(path=state_path)
    store.update(lambda plane: plane.bootstrap_steward_public_wiki_feed(bundle_path=bundle_path, now=100.0))

    class _BusyLock:
        def __enter__(self):
            raise BlockingIOError()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("agent_internet.projection_reconciler.locked_file", lambda *args, **kwargs: _BusyLock())
    result = ProjectionReconciler(root=repo_root, state_path=state_path).run_once()

    assert result["reconcile_state"] == "skipped"
    assert result["last_error"] == "reconcile_locked"


def test_projection_reconcile_daemon_runs_bounded_cycles(tmp_path, monkeypatch):
    repo_root, wiki_remote = _init_git_workspace(tmp_path)
    state_path = tmp_path / "state.json"
    _bind_local_wiki(state_path, wiki_remote)
    bundle_path = _write_steward_authority_bundle(tmp_path)
    monkeypatch.setattr("agent_internet.projection_reconciler.time.sleep", lambda *_args, **_kwargs: None)

    result = ProjectionReconcileDaemon(root=repo_root, state_path=state_path).run(
        bundle_path=bundle_path,
        wiki_repo_url=str(wiki_remote),
        wiki_path=tmp_path / "wiki-checkout",
        max_cycles=2,
        idle_sleep_seconds=0.0,
    )

    assert result["cycles"] == 2
    assert result["published_count"] == 1
    assert result["failed_count"] == 0
    assert result["runs"][1]["results"][0]["publish_required"] is False