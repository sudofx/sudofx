# Project status

**Date:** October 2, 2026  
**Scope:** current implementation on `master` plus the active WAKE✳︎ migration path in `sudofx/wake`

## Objective

sudofx provides durable, portable, governed context for work performed by interchangeable intelligences.

The success condition is not that one model remembers. The success condition is that a fresh process can reconstruct enough explicit, governed context from authoritative state to continue useful work correctly.

## Contract phase status

| Phase | Current status | Evidence |
| --- | --- | --- |
| A — reusable sudofx boundary | Substantially complete | Kernel/runtime/application separation, invocation lifecycle, provenance, bounded context, provider boundary, and research-specific exclusions are explicit in code and docs. |
| B — harden and sanitize | Substantially complete | Experiments are quarantined, replay/failure/invocation tests are extensive, schema identity is explicit, Pages is being kept read-only, and production paths are separated from experiment machinery. |
| C — application contract | Substantially complete | `ApplicationDefinition`, registry/host, deterministic policy re-evaluation, namespaced state, migration/version checks, and compact event-log storage are implemented and tested. |
| D — minimal human conversation proof | **Complete at contract level** | Governed human and assistant turns, bounded database-derived context, provider invocation, dedicated browser workflow, and derived Pages projection are implemented. CI now proves two back-and-forth rounds across separate Python interpreters sharing only the authoritative SQLite record, followed by a third fresh-process reconstruction of the four-turn transcript. |
| E — WAKE✳︎ migration | Underway | `sudofx/wake` contains `wake/sudofx_application.py`, `wake/sudofx_store.py`, migration/rehearsal workflows, and a cloud path where `wake-state` carries `data/sudofx.sqlite`. |

## What is already proven mechanically

- SQLite is the authoritative operational store.
- Models/providers do not receive database authority.
- Governance reruns deterministically at the commit boundary.
- Accepted/rejected operations leave accountable receipts.
- Provider invocation lifecycle and failures are durable evidence.
- Context delivery is bounded and can disclose omitted history.
- A new process can reconstruct application state from the database.
- Application version drift fails closed unless an explicit migration exists.
- Large applications can use compact event-log storage without duplicating full state on every transition.
- GitHub Actions, providers, browser surfaces, and generated Pages output remain replaceable infrastructure.
- The conversation proof survives complete Python interpreter replacement across multiple rounds; continuity is reconstructed from SQLite alone.
- WAKE✳︎ domain migration can preserve its own policy above the generic sudofx authority boundary.

## Current architecture

```text
SQLite record
    ↓ replay
kernel
    ├─ deterministic governance
    ├─ transitions
    ├─ receipts
    └─ provenance
    ↓
runtime
    ├─ bounded context
    ├─ invocation lifecycle
    ├─ provider/effect boundary
    └─ recovery/accounting
    ↓
applications
    ├─ conversation
    └─ WAKE✳︎ migration
    ↓
derived presentation / external infrastructure
```

## Important current correction

Presentation must remain read-only with respect to authority.

A Pages render may reconstruct or migrate a disposable local copy far enough to interpret current state, but it must not checkpoint schema changes merely because presentation code encountered an older database. Authorized stateful paths own durable migration commits.

This preserves the contract:

> presentation is a projection, not an authority surface.

## Remaining work

1. Finish the Phase B/C audit for duplicate execution paths, application bypasses, and compatibility code that can now be retired or quarantined.
2. Keep invocation/effect boundaries generic and avoid importing WAKE✳︎ research policy into the kernel.
3. Continue Phase E incrementally: reduce duplicated WAKE engine responsibilities while preserving replay and behavioral equivalence.
4. Retain the legacy WAKE Store only as verified migration/compatibility machinery; it is no longer an operational authority path.
5. Move authoritative cloud state away from a public Git ref before private or identifying durable material is allowed.
6. Prove broader provider substitution when deliberately authorized.
7. Continue long-horizon semantic tests; mechanical replay alone does not prove that compressed context preserves useful meaning indefinitely.

## Open risks

- semantic loss under aggressive context compression
- provider breadth not yet demonstrated across materially different live vendors
- GitHub remains a significant execution/storage host dependency
- public Git refs are unsuitable for sensitive durable state
- application growth could tempt domain logic back into the kernel
- legacy migration code may become accidental permanent architecture if not explicitly retired
- long records still require bounded replay/checkpoint strategy without weakening auditability

## Current interpretation

The original continuity experiment succeeded strongly enough to justify the October 1 extension.

sudofx is now better described as a **working governed engine with an implemented application boundary** than as a continuity prototype.

The immediate test is no longer “can a fresh model continue from external state?”

It is:

> Can materially different applications use the same authority boundary without forcing the kernel to absorb their domain assumptions?

The conversation application and the WAKE✳︎ migration are the first two concrete tests of that claim.
