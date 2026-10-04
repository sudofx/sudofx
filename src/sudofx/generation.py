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

from dataclasses import dataclass, field
import errno
import json
import re
import socket
import ssl
import time
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
    temperature: float | None = None
    response_mime_type: str = "application/json"
    response_schema: dict[str, Any] | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationResponse:
    """Return untrusted provider text plus bounded generic execution metadata."""

    provider: str
    model: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


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
    if request.temperature is not None and request.temperature < 0:
        raise ValueError("generation temperature must not be negative")
    if request.max_output_tokens is not None and request.max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be positive when supplied")
    if request.reasoning_effort not in {None, "low", "medium", "high"}:
        raise ValueError("reasoning_effort must be low, medium, high, or None")
    unknown_tools = set(request.tools) - {"read_public_url", "search_public_web"}
    if unknown_tools:
        raise ValueError("generation request contains an unsupported tool")

    safe_model = sanitize_gemini_model(request.model)
    generation: dict[str, Any] = {
        "responseMimeType": request.response_mime_type,
    }
    if request.temperature is not None:
        generation["temperature"] = request.temperature
    if request.response_schema is not None:
        generation["responseJsonSchema"] = request.response_schema
    if request.max_output_tokens is not None:
        generation["maxOutputTokens"] = request.max_output_tokens
    if request.reasoning_effort is not None:
        generation["thinkingConfig"] = {"thinkingLevel": request.reasoning_effort}

    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
        "generationConfig": generation,
    }
    if request.system:
        body["systemInstruction"] = {
            "parts": [{"text": request.system}],
        }
    if request.tools:
        # These names are provider-neutral application capabilities. Gemini's
        # wire spellings remain isolated here so applications do not learn a
        # vendor request schema merely to authorize read-only web evidence.
        vendor_tools = {
            "read_public_url": {"url_context": {}},
            "search_public_web": {"google_search": {}},
        }
        body["tools"] = [vendor_tools[name] for name in request.tools]

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
) -> tuple[dict[str, Any], int]:
    """Execute one Gemini HTTP request and decode a successful JSON object."""

    with urllib.request.urlopen(http_request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200))
        payload = json.loads(response.read(1_000_001))
    if not isinstance(payload, dict):
        raise ValueError("Gemini response must be a JSON object")
    return payload, status


def extract_gemini_text(response: dict[str, Any]) -> str:
    """Extract the first complete non-thought textual Gemini candidate."""

    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ProviderError("Gemini returned no candidates")
    first = candidates[0]
    if not isinstance(first, dict) or first.get("finishReason") not in {None, "STOP"}:
        raise ProviderError("Gemini did not return a complete answer")
    content = first.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise ProviderError("Gemini candidate has no content parts")
    text = "".join(
        str(part.get("text", ""))
        for part in parts
        if isinstance(part, dict)
        and not part.get("thought")
        and isinstance(part.get("text", ""), str)
    ).strip()
    if not text:
        raise ProviderError("Gemini candidate contained no text")
    return text


def extract_gemini_web_evidence(response: dict[str, Any]) -> dict[str, Any]:
    """Return bounded public-source metadata without retaining fetched content."""

    candidates = response.get("candidates")
    first = candidates[0] if isinstance(candidates, list) and candidates else {}
    if not isinstance(first, dict):
        return {"sources": [], "search_queries": [], "url_retrievals": []}

    sources: list[dict[str, str]] = []
    grounding = first.get("groundingMetadata")
    if isinstance(grounding, dict):
        chunks = grounding.get("groundingChunks", [])
        if isinstance(chunks, list):
            for chunk in chunks[:20]:
                web = chunk.get("web") if isinstance(chunk, dict) else None
                uri = web.get("uri") if isinstance(web, dict) else None
                title = web.get("title") if isinstance(web, dict) else None
                if isinstance(uri, str) and uri.startswith("https://"):
                    source = {"url": uri[:2000], "title": title[:200] if isinstance(title, str) else uri[:200]}
                    if source not in sources:
                        sources.append(source)
                if len(sources) >= 12:
                    break
        raw_queries = grounding.get("webSearchQueries", [])
        queries = [item[:500] for item in raw_queries[:8] if isinstance(item, str)] if isinstance(raw_queries, list) else []
    else:
        queries = []

    retrievals: list[dict[str, str]] = []
    url_context = first.get("urlContextMetadata")
    raw_metadata = url_context.get("urlMetadata", []) if isinstance(url_context, dict) else []
    if isinstance(raw_metadata, list):
        for item in raw_metadata[:20]:
            if not isinstance(item, dict):
                continue
            url = item.get("retrievedUrl")
            status = item.get("urlRetrievalStatus")
            if isinstance(url, str) and url.startswith("https://"):
                retrievals.append(
                    {
                        "url": url[:2000],
                        "status": status[:100] if isinstance(status, str) else "unknown",
                    }
                )
                if not any(source["url"] == url for source in sources) and len(sources) < 12:
                    sources.append({"url": url[:2000], "title": url[:200]})
    return {"sources": sources, "search_queries": queries, "url_retrievals": retrievals}


