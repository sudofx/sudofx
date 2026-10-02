# Conversation application

Conversation is the smallest interactive application built on sudofx.

Its purpose is to demonstrate a strict continuity boundary:

- every provider invocation starts fresh;
- the provider receives only bounded context reconstructed from sudofx;
- human and assistant turns cross deterministic application governance before becoming durable;
- SQLite, not provider/session memory, carries continuity;
- the browser and workflow are transport/presentation only.

## Package layout

- `application.py` — Conversation actions, deterministic transition policy, and bounded context projection.
- `runtime.py` — one governed human → fresh provider → governed assistant turn.
- `provider.py` — current stateless provider adapter.
- `__init__.py` — stable package exports.

The application is intentionally self-contained under `applications/conversation/`.
Shared kernel/runtime semantics remain in `src/sudofx/`; shared deployment helpers remain outside the application package.

## Current boundary

The process-replacement proof is implemented and exercised from SQLite-backed state.

The end-user chat transport is intentionally **not** published yet. The current authoritative cloud checkpoint is public, so private or identifying conversation material must not be written to it.

A future browser transport may authenticate the operator, but authentication must remain separate from conversation identity and durable application state.

If GitHub authentication is used for that transport, use **GitHub OAuth**. Do not require users to paste PATs or expose repository credentials to the browser.

## Stateless-provider contract

The provider must not rely on hidden session memory.

For each assistant turn:

1. reopen/reconstruct authoritative state;
2. build the bounded Conversation projection;
3. invoke one fresh provider process/request;
4. validate the result as an untrusted application proposal;
5. govern and commit the assistant turn;
6. discard provider-local state.

A provider can be replaced without changing the Conversation application's durable semantics.

## Privacy note

Do not treat authentication metadata as conversation content.

Until authoritative cloud storage is private, do not persist private or identifying conversation material in the production state branch.
