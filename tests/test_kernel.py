from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from sudofx import (
    CommandIntelligence,
    FakeIntelligence,
    FakeWorkIntelligence,
    Kernel,
    Operation,
    Proposal,
    ProviderError,
)
from sudofx.record import IntegrityError, Record
from sudofx.continuity import run_continuity_proof, run_model_continuity_probe, run_work_continuity_probe
from sudofx.report import render
from scripts.github_sudofx import main as github_main

# These tests protect durable guarantees rather than implementation shape.
# Temporary SQLite records prove replay across reopened processes without
# depending on a developer's local state or the production state branch.


class ContractOnlyStore:
    """
    Expose only the backend-neutral record contract around a real SQLite Record.

    This adapter intentionally has no connect(), path, SQL surface, commit,
    rollback, or SQLite-specific helper. Kernel regressions that reach through
    the contract therefore fail even though the underlying implementation still
    uses SQLite.
    """

    def __init__(self, record: Record) -> None:
        self._record = record

    def read_transaction(self):
        return self._record.read_transaction()

    def write_transaction(self):
        return self._record.write_transaction()

    def history(self):
        return self._record.history()


class KernelTests(unittest.TestCase):
    """Exercise continuity, governance, integrity, bounded context, and projection."""
    def setUp(self) -> None:
        # Every test owns a fresh record so event identity and revision assertions
        # remain independent and reproducible in any execution order.
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "record.sqlite"
        self.kernel = Kernel(Record(self.path))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_deterministic_continuity_proof_crosses_fresh_process_boundary(self) -> None:
        """
        The publishable proof must survive kernel/provider replacement and replay.

        This is the executable v0.1 infrastructure claim. It intentionally does
        not claim that a real model understands human context well.
        """
        proof = run_continuity_proof()
        self.assertTrue(proof["passed"])
        self.assertEqual(proof["receipt"]["status"], "accepted")
        self.assertTrue(proof["checks"]["provider_is_fresh_external_process"])
        self.assertTrue(proof["checks"]["unrelated_state_remained_outside_provider_context"])
        self.assertTrue(proof["checks"]["accepted_result_survived_replay"])
        self.assertFalse(proof["checks"]["production_state_mutated"])

    def test_phone_prove_work_trims_accidental_input_whitespace(self) -> None:
        """
        GitHub Mobile may preserve leading/trailing spaces in text inputs.

        The phone-only probe boundary normalizes only the work selector; general
        state keys retain their exact operator-supplied semantics.
        """
        import scripts.github_sudofx as adapter

        seen: list[str] = []
        original = adapter.run_work_continuity_probe
        try:
            adapter.run_work_continuity_probe = lambda path, work_id: (
                seen.append(work_id)
                or {
                    "passed": True,
                    "kind": "test",
                    "proves": "test",
                    "does_not_prove": "test",
                    "checks": {},
                }
            )
            original_restore = adapter.restore
            original_export = adapter.export_site
            adapter.restore = lambda: False
            adapter.export_site = lambda *args, **kwargs: Path(self.tempdir.name) / "index.html"
            original_argv = sys.argv
            try:
                sys.argv = ["github_sudofx.py", "--prove-work", "   first-workflow   "]
                self.assertEqual(github_main(), 0)
            finally:
                sys.argv = original_argv
                adapter.restore = original_restore
                adapter.export_site = original_export
        finally:
            adapter.run_work_continuity_probe = original
        self.assertEqual(seen, ["first-workflow"])

    def test_real_work_continuity_probe_uses_snapshot_without_mutating_source(self) -> None:
        """
        A real-record probe must exercise bounded continuation without changing source authority.
        """
        self.kernel.submit(
            Proposal(
                "probe-real-create",
                0,
                (
                    Operation(
                        "create_work",
                        "real",
                        {
                            "objective": "Continue real durable work",
                            "constraints": ["Do not mutate source during probe"],
                        },
                    ),
                ),
            )
        )
        self.kernel.submit(
            Proposal(
                "probe-real-advance",
                1,
                (
                    Operation(
                        "advance_work",
                        "real",
                        {"result": "Existing progress", "open_obligations": ["Next real step"]},
                    ),
                ),
            )
        )
        before = self.kernel.record.history()
        proof = run_work_continuity_probe(self.path, "real")
        after = Kernel(Record(self.path)).record.history()
        self.assertTrue(proof["passed"])
        self.assertTrue(proof["checks"]["production_record_head_unchanged"])
        self.assertFalse(proof["checks"]["production_state_mutated"])
        self.assertEqual(before, after)
        source_work = Kernel(Record(self.path)).context(work_id="real").state["work:real"]
        self.assertEqual(source_work["accepted_results"], ["Existing progress"])
        self.assertEqual(source_work["open_obligations"], ["Next real step"])

    def test_real_model_probe_uses_same_bounded_process_contract_without_source_mutation(self) -> None:
        """
        A model probe may vary semantics but must preserve the authority boundary.

        The helper process stands in for a network model adapter here so unit
        tests remain deterministic and credential-free.
        """
        self.kernel.submit(
            Proposal(
                "model-create",
                0,
                (
                    Operation(
                        "create_work",
                        "model",
                        {
                            "objective": "Recover meaning after provider replacement",
                            "constraints": ["Use durable context only"],
                        },
                    ),
                ),
            )
        )
        helper = """
import json, sys
context = json.load(sys.stdin)
assert set(context["state"]) == {"work:model"}
work = context["state"]["work:model"]
json.dump({
    "proposal_id": f"model-test-{context['revision']}",
    "based_on_revision": context["revision"],
    "operations": [{
        "action": "advance_work",
        "key": work["id"],
        "value": {
            "result": "Reconstruction: durable context defines the work. Proposed next step: evaluate semantic fidelity.",
            "open_obligations": ["evaluate semantic fidelity"]
        }
    }],
    "rationale": "derived only from bounded context"
}, sys.stdout)
"""
        before = self.kernel.record.history()
        proof = run_model_continuity_probe(
            self.path,
            "model",
            (sys.executable, "-c", helper),
            provider="test-provider",
            model="test-model",
        )
        after = Kernel(Record(self.path)).record.history()
        self.assertTrue(proof["passed"])
        self.assertEqual(proof["assessment_status"], "semantic_review_pending")
        self.assertEqual(proof["semantic_review"]["version"], 1)
        self.assertEqual(proof["semantic_review"]["status"], "pending")
        self.assertEqual(len(proof["semantic_review"]["criteria"]), 6)
        self.assertEqual(
            {item["id"] for item in proof["semantic_review"]["criteria"]},
            {
                "objective_fidelity",
                "history_fidelity",
                "frontier_fidelity",
                "constraint_fidelity",
                "unsupported_claims",
                "actionability",
            },
        )
        self.assertEqual(
            proof["semantic_review"]["evidence"]["objective"],
            "Recover meaning after provider replacement",
        )
        self.assertIn("evaluate semantic fidelity", proof["candidate_result"])
        self.assertEqual(before, after)
        self.assertFalse(proof["checks"]["production_state_mutated"])

    def test_kernel_depends_on_storage_contract_not_sqlite_connection(self) -> None:
        """
        Kernel must operate when every SQLite-specific surface is hidden.

        This protects backend replacement as a durable architectural guarantee,
        not merely as a type annotation or documentation claim.
        """
        path = Path(self.tempdir.name) / "contract-only.sqlite"
        kernel = Kernel(ContractOnlyStore(Record(path)))
        receipt = kernel.submit(Proposal("portable", 0, (Operation("set", "x", 1),)))
        self.assertEqual(receipt.status, "accepted")
        self.assertEqual(kernel.context().state, {"x": 1})

    def test_fresh_intelligences_continue_from_durable_context(self) -> None:
        """A second provider instance must derive progress only from durable context."""
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

    def test_external_process_advances_work_from_bounded_json_context(self) -> None:
        """A disposable process must continue work without record or kernel access."""
        self.kernel.submit(
            Proposal(
                "create-external",
                0,
                (Operation("create_work", "external", {"objective": "Cross process", "constraints": []}),),
            )
        )
        self.kernel.submit(Proposal("unrelated", 1, (Operation("set", "private", "not shared"),)))
        # The helper is intentionally stateless: it derives every proposal field
        # from the JSON document delivered to this one process invocation. Its
        # assertion proves unrelated durable state did not cross the boundary.
        helper = """
import json, sys
context = json.load(sys.stdin)
assert set(context['state']) == {'work:external'}
work = context['state']['work:external']
json.dump({
    'proposal_id': f\"external-{context['revision']}\",
    'based_on_revision': context['revision'],
    'operations': [{'action': 'advance_work', 'key': work['id'], 'value': {
        'result': 'External process continued the work', 'open_obligations': []}}],
    'rationale': 'Derived only from bounded durable context'
}, sys.stdout)
"""
        # Reopen both the record and kernel before invoking the external process.
        # Continuity must come from durable replay, not from surviving Python
        # objects or provider-local memory from the setup phase above.
        replacement = Kernel(Record(self.path))
        result = replacement.run(
            CommandIntelligence((sys.executable, "-c", helper)),
            work_id="external",
        )
        self.assertEqual(result.receipt.status, "accepted")
        self.assertEqual(
            replacement.context().state["work:external"]["accepted_results"],
            ["External process continued the work"],
        )

    def test_invalid_external_output_never_creates_a_receipt(self) -> None:
        """Provider transport failure must not fabricate durable proposal history."""
        provider = CommandIntelligence((sys.executable, "-c", "print('not json')"))
        with self.assertRaises(ProviderError):
            self.kernel.run(provider)
        self.assertEqual(self.kernel.record.history(), ())

    def test_replay_survives_kernel_and_provider_replacement(self) -> None:
        """Replacing both active objects must preserve authoritative state."""
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
        """Optimistic concurrency must preserve newer accepted work and record refusal."""
        self.kernel.submit(Proposal("p1", 0, (Operation("set", "safe", True),)))
        receipt = self.kernel.submit(Proposal("stale", 0, (Operation("set", "safe", False),)))
        self.assertEqual(receipt.status, "rejected")
        self.assertEqual(receipt.revision_before, receipt.revision_after)
        self.assertEqual(self.kernel.context().state, {"safe": True})
        self.assertEqual(len(self.kernel.context().recent_receipts), 2)

    def test_invalid_proposal_is_recorded_as_rejected(self) -> None:
        """Malformed intent should become evidence without becoming state."""
        receipt = self.kernel.submit(Proposal("empty", 0, ()))
        self.assertEqual(receipt.status, "rejected")
        self.assertIn("at least one operation", receipt.reasons[0])
        self.assertEqual(self.kernel.context().revision, 0)

    def test_duplicate_proposal_id_cannot_be_replayed(self) -> None:
        """Proposal identity reuse must fail rather than append ambiguous history."""
        proposal = Proposal("same", 0, (Operation("set", "x", 1),))
        self.kernel.submit(proposal)
        with self.assertRaises(ValueError):
            self.kernel.submit(proposal)

    def test_hash_chain_detects_tampering(self) -> None:
        """Changing stored payload bytes must make complete replay unavailable."""
        self.kernel.submit(Proposal("p1", 0, (Operation("set", "x", 1),)))
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE events SET payload = ? WHERE sequence = 1", ('{}',))
            connection.commit()
        with self.assertRaises(IntegrityError):
            self.kernel.context()

    def test_static_report_exposes_state_and_receipt_provenance(self) -> None:
        """The public projection must preserve navigation, theme, and traceability."""
        self.kernel.submit(Proposal("p1", 0, (Operation("set", "objective", "continue"),)))
        page = render(
            self.kernel,
            verification={
                "commit": "0123456789abcdef",
                "run_url": "https://github.com/sudofx/sudofx/actions/runs/123",
            },
            continuity_proof={
                "passed": True,
                "artifact_run_id": "123",
                "artifact_commit": "0123456789abcdef",
                "proves": "Fresh process continued bounded work.",
                "does_not_prove": "Real model semantic reconstruction.",
                "checks": {
                    "provider_is_fresh_external_process": True,
                    "production_state_mutated": False,
                },
                "semantic_review": {
                    "version": 1,
                    "status": "pending",
                    "rule": "Human review only.",
                    "criteria": [
                        {
                            "id": "objective_fidelity",
                            "question": "Does it preserve the objective?",
                            "status": "pending",
                        }
                    ],
                },
            },
        )
        self.assertIn("Tests passed before this page was published.", page)
        self.assertIn("Disposable continuity proof", page)
        self.assertIn("Fresh process continued bounded work.", page)
        self.assertIn("continuity-proof.json", page)
        self.assertIn("Human semantic review", page)
        self.assertIn("Get latest result", page)
        self.assertIn("data-artifact-run-id=\"123\"", page)
        self.assertIn("data-artifact-commit=\"0123456789abcdef\"", page)
        self.assertIn("artifact_run_id=", page)
        self.assertIn("artifact_commit=", page)
        self.assertIn("continuity-proof.json?ts=", page)
        self.assertIn("No newer result yet", page)
        self.assertIn("initializeReviewControls", page)
        self.assertIn("Does it preserve the objective?", page)
        self.assertIn("Pass", page)
        self.assertIn("Fail", page)
        self.assertIn("Uncertain", page)
        self.assertIn("Copy review", page)
        self.assertIn("choices[item.dataset.reviewId]='pass'", page)
        self.assertIn("choices.__overall='pass'", page)
        self.assertIn("SUDOFX_SEMANTIC_REVIEW", page)
        self.assertIn("navigator.clipboard.writeText", page)
        self.assertIn("Refreshing this page in", page)
        self.assertIn("Refresh now", page)
        self.assertIn("Cancel", page)
        self.assertIn("remaining=5", page)
        self.assertIn("window.location.replace", page)
        self.assertIn("searchParams.set('refresh'", page)
        self.assertIn("refresh-backdrop", page)
        self.assertIn("top:50%; transform:translate(-50%,-50%)", page)
        self.assertIn("Automatic refresh cancelled.", page)
        self.assertIn("No authoritative state was changed.", page)
        self.assertIn("const payload=lines.join(", page)
        self.assertNotIn("lines.join('\n')", page)
        self.assertIn("0123456789ab", page)
        self.assertIn("actions/runs/123", page)
        self.assertIn("objective", page)
        self.assertIn("continue", page)
        self.assertIn("proposal p1", page)
        self.assertIn("Run operation", page)
        self.assertIn("wake-theme", page)
        self.assertIn("data-theme=dark", page)
        # Green is the accepted toggle highlight. The switch remains the only
        # visual indicator so no redundant glyph can drift out of alignment.
        self.assertIn("background:var(--green)", page)
        self.assertNotIn("theme-icon", page)
        self.assertIn("width:1px; height:1px", page)
        # The theme control owns the header's upper-right grid area. This guards
        # against regrouping it with the tagline, which made it drop on phones.
        self.assertIn('grid-template-areas:"brand theme" "tagline tagline"', page)
        self.assertIn("grid-area:theme; justify-self:end", page)
        self.assertIn('class="brand" href="./"', page)
        self.assertIn('href="https://sudofx.github.io/wake/">Inspired by WAKE', page)
        self.assertIn("Continuity Challenge", page)
        self.assertIn("Public question. Shared-history answer.", page)
        self.assertIn("Copy challenge", page)
        self.assertIn("Next question", page)
        self.assertNotIn("Reveal answer check", page)
        self.assertIn("SUDOFX_CONTINUITY_CHALLENGE v1", page)
        self.assertNotIn("challenge-anchors", page)
        self.assertIn("record_revision=", page)
        self.assertIn("Do not treat this as authentication.", page)
        self.assertIn("answer is intentionally not stored on this page", page)
        self.assertIn("When I say “BANG‼️”", page)
        self.assertIn("When I tell you “you get me,”", page)

    def test_record_initializes_inside_an_existing_empty_directory(self) -> None:
        """A first cloud run may create a record once its explicit parent exists."""
        nested = Path(self.tempdir.name) / "cloud-data" / "record.sqlite"
        nested.parent.mkdir(parents=True)
        kernel = Kernel(Record(nested))
        self.assertEqual(kernel.context().revision, 0)

    def test_disposable_intelligences_advance_one_durable_work_item(self) -> None:
        """Independent invocations must append results to the same governed objective."""
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
        """Completion is terminal and cannot be silently reopened by later progress."""
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
        """Scoped context must not leak another work item's state or receipts."""
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
        """Users must be able to inspect durable work rather than only raw JSON."""
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
