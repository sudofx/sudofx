# sudofx implementation guidance

This repository is built to survive turnover in models, vendors, maintainers,
and active context. Source code is therefore not merely an executable artifact.
It is also part of the durable explanation of why the system is safe to change.

## The comment-heavy code-cementing rule

Consequential implementation should target approximately two lines of useful
commentary for every logical line or small block of executable behavior. This
is a design-density target, not a repository-wide mechanical line quota.

Apply the target to authority, governance, storage, replay, recovery, provider,
concurrency, and lifecycle boundaries. A short expression there may need a long
explanation of its contract. Routine argument plumbing, obvious rendering, data
fixtures, and declarative fields may use one shared comment block. Never add
filler merely to satisfy arithmetic.

Commentary includes module docstrings, class and function docstrings, and inline
comments that preserve material engineering intent. It does not include copied
requirements, filler, syntax narration, disabled code, generated prose, or
repetition whose only purpose is inflating the ratio.

## What comments must cement

Prefer comments that answer questions the code cannot answer by itself:

- Which component owns authority here?
- Which state is durable, derived, untrusted, or merely presentational?
- What invariant must remain true after this operation?
- What happens after interruption, stale input, duplication, or partial failure?
- Why is the implementation stricter or smaller than an obvious alternative?
- Which attractive simplification would violate the product boundary?
- What evidence proves this behavior, and what does that evidence not prove?
- What would a future maintainer be tempted to change incorrectly?

Public interfaces must document inputs, outputs, rejection behavior, atomicity,
and ownership. Storage code must document ordering, replay, integrity, and
recovery. Governance code must document why each rule exists. Provider code
must document the trust boundary. Presentation code must distinguish projection
from authority. Tests must name the durable guarantee they protect and explain
the failure mode that would matter.

## What comments must not do

Do not restate visible syntax, speculate about nonexistent behavior, claim that
a local test proves an external system, or preserve obsolete implementation
history. Remove or revise a comment in the same change that invalidates it.

Comments are not a substitute for small functions, meaningful names, explicit
types, deterministic governance, or tests. If an implementation needs prose to
hide needless complexity, simplify the implementation first.

## Change discipline

Every code change must preserve or improve explanatory density in the touched
logical area. New modules start with an architectural docstring. Public
functions receive contract-level documentation. New governance rules state the
harm they prevent. New tests state the invariant under proof. Deeply consequential
logic should approach the 2:1 target; simple glue should remain concise.

Review comments as executable design constraints. A change is incomplete when
the code works but its authority, invariants, or failure semantics would need to
be rediscovered by the next maintainer.


## Database-first operational truth

The SQLite database is the single authoritative source of durable operational
truth. Events, proposals, governance decisions, transitions, receipts,
provenance, commitments, and derived state belong there rather than in persistent
JSON, JSONL, Markdown, HTML, workflow artifacts, or generated Pages output.

Flat files are appropriate for source, configuration, migrations, tests, and
temporary exports. Human-readable pages, APIs, reports, feeds, proof artifacts,
and static sites are projections generated from database queries or bounded
runtime evidence. Never create a second persistent state model merely to make a
view easier to render.

Keep storage contracts backend-independent. SQLite is the initial implementation,
not a semantic dependency of the kernel; a future PostgreSQL or other backend
must be able to replace it without changing proposal, governance, transition,
receipt, or context meaning.

Principle: one authoritative database -> everything else is a view, query, or
export.


## Current architectural vocabulary

Use these terms in code, comments, reviews, and documentation:

- **kernel** — smallest durable authority boundary
- **runtime** — execution, context, invocation, recovery, and effect coordination
- **application** — complete domain behavior built on sudofx
- **extension** — optional capability layered onto the engine or an application
- **plugin** — only a technical loading/packaging mechanism if dynamic installation is actually implemented

Domain-specific policy belongs above the sudofx kernel in applications.

## Presentation is read-only authority-wise

Generated HTML, Pages publication, reports, workflow summaries, browser state, and exported JSON/Markdown are projections or transport.

A presentation-only path may reconstruct a disposable local view of database state, but it must not commit migrations, advance revisions, write receipts, or otherwise gain authority merely because rendering encountered older stored bytes. Durable schema migration belongs to an authorized stateful path.

## Documentation synchronization

When a change materially alters authority, storage, replay, application semantics, operator workflows, or migration status, update the canonical documentation in the same work:

- `README.md` for the repository-level current picture
- `docs/STATUS.md` for implementation status and current frontier
- `docs/ARCHITECTURE.md` for implemented authority boundaries
- `docs/APPLICATION_ARCHITECTURE.md` for application contract changes

Historical experiment notes may remain historical, but they must be clearly labeled so they cannot be mistaken for current operating instructions.
