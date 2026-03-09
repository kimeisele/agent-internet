import json
import subprocess
from hashlib import sha256

import pytest

from agent_internet.control_plane import STEWARD_PROTOCOL_REPO_ID, STEWARD_PUBLIC_WIKI_BINDING_ID
from agent_internet.models import AuthorityExportKind, AuthorityExportRecord, PublicationState
from agent_internet.publication_status import sanitize_remote_url
from agent_internet.publisher import build_agent_internet_peer_descriptor, build_agent_internet_wiki, probe_wiki_remote, publish_agent_internet_wiki
from agent_internet.snapshot import ControlPlaneStateStore


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_git_workspace(tmp_path):
    remote_root = tmp_path / "remotes"
    repo_remote = remote_root / "agent-internet.git"
    wiki_remote = remote_root / "agent-internet.wiki.git"
    work_root = tmp_path / "work"
    repo_remote.parent.mkdir(parents=True)
    _git(tmp_path, "init", "--bare", str(repo_remote))
    _git(tmp_path, "init", "--bare", str(wiki_remote))
    _git(tmp_path, "clone", str(repo_remote), str(work_root))
    _git(work_root, "config", "user.email", "test@example.com")
    _git(work_root, "config", "user.name", "Test User")
    (work_root / "README.md").write_text("# Agent Internet\n")
    _git(work_root, "add", ".")
    _git(work_root, "commit", "-m", "init")
    _git(work_root, "push", "origin", "HEAD")
    _git(work_root, "remote", "set-url", "origin", "git@github.com:org/agent-internet.git")
    return work_root, wiki_remote


