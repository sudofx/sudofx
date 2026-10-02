# Plugin architecture — historical redirect

**Status:** Deprecated terminology.  
**Current authority:** [APPLICATION_ARCHITECTURE.md](APPLICATION_ARCHITECTURE.md) and [../100126-CONTRACT.md](../100126-CONTRACT.md).

The earlier design explored WAKE✳︎ as a sudofx “plugin.” That framing is no longer the active architecture.

A complete domain system such as WAKE✳︎ is now an **application**. Optional capabilities that augment an application or the engine may be called **extensions**. The term **plugin** is reserved only for a future technical loading or packaging mechanism if dynamic installation is actually implemented.

Do not use this file as an implementation specification.

Current vocabulary:

- **kernel** — smallest durable authority boundary
- **runtime** — context, invocation, recovery, provider/effect coordination
- **application** — complete domain system built on sudofx
- **extension** — optional capability that augments the engine or an application
- **plugin** — optional loading/packaging mechanism only if implemented

The current application contract is implemented in `src/sudofx/applications.py` and documented in [APPLICATION_ARCHITECTURE.md](APPLICATION_ARCHITECTURE.md).

WAKE✳︎ migration work lives in the separate `sudofx/wake` repository and must preserve WAKE-specific research policy above the generic sudofx authority boundary.
