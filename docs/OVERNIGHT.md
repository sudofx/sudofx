# Overnight evolving continuity

## Purpose

This experiment asks a narrower question than "does Gemini repeat the same answer?"

It asks whether a sequence of **fresh Gemini instances** can preserve and improve
useful continuity when each instance receives only a bounded governed residue of
what came before.

The North Star is unchanged: durable, portable, governed context must survive
replacement of models, vendors, platforms, agents, people, and time.

## Authority boundary

SQLite remains the single authoritative operational record.

A Gemini response does **not** become accepted project progress. Each model
proposal is evaluated only on an isolated SQLite snapshot. Production work
remains unchanged by model output.

After a successful probe, sudofx records a different fact in SQLite:

> this fresh model produced this response under this trial phase and context digest

That durable observation is evidence of model behavior, not evidence that the
model's claims are true.

## What the next Gemini receives

The next instance receives:

- the current governed work objective, constraints, and frontier;
- only the newest accepted work milestone;
- counts and digests for omitted accepted history;
- zero receipt prose;
- the most recent Gemini observation, explicitly labeled **untrusted**;
- a chained digest and count acknowledging older observations without exposing a transcript;
- one deterministic experiment lens.

Older Gemini prose remains recoverable from SQLite event history but does not
accumulate in provider context.

## Rotating lenses

The experiment rotates deterministically through five lenses:

1. **reconstruction** — recover objective, supported history, frontier, next action;
2. **compression** — test what meaning survives bounded context;
3. **missing context** — identify what cannot safely be inferred;
4. **authority boundary** — distinguish durable authority from derived/model material;
5. **adversarial integrity** — challenge plausible self-authorizing or authority-laundering claims.

Then the sequence repeats against a new inherited observation.

The model does not choose the next phase.

## Relation to WAKE✳︎

WAKE✳︎ provided the useful architectural precedent: durable state stays complete,
while each fresh invocation receives a bounded working representation and a
changing attention target.

sudofx applies that lesson to continuity itself. Instead of rotating research
topics, it rotates semantic-continuity lenses while carrying forward only
governed observational residue.

## Start / Stop

The existing authenticated website control remains the operator boundary.

**Start** records operator intent before the first Gemini call. Successful cycles
chain automatically. **Stop** ends the chain and records the durable obligation
to await another explicit Start.

A stray workflow dispatch cannot bypass a durable stopped state.

## What an overnight run can and cannot show

An overnight run can provide evidence about:

- drift across fresh instances;
- compression tolerance;
- missing-context discipline;
- authority-boundary preservation;
- susceptibility to plausible adversarial claims;
- whether a prior model response helps or contaminates the next reconstruction.

It cannot by itself prove long-term vendor interchangeability, semantic truth,
or production readiness. Claude/DeepSeek manual handoffs remain useful external
comparison probes while Gemini supplies the automated free-provider baseline.
