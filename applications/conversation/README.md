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
- a small governed set of semantic observations needed for future continuity;
- explicit active commitments when the human establishes a persistent response obligation.

Observations are bounded and screened for common direct identifiers. That screening is deliberately conservative and is not claimed to be a perfect PII detector. Users should not enter secrets or direct identifiers.

The raw current human message is transient provider context. Previous raw turns are not replayed to the provider.

Persistent obligations are not stored as transcript. Conversation gives them an explicit governed lifecycle separate from observations. The initial supported commitment kind is an exact response suffix with structured placement semantics: it can be created or updated, deterministically enforced on every response, and explicitly revoked. A suffix may require only exact end placement or canonical `new_line` placement as its own final paragraph. The provider proposes this structure; sudofx validates and enforces it. Historical suffix commitments that predate placement metadata remain valid and retain the earlier exact-end semantics until explicitly updated. This is intentionally narrower than treating every remembered preference as an instruction.


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

Each bubble shows a timestamp in the browser's local timezone, including seconds.
The private server supplies UTC request-receipt and governed-response completion
times; transports without timestamp fields fall back to browser send/arrival time.
These times stay in the disposable browser transcript and its Markdown export.
They do not replace SQLite receipt timestamps or introduce durable chat state.

The public shell never receives a PAT and never becomes authority.

Three transport/runtime patterns are defined:

- **private same-origin server** — `python -m applications.conversation.server` hosts the chat and one explicit SQLite authority directly;
- **private GitHub Codespace** — the repository dev container starts that same server on port 8765. GitHub keeps forwarded ports private by default and authenticates the codespace creator before access;
- **encrypted Actions seam** — `conversation.yml` remains available for a future authenticated server-side gateway. It is not exposed directly to the browser.

The Actions seam requires the same `CONVERSATION_TRANSPORT_KEY` at both ends. Workflow inputs and the disposable reply branch contain ciphertext, not plaintext.

The public Pages client reads `web/conversation-config.json`. Its current public launch target is GitHub Codespaces. `gateway_url` remains empty because GitHub Pages cannot safely complete GitHub OAuth or hold server-side credentials by itself. Do not invent a fallback PAT or expose repository/provider credentials in browser code.

For the Codespaces path, add `GEMINI_API_KEY` as a GitHub Codespaces secret before starting a Conversation codespace. The forwarded port is private and GitHub-authenticated; no application OAuth secret is shipped to Pages.

## Authority rule

SQLite remains authoritative.

The browser transcript, encrypted workflow envelope, `conversation-live/reply.json`, workflow summary, and public Pages files are disposable transport or presentation. They are never read as sudofx operational truth.
