# Provider Execution Contract

**Date:** October 2, 2026
**Project:** sudofx
**Status:** Complete at the current provider-execution boundary; retained as implementation evidence

## Purpose

Make sudofx the reusable execution boundary between an application and a
stateless intelligence provider.

Applications own domain meaning. sudofx owns the generic provider machinery.
A provider never becomes application authority and an application never needs
to reimplement vendor network transport in order to use the engine.

Provider-neutral generation may declare the read-only capabilities
`read_public_url` and `search_public_web`. An application owns when those
capabilities are requested and which targets are admissible; deployment owns
whether either is granted. Provider adapters may map them to native managed
tools, but retrieved content remains untrusted transient evidence and never
acquires kernel or database authority.

The intended flow is:

```text
application
  -> application-built bounded request
  -> sudofx provider execution
  -> stateless external provider
  -> untrusted provider response
  -> application domain validation/proposal shaping
  -> sudofx governance + durable commit
  -> application
```

## Ownership

### Application owns

- domain state and policy
- domain prompt/instructions
- response schema and domain validation
- application-specific fallback meaning and business rules
- interpretation of provider output
- domain proposal/action semantics
- deployment choice of enabled provider/model(s)

### sudofx owns

- provider-neutral request/response contracts
- vendor transport implementations
- credential injection boundary
- timeout and transport error classification
- stateless invocation lifecycle
- context-delivery evidence
- durability barrier before external effects
- provider-attempt accounting
- generic quota/temporary/provider-failure categories
- future multi-provider support

### Deployment owns

- credentials and secrets
- which provider/model is enabled
- provider-specific limits configured for that deployment

Two repositories may use the same environment variable name, such as
`GEMINI_API_KEY`, while storing different secret values. Shared implementation
must not imply shared credentials.

## Dependency direction

The dependency is one-way:

```text
Conversation -> sudofx
future applications -> sudofx

sudofx -X-> application internals
```

sudofx must never import application modules, domain policy, prompts, schemas, or
configuration.

## Provider-neutral generation boundary

sudofx should expose a small generation contract that accepts application-built
content and returns untrusted model output plus bounded generic metadata.

The generic request may contain:

- model identifier
- system/instruction text
- user/application prompt text
- optional JSON response schema
- response mode
- generation parameters that have provider-neutral meaning

The generic response may contain:

- provider identifier
- resolved model identifier
- output text
- bounded provider metadata safe for accounting/diagnostics

Raw provider responses, secrets, HTTP headers, and application state are not
part of the public contract.

## Credentials

Credentials are injected at runtime and never persisted by the provider API.

A provider implementation may read a supplied credential or a deployment
environment variable, but it must not record the value, return it in metadata,
or place it into durable context.

Credential ownership is independent of provider implementation ownership.

Therefore:

- each application can use its own Gemini API key;
- sudofx experiments can use a different Gemini API key;
- both can execute through the same sudofx Gemini transport implementation.

## Lifecycle ordering

Applications should not call vendor HTTP APIs directly.

A provider effect executes only after sudofx has durably recorded the generic
invocation attempt and any configured effect barrier succeeds.

The generic lifecycle remains:

```text
requested
context_delivered
attempt_started
[external provider effect]
proposal_received / application response received
governed
completed | failed
```

Applications may add domain receipts around this sequence, but may not replace
or bypass it.

## Provider failure categories

Vendor-specific errors map onto generic categories:

- temporary_failure
- quota_exhausted
- provider_failure
- effect_barrier_failure

The original provider-specific diagnostic may be retained only in bounded,
redacted application/runtime evidence when policy permits. Generic sudofx
behavior must not depend on parsing application-specific error strings.

## Multi-provider future

Adding another vendor should require:

1. one new sudofx provider transport implementation;
2. transport-specific tests;
3. optional deployment configuration.

Existing applications should not need a new authority path, storage schema, or
governance mechanism merely because a different stateless provider is selected.

Application prompts and response validators may still vary by provider when
that is genuinely required, but vendor HTTP mechanics belong in sudofx.

## Non-goals

This contract does not:

- make sudofx aware of application domain semantics;
- make one shared API key mandatory;
- centralize every application's database;
- require applications to share provider quotas;
- move domain prompt design into the kernel;
- grant providers direct Record/Kernel access;
- treat provider output as authoritative before governance.

## North-star test

A new application should be able to bring domain context and policy to sudofx,
select a supported stateless provider, and receive an untrusted response without
implementing vendor HTTP mechanics.

A new provider should be addable to sudofx without changing an application's database,
domain governance, or application identity.
