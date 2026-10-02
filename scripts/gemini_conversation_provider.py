"""Disposable Gemini adapter for the governed conversation proof."""

from __future__ import annotations

import json
import os
import sys
import urllib.error

from gemini_transport import build_generate_request, extract_text, request_json


def _prompt(context: dict[str, object]) -> str:
    return (
        "You are a stateless assistant in a sudofx continuity proof. You have no "
        "memory or hidden conversation beyond the bounded durable context below. "
        "Reply to the latest human message. If older turns were omitted, do not "
        "pretend to know their contents. Return ONLY JSON with exactly one field: "
        "{\\\"content\\\":\\\"your reply\\\"}.\\n\\nBOUNDED CONTEXT:\\n"
        + json.dumps(context, ensure_ascii=False, sort_keys=True)
    )


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    model = os.environ.get("GEMINI_MODEL", "").strip()
    if not api_key or not model:
        raise RuntimeError("GEMINI_API_KEY and GEMINI_MODEL are required")
    context = json.load(sys.stdin)
    if not isinstance(context, dict):
        raise ValueError("stdin context must be an object")

    _, request = build_generate_request(
        api_key=api_key,
        model=model,
        prompt=_prompt(context),
        temperature=0.4,
    )
    try:
        payload = request_json(request, timeout=80)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            return 78
        if 500 <= error.code < 600:
            return 75
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Gemini API HTTP {error.code}: {detail}") from error
    except urllib.error.URLError:
        return 75

    raw = extract_text(payload)
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or set(value) != {"content"}
        or not isinstance(value["content"], str)
        or not value["content"].strip()
    ):
        raise ValueError("Gemini conversation output must contain one non-empty content field")
    json.dump({"content": value["content"].strip()}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
