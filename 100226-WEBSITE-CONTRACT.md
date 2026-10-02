# 100226 — sudofx Product Surface Contract

**Date:** October 2, 2026  
**Status:** Active execution contract  
**Authority:** operator-approved implementation direction

## Purpose

Turn the proven sudofx architecture into a clear, durable, accessible public product surface without weakening the authority boundary or adding new kernel semantics merely to support presentation.

## Product rule

> Exact underneath. Simple at the surface. Proven when you go deeper.

The website must explain sudofx to a first-time visitor before exposing technical machinery.

## Required public surfaces

1. **Home** — a natural explanation of what sudofx is, followed by short ELI15 summaries where useful.
2. **Applications** — applications currently using sudofx, with a plain description and links.
3. **Technical** — architecture, authority boundaries, replay, storage, governance, runtime, and implementation status.
4. **Metrics** — derived runtime, continuity, application, and experimental measurements with clear provenance and limitations.

## Hosting boundary

GitHub Pages is the lightweight presentation shell only.

Changing operational state must **not** require a Pages rebuild. Dynamic public data is fetched from the historyless `sudofx-live` projection branch, following the same pattern already used by WAKE✳︎.

The browser may read public projections. It may never become an authority surface.

## Authority constraints

- SQLite remains the single authoritative source of operational truth.
- Raw authoritative SQLite is never shipped as a website asset.
- Pages, JSON projections, charts, summaries, and browser state are disposable views.
- Models remain proposers, not authorities.
- Presentation paths may not checkpoint migrations, advance revisions, write receipts, or mutate application state.
- WAKE✳︎ remains application-owned; WAKE research policy does not move into the sudofx kernel.
- Public metrics use allowlisted, bounded projection fields only.
- Every “current” technical claim must expose freshness or source revision when available.

## Design direction

The site should feel like a **technical instrument made humane**:

- state-of-the-art but restrained;
- strong typography and clear hierarchy;
- mobile-first;
- dark/light capable;
- minimal motion;
- evidence and provenance one level deeper than the explanation;
- no generic AI imagery;
- no dashboard overload on the homepage.

## Content rules

The homepage leads with plain language.

Technical implementation detail moves to the Technical page.

Metrics are grouped by meaning:
- runtime health;
- continuity quality;
- application activity;
- experimental measurements.

Different classes must never be visually collapsed into one “score.”

## Applications

Current concrete implementations:

- **WAKE✳︎** — substantial research application. sudofx owns generic authority/runtime primitives; WAKE owns research policy and domain behavior.
- **Conversation** — minimal governed conversation proof demonstrating fresh-process reconstruction from SQLite-backed durable state.

Future or experimental concepts are not listed as active applications until they actually use the application contract.

## Delivery phases

### A — public information contract
Exit condition: public facts have an identified canonical source and the site map is stable.

### B — static shell
Exit condition: a fresh checkout can build Home, Applications, Technical, and Metrics without operational state or secrets.

### C — live projection boundary
Exit condition: changing authoritative state can refresh bounded public data without rebuilding GitHub Pages.

### D — technical and metrics fidelity
Exit condition: public technical claims and metrics identify their source, scope, freshness, and limits.

### E — hardening and cutover
Exit condition: mobile, accessibility, performance, metadata, links, and old-surface routing are verified; the rebuilt site is the canonical public front door.

## Explicit non-goals

- new kernel semantics for presentation;
- a hosted multi-user SaaS product;
- raw database browsing from the public internet;
- browser-side authority;
- duplicating operational truth in Markdown/JSON/HTML;
- moving WAKE-specific research semantics into sudofx;
- treating experimental measurements as universal product reliability scores.
