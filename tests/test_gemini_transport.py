from __future__ import annotations

import json
import unittest

from scripts.gemini_transport import build_generate_request, extract_text, sanitize_model


class GeminiTransportTests(unittest.TestCase):
    """Protect vendor transport mechanics without making live API calls."""

    def test_model_identifier_is_sanitized_and_rejects_empty_result(self) -> None:
        self.assertEqual(sanitize_model("gemini-3.5-flash-lite"), "gemini-3.5-flash-lite")
        self.assertEqual(sanitize_model("gemini model/1"), "geminimodel1")
        with self.assertRaisesRegex(ValueError, "no usable model identifier"):
            sanitize_model(" /// ")

    def test_request_contains_only_supplied_prompt_and_transport_configuration(self) -> None:
        safe_model, request = build_generate_request(
            api_key="test-key",
            model="gemini-test",
            prompt="bounded context only",
            temperature=0.2,
        )
        self.assertEqual(safe_model, "gemini-test")
        self.assertTrue(request.full_url.endswith("/gemini-test:generateContent"))
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["contents"], [{"parts": [{"text": "bounded context only"}]}])
        self.assertEqual(body["generationConfig"]["temperature"], 0.2)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")

    def test_candidate_text_extraction_fails_closed(self) -> None:
        self.assertEqual(
            extract_text({"candidates": [{"content": {"parts": [{"text": " one "}, {"text": "two"}]}}]}),
            "one two",
        )
        with self.assertRaisesRegex(ValueError, "no candidates"):
            extract_text({})
        with self.assertRaisesRegex(ValueError, "contained no text"):
            extract_text({"candidates": [{"content": {"parts": [{"text": "  "}]}}]})


if __name__ == "__main__":
    unittest.main()
