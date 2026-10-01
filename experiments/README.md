# sudofx experiments

This directory contains disposable evidence-gathering harnesses used to test
sudofx claims. Experiments may import and exercise the engine, but the engine
must not depend on them.

Current experiments include:

- `continuity.py` — deterministic and real-provider replacement probes;
- `overnight.py` — continuity stress-matrix curriculum and residue progression;
- `manual_handoff/` — human-transported cross-provider handoff scoring.

Experiment success can justify later engine changes. Experiment implementation
itself is not an engine contract.

**Removal test:** deleting this directory must not change authoritative sudofx
record semantics, kernel governance, or replay.
