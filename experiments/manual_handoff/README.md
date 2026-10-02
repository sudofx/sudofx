# Manual handoff compatibility path

**Deprecated:** Handoff is now the first-class `applications/handoff/` sudofx
application.

These modules remain only as import shims so old scripts, historical tests, and
external references do not break abruptly. They own no policy or durable state.

New development belongs in:

```text
applications/handoff/
```

The application owns packet construction, deterministic grounding scoring,
target registration, governed evaluation state, and disposable projections.
SQLite remains authoritative through the ordinary sudofx application boundary.
