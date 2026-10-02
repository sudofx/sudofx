"""
STATELESS GENERATION PROVIDER BOUNDARY
======================================

Applications own domain meaning; sudofx owns reusable provider execution.

This module contains provider-neutral generation request/response contracts plus
the Gemini transport implementation. It deliberately does not know about WAKE,
Conversation, research policy, work items, or application governance.

Credentials are deployment inputs. They are never persisted, returned in
metadata, or copied into provider-visible context beyond the authenticated HTTP
request itself.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import urllib.error
import urllib.request
from typing import Any, Protocol

from .providers import ProviderError, ProviderQuotaError, ProviderTemporaryError


@dataclass(frozen=True)
class GenerationRequest:
    """
    Describe one stateless generation request without application semantics.

    system and prompt are already-bounded application-provided content.
    response_schema is optional because some deployments deliberately avoid
    vendor schema compilers even when JSON output is requested.
    """

    model: str
    prompt: str
    system: str = ""
    temperature: float = 0.2
    response_mime_type: str = "application/json"
    response_schema: dict[str, Any] | None = None
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class GenerationResponse:
    """Return untrusted provider text plus bounded generic execution metadata."""

    provider: str
    model: str
    text: str


class GenerationProvider(Protocol):
    """Provider-neutral execution surface consumed by applications."""

    def generate(self, request: GenerationRequest) -> GenerationResponse: ...


def sanitize_gemini_model(model: str) -> str:
    """Return one URL-safe Gemini model identifier or fail closed."""

    safe_model = re.sub(r"[^A-Za-z0-9._-]", "", model)
    if not safe_model:
        raise ValueError("Gemini model contains no usable model identifier")
    return safe_model


def build_gemini_request(
    *,
    api_key: str,
    request: GenerationRequest,
) -> tuple[str, urllib.request.Request]:
    """
    Build one Gemini generateContent HTTP request without performing network I/O.

    The API key exists only in the HTTP header. It is intentionally excluded
    from GenerationRequest so application code cannot accidentally persist it as
    request metadata or include it in provider context.
    """

    if not api_key:
        raise ValueError("Gemini API key must not be empty")
    if not isinstance(request.prompt, str) or not request.prompt:
        raise ValueError("generation prompt must be non-empty text")
    if request.temperature < 0:
        raise ValueError("generation temperature must not be negative")
    if request.max_output_tokens is not None and request.max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be positive when supplied")

    safe_model = sanitize_gemini_model(request.model)
    generation: dict[str, Any] = {
        "temperature": request.temperature,
        "responseMimeType": request.response_mime_type,
    }
    if request.response_schema is not None:
        generation["responseJsonSchema"] = request.response_schema
    if request.max_output_tokens is not None:
        generation["maxOutputTokens"] = request.max_output_tokens

    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
        "generationConfig": generation,
    }
    if request.system:
        body["systemInstruction"] = {
            "role": "system",
            "parts": [{"text": request.system}],
        }

    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    http_request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{safe_model}:generateContent",
        data=encoded,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    return safe_model, http_request


def request_gemini_json(
    http_request: urllib.request.Request,
    *,
    timeout: float,
) -> dict[str, Any]:
    """
    Execute one Gemini HTTP request and decode only a successful JSON object.

    Error classification stays in GeminiGenerationProvider because applications
    should receive sudofx's generic provider error categories rather than vendor
    transport exceptions.
    """

    with urllib.request.urlopen(http_request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Gemini response must be a JSON object")
    return payload


def extract_gemini_text(response: dict[str, Any]) -> str:
    """Extract the first non-empty textual Gemini candidate."""

    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ProviderError("Gemini returned no candidates")
    first = candidates[0]
    content = first.get("content") if isinstance(first, dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise ProviderError("Gemini candidate has no content parts")
    text = " ".join(
        str(part.get("text", "")).strip()
        for part in parts
        if isinstance(part, dict) and str(part.get("text", "")).strip()
    ).strip()
    if not text:
        raise ProviderError("Gemini candidate contained no text")
    return text


class GeminiGenerationProvider:
    """
    Execute stateless Gemini generation through the shared sudofx boundary.

    The provider owns vendor HTTP mechanics only. Application prompt policy,
    response interpretation, domain retries, and governance remain outside this
    class unless and until a future generic contract explicitly moves them here.
    """

    provider = "google-gemini"

    def __init__(self, api_key: str, *, timeout_seconds: float = 80.0) -> None:
        if not api_key:
            raise ValueError("Gemini API key must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Perform exactly one stateless vendor request and return untrusted text."""

        safe_model, http_request = build_gemini_request(
            api_key=self._api_key,
            request=request,
        )
        try:
            payload = request_gemini_json(
                http_request,
                timeout=self.timeout_seconds,
            )
        except urllib.error.HTTPError as error:
            if error.code == 429:
                raise ProviderQuotaError("Gemini quota exhausted (HTTP 429)") from error
            if error.code in {500, 502, 503, 504}:
                raise ProviderTemporaryError(
                    f"Gemini temporarily unavailable (HTTP {error.code})"
                ) from error
            raise ProviderError(f"Gemini provider request failed (HTTP {error.code})") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise ProviderTemporaryError("Gemini transport temporarily unavailable") from error
        except json.JSONDecodeError as error:
            raise ProviderError("Gemini returned invalid JSON transport data") from error
        except ValueError as error:
            raise ProviderError(str(error)) from error

        return GenerationResponse(
            provider=self.provider,
            model=safe_model,
            text=extract_gemini_text(payload),
        )
