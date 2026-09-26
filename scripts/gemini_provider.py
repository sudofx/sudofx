"""
GEMINI CONTINUITY EXPERIMENT ADAPTER
====================================

This executable is intentionally outside the sudofx kernel. It receives one
bounded Context JSON document on stdin, sends only that document plus experiment
instructions to Gemini, and emits one provider-neutral Proposal JSON document on
stdout.

The model never receives the SQLite path, Record, Kernel, governance rules as a
capability, GitHub token, or any mutation interface. The API key exists only in
this disposable process environment and is sent in the x-goog-api-key header.

The adapter owns transport mechanics: proposal identity, observed revision, work
ID, and the single allowed advance_work action. The model is evaluated on the
semantic part of the experiment—reconstructing current work and identifying a
meaningful next step—not on whether it can reproduce sudofx's wire format.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any


def _bounded_work(context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Require exactly one open work item in the context supplied by sudofx."""
    state = context.get("state")
    if not isinstance(state, dict) or len(state) != 1:
        raise ValueError("Gemini continuity probe requires exactly one bounded work item")
    key, work = next(iter(state.items()))
    if not isinstance(key, str) or not key.startswith("work:") or not isinstance(work, dict):
        raise ValueError("bounded context does not contain a work item")
    if work.get("status") != "open":
        raise ValueError("Gemini continuity probe requires open work")
    work_id = work.get("id")
    if not isinstance(work_id, str) or not work_id:
        raise ValueError("work item has no valid ID")
    return work_id, work


def _prompt(context: dict[str, Any]) -> str:
    """
    Ask for semantic reconstruction while forbidding claims of performed work.

    The output is deliberately smaller than a Proposal. The adapter controls
    transport and mutation shape so semantic quality is the variable under test.
    """
    return (
        "You are participating in a continuity experiment. You have no memory, "
        "conversation history, files, tools, or hidden context beyond the bounded "
        "durable record below. Reconstruct the work from that record alone.\n\n"
        "Return ONLY a JSON object with exactly these fields:\n"
        '{"reconstruction":"...","next_step":"...","rationale":"..."}\n\n'
        "Rules:\n"
        "- reconstruction: concise description of what the work is, what has "
        "already been accepted, and its current frontier.\n"
        "- next_step: one concrete next action that follows from the record.\n"
        "- rationale: concise evidence-based reason using only supplied context.\n"
        "- Do not claim you performed external work, inspected unavailable files, "
        "or know anything not present in the record.\n"
        "- Do not output markdown or code fences.\n\n"
        "BOUNDED DURABLE CONTEXT:\n"
        + json.dumps(context, ensure_ascii=False, sort_keys=True)
    )


def _extract_text(response: dict[str, Any]) -> str:
    """Extract the first textual candidate from Gemini's generateContent response."""
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Gemini returned no candidates")
    content = candidates[0].get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise ValueError("Gemini candidate has no content parts")
    text = "".join(
        part.get("text", "") for part in parts if isinstance(part, dict)
    ).strip()
    if not text:
        raise ValueError("Gemini candidate contained no text")
    return text


def _semantic_output(raw: str) -> dict[str, str]:
    """Validate the model's compact semantic response and reject extra shapes."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"Gemini returned non-JSON semantic output: {error.msg}") from error
    expected = {"reconstruction", "next_step", "rationale"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("Gemini semantic output must contain exactly reconstruction, next_step, rationale")
    for key in expected:
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError(f"Gemini semantic output field {key} must be non-empty text")
        value[key] = value[key].strip()
    return value


def main() -> int:
    """
    Make one stateless Gemini request and emit one sudofx Proposal document.

    Authentication and model choice are runtime configuration, never durable
    state. Network/API failures exit nonzero so CommandIntelligence records no
    fabricated proposal receipt.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    model = os.environ.get("GEMINI_MODEL", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for the real-model continuity probe")
    if not model:
        raise RuntimeError("GEMINI_MODEL is required for the real-model continuity probe")

    context = json.load(sys.stdin)
    if not isinstance(context, dict):
        raise ValueError("stdin context must be a JSON object")
    revision = context.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool):
        raise ValueError("context revision must be an integer")
    work_id, work = _bounded_work(context)

    body = json.dumps(
        {
            "contents": [{"parts": [{"text": _prompt(context)}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
    ).encode("utf-8")
    safe_model = re.sub(r"[^A-Za-z0-9._-]", "", model)
    if not safe_model:
        raise ValueError("GEMINI_MODEL contains no usable model identifier")
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{safe_model}:generateContent",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Gemini API HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Gemini API transport failure: {error.reason}") from error

    semantic = _semantic_output(_extract_text(payload))
    current_obligations = work.get("open_obligations", [])
    if not isinstance(current_obligations, list) or not all(
        isinstance(item, str) for item in current_obligations
    ):
        raise ValueError("work open_obligations must be a list of strings")

    # Preserve existing durable obligations and add the model's proposed next
    # step as the new frontier on the temporary snapshot only.
    obligations = list(dict.fromkeys([*current_obligations, semantic["next_step"]]))
    result_text = (
        f"Reconstruction: {semantic['reconstruction']} "
        f"Proposed next step: {semantic['next_step']}"
    )
    json.dump(
        {
            "proposal_id": f"gemini-{safe_model}-{revision}-{work.get('work_revision', 0)}",
            "based_on_revision": revision,
            "operations": [
                {
                    "action": "advance_work",
                    "key": work_id,
                    "value": {
                        "result": result_text,
                        "open_obligations": obligations,
                    },
                }
            ],
            "rationale": semantic["rationale"],
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
