# Manual handoff development plugin

Status: **development extension**

This plugin contains the vendor-facing and Apple Shortcut machinery used to test
sudofx handoffs across ChatGPT, Claude, Gemini, DeepSeek, and other models.

It is intentionally **not part of the sudofx kernel**.

## What belongs here

- launching a selected model app
- Apple Shortcut transport
- fresh test IDs and nonces
- parsing a human-transported model response
- deterministic packet-grounding checks
- development-only UI and workflow glue for collecting results

## What stays in core

- the authoritative SQLite record
- bounded governed context
- portable handoff packet construction
- governance
- transitions and receipts
- provenance
- the rule that model output is a proposal or observation, never authority by itself

## Current transport

The development workflow uses the action `handoff-evaluate`. A fresh request
should use a nonce shaped like `HANDOFF-UUID-NNNNNN`.

The response is untrusted text. The plugin binds it to the frozen packet,
checks the seven grounding dimensions, then asks the normal sudofx governance
path to record the evaluation. The score measures literal packet grounding,
not semantic truth.

## Boundary

This directory is the first concrete use of the plugin boundary described in
`docs/PLUGIN_ARCHITECTURE.md`. It does **not** establish a general runtime
plugin loader yet. The boundary is being exercised before that API is frozen.

## Shortcut prompt

The current iOS Shortcut should build this prompt:

```text
Strict manual handoff evaluation prompt.
Selected Vendor: vendor
test_id: Text
nonce: HANDOFF-Text
packet_digest: Dictionary Value
Complete JSON Packet:
Contents of URL

Return only one JSON object with test_id, nonce, vendor, packet_digest, and answers.
Answers must contain exactly objective_fidelity, authority_fidelity, history_fidelity, constraint_fidelity, frontier_fidelity, epistemic_discipline, and transfer_usability.
Each answer has non-empty answer and evidence fields, and evidence must be an exact quote from the packet.
```

The nonce prefix is part of the transport contract. Do not use the retired development nickname in Shortcut names, prompts, variables, or nonce values.
