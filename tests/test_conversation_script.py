from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ConversationScriptTests(unittest.TestCase):
    def test_launcher_restarts_and_reset_is_scoped_to_conversation_db(self) -> None:
        script = (ROOT / "scripts" / "conversation.sh").read_text(encoding="utf-8")

        self.assertIn("--reset|—reset", script)
        self.assertIn("pkill -f 'python .*applications\\.conversation\\.server'", script)
        self.assertIn('git pull --ff-only origin master', script)
        self.assertIn('DB="$ROOT/.data/conversation.sqlite"', script)
        self.assertIn('rm -f "$DB" "$DB-wal" "$DB-shm"', script)
        self.assertNotIn('rm -rf "$ROOT/.data"', script)
        self.assertIn("python -m applications.conversation.server", script)
        self.assertIn("--host 0.0.0.0", script)
        self.assertIn('--port "$PORT"', script)


if __name__ == "__main__":
    unittest.main()
