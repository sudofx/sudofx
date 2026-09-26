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
