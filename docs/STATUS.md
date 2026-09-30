# Project status

**Date:** September 27, 2026
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
| Phone-first observation and control | Achieved | Pages observer plus GitHub-native Start/Stop workflows. |
| Bounded operational maintenance | Achieved at current scale | Schema identity/versioning, fail-closed restore, bounded public history, verified 30-day backup artifacts, and authenticated storage diagnostics are live. |
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
- replaced remote owner controls with GitHub-native Start/Stop workflows
- kept bounded recovery operations in GitHub Actions
- added SQLite application identity, ordered schema migrations, and fail-closed restore checks
- bounded the public activity projection while preserving the complete authoritative event chain
- 
- 
- refreshed GitHub Actions to current Node.js 24-compatible major versions
- 
- 
- made the Pages status light link directly to GitHub Actions
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

Operator control
  GitHub Actions
  Start / Stop / bounded maintenance

Recovery / inspection
  local runner + CLI + tests
```

## Current experiment

The active `handoff-v1` record has now crossed five distinct semantic gates.

First, a fresh Gemini process proved useful continuation from bounded durable
context by reconstructing the work and choosing a concrete `VACUUM INTO`
recoverability action. That action was then executed through a finite governed
proof: the derived SQLite snapshot passed integrity checking and full semantic
replay while authoritative revision, state, and event head remained unchanged.

Second, Gemini repeatability passed **3 of 3** successive fresh-process handoffs.
Each process received newly advanced bounded state, reconstructed the objective
and accepted history needed for the frontier, proposed one actionable next step,
avoided unsupported execution claims, and left production authority unchanged.

Third, deliberate context compression established a practical semantic floor.
The tested handoff was reduced to exactly one readable accepted milestone and
zero receipt prose, while objective, constraints, current frontier, accepted and
omitted counts, provenance, and an omitted-history digest remained available.
At that boundary Gemini reconstructed the work correctly from **1,810 bytes
instead of 28,480 bytes**, a **93.64% reduction**, without pretending the
omitted digest contained readable history.

Fourth, that compressed shape was promoted from an experiment to the normal
live Gemini handoff policy. The promoted-default proof passed again against a
larger authoritative record: Gemini received **2,053 bytes instead of 31,085
bytes** (**93.4% reduction**), with one of eighteen milestones readable, zero
receipts, and seventeen milestones represented only by count plus digest. It
still reconstructed the portable-continuity objective and exact active frontier
and proposed the correct policy action.

Fifth, the promoted policy survived a second bounded repeatability trial after
operator intent itself became durable context. One fresh process correctly
stopped at the recorded owner-Stop boundary instead of inventing permission.
After an explicit governed Start, **3 of 3** additional fresh processes preserved
the objective, current frontier, compression boundary, and semantic-review duty.
Each received **1,154 bytes instead of 43,190 bytes** (**97.33% reduction**),
exposed one of twenty-three accepted milestones and zero receipts, and left
production authority unchanged. The batch was then deliberately stopped and
recorded as a structured passing assessment rather than allowed to consume
provider capacity without adding proportional evidence.

Semantic quality is now represented as governed structured data rather than
only prose. A `record_assessment` transition stores verdict, criterion-level
judgments, compression metrics, and provider/run/context provenance in
authoritative SQLite. The generated observer renders the newest assessment as a
**Continuity quality** view. Assessment history remains durable in SQLite but is
excluded from provider context; models receive only an assessment count and
digest so measurement cannot gradually bloat the handoff being measured.

Gemini has now demonstrated sustained success across two independent 3-of-3
repeatability batches in addition to the earlier finite proofs. Paid-vendor
substitution remains deliberately deferred until the owner chooses to spend on
provider breadth rather than deepen the free-vendor baseline.

Continuous mode is technically eligible to resume, but it remains intentionally
**owner-stopped**. The next continuous run no longer repeats one packet shape:
a deterministic seven-phase stress matrix varies which continuity cues survive
into each fresh-model handoff. Some cycles remove the latest readable milestone,
some remove the previous model observation, and the frontier-only phase removes
both. Authority, provenance, and adversarial phases test different failure modes
without allowing the model to choose its own curriculum.

Every live-model cycle remains a test rather than an authoritative model
mutation:

- Gemini receives a derived bounded view, not the database
- the proposal crosses deterministic governance on a temporary SQLite snapshot
- production SQLite remains unchanged by the probe
- human semantic judgment is recorded separately as governed evidence
- Pages, JSON proof files, and workflow artifacts remain replaceable projections

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
10. **Unprotected authority branch:** `sudofx-state` is currently unprotected; any protection design must preserve the serialized Actions checkpoint path rather than blocking it accidentally.

## Next objectives

The next work remains intentionally narrow:

- retain the structured assessment contract for future judged probes so continuity quality remains comparable over time
- treat bounded, explicitly judged batches as the default experiment shape; continuous mode remains available for deliberate sustained trials
- compare objective fidelity, frontier fidelity, unsupported-claim discipline, actionability, context size, and compression across deterministic handoff-dropout conditions and future provider changes
- preserve assessment provenance and keep all durable operational truth in SQLite
- prevent assessment/history growth from leaking back into provider context
- keep the uncompressed Gemini path only as an explicit diagnostic baseline
- migrate authoritative persistence out of the public Git ref before any private or identifying context is stored
- use the seven-phase dropout matrix to locate the semantic floor before spending on another provider; provider substitution, a longer time gap, and human-maintainer replacement remain later independent boundaries
- establish an independent/private backup target before sensitive durable context exists
- resist product breadth that weakens the kernel experiment

## Bottom line

The first implementation objective has been met: the governed loop exists, runs with a real external model, survives disposable execution, and keeps authority outside the model.

The larger sudofx objective is still under test: whether that governed record can preserve enough meaning for durable work across model, vendor, person, device, and time replacement.
