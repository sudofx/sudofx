from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from sudofx import (
    ApplicationAction,
    ApplicationDecision,
    ApplicationDefinition,
    ApplicationHost,
    ApplicationIntent,
    ApplicationRegistry,
    CONTINUITY_MATRIX_V1,
    MatrixAxis,
    MatrixDefinition,
    MatrixValue,
    continuity_matrix,
)
from sudofx.governance import Governance
from sudofx.kernel import Kernel
from sudofx.record import Record


class MatrixExtensionTests(unittest.TestCase):
    """Protect the reusable seven-cubed contract and its application boundary."""

    def test_canonical_continuity_matrix_is_exactly_seven_cubed(self) -> None:
        """The recovered experiment grammar must remain 7 × 7 × 7 = 343."""
        matrix = continuity_matrix()
        self.assertIs(matrix, CONTINUITY_MATRIX_V1)
        self.assertEqual([len(axis.values) for axis in matrix.axes], [7, 7, 7])
        self.assertEqual(matrix.cell_count, 343)

        coordinates = list(matrix.coordinates())
        self.assertEqual(len(coordinates), 343)
        self.assertEqual(len({cell.coordinate_id for cell in coordinates}), 343)
        self.assertEqual([cell.ordinal for cell in coordinates], list(range(1, 344)))

    def test_recovered_v1_axis_keys_are_frozen_in_original_order(self) -> None:
        """Changing v1 labels in place would silently reinterpret durable cell IDs."""
        matrix = continuity_matrix()
        self.assertEqual(
            [value.key for value in matrix.axes[0].values],
            [
                "reconstruction",
                "milestone-dropout",
                "observation-dropout",
                "frontier-only",
                "authority-boundary",
                "provenance",
                "adversarial-integrity",
            ],
        )
        self.assertEqual(
            [value.key for value in matrix.axes[1].values],
            [
                "rich",
                "milestones-only",
                "observation-only",
                "minimal",
                "two-milestones",
                "counts-without-digests",
                "digests-without-counts",
            ],
        )
        self.assertEqual(
            [value.key for value in matrix.axes[2].values],
            [
                "clean",
                "stale-frontier",
                "authority-injection",
                "digest-overclaim",
                "instruction-hijack",
                "provenance-collision",
                "compound-adversarial",
            ],
        )

    def test_coordinate_ids_and_ordinals_are_stable_and_resolvable(self) -> None:
        """Applications need durable cell identity without storing a second matrix copy."""
        matrix = continuity_matrix()

        first = matrix.coordinate("reconstruction", "rich", "clean")
        self.assertEqual(first.ordinal, 1)
        self.assertEqual(
            first.coordinate_id,
            "continuity@1:reconstruction|rich|clean",
        )

        last = matrix.coordinate(
            "adversarial-integrity",
            "digests-without-counts",
            "compound-adversarial",
        )
        self.assertEqual(last.ordinal, 343)
        self.assertEqual(
            last.coordinate_id,
            "continuity@1:adversarial-integrity|digests-without-counts|compound-adversarial",
        )

        generated = list(matrix.coordinates())
        self.assertEqual(generated[first.ordinal - 1], first)
        self.assertEqual(generated[last.ordinal - 1], last)

    def test_application_can_govern_and_reconstruct_matrix_progress_without_core_changes(self) -> None:
        """An opt-in app can persist matrix cells through the ordinary SQLite authority path."""
        matrix = continuity_matrix()

        def record_cell(current, payload):
            state = dict(current) if isinstance(current, dict) else {"completed": []}
            if not isinstance(payload, str):
                return ApplicationDecision(False, reasons=("coordinate ID must be text",))
            try:
                matrix.coordinate_by_id(payload)
            except ValueError as exc:
                return ApplicationDecision(False, reasons=(str(exc),))
            completed = list(state.get("completed", []))
            if payload not in completed:
                completed.append(payload)
            return ApplicationDecision(True, {"completed": completed})

        consumer = ApplicationDefinition(
            "matrix-consumer",
            "1",
            (ApplicationAction("record_cell", record_cell),),
        )
        registry = ApplicationRegistry((consumer,))

        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "record.sqlite"
            kernel = Kernel(Record(path), Governance(application_registry=registry))
            host = ApplicationHost(kernel, registry, "matrix-consumer")
            first = matrix.coordinate("reconstruction", "rich", "clean")

            receipt = host.submit(
                ApplicationIntent("matrix-cell-1", 0, "record_cell", first.coordinate_id)
            )
            self.assertEqual(receipt.status, "accepted")
            self.assertEqual(host.context().state["completed"], [first.coordinate_id])

            # Replace Kernel, Record, and Host. The matrix extension provides
            # semantics; SQLite remains the only durable campaign authority.
            rebuilt = ApplicationHost(
                Kernel(Record(path), Governance(application_registry=registry)),
                registry,
                "matrix-consumer",
            )
            self.assertEqual(rebuilt.context().state["completed"], [first.coordinate_id])

    def test_application_matrix_validation_fails_closed_on_other_versions(self) -> None:
        """A consumer must not silently reinterpret a coordinate from another matrix version."""
        matrix = continuity_matrix()
        first = matrix.coordinate("reconstruction", "rich", "clean")
        self.assertEqual(matrix.coordinate_by_id(first.coordinate_id), first)
        with self.assertRaises(ValueError):
            matrix.coordinate_by_id(first.coordinate_id.replace("continuity@1:", "continuity@2:", 1))

    def test_next_uncovered_accepts_database_derived_completion_ids(self) -> None:
        """Traversal stays pure while an application's SQLite state owns progress."""
        matrix = continuity_matrix()
        first_three = list(matrix.coordinates())[:3]

        next_cell = matrix.next_uncovered(
            cell.coordinate_id for cell in first_three[:2]
        )
        self.assertEqual(next_cell, first_three[2])

        self.assertIsNone(
            matrix.next_uncovered(cell.coordinate_id for cell in matrix.coordinates())
        )

    def test_definition_digest_is_deterministic_and_semantically_sensitive(self) -> None:
        """Apps may anchor which immutable grammar a campaign used without copying it."""
        matrix = continuity_matrix()
        self.assertEqual(matrix.definition_digest, continuity_matrix().definition_digest)
        self.assertEqual(len(matrix.definition_digest), 64)

        altered = MatrixDefinition(
            "continuity-copy",
            "1",
            matrix.axes,
        )
        self.assertNotEqual(matrix.definition_digest, altered.definition_digest)

    def test_invalid_or_ambiguous_definitions_fail_before_application_use(self) -> None:
        """Bad extension configuration must fail before it reaches governed state."""
        with self.assertRaises(ValueError):
            MatrixValue("", "Missing", "invalid key")
        with self.assertRaises(ValueError):
            MatrixValue("bad|key", "Bad", "invalid delimiter")
        with self.assertRaises(ValueError):
            MatrixAxis(
                "duplicate",
                "Duplicate",
                (
                    MatrixValue("same", "Same", "first"),
                    MatrixValue("same", "Same again", "second"),
                ),
            )
        with self.assertRaises(ValueError):
            continuity_matrix().coordinate("missing", "rich", "clean")
        with self.assertRaises(ValueError):
            continuity_matrix().coordinate("reconstruction", "rich")


if __name__ == "__main__":
    unittest.main()
