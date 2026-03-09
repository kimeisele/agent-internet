import json
import subprocess
from dataclasses import replace
from hashlib import sha256

from agent_internet.control_plane import STEWARD_AUTHORITY_BUNDLE_FEED_ID, STEWARD_PROTOCOL_REPO_ID, STEWARD_PUBLIC_WIKI_BINDING_ID
from agent_internet.models import AuthorityExportKind, PublicationState
from agent_internet.projection_reconciler import ProjectionReconciler
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


def _bind_local_wiki(state_path, wiki_remote):
    store = ControlPlaneStateStore(path=state_path)

    def _update(plane):
        plane.bootstrap_steward_public_wiki_contract(now=100.0)
        binding = plane.registry.get_projection_binding(STEWARD_PUBLIC_WIKI_BINDING_ID)
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