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
- **[WAKE✳︎](https://github.com/sudofx/wake)** — an experimental research application built around durable evidence, obligations, correction, and externalized continuity. It is currently migrating onto the sudofx application boundary.
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

## Current status — October 2, 2026

The project has moved beyond the original continuity proof into a reusable engine/application architecture.

Implemented and exercised on `master`:

- SQLite as the single authoritative operational store
- deterministic governance and atomic transitions
- append-only accountable receipts and provenance
- verified replay plus explicit full-history audit paths
- durable provider invocation lifecycle and resource accounting
- bounded context with explicit omission evidence
- provider-neutral execution boundaries
- application identity, versioning, actions, policy re-evaluation, migration boundaries, and event-log storage
- a governed conversation application that survives process replacement from SQLite alone
- a dedicated GitHub Actions conversation input surface
- GitHub Pages as a derived, read-only projection
- phone-first operator workflows and explicit Start/Stop control
- quarantined continuity/overnight/manual-handoff experiments under `experiments/`
- WAKE✳︎ migration work underway as a sudofx application in the separate `sudofx/wake` repository

The active execution direction is defined by [100126-CONTRACT.md](100126-CONTRACT.md).

See [docs/STATUS.md](docs/STATUS.md) for the phase-by-phase state,
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

## Applications, not plugins

A complete domain system built on sudofx is an **application**.

Applications may define domain state, deterministic policy, context projection, presentation, and requested capabilities. They may not bypass governance, write arbitrary database state, create an independent authoritative event store, or gain authority merely because their code is installed.

WAKE✳︎ is the first substantial application migration. The older broad “WAKE as plugin” framing is retired; [docs/PLUGIN_ARCHITECTURE.md](docs/PLUGIN_ARCHITECTURE.md) is retained only as a historical redirect.

## Governed conversation proof

The first small non-WAKE application is `applications/conversation.py`.

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

Tests replace the kernel, application host, and provider process between turns and reconstruct the next turn only from SQLite. The public projection links to the dedicated `conversation.yml` workflow for one-message browser input.

The browser is transport and presentation, not memory.

## Database-first storage

The database is the single authoritative source of operational truth.

Durable events, proposals, governance decisions, transitions, receipts, provenance, commitments, application state, invocation lifecycle, and derived authoritative state belong in SQLite.

**One authoritative database → everything else is a view, query, or export.**

SQLite is the current implementation, not the semantic contract. A future PostgreSQL or other backend must be able to replace it without redefining proposal, governance, transition, receipt, provenance, or application semantics.

The current `sudofx-state` Git ref is public. Do not place private or identifying durable material in it until authority is moved to private storage.

## Repository structure

```text
src/sudofx/             reusable engine: kernel, storage, governance, runtime, applications
applications/           concrete sudofx applications; conversation is the first small proof
scripts/                provider, GitHub runtime, recovery, conversation adapters
.github/workflows/      CI, operator control, conversation, runtime, Pages
tests/                  invariant, replay, failure, lifecycle, and application proofs
experiments/            quarantined continuity and handoff experiment machinery
docs/                   current architecture/status plus historical design notes
AGENTS.md               implementation and documentation discipline
100126-CONTRACT.md      active execution direction
```

## Local verification

Python 3.11+:

```bash
python -m venv .venv
.venv/bin/pip install -e .
PYTHONPATH=src:. .venv/bin/python -m unittest discover -s tests -v
```

Basic kernel commands remain available through the `sudofx` CLI.

## Current frontier

The core loop, application boundary, and database-derived continuity mechanics are implemented.

The immediate engineering frontier is to finish hardening the Phase D human interaction proof, then continue Phase E by moving WAKE✳︎ domain execution onto sudofx without importing research-specific semantics into the kernel.

The larger experiment remains open:

> **Can enough governed context survive model, vendor, session, device, person, and time replacement that useful work continues without hidden continuity?**

## What sudofx is not

The kernel is deliberately not:

- an autonomous-agent authority
- a chatbot memory layer
- a model identity preservation system
- a dashboard as system of record
- a pile of persistent flat-file state
- WAKE✳︎ with renamed modules
- a provider-specific orchestration framework

## License

sudofx is licensed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
