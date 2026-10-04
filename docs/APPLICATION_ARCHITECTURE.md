# Application Architecture

**Status:** Active direction under `100126-CONTRACT.md`

## Decision

sudofx is the governed engine.

A complete domain system built on sudofx is an **application**.

WAKE✳︎ is the first substantial application migration in the separate `sudofx/wake` repository. Its Phase E architectural exit condition is now satisfied on WAKE `master`: operational authority and generic runtime responsibilities are sudofx-owned while WAKE retains its domain/research policy. It is not primarily a plugin: its research state, policy, workflows, presentation, and external integrations define an application identity rather than an optional capability that can be removed while leaving the same product behind.

Use these terms:

- **kernel** — smallest durable authority boundary
- **runtime** — context, invocation, recovery, and effect coordination around the kernel
- **application** — complete domain behavior built on sudofx
- **extension** — optional capability added to sudofx or an application
- **plugin** — optional packaging/loading mechanism if dynamic installation is implemented

## Current implementation evidence

As of October 2, 2026:

- `src/sudofx/applications.py` implements the application registry/host, deterministic action evaluation, version checks, and compact event-log storage.
- `applications/conversation/` provides the first small non-WAKE application proof.
- `applications/handoff/` owns portable handoff packet policy, grounding scoring, target registration, and evaluation evidence; the former manual-handoff experiment is now a compatibility shim.
- process-replacement tests reconstruct multiple conversation rounds from SQLite alone.
- `applications/conversation/server.py` provides a private same-origin end-to-end chat transport while `web/conversation.html` remains disposable presentation.
- the WAKE repository contains a versioned `WAKE_APPLICATION`, a sudofx-backed transitional Store, verified legacy import/archive logic, and Phase E rehearsal workflows.
- WAKE now writes provider-boundary evidence through sudofx's generic invocation journal and delegates durability-barrier/external-effect ordering to `InvocationLifecycle.invoke()`; Gemini-specific quota/fallback interpretation remains WAKE policy.

These are implementation facts, not a claim that the application contract is permanently frozen. WAKE remains the larger stress test, and its explicitly promoted `wake-runtime` branch may intentionally lag verified `master` while continuous research is active.

The conversation application is the first small concrete proof of this contract. Its human and assistant turns are governed application actions, its provider context contains the transient current message plus bounded database-derived observations and active commitments, and raw transcript text is not durable Conversation state. The private service owns one additional volatile input: the immediately previous successful human/assistant exchange. It supplies that pair only to the next fresh provider to resolve adjacent references, never writes it to SQLite, and drops it on restart or explicit Clear. Exact suffixes and declared per-response follow-up questions are deterministically enforced, including canonical removal of duplicate standalone suffixes when citations precede the final footer. Other semantic response instructions are explicit application state rather than hidden provider memory; new instructions must be exact excerpts of the authorizing human turn, multiple instructions may coexist, and fresh providers receive the governed set. The application deterministically parses the explicit `following footer:` and `[DONT FORGET]` init syntax instead of relying on a probabilistic provider to notice those declarations. Tests replace process-local kernel/application/provider objects between rounds and also exercise the private HTTP transport against one SQLite authority.

Conversation also declares two read-only web capabilities: `read_public_url` for validated public HTTPS targets and `search_public_web` for explicit search intent. Deployment configuration may narrow either capability. The application selects capabilities from the current transient turn, while the shared provider transport maps them to managed Gemini tools after invocation evidence and the application-access barrier. Retrieved content remains transient and untrusted; the reply may project bounded citations, but URL-bearing observations cannot enter durable continuity state. Client-visible failures carry a bounded ownership scope so application/provider/transport failures remain distinguishable from sudofx authority failures.

Handoff is a second native sudofx application with materially different semantics. It reads generic governed work through public kernel context, creates bounded export views, deterministically scores returned packet-grounding evidence, and commits new evaluations through `apply_application` under `app:handoff`. Historical `record_handoff_evaluation` work events remain replay compatibility only and are rejected for new submissions.

WAKE✳︎ is the larger Phase E proof: preserve its domain semantics while moving operational authority onto the same generic sudofx boundary.

## Authority boundary

Applications never become authority merely because they are installed.

The kernel continues to own:

- authoritative record semantics
- verified replay
- deterministic governance boundary
- atomic transitions
- receipts
- durable revision semantics

The runtime may own:

- bounded context construction
- provider invocation lifecycle
- external effect execution
- recovery
- application discovery/loading

An application may define:

- stable application identity and version
- application state schema
- application actions
- additional deterministic governance rules
- deterministic transition semantics
- bounded context projection
- presentation projection
- requested external-effect capabilities
- application migrations

