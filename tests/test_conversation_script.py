from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ConversationScriptTests(unittest.TestCase):
    def test_launcher_restarts_and_reset_is_scoped_to_conversation_db(self) -> None:
        script = (ROOT / "scripts" / "conversation.sh").read_text(encoding="utf-8")
        codespace_start = (ROOT / ".devcontainer" / "start-conversation.sh").read_text(encoding="utf-8")
        devcontainer = (ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8")

        self.assertIn("--reset|—reset", script)
        self.assertIn("pkill -f 'python .*applications\\.conversation\\.server'", script)
        self.assertIn('git pull --ff-only origin master', script)
        self.assertIn('DB="$ROOT/.data/conversation.sqlite"', script)
        self.assertIn('rm -f "$DB" "$DB-wal" "$DB-shm"', script)
        self.assertNotIn('rm -rf "$ROOT/.data"', script)
        self.assertIn("python -m applications.conversation.server", script)
        self.assertIn("--host 0.0.0.0", script)
        self.assertIn('--port "$PORT"', script)
        self.assertIn('GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.5-flash-lite}"', codespace_start)
        self.assertIn('GEMINI_MODEL="$GEMINI_MODEL"', codespace_start)
        self.assertIn('"protocol": "http"', devcontainer)
        self.assertIn('"onAutoForward": "notify"', devcontainer)
        self.assertIn("http://localhost:8765/conversation", codespace_start)
        self.assertIn('http://localhost:$PORT/conversation', script)


if __name__ == "__main__":
    unittest.main()
