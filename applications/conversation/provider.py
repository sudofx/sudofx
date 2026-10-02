"""Stateless provider adapter for one privacy-bounded Conversation turn."""

from __future__ import annotations

import json
import os
import sys

from sudofx import GenerationRequest, GeminiGenerationProvider


SYSTEM_PROMPT = """You are the stateless response engine for a sudofx Conversation proof.

You have no hidden memory. Everything you know about prior turns comes from the
bounded durable observations supplied with this request.

Return JSON only with exactly these fields:
- content: the assistant reply to the current human message.
- observations: zero to four short semantic observations useful for future
  continuity.
- commitment_updates: zero to two governed lifecycle updates for persistent
  response obligations requested or revoked by the current human message.

Commitment rules:
- use {"op":"upsert","kind":"response_suffix","text":"..."} when the human
  explicitly requires exact text at the end of every future response until
  revoked;
- preserve the required suffix text exactly;
- use {"op":"clear","kind":"response_suffix"} when the human explicitly revokes
  that persistent suffix requirement;
- do not turn casual wording, one-turn requests, or ordinary preferences into
  commitments;
- active_commitments in the supplied state are mandatory. The runtime also
  enforces them deterministically.

Observation rules:
- do not copy the transcript or quote the user;
- do not include direct identifiers, contact details, addresses, account IDs,
  URLs, or secrets;
- preserve meaning needed for later continuity, not wording;
- each observation must be at most 240 characters;
- use [] when no durable observation is useful.

The current human message is transient. Prior conversation text is intentionally
not present.
"""


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    model = os.environ.get("GEMINI_MODEL", "").strip()
    if not api_key or not model:
        raise RuntimeError("GEMINI_API_KEY and GEMINI_MODEL are required")

    context = json.load(sys.stdin)
    if not isinstance(context, dict):
        raise ValueError("stdin context must be an object")

    provider = GeminiGenerationProvider(api_key, timeout_seconds=80)
    response = provider.generate(
        GenerationRequest(
            model=model,
            system=SYSTEM_PROMPT,
            prompt=json.dumps(context, ensure_ascii=False, sort_keys=True),
            temperature=0.4,
            response_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "observations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 4,
                    },
                    "commitment_updates": {
                        "type": "array",
                        "maxItems": 2,
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {"type": "string", "enum": ["upsert", "clear"]},
                                "kind": {"type": "string", "enum": ["response_suffix"]},
                                "text": {"type": "string"},
                            },
                            "required": ["op", "kind"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["content", "observations", "commitment_updates"],
                "additionalProperties": False,
            },
        )
    )

    value = json.loads(response.text)
    if (
        not isinstance(value, dict)
        or set(value) != {"content", "observations", "commitment_updates"}
        or not isinstance(value["content"], str)
        or not value["content"].strip()
        or not isinstance(value["observations"], list)
        or any(not isinstance(item, str) for item in value["observations"])
        or not isinstance(value["commitment_updates"], list)
    ):
        raise ValueError("Gemini conversation output does not match the privacy-bounded schema")

    json.dump(
        {
            "content": value["content"].strip(),
            "observations": value["observations"],
            "commitment_updates": value["commitment_updates"],
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
