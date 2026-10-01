# sudofx

**Durable, accountable work across interchangeable intelligences.**

sudofx is infrastructure for work that must survive changes in models, vendors, processes, people, devices, and time.

> Intelligence can be temporary. The work should not be.

The model is never the system of record. It receives bounded context, returns a structured proposal, and can disappear. Authority remains outside the model.

## North star

Build a durable work boundary that survives replacement of every intelligence participating in it.

The core loop is:

```text
Record → Context → Proposal → Governance → Transition → Receipt → Record
```

**Models propose. The system governs.**

## Current status — September 26, 2026

The initial kernel is implemented and runnable. The project has moved beyond a fake-provider-only proof into live bounded Gemini continuity experiments and an operator-visible cloud runtime.

Implemented and exercised:

- SQLite authoritative record
- append-only, hash-linked receipts
- deterministic governance
- controlled transitions
- state replay
- bounded context construction
- durable work items with revisions, constraints, accepted results, obligations, and lifecycle
- provider-neutral process boundary
- deterministic fake intelligence for testing
- live Google Gemini adapter
- isolated model-continuity probes that cannot mutate authoritative state
- GitHub-hosted durable-state checkpointing on the `sudofx-state` branch
- GitHub Pages observer generated as a disposable projection
- continuous success-only Gemini cycle chaining
- sequential workflow concurrency
- visible stop-on-failure behavior
- local recovery runner
- GitHub-native Start/Stop controls modeled after WAKE
- phone-first observer UI
- handoff export artifacts for bounded continuity experiments

The central architectural claim is therefore no longer hypothetical: a fresh intelligence can receive explicit context reconstructed from durable state and produce a governed proposal without inheriting a previous model session.

What is **not** yet proven is the larger product claim: that this mechanism preserves enough useful context across repeated provider/model replacement, long time spans, and broader real work to become durable infrastructure rather than a successful kernel experiment.

See [docs/STATUS.md](docs/STATUS.md) for the current objective-by-objective assessment and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the implemented boundaries.

## Authority model

sudofx has intentionally separate layers:

```text
master branch
  └─ implementation + workflow definitions

sudofx-state branch
  └─ authoritative SQLite database

GitHub Actions
  └─ disposable execution environment

Gemini / other provider
  └─ disposable intelligence

GitHub Pages
  └─ derived observer projection
```

Only the SQLite record is operational truth.

Pages, JSON proof artifacts, workflow status, reports, and handoff exports are views or transport artifacts. They must never become competing durable state.

## The boundary

An intelligence may:

- inspect bounded context
- reason about current work
- return a structured proposal

It may not:

- write the SQLite record directly
- bypass governance
- decide that its own output is authoritative
- treat Pages or exported JSON as durable truth
- inherit hidden continuity as a requirement

Accepted proposals become explicit transitions. Rejected proposals leave authoritative state unchanged. Meaningful governed operations leave receipts.

## Durable work

The first concrete workflow carries one work item across disposable intelligence invocations.

A work item contains explicit:

- objective
- constraints
- accepted results
- open obligations
- lifecycle status
- revision

A fresh invocation receives only the bounded representation needed for that work item.

```bash
.venv/bin/sudofx work-create launch "Launch the first governed workflow" \
  --constraint "Every transition leaves a receipt"

.venv/bin/sudofx work-advance launch "Defined the lifecycle" \
  --obligation "Complete the interface"

.venv/bin/sudofx work-show launch
.venv/bin/sudofx work-complete launch "Workflow delivered and verified"
```

Completed work cannot be advanced again. Rejection remains visible while authoritative state remains unchanged.

## Continuous Gemini experiment

The `sudofx — continue` GitHub workflow performs one bounded cycle:

1. check out current source
2. run the proof suite
3. restore authoritative SQLite state
4. construct bounded context
5. ask Gemini
6. govern the returned proposal on an isolated verification snapshot
7. publish the human-readable observer
8. dispatch exactly one successor after successful publication

The continuous observer does **not** append every Gemini experiment to durable history. That separation is intentional: an indefinitely running experiment must not manufacture authoritative state merely because a provider returned another answer.

A failed test, provider call, governance step, or deployment stops the chain visibly rather than recursively spending calls in a broken state.

## Phone-first operation

The GitHub Pages interface is a live observer, not an authority surface.

It exposes:

- current execution state
- the bounded context sent to Gemini
- Gemini's response
- the governed interpretation
- accepted/rejected receipt history
- exact workflow/run provenance
- a public manual continuity workbench that can launch/copy a bounded test prompt and score returned JSON locally
- a public contribution path through GitHub Issues for useful manual test results
- direct access to the repository's GitHub Actions operator surface for governed recording and runtime control

## Operator control boundary

GitHub Actions is the operator surface.

The public Pages artifact contains no GitHub credentials, OAuth flow, control backend, or operator session. The status light links directly to this repository's Actions page. **Start** opens the GitHub-native continuation latch and dispatches one runtime cycle; **Stop** closes the latch before cancelling active cycles.

`sudofx-runtime` remains the live-code branch, so development changes on `master` do not alter an already-running experiment until explicitly promoted.


## Database-first storage

The database is the single authoritative source of operational truth.

Durable events, proposals, governance decisions, transitions, receipts, provenance, commitments, and derived state belong in SQLite. Persistent JSON, Markdown, HTML, and Pages artifacts are not alternate stores.

The storage contract should remain backend-independent so SQLite can later be replaced by PostgreSQL or another durable database without changing the kernel's authority model.

**One authoritative database → everything else is a view, query, or export.**

The current `sudofx-state` branch is public because the repository is public.
GitHub authentication protects repository Actions and retained recovery artifacts, not Git
branch visibility. Until state moves to private persistence, durable proposal
content must be treated as public data.

## Repository structure

```text
src/sudofx/             reusable engine: kernel, record, governance, reporting
scripts/                provider adapters, GitHub runtime, recovery runner
.github/workflows/      governed cloud execution and continuation
tests/                  invariant and failure-boundary proofs
experiments/            disposable development and continuity experiments
site/                   generated public projection
data/                   local runtime database path; live cloud authority is checkpointed separately
docs/                   architecture, current status, and design notes
AGENTS.md               implementation and commentary discipline
```

## Try the kernel locally

Python 3.11+ is required.

```bash
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/sudofx init
.venv/bin/sudofx set objective '"prove durable continuity"'
.venv/bin/sudofx show
.venv/bin/sudofx history
.venv/bin/sudofx serve
```

Run the proof suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The local continuous runner remains an operator recovery tool:

```bash
scripts/run-sudofx-cycles.sh
```

Pass a positive integer to cap recovery cycles, for example:

```bash
scripts/run-sudofx-cycles.sh 3
```

## What sudofx is not

The kernel is deliberately not:

- an autonomous-agent platform
- a chatbot memory layer
- a multi-agent simulation
- a model identity preservation system
- a dashboard as system of record
- a pile of persistent JSON state
- a provider-specific orchestration framework

Those things may exist around the kernel. They are not the kernel.

## Current frontier

The immediate frontier is no longer "can the loop run?"

It can.

The frontier is:

> **Can enough governed context survive model, vendor, session, device, and time replacement that useful work continues without either side depending on hidden continuity?**

That is the experiment now underway.

## License

sudofx is licensed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
