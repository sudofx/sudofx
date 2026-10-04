# Conversation application

Conversation is the smallest interactive application built on sudofx.

Its purpose is to demonstrate a strict continuity boundary:

- every provider invocation starts fresh;
- the provider receives the current transient message, the immediately previous
  process-local exchange when available, and bounded context reconstructed from sudofx;
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

Observations are bounded and screened for common direct identifiers. On the private production path, a durable observation must also be an exact contiguous excerpt of the current human message. The runtime drops unsupported provider observations before submission, records the source human-message digest with accepted observations, and exposes only those verified observations to later provider calls. Historical observations created before this rule remain in replayable history but are quarantined from future provider context. That screening is deliberately conservative and is not claimed to be a perfect PII detector. Users should not enter secrets or direct identifiers.

The raw current human message is transient provider context. The private server
also keeps exactly one successful human/assistant pair in process memory and
supplies it to the next fresh provider. This active-window buffer exists so
adjacent references such as “that” and “any of that” remain intelligible. It is
not SQLite authority, is never replayed after restart, and is discarded by the
Clear action; older raw turns are never replayed.

Public-web access is an explicit read-only application capability. A validated public HTTPS URL enables `read_public_url` for that turn; explicit phrases such as “search the web” enable `search_public_web`. Local/private hosts, non-HTTPS targets, credential-bearing URLs, sensitive query parameters, and more than five URLs fail before provider invocation. Gemini URL Context and Google Search are managed provider effects behind sudofx's ordinary invocation barrier. Retrieved bodies and snippets remain transient; bounded citations are projected into the reply and URL-bearing provider observations are discarded. `CONVERSATION_WEB_CAPABILITIES` may narrow the deployment to either capability or neither; its default enables both. Managed web-tool turns have provider retention and possible search-cost characteristics distinct from private-only turns, which the local UI discloses.

HTTP errors expose a bounded owner rather than labeling every failure as transport: `conversation.app`, `conversation.provider`, `conversation.transport`, `conversation.deployment`, `conversation.runtime`, or `sudofx`. Exception internals and provider payloads remain private.

Persistent obligations are not stored as transcript. Conversation gives them an explicit governed lifecycle separate from observations. Exact response suffixes have structured placement semantics and are deterministically enforced on every response. A declared follow-up-question obligation is also enforced mechanically: if a fresh provider omits a question, the application adds a neutral follow-up before the suffix. Semantic `response_instruction` commitments cover other explicit ongoing behavioral obligations that cannot be reduced to a mechanical output rule; multiple instructions may remain active together and every fresh provider receives them. New commitments must preserve an exact excerpt of the authorizing human message, so a provider cannot invent durable policy. Any kind can be explicitly revoked. Historical suffix commitments that predate placement metadata remain valid and retain the earlier exact-end semantics until explicitly updated.

An instruction to build a user model does not authorize opaque provider memory. Conversation satisfies it through the same explicit, bounded, verified observations used for continuity. SQLite remains the only durable owner, and the active projection remains inspectable.

The explicit Conversation `# init prompt` syntax is deterministic: the line after `following footer:` becomes the governed suffix, and every `[DONT FORGET]` bullet becomes an independent response instruction. This parsing belongs to the application rather than the provider, so a fresh model cannot silently omit declared initialization commitments.


## Stateless-provider contract

For each assistant turn:

1. reopen/reconstruct authoritative state;
2. build the bounded Conversation observation projection;
3. add the current transient human message and, when present, the server-owned
   immediately previous exchange;
4. invoke one fresh provider request through sudofx's shared generation boundary;
5. validate the untrusted response and proposed observations;
6. govern and commit only privacy-bounded assistant metadata/observations;
7. discard provider-local state and raw response text after presentation.

A provider can be replaced without changing Conversation's durable semantics.
The disposable provider process returns bounded, credential-sanitized failure
metadata over stderr and uses distinct temporary/quota exit codes. The parent
runtime converts those codes into generic sudofx invocation outcomes while raw
provider payloads, prompts, and response text remain outside durable state.

## Browser and transport

`web/conversation.html` is a disposable chat presentation. Its visible transcript
is DOM-only: reloading discards the screen, and Clear discards both the screen
and the server's one-exchange active buffer without resetting governed SQLite
continuity. Successful assistant bubbles and Markdown exports carry a monotonic
display number derived from the authoritative completed-turn count (`#0001`,
`#0002`, and so on); transport errors are labeled System and consume no number.

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
