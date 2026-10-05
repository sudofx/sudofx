# Application Observability Contract

**Date:** October 2, 2026  
**Project:** sudofx  
**Status:** Complete at the current product/engine boundary; retained as implementation evidence

## Purpose

Make it possible to see how an application is using sudofx without turning the
viewer, website, or a second telemetry service into operational authority.

The user-facing question is simple:

> Which application is using sudofx, what engine boundary did it cross, and what durable evidence did sudofx record?

The observability interface is generic. Application-specific policy, URLs,
repositories, and metrics do not belong in the engine implementation.

## Authority rule

The application's own authoritative sudofx database remains the only operational
truth for that deployment.

Observability is always:

```text
application-owned sudofx database
        ↓ verified read
generic observability projection
        ↓ disposable publication / transport
viewer
```

The projection is never read back into governance, replay, recovery, provider
context, or application policy.

No central observability database is introduced.

## Generic evidence surface

sudofx may derive a bounded application-observability snapshot from the stable
record contracts already present in the authoritative database:

- registered/durable application identity and version
- application storage mode
- governed `apply_application` actions
- accepted/rejected application action counts
- recent action names and governed outcomes, without action payloads
- application-scoped invocation lifecycle evidence
- context-delivery scope and bounded byte/category metadata
- provider attempt counts and generic outcomes
- completed/failed invocation counts
- source record revision and timestamps already present in durable evidence

The projection must not expose arbitrary application state, proposal payloads,
provider prompts/responses, secrets, or domain-specific records merely because
they exist in the database.

## Application boundary

An application does not implement a custom observability schema.

It may call the generic sudofx projection helper against its own Record and
publish the resulting bounded document through its existing disposable
presentation path.

Application deployments remain free to publish additional domain metrics under
their own contracts. Those metrics do not become sudofx engine semantics.

Examples:

- Conversation may separately show a transcript or turn-oriented UI.
- sudofx application observability shows only the shared engine boundary:
  governed app actions, runtime invocation lifecycle, context delivery, outcomes,
  and revision/provenance evidence.

## Viewer boundary

A sudofx website or another observer may consume one or more standard
application-observability documents.

Feed discovery belongs to presentation/product configuration, not the kernel.
The kernel must not gain knowledge of application internals, a particular repository host, or a
public URL.

A viewer must tolerate:

- an application feed being unavailable
- a feed being stale
- an unknown application ID
- an application being removed
- multiple independent sudofx deployments
- different applications advancing at different cadences

Failure to load a feed must never affect the application or its authority.

## Removal test

Removing an application must require no change to:

- the sudofx kernel
- governance
- storage
- replay
- runtime lifecycle
- the generic observability schema or builder

Only product/catalog configuration that chooses to display that application may disappear.

## Privacy and public-safe rule

The generic projection is intentionally metadata-first.

It may expose stable IDs, action names, lifecycle stages, counts, bounded context
metadata, generic outcomes, source revisions, and timestamps. It must not expose
application action input payloads, state payloads, raw provider content, or
arbitrary provenance strings by default.

Applications with sensitive deployments should not publish the projection
publicly unless their deployment policy allows it.

## Schema evolution

The projection carries an explicit `projection_schema` and
`projection_kind`.

Schema changes must remain backward-readable where practical. A viewer should
feature-detect optional fields and treat unknown fields as ignorable evidence,
not authority.

## Product interpretation

The visual surface should make a real sequence legible without pretending that
a diagram is itself evidence.

A useful application card may answer:

- **Application:** which application ID produced this evidence?
- **Governed actions:** how many application intents were accepted or rejected?
- **Runtime calls:** how many application-scoped invocations crossed the runtime?
- **Latest boundary:** what lifecycle stages were durably recorded?
- **Context:** how many bounded bytes/categories crossed the intelligence boundary?
- **Outcome:** did the invocation complete, fail, hit quota, or stop at another stage?
- **Revision:** which authoritative record revision did this evidence come from?

The site should visually distinguish static explanation from recorded evidence.

## Non-goals

This contract does **not** create:

- a central application registry service
- a cross-application authoritative database
- a monitoring control plane
- application-to-application messaging
- a requirement that all applications be public
- application-specific engine APIs
- a new semantic event type merely for presentation
- permission for a website to infer application health from missing data

## North-star test

A fresh observer should be able to see that an application is genuinely using
sudofx's shared authority/runtime boundaries while the application remains
replaceable, independently deployed, and domain-owned.

> One authoritative database per deployment → generic bounded evidence → disposable views.
