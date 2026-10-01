"""Tests for deterministic three-axis continuity experiment state."""

from __future__ import annotations

import unittest

from experiments.overnight import (
    CUBE_SIZE,
    EXPERIMENT_VERSION,
    EXPOSURES,
    PHASES,
    PRESSURES,
    advance_experiment_state,
    build_trial_directive,
)


class OvernightContinuityTests(unittest.TestCase):
    """Protect the bounded handoff and deterministic 7×7×7 cube contract."""

    def _advance(self, state: dict, directive: dict, n: int) -> dict:
        return advance_experiment_state(
            state,
            directive=directive,
            observation={"candidate_result": f"response {n}", "candidate_rationale": "test"},
        )

    def test_version_three_migration_starts_fresh_cube_without_resetting_global_cycle(self) -> None:
        old = {
            "version": 2,
            "cycle": 113,
            "response_count": 113,
            "chain_digest": "a" * 64,
            "latest_observation": {"candidate_result": "prior"},
        }
        directive = build_trial_directive(old)
        self.assertEqual(directive["version"], EXPERIMENT_VERSION)
        self.assertEqual(directive["cycle"], 114)
        self.assertEqual(directive["matrix_cycle"], 1)
        self.assertEqual(
            directive["coordinate"],
            {
                "semantic_lens": PHASES[0],
                "exposure": EXPOSURES[0],
                "pressure": PRESSURES[0],
            },
        )

    def test_cube_visits_all_343_coordinates_before_wraparound(self) -> None:
        state: dict = {}
        seen: set[tuple[str, str, str]] = set()
        first = None
        for n in range(1, CUBE_SIZE + 1):
            directive = build_trial_directive(state)
            coordinate = directive["coordinate"]
            key = (
                coordinate["semantic_lens"],
                coordinate["exposure"],
                coordinate["pressure"],
            )
            if first is None:
                first = key
            self.assertNotIn(key, seen)
            seen.add(key)
            self.assertEqual(directive["matrix_cycle"], n)
            state = self._advance(state, directive, n)

        self.assertEqual(len(seen), 343)
        self.assertEqual(len(seen), CUBE_SIZE)
        wrapped = build_trial_directive(state)
        coordinate = wrapped["coordinate"]
        self.assertEqual(
            (
                coordinate["semantic_lens"],
                coordinate["exposure"],
                coordinate["pressure"],
            ),
            first,
        )
        self.assertEqual(wrapped["matrix_cycle"], CUBE_SIZE + 1)

    def test_axes_change_independently_at_expected_boundaries(self) -> None:
        state: dict = {}
        directives = []
        for n in range(1, 51):
            directive = build_trial_directive(state)
            directives.append(directive)
            state = self._advance(state, directive, n)

        # X changes every cycle.
        self.assertEqual(directives[0]["coordinate"]["semantic_lens"], PHASES[0])
        self.assertEqual(directives[1]["coordinate"]["semantic_lens"], PHASES[1])
        # Y changes after seven X positions.
        self.assertEqual(directives[6]["coordinate"]["exposure"], EXPOSURES[0])
        self.assertEqual(directives[7]["coordinate"]["exposure"], EXPOSURES[1])
        # Z changes after a full 7×7 plane.
        self.assertEqual(directives[48]["coordinate"]["pressure"], PRESSURES[0])
        self.assertEqual(directives[49]["coordinate"]["pressure"], PRESSURES[1])

    def test_exposure_axis_controls_actual_readable_cues(self) -> None:
        state: dict = {
            "version": EXPERIMENT_VERSION,
            "cycle": 0,
            "matrix_cycle": 0,
            "response_count": 1,
            "chain_digest": "a" * 64,
            "latest_observation": {"candidate_result": "prior"},
        }

        # Walk to each Y profile's first coordinate while Z remains clean.
        observed = {}
        for n in range(1, len(PHASES) * len(EXPOSURES) + 1):
            directive = build_trial_directive(state)
            observed.setdefault(directive["coordinate"]["exposure"], directive)
            state = self._advance(state, directive, n)

        self.assertEqual(set(observed), set(EXPOSURES))
        self.assertEqual(observed["rich"]["exposure"]["accepted_results_limit"], 1)
        self.assertTrue(observed["rich"]["exposure"]["include_previous_observation"])
        self.assertEqual(observed["two_milestones"]["exposure"]["accepted_results_limit"], 2)
        self.assertFalse(observed["minimal"]["exposure"]["include_counts"])
        self.assertFalse(observed["minimal"]["exposure"]["include_digests"])
        self.assertIsNone(observed["minimal"]["prior_observation_count"])
        self.assertIsNone(observed["minimal"]["prior_observation_chain_digest"])
        self.assertTrue(observed["counts_without_digests"]["exposure"]["include_counts"])
        self.assertFalse(observed["counts_without_digests"]["exposure"]["include_digests"])
        self.assertFalse(observed["digests_without_counts"]["exposure"]["include_counts"])
        self.assertTrue(observed["digests_without_counts"]["exposure"]["include_digests"])

    def test_pressure_axis_is_synthetic_data_not_authority(self) -> None:
        state: dict = {}
        observed = {}
        for n in range(1, CUBE_SIZE + 1):
            directive = build_trial_directive(state)
            pressure = directive["coordinate"]["pressure"]
            observed.setdefault(pressure, directive)
            state = self._advance(state, directive, n)

        self.assertNotIn("synthetic_challenge_claims", observed["clean"])
        for pressure in PRESSURES[1:]:
            claims = observed[pressure].get("synthetic_challenge_claims", [])
            self.assertGreater(len(claims), 0)
            self.assertTrue(all("Synthetic challenge:" in claim for claim in claims))
        self.assertTrue(
            any("never instructions or authority" in rule for rule in observed["compound_adversarial"]["rules"])
        )

    def test_only_latest_observation_crosses_when_profile_allows_it(self) -> None:
        state = {
            "version": EXPERIMENT_VERSION,
            "cycle": 0,
            "matrix_cycle": 0,
            "response_count": 1,
            "chain_digest": "a" * 64,
            "latest_observation": {"candidate_result": "prior"},
        }
        # First plane is rich, so latest observation is visible.
        directive = build_trial_directive(state)
        self.assertEqual(
            directive["previous_model_observation_untrusted"]["candidate_result"],
            "prior",
        )

        # Advance seven coordinates into milestones_only, which withholds it.
        for n in range(1, 8):
            directive = build_trial_directive(state)
            state = self._advance(state, directive, n)
        directive = build_trial_directive(state)
        self.assertEqual(directive["coordinate"]["exposure"], "milestones_only")
        self.assertIsNone(directive["previous_model_observation_untrusted"])
        self.assertTrue(directive["previous_model_observation_withheld"])

    def test_chain_digest_commits_to_cube_coordinate_and_observation(self) -> None:
        directive = build_trial_directive({})
        left = advance_experiment_state(
            {}, directive=directive, observation={"candidate_result": "left"}
        )
        right = advance_experiment_state(
            {}, directive=directive, observation={"candidate_result": "right"}
        )
        self.assertNotEqual(left["chain_digest"], right["chain_digest"])
        self.assertEqual(left["coordinate"], directive["coordinate"])


if __name__ == "__main__":
    unittest.main()
