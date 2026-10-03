"""Executable invariants for the global sudofx application kill switch."""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from sudofx import Kernel, Operation, Proposal, SubmissionProvenance
from sudofx.record import Record
from sudofx.storage import ApplicationAccessError


class ApplicationAccessTests(unittest.TestCase):
    """Prove that app access is authoritative, fail-closed, and generation-bound."""

    def make_kernel(self) -> Kernel:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        return Kernel(Record(Path(self.temp.name) / "record.sqlite"))

    @staticmethod
    def proposal(kernel: Kernel, key: str = "operator-note") -> Proposal:
        context = kernel.context()
        return Proposal(
            str(uuid.uuid4()),
            context.revision,
            (Operation("set", key, "value"),),
            "application access invariant probe",
        )

    def test_access_defaults_enabled_without_semantic_revision(self) -> None:
        kernel = self.make_kernel()
        state = kernel.application_access_state()
        self.assertTrue(state.enabled)
        self.assertEqual(state.generation, 0)
        self.assertEqual(kernel.context().revision, 0)

    def test_stop_blocks_application_submission_but_not_operator_submission(self) -> None:
        kernel = self.make_kernel()
        stopped = kernel.record.set_application_access(
            False,
            actor="operator",
            reason="test stop",
        )
        self.assertFalse(stopped.enabled)
        self.assertEqual(stopped.generation, 1)

        with self.assertRaises(ApplicationAccessError) as caught:
            kernel.submit(
                self.proposal(kernel, "app-write"),
                provenance=SubmissionProvenance("application", "test-app", "tests"),
                application_access_generation=stopped.generation,
            )
        self.assertEqual(caught.exception.code, "SUDOFX_EXTERNAL_ACCESS_DISABLED")

        receipt = kernel.submit(
            self.proposal(kernel, "operator-write"),
            provenance=SubmissionProvenance("human", "operator", "tests"),
        )
        self.assertEqual(receipt.status, "accepted")

    def test_stop_then_start_invalidates_inflight_generation(self) -> None:
        kernel = self.make_kernel()
        captured = kernel.application_access_state()
        kernel.record.set_application_access(False, actor="operator", reason="stop")
        restarted = kernel.record.set_application_access(True, actor="operator", reason="resume")
        self.assertTrue(restarted.enabled)
        self.assertEqual(restarted.generation, captured.generation + 2)

        with self.assertRaises(ApplicationAccessError):
            kernel.submit(
                self.proposal(kernel, "stale-inflight"),
                provenance=SubmissionProvenance("application", "test-app", "tests"),
                application_access_generation=captured.generation,
            )

        receipt = kernel.submit(
            self.proposal(kernel, "fresh-app"),
            provenance=SubmissionProvenance("application", "test-app", "tests"),
            application_access_generation=restarted.generation,
        )
        self.assertEqual(receipt.status, "accepted")

    def test_repeating_same_state_does_not_churn_generation(self) -> None:
        kernel = self.make_kernel()
        first = kernel.record.set_application_access(False, actor="operator")
        second = kernel.record.set_application_access(False, actor="operator")
        self.assertEqual(second.generation, first.generation)


if __name__ == "__main__":
    unittest.main()
