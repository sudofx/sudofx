"""Stateless provider adapter for one privacy-bounded Conversation turn."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from sudofx import (
    GenerationRequest,
    GeminiGenerationProvider,
    ProviderError,
    ProviderQuotaError,
    ProviderTemporaryError,
)


SYSTEM_PROMPT = """You are the stateless response engine for a sudofx Conversation proof.

You have no hidden memory. Everything you know about prior turns comes from the
bounded durable observations and commitments supplied with this request.

Return JSON only with exactly these fields:
- content: the assistant reply to the current human message.
- observations: zero to four short semantic observations useful for future
  continuity.
- commitment_updates: zero to four explicit persistent commitment changes.

Commitment update shape:
- upsert a response suffix:
  {"op":"upsert","kind":"response_suffix","text":"...","placement":"end"}
  or
  {"op":"upsert","kind":"response_suffix","text":"...","placement":"new_line"}
- clear a response suffix:
  {"op":"clear","kind":"response_suffix"}
- add a semantic response instruction, preserving the human's exact words:
  {"op":"upsert","kind":"response_instruction","text":"..."}
- clear one response instruction by repeating its exact active text:
  {"op":"clear","kind":"response_instruction","text":"..."}

Commitment rules:
- propose an update only when the human explicitly creates, changes, or revokes
  a persistent response obligation;
- response_suffix means exact required text at the end of future responses;
- placement "end" requires only exact ending text;
- placement "new_line" requires the suffix as its own final paragraph, separated
  from preceding response text by a blank line;
- use "new_line" when the human explicitly requires a new line, its own line, or
  equivalent footer placement;
- preserve required suffix text exactly;
- response_instruction represents a persistent behavioral obligation that
  cannot be reduced to an exact suffix. Follow every active response_instruction
  on every turn, including the turn that creates it;
- commitment upsert text must be an exact contiguous excerpt of current_message;
- when the human requests an ongoing user model or memory, use verified durable
  observations as that explicit privacy-bounded model; never claim hidden memory;
- clear the commitment only when the human explicitly revokes it;
- do not turn casual wording, one-turn requests, or ordinary preferences into
  commitments;
- active_commitments in the supplied state are already authoritative. Do not
  re-propose them merely to keep them active. Runtime enforces them
  deterministically.

Observation rules:
- every observation must be an exact contiguous excerpt from current_message;
- never paraphrase, summarize, infer, generalize, or add a fact that is not
  literally present in current_message;
- do not include direct identifiers, contact details, addresses, account IDs,
  URLs, or secrets;
- choose only short excerpts whose meaning is useful for future continuity;
- each observation must be at most 240 characters;
- use [] when no exact supported excerpt is useful.

Response grounding rules:
- personal facts about the human may come only from current_message or the
  verified durable observations supplied in state;
- never invent, autocomplete, or substitute plausible personal details;
- if the available evidence does not support a requested personal fact, say it
  is unknown rather than guessing.

The current human message is transient. Prior conversation text is intentionally
not present. Durable observations include provenance and have already passed the
runtime's exact-excerpt check.
"""


def _failure_envelope(error: Exception) -> dict[str, Any]:
    """Return bounded diagnostics for the parent process, never provider input.

    The shared Gemini boundary already removes credentials from ``details``.
    This adapter deliberately emits only that sanitized metadata and a bounded,
    implementation-owned message; prompts and provider response bodies never
    cross stderr and therefore cannot leak into server logs or HTTP errors.
    """
    details = getattr(error, "details", {})
    return {
        "error_type": type(error).__name__,
        "message": str(error)[:500],
        "details": details if isinstance(details, dict) else {},
    }


def _report_failure(error: Exception) -> None:
    """Write one machine-readable diagnostic envelope to the private parent."""
    json.dump(_failure_envelope(error), sys.stderr, ensure_ascii=False)
    sys.stderr.write("\n")


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
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {"type": "string", "enum": ["upsert", "clear"]},
                                "kind": {
                                    "type": "string",
                                    "enum": ["response_suffix", "response_instruction"],
                                },
                                "text": {"type": "string"},
                                "placement": {
                                    "type": "string",
                                    "enum": ["end", "new_line"],
                                },
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
        or any(not isinstance(item, dict) for item in value["commitment_updates"])
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
    # Exit codes are part of the application-owned process protocol. Preserve
    # retry/quota meaning so sudofx can journal the right generic outcome; an
    # unhandled traceback would collapse every vendor condition into exit 1.
    try:
        raise SystemExit(main())
    except ProviderQuotaError as error:
        _report_failure(error)
        raise SystemExit(78)
    except ProviderTemporaryError as error:
        _report_failure(error)
        raise SystemExit(75)
    except (ProviderError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        _report_failure(error)
        raise SystemExit(1)
