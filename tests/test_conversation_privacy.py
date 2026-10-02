from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from applications.conversation import (
    CONVERSATION_APPLICATION,
    private_bounded_context,
    private_message_descriptor,
    validate_private_message,
)
from applications.conversation.runtime import commit_assistant_turn, commit_human_turn
from sudofx import ApplicationHost, ApplicationRegistry, Kernel, SubmissionProvenance
from sudofx.governance import Governance
from sudofx.record import Record


class ConversationPrivacyTests(unittest.TestCase):
    def test_direct_identifiers_are_rejected_before_provider_boundary(self) -> None:
        for message in (
            "My email is rob@example.com",
            "Call me at 619-555-1212",
            "My name is Example Person",
            "See https://example.com/private",
            "My SSN is 123-45-6789",
        ):
            with self.subTest(message=message):
                with self.assertRaises(ValueError):
                    validate_private_message(message)

    def test_private_descriptor_contains_no_message_text(self) -> None:
        message = "We are trying to understand whether durable observations preserve continuity."
        descriptor = private_message_descriptor(message)
        self.assertEqual(descriptor["message_chars"], len(message))
        self.assertEqual(len(descriptor["message_digest"]), 64)
        self.assertNotIn(message, json.dumps(descriptor))

    def test_full_private_turn_persists_observations_not_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "record.sqlite"
            human_text = "Earlier we were comparing exact records with bounded observations."
            assistant_text = "Yes. The key question was whether continuity survives without replaying the transcript."
            observation = "The conversation is testing whether bounded observations can preserve continuity without transcript replay."

            commit_human_turn(
                human_text,
                data_path=path,
                private_mode=True,
                provenance=SubmissionProvenance("human", "fixture", "unit-test"),
            )
            provider = (
                sys.executable,
                "-c",
                "import json,sys; data=json.load(sys.stdin); "
                "assert data['state']['app:conversation']['current_message']; "
                f"json.dump({{'content':{assistant_text!r},'observations':[{observation!r}]}}, sys.stdout)",
            )
            reply = commit_assistant_turn(
                data_path=path,
                provider_command=provider,
                private_message=human_text,
                provenance=SubmissionProvenance("model", "fixture", "unit-test"),
            )
            self.assertEqual(reply, assistant_text)

            registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
            kernel = Kernel(Record(path), Governance(application_registry=registry))
            state = ApplicationHost(kernel, registry, "conversation").context().state
            serialized = json.dumps(state, sort_keys=True)
            self.assertNotIn(human_text, serialized)
            self.assertNotIn(assistant_text, serialized)
            self.assertIn(observation, serialized)

            projection = private_bounded_context(state)
            self.assertNotIn("turns", projection)
            self.assertEqual(projection["observations"], [observation])

            # Invocation evidence fingerprints the exact transient context but
            # keeps the message body itself out of lifecycle rows.
            lifecycle = Record(path).invocation_history()
            self.assertEqual(lifecycle[-1]["stage"], "completed")
            self.assertNotIn(human_text, json.dumps(lifecycle, sort_keys=True))
            self.assertNotIn(assistant_text, json.dumps(lifecycle, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