def _seed_steward_public_wiki_binding(state_path, *, wiki_repo_url: str, version: str = "v1", source_sha: str = "bundle-sha"):
    artifact_payload = {"kind": "canonical_surface", "documents": [{"document_id": "constitution"}]}
    digest = sha256(json.dumps(artifact_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    store = ControlPlaneStateStore(path=state_path)

    def _update(plane):
        plane.bootstrap_steward_public_wiki_contract(now=100.0)
        binding = plane.registry.get_projection_binding(STEWARD_PUBLIC_WIKI_BINDING_ID)
        plane.registry.upsert_projection_binding(
            binding.__class__(
                binding_id=binding.binding_id,
                source_repo_id=binding.source_repo_id,
                required_export_kind=binding.required_export_kind,
                operator_repo_id=binding.operator_repo_id,
                target_kind=binding.target_kind,
                target_locator=str(wiki_repo_url),
                projection_mode=binding.projection_mode,
                failure_policy=binding.failure_policy,
                freshness_sla_seconds=binding.freshness_sla_seconds,
                labels=dict(binding.labels),
            ),
        )
        plane.upsert_authority_export(
            AuthorityExportRecord(
                export_id=f"{STEWARD_PROTOCOL_REPO_ID}/canonical_surface",
                repo_id=STEWARD_PROTOCOL_REPO_ID,
                export_kind=AuthorityExportKind.CANONICAL_SURFACE,
                version=version,
                artifact_uri=".authority-exports/canonical-surface.json",
                generated_at=101.0,
                content_sha256=digest,
                labels={"source_sha": source_sha},
            ),
        )

    store.update(_update)
    return store


def _ingest_new_steward_source(store: ControlPlaneStateStore, *, version: str, source_sha: str, document_id: str = "constitution-v2"):
    artifact_payload = {"kind": "canonical_surface", "documents": [{"document_id": document_id}]}
    digest = sha256(json.dumps(artifact_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    bundle = {
        "kind": "source_authority_bundle",
        "generated_at": 202.0,
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
                "artifact_uri": ".authority-exports/canonical-surface.json",
                "generated_at": 201.0,
                "contract_version": 1,
                "content_sha256": digest,
                "labels": {"source_sha": source_sha},
            },
        ],
    }
    store.update(lambda plane: plane.ingest_authority_bundle(bundle, artifacts={".authority-exports/canonical-surface.json": artifact_payload}, now=203.0))


def test_build_agent_internet_peer_descriptor_detects_git_metadata(tmp_path):
    work_root, _wiki_remote = _init_git_workspace(tmp_path)
    payload = build_agent_internet_peer_descriptor(work_root)
    assert payload["identity"]["repo"] == "org/agent-internet"
    assert payload["git_federation"]["wiki_repo_url"] == "git@github.com:org/agent-internet.wiki.git"


def test_sanitize_remote_url_removes_embedded_credentials():
    sanitized = sanitize_remote_url("https://x-access-token:secret-token@github.com/org/agent-internet.wiki.git")

    assert sanitized == "https://github.com/org/agent-internet.wiki.git"


def test_build_agent_internet_wiki_materializes_pages(tmp_path):
    work_root, _wiki_remote = _init_git_workspace(tmp_path)
    built = build_agent_internet_wiki(root=work_root, output_dir=tmp_path / "wiki-build", state_path=tmp_path / "state.json")
    assert any(path.name == "Agent-Web.md" for path in built)
    assert any(path.name == "Assistant-Surface.md" for path in built)
    assert any(path.name == "Node-Health.md" for path in built)
    assert any(path.name == "Publication-Status.md" for path in built)
    assert any(path.name == "Federation-Status.md" for path in built)
    assert any(path.name == "Surface-Integrity.md" for path in built)
    assert any(path.name == "Repo-Quality.md" for path in built)
    assert any(path.name == "_Sidebar.md" for path in built)
    assert "# Repo Graph Capabilities" in (tmp_path / "wiki-build" / "Repo-Graph-Capabilities.md").read_text()
    assert "No assistant snapshot is published yet for this city." in (tmp_path / "wiki-build" / "Assistant-Surface.md").read_text()
    assert "No services are published yet." in (tmp_path / "wiki-build" / "Services.md").read_text()
    assert "# Node Health" in (tmp_path / "wiki-build" / "Node-Health.md").read_text()
    assert "# Publication Status" in (tmp_path / "wiki-build" / "Publication-Status.md").read_text()
    assert "Status: `build_preview`" in (tmp_path / "wiki-build" / "Publication-Status.md").read_text()
    assert "# Federation Status" in (tmp_path / "wiki-build" / "Federation-Status.md").read_text()
    assert "Missing Declared Documents: `0`" in (tmp_path / "wiki-build" / "Surface-Integrity.md").read_text()
    assert "# Repo Quality" in (tmp_path / "wiki-build" / "Repo-Quality.md").read_text()
    assert "Tracked Files: `" in (tmp_path / "wiki-build" / "Repo-Quality.md").read_text()
    assert "Has tests: `" in (tmp_path / "wiki-build" / "Repo-Quality.md").read_text()


def test_publish_agent_internet_wiki_commits_without_push(tmp_path):
    work_root, wiki_remote = _init_git_workspace(tmp_path)
    result = publish_agent_internet_wiki(
        root=work_root,
        state_path=tmp_path / "state.json",
        wiki_path=tmp_path / "wiki-checkout",
        wiki_repo_url=str(wiki_remote),
        push=False,
    )
    assert result["changed"] is True
    assert result["pushed"] is False
    assert result["pruned"] == 0
    assert result["published_at_utc"].endswith("Z")
    log = _git(tmp_path / "wiki-checkout", "log", "-1", "--pretty=%s").stdout.strip()
    assert log.startswith("agent-web: publish surfaces from ")
    assert (tmp_path / "wiki-checkout" / ".wiki-generated-inventory.json").exists()
    assert (tmp_path / "wiki-checkout" / ".agent-web-publication.json").exists()
    publication_page = (tmp_path / "wiki-checkout" / "Publication-Status.md").read_text()
    assert "Status: `published`" in publication_page
    assert "x-access-token" not in publication_page
    publication_payload = json.loads((tmp_path / "wiki-checkout" / ".agent-web-publication.json").read_text())
    assert "x-access-token" not in publication_payload["wiki_repo_url"]
    assert publication_payload["wiki_repo_url"] == str(wiki_remote)


def test_publish_agent_internet_wiki_records_success_for_bound_projection(tmp_path):
    work_root, wiki_remote = _init_git_workspace(tmp_path)
    state_path = tmp_path / "state.json"
    store = _seed_steward_public_wiki_binding(state_path, wiki_repo_url=str(wiki_remote), version="v-success", source_sha="bundle-success")

    result = publish_agent_internet_wiki(
        root=work_root,
        state_path=state_path,
        wiki_path=tmp_path / "wiki-checkout",
        wiki_repo_url=str(wiki_remote),
        push=False,
    )

    status = store.load().registry.get_publication_status(STEWARD_PUBLIC_WIKI_BINDING_ID)

    assert result["binding_id"] == STEWARD_PUBLIC_WIKI_BINDING_ID
    assert result["publication_state"] == PublicationState.SUCCESS.value
    assert status.status == PublicationState.SUCCESS
    assert status.projected_from_export_id == f"{STEWARD_PROTOCOL_REPO_ID}/canonical_surface"
    assert status.published_at is not None
    assert status.stale is False
    assert status.failure_reason == ""
    assert status.labels["source_export_version"] == "v-success"
    assert status.labels["operator_source_sha"] == result["source_sha"]


def test_publish_agent_internet_wiki_records_failed_projection_attempt(tmp_path, monkeypatch):
    work_root, wiki_remote = _init_git_workspace(tmp_path)
    state_path = tmp_path / "state.json"
    store = _seed_steward_public_wiki_binding(state_path, wiki_repo_url=str(wiki_remote), version="v-fail", source_sha="bundle-fail")

    def boom(*args, **kwargs):
        raise RuntimeError("simulated-publish-failure")

    monkeypatch.setattr("agent_internet.publisher._git_commit_all", boom)

    with pytest.raises(RuntimeError, match="simulated-publish-failure"):
        publish_agent_internet_wiki(
            root=work_root,
            state_path=state_path,
            wiki_path=tmp_path / "wiki-checkout",
            wiki_repo_url=str(wiki_remote),
            push=False,
        )

    status = store.load().registry.get_publication_status(STEWARD_PUBLIC_WIKI_BINDING_ID)

    assert status.status == PublicationState.FAILED
    assert status.projected_from_export_id == f"{STEWARD_PROTOCOL_REPO_ID}/canonical_surface"
    assert status.failure_reason.startswith("projection_publish_failed:RuntimeError:simulated-publish-failure")
    assert status.checked_at is not None


def test_publish_agent_internet_wiki_success_becomes_stale_after_new_source_import(tmp_path):
    work_root, wiki_remote = _init_git_workspace(tmp_path)
    state_path = tmp_path / "state.json"
    store = _seed_steward_public_wiki_binding(state_path, wiki_repo_url=str(wiki_remote), version="v1", source_sha="bundle-v1")

    publish_agent_internet_wiki(
        root=work_root,
        state_path=state_path,
        wiki_path=tmp_path / "wiki-checkout",
        wiki_repo_url=str(wiki_remote),
        push=False,
    )
    _ingest_new_steward_source(store, version="v2", source_sha="bundle-v2")

    status = store.load().registry.get_publication_status(STEWARD_PUBLIC_WIKI_BINDING_ID)

    assert status.status == PublicationState.STALE
    assert status.failure_reason == "projection_out_of_date"
    assert status.labels["source_export_version"] == "v2"
    assert status.labels["authority_bundle_source_sha"] == "bundle-v2"


def test_publish_agent_internet_wiki_blocks_bound_projection_without_imported_source(tmp_path):
    work_root, wiki_remote = _init_git_workspace(tmp_path)
    state_path = tmp_path / "state.json"
    store = ControlPlaneStateStore(path=state_path)

    def _update(plane):
        plane.bootstrap_steward_public_wiki_contract(now=100.0)
        binding = plane.registry.get_projection_binding(STEWARD_PUBLIC_WIKI_BINDING_ID)
        plane.registry.upsert_projection_binding(
            binding.__class__(
                binding_id=binding.binding_id,
                source_repo_id=binding.source_repo_id,
                required_export_kind=binding.required_export_kind,
                operator_repo_id=binding.operator_repo_id,
                target_kind=binding.target_kind,
                target_locator=str(wiki_remote),
                projection_mode=binding.projection_mode,
                failure_policy=binding.failure_policy,
                freshness_sla_seconds=binding.freshness_sla_seconds,
                labels=dict(binding.labels),
            ),
        )

    store.update(_update)

    with pytest.raises(RuntimeError, match="missing_authority_export:steward-protocol:canonical_surface"):
        publish_agent_internet_wiki(
            root=work_root,
            state_path=state_path,
            wiki_path=tmp_path / "wiki-checkout",
            wiki_repo_url=str(wiki_remote),
            push=False,
        )

    status = store.load().registry.get_publication_status(STEWARD_PUBLIC_WIKI_BINDING_ID)
    assert status.status == PublicationState.BLOCKED


def test_publish_agent_internet_wiki_prunes_only_stale_generated_pages(tmp_path):
    work_root, wiki_remote = _init_git_workspace(tmp_path)
    checkout = tmp_path / "wiki-checkout"
    first = publish_agent_internet_wiki(
        root=work_root,
        state_path=tmp_path / "state.json",
        wiki_path=checkout,
        wiki_repo_url=str(wiki_remote),
        push=False,
        prune_generated=True,
    )

    assert first["pruned"] == 0
    stale_generated = checkout / "Semantic-Contracts.md"
    assert stale_generated.exists()
    (checkout / "Welcome-to-the-Agent-Internet.md").write_text("# Manual page\n")
    inventory = checkout / ".wiki-generated-inventory.json"
    payload = json.loads(inventory.read_text())
    payload["files"] = [path for path in payload["files"] if path != "Semantic-Contracts.md"]
    inventory.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-m", "mutate inventory without ownership")

    result = publish_agent_internet_wiki(
        root=work_root,
        state_path=tmp_path / "state.json",
        wiki_path=checkout,
        wiki_repo_url=str(wiki_remote),
        push=False,
        prune_generated=True,
    )

    assert result["pruned"] == 0
    assert stale_generated.exists()
    assert (checkout / "Welcome-to-the-Agent-Internet.md").exists()


def test_publish_agent_internet_wiki_prunes_stale_generated_from_previous_inventory(tmp_path):
    work_root, wiki_remote = _init_git_workspace(tmp_path)
    checkout = tmp_path / "wiki-checkout"
    publish_agent_internet_wiki(
        root=work_root,
        state_path=tmp_path / "state.json",
        wiki_path=checkout,
        wiki_repo_url=str(wiki_remote),
        push=False,
        prune_generated=True,
    )

    stale_generated = checkout / "Legacy-Generated.md"
    stale_generated.write_text("# Legacy\n")
    inventory = checkout / ".wiki-generated-inventory.json"
    payload = json.loads(inventory.read_text())
    payload["files"].append("Legacy-Generated.md")
    inventory.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (checkout / "Welcome-to-the-Agent-Internet.md").write_text("# Manual page\n")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-m", "add stale generated and manual pages")

    result = publish_agent_internet_wiki(
        root=work_root,
        state_path=tmp_path / "state.json",
        wiki_path=checkout,
        wiki_repo_url=str(wiki_remote),
        push=False,
        prune_generated=True,
    )

    assert result["pruned"] == 1
    assert result["pruned_paths"] == ["Legacy-Generated.md"]
    assert not stale_generated.exists()
    assert (checkout / "Welcome-to-the-Agent-Internet.md").exists()


def test_probe_wiki_remote_reports_missing_remote(tmp_path):
    missing = probe_wiki_remote(str(tmp_path / "missing.wiki.git"))

    assert missing["reachable"] is False


def test_probe_wiki_remote_reports_existing_remote(tmp_path):
    _work_root, wiki_remote = _init_git_workspace(tmp_path)

    payload = probe_wiki_remote(str(wiki_remote))

    assert payload["reachable"] is True