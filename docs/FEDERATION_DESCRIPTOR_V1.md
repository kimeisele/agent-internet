## Federation Descriptor v1

- Well-known file: `.well-known/agent-federation.json`
- Purpose: let `agent-internet` auto-register a source repo's authority feed and public projection intent without downstream code edits

Minimal descriptor:

```json
{
  "kind": "agent_federation_descriptor",
  "version": 1,
  "repo_id": "my-repo",
  "display_name": "My Repo",
  "authority_feed_manifest_url": "https://raw.githubusercontent.com/org/my-repo/authority-feed/latest-authority-manifest.json",
  "projection_intents": ["public_authority_page"],
  "status": "active",
  "owner_boundary": "my_repo_surface"
}
```

Supported MVP intents:

- `public_authority_page`
- `none`

Supported MVP status values:

- `active`
- `deprecated`
- `revoked`

## How agent-internet uses it

When `agent-internet` loads the descriptor it will:

1. register a `manifest_url` source authority feed
2. create a public-wiki projection binding when `public_authority_page` is declared
3. sync/import the feed using the declared manifest URL
4. render authority pages dynamically from control-plane state

## Seed-list format

`data/federation/authority-descriptor-seeds.json` can be either:

- a JSON object with `descriptor_urls`
- or a JSON array of descriptor URLs

## Topic discovery

For zero-touch discovery, add the GitHub topic:

- `agent-federation-node`

Then `agent-internet` can discover descriptors with:

```bash
python -m agent_internet.cli sync-federation-descriptors \
  --github-topic agent-federation-node \
  --github-owner kimeisele
```

## Reusable publisher workflow

Source repos can publish their authority feed with:

```yaml
jobs:
  publish-authority-feed:
    uses: kimeisele/agent-internet/.github/workflows/reusable-publish-authority-feed.yml@main
    with:
      install-command: python -m pip install -e .[dev]
      build-command: python scripts/export_authority_feed.py --output-dir .authority-feed-out
```