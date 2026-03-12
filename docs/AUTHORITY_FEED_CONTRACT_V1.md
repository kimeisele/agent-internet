## Authority Feed Contract v1

Each source repo publishes a stable `latest-authority-manifest.json` plus immutable bundle files under `bundles/<source_sha>/...`.

### Manifest shape

```json
{
  "kind": "source_authority_feed_manifest",
  "contract_version": 1,
  "generated_at": 0.0,
  "source_repo_id": "steward-protocol",
  "source_sha": "abc123",
  "bundle": {"kind": "source_authority_bundle", "path": "bundles/abc123/source-authority-bundle.json", "sha256": "..."},
  "artifacts": {".authority-exports/canonical-surface.json": {"path": "bundles/abc123/.authority-exports/canonical-surface.json", "sha256": "..."}}
}
```

### Verification rules

- `kind` must equal `source_authority_feed_manifest`
- `contract_version` must be supported by `agent-internet`
- `source_repo_id` must match the configured feed source repo
- `bundle.sha256` must match the downloaded bundle bytes
- each artifact `sha256` must match the downloaded artifact bytes
- downloaded bundle `repo_role.repo_id` must match `source_repo_id`
- downloaded bundle `source_sha` must match manifest `source_sha`

### Consumer flow

1. fetch manifest URL
2. resolve bundle/artifact paths relative to the manifest URL
3. download changed bundle/artifact files into local cache
4. verify digests and repo identity
5. import the cached bundle into control-plane state
6. publish wiki projection from imported state

### Recommended `surface-metadata` alignment

When a source repo publishes `.authority-exports/surface-metadata.json`, it should
explicitly identify whether the exported feed/projection is part of the canonical
public federation surface.

Recommended shape:

```json
{
  "kind": "surface_metadata",
  "public_surface": {"repo_label": "Steward"},
  "federation_surface": {
    "surface_role": "canonical_public_source_authority",
    "canonical_for_public_federation": true,
    "publication_model": "github_authority_feed_plus_projected_wiki",
    "public_channels": ["authority_feed_manifest", "canonical_surface", "public_summary_registry"],
    "consumer_guidance": "Treat this authority feed and its projected wiki/agent-web pages as public federation truth; authenticated control planes are companion operator surfaces."
  }
}
```

This keeps public authority publication distinct from any authenticated operator
or bridge API that may exist alongside it.

### Publication recording

`agent-internet` records, per synced feed:

- `manifest_url`
- `source_sha`
- `bundle_sha256`
- cached `bundle_path`

Projection reconcile status also exposes:

- `manifest_url`
- `bundle_sha256`
- imported export version / source sha

### Ownership split

- `agent-world` owns its authority feed publication
- `steward-protocol` owns its authority feed publication
- `agent-internet` only fetches, verifies, imports, and projects those feeds