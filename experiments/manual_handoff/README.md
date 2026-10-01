# Manual handoff experiment

**Status:** development experiment; not sudofx runtime architecture.

This directory contains the human-transported continuity scorer used to test a
bounded sudofx handoff across consumer AI surfaces.

It deliberately sits under `experiments/` because it is evidence-gathering
machinery, not a plugin, application contract, provider abstraction, or durable
authority surface.

## What it does

- parses a human-transported model response;
- binds the response to the exact frozen handoff packet;
- validates test IDs, nonce, vendor, and work identity;
- scores seven deterministic packet-grounding dimensions;
- produces a governance-ready evaluation payload.

A browser-local score is evidence only. Recording an evaluation still crosses
the normal sudofx kernel/governance boundary.

## What it does not own

- SQLite authority;
- kernel transitions;
- application loading;
- provider authority;
- model memory;
- a second event store.

If this experiment disappears, authoritative sudofx history and replay remain
valid. That is the boundary this location is meant to make obvious.
