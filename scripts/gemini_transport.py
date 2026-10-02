"""Compatibility facade over sudofx's shared Gemini transport.

New provider transport lives in the installed sudofx package. This script-level
module remains temporarily so existing experiment adapters and tests can migrate
without duplicating vendor HTTP mechanics.
"""

from __future__ import annotations

from sudofx.generation import (
    GenerationRequest,
    build_gemini_request,
    extract_gemini_text,
    request_gemini_json,
    sanitize_gemini_model,
)


def sanitize_model(model: str) -> str:
    return sanitize_gemini_model(model)


def build_generate_request(*, api_key: str, model: str, prompt: str, temperature: float):
    return build_gemini_request(
        api_key=api_key,
        request=GenerationRequest(
            model=model,
            prompt=prompt,
            temperature=temperature,
            response_mime_type="application/json",
        ),
    )


def request_json(request, *, timeout: float):
    return request_gemini_json(request, timeout=timeout)


def extract_text(response):
    return extract_gemini_text(response)