def _safe_error_payload(
    error: urllib.error.HTTPError,
    *,
    secret_values: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Retain bounded provider diagnostics while excluding credentials."""

    try:
        raw = error.read(64_001)
    except Exception:
        raw = b""
    try:
        parsed = json.loads(raw.decode("utf-8", errors="replace")) if raw else {}
    except Exception:
        parsed = {}

    blocked = ("key", "token", "secret", "authorization", "credential")

    def clean(value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "[truncated]"
        if isinstance(value, dict):
            return {
                str(k): clean(v, depth + 1)
                for k, v in value.items()
                if not any(part in str(k).lower() for part in blocked)
            }
        if isinstance(value, list):
            return [clean(v, depth + 1) for v in value[:20]]
        if isinstance(value, str):
            cleaned = value[:1000]
            for secret in secret_values:
                if secret:
                    cleaned = cleaned.replace(secret, "[redacted]")
            return cleaned
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return str(value)[:1000]

    cleaned = clean(parsed) if isinstance(parsed, (dict, list)) else {}
    if isinstance(cleaned, dict) and isinstance(cleaned.get("error"), dict):
        return cleaned["error"]
    return cleaned if isinstance(cleaned, dict) else {}

def _quota_ids(payload: dict[str, Any]) -> list[str]:
    """Extract quota identifiers without requiring an application to parse vendor JSON."""

    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "quotaId" and isinstance(item, str):
                    found.append(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return list(dict.fromkeys(found))


def _raise_with_details(error: Exception, details: dict[str, Any]) -> None:
    error.details = details
    raise error


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
        payload_bytes = len(http_request.data or b"")
        started = time.monotonic()
        base = {
            "provider": self.provider,
            "model": safe_model,
            "request_payload_bytes": payload_bytes,
        }
        try:
            payload, http_status = request_gemini_json(
                http_request,
                timeout=self.timeout_seconds,
            )
        except urllib.error.HTTPError as error:
            provider_error = _safe_error_payload(
                error,
                secret_values=(self._api_key,),
            )
            details = {
                **base,
                "http_status": error.code,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "retry_after": error.headers.get("Retry-After") if error.headers else None,
                "provider_error": provider_error,
                "quota_ids": _quota_ids(provider_error),
            }
            if error.code == 429:
                details["category"] = "quota"
                _raise_with_details(
                    ProviderQuotaError("Gemini quota exhausted (HTTP 429)"),
                    details,
                )
            if error.code in {500, 502, 503, 504}:
                details["category"] = "server"
                _raise_with_details(
                    ProviderTemporaryError(
                        f"Gemini temporarily unavailable (HTTP {error.code})"
                    ),
                    details,
                )
            details["category"] = "http"
            _raise_with_details(
                ProviderError(f"Gemini provider request failed (HTTP {error.code})"),
                details,
            )
        except urllib.error.URLError as error:
            cause = getattr(error, "reason", error)
            transient = (
                isinstance(cause, (TimeoutError, ConnectionError))
                or getattr(cause, "errno", None)
                in {
                    errno.ETIMEDOUT,
                    errno.ECONNRESET,
                    errno.ECONNREFUSED,
                    errno.ECONNABORTED,
                    errno.EHOSTUNREACH,
                    errno.ENETUNREACH,
                    socket.EAI_AGAIN,
                }
            )
            details = {
                **base,
                "http_status": None,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "category": (
                    "timeout"
                    if isinstance(cause, TimeoutError)
                    else "tls"
                    if isinstance(cause, ssl.SSLCertVerificationError)
                    else "connection"
                ),
                "error_type": type(cause).__name__,
            }
            if isinstance(getattr(cause, "errno", None), int):
                details["errno"] = cause.errno
            if transient:
                _raise_with_details(
                    ProviderTemporaryError("Gemini transport temporarily unavailable"),
                    details,
                )
            _raise_with_details(
                ProviderError("Gemini transport failed"),
                details,
            )
        except TimeoutError as error:
            _raise_with_details(
                ProviderTemporaryError("Gemini transport temporarily unavailable"),
                {
                    **base,
                    "http_status": None,
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "category": "timeout",
                    "error_type": type(error).__name__,
                },
            )
        except json.JSONDecodeError as error:
            _raise_with_details(
                ProviderError("Gemini returned invalid JSON transport data"),
                {
                    **base,
                    "http_status": None,
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "category": "invalid_response",
                    "error_type": type(error).__name__,
                },
            )
        except ValueError as error:
            _raise_with_details(
                ProviderError(str(error)),
                {
                    **base,
                    "http_status": None,
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "category": "invalid_response",
                    "error_type": type(error).__name__,
                },
            )

        metadata = {
            **base,
            "http_status": http_status,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "finish_reason": (
                payload.get("candidates", [{}])[0].get("finishReason")
                if isinstance(payload.get("candidates"), list)
                and payload.get("candidates")
                and isinstance(payload.get("candidates")[0], dict)
                else None
            ),
            "usage": payload.get("usageMetadata", {}),
            "model_version": payload.get("modelVersion", safe_model),
            "web_evidence": extract_gemini_web_evidence(payload),
        }
        return GenerationResponse(
            provider=self.provider,
            model=safe_model,
            text=extract_gemini_text(payload),
            metadata=metadata,
        )
