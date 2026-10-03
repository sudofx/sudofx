from __future__ import annotations

from datetime import datetime, timezone
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

            started_at = datetime.now(timezone.utc)
            first = service.converse("First, compare blue and green for this continuity test.")
            second = service.converse("What were we trying to figure out earlier?")

            # Transport timestamps bracket completed governed work in UTC;
            # they are metadata, not a transcript or a second durable record.
            for result in (first, second):
                received = datetime.fromisoformat(result["received_at"])
                completed = datetime.fromisoformat(result["completed_at"])
                self.assertEqual(received.utcoffset(), timezone.utc.utcoffset(received))
                self.assertLessEqual(started_at.replace(microsecond=0), received)
                self.assertLessEqual(received, completed)
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

    def test_persistent_response_suffix_is_governed_until_revoked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "conversation.sqlite"
            footer = "My nickname is Stereo, and we are many. 🙂"
            provider = (
                sys.executable,
                "-c",
                "import json,sys; d=json.load(sys.stdin); "
                "s=d['state']['app:conversation']; m=s['current_message']; "
                "active=s.get('active_commitments',[]); "
                "updates=([{'op':'upsert','kind':'response_suffix','text':" + repr(footer) + "}] "
                "if m.startswith('Set footer') else "
                "([{'op':'clear','kind':'response_suffix'}] if m.startswith('Stop footer') else [])); "
                "content=('Footer set.' if m.startswith('Set footer') else "
                "('Footer stopped.' if m.startswith('Stop footer') else 'A fresh provider forgot the footer.')); "
                "json.dump({'content':content,'observations':[],'commitment_updates':updates},sys.stdout)",
            )
            service = ConversationService(database, provider_command=provider)

            first = service.converse("Set footer for every response until I tell you to stop.")
            second = service.converse("Are you sure?")
            third = service.converse("Stop footer now.")
            fourth = service.converse("Is it gone?")

            self.assertTrue(first["content"].endswith(footer))
            self.assertTrue(second["content"].endswith(footer))
            self.assertEqual(third["content"], "Footer stopped.")
            self.assertEqual(fourth["content"], "A fresh provider forgot the footer.")

            registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
            kernel = Kernel(Record(database), Governance(application_registry=registry))
            state = ApplicationHost(kernel, registry, "conversation").context().state
            privacy = state["privacy"]
            self.assertEqual(privacy["commitments"], [])

    def test_flat_provider_commitment_shape_is_governed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "conversation.sqlite"
            footer = "Persistent footer."
            provider = (
                sys.executable,
                "-c",
                "import json,sys; json.load(sys.stdin); "
                "json.dump({'content':'Okay.','observations':[],'response_suffix':" + repr(footer) + ",'clear_response_suffix':False},sys.stdout)",
            )
            service = ConversationService(database, provider_command=provider)
            result = service.converse("Keep a footer active.")
            self.assertTrue(result["content"].endswith(footer))

    def test_provider_failure_does_not_wedge_next_role(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "conversation.sqlite"
            failing_provider = (
                sys.executable,
                "-c",
                "import sys; sys.exit(1)",
            )
            service = ConversationService(database, provider_command=failing_provider)

            with self.assertRaises(Exception):
                service.converse("Hello")

            status = service.status()
            self.assertEqual(status["next_role"], "human")
            self.assertTrue(status["provider_configured"])

    def test_startup_recovers_orphaned_pending_assistant_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "conversation.sqlite"
            from applications.conversation.runtime import commit_human_turn

            commit_human_turn("Hello", data_path=database, private_mode=True)
            service = ConversationService(
                database,
                provider_command=(sys.executable, "-c", "import sys; sys.exit(0)"),
            )
            self.assertEqual(service.status()["next_role"], "human")

    def test_direct_identifier_is_rejected_before_provider_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = ConversationService(Path(temporary) / "conversation.sqlite")
            with self.assertRaises(ValueError):
                service.converse("My email is private@example.com")


if __name__ == "__main__":
    unittest.main()
