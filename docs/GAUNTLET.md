# Continuity Gauntlet transport

The transport uses two Apple Shortcuts because the outbound launcher and the
Share Sheet receiver have different system entry points. Keeping those entry
points separate removes a mode prompt and makes the normal journey one launch,
one paste, and one share.

## Operator journey

1. Run **Start sudofx Gauntlet** and choose ChatGPT, Claude, Gemini, or DeepSeek.
2. The Shortcut downloads the current bounded packet, creates a fresh test ID
   and nonce, copies the sealed prompt, and opens a new vendor chat.
3. Paste once and send. The vendor is instructed to return only the response
   JSON, including exact packet evidence for all seven dimensions.
4. Share the complete response text to **Send to sudofx**.
5. The Shortcut dispatches the response through the serialized sudofx workflow.
   The workflow verifies the current packet digest and nonce, computes the
   deterministic grounding score, and appends the raw response and parsed
   result to the authoritative SQLite work record.

The `0–7` score establishes response completeness and literal grounding in the
packet. It does not pretend to replace semantic review of whether the cited
evidence supports the answer.

## One-time iPhone setup

- Sign into the same Apple Account and enable iCloud sync for Shortcuts on the
  Mac and iPhone. Wait for **Start sudofx Gauntlet** and **Send to sudofx** to
  appear in the iPhone Shortcuts library.
- Open **Send to sudofx** once on the iPhone and allow network access if iOS
  asks. It is already enabled for the Share Sheet.
- In a vendor app, share selected response text and choose **Send to sudofx**.
  If the app shares only a conversation URL, use its Copy action and share the
  copied response text instead; private conversation URLs are not fetched.

Both Shortcuts use actions available on macOS 27 and iOS 27. The workflow
credential remains inside the private iCloud-synced Shortcut and is never
written to this repository or the public Pages artifact.
