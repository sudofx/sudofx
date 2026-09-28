# sudofx remote operator plugin

This optional plugin is the confidential authentication and remote-control boundary
for phone-first development and operator workflows.

It is deliberately outside the sudofx kernel. Removing this directory removes
the remote control surface without changing durable work semantics, governance,
or SQLite authority.

## Configuration

Two text files define the install:

- `plugin.toml` — portable plugin identity, compatibility, permissions, authority claims, and supported capabilities.
- `wrangler.jsonc` — Cloudflare-specific deployment configuration. Users may edit `ENABLED_CAPABILITIES` to select a subset of the plugin's supported powers.

Configuration can **narrow** authority but cannot widen it. The worker contains a
compiled capability ceiling, so adding an unknown action to `wrangler.jsonc`
does not create a new permission.

Secrets never belong in either file; they remain in the provider's encrypted
secret store.

The Cloudflare Git build keeps the repository root as `/` and uses this deploy
command:

```sh
npx wrangler deploy --config plugins/remote_operator/wrangler.jsonc
```

Keeping the path here beside the provider-specific configuration prevents the
Git integration from depending on a retired plugin directory. A local deploy
uses the same command, so Git builds and operator-initiated releases resolve the
same manifest and preserve the existing `sudofx-control` Worker identity.

## Authority

```text
GitHub OAuth
  -> proves configured operator identity

remote_operator plugin
  -> validates configured + compiled capability

GitHub Actions
  -> invokes the existing sudofx workflow

Kernel + SQLite
  -> remain governance and durability authority
```

The plugin stores no sudofx operational truth and never writes SQLite directly.

## One-shot API

Authenticated callers may POST to `/api/operate`:

```json
{"action":"export-handoff","key":"handoff-v1"}
```

Supported one-shot actions are `verify`, `backup`, `prove-work`,
`prove-model`, `export-handoff`, and `handoff-evaluate`. Start and Stop keep dedicated endpoints
because their ordering and cancellation semantics are stronger than a generic
one-shot dispatch.

`handoff-evaluate` accepts one bounded returned JSON object from the authenticated
Pages UI and dispatches it unchanged to `sudofx.yml`. The Worker validates only
transport shape and size. The workflow reconstructs the frozen packet, scores
the untrusted response, and asks normal governance to append the SQLite record.
The page's encrypted operator session—not an iOS Shortcut token—is the authority
that permits the dispatch.

## Removal test

Deleting `plugins/remote_operator/` must leave the kernel, durable record,
governance semantics, replay, and work lifecycle unchanged. That is the plugin
boundary this implementation is intended to prove.
