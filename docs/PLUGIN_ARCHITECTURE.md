# Plugin Architecture Direction

Status: **Preserved design direction — directory boundary now in use; runtime plugin API not yet frozen**

## Decision

sudofx should evolve toward a small, durable core with optional capabilities loaded as plugins.

A plugin should be installable without modifying core code, ideally by either:

- cloning a repository into `plugins/<name>/`
- copying/dropping a compatible plugin directory into `plugins/<name>/`

Different installation methods should resolve to the same plugin contract.

## Mental model

- **sudofx core** — durable record, context construction, governance, transitions, receipts, permissions, provenance
- **plugins** — domain-specific capabilities, workflows, UI, hooks, migrations, tools, or integrations
- **WAKE✳︎** — first serious candidate application/plugin: an automated research institution running on top of sudofx

## Architectural rule

Do not hard-wire WAKE✳︎-specific assumptions into sudofx core.

If a capability is specific to research, topics, Bob, research cycles, publications, evidence collection, or another application domain, prefer keeping it outside the core unless it is genuinely required for durable governed continuity itself.

## Trust boundary

Installed does **not** mean trusted.

Plugins should remain subject to sudofx governance. A future plugin contract should make permissions and effects explicit and preserve provenance and receipts for meaningful actions.

At minimum, a plugin system should eventually define:

- manifest / identity / version
- compatibility requirements
- requested permissions
- lifecycle hooks
- migrations / durable state ownership
- optional UI surfaces
- workflow or tool registration
- provenance for plugin-produced work
- auditable install / enable / disable / upgrade events
- failure isolation so one plugin cannot silently corrupt core state

## Likely future shape

```text
sudofx/
  core/
  plugins/
    manual_handoff/
    remote_operator/
    wake/
    <future-plugin>/
```

The top-level `plugins/` boundary is now real. `manual_handoff` contains development-only scoring/transport logic, while `remote_operator` contains the removable authenticated control surface used during development and operations. Each plugin begins with a human-readable `plugin.toml` manifest; deployment-specific configuration remains text alongside the plugin. Plugins may request capabilities, but configuration may only narrow authority granted by code/governance. Neither plugin owns durable truth. The general runtime API remains intentionally small and may evolve as more plugins prove the contract.

## North-star test

A successful plugin architecture should allow this sentence to become true:

> WAKE✳︎ can be removed, replaced, upgraded, or moved without changing the durable continuity and governance guarantees of sudofx itself.

That is the key constraint to protect as sudofx grows.
