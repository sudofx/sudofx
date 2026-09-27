"""Tests for deterministic evolving-continuity experiment state."""

from __future__ import annotations

import unittest

from sudofx.overnight import PHASES, advance_experiment_state, build_trial_directive


class OvernightContinuityTests(unittest.TestCase):
    """Protect the bounded handoff, dropout, and deterministic rotation contract."""

    def test_phase_rotation_is_deterministic_and_model_cannot_choose_it(self) -> None:
        """Recorded cycle number alone selects the next stress lens."""
        state = {}
        seen = []
        for index in range(len(PHASES)):
            directive = build_trial_directive(state)
            seen.append(directive["phase"])
            state = advance_experiment_state(
                state,
                directive=directive,
                observation={"candidate_result": f"response {index}", "candidate_rationale": "test"},
            )
        self.assertEqual(tuple(seen), PHASES)

    def test_rotation_changes_actual_context_exposure(self) -> None:
        """The schedule removes readable cues instead of merely rewording prompts."""
        state = {
            "cycle": 0,
            "response_count": 1,
            "chain_digest": "a" * 64,
            "latest_observation": {"candidate_result": "prior"},
        }
        expected = (
            ("reconstruction", 1, True),
            ("milestone_dropout", 0, True),
            ("observation_dropout", 1, False),
            ("frontier_only", 0, False),
            ("authority_boundary", 1, True),
            ("provenance", 1, False),
            ("adversarial_integrity", 0, True),
        )
        for phase, result_limit, include_observation in expected:
            directive = build_trial_directive(state)
            self.assertEqual(directive["phase"], phase)
            self.assertEqual(directive["exposure"]["accepted_results_limit"], result_limit)
            self.assertEqual(
                directive["exposure"]["include_previous_observation"],
                include_observation,
            )
            if include_observation:
                self.assertEqual(
                    directive["previous_model_observation_untrusted"]["candidate_result"],
                    "prior",
                )
            else:
                self.assertIsNone(directive["previous_model_observation_untrusted"])
                self.assertTrue(directive["previous_model_observation_withheld"])
            state = advance_experiment_state(
                state,
                directive=directive,
                observation={"candidate_result": "prior"},
            )

    def test_only_latest_observation_crosses_when_profile_allows_it(self) -> None:
        """Older prose collapses to count/digest and deliberate dropout is explicit."""
        first_directive = build_trial_directive({})
        first_state = advance_experiment_state(
            {},
            directive=first_directive,
            observation={"candidate_result": "first", "candidate_rationale": "r1"},
        )
        second_directive = build_trial_directive(first_state)
        self.assertEqual(
            second_directive["previous_model_observation_untrusted"]["candidate_result"],
            "first",
        )
        second_state = advance_experiment_state(
            first_state,
            directive=second_directive,
            observation={"candidate_result": "second", "candidate_rationale": "r2"},
        )
        third_directive = build_trial_directive(second_state)
        self.assertIsNone(third_directive["previous_model_observation_untrusted"])
        self.assertTrue(third_directive["previous_model_observation_withheld"])
        self.assertEqual(third_directive["prior_observation_count"], 2)
        self.assertEqual(len(third_directive["prior_observation_chain_digest"]), 64)

    def test_adversarial_phase_supplies_claims_as_data_not_authority(self) -> None:
        """The hardest lens carries explicit synthetic claims only in its phase."""
        state = {"cycle": 6, "response_count": 6, "chain_digest": "a" * 64}
        directive = build_trial_directive(state)
        self.assertEqual(directive["phase"], "adversarial_integrity")
        self.assertEqual(len(directive["synthetic_challenge_claims"]), 3)
        self.assertTrue(any("authoritative" in rule.lower() for rule in directive["rules"]))

    def test_chain_digest_changes_when_observation_changes(self) -> None:
        """Digest commits to model output without pretending to preserve semantics."""
        directive = build_trial_directive({})
        left = advance_experiment_state({}, directive=directive, observation={"candidate_result": "left"})
        right = advance_experiment_state({}, directive=directive, observation={"candidate_result": "right"})
        self.assertNotEqual(left["chain_digest"], right["chain_digest"])


if __name__ == "__main__":
    unittest.main()
