from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from sudofx import FakeIntelligence, FakeWorkIntelligence, Kernel, Operation, Proposal
from sudofx.record import IntegrityError, Record
from sudofx.report import render


class KernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "record.sqlite"
        self.kernel = Kernel(Record(self.path))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_fresh_intelligences_continue_from_durable_context(self) -> None:
        first = FakeIntelligence(
            lambda context: Proposal("p1", context.revision, (Operation("set", "step", 1),))
        )
        second = FakeIntelligence(
            lambda context: Proposal(
                "p2", context.revision, (Operation("set", "step", context.state["step"] + 1),)
            )
        )
        self.assertEqual(self.kernel.run(first).receipt.status, "accepted")
        self.assertEqual(self.kernel.run(second).receipt.status, "accepted")
        self.assertEqual(self.kernel.context().state, {"step": 2})

    def test_replay_survives_kernel_and_provider_replacement(self) -> None:
        proposal = Proposal("p1", 0, (Operation("set", "provider", "fake-a"),))
        self.kernel.run(FakeIntelligence([proposal]))
        replacement = Kernel(Record(self.path))
        replacement.run(
            FakeIntelligence(
                [Proposal("p2", 1, (Operation("set", "provider", "fake-b"),))]
            )
        )
        self.assertEqual(replacement.context().state["provider"], "fake-b")
        self.assertEqual(replacement.context().revision, 2)

    def test_stale_proposal_is_rejected_without_state_change(self) -> None:
        self.kernel.submit(Proposal("p1", 0, (Operation("set", "safe", True),)))
        receipt = self.kernel.submit(Proposal("stale", 0, (Operation("set", "safe", False),)))
        self.assertEqual(receipt.status, "rejected")
        self.assertEqual(receipt.revision_before, receipt.revision_after)
        self.assertEqual(self.kernel.context().state, {"safe": True})
        self.assertEqual(len(self.kernel.context().recent_receipts), 2)

    def test_invalid_proposal_is_recorded_as_rejected(self) -> None:
        receipt = self.kernel.submit(Proposal("empty", 0, ()))
        self.assertEqual(receipt.status, "rejected")
        self.assertIn("at least one operation", receipt.reasons[0])
        self.assertEqual(self.kernel.context().revision, 0)

    def test_duplicate_proposal_id_cannot_be_replayed(self) -> None:
        proposal = Proposal("same", 0, (Operation("set", "x", 1),))
        self.kernel.submit(proposal)
        with self.assertRaises(ValueError):
            self.kernel.submit(proposal)

    def test_hash_chain_detects_tampering(self) -> None:
        self.kernel.submit(Proposal("p1", 0, (Operation("set", "x", 1),)))
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE events SET payload = ? WHERE sequence = 1", ('{}',))
            connection.commit()
        with self.assertRaises(IntegrityError):
            self.kernel.context()

    def test_static_report_exposes_state_and_receipt_provenance(self) -> None:
        self.kernel.submit(Proposal("p1", 0, (Operation("set", "objective", "continue"),)))
        page = render(self.kernel)
        self.assertIn("objective", page)
        self.assertIn("continue", page)
        self.assertIn("proposal p1", page)
        self.assertIn("Run operation", page)
        self.assertIn("wake-theme", page)
        self.assertIn("data-theme=dark", page)
        self.assertIn("width:1px; height:1px", page)
        self.assertIn('class="brand" href="./"', page)
        self.assertIn('href="https://sudofx.github.io/wake/">Inspired by WAKE', page)

    def test_record_initializes_inside_an_existing_empty_directory(self) -> None:
        nested = Path(self.tempdir.name) / "cloud-data" / "record.sqlite"
        nested.parent.mkdir(parents=True)
        kernel = Kernel(Record(nested))
        self.assertEqual(kernel.context().revision, 0)

    def test_disposable_intelligences_advance_one_durable_work_item(self) -> None:
        created = self.kernel.submit(
            Proposal(
                "create",
                0,
                (
                    Operation(
                        "create_work",
                        "launch",
                        {"objective": "Launch the first workflow", "constraints": ["Keep receipts"]},
                    ),
                ),
            )
        )
        self.assertEqual(created.status, "accepted")
        first = FakeWorkIntelligence("launch", "Defined the lifecycle", open_obligations=["Ship UI"])
        second = FakeWorkIntelligence("launch", "Shipped the UI")
        self.assertEqual(self.kernel.run(first).receipt.status, "accepted")
        self.assertEqual(self.kernel.run(second).receipt.status, "accepted")
        work = self.kernel.context().state["work:launch"]
        self.assertEqual(work["accepted_results"], ["Defined the lifecycle", "Shipped the UI"])
        self.assertEqual(work["work_revision"], 2)

    def test_work_completion_closes_obligations_and_blocks_more_progress(self) -> None:
        self.kernel.submit(
            Proposal(
                "create",
                0,
                (Operation("create_work", "done", {"objective": "Finish", "constraints": []}),),
            )
        )
        receipt = self.kernel.submit(
            Proposal("complete", 1, (Operation("complete_work", "done", {"result": "Finished"}),))
        )
        self.assertEqual(receipt.status, "accepted")
        rejected = self.kernel.submit(
            Proposal(
                "late",
                2,
                (Operation("advance_work", "done", {"result": "Too late", "open_obligations": []}),),
            )
        )
        self.assertEqual(rejected.status, "rejected")
        self.assertIn("not open", rejected.reasons[0])
        self.assertEqual(self.kernel.context().state["work:done"]["final_result"], "Finished")

    def test_work_context_is_bounded_to_one_item(self) -> None:
        self.kernel.submit(
            Proposal(
                "a",
                0,
                (Operation("create_work", "a", {"objective": "A", "constraints": []}),),
            )
        )
        self.kernel.submit(
            Proposal(
                "b",
                1,
                (Operation("create_work", "b", {"objective": "B", "constraints": []}),),
            )
        )
        bounded = self.kernel.context(work_id="a", receipt_limit=100)
        self.assertEqual(set(bounded.state), {"work:a"})
        self.assertEqual(len(bounded.recent_receipts), 1)
        self.assertEqual(bounded.recent_receipts[0]["proposal_id"], "a")

    def test_work_lifecycle_is_visible_in_static_report(self) -> None:
        self.kernel.submit(
            Proposal(
                "create",
                0,
                (Operation("create_work", "visible", {"objective": "Visible work", "constraints": []}),),
            )
        )
        page = render(self.kernel)
        self.assertIn("Durable work", page)
        self.assertIn("Visible work", page)
        self.assertIn("Create or advance", page)


if __name__ == "__main__":
    unittest.main()
