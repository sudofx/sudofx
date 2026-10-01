# 100126 CONTRACT

**Date:** October 1, 2026  
**Project:** sudofx  
**Status:** Active execution contract  
**Authority:** Human-approved implementation direction for October 1 work

## Purpose

This document defines the work contract for the next stage of sudofx.

The goal is not to add features indiscriminately. The goal is to turn the existing continuity proof into a durable, reusable engine whose architecture remains faithful to the north star:

> Build a durable work boundary that survives replacement of every intelligence participating in it.

Everything completed under this contract must strengthen that boundary or remain clearly outside it.

## Operating constraints

This work is intentionally constrained.

- Budget: **$0**
- API calls: **limited**
- Operator hardware: **iPhone only**
- Development/control surfaces: **GitHub and ChatGPT**
- Authoritative operational truth: **database first**
- SQLite remains the current storage implementation
- No durable JSON, JSONL, Markdown, HTML, Pages output, workflow artifact, or browser state may become a competing source of operational truth
- Models propose; deterministic governance decides; the database records durable outcomes
- GitHub, provider APIs, browsers, workflows, and presentation surfaces remain replaceable infrastructure
- Changes must be made directly against the live repository
- Work must favor explicit contracts, replayability, provenance, failure visibility, and bounded authority over convenience

These constraints are not temporary excuses. They are part of the design pressure under which sudofx must prove itself.

## Core architectural decision

WAKE✳︎ should not define sudofx.

sudofx is the reusable governed engine.

WAKE✳︎ should become a **sudofx application**: a self-contained domain system that uses sudofx for durable state, governance, continuity, provenance, provider interaction boundaries, and execution contracts.

The term **plugin** should no longer be used as the primary description of WAKE✳︎.

Use the following vocabulary unless later evidence requires refinement:

- **kernel** — smallest durable authority boundary
- **runtime** — execution and provider/effect coordination around the kernel
- **application** — a complete domain system built on sudofx, such as WAKE✳︎
- **extension** — optional capability that augments sudofx or an application without becoming its identity
- **plugin** — optional technical loading/packaging mechanism only when dynamic installability is actually implemented

A healthy application may define its own domain state and policy, but it must not bypass sudofx authority or create a second authoritative operational store.

## What belongs in the sudofx core

WAKE✀︎ has produced several concepts that are more general than research and should be considered for sudofx itself.

### 1. Durable invocation lifecycle

Provider interaction must become first-class durable evidence.

The durable record should be able to distinguish:

- invocation requested
- context delivered
- provider selected
- attempt started
- attempt completed
- provider failed before producing a proposal
- proposal received
- proposal governed
- invocation completed or interrupted

A provider failure before proposal creation must not fabricate a proposal receipt, but the fact that an invocation occurred should not disappear from operational history.

### 2. Explicit actor and origin provenance

Durable operations should identify where they came from.

Initial origins should support at least:

- human
- model/provider
- scheduled/runtime process
- application
- external integration

Origin describes provenance. It must never grant authority merely because of who or what produced the input.

### 3. Incomplete-operation recovery

If execution stops after durable work begins but before it completes, a fresh process must be able to reconstruct that interruption explicitly.

Recovery must not guess that an external effect succeeded.

### 4. Context-delivery receipts

The record should preserve enough evidence to know what representation was actually delivered across an intelligence boundary.

That may include:

- source revision
- context policy/version
- byte size
- included categories
- omitted counts
- omission digests
- provider/model provenance
- application/work scope

The delivered representation is derived evidence, not a second source of truth.

### 5. Progressive abstraction with recoverable provenance

Bounded or compressed context may be lossy, but the loss must be explicit.

Working abstractions should preserve durable references, counts, digests, or identifiers that point back toward authoritative underlying records.

A summary must never silently replace the source material it summarizes.

### 6. Explicit external-effect boundary

Provider calls and future external actions must cross a declared execution boundary.

An application or model should not receive arbitrary authority to perform external actions.

The intended separation is:

```text
intent/proposal
    ↓
governance
    ↓
authorized effect request
    ↓
effect adapter
    ↓
external system
    ↓
durable outcome / failure evidence
```

The exact implementation may evolve, but the authority boundary must remain explicit.

### 7. Generic resource accounting

The runtime should support durable accounting for provider attempts, call counts, quota-related outcomes, and future cost metadata.

Vendor-specific quota rules remain outside the kernel.

## What does not belong in sudofx core

The following WAKE✳︎ concepts remain application/domain concerns unless future evidence proves they are universally necessary:

- research topics
- research projects
- notebooks
- beliefs
- research evidence promotion rules
- publication policy
- Bob
- inquiry-drive scoring
- scholarly collection logic
- host/source allowlists
- research seed questions
- research-specific commitments
- time dilation experiments
- editorial policy
- research feeds
- scientific-source qualification rules

The kernel must not become WAKE✳︎ with renamed modules.

## Target architecture

```text
sudofx
│
├── kernel
│   ├── durable record contract
│   ├── replay
│   ├── governance boundary
│   ├── transitions
│   ├── receipts
│   └── provenance primitives
│
├── runtime
│   ├── bounded context construction
│   ├── invocation lifecycle
│   ├── provider/effect adapters
│   ├── recovery
│   └── application loading
│
├── applications
│   ├── WAKE✳︎
│   ├── conversation proof
│   └── future applications
│
└── extensions
    └── optional capabilities
```

This diagram is directional. Code should not be moved merely to match folder names. Boundaries must be proven by contracts and tests first.

## Application contract direction

The first application contract should remain deliberately small.

An application may need to define:

