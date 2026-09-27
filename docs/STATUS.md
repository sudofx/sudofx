# Project status

**Date:** September 26, 2026  
**Scope:** current implementation on `master`

## Objective

sudofx exists to provide durable, portable, governed context for work performed by interchangeable intelligences.

The success condition is not that one model remembers. The success condition is that a fresh intelligence can reconstruct enough explicit context from authoritative state to continue useful work correctly.

## Objective assessment

| Objective | Status | Evidence in current implementation |
| --- | --- | --- |
| Externalize authority from the model | Achieved at kernel level | Models receive context and return proposals; mutation remains inside deterministic kernel/governance paths. |
| One durable source of truth | Achieved at current scale | SQLite is authoritative; cloud state is checkpointed on `sudofx-state`; Pages and proof artifacts are derived. |
| Append-only accountable history | Achieved at kernel level | Accepted and rejected governed operations produce hash-linked receipts. |
| Replay state from durable history | Achieved at kernel level | Kernel startup and tests verify replay from the record. |
| Bounded context | Achieved | Work-specific context and handoff packets avoid inheriting an entire opaque session. |
| Disposable intelligence | Achieved mechanically | Fake provider and Gemini process adapter both operate through the same proposal boundary. |
| Provider substitution | Mechanism achieved; breadth not yet proven | Provider-neutral process boundary exists, but sustained multi-provider real-world continuity remains future evidence. |
| Live external model continuity | Achieved for bounded experiment | Gemini receives reconstructed context and returns governed proposals without direct state authority. |
| Continuous unattended testing | Achieved | Success-only GitHub Actions chain dispatches exactly one successor after successful publication. |
| Fail visibly instead of looping blindly | Achieved | Test, provider, governance, or deployment failure ends the continuation chain. |
| Phone-first observation and control | Achieved | Pages observer plus separate owner-authenticated Start/Stop service. |
| Human-readable auditability | Substantially achieved | Observer exposes context, response, outcome, receipts, run identity, and status. |
| Durable continuity over long time/model/vendor turnover | Not yet proven | This is the current experiment, not an established result. |
| Product-market utility beyond the kernel | Not yet proven | No claim yet that the mechanism is sufficient for broad production workflows. |

## What changed today

The project crossed several implementation boundaries in one day:

- moved from deterministic-only proof to live Gemini continuity probes
- built a phone-first observer for live development
- made observer updates refresh from current workflow evidence
- moved to continuous success-only cloud cycles
- isolated continuous Gemini tests from authoritative SQLite mutation
- added authenticated owner Start/Stop controls
- contained provider/OAuth failures inside the control-service boundary
- separated Cloudflare execution context from GitHub transport injection
- made authenticated owner workflow state override weaker observer telemetry
- opened the WAKE✳︎ inspiration link in a separate tab

These changes increase operational capability without changing the core authority model.

## Current structure

```text
Implementation authority
  master

Operational truth
  SQLite database
  checkpointed to sudofx-state

Disposable execution
  GitHub Actions

Disposable intelligence
  Gemini provider adapter
  deterministic fake provider

Deterministic authority
  Kernel + governance + transition logic

Presentation
  generated GitHub Pages observer

Authenticated operator control
  Cloudflare Worker + GitHub OAuth

Recovery / inspection
  local runner + CLI + tests
```

## Current experiment

The active `handoff-v1` objective asks a fresh model to reconstruct the essential sudofx project boundary from sanitized durable context.

Every continuous cycle is deliberately a test, not a state mutation.

That distinction matters:

- successful Gemini output proves only that the bounded exchange occurred
- deterministic governance proves whether the proposal matches allowed structure
- the isolated verification snapshot prevents test traffic from changing authoritative work
- durable state changes still require an explicit governed transition

## Remaining risks

The architecture is directionally aligned, but several risks remain open:

1. **Semantic sufficiency:** bounded context may be structurally correct yet still omit information needed for useful continuation.
2. **Provider breadth:** Gemini success does not prove interchangeable behavior across materially different providers.
3. **Long-horizon drift:** repeated summaries/derivations can preserve syntax while losing meaning.
4. **Governance growth:** deterministic policy must remain understandable as operations become richer.
5. **Operational coupling:** GitHub and Cloudflare currently provide execution/control infrastructure even though neither owns sudofx state.
6. **Storage evolution:** SQLite is correct for the current scale; migration to another backend must not leak storage specifics into kernel contracts.
7. **Projection trust:** the observer must continue clearly distinguishing live telemetry, generated artifacts, and authoritative state.
8. **State confidentiality:** `sudofx-state` is currently a public Git ref; no private or identifying durable material may enter it before migration to private storage.
9. **Independent recovery:** authenticated 30-day Actions backups improve rollback, but they still share the repository/account failure domain.

## Next objectives

Near-term work should remain narrow:

- measure continuity quality instead of merely cycle success
- test replacement across more than one real model/provider
- make reconstruction quality comparable over time
- preserve provenance for every derived context unit
- keep all durable operational truth in the database
- migrate authoritative persistence out of the public Git ref before storing private context
- establish a second-provider/private backup target and periodically prove restoration
- resist adding product breadth that weakens the kernel experiment

## Bottom line

The first implementation objective has been met: the governed loop exists, runs with a real external model, survives disposable execution, and keeps authority outside the model.

The larger sudofx objective is still under test: whether that governed record can preserve enough meaning for durable work across model, vendor, person, device, and time replacement.
