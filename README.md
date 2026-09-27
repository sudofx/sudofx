# sudofx

**Durable, accountable work across interchangeable intelligences.**

sudofx is infrastructure for work that must survive changes in models, vendors, processes, people, and time.

The core idea is simple:

> Intelligence can be temporary.  
> The work should not be.

Instead of treating an AI model as the system of record, sudofx keeps authority outside the model.

Models receive bounded context, make proposals, and disappear.

The durable system decides what becomes part of the record.

---

## The Problem

Most AI systems implicitly depend on continuity inside the intelligence performing the work.

That continuity is fragile.

Models change.  
Providers change.  
Context windows end.  
Sessions disappear.  
Prompts evolve.  
People leave.

If the intelligence performing the work is also responsible for remembering what happened, deciding what is valid, and maintaining the authoritative state, continuity becomes difficult to verify.

sudofx separates those responsibilities.

---

## Core Principle

**Models propose. The system governs.**

An intelligence may:

- inspect bounded context
- reason about the current state
- produce a structured proposal

It may not directly mutate authoritative state.

State changes occur through deterministic system-controlled transitions that produce durable receipts.

---

## The Loop

The initial architecture is intentionally small:

```text
Record
  ↓
Context
  ↓
Proposal
  ↓
Governance
  ↓
Transition
  ↓
Receipt
  ↓
Record
```

### Record

The durable history of what happened.

The record is authoritative and append-only.

### Context

A bounded working set derived from the record.

An intelligence receives what it needs for the current operation rather than inheriting an opaque internal memory.

### Proposal

A structured suggestion produced by an intelligence.

A proposal describes a possible change. It does not perform the change.

### Governance

Deterministic rules evaluate whether the proposal is permitted.

Governance lives outside the intelligence producing the proposal.

### Transition

An accepted proposal becomes an explicit state transition.

Rejected proposals leave authoritative state unchanged.

### Receipt

Every meaningful operation produces evidence of what occurred, including enough provenance to reconstruct and audit the transition.

The receipt becomes part of the durable record.

---

## Architecture

sudofx is built around a small set of boundaries:

```text
┌───────────────────────┐
│    Intelligence       │
│                       │
│  receives context     │
│  returns proposal     │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│      Governance       │
│                       │
│ deterministic checks  │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│      Transition       │
│                       │
│ controlled mutation   │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│    Durable Record     │
│                       │
│ state + receipts      │
└───────────────────────┘
```

The intelligence is intentionally replaceable.

The record is not.

---

## Design Principles

### Durable state over model memory

Important state belongs in explicit storage, not inside an active model session.

### Append-only history

History should describe what actually occurred rather than silently rewriting the past.

### Bounded context

Each intelligence invocation receives an explicit working set assembled from durable state.

### Structured proposals

Models communicate intent through defined proposal structures rather than unrestricted state mutation.

### Deterministic governance

Whether a proposal is allowed should not depend on the opinion of the model that produced it.

### Receipts for transitions

Important actions should leave inspectable evidence.

### Replayable state

Current state should be reconstructable from durable history.

### Provider independence

Changing the intelligence provider should not require changing the fundamental work model.

---

## v0.1

The first version exists to prove one thing:

> **Can governed work continue correctly when every intelligence invocation is disposable?**

v0.1 focuses on the smallest system capable of answering that question.

### Included

- append-only durable record
- SQLite persistence
- bounded context construction
- generic structured proposals
- deterministic governance
- controlled state transitions
- transition receipts
- state replay
- provider adapters
- CLI/runtime execution
- deterministic fake intelligence for testing

### Core Tests

The architecture should demonstrate:

**Continuity**

A fresh intelligence can continue work using only the durable record and supplied context.

**Replay**

Current state can be reconstructed from history.

**Substitution**

One intelligence provider can be replaced by another without changing authoritative state.

**Rejection**

Invalid proposals can be rejected without corrupting state.

**Stateless operation**

No individual model invocation needs hidden knowledge from a previous invocation.

---

## What v0.1 Is Not

sudofx v0.1 is deliberately not:

- an autonomous agent platform
- a research system
- a chatbot memory layer
- a multi-agent simulation
- a dashboard product
- a metrics platform
- a general-purpose API platform
- an attempt to preserve a model's identity or personality

Those capabilities may eventually exist around the kernel.

They are not the kernel.

---

## Why Start With a Fake Intelligence?

The first intelligence implementation should be deterministic.

That removes model behavior as a variable while the infrastructure is being tested.

