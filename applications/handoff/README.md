# Handoff application

Handoff is a sudofx application for testing whether bounded governed context can
be carried to a fresh intelligence and returned as auditable evidence.

It replaces the former `experiments/manual_handoff/` ownership boundary.

## Authority

SQLite remains the only operational authority.

The generic sudofx work lifecycle owns objectives, accepted results, constraints,
and open obligations. Handoff owns only handoff-domain semantics:

- target registration;
- bounded packet construction;
- human-transport prompt construction;
- deterministic packet-grounding scoring;
- durable handoff evaluation evidence;
- compact disposable evaluation projections.

New evaluations are stored under `app:handoff` through
`ApplicationHost.submit()`. They are no longer generic work operations.

Historical `record_handoff_evaluation` events remain replayable as compatibility
evidence so existing databases are not invalidated. New code must not create
those legacy operations.

## Removal boundary

Removing this application may make handoff-domain state uninterpretable, but it
must not corrupt generic sudofx replay or the underlying work items.

Packet JSON, text prompts, public projections, and browser/manual transport are
views or transport only. They are not additional state stores.
