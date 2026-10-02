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

Owns transition execution.

It accepts structured proposals, invokes governance, writes receipts, and maintains atomicity.

### Governance

Owns deterministic admission rules.

The model that proposes a change does not decide whether the change is valid.

### Provider adapter

Owns transport to an intelligence provider.

It receives bounded context and returns a provider-neutral structured proposal. It receives no SQLite path, GitHub credentials, kernel mutation callback, or governance authority.

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

Owns presentation only.

HTML, JSON proof artifacts, runner disposition files, and telemetry are generated views. They are never read back as authoritative work state.

### GitHub Actions operator boundary

GitHub Actions owns manual runtime control. Pages remains public and unauthenticated.

A dedicated internal latch workflow provides durable enabled/disabled state. Start enables the latch and dispatches one runtime cycle. Stop disables the latch before cancelling active cycles. The latch cannot edit work items, receipts, source, secrets, or SQLite state.

## Application boundary

Applications sit above the kernel and runtime. They own domain meaning, not durable authority.

The implemented contract in `src/sudofx/applications.py` provides stable application identity/version, registered actions, deterministic policy re-evaluation, namespaced state, explicit migration failure, and optional compact event-log storage. A provider or application cannot commit arbitrary next state merely by supplying it; governance reruns the registered application policy before acceptance.

The small `conversation` application proves the boundary with human-origin and assistant-origin turns. Tests replace application/runtime/provider objects between rounds and reconstruct the next turn from SQLite alone.

WAKE✳︎ is the first substantial migration onto this boundary. WAKE-specific research semantics remain application policy in the separate WAKE repository and must not become kernel rules.

## Presentation boundary

Presentation is strictly derived.

Pages, reports, workflow summaries, browser state, JSON exports, and Markdown exports may be generated from verified state, but they do not acquire mutation authority. A publish-only path may migrate a disposable local copy enough to interpret it, but durable schema migration/checkpointing belongs to an authorized stateful path.

This distinction prevents a renderer from becoming an accidental database writer.

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
publish observer
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
