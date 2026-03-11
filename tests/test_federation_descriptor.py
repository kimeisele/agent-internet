import json
from hashlib import sha256
from pathlib import Path

from agent_internet.authority_contracts import build_authority_projection_documents
from agent_internet.cli import main
from agent_internet.control_plane import AgentInternetControlPlane, default_public_authority_binding_id, default_public_authority_feed_id
from agent_internet.federation_descriptor import FederationProjectionIntent, load_federation_descriptor, load_federation_descriptor_seed
from agent_internet.github_topic_discovery import GitHubTopicDiscoveryResult
from agent_internet.models import AuthorityExportKind, PublicationState, RepoRole
from agent_internet.snapshot import ControlPlaneStateStore, snapshot_control_plane


def _write_authority_bundle(tmp_path, *, repo_id="future-federation-repo", version="future-v1", source_sha="future-sha"):
    bundle_dir = tmp_path / repo_id
    artifacts_dir = bundle_dir / ".authority-exports"
    artifacts_dir.mkdir(parents=True)
    canonical_payload = {"kind": "canonical_surface", "documents": [{"document_id": "charter", "title": "Future Charter", "wiki_name": "Future-Charter"}]}
    summary_payload = {"kind": "public_summary_registry", "records": [{"id": "charter", "public_summary": "Future summary"}]}
    source_surface_payload = {"kind": "source_surface_registry", "pages": [{"id": "charter", "wiki_name": "Future-Charter", "include_in_sidebar": True}]}
    surface_metadata_payload = {"kind": "surface_metadata", "public_surface": {"repo_label": "Future Federation"}, "surface_registry": {"kind": "wiki_surface_registry", "page_count": 1}}
    artifacts = {
        ".authority-exports/canonical-surface.json": canonical_payload,
        ".authority-exports/public-summary-registry.json": summary_payload,
        ".authority-exports/source-surface-registry.json": source_surface_payload,
        ".authority-exports/surface-metadata.json": surface_metadata_payload,
    }
    for relative_path, payload in artifacts.items():
        target = bundle_dir / relative_path
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    authority_exports = []
    for export_kind, relative_path in {
        AuthorityExportKind.CANONICAL_SURFACE.value: ".authority-exports/canonical-surface.json",
        AuthorityExportKind.PUBLIC_SUMMARY_REGISTRY.value: ".authority-exports/public-summary-registry.json",
        AuthorityExportKind.SOURCE_SURFACE_REGISTRY.value: ".authority-exports/source-surface-registry.json",
        AuthorityExportKind.SURFACE_METADATA.value: ".authority-exports/surface-metadata.json",
    }.items():
        payload = artifacts[relative_path]
        authority_exports.append(
            {
                "export_id": f"{repo_id}/{export_kind}",
                "repo_id": repo_id,
                "export_kind": export_kind,
                "version": version,
                "artifact_uri": relative_path,
                "generated_at": 170.0,
                "contract_version": 1,
                "content_sha256": sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
                "labels": {"source_sha": source_sha},
            },
        )
    bundle = {
        "kind": "source_authority_bundle",
        "contract_version": 1,
        "generated_at": 171.0,
        "source_sha": source_sha,
        "repo_role": {
            "repo_id": repo_id,
            "role": RepoRole.NORMATIVE_SOURCE.value,
            "owner_boundary": "future_federation_surface",
            "exports": [record["export_kind"] for record in authority_exports],
            "consumes": [],
            "publication_targets": [default_public_authority_binding_id(repo_id)],
            "labels": {"display_name": "Future Federation"},
        },
        "authority_exports": authority_exports,
        "artifact_paths": {record["export_kind"]: record["artifact_uri"] for record in authority_exports},
    }
    bundle_path = bundle_dir / ".authority-export-bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    return bundle_path


def _write_authority_feed_manifest(tmp_path, *, repo_id, bundle_path):
    bundle_payload = json.loads(Path(bundle_path).read_text())
    source_sha = str(bundle_payload["source_sha"])
    feed_root = tmp_path / f"{repo_id}-feed"
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
        artifacts[relative_path] = {"path": str(Path("bundles") / source_sha / relative_path), "sha256": sha256(target_artifact.read_bytes()).hexdigest()}
    manifest = {
        "kind": "source_authority_feed_manifest",
        "contract_version": 1,
        "generated_at": bundle_payload["generated_at"],
        "source_repo_id": repo_id,
        "source_sha": source_sha,
        "bundle": {"kind": "source_authority_bundle", "path": str(Path("bundles") / source_sha / "source-authority-bundle.json"), "sha256": sha256(persisted_bundle_path.read_bytes()).hexdigest()},
        "artifacts": artifacts,
    }
    manifest_path = feed_root / "latest-authority-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest_path


def _write_descriptor(tmp_path, *, repo_id, manifest_path):
    descriptor_path = tmp_path / ".well-known" / f"{repo_id}.json"
    descriptor_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor_path.write_text(json.dumps({"kind": "agent_federation_descriptor", "version": 1, "repo_id": repo_id, "display_name": "Future Federation", "authority_feed_manifest_url": manifest_path.resolve().as_uri(), "projection_intents": [FederationProjectionIntent.PUBLIC_AUTHORITY_PAGE.value], "status": "active", "owner_boundary": "future_federation_surface"}, indent=2) + "\n")
    return descriptor_path