Before an application may invoke a provider or submit state, the runtime/application host must pass the global sudofx application-access gate. The gate is database-backed, fail-closed when present but unreadable, and generation-fenced so an operator STOP invalidates stale in-flight work at commit time.

An application must not receive:

- an unrestricted SQLite connection
- authority to append record rows directly
- a bypass around kernel governance
- hidden provider/session memory as required state
- a second durable operational store
- undeclared external-effect authority

## Intended call shape

```text
human / schedule / integration / model
              │
              ▼
        application intent
              │
              ▼
      sudofx runtime boundary
              │
      bounded context / effect
              ▼
           provider
              │
         untrusted result
              ▼
     application proposal shape
              │
              ▼
      deterministic governance
              │
              ▼
       kernel transition
              │
              ▼
     authoritative database
              │
              ▼
      derived presentation
```

The application may interpret domain meaning. It may not redefine which component owns durable truth.

## Application contract: first version

Do not freeze a broad framework before two materially different applications exercise it. The contract tests now exercise both a counter-style transition and an append-only notes-style transition through the same kernel seam.

The first contract should therefore expose the smallest useful concepts:

### Identity

Every application has a stable ID and version.

Identity is provenance and compatibility information. Version never grants authority.

### State namespace

Application-owned durable state must occupy an explicit namespace so domain keys cannot collide accidentally with kernel-owned state.

The namespace is semantic, not a separate database.

### Action registration

Applications may define domain action names, but registration alone never makes an action legal.

The v1 implementation uses one generic kernel action, `apply_application`. The application host supplies identity, version, action input, and a candidate next state; kernel governance independently reruns the registered deterministic policy before acceptance. Small applications may persist the verified resulting JSON state directly. Large applications may instead choose compact event-log storage: accepted events persist only the governed action input plus a digest of the deterministic result. Generic sudofx replay remains possible without the application installed; reconstructing that application's domain state requires the matching application version, which replays the compact inputs and verifies every stored result digest. This prevents whole-state duplication while making same-version policy drift visible.

For each application action, all of the following must exist together:

1. serialized boundary shape
2. deterministic governance validation
3. generic replay of the verified result
4. tests proving acceptance and rejection behavior

### Context projection

Applications determine which domain state is useful to a provider or human-facing interaction.

The runtime supplies only the resulting bounded projection.

Projection code cannot mutate authority and must disclose material omission when compression is used.

### Effect capabilities

Applications request named effect capabilities.

An effect adapter receives only the minimum material required for that effect. It does not receive general database authority.

`InvocationLifecycle.invoke()` owns the generic ordering rule: durable request/attempt evidence and any caller-supplied durability barrier precede the irreversible external call. A barrier failure is recorded as pre-effect evidence, not misclassified as a provider outcome. Applications may classify provider-specific exceptions into generic temporary/quota/provider failure categories without importing those provider types into sudofx.

Deployment permissions independently grant a subset of declared capabilities. Declaration alone never grants effect authority, and configuration can narrow authority but cannot silently widen it.

### Presentation

Applications may render browser or API views from verified database-derived projections.

Presentation output is disposable and must never be read back as authority.

## WAKE✳︎ boundary

WAKE✳︎ should retain ownership of concepts such as:

- research topics and seed questions
- projects and notebooks
- beliefs and evidence rules
- retrieval and source qualification
- publication/editorial policy
- Bob
- inquiry-drive experiments
- research-specific scheduling and collection policy

sudofx should provide the generic substrate beneath those concepts:

- durable governed transitions
- provenance
- replay
- bounded context
- invocation/effect lifecycle
- recovery
- application isolation

The migration succeeds when WAKE✳︎ can change substantially without requiring new research-specific assumptions in the sudofx kernel.

## Removal tests

Two removal tests distinguish applications from extensions.

### Extension removal

Removing an optional extension should leave the owning application semantically valid. Historical records may retain provenance that the extension once existed.

### Application removal

Removing an application may make that application's domain state uninterpretable until the application is restored, but it must not corrupt the generic sudofx record or redefine kernel replay semantics.

Application-specific historical payloads therefore need explicit identity/version provenance.

For compact event-log applications, removal leaves the generic event envelope replayable and auditable, while domain materialization is intentionally unavailable until the matching application code is restored.

## Why this boundary is intentionally small

WAKE✳︎ accumulated useful ideas and domain complexity at the same time. sudofx must not repeat that growth pattern at the engine layer.

A feature belongs below the application boundary only when at least one of these is true:

- durable governed continuity requires it regardless of domain;
- multiple applications need the same semantic contract;
- leaving it to applications would permit bypass of the authority boundary.

Everything else stays above the kernel until evidence proves otherwise.
