# Plugin Architecture — superseded terminology

**Status:** Superseded by [Application Architecture](APPLICATION_ARCHITECTURE.md) and `100126-CONTRACT.md`.

The original plugin direction correctly identified that sudofx needed a small reusable core and optional capabilities. The term **plugin**, however, became too broad and incorrectly described WAKE✳︎.

Current terminology is:

- **application** — a complete domain system built on sudofx, such as WAKE✳︎
- **extension** — an optional capability that augments sudofx or an application
- **plugin** — a possible technical packaging/loading mechanism, only if dynamic installation is implemented

The still-valid architectural rules are preserved:

- installed code does not become trusted merely because it is present;
- no application or extension owns a competing durable source of truth;
- meaningful actions remain subject to deterministic governance and durable provenance;
- external permissions/effects must be explicit;
- failures must not silently corrupt core state.

Do not build new architecture against this document. Use
[APPLICATION_ARCHITECTURE.md](APPLICATION_ARCHITECTURE.md) and
[100126-CONTRACT.md](../100126-CONTRACT.md).
