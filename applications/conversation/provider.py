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
                },
                "required": ["content", "observations"],
                "additionalProperties": False,
            },
        )
    )

    value = json.loads(response.text)
    if (
        not isinstance(value, dict)
        or set(value) != {"content", "observations"}
        or not isinstance(value["content"], str)
        or not value["content"].strip()
        or not isinstance(value["observations"], list)
        or any(not isinstance(item, str) for item in value["observations"])
    ):
        raise ValueError("Gemini conversation output does not match the privacy-bounded schema")

    json.dump(
        {
            "content": value["content"].strip(),
            "observations": value["observations"],
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
