<div align="center">

# Hi, I'm Rob 👋

### I build systems for durable, accountable work across models, vendors, people, and time.

**Current focus:** externalized context, governed AI workflows, replayable state, and systems that stay understandable after the intelligence using them changes.

</div>

## About me

I’m interested in a simple but difficult problem: **how do useful ideas, decisions, evidence, and obligations survive when the model, vendor, device, maintainer, or session changes?**

Most of my current work explores that question by keeping authority outside the model, preserving provenance, and making continuity reconstructable instead of relying on hidden memory.

## Projects

- **[sudofx](https://github.com/sudofx/sudofx)** — a governed engine for durable work across interchangeable intelligences. SQLite is authoritative; models propose and the system governs.
- **[lab](https://github.com/sudofx/lab)** — my Docker lab and infrastructure sandbox.

Earlier projects: [pure-bootstrap](https://github.com/sudofx/pure-bootstrap) · [python-digitalocean-backup](https://github.com/sudofx/python-digitalocean-backup)

---

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

## Current status — October 10, 2026

The project has moved beyond the original continuity proof into a reusable engine/application architecture.

Implemented on `master`; the recent WAKE-derived kernel changes are local and
awaiting focused validation:

- SQLite as the single authoritative operational store
- deterministic governance and atomic transitions
- append-only accountable receipts and provenance
- verified replay plus explicit full-history audit paths, including a separate
  deterministic reducer for committed application events when live eligibility
  has tightened
- schema-v12 compressed event/projection storage with verified prior-schema
  migration that preserves decoded event bytes and history hashes
- read-only current-format record opening for inspection paths that must not
  initialize or migrate authority
- durable provider invocation lifecycle and resource accounting
- bounded context with explicit omission evidence
- provider-neutral execution boundaries
- application identity, versioning, actions, policy re-evaluation, migration boundaries, and event-log storage
- a database-backed global application access kill switch with generation fencing for in-flight work
- a privacy-bounded governed Conversation application that survives process replacement from SQLite alone
- a runnable private/local chat transport whose visible transcript stays transient, whose one-exchange process-local buffer resolves adjacent references, and whose SQLite authority stores governed observations and exact human-authorized commitments
- explicit read-only Conversation URL and public-web search capabilities with bounded citations and private-target rejection
- an encrypted GitHub Actions transport seam for a future authenticated cloud gateway
- a first-class Handoff application for bounded fresh-intelligence packets and governed cross-provider grounding evidence
- GitHub Pages as a lightweight, read-only public shell
- a separate historyless `sudofx-live` branch for disposable public-safe metrics and technical projections, so state changes do not rebuild Pages
- phone-first operator workflows and explicit Start/Stop control
- quarantined continuity/overnight experiments under `experiments/`; the former manual-handoff experiment has migrated to `applications/handoff/` with compatibility shims retained temporarily

The public shell, provider execution, and application observability are implemented.

See [docs/STATUS.md](docs/STATUS.md) for implementation status,
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for authority boundaries, and
[docs/APPLICATION_ARCHITECTURE.md](docs/APPLICATION_ARCHITECTURE.md) for the application contract.

## Authority model

```text
master
  └─ source, tests, workflows, documentation

sudofx-state
  └─ authoritative SQLite checkpoint

kernel
  └─ governance, transitions, receipts, replay

runtime
  └─ bounded context, invocation lifecycle, provider/effect coordination

applications
  └─ domain behavior built above the kernel

GitHub Actions / providers / browser
  └─ replaceable execution and presentation infrastructure
```

Only the SQLite record is operational truth.

Pages, workflow state, JSON, Markdown, reports, summaries, handoff packets, and browser state are views, transport, evidence, or exports. They must never become a competing authoritative store.

## Application kill switch

sudofx owns a global application-access latch in authoritative SQLite. The operator can STOP or RESTORE connected-application access through the dedicated **sudofx — application access** workflow. STOP does not shut down sudofx itself: inspection, recovery, and operator work remain available while application-origin work is denied.

Each access transition advances a generation token and is recorded in an independently hash-chained operational audit. Application work captures that generation before execution and the kernel rechecks it inside the commit transaction, so work that began before a STOP/RESTORE boundary cannot commit afterward using stale authority. Emergency STOP deliberately has no full-test-suite dependency and may preempt ordinary serialized authority work; RESTORE is stricter and requires the full test suite to pass before access is reopened. Connected deployments with separate databases must consult the central sudofx latch before beginning provider work.

## Reusable matrix extension

sudofx now includes an opt-in deterministic matrix contract in `src/sudofx/matrix.py`. The canonical `continuity@1` definition restores the original 7×7×7 continuity experiment: seven semantic lenses × seven exposure modes × seven pressure modes = 343 stable cells.

The matrix is an **extension**, not a new authority surface. It owns immutable coordinate definitions, stable IDs, definition digests, and deterministic traversal. It does not invoke providers, write SQLite, schedule work, or decide what an application result means. An application may use a coordinate ID inside its own deterministic actions and persist campaign progress/results through its ordinary governed `app:*` state. This keeps one authoritative database while allowing Conversation, Handoff, or future applications to reuse the same experiment grammar without being modified by sudofx.

Changing the meaning of an already-versioned coordinate requires a new matrix version rather than rewriting v1.

## Applications, not plugins

A complete domain system built on sudofx is an **application**.

Applications may define domain state, deterministic policy, context projection, presentation, and requested capabilities. They may not bypass governance, write arbitrary database state, create an independent authoritative event store, or gain authority merely because their code is installed.

Conversation and Handoff are native sudofx applications exercising different boundaries: privacy-bounded stateless chat and portable fresh-intelligence continuity testing.

## Governed conversation proof

The governed conversation application is `applications/conversation/`.

Its flow is:

```text
human input
  ↓
governed human-origin application transition
  ↓
SQLite
  ↓
bounded database-derived context
  ↓
provider invocation
  ↓
governed assistant application transition
  ↓
SQLite
  ↓
derived browser projection
```

`applications/conversation/server.py` now provides the smallest complete end-to-end chat path: a mobile-first browser talks to a private same-origin server, every provider invocation starts fresh, and SQLite retains governed fingerprints, verified observations, and explicit commitments rather than raw transcript text. The server separately holds only the immediately previous successful exchange in volatile memory so adjacent references remain conversational; restart or Clear removes that buffer. Referential follow-ups may revisit public URLs from that immediately previous human message after the ordinary target validation, while unrelated turns inherit no web capability. Assistant display numbers come from committed turn counts. Exact suffix commitments are enforced deterministically; semantic response instructions remain visible governed state and must quote the human turn that authorized them. The public Pages shell exposes the Conversation UI but remains disabled until an authenticated private gateway is actually configured; it does not fall back to browser credentials or PATs.

Tests also preserve the earlier fresh-process continuity proof. The browser is transport and presentation, not memory.

Conversation now also opts into the shared `continuity@1` matrix extension when explicitly enabled. A governed matrix campaign records only version/digest, completed coordinate IDs, verdicts, and optional evidence digests in Conversation's existing SQLite application state. While active, the next deterministic matrix coordinate is added to the bounded fresh-provider context; ordinary Conversation turns contain no matrix context until a campaign is started. The private same-origin service exposes start/result/stop controls and reports bounded progress without creating another state store.

## Database-first storage

The database is the single authoritative source of operational truth.

Durable events, proposals, governance decisions, transitions, receipts, provenance, commitments, application state, invocation lifecycle, and derived authoritative state belong in SQLite.

**One authoritative database → everything else is a view, query, or export.**

SQLite is the current implementation, not the semantic contract. A future PostgreSQL or other backend must be able to replace it without redefining proposal, governance, transition, receipt, provenance, or application semantics.

The current `sudofx-state` Git ref is public. Do not place private or identifying durable material in it until authority is moved to private storage.

## Repository structure

```text
src/sudofx/             reusable engine: kernel, storage, governance, runtime, applications
applications/           concrete application packages; each application owns its own directory
scripts/                shared GitHub/runtime/recovery and transport utilities
web/                    lightweight public-site shell; live data is fetched from sudofx-live
.github/workflows/      CI, operator control, conversation, runtime, Pages
tests/                  invariant, replay, failure, lifecycle, and application proofs
experiments/            quarantined continuity and handoff experiment machinery
docs/                   current architecture and implementation status
AGENTS.md               implementation and documentation discipline
100226-WEBSITE-CONTRACT.md public product-surface specification
```

## Local verification

Python 3.11+:

```bash
python -m venv .venv
.venv/bin/pip install -e .
PYTHONPATH=src:. .venv/bin/python -m unittest discover -s tests -v
```

### Local Docker development

`./scripts/sudofx_runner start` builds the `sudofx-dev:local` development image
and starts the `sudofx.app` container. The checkout is mounted read/write at
`/workspace`, so edits, branches, commits, and pushes operate on this host repo.
The local `.env` is supplied to the container process, and host `~/.ssh` is
mounted read-only when present. Pushes to this repo's `origin` use SSH; fetches
retain the configured remote transport. No source, credential,
or database file is copied into the image.

Use `./scripts/sudofx_runner stop` to stop the container while retaining its
disposable home volume. `./scripts/sudofx_runner reset` recreates it and removes
that home volume; it preserves the checkout, `.env`, and any `data/` SQLite
record in the repository. The pre-existing `sudofx` container is independent.

Basic kernel commands remain available through the `sudofx` CLI.

## Current frontier

The core loop, application boundary, and database-derived continuity mechanics are implemented.

Multiple governed conversation rounds survive separate Python interpreter replacement from SQLite alone. Provider execution is runtime-only, experiment-specific packet/prompt machinery stays outside `src/sudofx`, and governed namespaces are sealed. The public shell presents application discovery, technical evidence, metrics, and system light/dark support.

The next discussion concerns the sudofx API and extensible application design. No new API design is selected by this cleanup.

The larger experiment remains open:

> **Can enough governed context survive model, vendor, session, device, person, and time replacement that useful work continues without hidden continuity?**

## What sudofx is not

The kernel is deliberately not:

- an autonomous-agent authority
- a chatbot memory layer
- a model identity preservation system
- a dashboard as system of record
- a pile of persistent flat-file state
- a provider-specific orchestration framework

## License

sudofx is licensed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
