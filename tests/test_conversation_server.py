from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from applications.conversation import CONVERSATION_APPLICATION
from applications.conversation.server import ConversationService
from sudofx import ApplicationHost, ApplicationRegistry, Kernel
from sudofx.governance import Governance
from sudofx.record import Record


class ConversationServerTests(unittest.TestCase):
    """Protect the private chat's stateless-provider and no-transcript guarantees."""

    def test_popout_route_uses_path_without_query(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "applications" / "conversation" / "server.py").read_text(encoding="utf-8")
        self.assertIn("requested = urlsplit(self.path)", source)
        self.assertIn('requested.path in {"/", "/conversation"}', source)

    def test_two_turn_continuity_uses_observations_not_transcript_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "conversation.sqlite"
            provider = (
                sys.executable,
                "-c",
                "import json,sys; d=json.load(sys.stdin); "
                "s=d['state']['app:conversation']; m=s['current_message']; "
                "obs=s.get('observations',[]); "
                "out=({'content':'Saved.','observations':['The test is comparing blue and green.']} "
                "if m.startswith('First') else "
                "({'content':'We were comparing blue and green.','observations':[]} "
                "if 'The test is comparing blue and green.' in obs else "
                "{'content':'Continuity missing.','observations':[]})); "
                "json.dump(out,sys.stdout)",
            )
            service = ConversationService(database, provider_command=provider)

            first = service.converse("First, compare blue and green for this continuity test.")
            second = service.converse("What were we trying to figure out earlier?")

            self.assertEqual(first["content"], "Saved.")
            self.assertEqual(second["content"], "We were comparing blue and green.")
            self.assertEqual(second["status"]["turn_count"], 4)
            self.assertEqual(second["status"]["provider_invocations"], 2)
            self.assertFalse(second["status"]["transcript_persisted"])

            registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
            kernel = Kernel(Record(database), Governance(application_registry=registry))
            state = ApplicationHost(kernel, registry, "conversation").context().state
            serialized = json.dumps(state, sort_keys=True)
            self.assertNotIn("First, compare blue and green", serialized)
            self.assertNotIn("What were we trying to figure out earlier?", serialized)
            self.assertNotIn("We were comparing blue and green.", serialized)
            self.assertIn("The test is comparing blue and green.", serialized)

    def test_direct_identifier_is_rejected_before_provider_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = ConversationService(Path(temporary) / "conversation.sqlite")
            with self.assertRaises(ValueError):
                service.converse("My email is private@example.com")


if __name__ == "__main__":
    unittest.main()
