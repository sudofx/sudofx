"""
ANTHROPIC CONTINUITY EXPERIMENT ADAPTER
=======================================

This disposable adapter deliberately mirrors the Gemini semantic contract while
changing the model provider. It receives exactly one bounded Context JSON object
on stdin and returns one provider-neutral Proposal JSON object on stdout.

The adapter owns API transport and proposal wiring only. Claude receives no
SQLite path, GitHub token, Kernel, Record, mutation capability, prior chat, or
provider-local memory. That keeps provider substitution focused on whether the
same governed durable context supports useful continuation.
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
    state = context.get("state")
    if not isinstance(state, dict) or len(state) != 1:
        raise ValueError("Anthropic continuity probe requires exactly one bounded work item")
    key, work = next(iter(state.items()))
    if not isinstance(key, str) or not key.startswith("work:") or not isinstance(work, dict):
        raise ValueError("bounded context does not contain a work item")
    if work.get("status") != "open":
        raise ValueError("Anthropic continuity probe requires open work")
    work_id = work.get("id")
    if not isinstance(work_id, str) or not work_id:
        raise ValueError("work item has no valid ID")
    return work_id, work


def _prompt(context: dict[str, Any]) -> str:
    return (
        "You are participating in a continuity experiment. You have no memory, "
        "conversation history, files, tools, or hidden context beyond the bounded "
        "durable record below. Reconstruct the work from that record alone.\n\n"
        "Return ONLY a JSON object with exactly these fields:\n"
        '{"reconstruction":"...","chosen_action":"...","target":"...",'
        '"verification":"...","rationale":"..."}\n\n'
        "Rules:\n"
        "- reconstruction: concise description of what the work is, what has "
        "already been accepted, and its current frontier.\n"
        "- chosen_action: one specific next action, written as an imperative; "
        "do not merely restate the obligation.\n"
        "- target: the exact system boundary, experiment, or artifact the action applies to.\n"
        "- verification: one observable check that would prove the action succeeded.\n"
        "- rationale: concise evidence-based reason using only supplied context.\n"
        "- Do not claim you performed external work, inspected unavailable files, "
        "or know anything not present in the record.\n"
        "- Do not output markdown or code fences.\n\n"
        "BOUNDED DURABLE CONTEXT:\n"
        + json.dumps(context, ensure_ascii=False, sort_keys=True)
    )


def _extract_text(response: dict[str, Any]) -> str:
    content = response.get("content")
    if not isinstance(content, list):
        raise ValueError("Anthropic response has no content array")
    text = "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    if not text:
        raise ValueError("Anthropic response contained no text")
    return text


def _semantic_output(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"Anthropic returned non-JSON semantic output: {error.msg}") from error
    expected = {"reconstruction", "chosen_action", "target", "verification", "rationale"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(
            "Anthropic semantic output must contain exactly reconstruction, "
            "chosen_action, target, verification, rationale"
        )
    for key in expected:
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError(f"Anthropic semantic output field {key} must be non-empty text")
        value[key] = value[key].strip()
    return value


def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = os.environ.get("ANTHROPIC_MODEL", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for the provider-substitution probe")
    if not model:
        raise RuntimeError("ANTHROPIC_MODEL is required for the provider-substitution probe")

    context = json.load(sys.stdin)
    if not isinstance(context, dict):
        raise ValueError("stdin context must be a JSON object")
    revision = context.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool):
        raise ValueError("context revision must be an integer")
    work_id, work = _bounded_work(context)

    body = json.dumps(
        {
            "model": model,
            "max_tokens": 1400,
            "messages": [{"role": "user", "content": _prompt(context)}],
        }
    ).encode("utf-8")
    safe_model = re.sub(r"[^A-Za-z0-9._-]", "", model)
    if not safe_model:
        raise ValueError("ANTHROPIC_MODEL contains no usable model identifier")

    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=80) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Anthropic API HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Anthropic API transport failure: {error.reason}") from error

    semantic = _semantic_output(_extract_text(payload))
    current_obligations = work.get("open_obligations", [])
    if not isinstance(current_obligations, list) or not all(
        isinstance(item, str) for item in current_obligations
    ):
        raise ValueError("work open_obligations must be a list of strings")

    candidate_action = (
        f"{semantic['chosen_action']} Target: {semantic['target']}. "
        f"Verify: {semantic['verification']}"
    )
    obligations = list(dict.fromkeys([*current_obligations, candidate_action]))
    result_text = (
        f"Reconstruction: {semantic['reconstruction']} "
        f"Chosen action: {semantic['chosen_action']} "
        f"Target: {semantic['target']} "
        f"Verification: {semantic['verification']}"
    )
    json.dump(
        {
            "proposal_id": f"anthropic-{safe_model}-{revision}-{work.get('work_revision', 0)}",
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
