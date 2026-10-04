from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from applications.conversation import (
    CONVERSATION_APPLICATION,
    conversation_web_tools,
    private_bounded_context,
    private_message_descriptor,
    validate_private_message,
)
from applications.conversation.runtime import (
    commit_assistant_turn,
    commit_human_turn,
    recover_failed_private_turn,
    recover_rejected_private_turn,
)
from applications.conversation.server import ConversationService
from sudofx import ApplicationHost, ApplicationRegistry, Kernel, SubmissionProvenance
from sudofx.governance import Governance
from sudofx.record import Record


class ConversationPrivacyTests(unittest.TestCase):
    def test_direct_identifiers_are_rejected_before_provider_boundary(self) -> None:
        for message in (
            "My email is rob@example.com",
            "Call me at 619-555-1212",
            "My name is Example Person",
            "My SSN is 123-45-6789",
        ):
            with self.subTest(message=message):
                with self.assertRaises(ValueError):
                    validate_private_message(message)

    def test_public_web_targets_are_explicit_and_private_targets_fail_closed(self) -> None:
        github = "https://github.com/sudofx/wake"
        self.assertEqual(validate_private_message(github), github)
        self.assertEqual(conversation_web_tools(github), ("read_public_url",))
        self.assertEqual(
            conversation_web_tools("Search the web for current sudofx documentation"),
            ("search_public_web",),
        )
        self.assertEqual(
            conversation_web_tools(f"Search the web and compare {github}"),
            ("read_public_url", "search_public_web"),
        )
        for unsafe in (
            "http://example.com",
            "https://localhost/private",
            "https://127.0.0.1/private",
            "https://user:password@example.com/private",
            "https://example.com/?access_token=secret",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ValueError):
                    validate_private_message(unsafe)

    def test_private_descriptor_contains_no_message_text(self) -> None:
        message = "We are trying to understand whether durable observations preserve continuity."
        descriptor = private_message_descriptor(message)
        self.assertEqual(descriptor["message_chars"], len(message))
        self.assertEqual(len(descriptor["message_digest"]), 64)
        self.assertNotIn(message, json.dumps(descriptor))

    def test_web_citations_are_transient_and_never_become_observations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "record.sqlite"
            url = "https://github.com/sudofx/wake"
            commit_human_turn(
                f"Read {url}",
                data_path=path,
                private_mode=True,
                provenance=SubmissionProvenance("human", "fixture", "unit-test"),
            )
            provider = (
                sys.executable,
                "-c",
                "import json,sys; json.load(sys.stdin); json.dump({"
                "'content':'WAKE is a public repository.',"
                "'observations':['https://github.com/sudofx/wake'],"
                "'commitment_updates':[],"
                "'sources':[{'url':'https://github.com/sudofx/wake','title':'WAKE'}]"
                "},sys.stdout)",
            )
            reply = commit_assistant_turn(
                data_path=path,
                provider_command=provider,
                private_message=f"Read {url}",
                provenance=SubmissionProvenance("model", "fixture", "unit-test"),
            )
            self.assertIn("[WAKE](https://github.com/sudofx/wake)", reply)

            registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
            kernel = Kernel(Record(path), Governance(application_registry=registry))
            state = ApplicationHost(kernel, registry, "conversation").context().state
            self.assertEqual(private_bounded_context(state)["observations"], [])
            self.assertNotIn(url, json.dumps(state, sort_keys=True))

    def test_private_http_service_uses_one_sqlite_authority_without_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "conversation.sqlite"
            provider = (
                sys.executable,
                "-c",
                "import json,sys; data=json.load(sys.stdin); "
                "json.dump({'content':'Recovered continuity','observations':['The user is testing continuity across fresh provider calls.']}, sys.stdout)",
            )
            service = ConversationService(path, provider_command=provider)
            result = service.converse("Are we still testing continuity?")
            self.assertEqual(result["content"], "Recovered continuity")
            self.assertEqual(result["status"]["turn_count"], 2)
            self.assertEqual(result["status"]["provider_invocations"], 1)
            self.assertFalse(result["status"]["transcript_persisted"])

            registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
            kernel = Kernel(Record(path), Governance(application_registry=registry))
            state = ApplicationHost(kernel, registry, "conversation").context().state
            serialized = json.dumps(state, sort_keys=True)
            self.assertNotIn("Are we still testing continuity?", serialized)
            self.assertNotIn("Recovered continuity", serialized)

    def test_governance_rejection_recovery_is_not_provider_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "record.sqlite"
            commit_human_turn(
                "Test a governed rejection without storing transcript text.",
                data_path=path,
                private_mode=True,
                provenance=SubmissionProvenance("human", "fixture", "unit-test"),
            )

            recover_rejected_private_turn(
                data_path=path,
                receipt_id="receipt-governance-rejected",
            )

            registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
            kernel = Kernel(Record(path), Governance(application_registry=registry))
            state = ApplicationHost(kernel, registry, "conversation").context().state
            privacy = state["privacy"]
            self.assertEqual(privacy["next_role"], "human")
            self.assertEqual(
                privacy["last_governance_rejection"],
                {"receipt_id": "receipt-governance-rejected"},
            )
            self.assertNotIn("last_provider_failure", privacy)

    def test_provider_failure_recovery_remains_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "record.sqlite"
            commit_human_turn(
                "Test provider failure classification separately.",
                data_path=path,
                private_mode=True,
                provenance=SubmissionProvenance("human", "fixture", "unit-test"),
            )

            recover_failed_private_turn(
                data_path=path,
                category="ProviderTemporaryError",
            )

            registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
            kernel = Kernel(Record(path), Governance(application_registry=registry))
            state = ApplicationHost(kernel, registry, "conversation").context().state
            privacy = state["privacy"]
            self.assertEqual(privacy["next_role"], "human")
            self.assertEqual(
                privacy["last_provider_failure"],
                {"category": "ProviderTemporaryError"},
            )
            self.assertNotIn("last_governance_rejection", privacy)

    def test_unsupported_provider_observation_never_enters_durable_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "record.sqlite"
            human_text = "I like reggae and writing code."
            commit_human_turn(
                human_text,
                data_path=path,
                private_mode=True,
                provenance=SubmissionProvenance("human", "fixture", "unit-test"),
            )
            provider = (
                sys.executable,
                "-c",
                "import json,sys; json.load(sys.stdin); "
                "json.dump({'content':'Understood.','observations':['The user likes jazz.']},sys.stdout)",
            )
            reply = commit_assistant_turn(
                data_path=path,
                provider_command=provider,
                private_message=human_text,
                provenance=SubmissionProvenance("model", "fixture", "unit-test"),
            )
            self.assertEqual(reply, "Understood.")

            registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
            kernel = Kernel(Record(path), Governance(application_registry=registry))
            state = ApplicationHost(kernel, registry, "conversation").context().state
            projection = private_bounded_context(state)
            self.assertEqual(projection["observations"], [])
            self.assertNotIn("jazz", json.dumps(Record(path).history(), sort_keys=True).lower())

    def test_legacy_unverified_observations_are_not_replayed_to_provider_context(self) -> None:
        state = {
            "privacy": {
                "turn_count": 2,
                "next_role": "human",
                "observations": ["The user likes jazz and mechanical keyboards."],
                "commitments": [],
            }
        }
        projection = private_bounded_context(state)
        self.assertEqual(projection["observations"], [])
        self.assertEqual(projection["observation_count"], 0)
        self.assertEqual(projection["legacy_unverified_observation_count"], 1)


    def test_full_private_turn_persists_observations_not_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "record.sqlite"
            human_text = (
                "Earlier we were comparing exact records with bounded observations. "
                "Please preserve only the first sentence as durable context."
            )
            assistant_text = "Yes. The key question was whether continuity survives without replaying the transcript."
            observation = "Earlier we were comparing exact records with bounded observations."

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
            self.assertEqual(projection["observation_provenance"][0]["text"], observation)
            self.assertEqual(
                projection["observation_provenance"][0]["support"],
                "exact_excerpt",
            )

            # Invocation evidence fingerprints the exact transient context but
            # keeps the message body itself out of lifecycle rows.
            lifecycle = Record(path).invocation_history()
            self.assertEqual(lifecycle[-1]["stage"], "completed")
            self.assertNotIn(human_text, json.dumps(lifecycle, sort_keys=True))
            self.assertNotIn(assistant_text, json.dumps(lifecycle, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
