from __future__ import annotations

import json
import unittest
import urllib.error
from unittest.mock import patch

from scripts.gemini_transport import (
    build_generate_request,
    extract_text,
    request_json,
    sanitize_model,
)
from sudofx import (
    GenerationRequest,
    GeminiGenerationProvider,
    ProviderError,
    ProviderQuotaError,
    ProviderTemporaryError,
)
from sudofx.generation import build_gemini_request


class GeminiTransportTests(unittest.TestCase):
    """Protect the shared sudofx vendor boundary without making live API calls."""

    def test_model_identifier_is_sanitized_and_rejects_empty_result(self) -> None:
        self.assertEqual(sanitize_model("gemini-3.5-flash-lite"), "gemini-3.5-flash-lite")
        self.assertEqual(sanitize_model("gemini model/1"), "geminimodel1")
        with self.assertRaisesRegex(ValueError, "no usable model identifier"):
            sanitize_model(" /// ")

    def test_compatibility_request_routes_through_shared_transport(self) -> None:
        safe_model, request = build_generate_request(
            api_key="test-key",
            model="gemini-test",
            prompt="bounded context only",
            temperature=0.2,
        )
        self.assertEqual(safe_model, "gemini-test")
        self.assertTrue(request.full_url.endswith("/gemini-test:generateContent"))
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            body["contents"],
            [{"role": "user", "parts": [{"text": "bounded context only"}]}],
        )
        self.assertEqual(body["generationConfig"]["temperature"], 0.2)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")

    def test_generic_request_supports_system_schema_and_output_limit(self) -> None:
        safe_model, request = build_gemini_request(
            api_key="deployment-secret",
            request=GenerationRequest(
                model="gemini-test",
                system="application-owned rules",
                prompt="bounded application request",
                temperature=0.1,
                response_schema={"type": "object"},
                max_output_tokens=512,
            ),
        )
        self.assertEqual(safe_model, "gemini-test")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            body["systemInstruction"]["parts"][0]["text"],
            "application-owned rules",
        )
        self.assertEqual(
            body["contents"][0]["parts"][0]["text"],
            "bounded application request",
        )
        self.assertEqual(
            body["generationConfig"]["responseJsonSchema"],
            {"type": "object"},
        )
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 512)
        self.assertNotIn("deployment-secret", request.full_url)
        self.assertNotIn("deployment-secret", request.data.decode("utf-8"))

    def test_request_json_centralizes_only_success_transport(self) -> None:
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            def read(self):
                return b'{"candidates": []}'

        _, request = build_generate_request(
            api_key="test-key",
            model="gemini-test",
            prompt="bounded",
            temperature=0.1,
        )
        with patch("sudofx.generation.urllib.request.urlopen", return_value=Response()) as opened:
            self.assertEqual(request_json(request, timeout=12), {"candidates": []})
        opened.assert_called_once_with(request, timeout=12)

    def test_request_json_rejects_non_object_json(self) -> None:
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            def read(self):
                return b'[]'

        _, request = build_generate_request(
            api_key="test-key",
            model="gemini-test",
            prompt="bounded",
            temperature=0.1,
        )
        with patch("sudofx.generation.urllib.request.urlopen", return_value=Response()):
            with self.assertRaisesRegex(ValueError, "JSON object"):
                request_json(request, timeout=12)

    def test_candidate_text_extraction_fails_closed(self) -> None:
        self.assertEqual(
            extract_text({"candidates": [{"content": {"parts": [{"text": " one "}, {"text": "two"}]}}]}),
            "one two",
        )
        with self.assertRaisesRegex(ProviderError, "no candidates"):
            extract_text({})
        with self.assertRaisesRegex(ProviderError, "contained no text"):
            extract_text({"candidates": [{"content": {"parts": [{"text": "  "}]}}]})

    def test_provider_classifies_vendor_failures_generically(self) -> None:
        provider = GeminiGenerationProvider("test-key", timeout_seconds=5)
        request = GenerationRequest(model="gemini-test", prompt="bounded")

        quota = urllib.error.HTTPError("https://example", 429, "quota", {}, None)
        with patch("sudofx.generation.urllib.request.urlopen", side_effect=quota):
            with self.assertRaises(ProviderQuotaError):
                provider.generate(request)

        unavailable = urllib.error.HTTPError("https://example", 503, "busy", {}, None)
        with patch("sudofx.generation.urllib.request.urlopen", side_effect=unavailable):
            with self.assertRaises(ProviderTemporaryError):
                provider.generate(request)

        bad_request = urllib.error.HTTPError("https://example", 400, "bad", {}, None)
        with patch("sudofx.generation.urllib.request.urlopen", side_effect=bad_request):
            with self.assertRaises(ProviderError):
                provider.generate(request)

    def test_provider_returns_untrusted_text_without_exposing_secret(self) -> None:
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            def read(self):
                return json.dumps({
                    "candidates": [{
                        "content": {"parts": [{"text": '{"ok":true}'}]}
                    }]
                }).encode()

        provider = GeminiGenerationProvider("private-deployment-key", timeout_seconds=5)
        with patch("sudofx.generation.urllib.request.urlopen", return_value=Response()):
            response = provider.generate(
                GenerationRequest(model="gemini-test", prompt="application payload")
            )
        self.assertEqual(response.provider, "google-gemini")
        self.assertEqual(response.model, "gemini-test")
        self.assertEqual(response.text, '{"ok":true}')
        self.assertNotIn("private-deployment-key", repr(response))


if __name__ == "__main__":
    unittest.main()
