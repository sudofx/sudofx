# sudofx plugins

Plugins extend sudofx without becoming sudofx.

The kernel owns durable work semantics, governance, receipts, replay, and the
authoritative database. A plugin may add an integration, workflow, UI, domain
capability, development tool, or provider adapter, but it must not create a
second operational source of truth.

## Minimal plugin shape

```text
plugins/<id>/
  plugin.toml       portable identity + declared contract
  README.md         human explanation
  <code>            implementation
  <config>          optional human-editable deployment/runtime configuration
```

`plugin.toml` is intentionally plain TOML so people and tooling can inspect it
without loading plugin code.

A manifest should state at least:

- stable plugin id, name, version, kind, and entrypoint
- sudofx compatibility
- authority claims
- requested external permissions
- supported capabilities

## Configuration rule

Configuration is text when practical and belongs beside the plugin or in the
deployment environment. Secrets never belong in committed configuration.

Configuration may **narrow** authority but must not silently widen it beyond what
the plugin implementation and sudofx governance explicitly permit.

## Removal test

A healthy optional plugin can be removed without changing the meaning of the
authoritative sudofx record or breaking kernel replay/governance.

If removing a plugin destroys core continuity, that capability probably belongs
in the kernel or the durable contract needs a better boundary.
