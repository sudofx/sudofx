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
- **[WAKE✳︎](https://github.com/sudofx/wake)** — an experimental research application built around durable evidence, obligations, correction, and externalized continuity. Its Phase E architectural migration onto the sudofx application boundary is complete.
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
- a privacy-bounded governed Conversation application that survives process replacement from SQLite alone
- a runnable private/local chat transport whose visible transcript stays transient while SQLite stores governed observations
- an encrypted GitHub Actions transport seam for a future authenticated cloud gateway
- GitHub Pages as a lightweight, read-only public shell
- a separate historyless `sudofx-live` branch for disposable public-safe metrics and technical projections, so state changes do not rebuild Pages
- phone-first operator workflows and explicit Start/Stop control
- quarantined continuity/overnight/manual-handoff experiments under `experiments/`
- WAKE✳︎ Phase E architectural migration complete on the separate `sudofx/wake` repository's `master`: sudofx owns operational authority/runtime primitives while WAKE retains research policy

The October 2 public product-surface contract is complete and preserved in [100226-WEBSITE-CONTRACT.md](100226-WEBSITE-CONTRACT.md). The completed A–E architecture contract remains preserved in [100126-CONTRACT.md](100126-CONTRACT.md) as historical evidence.

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

The first small non-WAKE application is `applications/conversation/`.

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

`applications/conversation/server.py` now provides the smallest complete end-to-end chat path: a mobile-first browser talks to a private same-origin server, every provider invocation starts fresh, and SQLite retains only governed fingerprints/observations rather than raw transcript text. The public Pages shell exposes the Conversation UI but remains disabled until an authenticated private gateway is actually configured; it does not fall back to browser credentials or PATs.

Tests also preserve the earlier fresh-process continuity proof. The browser is transport and presentation, not memory.

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
docs/                   current architecture/status plus historical design notes
AGENTS.md               implementation and documentation discipline
100126-CONTRACT.md      completed A–E architecture contract
100226-WEBSITE-CONTRACT.md completed public product-surface contract
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

Phases A–E are complete at their stated architectural exit conditions. Multiple governed conversation rounds survive separate Python interpreter replacement from SQLite alone, and WAKE's operational authority/runtime primitives now sit on sudofx while WAKE retains research policy. The reusable package has also completed its current hardening pass: provider execution is runtime-only, experiment-specific packet/prompt machinery is quarantined outside `src/sudofx`, governed namespaces are sealed, and duplicate/dead execution surfaces are retired. The next major step should begin from a new explicit contract or product frontier rather than quietly expanding the kernel.

The October 2 public product-surface contract is complete: the homepage, application discovery, dedicated technical/metrics surfaces, shell/live-data split, accessibility/performance guardrails, and system light/dark support are implemented and deployed. The next substantial product or kernel frontier should begin from a new explicit contract.

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
