# Project history

This document preserves the consequential decisions that shaped sudofx: the
constraints that became visible, the choices made in response, and the open
questions those choices left behind. It is a curated engineering narrative,
not an exhaustive commit log, a personal biography, or a source of operational
truth.

Current behavior belongs in the implementation and `ARCHITECTURE.md`. Current
progress belongs in `STATUS.md`. Durable work state belongs in the authoritative
database. When this history disagrees with any of those owners, this narrative
must be corrected rather than treated as authority.

## September 26, 2026 — From an idea to a governed kernel

### The constraint

Work performed with an intelligence was too easy to bind to one conversation,
one provider, or one model's hidden continuity. A successor could inherit prose,
but it could not reliably distinguish durable state from conversational residue,
nor could anyone audit why a proposed change had been accepted.

WAKE✳︎ had explored continuity and model-supported work before sudofx. That
experience supplied useful evidence, but sudofx needed a smaller center: a
system whose correctness did not depend on preserving the intelligence that
helped operate it.

### The decision

sudofx began as a governed-work kernel with explicit separation between:

- an append-only SQLite record that owns durable operational truth
- bounded context assembled for one work item
- interchangeable intelligences that may propose but cannot mutate
- deterministic governance that admits or rejects proposals
- atomic transitions and hash-linked receipts that make outcomes replayable

The name and public identity were linked to the earlier WAKE✳︎ experiment, but
the implementation deliberately did not become a general agent platform or a
memory layer for a chatbot.

### The consequence

The first kernel could create and revise durable work, reject stale or invalid
proposals, replay accepted history, and expose a human-readable projection. The
central authority boundary existed before a live external model was introduced,
so provider integration could be tested without giving the provider control.

### The unresolved frontier

Mechanical replay did not yet prove semantic continuity. A record could survive
while still omitting the intent a fresh intelligence would need to continue
useful work.

## September 26, 2026 — Making storage replaceable without weakening authority

### The constraint

SQLite was the correct durable store for the experiment, but letting kernel
contracts depend on SQLite details would turn an implementation choice into a
permanent product boundary. Cloud execution also needed a durable checkpoint
without creating a second state model in files, workflow artifacts, or Pages.

### The decision

The kernel was decoupled from the concrete SQLite backend while the database
remained the sole owner of operational truth. Cloud runs restore and checkpoint
that database on a dedicated state branch. JSON, Markdown, HTML, and workflow
artifacts remain transport, evidence, or presentation only.

### The consequence

Storage can evolve behind the same proposal, governance, transition, receipt,
and context contracts. GitHub can coordinate disposable execution without
becoming the system of record.

### The unresolved frontier

The abstraction has not yet been proven against a second durable backend, and
future migration must preserve ordering, replay, atomicity, and integrity rather
than merely copy the current schema.

## September 26, 2026 — Crossing the external-intelligence boundary

### The constraint

Deterministic fixtures could prove governance mechanics, but not that a fresh
real model could reconstruct a bounded work item and return a useful proposal.
Giving a provider database access or mutation callbacks would have invalidated
the experiment by moving authority back into the intelligence boundary.

### The decision

A provider-neutral process contract was introduced. Gemini became the first
live adapter and received only selected, sanitized context. It returned a
structured proposal through the same governance path used by the deterministic
provider. Continuous experiments run against isolated database snapshots so
test traffic cannot alter authoritative work.

### The consequence

The project demonstrated model replacement, process isolation, governed proposal
handling, and exact snapshot replay with a real external provider. Published
proof can show that the exchange crossed those boundaries without claiming that
the model's answer preserved meaning well enough.

### The unresolved frontier

Provider breadth and long-horizon semantic fidelity remain unproven. Passing
mechanical checks is necessary evidence, not a substitute for judging whether a
candidate understood the objective, history, constraints, and next action.

## September 26, 2026 — Turning continuity into a human-reviewable experiment

### The constraint

The early proof answered whether a model exchange completed, but not whether its
reconstruction was faithful or actionable. Continuity quality needed an explicit
human boundary because an automated score would only encode another model of
meaning and could conceal the judgment under test.

### The decision

The observer gained a structured semantic review covering objective, history,
frontier, constraints, unsupported claims, and actionability. Portable handoff
packets were added so a fresh intelligence could receive bounded governed
context rather than an opaque transcript.

