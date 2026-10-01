from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from sudofx import (
    FakeIntelligence,
    Kernel,
    Operation,
    Proposal,
    ProviderError,
    Runtime,
    SubmissionProvenance,
)
from sudofx.record import IntegrityError, Record


class RuntimeInvocationTests(unittest.TestCase):
    """Protect lifecycle evidence independently from governed state revisions."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "runtime.sqlite"
        self.record = Record(self.path)
        self.kernel = Kernel(self.record)
        self.runtime = Runtime(self.kernel)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_successful_invocation_records_context_proposal_and_completion(self) -> None:
        provider = FakeIntelligence(
            [
                Proposal(
                    "runtime-success",
                    0,
                    (Operation("set", "answer", "carried"),),
                    "bounded provider proposal",
                )
            ]
        )
        result = self.runtime.run(
            provider,
            provenance=SubmissionProvenance("model", "fixture-provider", "fixture-model"),
        )
        self.assertEqual(result.receipt.status, "accepted")
        self.assertEqual(self.kernel.context().state, {"answer": "carried"})

        history = self.record.invocation_history()
        self.assertEqual([item["phase"] for item in history], ["started", "proposal_received", "completed"])
        started = history[0]["payload"]
        self.assertEqual(started["source_revision"], 0)
        self.assertEqual(started["receipt_count"], 0)
        self.assertEqual(started["state_keys"], [])
        self.assertEqual(
            started["provenance"],
            {"origin": "model", "actor": "fixture-provider", "source": "fixture-model"},
        )
        self.assertGreater(started["context_bytes"], 0)
        self.assertEqual(len(started["context_digest"]), 64)
        self.assertEqual(history[1]["payload"]["proposal_id"], "runtime-success")
        self.assertEqual(history[2]["payload"]["receipt_id"], result.receipt.receipt_id)
        self.assertEqual(history[2]["payload"]["receipt_status"], "accepted")

    def test_provider_failure_is_durable_without_fabricating_proposal_receipt(self) -> None:
        class BrokenProvider:
            def propose(self, context):
                raise ProviderError("transient detail that must not become durable")

        with self.assertRaises(ProviderError):
            self.runtime.run(
                BrokenProvider(),
                provenance=SubmissionProvenance("model", "broken-provider", "fixture-model"),
            )

        self.assertEqual(self.kernel.context().revision, 0)
        self.assertEqual(self.record.history(), ())
        lifecycle = self.record.invocation_history()
        self.assertEqual([item["phase"] for item in lifecycle], ["started", "failed"])
        self.assertEqual(lifecycle[-1]["payload"]["stage"], "provider")
        self.assertEqual(lifecycle[-1]["payload"]["error_type"], "ProviderError")
        self.assertNotIn("transient detail", json.dumps(lifecycle[-1]["payload"]))

    def test_fresh_runtime_marks_abandoned_invocation_interrupted_without_guessing(self) -> None:
        started = self.record.append_invocation_event(
            "abandoned",
            "started",
            {
                "source_revision": 0,
                "context_digest": "0" * 64,
                "context_bytes": 1,
            },
        )
        self.assertEqual(started["phase"], "started")
        recovered = Runtime(Kernel(Record(self.path))).recover_incomplete_invocations()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["phase"], "interrupted")
        self.assertFalse(recovered[0]["payload"]["external_success_assumed"])
        self.assertEqual(self.record.incomplete_invocations(), ())

    def test_proposal_received_can_be_recovered_as_interrupted_without_assuming_commit(self) -> None:
        self.record.append_invocation_event("uncertain", "started", {"source_revision": 0})
        self.record.append_invocation_event(
            "uncertain",
            "proposal_received",
            {"proposal_id": "may-or-may-not-have-committed"},
        )
        recovered = self.runtime.recover_incomplete_invocations()
        self.assertEqual(recovered[0]["payload"]["observed_prior_phase"], "proposal_received")
        self.assertFalse(recovered[0]["payload"]["external_success_assumed"])

    def test_invocation_hash_chain_detects_tampering(self) -> None:
        self.record.append_invocation_event("tamper", "started", {"source_revision": 0})
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "UPDATE invocation_events SET payload = ? WHERE sequence = 1",
                (json.dumps({"source_revision": 999}),),
            )
            connection.commit()
        with self.assertRaises(IntegrityError):
            self.record.invocation_history()


if __name__ == "__main__":
    unittest.main()