If continuity, governance, receipts, replay, and provider substitution cannot work with a predictable test intelligence, adding an LLM will only make failures harder to diagnose.

Real model providers come after the core invariants are proven.

## Phase 2: External Intelligence

The next phase has begun with a vendor-neutral process adapter. An external
intelligence receives one bounded Context document on standard input and returns
one structured Proposal document on standard output. It never receives the
SQLite record, governance authority, or a mutation callback.

```bash
.venv/bin/sudofx run --work-id launch -- python path/to/provider.py
```

The provider process may be a local model, a thin adapter around a hosted model,
or any other executable that speaks the JSON boundary. Successful output is not
automatically trusted: the proposal still passes through deterministic governance,
the atomic kernel transaction, and the hash-linked receipt record. A timeout,
process failure, or malformed response creates no proposal receipt because no
complete proposal existed to govern.

---

## The Boundary That Matters

sudofx does not require an intelligence to remain alive, remember previous interactions, or maintain an identity.

Every invocation can begin fresh.

What persists is external:

```text
state
history
rules
context
transitions
receipts
```

That separation is the foundation of the project.

---

## Status

sudofx now has an initial runnable Python kernel implementing the full governed loop.

The immediate objective is not feature breadth.

It is proving the kernel:

```text
Record → Context → Proposal → Governance → Transition → Receipt → Record
```

Everything else can grow from there.

## Try the Kernel

The core has no runtime dependencies beyond Python 3.11+.

```bash
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/sudofx init
.venv/bin/sudofx set objective '"prove durable continuity"'
.venv/bin/sudofx show
.venv/bin/sudofx history
.venv/bin/sudofx serve
```

Each `set` or `delete` is a structured proposal evaluated against the revision it
observed. Accepted and rejected proposals both leave hash-linked receipts in the
append-only SQLite record; only accepted proposals advance replayed state.

Run the proof suite with:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Phone Interface

The static interface is designed for GitHub Pages and can be opened locally with
`sudofx serve`. Its phone-first view puts live development status first, then
shows the human-readable context sent to Gemini, Gemini's response, and the
governed outcome. Current work remains visible and the exact accepted/rejected
receipt chain is preserved in a collapsed, searchable history instead of
dominating the operating view.

In GitHub, the `sudofx — operate & publish` workflow is the authenticated control
plane. A manual run accepts a `set` or `delete` proposal, applies deterministic
governance, checkpoints the SQLite record to the `sudofx-state` branch, verifies it,
and publishes the resulting projection to Pages. The browser never holds a GitHub
token and the Pages output is never treated as authoritative state.

### Continuous Mac Runner

The 30-minute GitHub schedule is a backup heartbeat. For immediate sequential
development cycles, run this from a clean `master` checkout with an authenticated
GitHub CLI:

```bash
scripts/run-sudofx-cycles.sh
```

The runner fast-forwards local source, dispatches one bounded cloud cycle, waits
for its exact tokenized run, and reads the verified decision from that run's Pages
artifact. It repeats only when the artifact explicitly says `CONTINUE`; otherwise
it stops at `WAITING FOR YOU`, `FAILED`, or `NO MORE SAFE WORK`. Pass a positive
number to cap the run, for example `scripts/run-sudofx-cycles.sh 3`.

## Durable Work Items

The first product workflow carries an objective across disposable intelligence
invocations. Work items have explicit constraints, accepted results, open
obligations, lifecycle status, and their own revision inside the global record.

```bash
.venv/bin/sudofx work-create launch "Launch the first governed workflow" \
  --constraint "Every transition leaves a receipt"
.venv/bin/sudofx work-advance launch "Defined the lifecycle" \
  --obligation "Complete the interface"
.venv/bin/sudofx work-show launch
.venv/bin/sudofx work-complete launch "Workflow delivered and verified"
```

`work-show` supplies only the selected work item and its receipts, demonstrating
bounded context. A fresh provider can continue from that context without access to
an earlier invocation. Completed work cannot be advanced again; the rejected
proposal remains visible while authoritative state stays unchanged.

## Implementation Commentary

sudofx treats source commentary as part of its continuity infrastructure. Every
module and public function documents its authority, invariants, and failure
semantics; governance, replay, recovery, provider, and concurrency boundaries
receive the deepest treatment. The project targets roughly two lines of useful
commentary per logical line or small block of consequential behavior without
padding obvious plumbing with filler. The durable guidance lives in
[`AGENTS.md`](AGENTS.md).