### The consequence

The system can now distinguish transport success from semantic success. A model
candidate may pass governance and still remain pending—or fail—human semantic
review.

### The unresolved frontier

The latest candidate reconstructed the project boundary reasonably well but
offered a circular next step: it proposed that another proposal should be made.
That result supports the mechanics while leaving useful continuation unproven.

## September 26–27, 2026 — The development method became evidence

### The constraint

Development moved repeatedly between a full desktop environment and mobile
devices. Design and implementation were strongest when the desktop coding
surface was available, while mobile review, testing, and continuation depended
on a public webpage and voice-first interaction. The creator also relies on
clear visual cues to understand whether work is running, waiting, complete, or
in need of human judgment.

A public observer created a strict privacy boundary: it could show everything
needed to review the experiment, but it could not expose personal identifiers,
private prompts, secrets, or unnecessary operational metadata.

### The decision

The project adopted a cross-device development harness around the kernel:

- desktop Codex is the primary design and implementation surface when available
- repository and governed state, rather than conversational memory, carry work
  between environments
- the public observer provides the evidence needed for mobile review and QA
- visual state cues are treated as functional operating requirements
- public projections remain non-authoritative and privacy-minimized
- front-end work requires a concrete operational or review need, preventing the
  observer from becoming an open-ended product-design project

GitHub Actions became the disposable execution coordinator, GitHub Pages the
phone-first observer, and a narrowly scoped Cloudflare Worker the authenticated
owner control for starting and stopping the continuation chain.

### The consequence

What began as development accommodation became a direct stress test of the
project thesis. Work now crosses device, interface, session, execution host, and
model boundaries while converging through explicit durable state. The creator
can step away from a workstation without asking a single conversation to carry
the project's continuity.

This harness remains distinct from the kernel. GitHub, Cloudflare, the observer,
and voice-first operation are current means of exercising sudofx; they do not
define the minimum governed-continuity mechanism.

### The unresolved frontier

The workflow proves that the experiment can be operated across devices. It does
not yet prove that governed context is semantically sufficient across long time,
multiple providers, or a change of human maintainer. Public review must also
continue to disclose the strength of its evidence so a live-looking projection
is never mistaken for authoritative state.

## September 27, 2026 — The next experiment

The kernel, external-provider boundary, disposable cloud execution, public
observer, and owner controls are now implemented. The active question is no
longer whether the loop can run.

The next experiment is to record an honest semantic verdict for the current
candidate, place one concrete obligation into the authoritative `handoff-v1`
work item, and ask a fresh intelligence to continue from that bounded record.
The result should be judged on whether it advances the obligation correctly—not
merely whether it can describe sudofx or request another cycle.

That is the threshold between durable context transport and durable useful work.

## September 27, 2026 — Maintenance became an owner-visible contract

### The constraint

The authoritative event record is intentionally append-only, while the public
observer and recovery surface must remain bounded as history grows. A restore
path that accepts an unknown or partially written database would turn routine
maintenance into an authority failure. Recovery copies also needed to be useful
without quietly becoming a second persistent state model.

### The decision

The SQLite header now carries an application identity and ordered schema
version. Restore verifies physical integrity, semantic replay, identity, and
supported version before atomically installing a candidate. Public history is a
bounded projection of the complete event chain. An authenticated owner can
request a verified recovery artifact retained for 30 days, and can inspect the
database size, repository visibility, and state-branch protection posture from
the phone interface.

The GitHub App gained read-only Contents access solely for those diagnostics;
its installation remains limited to `sudofx/sudofx`. The control service still
cannot edit work, receipts, source, secrets, or SQLite state.

### The consequence

The live system now reports a 24,576-byte authoritative database, public
repository visibility, and an unprotected `sudofx-state` branch. Backup and
restore have been exercised through the deployed owner control, while SQLite
remains the only operational authority.

### The unresolved frontier

The continuous runner is stopped. The next useful test is not another empty
cycle: it is one bounded fresh-intelligence cycle against a concrete recorded
obligation, followed by an explicit semantic verdict. Independent private
recovery and a checkpoint-compatible state-branch protection policy remain
future maintenance work before sensitive or materially valuable state is kept.
