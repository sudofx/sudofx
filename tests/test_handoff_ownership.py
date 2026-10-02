from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "experiments" / "manual_handoff"


class HandoffOwnershipTests(unittest.TestCase):
    """Prevent Handoff domain behavior from drifting back under experiments/."""

    def test_manual_handoff_experiment_is_compatibility_only(self) -> None:
        packet = (LEGACY / "packet.py").read_text(encoding="utf-8")
        scoring = (LEGACY / "scoring.py").read_text(encoding="utf-8")
        readme = (LEGACY / "README.md").read_text(encoding="utf-8")

        self.assertIn("applications.handoff.packet", packet)
        self.assertIn("applications.handoff.scoring", scoring)
        self.assertNotIn("def build_handoff_packet", packet)
        self.assertNotIn("def evaluate_handoff_response", scoring)
        self.assertIn("Deprecated", readme)

    def test_active_kernel_governance_has_no_handoff_domain_action(self) -> None:
        governance = (ROOT / "src" / "sudofx" / "governance.py").read_text(encoding="utf-8")
        self.assertNotIn("record_handoff_evaluation", governance)
        self.assertNotIn("_validate_handoff_evaluation", governance)

    def test_historical_replay_keeps_legacy_action_only_for_compatibility(self) -> None:
        record = (ROOT / "src" / "sudofx" / "record.py").read_text(encoding="utf-8")
        self.assertIn('elif action == "record_handoff_evaluation"', record)


if __name__ == "__main__":
    unittest.main()
