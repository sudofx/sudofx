from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from applications.conversation import (
    CONVERSATION_APPLICATION,
    matrix_campaign_projection,
    private_bounded_context,
)
from applications.conversation.runtime import (
    record_matrix_result,
    run_private_turn,
    start_matrix_campaign,
    stop_matrix_campaign,
)
from applications.conversation.server import ConversationService
from sudofx import ApplicationHost, ApplicationRegistry, Kernel
from sudofx.governance import Governance
from sudofx.record import Record


class ConversationMatrixTests(unittest.TestCase):
    """Prove Conversation opts into the shared matrix without changing normal chat."""

    def _state(self, path: Path):
        registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
        kernel = Kernel(Record(path), Governance(application_registry=registry))
        return ApplicationHost(kernel, registry, "conversation").context().state

    def test_normal_conversation_has_no_matrix_provider_context(self) -> None:
        """Ordinary Conversation remains byte-for-byte free of matrix context until enabled."""
        projection = private_bounded_context(None)
        self.assertNotIn("matrix_campaign", projection)
        self.assertEqual(matrix_campaign_projection(None), {"enabled": False})

    def test_starting_campaign_exposes_first_shared_coordinate_to_fresh_provider(self) -> None:
        """Opt-in campaign state should drive the provider from the shared continuity@1 grammar."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "conversation.sqlite"
            campaign = start_matrix_campaign(data_path=path)
            self.assertTrue(campaign["enabled"])
            self.assertEqual(campaign["completed_count"], 0)
            self.assertEqual(campaign["total_cells"], 343)
            first = campaign["next_coordinate"]
            self.assertEqual(first["ordinal"], 1)
            self.assertEqual(
                first["coordinate_id"],
                "continuity@1:reconstruction|rich|clean",
            )

            provider = (
                sys.executable,
                "-c",
                "import json,sys; data=json.load(sys.stdin); "
                "m=data['state']['app:conversation']['matrix_campaign']; "
                "assert m['enabled'] is True; "
                "assert m['next_coordinate']['coordinate_id']=='continuity@1:reconstruction|rich|clean'; "
                "json.dump({'content':'matrix cell received','observations':[],'commitment_updates':[]},sys.stdout)",
            )
            reply = run_private_turn(
                "Test this governed continuity cell.",
                data_path=path,
                provider_command=provider,
            )
            self.assertEqual(reply, "matrix cell received")

    def test_results_advance_deterministically_and_survive_fresh_process_reconstruction(self) -> None:
        """Conversation stores only governed progress while matrix semantics remain reusable source."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "conversation.sqlite"
            first = start_matrix_campaign(data_path=path)["next_coordinate"]
            evidence = "a" * 64
            after = record_matrix_result(
                first["coordinate_id"],
                "pass",
                data_path=path,
                evidence_digest=evidence,
            )
            self.assertEqual(after["completed_count"], 1)
            self.assertEqual(after["next_coordinate"]["ordinal"], 2)

            # Rebuild every runtime object from SQLite. No process-local matrix
            # progress is required for the application to resume at cell 2.
            service = ConversationService(path, provider_command=(sys.executable, "-c", ""))
            status = service.status()
            self.assertTrue(status["matrix_enabled"])
            self.assertEqual(status["matrix_completed_count"], 1)
            self.assertEqual(status["matrix_total_cells"], 343)
            self.assertEqual(
                status["matrix_next_coordinate_id"],
                after["next_coordinate"]["coordinate_id"],
            )

            state = self._state(path)
            serialized = json.dumps(state, sort_keys=True)
            self.assertIn(first["coordinate_id"], serialized)
            self.assertIn(evidence, serialized)
            self.assertNotIn("matrix cell received", serialized)

    def test_duplicate_or_foreign_results_fail_closed(self) -> None:
        """Campaign history must not silently reinterpret or overwrite matrix coordinates."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "conversation.sqlite"
            first = start_matrix_campaign(data_path=path)["next_coordinate"]
            record_matrix_result(first["coordinate_id"], "pass", data_path=path)

            with self.assertRaises(RuntimeError):
                record_matrix_result(first["coordinate_id"], "fail", data_path=path)
            with self.assertRaises(RuntimeError):
                record_matrix_result(
                    first["coordinate_id"].replace("continuity@1:", "continuity@2:", 1),
                    "pass",
                    data_path=path,
                )

    def test_stop_preserves_results_but_removes_matrix_from_provider_context(self) -> None:
        """Stopping a campaign is durable control, not deletion of prior evidence."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "conversation.sqlite"
            first = start_matrix_campaign(data_path=path)["next_coordinate"]
            record_matrix_result(first["coordinate_id"], "uncertain", data_path=path)
            stopped = stop_matrix_campaign(data_path=path)
            self.assertFalse(stopped["enabled"])
            self.assertEqual(stopped["completed_count"], 1)

            state = self._state(path)
            self.assertNotIn("matrix_campaign", private_bounded_context(state))
            durable = matrix_campaign_projection(state)
            self.assertFalse(durable["enabled"])
            self.assertEqual(durable["completed_count"], 1)
            self.assertNotIn("next_coordinate", durable)

    def test_service_controls_use_governed_application_state(self) -> None:
        """The actual Conversation service exposes opt-in controls without a side store."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "conversation.sqlite"
            service = ConversationService(path, provider_command=(sys.executable, "-c", ""))
            started = service.start_matrix_campaign()
            first = started["next_coordinate"]
            result = service.record_matrix_result(first["coordinate_id"], "pass")
            self.assertEqual(result["completed_count"], 1)
            service.stop_matrix_campaign()

            fresh = ConversationService(path, provider_command=(sys.executable, "-c", ""))
            status = fresh.status()
            self.assertFalse(status["matrix_enabled"])
            self.assertEqual(status["matrix_completed_count"], 1)


if __name__ == "__main__":
    unittest.main()
