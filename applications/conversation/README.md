# Conversation application

Conversation is the smallest interactive application built on sudofx.

Its purpose is to demonstrate a strict continuity boundary:

- every provider invocation starts fresh;
- the provider receives the current transient message plus bounded context reconstructed from sudofx;
- raw human and assistant transcript text is not durable Conversation state;
- human and assistant turns cross deterministic application governance;
- SQLite, not provider/session memory or the browser, carries continuity;
- browser/workflow transport remains disposable.

## Package layout

- `application.py` — Conversation policy, privacy-bounded durable state, and context projection.
- `runtime.py` — governed human → fresh provider → governed assistant execution.
- `provider.py` — Conversation prompt/schema over the shared sudofx generation boundary.
- `transport.py` — encrypted disposable GitHub workflow transport.
- `server.py` — private same-origin HTTP transport for deployments that host Conversation directly.
- `__init__.py` — stable package exports.

Shared kernel/runtime/provider mechanics remain in `src/sudofx/`.

## Durable privacy contract

The production/private Conversation path does **not** store a conventional transcript.

For a human turn, authoritative state may retain only bounded metadata such as:

- SHA-256 message fingerprint;
- character count;
- turn ordering metadata.

For an assistant turn, authoritative state may retain:

- SHA-256 response fingerprint;
- character count;
- a small governed set of semantic observations needed for future continuity.

Observations are bounded and screened for common direct identifiers. That screening is deliberately conservative and is not claimed to be a perfect PII detector. Users should not enter secrets or direct identifiers.

The raw current human message is transient provider context. Previous raw turns are not replayed to the provider.

## Stateless-provider contract

For each assistant turn:

1. reopen/reconstruct authoritative state;
2. build the bounded Conversation observation projection;
3. add the current transient human message;
4. invoke one fresh provider request through sudofx's shared generation boundary;
5. validate the untrusted response and proposed observations;
6. govern and commit only privacy-bounded assistant metadata/observations;
7. discard provider-local state and raw response text after presentation.

A provider can be replaced without changing Conversation's durable semantics.

## Browser and transport

`web/conversation.html` is a disposable chat presentation. Its visible transcript is DOM-only: reloading or clearing the page discards it.

The public shell never receives a PAT and never becomes authority.

Two transport patterns are supported:

- **private same-origin server** — `python -m applications.conversation.server` hosts the chat and one explicit SQLite authority directly;
- **OAuth gateway + GitHub Actions** — an authenticated gateway encrypts the current message, dispatches `conversation.yml`, and decrypts the matching encrypted response from the historyless `conversation-live` projection.

The Actions path requires the same `CONVERSATION_TRANSPORT_KEY` to be available to the authenticated gateway and the GitHub Actions deployment. Workflow inputs and the disposable reply branch contain ciphertext, not plaintext.

The public Pages client reads `web/conversation-config.json`. Leave `gateway_url` empty until the authenticated gateway is actually deployed; do not invent a fallback PAT or expose repository credentials in browser code.

If GitHub authentication is used, use GitHub OAuth.

## Authority rule

SQLite remains authoritative.

The browser transcript, encrypted workflow envelope, `conversation-live/reply.json`, workflow summary, and public Pages files are disposable transport or presentation. They are never read as sudofx operational truth.
