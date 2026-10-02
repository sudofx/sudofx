from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from applications.handoff import (
    DIMENSIONS,
    HandoffService,
    build_handoff_packet,
    build_manual_evaluation_projection,
    evaluate_handoff_response,
)
from sudofx import Kernel, Operation, Proposal
from sudofx.record import Record


class HandoffApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "record.sqlite"
        self.kernel = Kernel(Record(self.path))
        receipt = self.kernel.submit(
            Proposal(
                "create-work",
                0,
                (
                    Operation(
                        "create_work",
                        "handoff-v1",
                        {
                            "objective": "Carry useful governed context to a fresh intelligence",
                            "constraints": ["Unknown means unknown"],
                        },
                    ),
                ),
            )
        )
        self.assertEqual(receipt.status, "accepted")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _evaluation(self) -> dict[str, object]:
        packet = build_handoff_packet(self.kernel, "handoff-v1")
        evidence = packet["work"]["objective"]
        response = {
            "test_id": "UUID-123456",
            "nonce": "HANDOFF-UUID-123456",
            "vendor": "ChatGPT",
            "work_id": packet["work_id"],
            "packet_digest": packet["packet_digest"],
            "answers": {
                dimension: {"answer": f"Grounded {dimension}", "evidence": evidence}
                for dimension in DIMENSIONS
            },
        }
        return evaluate_handoff_response(json.dumps(response), packet)

    def test_new_evaluation_is_application_state_not_work_state(self) -> None:
        result = self._evaluation()
        receipt = HandoffService(self.kernel).record_evaluation("handoff-v1", result)
        self.assertEqual(receipt.status, "accepted")

        state = self.kernel.context().state
        work = state["work:handoff-v1"]
        self.assertEqual(work.get("handoff_evaluations", []), [])

        envelope = state["app:handoff"]
        self.assertEqual(envelope["application_id"], "handoff")
        projection = envelope["projection_state"]
        saved = projection["targets"]["handoff-v1"]["evaluations"][0]
        self.assertEqual(saved["test_id"], "UUID-123456")
        self.assertEqual(saved["score"], 7)

    def test_projection_reads_application_evidence(self) -> None:
        HandoffService(self.kernel).record_evaluation("handoff-v1", self._evaluation())
        projection = build_manual_evaluation_projection(self.kernel, "handoff-v1")
        self.assertEqual(projection["application_id"], "handoff")
        self.assertEqual(projection["total_tests"], 1)
        self.assertEqual(projection["comparable_batch"]["score"], 7)
        self.assertEqual(projection["comparable_batch"]["max_score"], 7)

    def test_legacy_work_operation_is_replay_only(self) -> None:
        result = self._evaluation()
        context = self.kernel.context()
        receipt = self.kernel.submit(
            Proposal(
                "legacy-handoff-write",
                context.revision,
                (Operation("record_handoff_evaluation", "handoff-v1", result),),  # type: ignore[arg-type]
            )
        )
        self.assertEqual(receipt.status, "rejected")
        self.assertTrue(any("unsupported action" in reason for reason in receipt.reasons))

    def test_duplicate_test_id_is_rejected_by_application_policy(self) -> None:
        service = HandoffService(self.kernel)
        result = self._evaluation()
        service.record_evaluation("handoff-v1", result)
        with self.assertRaises(RuntimeError):
            service.record_evaluation("handoff-v1", result)


if __name__ == "__main__":
    unittest.main()