- stable identity
- version
- application state schema
- context projection rules
- allowed proposal/action schema
- application governance policy
- deterministic transition semantics
- presentation projection
- requested external-effect capabilities
- application migrations
- human-readable metadata

An application must not receive:

- raw authority to commit database events
- unrestricted SQLite/database access as a substitute for the storage contract
- permission to bypass governance
- hidden provider memory as required state
- an independent authoritative event store
- permission to perform undeclared external effects
- authority merely because code is installed

### Application removal test

Removing an application must not invalidate the meaning or replay semantics of the sudofx kernel itself.

Removing WAKE✳︎ may make WAKE✳︎-specific application state unusable without that application, but it must not corrupt or redefine the underlying sudofx authority contract.

## Hardening phase

Before WAKE✳︎ is migrated, sudofx must be cleaned and hardened.

This is not cosmetic refactoring.

The key question for every experimental path is:

> Is this part of sudofx, or was this scaffolding used to discover sudofx?

The hardening work should:

1. Freeze the smallest credible kernel contract.
2. Separate provider/network execution from kernel authority.
3. Add durable invocation and provenance lifecycle primitives.
4. Make human/model/system/application origins explicit.
5. Consolidate duplicated provider and overnight experiment paths.
6. Isolate continuity experiments, manual handoff scoring, and test-only machinery from production architecture.
7. Reduce GitHub-specific workflow machinery to an infrastructure adapter rather than an architectural dependency.
8. Strengthen tests around invariants and failure semantics.
9. Verify fresh replay for every durable operation.
10. Verify human-readable outputs are projections generated from database state.
11. Remove or quarantine dead compatibility code and one-off development workarounds.
12. Replace the current broad plugin direction with applications plus optional extensions.
13. Preserve or improve explanatory/comment density at consequential boundaries.
14. Avoid rewriting clean kernel pieces merely for stylistic uniformity.

## Human interaction proof

After the core boundary and application contract are credible, build the smallest possible freeform human interaction application.

The proof should provide a simple browser surface:

- text input
- submit action
- readable response

The intended flow is:

```text
human text
    ↓
durable human-origin input
    ↓
bounded context reconstructed from database
    ↓
provider invocation through sudofx runtime
    ↓
provider response / proposal
    ↓
governance
    ↓
authoritative database transition
    ↓
derived human-readable response
    ↓
browser
```

The browser is not memory.

The browser may disappear between every turn.

Each new interaction must be reconstructable from the database and governed runtime state.

The proof does not need polished chat UX, streaming, rich formatting, authentication, or multi-user support.

A single text box and response view are sufficient.

## Execution order

Work under this contract should proceed in this order.

### Phase A — Define the reusable sudofx boundary

- compare WAKE✳︎ lessons against current sudofx contracts
- identify reusable primitives
- formalize invocation/effect/provenance boundaries
- keep research-specific concepts out

**Exit condition:** the reusable engine boundary is explicit enough that WAKE✳︎ cannot accidentally define it.

### Phase B — Harden and sanitize sudofx

- inspect current experimental scaffolding
- consolidate or quarantine duplicated paths
- remove development workarounds that have become accidental architecture
- strengthen invariant and recovery tests
- keep database authority singular

**Exit condition:** the repository has a clear production path and experimental/test paths cannot be mistaken for the engine.

### Phase C — Define and prove the Application contract

- replace WAKE✳︎-as-plugin framing
- define smallest application-facing contract
- define permissions/effect requests
- prove applications cannot bypass kernel authority

**Exit condition:** a new application can be added without modifying kernel semantics.

### Phase D — Build minimal human conversation proof

- browser input
- governed human-origin record
- bounded database-derived context
- provider call
- governed response
- readable browser projection

**Exit condition:** multiple back-and-forth turns survive browser/process replacement because continuity lives in the authoritative database.

### Phase E — Begin WAKE✳︎ application migration

Only after A-D are credible:

- map WAKE✳︎ domain state onto the application contract
- preserve research-specific governance above the kernel
- remove duplicated engine responsibilities from WAKE✳︎
- migrate incrementally with replay and behavioral equivalence tests

**Exit condition:** WAKE✳︎ runs as a sudofx application rather than maintaining a competing engine.

## Priority

The work priority is:

1. core boundary
2. hardening
3. application contract
4. WAKE✳︎ migration foundation
5. human conversation proof

The human interaction proof is valuable because it demonstrates generality, but it must not distort the engine merely to produce a visible demo quickly.

## October 1 decision rule

The original October 1 continuity milestone remains meaningful.

The deadline may be extended if today's work materially advances sudofx from a successful continuity experiment toward a reusable governed engine.

A meaningful extension should be justified by concrete progress such as:

- reusable core boundaries formalized
- architectural debt removed
- invocation/effect provenance made durable
- application boundary implemented
- invariant coverage strengthened
- first non-WAKE application path proven

The deadline should not be extended merely because more features remain desirable.

## Non-negotiable north-star tests

Before accepting a consequential design change, ask:

1. Does this preserve one authoritative database?
2. Can a fresh process reconstruct the state without hidden model/session memory?
3. Does the model remain a proposer rather than authority?
4. Is governance deterministic at the authority boundary?
5. Are external effects explicit and accountable?
6. Does failure stop or recover visibly rather than silently inventing success?
7. Can the underlying intelligence/provider be replaced?
8. Can GitHub or the current execution host eventually be replaced?
9. Does this belong to sudofx generally, or to one application?
10. Does this make the system easier to audit years later rather than merely easier to ship today?

If a change fails these tests, convenience is not sufficient reason to accept it.

## Working principle

> Exact underneath. Bounded on purpose. Correctable always.

The database remains the record.

Everything else is a view, proposal, execution boundary, or application built around it.
