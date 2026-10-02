from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ConversationSurfaceTests(unittest.TestCase):
    """Keep the chat transport explicit and browser transcript disposable."""

    def test_surface_supports_private_local_server_without_browser_persistence(self) -> None:
        page = (ROOT / "web" / "conversation.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "assets" / "conversation.js").read_text(encoding="utf-8")
        config = (ROOT / "web" / "conversation-config.json").read_text(encoding="utf-8")

        self.assertIn("data-conversation-form", page)
        self.assertIn("/api/conversation/status", script)
        self.assertIn("sendLocal", script)
        self.assertIn("await useLocalTransport()", script)
        self.assertNotIn("location.hostname===\'localhost\'", script)
        self.assertIn("conversation-config.json", script)
        self.assertIn("codespaces_url", script)
        self.assertIn("codespaces.new/sudofx/sudofx", config)
        self.assertIn("event.key!=='Enter'", script)
        self.assertIn("event.shiftKey", script)
        self.assertIn("form.requestSubmit()", script)
        self.assertIn("data-conversation-popout", page)
        self.assertIn("popoutMode", script)
        self.assertIn("window.open", script)
        self.assertIn("data-conversation-paste", page)
        self.assertIn("navigator.clipboard.writeText", script)
        self.assertIn("navigator.clipboard.readText", script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        self.assertNotIn("GEMINI_API_KEY", script)
        self.assertIn('"gateway_url":""', config.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
