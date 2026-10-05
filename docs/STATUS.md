# Project status

**Date:** October 5, 2026
**Scope:** current sudofx implementation

## Objective

sudofx provides durable, portable, governed context for work performed by interchangeable intelligences.

The success condition is not that one model remembers. The success condition is that a fresh process can reconstruct enough explicit, governed context from authoritative state to continue useful work correctly.

## Implemented boundaries

- Kernel: deterministic governance, atomic transitions, receipts, provenance, and verified replay.
- Runtime: bounded context, durable invocation lifecycle, recovery, accounting, and provider/effect ordering.
- Applications: identity/versioning, sealed namespaces, deterministic policy re-evaluation, explicit migrations, and compact event-log storage.
- Conversation: private same-origin chat with fresh provider calls and privacy-bounded durable state.
- Handoff: bounded packet export and governed grounding evaluations.

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
- The private Conversation server runs the same governed path end-to-end while raw browser transcript text remains transient.
- The private Conversation server now retains one successful exchange only in process memory for adjacent-reference resolution; explicit provider framing and one-follow-up public-URL inheritance make pronouns actionable, restart or Clear removes the pair, SQLite receives no raw text, and assistant display numbers derive from committed turn counts.
- Conversation preserves multiple simultaneous human-authorized commitments across fresh providers: suffixes are enforced deterministically, semantic response instructions remain explicit, and provider-invented commitment text is discarded before it can affect a reply or durable state.
- Conversation can read validated public HTTPS URLs and perform explicitly requested public-web searches through bounded provider capabilities; private targets fail closed, citations remain transient presentation, and web content cannot become a durable observation merely because it was retrieved.
- Handoff packet/scoring/evaluation semantics now live in `applications/handoff/`; new evaluations persist under `app:handoff` rather than as handoff-specific generic work operations.
- A schema-v11 global application-access latch now lets the operator STOP or RESTORE application-origin access while leaving sudofx itself online; application commits are generation-fenced against stale in-flight work, and STOP/RESTORE transitions are protected by an independently hash-chained audit trail.
- Emergency STOP has no full-suite dependency and may preempt ordinary serialized sudofx authority work; RESTORE requires the full suite to pass before reopening connected-application access.
- The recovered `continuity@1` seven-cubed matrix is now a reusable sudofx extension: 343 stable coordinates, deterministic traversal, and an immutable versioned definition that applications may use while keeping campaign progress/results in their own governed SQLite state.
- Conversation is the first in-repo consumer of that extension: matrix campaigns are opt-in, the next cell enters bounded provider context only while active, cell verdicts/evidence digests persist through `app:conversation`, and fresh service instances reconstruct campaign progress from SQLite.

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
matrix extension
    └─ deterministic shared coordinate grammar (no authority)
    ↓
applications
    ├─ conversation
    └─ handoff
    ↓
derived presentation / external infrastructure
```

## Important current correction

Presentation must remain read-only with respect to authority.

A Pages render may reconstruct or migrate a disposable local copy far enough to interpret current state, but it must not checkpoint schema changes merely because presentation code encountered an older database. Authorized stateful paths own durable migration commits.

This preserves the contract:

> presentation is a projection, not an authority surface.

## Public product surface

Implemented and verified:

- GitHub Pages now publishes a lightweight static shell rather than replaying SQLite to regenerate the whole site.
- Home, Applications, Technical, and Metrics are separate public surfaces.
- The application catalog presents Conversation and Handoff; external metrics sources are unconfigured.
- The homepage leads with a natural explanation and ELI15 summaries rather than raw technical telemetry.
- Technical and metric pages fetch changing public-safe data from the disposable `sudofx-live` projection branch at runtime.
- Pages rebuild triggers are limited to shell/product-surface source changes; operational state changes do not trigger a site rebuild.
- The new shell has deployed successfully through GitHub Pages.
- Pages and live projection cadence are separated; operational state does not rebuild the shell.
- Public metrics expose bounded provenance/freshness and preserve the database-first authority boundary.
- Accessibility/performance guardrails are enforced by `scripts/check_site_shell.py` in CI and Pages.
- The shell supports responsive mobile layouts plus automatic system light/dark modes.
- The old monolithic report renderer is no longer a public surface; it remains only an internal/diagnostic export path.
- Final website CI and Pages runs passed on commit `7d9be2a`.

## Current frontier

Next: discuss the sudofx API and extensible application design before selecting new implementation behavior.

## Remaining work

1. Preserve the now-hardened boundary: providers execute only through runtime lifecycle/effect seams; experiments remain outside the reusable package; application/work namespaces stay sealed.
2. Before internet-hosting Conversation, deploy an authenticated private gateway/state path; public Pages and public Git refs remain unsuitable as a private chat authority.
3. Prove broader provider substitution when deliberately authorized.
4. Continue long-horizon semantic tests; mechanical replay alone does not prove that compressed context preserves useful meaning indefinitely.
5. Continue retiring the pre-application manual-handoff compatibility path after existing authoritative records no longer depend on it; do not remove historical replay support prematurely.

## Open risks

- semantic loss under aggressive context compression
- provider breadth not yet demonstrated across materially different live vendors
- GitHub remains a significant execution/storage host dependency
- public Git refs are unsuitable for sensitive durable state
- application growth could tempt domain logic back into the kernel
- legacy migration code may become accidental permanent architecture if not explicitly retired
- long records still require bounded replay/checkpoint strategy without weakening auditability

## Current interpretation

sudofx is a working governed engine with an implemented application boundary.
Conversation and Handoff exercise different domain semantics through that boundary.
Mechanical replay proves record integrity and reconstruction; it does not prove
that bounded context preserves useful meaning indefinitely.
