"""Shared Gemini HTTP mechanics for disposable provider adapters.

This module is deliberately outside the sudofx kernel. It owns only vendor
transport mechanics that are identical across current experiments: model-name
sanitization, request construction, and extraction of textual candidate output.

Prompt policy, retry policy, quota semantics, proposal shaping, governance, and
durable state remain with their respective callers. Keeping those concerns out
of this helper prevents a convenience refactor from turning Gemini behavior
into an engine contract.
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any


def sanitize_model(model: str) -> str:
    """Return the URL-safe Gemini model identifier or fail closed."""
    safe_model = re.sub(r"[^A-Za-z0-9._-]", "", model)
    if not safe_model:
        raise ValueError("GEMINI_MODEL contains no usable model identifier")
    return safe_model


def build_generate_request(
    *,
    api_key: str,
    model: str,
    prompt: str,
    temperature: float,
) -> tuple[str, urllib.request.Request]:
    """Build one generateContent request without performing network I/O."""
    safe_model = sanitize_model(model)
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{safe_model}:generateContent",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    return safe_model, request


def request_json(request: urllib.request.Request, *, timeout: float) -> dict[str, Any]:
    """Execute one Gemini request and decode a JSON object.

    Error classification, retries, and quota policy stay with the caller. This
    helper centralizes only the transport-success path shared by all adapters.
    """
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Gemini response must be a JSON object")
    return payload


def extract_text(response: dict[str, Any]) -> str:
    """Extract the first non-empty textual candidate from generateContent."""
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
