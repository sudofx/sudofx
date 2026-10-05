from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ConversationSurfaceTests(unittest.TestCase):
    """Keep the chat transport explicit and browser transcript disposable."""

    def test_surface_supports_private_local_server_without_browser_persistence(self) -> None:
        page = (ROOT / "web" / "conversation.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "assets" / "conversation.js").read_text(encoding="utf-8")
        site_script = (ROOT / "web" / "assets" / "site.js").read_text(encoding="utf-8")
        markdown_script = (ROOT / "web" / "assets" / "conversation-markdown.js").read_text(encoding="utf-8")
        config = (ROOT / "web" / "conversation-config.json").read_text(encoding="utf-8")
        server = (ROOT / "applications" / "conversation" / "server.py").read_text(encoding="utf-8")

        self.assertIn("data-conversation-form", page)
        self.assertIn("/api/conversation/status", script)
        self.assertIn("sendLocal", script)
        self.assertIn("await useLocalTransport()", script)
        self.assertIn("web_capabilities", script)
        self.assertIn("web_privacy_notice", script)
        self.assertIn("error_scope", script)
        self.assertIn("scope+' error: '", script)
        self.assertIn("reply.assistant_number", script)
        self.assertIn("padStart(4,'0')", script)
        self.assertIn("/api/conversation/buffer/clear", script)
        self.assertIn("/api/conversation/matrix/start", server)
        self.assertIn("/api/conversation/matrix/result", server)
        self.assertIn("/api/conversation/matrix/stop", server)
        self.assertIn("item.assistantNumber", markdown_script)
        self.assertIn("padStart(4, '0')", markdown_script)
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
        self.assertIn("event.metaKey||event.ctrlKey", script)
        self.assertIn("key==='c'", script)
        # Keyboard paste belongs exclusively to the browser. An async custom
        # handler can insert clipboard text after native paste already landed,
        # duplicating user input even if it eventually calls preventDefault().
        self.assertNotIn("if(key==='v'", script)
        self.assertIn("data-conversation-export", page)
        self.assertIn("conversation-markdown.js", page)
        self.assertIn("SudofxConversationMarkdown.render", script)
        self.assertIn("SudofxConversationMarkdown.toDocument", script)
        self.assertIn("text/markdown", script)
        self.assertIn("textContent", markdown_script)
        self.assertNotIn("innerHTML", markdown_script)
        self.assertIn("# sudofx Conversation", markdown_script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        self.assertNotIn("GEMINI_API_KEY", script)
        self.assertIn('"gateway_url":""', config.replace(" ", ""))
        self.assertIn("api/site/live", site_script)
        self.assertIn("local.status!==404", site_script)
        self.assertIn("federate:false", site_script)
        self.assertIn("source.federate?await loadFederatedApplications():[]", site_script)
        self.assertIn("/api/site/live", server)


if __name__ == "__main__":
    unittest.main()
