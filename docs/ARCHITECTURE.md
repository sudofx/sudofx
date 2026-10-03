# Architecture

## Principle

sudofx separates **intelligence**, **authority**, **execution**, **storage**, and **presentation**.

No disposable component is allowed to become operational truth merely because it is convenient.

## Implemented flow

```text
              bounded Context
SQLite Record ───────────────► Provider
     ▲                            │
     │                            │ structured Proposal
     │                            ▼
     │                       Governance
     │                            │
     │                    accepted / rejected
     │                            ▼
     └──── Receipt ◄──────── Transition
```

For continuous model experiments, governance runs against an isolated verification snapshot. The resulting proof may be published without mutating authoritative SQLite state.

## Authority boundaries

### SQLite record

Owns durable operational truth.

It contains the history from which authoritative state is reconstructed.

### Kernel

Owns governed semantic submission and transition sequencing.

It accepts structured proposals, invokes governance, writes receipts, and maintains atomicity. It does **not** invoke providers. Provider execution belongs to Runtime, so pre-proposal failures can never be confused with governed proposal receipts.

### Governance

Owns deterministic admission rules.

The model that proposes a change does not decide whether the change is valid.

### Provider adapter

Owns transport to an intelligence provider.

It receives bounded context and returns an untrusted result shaped for its application/runtime boundary. It receives no SQLite path, GitHub credentials, kernel mutation callback, or governance authority.

### Global application-access boundary

Authoritative SQLite contains a singleton application-access latch plus an independently hash-chained transition audit. The latch is operational authority and does not advance semantic work revision. Applications capture its generation before work, recheck access immediately before provider effects, and revalidate the same generation inside the serialized kernel commit transaction. STOP therefore invalidates stale in-flight application commits while leaving operator/kernel access available. Emergency STOP intentionally avoids a full-suite dependency and may preempt ordinary work in the serialized authority lane; RESTORE requires the full suite to pass before reopening application access.

Deployments with separate application databases cannot obtain a mathematically atomic distributed fence from a static website or GitHub workflow alone. They must consult the central sudofx authority before beginning new work; WAKE✳︎ performs that check before each cloud cycle. A future always-on central sudofx service can extend the same generation contract across distributed commits.

### Invocation and external-effect boundary

The append-only invocation journal records provider/runtime attempts separately from governed semantic receipts.

`InvocationLifecycle` owns generic request/context/attempt evidence, interruption recovery, and external-effect ordering. `invoke()` runs a caller-supplied durability barrier before the external effect and records provider failure classes without granting the provider authority. Applications may supply an error classifier for provider-specific exceptions; they may not bypass the durability barrier or mutate the journal directly.

This allows WAKE✳︎ to keep Gemini-specific fallback and quota policy above the kernel while reusing the same provider-attempt and effect-ordering contract as other applications.

### GitHub Actions

Owns disposable execution coordination.

Workflow concurrency keeps stateful cloud operations sequential, but workflow ordering is not the final correctness boundary. Revision checks, governance, SQLite transactions, and replay remain authoritative.

### `sudofx-state` branch

Stores the cloud checkpoint of the authoritative SQLite file.

The branch is operational persistence, not a second state model. The database remains the state authority.

The current repository is public, so the branch and every historical database
blob are publicly retrievable. GitHub authentication protects repository Actions and
private recovery artifacts; it cannot make a public Git ref confidential.
Proposal material must remain public-safe until authority migrates to private
durable storage.

Checkpoint creation uses SQLite's backup API, verifies SQLite structure, and
replays the complete event chain before Git receives new database bytes. Restore
downloads to a temporary sibling file, verifies it, removes sidecars belonging
to the replaced identity, and atomically installs the candidate. Missing remote
state is accepted only when the branch is genuinely absent; provider failures
stop instead of initializing empty authority.

### Schema and maintenance

The SQLite header carries a sudofx application ID and an ordered user schema
version. Version zero is the supported legacy shape; unknown identities and
newer schemas fail closed. Storage migrations are checkpointed before a newer
projection is published.

The complete event chain remains append-only. Public presentation materializes
only a bounded recent window and exports content-free health evidence such as
database bytes, event count, replay duration, and integrity status. This bounds
browser growth without deleting the history needed for replay or audit.

An operator may request a verified recovery snapshot through GitHub Actions. GitHub Actions
retains that artifact for 30 days outside Pages. It is a recovery copy, not
authority, and does not replace the need for private independent storage as the
record becomes sensitive or operationally valuable.

### GitHub Pages

Owns the lightweight presentation shell only.

The public shell contains navigation, product explanation, accessibility structure, and client-side rendering logic. It does not restore SQLite or rebuild merely because operational state changed.

Changing public-safe technical/metric data is fetched at runtime from the historyless `sudofx-live` projection branch. That branch is disposable and replaceable from verified state. Neither Pages nor `sudofx-live` is ever read back into governance, replay, recovery, or provider context.

