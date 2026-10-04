# Project status

**Date:** October 3, 2026  
**Scope:** current implementation on `master` plus the completed Phase E application boundary on WAKE✳︎ `master` in `sudofx/wake`

## Objective

sudofx provides durable, portable, governed context for work performed by interchangeable intelligences.

The success condition is not that one model remembers. The success condition is that a fresh process can reconstruct enough explicit, governed context from authoritative state to continue useful work correctly.

## Contract phase status

| Phase | Current status | Evidence |
| --- | --- | --- |
| A — reusable sudofx boundary | **Complete at the current contract boundary** | Kernel/runtime/application separation, invocation lifecycle, provenance, bounded context, provider/effect boundaries, and research-specific exclusions are explicit in code, docs, and executable invariants. |
| B — harden and sanitize | **Complete at the current contract boundary** | Provider execution is runtime-only; experiments are quarantined outside `src/sudofx`; Pages is read-only; `app:*` and `work:*` namespaces are sealed; duplicate conversation/local-cycle entry points and unreachable diagnostic flags are retired; Gemini HTTP success transport is consolidated without importing vendor policy into the engine. |
| C — application contract | **Complete at the current contract boundary** | `ApplicationDefinition`, registry/host, deterministic policy re-evaluation, sealed namespaced state, migration/version checks, bounded capabilities, compact event-log storage, and removal tests are implemented and covered by executable invariants. |
| D — minimal human conversation proof | **Complete at private end-to-end proof level** | Governed human and assistant turns, privacy-bounded database-derived observations, fresh provider invocation, and a mobile-first chat surface are implemented. A private same-origin server provides the runnable path today; public Pages stays presentation-only until an authenticated gateway is configured. |
| E — WAKE✳︎ migration | **Complete at architectural exit condition on WAKE `master`** | `wake-state` carries only `data/sudofx.sqlite`; fresh initialization is native sudofx; WAKE policy is a versioned application; generic invocation lifecycle, interruption recovery, external-effect ordering, and aggregate invocation accounting use sudofx; legacy SQLite persistence is quarantined to migration/compatibility code. The explicitly promoted `wake-runtime` branch may lag while research is active. |

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
- The private Conversation server now retains one successful exchange only in process memory for adjacent-reference resolution; restart or Clear removes it, SQLite receives no raw pair, and assistant display numbers derive from committed turn counts.
- Conversation preserves multiple simultaneous human-authorized commitments across fresh providers: suffixes are enforced deterministically, semantic response instructions remain explicit, and provider-invented commitment text is discarded before it can affect a reply or durable state.
- Conversation can read validated public HTTPS URLs and perform explicitly requested public-web searches through bounded provider capabilities; private targets fail closed, citations remain transient presentation, and web content cannot become a durable observation merely because it was retrieved.
- Handoff packet/scoring/evaluation semantics now live in `applications/handoff/`; new evaluations persist under `app:handoff` rather than as handoff-specific generic work operations.
- WAKE✳︎ domain migration preserves its own policy above the generic sudofx authority boundary.
- WAKE✳︎ provider attempts share sudofx invocation IDs/evidence, survive fresh-process recovery, and use the generic pre-effect durability barrier without importing Gemini-specific exception types into the engine.
- A schema-v11 global application-access latch now lets the operator STOP or RESTORE application-origin access while leaving sudofx itself online; application commits are generation-fenced against stale in-flight work, and STOP/RESTORE transitions are protected by an independently hash-chained audit trail.
- Emergency STOP has no full-suite dependency and may preempt ordinary serialized sudofx authority work; RESTORE requires the full suite to pass before reopening connected-application access.

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
    ├─ handoff
    └─ WAKE✳︎ migration
    ↓
derived presentation / external infrastructure
```

## Important current correction

Presentation must remain read-only with respect to authority.

A Pages render may reconstruct or migrate a disposable local copy far enough to interpret current state, but it must not checkpoint schema changes merely because presentation code encountered an older database. Authorized stateful paths own durable migration commits.

This preserves the contract:

> presentation is a projection, not an authority surface.

## Completed product-surface contract

The completed A–E architecture contract remains closed. The October 2 public product-surface contract in `100226-WEBSITE-CONTRACT.md` is also complete at its stated boundary.

Implemented and verified:

- GitHub Pages now publishes a lightweight static shell rather than replaying SQLite to regenerate the whole site.
- Home, Applications, Technical, and Metrics are separate public surfaces.
- The homepage leads with a natural explanation and ELI15 summaries rather than raw technical telemetry.
- Applications currently presented are WAKE✳︎, Conversation, and Handoff.
- Technical and metric pages fetch changing public-safe data from the disposable `sudofx-live` projection branch at runtime.
- Pages rebuild triggers are limited to shell/product-surface source changes; operational state changes do not trigger a site rebuild.
- The new shell has deployed successfully through GitHub Pages.
- Pages and live projection cadence are separated; operational state does not rebuild the shell.
- Public metrics expose bounded provenance/freshness and preserve the database-first authority boundary.
- Accessibility/performance guardrails are enforced by `scripts/check_site_shell.py` in CI and Pages.
- The shell supports responsive mobile layouts plus automatic system light/dark modes.
- The old monolithic report renderer is no longer a public surface; it remains only an internal/diagnostic export path.
- Final website CI and Pages runs passed on commit `7d9be2a`.

## Remaining work

1. Preserve the now-hardened boundary: providers execute only through runtime lifecycle/effect seams; experiments remain outside the reusable package; application/work namespaces stay sealed.
2. Treat further WAKE legacy-store cleanup as compatibility retirement, not as a missing Phase E authority cutover; preserve replay/equivalence while removing dead migration-only coupling.
3. Before internet-hosting Conversation, deploy an authenticated private gateway/state path; public Pages and public Git refs remain unsuitable as a private chat authority.
4. Prove broader provider substitution when deliberately authorized.
5. Continue long-horizon semantic tests; mechanical replay alone does not prove that compressed context preserves useful meaning indefinitely.
6. Continue retiring the pre-application manual-handoff compatibility path after existing authoritative records no longer depend on it; do not remove historical replay support prematurely.

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

The question “can materially different applications use the same authority boundary without forcing the kernel to absorb their domain assumptions?” now has three concrete implementation proofs: Conversation, Handoff, and WAKE✳︎.

The A–E execution contract is satisfied at its stated architectural exit conditions. Remaining items are operational hardening, compatibility retirement, provider breadth, storage/privacy evolution, and long-horizon semantic research—not unfinished A–E architecture. Any new kernel or product semantics should begin from a new explicit frontier rather than silently extending the completed contract.