def test_load_federation_descriptor_seed_expands_environment_variables(tmp_path, monkeypatch):
    descriptor_url = "https://example.com/.well-known/agent-federation.json"
    seed_path = tmp_path / "descriptor-seed.json"
    seed_path.write_text(json.dumps({"descriptor_urls": ["${FUTURE_DESCRIPTOR_URL}"]}) + "\n")
    monkeypatch.setenv("FUTURE_DESCRIPTOR_URL", descriptor_url)

    assert load_federation_descriptor_seed(seed_path) == (descriptor_url,)


def test_register_federation_descriptor_creates_binding_and_feed(tmp_path):
    repo_id = "future-federation-repo"
    bundle_path = _write_authority_bundle(tmp_path, repo_id=repo_id)
    manifest_path = _write_authority_feed_manifest(tmp_path, repo_id=repo_id, bundle_path=bundle_path)
    descriptor, descriptor_url = load_federation_descriptor(_write_descriptor(tmp_path, repo_id=repo_id, manifest_path=manifest_path))
    plane = AgentInternetControlPlane()

    result = plane.register_federation_descriptor(descriptor, descriptor_url=descriptor_url, now=100.0)

    assert result["binding"].binding_id == default_public_authority_binding_id(repo_id)
    assert result["feed"].feed_id == default_public_authority_feed_id(repo_id)
    assert result["feed"].binding_ids == (default_public_authority_binding_id(repo_id),)
    assert result["binding"].labels["authority_projection"] == FederationProjectionIntent.PUBLIC_AUTHORITY_PAGE.value


def test_cli_sync_federation_descriptors_registers_and_imports_manifest_feed(tmp_path, capsys):
    repo_id = "future-federation-repo"
    state_path = tmp_path / "state.json"
    bundle_path = _write_authority_bundle(tmp_path, repo_id=repo_id, version="future-v2", source_sha="future-sync")
    manifest_path = _write_authority_feed_manifest(tmp_path, repo_id=repo_id, bundle_path=bundle_path)
    descriptor_path = _write_descriptor(tmp_path, repo_id=repo_id, manifest_path=manifest_path)
    seed_path = tmp_path / "descriptor-seed.json"
    seed_path.write_text(json.dumps({"descriptor_urls": [str(descriptor_path)]}) + "\n")

    assert main(["sync-federation-descriptors", "--state-path", str(state_path), "--seed-path", str(seed_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    plane = ControlPlaneStateStore(path=state_path).load()
    status = plane.registry.get_publication_status(default_public_authority_binding_id(repo_id))

    assert payload["registered"][0]["repo_id"] == repo_id
    assert payload["synced"][0]["source_sha"] == "future-sync"
    assert status is not None
    assert status.status == PublicationState.STALE
    assert status.labels["source_export_version"] == "future-v2"


def test_cli_sync_federation_descriptors_accepts_github_topic_results(tmp_path, capsys, monkeypatch):
    repo_id = "future-federation-repo"
    state_path = tmp_path / "state.json"
    bundle_path = _write_authority_bundle(tmp_path, repo_id=repo_id, version="future-v2", source_sha="future-topic")
    manifest_path = _write_authority_feed_manifest(tmp_path, repo_id=repo_id, bundle_path=bundle_path)
    descriptor_path = _write_descriptor(tmp_path, repo_id=repo_id, manifest_path=manifest_path)
    monkeypatch.setattr(
        "agent_internet.cli.discover_federation_descriptors_by_github_topic",
        lambda **_: (
            GitHubTopicDiscoveryResult(
                repository_full_name="kimeisele/future-federation-repo",
                default_branch="main",
                descriptor_url=descriptor_path.as_uri(),
            ),
        ),
    )

    assert main(["sync-federation-descriptors", "--state-path", str(state_path), "--github-topic", "agent-federation-node"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["registered"][0]["repo_id"] == repo_id
    assert payload["synced"][0]["source_sha"] == "future-topic"


def test_dynamic_authority_projection_documents_include_registered_descriptor_repo(tmp_path):
    repo_id = "future-federation-repo"
    bundle_path = _write_authority_bundle(tmp_path, repo_id=repo_id, version="future-v3", source_sha="future-docs")
    manifest_path = _write_authority_feed_manifest(tmp_path, repo_id=repo_id, bundle_path=bundle_path)
    descriptor, descriptor_url = load_federation_descriptor(_write_descriptor(tmp_path, repo_id=repo_id, manifest_path=manifest_path))
    plane = AgentInternetControlPlane()

    plane.register_federation_descriptor(descriptor, descriptor_url=descriptor_url, now=100.0)
    plane.ingest_authority_bundle_path(bundle_path, now=110.0)
    documents = build_authority_projection_documents(snapshot_control_plane(plane))

    assert any(document["source_repo_id"] == repo_id and document["render_mode"] == "overview" and document["title"] == "Future Federation Authority" for document in documents)
    assert any(document["source_repo_id"] == repo_id and document["render_mode"] == "canonical_document" and document["href"] == "Future-Charter.md" for document in documents)