This separates publication cadence from state cadence: website source changes rebuild Pages; state changes refresh only the bounded live projection.

### GitHub Actions operator boundary

GitHub Actions owns manual runtime control. Pages remains public and unauthenticated.

A dedicated internal latch workflow provides durable enabled/disabled state. Start enables the latch and dispatches one runtime cycle. Stop disables the latch before cancelling active cycles. The latch cannot edit work items, receipts, source, secrets, or SQLite state.

## Hardened core boundary

The reusable package under `src/sudofx/` is deliberately experiment-free.

Continuity probes, overnight trials, manual handoff packet/prompt policy, and experiment-specific identities live under `experiments/` or orchestration scripts. CI fails if experiment imports or frozen experiment identifiers leak back into the reusable package.

Provider execution is also sealed away from Kernel. CLI/provider paths route through `Runtime` / `InvocationLifecycle`, which own context-delivery evidence, pre-effect durability barriers, provider-attempt outcomes, and interruption recovery. Application/work namespaces cannot be mutated through generic `set` or `delete`; their dedicated governed actions are the only accepted paths.

Obsolete duplicate surfaces have been retired: the old local cycle runner, the second conversation entry in the broad operator workflow, and uncalled diagnostic CLI flags.

## Application boundary

Applications sit above the kernel and runtime. They own domain meaning, not durable authority.

The implemented contract in `src/sudofx/applications.py` provides stable application identity/version, registered actions, deterministic policy re-evaluation, namespaced state, explicit migration failure, and optional compact event-log storage. A provider or application cannot commit arbitrary next state merely by supplying it; governance reruns the registered application policy before acceptance.

The small `conversation` application proves the boundary with human-origin and assistant-origin turns. Tests replace application/runtime/provider objects between rounds and reconstruct the next turn from SQLite alone.

WAKE✳︎ is the first substantial migration onto this boundary. WAKE-specific research semantics remain application policy in the separate WAKE repository and must not become kernel rules.

## Presentation boundary

Presentation is strictly derived.

The current website uses two disposable layers:

1. **GitHub Pages shell** — versioned HTML/CSS/JavaScript that changes only when the product surface changes.
2. **`sudofx-live` projection** — a bounded, public-safe, historyless JSON view refreshed from verified state by authorized runtime paths.

The browser may combine those layers for display, but neither gains mutation authority. Raw authoritative SQLite is never shipped to the browser. Durable schema migration/checkpointing belongs only to authorized stateful paths.

This distinction prevents a renderer, chart, cache, or live feed from becoming an accidental database writer or a competing system of record.

The older `export_site` monolithic report renderer is retained only for internal/diagnostic exports used by non-Pages workflows. GitHub Pages never deploys that renderer. The canonical public front door is the lightweight shell under `web/`, with changing public-safe state supplied only by `sudofx-live`.

## Continuous chain

`prove-model.yml` is intentionally a single success-only chain.

```text
GitHub Actions Start
        ↓
verify tests
        ↓
restore durable record
        ↓
construct bounded context
        ↓
Gemini proposal
        ↓
isolated governance
        ↓
refresh disposable observer projection
        ↓
dispatch exactly one successor
```

Any failed gate prevents the successor job.

This gives the project continuous experimentation without turning the provider into an autonomous state authority.

## Start/Stop race handling

Stop:

1. disable `sudofx-runner.yml`
2. disable `prove-model.yml`
3. inspect active runs
4. cancel active runs

Disabling first prevents a concurrently finishing run from successfully dispatching another successor.

Start:

1. enable `prove-model.yml`
2. enable `sudofx-runner.yml`
3. dispatch exactly one bootstrap

This recreates one chain rather than many competing loops.

## Database-first rule

Durable records belong in the database.

Persistent JSON, Markdown, HTML, workflow artifacts, and Pages output may describe state, transport state, or export state, but must not duplicate operational truth as another authoritative store.

The intended storage abstraction is:

```text
storage contract
     │
     ├── SQLite now
     └── PostgreSQL / other backend later
```

Backend replacement must not change proposal, governance, transition, receipt, or context contracts.

## Failure semantics

The system favors visible stop over ambiguous continuation.

Examples:

- stale revision → reject proposal
- malformed provider response → no complete proposal to govern
- provider failure → no authoritative mutation
- state checkpoint conflict → fail rather than choose a writer silently
- workflow test failure → no continuation
- deployment failure → no continuation
- anonymous telemetry failure → preserve last projection and disclose weaker evidence

## Why this structure matters

The project is testing a specific proposition:

> useful continuity should be reconstructable from governed external records rather than depending on persistence inside one intelligence.

Everything in the architecture should make that proposition easier to test, falsify, audit, and eventually transport to different infrastructure.
