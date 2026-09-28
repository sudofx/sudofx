from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from sudofx import (
    CommandIntelligence,
    FakeIntelligence,
    FakeWorkIntelligence,
    Kernel,
    Operation,
    Proposal,
    ProviderError,
    ProviderQuotaError,
    ProviderTemporaryError,
)
from sudofx.record import APPLICATION_ID, SCHEMA_VERSION, IntegrityError, Record, StorageVersionError
from sudofx.continuity import (
    run_compressed_model_continuity_probe,
    run_continuity_proof,
    run_default_model_continuity_probe,
    run_model_continuity_probe,
    run_work_continuity_probe,
)
from sudofx.report import _format_bytes, export_site, render
from sudofx.handoff import build_handoff_packet, export_handoff_packet
from plugins.manual_handoff.scoring import (
    DIMENSIONS,
    evaluate_handoff_response,
    handoff_packet_digest,
    handoff_work_id,
)
from scripts.github_sudofx import (
    build_manual_evaluation_projection,
    latest_overnight_proof,
    main as github_main,
)

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

    def projection_snapshot(self, history_limit=50):
        return self._record.projection_snapshot(history_limit)


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

    def test_database_size_uses_compact_units_at_binary_thresholds(self) -> None:
        """The phone readout should scale without changing the authoritative byte count."""
        self.assertEqual(_format_bytes(1023), "1023 B")
        self.assertEqual(_format_bytes(1024), "1 KB")
        self.assertEqual(_format_bytes(147456), "144 KB")
        self.assertEqual(_format_bytes(1572864), "1.5 MB")
        self.assertEqual(_format_bytes(1073741824), "1 GB")

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
            adapter.restore = lambda: (False, False)
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

    def test_restore_provider_failure_cannot_initialize_empty_authority(self) -> None:
        """A network or permission failure is not evidence that state is absent."""
        import scripts.github_sudofx as adapter

        original_git = adapter.git
        try:
            adapter.git = lambda *args, **kwargs: subprocess.CompletedProcess(
                args, 1, stdout="", stderr="provider unavailable"
            )
            with self.assertRaisesRegex(RuntimeError, "could not inspect durable state"):
                adapter.restore()
        finally:
            adapter.git = original_git

    def test_corrupt_restore_candidate_preserves_last_known_good_database(self) -> None:
        """Failed verification must leave the installed database bytes untouched."""
        import scripts.github_sudofx as adapter

        existing = Path(self.tempdir.name) / "installed.sqlite"
        source = Record(existing)
        Kernel(source).submit(Proposal("existing", 0, (Operation("set", "safe", True),)))
        before = existing.read_bytes()
        original_data = adapter.DATA
        original_git = adapter.git
        original_run = adapter.subprocess.run
        try:
            adapter.DATA = existing

            def fake_git(*args, **kwargs):
                return subprocess.CompletedProcess(args, 0, stdout="state-head\n", stderr="")

            def fake_run(args, **kwargs):
                # Only the git-show extraction crosses this seam. Supplying an
                # invalid SQLite body exercises verification before replacement.
                kwargs["stdout"].write(b"not a sqlite database")
                return subprocess.CompletedProcess(args, 0)

            adapter.git = fake_git
            adapter.subprocess.run = fake_run
            with self.assertRaises(sqlite3.DatabaseError):
                adapter.restore()
        finally:
            adapter.DATA = original_data
            adapter.git = original_git
            adapter.subprocess.run = original_run
        self.assertEqual(existing.read_bytes(), before)
        self.assertEqual(Kernel(Record(existing)).context().state, {"safe": True})

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
        self.assertEqual(proof["candidate_rationale"], "derived only from bounded context")
        self.assertEqual(before, after)
        self.assertFalse(proof["checks"]["production_state_mutated"])

    def test_compressed_model_probe_bounds_history_without_mutating_source(self) -> None:
        """Compressed provider context keeps recent meaning while full SQLite history stays authoritative."""
        self.kernel.submit(
            Proposal(
                "compressed-create",
                0,
                (
                    Operation(
                        "create_work",
                        "compressed",
                        {
                            "objective": "Prove semantic continuity under bounded context",
                            "constraints": ["Keep full history authoritative"],
                        },
                    ),
                ),
            )
        )
        for index in range(12):
            self.kernel.submit(
                Proposal(
                    f"compressed-{index}",
                    index + 1,
                    (
                        Operation(
                            "advance_work",
                            "compressed",
                            {
                                "result": f"Accepted milestone {index}: durable progress remains replayable.",
                                "open_obligations": ["Run the compressed continuity probe"],
                            },
                        ),
                    ),
                )
            )

        assessment = {
            "verdict": "pass",
            "criteria": {
                "objective_fidelity": "pass",
                "frontier_fidelity": "pass",
                "unsupported_claims": "pass",
                "actionability": "pass",
            },
            "metrics": {
                "context_bytes": 1200,
                "full_context_bytes": 10000,
                "compression_ratio": 0.88,
                "accepted_results_exposed": 1,
                "receipt_count_exposed": 0,
            },
            "provenance": {
                "artifact_run_id": "123",
                "artifact_commit": "abc123",
                "context_digest": "d" * 64,
                "provider": "test-provider",
                "model": "test-model",
            },
            "note": "structured semantic evidence",
        }
        assessment_receipt = self.kernel.submit(
            Proposal(
                "compressed-assessment",
                13,
                (Operation("record_assessment", "compressed", assessment),),
            )
        )
        self.assertEqual(assessment_receipt.status, "accepted")
        stored_work = self.kernel.context(work_id="compressed").state["work:compressed"]
        self.assertEqual(stored_work["semantic_assessments"], [assessment])
        self.assertEqual(stored_work["open_obligations"], ["Run the compressed continuity probe"])
        page = render(self.kernel)
        self.assertIn("Continuity quality", page)
        self.assertIn("88.0%", page)
        self.assertIn("test-provider", page)
        self.assertIn("run 123", page)
        self.assertIn("data-semantic-review-submit", page)
        self.assertIn('data-review-criterion="objective_fidelity"', page)

        helper = """
import json, sys
context = json.load(sys.stdin)
work = context["state"]["work:compressed"]
assert "accepted_results" not in work
assert work["accepted_result_count"] == 12
assert work["omitted_accepted_results_count"] == 8
assert len(work["accepted_results_recent"]) == 4
assert work["accepted_results_recent"][-1].startswith("Accepted milestone 11")
assert len(work["omitted_accepted_results_digest"]) == 64
assert "semantic_assessments" not in work
assert work["semantic_assessment_count"] == 1
assert len(work["semantic_assessments_digest"]) == 64
assert len(context["recent_receipts"]) <= 8
json.dump({
    "proposal_id": f"compressed-test-{context['revision']}",
    "based_on_revision": context["revision"],
    "operations": [{
        "action": "advance_work",
        "key": work["id"],
        "value": {
            "result": "Compressed context preserves the current objective and frontier.",
            "open_obligations": ["Judge compressed semantic fidelity"]
        }
    }],
    "rationale": "used only the compressed provider context"
}, sys.stdout)
"""
        before = self.kernel.record.history()
        proof = run_compressed_model_continuity_probe(
            self.path,
            "compressed",
            (sys.executable, "-c", helper),
            provider="test-provider",
            model="test-model",
        )
        after = Kernel(Record(self.path)).record.history()

        self.assertTrue(proof["passed"])
        self.assertEqual(proof["assessment_status"], "semantic_review_pending")
        self.assertEqual(proof["compression"]["accepted_result_count"], 12)
        self.assertEqual(proof["compression"]["accepted_results_exposed"], 4)
        self.assertEqual(proof["compression"]["accepted_results_omitted"], 8)
        self.assertLess(
            proof["compression"]["compressed_context_bytes"],
            proof["compression"]["full_context_bytes"],
        )
        self.assertTrue(proof["checks"]["full_accepted_history_not_exposed"])
        self.assertTrue(proof["checks"]["assessment_history_not_exposed"])
        self.assertTrue(proof["checks"]["omitted_history_anchored_by_digest"])
        self.assertTrue(proof["checks"]["assessment_history_anchored_by_digest"])
        self.assertEqual(proof["compression"]["semantic_assessment_count"], 1)
        self.assertFalse(proof["checks"]["production_state_mutated"])
        self.assertEqual(before, after)

    def test_default_model_handoff_uses_one_milestone_and_zero_receipts(self) -> None:
        """Normal live-model context uses the smallest semantic slice proven so far."""
        self.kernel.submit(
            Proposal(
                "default-compressed-create",
                0,
                (
                    Operation(
                        "create_work",
                        "default-compressed",
                        {
                            "objective": "Continue from minimal governed context",
                            "constraints": ["SQLite remains authoritative"],
                        },
                    ),
                ),
            )
        )
        for index in range(3):
            self.kernel.submit(
                Proposal(
                    f"default-compressed-{index}",
                    index + 1,
                    (
                        Operation(
                            "advance_work",
                            "default-compressed",
                            {
                                "result": f"Milestone {index}",
                                "open_obligations": ["Continue the frontier"],
                            },
                        ),
                    ),
                )
            )

        helper = """
import json, sys
context = json.load(sys.stdin)
work = context["state"]["work:default-compressed"]
assert work["accepted_result_count"] == 3
assert work["accepted_results_recent"] == ["Milestone 2"]
assert work["omitted_accepted_results_count"] == 2
assert len(work["omitted_accepted_results_digest"]) == 64
assert context["recent_receipts"] == []
json.dump({
    "proposal_id": f"default-compressed-{context['revision']}",
    "based_on_revision": context["revision"],
    "operations": [{
        "action": "advance_work",
        "key": work["id"],
        "value": {
            "result": "Minimal default context continued correctly.",
            "open_obligations": ["Judge the promoted default"]
        }
    }],
    "rationale": "used the promoted default handoff"
}, sys.stdout)
"""
        proof = run_default_model_continuity_probe(
            self.path,
            "default-compressed",
            (sys.executable, "-c", helper),
            provider="test-provider",
            model="test-model",
        )
        self.assertTrue(proof["passed"])
        self.assertEqual(proof["compression"]["accepted_results_exposed"], 1)
        self.assertEqual(proof["compression"]["receipt_count_exposed"], 0)
        self.assertFalse(proof["checks"]["production_state_mutated"])

    def test_human_semantic_review_needs_no_invented_metrics(self) -> None:
        """
        Human review may append judgments only for the six durable criteria.

        The overnight runtime did not persist byte-count diagnostics into SQLite,
        so this schema must preserve truthful provenance without manufacturing
        measurements merely to satisfy the older assessment envelope.
        """
        self.kernel.submit(
            Proposal(
                "review-create",
                0,
                (
                    Operation(
                        "create_work",
                        "reviewed",
                        {"objective": "Review one model observation", "constraints": []},
                    ),
                ),
            )
        )
        review = {
            "kind": "human_semantic_review_v1",
            "verdict": "uncertain",
            "criteria": {
                "objective_fidelity": "pass",
                "history_fidelity": "pass",
                "frontier_fidelity": "uncertain",
                "compression_awareness": "pass",
                "unsupported_claims": "pass",
                "actionability": "pass",
            },
            "provenance": {
                "artifact_run_id": "123",
                "artifact_commit": "abc123",
                "context_digest": "d" * 64,
                "provider": "test-provider",
                "model": "test-model",
            },
        }
        receipt = self.kernel.submit(
            Proposal("review-assessment", 1, (Operation("record_assessment", "reviewed", review),))
        )
        self.assertEqual(receipt.status, "accepted")
        stored = self.kernel.context(work_id="reviewed").state["work:reviewed"]
        self.assertEqual(stored["semantic_assessments"], [review])
        self.assertEqual(stored["accepted_results"], [])
        self.assertEqual(stored["open_obligations"], [])

        forged = dict(review)
        forged["verdict"] = "pass"
        rejected = self.kernel.submit(
            Proposal("review-forged", 2, (Operation("record_assessment", "reviewed", forged),))
        )
        self.assertEqual(rejected.status, "rejected")
        self.assertIn("human semantic review verdict must be derived from its criteria", rejected.reasons)

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

    def test_provider_exit_codes_classify_retryable_and_quota_failures(self) -> None:
        """Continuous runners can recover provider noise but must stop on exhausted quota."""
        retryable = CommandIntelligence((sys.executable, "-c", "import sys; sys.exit(75)"))
        with self.assertRaises(ProviderTemporaryError):
            retryable.propose(self.kernel.context())

        quota = CommandIntelligence((sys.executable, "-c", "import sys; sys.exit(78)"))
        with self.assertRaises(ProviderQuotaError):
            quota.propose(self.kernel.context())

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
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("UPDATE events SET payload = ? WHERE sequence = 1", ('{}',))
            connection.commit()
        with self.assertRaises(IntegrityError):
            self.kernel.context()

    def test_static_report_exposes_state_and_receipt_provenance(self) -> None:
        """The phone projection prioritizes status and the human-readable exchange."""
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
                "assessment_status": "semantic_review_pending",
                "candidate_result": "Reconstruction: continue safely. Proposed next step: inspect the frontier.",
                "candidate_rationale": "The durable objective identifies the frontier.",
                "semantic_review": {
                    "evidence": {
                        "objective": "Preserve the work across model replacement",
                        "accepted_results": ["Bounded context reached Gemini"],
                        "open_obligations": ["Inspect the frontier"],
                        "constraints": ["Do not mutate production during proof"],
                    }
                },
            },
            control_url="https://control.example",
        )
        # Public visitors see the experiment before any operator-only technical
        # material. The technical view is present in the static artifact but must
        # remain hidden until the authenticated control service validates a session.
        self.assertLess(page.index("Latest exchange"), page.index("Technical view"))
        self.assertIn("Stress matrix", page)
        self.assertIn("data-exchange-matrix", page)
        self.assertIn("data-exchange-coordinate", page)
        self.assertIn("Protocol gate", page)
        self.assertIn("Semantic review", page)
        self.assertIn("data-exchange-protocol>PASS</b>", page)
        self.assertIn("data-exchange-semantic>PENDING</b>", page)
        self.assertIn("protocol_gate_passed", page)
        self.assertIn("semantic_review_status", page)
        self.assertIn("pass '+pass+' · '+position+'/'+size", page)
        self.assertIn("CHECKING…", page)
        self.assertIn("Loading current status…", page)
        self.assertIn('data-fallback-state="CONTINUOUS"', page)
        self.assertIn("The experiment is running", page)
        self.assertNotIn("expectedHeartbeat", page)
        self.assertNotIn('data-fallback-state="WAITING FOR YOU"', page)
        self.assertIn("What Gemini was asked", page)
        self.assertIn("What Gemini responded", page)
        self.assertIn("What happened", page)
        self.assertIn("Gemini understood: continue safely.", page)
        self.assertNotIn("Why: The durable objective identifies the frontier.", page)
        self.assertIn('data-owner-technical hidden', page)
        self.assertIn("if(ownerTechnical)ownerTechnical.hidden=false", page)
        self.assertIn("if(ownerTechnical)ownerTechnical.hidden=true", page)
        self.assertIn("data-exchange-response", page)
        self.assertIn("sudofx-live/live.json", page)
        self.assertNotIn("fetch('./continuity-proof.json?ts='", page)
        self.assertIn("setInterval(refreshExchange,15000)", page)
        self.assertIn("manual-evaluations.json", page)
        self.assertIn("refreshManualEvidence", page)
        self.assertIn("Live manual grounding evidence", page)
        self.assertIn("Exact packet grounding only · semantic fidelity is reviewed separately.", page)
        self.assertIn("Semantic review queue", page)
        self.assertIn("Human judgment is recorded separately from protocol success and is bound to this exact run + digest.", page)
        self.assertIn("data-semantic-review-criteria", page)
        self.assertIn("data-semantic-review-run", page)
        self.assertIn("data-semantic-review-digest", page)
        # A signed-in owner has stronger evidence than the anonymous observer.
        # Stop must therefore replace a stale continuous fallback everywhere,
        # not merely beside the buttons at the bottom of the status panel.
        self.assertIn("Authenticated owner control confirms the workflow is disabled", page)
        self.assertIn("Continuous tests stopped by owner", page)
        self.assertIn("if(ownerSession()&&await refreshOwnerControls())return", page)
        self.assertIn('data-published-run-id="123"', page)
        # Live telemetry updates the status and Gemini exchange in place. A
        # whole-page refresh here would repeatedly reset the mobile viewport
        # while the continuous runner publishes faster than CDN caches settle.
        self.assertNotIn("refreshPublishedPage", page)
        self.assertNotIn("window.location.replace(target.toString())", page)
        self.assertIn("Activity history", page)
        self.assertIn("overflow-x:hidden", page)
        # Long digests are normal durable evidence. Hiding horizontal overflow
        # alone would truncate them, so the content owner must break the token.
        self.assertIn(".work-section li,.final-result p,.work-head code", page)
        self.assertIn("overflow-wrap:anywhere; word-break:break-word", page)
        self.assertIn("grid-template-columns:minmax(0,1fr) auto", page)
        self.assertNotIn("General state", page)
        self.assertNotIn("Technical pass", page)
        self.assertNotIn("Phone-ready verification", page)
        self.assertIn("objective", page)
        self.assertIn("continue", page)
        self.assertIn("proposal p1", page)
        self.assertNotIn("Run operation", page)
        self.assertIn("data-status-led", page)
        self.assertIn("status-led checking", page)
        self.assertIn("led-blink", page)
        self.assertIn("wake-theme", page)
        self.assertIn("data-theme=dark", page)
        # Green is the accepted toggle highlight. The switch remains the only
        # visual indicator so no redundant glyph can drift out of alignment.
        self.assertIn("background:var(--green)", page)
        self.assertNotIn("theme-icon", page)
        self.assertIn("width:1px; height:1px", page)
        # Brand and masthead actions share the top row; the tagline stays below.
        # This protects the compact phone layout from wrapping operator controls.
        self.assertIn('grid-template-areas:"brand actions" "tagline tagline"', page)
        self.assertIn('class="masthead-actions"', page)
        self.assertIn('aria-label="Open Settings"', page)
        self.assertNotIn('>Operator sign in<', page)
        self.assertIn('.owner-login[hidden]', page)
        self.assertNotIn('i::before { content:"☀"', page)
        self.assertIn('class="brand" href="./"', page)
        self.assertIn('href="https://sudofx.github.io/wake/" target="_blank"', page)
        # Operator access uses the same masthead popover contract as WAKE. The
        # authenticated actions remain hidden until the control service verifies
        # the encrypted session, even though the sign-in link is always visible.
        self.assertIn('href="https://control.example/auth/login"', page)
        self.assertLess(page.index('data-owner-access'), page.index('</header>'))
        self.assertIn('class="owner-menu-toggle"', page)
        self.assertIn('data-owner-menu-label>Settings</span>', page)
        self.assertIn('data-owner-controls hidden', page)
        self.assertIn('class="owner-control-actions"', page)
        self.assertIn('data-owner-start>Start</button>', page)
        self.assertIn('data-owner-stop>Stop</button>', page)
        self.assertIn('data-owner-backup hidden>Backup</button>', page)
        self.assertIn('data-owner-signout>Sign out</button>', page)
        self.assertIn('.owner-access { position:relative; z-index:2000', page)
        self.assertIn('position:fixed; top:52px; right:16px', page)
        self.assertIn("setOwnerMenu(ownerControls.hidden)", page)
        self.assertIn("'/api/backup'", page)
        # Every phone action keeps its panel open and leaves a success or error
        # result visible. This prevents an accepted or rejected request from
        # looking like an unexplained dismissal on iOS.
        self.assertIn("event?.stopPropagation()", page)
        self.assertIn("ownerControlStatus.textContent='Requesting '+label+'…'", page)
        self.assertIn("ownerControlStatus.textContent='Request failed: '+error.message", page)
        self.assertIn("operateOwnerControl('/api/backup',event,false)", page)
        self.assertIn("public state", page)
        self.assertIn("localStorage.setItem(ownerSessionKey", page)
        self.assertIn("localStorage.getItem(ownerSessionKey", page)
        self.assertIn("const legacy=sessionStorage.getItem(ownerSessionKey)", page)
        self.assertIn("sessionStorage.removeItem(ownerSessionKey)", page)
        self.assertNotIn("GITHUB_CLIENT_SECRET", page)

    def test_latest_overnight_projection_preserves_runtime_provenance(self) -> None:
        """Pages must not confuse renderer provenance with model-runtime provenance."""
        experiment = {
            "version": 3,
            "cycle": 17,
            "matrix_cycle": 17,
            "matrix_size": 343,
            "coordinate": {
                "semantic_lens": "authority_boundary",
                "exposure": "minimal",
                "pressure": "authority_injection",
            },
            "phase": "authority_boundary",
            "latest_observation": {
                "cycle": 17,
                "phase": "authority_boundary",
                "task": "Respect the authority boundary.",
                "candidate_result": "Gemini understood: authority stays with the system.",
                "candidate_rationale": "bounded evidence",
                "candidate_open_obligations": [],
                "context_digest": "d" * 64,
                "provider": "Google Gemini",
                "model": "gemini-3.5-flash-lite",
                "artifact_run_id": "run-17",
                "artifact_commit": "runtime-commit-17",
                "source_event_head": "e" * 64,
            },
        }
        self.kernel.submit(
            Proposal(
                "overnight-projection",
                0,
                (Operation("set", "experiment:overnight-continuity-v1", experiment),),
            )
        )
        proof = latest_overnight_proof(self.kernel)
        self.assertIsNotNone(proof)
        assert proof is not None
        self.assertEqual(proof["artifact_commit"], "runtime-commit-17")
        trial = proof["overnight_trial"]
        self.assertEqual(trial["matrix_cycle"], 17)
        self.assertEqual(trial["matrix_size"], 343)
        self.assertEqual(trial["coordinate"]["pressure"], "authority_injection")

    def test_report_wraps_matrix_progress_without_exceeding_one_hundred_percent(self) -> None:
        page = render(
            self.kernel,
            continuity_proof={
                "passed": True,
                "artifact_run_id": "wrap",
                "candidate_result": "Gemini understood: wrapped matrix.",
                "overnight_trial": {
                    "cycle": 344,
                    "matrix_cycle": 344,
                    "matrix_size": 343,
                    "coordinate": {
                        "semantic_lens": "reconstruction",
                        "exposure": "rich",
                        "pressure": "clean",
                    },
                },
            },
        )
        self.assertIn("pass 2 · 1/343 (0.3%)", page)
        self.assertNotIn("344/343", page)
        self.assertNotIn("100.3%", page)

    def test_exported_runner_state_continues_after_bounded_model_review(self) -> None:
        """
        The cloud chain must continue from verified artifact meaning, not run color.

        Continuous testing is explicitly authorized, while the model proposal is
        still isolated from durable state. A completed review proof therefore
        authorizes another test cycle without authorizing the proposed mutation.
        """
        destination = Path(self.tempdir.name) / "site"
        export_site(
            self.kernel,
            destination,
            continuity_proof={
                "passed": True,
                "assessment_status": "semantic_review_pending",
                "artifact_run_id": "456",
                "artifact_commit": "abcdef",
            },
        )
        state = json.loads(
            (destination / "runner-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state["schema_version"], 1)
        self.assertEqual(state["disposition"], "CONTINUE")
        self.assertEqual(state["artifact_run_id"], "456")

    def test_continuation_workflow_is_a_single_success_only_cloud_chain(self) -> None:
        """Continuous operation must self-dispatch once and stop on any failed gate."""
        workflow = (Path(__file__).parents[1] / ".github/workflows/prove-model.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("actions: write", workflow)
        self.assertIn("continue-again:", workflow)
        self.assertIn("needs: continue", workflow)
        self.assertIn("gh workflow run prove-model.yml", workflow)
        self.assertIn("actions/workflows/sudofx.yml/runs?per_page=20", workflow)
        self.assertIn('select(.status != "completed")', workflow)
        self.assertIn("yielding the authority lane", workflow)
        self.assertNotIn("gh workflow run pages.yml", workflow)
        self.assertNotIn("request-publication:", workflow)
        self.assertNotIn("actions/deploy-pages", workflow)
        self.assertNotIn("actions/upload-pages-artifact", workflow)
        self.assertIn("operator_start:", workflow)
        self.assertIn("--operator-start", workflow)
        self.assertIn("runtime_ref:", workflow)
        self.assertIn("ref: ${{ inputs.runtime_ref || github.sha }}", workflow)
        self.assertIn('-f "runtime_ref=$RUNTIME_REF"', workflow)
        self.assertNotIn("cron:", workflow)
        self.assertNotIn("\n  push:", workflow)

    def test_semantic_review_ui_defaults_to_pass_and_confirms_submission(self) -> None:
        """Phone review should be one-tap by default and visibly acknowledge dispatch."""
        self.kernel.submit(
            Proposal(
                "create-review-ui",
                0,
                (Operation("create_work", "handoff-v1", {"objective": "Portable continuity", "constraints": []}),),
            )
        )
        page = render(
            self.kernel,
            continuity_proof={
                "semantic_review_status": "pending",
                "assessment_status": "semantic_review_pending",
                "artifact_run_id": "123",
                "context_digest": "a" * 64,
            },
        )
        self.assertEqual(page.count('<option value="pass" selected>PASS</option>'), 6)
        self.assertNotIn('<option value="uncertain" selected>UNCERTAIN</option>', page)
        self.assertIn("Submitted ✓", page)
        self.assertIn("Checking the live record", page)
        self.assertIn("await refreshExchange()", page)

    def test_semantic_review_resolves_historical_authoritative_target(self) -> None:
        """Human review must survive runner advancement without accepting invented targets."""
        repository_root = Path(__file__).resolve().parents[1]
        source = (repository_root / "scripts" / "github_sudofx.py").read_text(encoding="utf-8")
        workflow = (repository_root / ".github" / "workflows" / "sudofx.yml").read_text(encoding="utf-8")
        self.assertIn("def frozen_overnight_proof(", source)
        self.assertIn('git("rev-list", f"origin/{STATE_BRANCH}"', source)
        self.assertIn('raise ValueError("semantic review names no overnight observation in durable state history")', source)
        self.assertIn("semantic review for this exact run and context is already recorded", source)
        self.assertNotIn("semantic review target is stale or mismatched", source)
        self.assertIn("exact authoritative", workflow)
        self.assertIn("Runner advancement is allowed", workflow)

    def test_ci_pages_and_authority_workflows_are_separated(self) -> None:
        """Push CI, replaceable publication, and state mutation must use distinct lanes."""
        root = Path(__file__).parents[1] / ".github/workflows"
        ci = (root / "ci.yml").read_text(encoding="utf-8")
        pages = (root / "pages.yml").read_text(encoding="utf-8")
        operator = (root / "sudofx.yml").read_text(encoding="utf-8")
        continuity = (root / "prove-model.yml").read_text(encoding="utf-8")

        self.assertIn("\n  push:", ci)
        self.assertIn("pull_request:", ci)
        self.assertIn("cancel-in-progress: true", ci)
        self.assertNotIn("GEMINI_API_KEY", ci)
        self.assertNotIn("workflow_dispatch:", operator.split("on:", 1)[0])

        self.assertIn("group: sudofx-pages", pages)
        self.assertIn("cancel-in-progress: true", pages)
        self.assertIn("--publish-only", pages)
        self.assertNotIn("workflow_dispatch:", pages)
        pages_triggers = pages.split("permissions:", 1)[0]
        self.assertNotIn("'scripts/github_sudofx.py'", pages_triggers)
        self.assertNotIn("GEMINI_API_KEY", pages)

        self.assertNotIn("\n  push:", operator)
        self.assertNotIn("gh workflow run pages.yml", operator)
        self.assertIn("group: sudofx-authority-v3", operator)
        self.assertIn("group: sudofx-authority-v3", continuity)
        self.assertNotIn("group: sudofx-pages", operator)
        self.assertNotIn("group: sudofx-pages", continuity)

    def test_live_exchange_is_outside_pages_and_disposable(self) -> None:
        """Cycles must refresh one replaceable live view without deploying Pages."""
        root = Path(__file__).parents[1]
        overnight = (root / "scripts/overnight_sudofx.py").read_text(encoding="utf-8")
        adapter = (root / "scripts/github_sudofx.py").read_text(encoding="utf-8")
        report = (root / "src/sudofx/report.py").read_text(encoding="utf-8")

        self.assertIn("publish_live_projection", overnight)
        self.assertIn("build_manual_evaluation_projection", overnight)
        self.assertNotIn("cloud.export_site(", overnight)
        self.assertIn('["git", "rev-parse", "HEAD"]', overnight)
        self.assertIn('proof["artifact_commit"] = _checked_out_commit()', overnight)
        self.assertIn('"protocol_gate_passed": True', overnight)
        self.assertIn('"semantic_review_status": "pending"', overnight)
        self.assertIn('LIVE_BRANCH = "sudofx-live"', adapter)
        self.assertIn("manual_evaluation_projection_updated", adapter)
        self.assertIn("A disposable observer-view", adapter)
        self.assertIn('"push", "--force"', adapter)
        self.assertIn("sudofx-live/live.json", report)
        self.assertNotIn("fetch('./continuity-proof.json?ts='", report)

    def test_recovery_workflow_retains_verified_backup_outside_pages(self) -> None:
        """Owner backup must be finite, authenticated, and excluded from public output."""
        workflow = (Path(__file__).parents[1] / ".github/workflows/sudofx.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("inputs.action == 'operator-stop'", workflow)
        self.assertIn("--operator-transition stop", workflow)
        self.assertIn("inputs.action == 'backup'", workflow)
        self.assertIn("--backup recovery/sudofx.sqlite", workflow)
        # Keep the backup action on the Node.js 24-compatible generation. An
        # obsolete runner dependency would make recovery decay even while the
        # storage contract itself remained correct.
        self.assertIn("actions/upload-artifact@v7", workflow)
        self.assertIn("retention-days: 30", workflow)
        self.assertNotIn("path: recovery\n", workflow)

    def test_handoff_packet_is_bounded_and_portable(self) -> None:
        """Handoff v1 must export one governed work item without unrelated state."""
        self.kernel.submit(
            Proposal(
                "handoff-create",
                0,
                (
                    Operation(
                        "create_work",
                        "handoff-v1",
                        {
                            "objective": "Continue the project from durable context",
                            "constraints": ["Use only governed context"],
                        },
                    ),
                ),
            )
        )
        self.kernel.submit(
            Proposal(
                "handoff-progress",
                1,
                (
                    Operation(
                        "advance_work",
                        "handoff-v1",
                        {
                            "result": "Defined the north star",
                            "open_obligations": ["Run a fresh-model handoff"],
                        },
                    ),
                ),
            )
        )
        self.kernel.submit(Proposal("private-decoy", 2, (Operation("set", "private", "nope"),)))
        packet = build_handoff_packet(self.kernel, "handoff-v1")
        self.assertEqual(packet["handoff_version"], 1)
        self.assertEqual(packet["work_id"], "handoff-v1")
        self.assertEqual(packet["work"]["objective"], "Continue the project from durable context")
        self.assertEqual(packet["work"]["open_obligations"], ["Run a fresh-model handoff"])
        self.assertEqual(packet["work"]["accepted_results_recent"], ["Defined the north star"])
        self.assertEqual(packet["work"]["accepted_result_count"], 1)
        self.assertEqual(packet["work"]["omitted_accepted_results_count"], 0)
        self.assertNotIn("accepted_results", packet["work"])
        self.assertEqual(packet["receipt_provenance"], [])
        self.assertNotIn("private", str(packet))
        self.assertEqual(len(packet["packet_digest"]), 64)

        with tempfile.TemporaryDirectory() as temporary:
            json_path, prompt_path = export_handoff_packet(self.kernel, temporary, "handoff-v1")
            self.assertTrue(json_path.exists())
            self.assertTrue(prompt_path.exists())
            self.assertIn("SUDOFX_HANDOFF v1", prompt_path.read_text())
            self.assertIn('"packet_digest"', json_path.read_text())

        page = render(self.kernel, control_url="https://control.example")
        # Manual provider use belongs to the authenticated operator surface. The
        # four destinations share one provider-neutral packet. Returned output
        # remains transient until the existing operator session submits it to
        # the bounded remote_operator capability.
        self.assertIn("Manual AI handoff", page)
        for provider in ("ChatGPT", "Claude", "Gemini", "DeepSeek"):
            self.assertIn(f'data-handoff-provider="{provider}"', page)
        self.assertIn('href="com.openai.chat://"', page)
        self.assertIn('href="claude://"', page)
        self.assertIn('href="https://gemini.google.com/app" target="_blank" rel="noopener noreferrer"', page)
        self.assertIn('href="deepseek://"', page)
        self.assertIn("temporary-chat=true&prompt=", page)
        self.assertIn("encodeURIComponent(handoffPrompt.value)", page)
        self.assertIn("Tap Send; if the draft is empty", page)
        self.assertIn("accepted_results_recent", page)
        self.assertIn("omitted_accepted_results_digest", page)
        self.assertNotIn('"accepted_results":', page)
        self.assertIn("navigator.clipboard.writeText", page)
        self.assertIn("navigator.clipboard.readText", page)
        self.assertIn("Paste the complete response here", page)
        self.assertIn("Paste &amp; submit result", page)
        self.assertIn("action:'handoff-evaluate',response", page)
        self.assertIn("'/api/operate','POST'", page)
        self.assertIn("#handoff-evaluate", page)
        self.assertIn("sudofx-pending-handoff-evaluation", page)
        self.assertIn("location.assign(controlUrl+'/auth/login')", page)
        self.assertIn("if(pendingHandoffReturn()&&controlUrl)location.assign", page)
        self.assertIn("capabilities.includes('handoff-evaluate')", page)
        self.assertNotIn("Keep it here", page)
        self.assertIn("CURRENT OPERATOR AUTHORIZATION", page)
        self.assertIn("exactly one manual response", page)
        self.assertIn("opening. Paste the copied prompt", page)
        self.assertIn("Return only one JSON object", page)
        self.assertIn("Do not cite CURRENT OPERATOR AUTHORIZATION or TRANSPORT METADATA as evidence", page)
        self.assertIn("Do not use this authorization paragraph as evidence", page)
        self.assertIn("__SUDOFX_VENDOR__", page)
        self.assertIn("__SUDOFX_TEST_ID__", page)
        self.assertIn("__SUDOFX_NONCE__", page)
        self.assertIn("objective_fidelity", page)
        self.assertIn("authority_fidelity", page)
        self.assertIn("epistemic_discipline", page)
        self.assertIn("transfer_usability", page)
        self.assertIn("crypto.getRandomValues", page)
        self.assertIn("const nonce='HANDOFF-'+testId", page)
        self.assertNotIn("Return exactly these labeled sections", page)
        # The response never enters a URL or persistent browser storage. The
        # fragment carries intent only; the clipboard supplies transient text
        # after an authenticated user gesture.
        self.assertNotIn("encodeURIComponent(response)", page)
        self.assertNotIn("localStorage.setItem(handoffReturnKey", page)

    def test_record_initializes_inside_an_existing_empty_directory(self) -> None:
        """A first cloud run may create a record once its explicit parent exists."""
        nested = Path(self.tempdir.name) / "cloud-data" / "record.sqlite"
        nested.parent.mkdir(parents=True)
        kernel = Kernel(Record(nested))
        self.assertEqual(kernel.context().revision, 0)

    def test_record_migrates_legacy_header_and_rejects_unknown_future_schema(self) -> None:
        """
        Storage identity must be explicit before later schema changes accumulate.

        Version zero is the one supported legacy shape. A newer version must
        fail closed so older code cannot reinterpret data it does not understand.
        """
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA application_id = 0")
            connection.execute("PRAGMA user_version = 0")
        migrated = Record(self.path)
        self.assertTrue(migrated.schema_changed)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA application_id").fetchone()[0], APPLICATION_ID)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        with self.assertRaises(StorageVersionError):
            Record(self.path)

    def test_snapshot_includes_committed_wal_pages_and_replays(self) -> None:
        """A checkpoint snapshot must include commits not yet folded into the main file."""
        # Holding a reader snapshot prevents WAL reset while another connection
        # appends. A raw main-file copy can miss that append; SQLite backup must
        # produce a complete snapshot that reconstructs the newer revision.
        with closing(sqlite3.connect(self.path)) as reader:
            reader.execute("BEGIN")
            reader.execute("SELECT COUNT(*) FROM events").fetchone()
            self.kernel.submit(Proposal("wal-event", 0, (Operation("set", "safe", True),)))
            snapshot = Path(self.tempdir.name) / "snapshot.sqlite"
            self.kernel.record.backup_to(snapshot)
        recovered = Kernel(Record(snapshot)).context()
        self.assertEqual(recovered.revision, 1)
        self.assertEqual(recovered.state, {"safe": True})

    def test_vacuum_snapshot_replays_without_mutating_authority(self) -> None:
        """VACUUM INTO yields a replayable derivative while source authority stays unchanged."""
        accepted = self.kernel.submit(
            Proposal("vacuum-source", 0, (Operation("set", "recoverable", True),))
        )
        self.assertEqual(accepted.status, "accepted")
        before = self.kernel.context()
        source_head = self.kernel.record.history()[-1]["event_hash"]

        snapshot = Path(self.tempdir.name) / "vacuum-snapshot.sqlite"
        self.kernel.record.vacuum_snapshot_to(snapshot)

        recovered = Kernel(Record(snapshot)).context()
        after = self.kernel.context()
        self.assertEqual(recovered.revision, before.revision)
        self.assertEqual(recovered.state, before.state)
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(after.state, before.state)
        self.assertEqual(self.kernel.record.history()[-1]["event_hash"], source_head)
        with closing(sqlite3.connect(snapshot)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_projection_history_is_bounded_without_pruning_authority(self) -> None:
        """A growing record must not create an unbounded public page or lose receipts."""
        for revision in range(60):
            self.kernel.submit(
                Proposal(
                    f"event-{revision}",
                    revision,
                    (Operation("set", "counter", revision),),
                )
            )
        page = render(self.kernel)
        self.assertEqual(len(self.kernel.record.history()), 60)
        self.assertEqual(len(self.kernel.record.history_tail(50)), 50)
        self.assertIn("showing 50 of 60 receipts", page)
        self.assertNotIn("proposal event-0", page)
        self.assertIn("proposal event-59", page)
        self.assertEqual(self.kernel.record.health()["quick_check"], "ok")

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
        self.assertIn("Current work", page)
        self.assertIn("Visible work", page)
        self.assertNotIn("Create or advance", page)

    def test_handoff_evaluation_is_bound_scored_and_governed(self) -> None:
        """A shared answer must match the packet and cite it before becoming evidence."""
        self.kernel.submit(
            Proposal(
                "create-handoff-evaluation",
                0,
                (Operation("create_work", "handoff-v1", {"objective": "Portable continuity", "constraints": []}),),
            )
        )
        packet = build_handoff_packet(self.kernel, "handoff-v1")
        evidence = packet["work"]["objective"]
        response = {
            "test_id": "UUID-123456",
            "nonce": "HANDOFF-UUID-123456",
            "vendor": "ChatGPT",
            "work_id": packet["work_id"],
            "packet_digest": packet["packet_digest"],
            "answers": {
                dimension: {"answer": f"Grounded answer for {dimension}", "evidence": evidence}
                for dimension in DIMENSIONS
            },
        }
        result = evaluate_handoff_response(json.dumps(response), packet)
        self.assertEqual(result["score"], 7)
        receipt = self.kernel.submit(
            Proposal("record-handoff-evaluation", 1, (Operation("record_handoff_evaluation", "handoff-v1", result),))
        )
        self.assertEqual(receipt.status, "accepted")
        saved = self.kernel.context().state["work:handoff-v1"]["handoff_evaluations"][0]
        self.assertEqual(saved["test_id"], response["test_id"])
        self.assertEqual(saved["work_id"], response["work_id"])
        self.assertEqual(saved["scorer_version"], 2)
        self.assertIn("visible COMPLETE JSON PACKET", saved["score_kind"])
        self.assertEqual(saved["raw_response"], json.dumps(response))
        second_response = dict(response)
        second_response["test_id"] = "UUID-333333"
        second_response["nonce"] = "HANDOFF-UUID-333333"
        second_response["vendor"] = "DeepSeek"
        second_result = evaluate_handoff_response(json.dumps(second_response), packet)
        second_receipt = self.kernel.submit(
            Proposal(
                "record-second-handoff-evaluation",
                2,
                (Operation("record_handoff_evaluation", "handoff-v1", second_result),),
            )
        )
        self.assertEqual(second_receipt.status, "accepted")

        page = render(self.kernel)
        self.assertIn("scorer v2", page)
        self.assertIn("Manual handoff grounding", page)
        self.assertIn("Objective grounding", page)
        self.assertIn("Manual tests recorded <b>2</b>", page)
        self.assertIn("Comparable grounding batch <b>2 tests · 2 vendors · 14/14</b>", page)
        self.assertIn("Recent manual test history", page)
        self.assertIn(response["test_id"], page)
        self.assertIn(second_response["test_id"], page)
        self.assertIn(packet["packet_digest"][:10], page)

        projection = build_manual_evaluation_projection(self.kernel, "handoff-v1")
        self.assertEqual(projection["total_tests"], 2)
        self.assertEqual(projection["comparable_batch"]["tests"], 2)
        self.assertEqual(projection["comparable_batch"]["vendors"], ["ChatGPT", "DeepSeek"])
        self.assertEqual(projection["comparable_batch"]["score"], 14)
        self.assertEqual(projection["comparable_batch"]["max_score"], 14)
        self.assertNotIn("raw_response", json.dumps(projection))

        wrong_work = dict(response)
        wrong_work["work_id"] = "different-work"
        with self.assertRaisesRegex(ValueError, "different work item"):
            evaluate_handoff_response(json.dumps(wrong_work), packet)

        response["packet_digest"] = "stale"
        with self.assertRaisesRegex(ValueError, "different packet"):
            evaluate_handoff_response(json.dumps(response), packet)

    def test_handoff_evaluation_accepts_consumer_chat_json_typography(self) -> None:
        """Smart quotes and a JSON fence are transport decoration, not semantic failure."""
        self.kernel.submit(
            Proposal(
                "create-smart-handoff-evaluation",
                0,
                (Operation("create_work", "handoff-v1", {"objective": "Portable continuity", "constraints": []}),),
            )
        )
        packet = build_handoff_packet(self.kernel, "handoff-v1")
        evidence = packet["work"]["objective"]
        response = {
            "test_id": "UUID-654321",
            "nonce": "HANDOFF-UUID-654321",
            "vendor": "ChatGPT",
            "work_id": packet["work_id"],
            "packet_digest": packet["packet_digest"],
            "answers": {
                dimension: {"answer": dimension, "evidence": evidence}
                for dimension in DIMENSIONS
            },
        }
        decorated = "```json\n" + json.dumps(response).replace('"', "\u201c") + "\n```"
        self.assertEqual(handoff_packet_digest(decorated), packet["packet_digest"])
        self.assertEqual(handoff_work_id(decorated), packet["work_id"])
        self.assertEqual(evaluate_handoff_response(decorated, packet)["score"], 7)

    def test_handoff_evidence_matches_the_visible_packet_serialization(self) -> None:
        """Exact quote means the JSON packet shown to the model, including its readable formatting."""
        self.kernel.submit(
            Proposal(
                "create-visible-handoff-evaluation",
                0,
                (Operation("create_work", "handoff-v1", {"objective": "Portable continuity", "constraints": []}),),
            )
        )
        packet = build_handoff_packet(self.kernel, "handoff-v1")
        visible_evidence = f'"record_revision": {packet["record_revision"]}'
        response = {
            "test_id": "UUID-222222",
            "nonce": "HANDOFF-UUID-222222",
            "vendor": "Claude",
            "work_id": packet["work_id"],
            "packet_digest": packet["packet_digest"],
            "answers": {
                dimension: {"answer": dimension, "evidence": visible_evidence}
                for dimension in DIMENSIONS
            },
        }
        self.assertEqual(evaluate_handoff_response(json.dumps(response), packet)["score"], 7)

        response["answers"]["objective_fidelity"]["evidence"] = visible_evidence.upper()
        result = evaluate_handoff_response(json.dumps(response), packet)
        self.assertEqual(result["criteria"]["objective_fidelity"], "fail")
        self.assertEqual(result["score"], 6)


if __name__ == "__main__":
    unittest.main()
