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
    ApplicationAction,
    ApplicationDecision,
    ApplicationDefinition,
    ApplicationHost,
    ApplicationIntent,
    ApplicationPermissions,
    ApplicationRegistry,
    CommandIntelligence,
    Context,
    FakeIntelligence,
    FakeWorkIntelligence,
    InvocationLifecycle,
    Kernel,
    Operation,
    Proposal,
    ProviderError,
    ProviderQuotaError,
    ProviderTemporaryError,
    Runtime,
    SubmissionProvenance,
)
from sudofx.record import APPLICATION_ID, SCHEMA_VERSION, IntegrityError, Record, StorageVersionError
from sudofx.governance import Governance
from applications.conversation import CONVERSATION_APPLICATION, bounded_context
from scripts.conversation_sudofx import ConversationIntelligence, ProjectedKernel
from sudofx.storage import InvocationEvent
from experiments.continuity import (
    run_compressed_model_continuity_probe,
    run_continuity_proof,
    run_default_model_continuity_probe,
    run_model_continuity_probe,
    run_work_continuity_probe,
)
from sudofx.report import _format_bytes, export_site, render
from sudofx.handoff import build_handoff_packet, export_handoff_packet
from experiments.manual_handoff.scoring import (
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
        import scripts.github_state as adapter

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
        import scripts.github_state as adapter

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
                "reviewer": "operator",
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
        self.assertIn("data-semantic-review-criteria", page)
        self.assertNotIn("data-semantic-review-submit", page)
        self.assertNotIn('data-review-criterion="objective_fidelity"', page)

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

    def test_human_semantic_review_allows_unknown_optional_runtime_provenance(self) -> None:
        """Exact historical review keeps unknown runtime metadata unknown."""
        self.kernel.submit(
            Proposal(
                "review-create-partial",
                0,
                (Operation("create_work", "reviewed", {"objective": "Review one observation", "constraints": []}),),
            )
        )
        assessment = {
            "kind": "human_semantic_review_v1",
            "verdict": "pass",
            "criteria": {
                "objective_fidelity": "pass",
                "history_fidelity": "pass",
                "frontier_fidelity": "pass",
                "compression_awareness": "pass",
                "unsupported_claims": "pass",
                "actionability": "pass",
            },
            "provenance": {
                "artifact_run_id": "run-old",
                "context_digest": "d" * 64,
                "reviewer": "chatgpt",
            },
        }
        receipt = self.kernel.submit(
            Proposal("review-partial", 1, (Operation("record_assessment", "reviewed", assessment),))
        )
        self.assertEqual(receipt.status, "accepted")

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
                "reviewer": "operator",
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

    def test_application_contract_governs_domain_transition_and_replays_without_app(self) -> None:
        """Accepted app state must remain replayable after application code is absent."""
        def increment(current, payload):
            current = current if isinstance(current, dict) else {"count": 0}
            if not isinstance(payload, int) or isinstance(payload, bool) or payload <= 0:
                return ApplicationDecision(False, reasons=("increment must be a positive integer",))
            return ApplicationDecision(True, {"count": int(current.get("count", 0)) + payload})

        definition = ApplicationDefinition(
            "counter",
            "1",
            (ApplicationAction("increment", increment),),
            frozenset({"notify"}),
        )
        registry = ApplicationRegistry((definition,))
        kernel = Kernel(self.kernel.record, Governance(application_registry=registry))
        host = ApplicationHost(kernel, registry, "counter")

        receipt = host.submit(
            ApplicationIntent("app-increment", 0, "increment", 2),
            provenance=SubmissionProvenance("application", "counter", "unit-test"),
        )
        self.assertEqual(receipt.status, "accepted")
        self.assertEqual(host.context().state, {"count": 2})

        # A fresh kernel with no registry still reconstructs accepted history.
        replayed = Kernel(Record(self.path)).context().state
        self.assertEqual(
            replayed["app:counter"],
            {
                "application_id": "counter",
                "application_version": "1",
                "state": {"count": 2},
            },
        )

    def test_application_namespace_rejects_direct_generic_mutation(self) -> None:
        """An app cannot bypass its policy by issuing ordinary set/delete operations."""
        registry = ApplicationRegistry((
            ApplicationDefinition(
                "sealed",
                "1",
                (ApplicationAction("replace", lambda current, payload: ApplicationDecision(True, payload)),),
            ),
        ))
        kernel = Kernel(self.kernel.record, Governance(application_registry=registry))
        receipt = kernel.submit(
            Proposal("app-bypass", 0, (Operation("set", "app:sealed", {"forged": True}),))
        )
        self.assertEqual(receipt.status, "rejected")
        self.assertIn("application namespace requires apply_application", receipt.reasons)
        self.assertNotIn("app:sealed", kernel.context().state)

    def test_application_governance_rejects_forged_next_state(self) -> None:
        """The host is not trusted to assert a domain result policy did not derive."""
        definition = ApplicationDefinition(
            "counter",
            "1",
            (ApplicationAction("increment", lambda current, payload: ApplicationDecision(True, {"count": 1})),),
        )
        registry = ApplicationRegistry((definition,))
        kernel = Kernel(self.kernel.record, Governance(application_registry=registry))
        forged = Proposal(
            "app-forged",
            0,
            (
                Operation(
                    "apply_application",
                    "counter",
                    {
                        "application_id": "counter",
                        "application_version": "1",
                        "action": "increment",
                        "input": 1,
                        "next_state": {"count": 999},
                    },
                ),
            ),
        )
        receipt = kernel.submit(forged)
        self.assertEqual(receipt.status, "rejected")
        self.assertIn(
            "application next_state does not match deterministic policy result",
            receipt.reasons,
        )
        self.assertNotIn("app:counter", kernel.context().state)

    def test_application_context_and_effect_capability_are_bounded(self) -> None:
        """Apps see their state only and may request only declared, unexecuted effects."""
        definition = ApplicationDefinition(
            "bounded",
            "1",
            (ApplicationAction("replace", lambda current, payload: ApplicationDecision(True, payload)),),
            frozenset({"notify"}),
        )
        registry = ApplicationRegistry((definition,))
        kernel = Kernel(self.kernel.record, Governance(application_registry=registry))
        kernel.submit(Proposal("unrelated-state", 0, (Operation("set", "secret", "outside-app"),)))
        host = ApplicationHost(
            kernel,
            registry,
            "bounded",
            permissions=ApplicationPermissions(frozenset({"notify"})),
        )
        accepted = host.submit(ApplicationIntent("bounded-state", 1, "replace", {"visible": True}))
        self.assertEqual(accepted.status, "accepted")
        self.assertEqual(host.context().state, {"visible": True})
        self.assertFalse(hasattr(host.context(), "recent_receipts"))

        request = host.request_effect("notify", {"message": "hello"})
        self.assertEqual(request.capability, "notify")
        self.assertEqual(request.application_id, "bounded")
        with self.assertRaises(PermissionError):
            ApplicationHost(kernel, registry, "bounded").request_effect("notify", {})
        with self.assertRaises(PermissionError):
            host.request_effect("network-admin", {})

    def test_second_application_uses_same_kernel_contract_without_core_changes(self) -> None:
        """A materially different app must fit the same generic authority seam."""
        def append_entry(current, payload):
            entries = list(current) if isinstance(current, list) else []
            if not isinstance(payload, str) or not payload.strip():
                return ApplicationDecision(False, reasons=("entry must be non-empty text",))
            return ApplicationDecision(True, [*entries, payload])

        notes = ApplicationDefinition(
            "notes",
            "1",
            (ApplicationAction("append", append_entry),),
        )
        registry = ApplicationRegistry((notes,))
        kernel = Kernel(self.kernel.record, Governance(application_registry=registry))
        host = ApplicationHost(kernel, registry, "notes")

        first = host.submit(ApplicationIntent("notes-1", 0, "append", "alpha"))
        second = host.submit(ApplicationIntent("notes-2", 1, "append", "beta"))
        self.assertEqual(first.status, "accepted")
        self.assertEqual(second.status, "accepted")
        self.assertEqual(host.context().state, ["alpha", "beta"])
        self.assertEqual(
            Kernel(Record(self.path)).context().state["app:notes"]["state"],
            ["alpha", "beta"],
        )
    def test_event_log_application_persists_transition_not_full_state(self) -> None:
        """Large apps may grow by governed inputs instead of whole-state snapshots."""
        def append_item(current, payload):
            items = list(current) if isinstance(current, list) else []
            if not isinstance(payload, str):
                return ApplicationDecision(False, reasons=("item must be text",))
            return ApplicationDecision(True, [*items, payload])

        definition = ApplicationDefinition(
            "compact",
            "1",
            (ApplicationAction("append", append_item),),
            state_storage="event_log",
        )
        registry = ApplicationRegistry((definition,))
        kernel = Kernel(self.kernel.record, Governance(application_registry=registry))
        host = ApplicationHost(kernel, registry, "compact")
        self.assertEqual(
            host.submit(ApplicationIntent("compact-1", 0, "append", "alpha")).status,
            "accepted",
        )
        self.assertEqual(
            host.submit(ApplicationIntent("compact-2", 1, "append", "beta")).status,
            "accepted",
        )
        self.assertEqual(host.context().state, ["alpha", "beta"])

        history = self.kernel.record.history()
        for event in history:
            value = event["proposal"]["operations"][0]["value"]
            self.assertEqual(value["storage"], "event_log")
            self.assertNotIn("next_state", value)
            self.assertEqual(len(value["result_digest"]), 64)
        generic = Kernel(Record(self.path)).context().state["app:compact"]
        self.assertEqual(generic["storage"], "event_log")
        self.assertEqual(len(generic["events"]), 2)
        self.assertNotIn("state", generic)

        reinstalled = ApplicationHost(
            Kernel(Record(self.path), Governance(application_registry=registry)),
            registry,
            "compact",
        )
        self.assertEqual(reinstalled.context().state, ["alpha", "beta"])

    def test_event_log_application_detects_same_version_policy_drift(self) -> None:
        """Stored result digests make silent behavior changes under one version visible."""
        original = ApplicationDefinition(
            "drift",
            "1",
            (ApplicationAction("set", lambda current, payload: ApplicationDecision(True, payload)),),
            state_storage="event_log",
        )
        registry = ApplicationRegistry((original,))
        kernel = Kernel(self.kernel.record, Governance(application_registry=registry))
        ApplicationHost(kernel, registry, "drift").submit(
            ApplicationIntent("drift-1", 0, "set", "expected")
        )

        changed = ApplicationDefinition(
            "drift",
            "1",
            (ApplicationAction("set", lambda current, payload: ApplicationDecision(True, "changed")),),
            state_storage="event_log",
        )
        changed_registry = ApplicationRegistry((changed,))
        changed_host = ApplicationHost(
            Kernel(Record(self.path), Governance(application_registry=changed_registry)),
            changed_registry,
            "drift",
        )
        # Normal operational context uses the verified materialized projection.
        self.assertEqual(changed_host.context().state, "expected")
        # Explicit audit still replays every historical application event under
        # the installed policy and must detect an unversioned behavior change.
        with self.assertRaisesRegex(ValueError, "replay drift detected"):
            changed_host.audit_context()
    def test_application_version_change_requires_explicit_migration(self) -> None:
        """Installing newer app code must not silently reinterpret older durable state."""
        v1 = ApplicationDefinition(
            "versioned",
            "1",
            (ApplicationAction("replace", lambda current, payload: ApplicationDecision(True, payload)),),
        )
        registry_v1 = ApplicationRegistry((v1,))
        kernel_v1 = Kernel(self.kernel.record, Governance(application_registry=registry_v1))
        ApplicationHost(kernel_v1, registry_v1, "versioned").submit(
            ApplicationIntent("versioned-v1", 0, "replace", {"shape": 1})
        )

        v2 = ApplicationDefinition(
            "versioned",
            "2",
            (ApplicationAction("replace", lambda current, payload: ApplicationDecision(True, payload)),),
        )
        registry_v2 = ApplicationRegistry((v2,))
        kernel_v2 = Kernel(self.kernel.record, Governance(application_registry=registry_v2))
        receipt = ApplicationHost(kernel_v2, registry_v2, "versioned").submit(
            ApplicationIntent("versioned-v2", 1, "replace", {"shape": 2})
        )
        self.assertEqual(receipt.status, "rejected")
        self.assertTrue(any("application migration required" in reason for reason in receipt.reasons))

    def test_conversation_provider_receives_bounded_app_context_and_governs_reply(self) -> None:
        """Phase D: one human/provider turn crosses the app and runtime boundaries."""
        registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
        kernel = Kernel(self.kernel.record, Governance(application_registry=registry))
        host = ApplicationHost(kernel, registry, "conversation")
        human = host.submit(
            ApplicationIntent("conversation-human", 0, "human_message", "Hello from the browser"),
            provenance=SubmissionProvenance("human", "operator", "unit-test"),
        )
        self.assertEqual(human.status, "accepted")

        app_context = host.context()
        projection = bounded_context(app_context.state, max_turns=2)
        bounded = Context(
            revision=app_context.revision,
            state={"app:conversation": projection},
            recent_receipts=(),
        )
        provider = (
            sys.executable,
            "-c",
            "import json,sys; data=json.load(sys.stdin); "
            "assert list(data['state']) == ['app:conversation']; "
            "json.dump({'content':'Hello back'}, sys.stdout)",
        )
        runtime = Runtime(
            ProjectedKernel(kernel, bounded),
            kernel.record,
        )
        result = runtime.run(
            ConversationIntelligence(current_state=app_context.state, provider_command=provider),
            provenance=SubmissionProvenance("model", "fake-conversation", "unit-test"),
            context_scope={"kind": "application", "application_id": "conversation"},
        )
        self.assertEqual(result.run.receipt.status, "accepted")
        turns = ApplicationHost(kernel, registry, "conversation").context().state["turns"]
        self.assertEqual(
            turns,
            [
                {"role": "human", "content": "Hello from the browser"},
                {"role": "assistant", "content": "Hello back"},
            ],
        )
        lifecycle = kernel.record.invocation_history(result.invocation_id)
        self.assertEqual(
            lifecycle[1]["context_receipt"]["scope"],
            {"kind": "application", "application_id": "conversation"},
        )

    def test_conversation_quota_failure_preserves_human_turn_and_failure_evidence(self) -> None:
        """Provider quota exhaustion must not erase already-governed human input."""
        registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
        kernel = Kernel(self.kernel.record, Governance(application_registry=registry))
        host = ApplicationHost(kernel, registry, "conversation")
        host.submit(
            ApplicationIntent("conversation-human-quota", 0, "human_message", "Please answer"),
            provenance=SubmissionProvenance("human", "operator", "unit-test"),
        )
        app_context = host.context()
        bounded = Context(
            revision=app_context.revision,
            state={"app:conversation": bounded_context(app_context.state)},
            recent_receipts=(),
        )
        runtime = Runtime(ProjectedKernel(kernel, bounded), kernel.record)
        with self.assertRaises(ProviderQuotaError):
            runtime.run(
                ConversationIntelligence(
                    current_state=app_context.state,
                    provider_command=(sys.executable, "-c", "import sys; sys.exit(78)"),
                ),
                provenance=SubmissionProvenance("model", "fake-conversation", "unit-test"),
                context_scope={"kind": "application", "application_id": "conversation"},
            )
        state = ApplicationHost(kernel, registry, "conversation").context().state
        self.assertEqual(state["turns"], [{"role": "human", "content": "Please answer"}])
        accounting = kernel.record.invocation_accounting()
        self.assertEqual(accounting["quota_exhausted"], 1)
        self.assertEqual(accounting["completed"], 0)

    def test_conversation_survives_process_replacement_across_multiple_rounds(self) -> None:
        """Phase D exit: two back-and-forth rounds continue only from durable SQLite."""
        registry_one = ApplicationRegistry((CONVERSATION_APPLICATION,))
        kernel_one = Kernel(Record(self.path), Governance(application_registry=registry_one))
        host_one = ApplicationHost(kernel_one, registry_one, "conversation")
        first_human = host_one.submit(
            ApplicationIntent("replacement-human-1", 0, "human_message", "First question"),
            provenance=SubmissionProvenance("human", "operator", "round-one"),
        )
        self.assertEqual(first_human.status, "accepted")
        first_context = host_one.context()
        first_bounded = Context(
            revision=first_context.revision,
            state={"app:conversation": bounded_context(first_context.state)},
            recent_receipts=(),
        )
        first_provider = (
            sys.executable,
            "-c",
            "import json,sys; json.load(sys.stdin); "
            "json.dump({'content':'First answer'}, sys.stdout)",
        )
        first_result = Runtime(
            ProjectedKernel(kernel_one, first_bounded),
            kernel_one.record,
        ).run(
            ConversationIntelligence(
                current_state=first_context.state,
                provider_command=first_provider,
            ),
            provenance=SubmissionProvenance("model", "replacement-provider-1", "round-one"),
            context_scope={"kind": "application", "application_id": "conversation"},
        )
        self.assertEqual(first_result.run.receipt.status, "accepted")

        # Replace every in-process application/runtime object before round two.
        # The second provider is also a new external process. No object from the
        # first round supplies conversation state to the second round.
        registry_two = ApplicationRegistry((CONVERSATION_APPLICATION,))
        kernel_two = Kernel(Record(self.path), Governance(application_registry=registry_two))
        host_two = ApplicationHost(kernel_two, registry_two, "conversation")
        recovered = host_two.context()
        self.assertEqual(
            recovered.state["turns"],
            [
                {"role": "human", "content": "First question"},
                {"role": "assistant", "content": "First answer"},
            ],
        )
        second_human = host_two.submit(
            ApplicationIntent(
                "replacement-human-2",
                recovered.revision,
                "human_message",
                "Second question",
            ),
            provenance=SubmissionProvenance("human", "operator", "round-two"),
        )
        self.assertEqual(second_human.status, "accepted")
        second_context = host_two.context()
        second_bounded = Context(
            revision=second_context.revision,
            state={"app:conversation": bounded_context(second_context.state)},
            recent_receipts=(),
        )
        second_provider = (
            sys.executable,
            "-c",
            "import json,sys; data=json.load(sys.stdin); "
            "turns=data['state']['app:conversation']['turns']; "
            "assert turns[-1] == {'role':'human','content':'Second question'}; "
            "assert turns[-2] == {'role':'assistant','content':'First answer'}; "
            "json.dump({'content':'Second answer'}, sys.stdout)",
        )
        second_result = Runtime(
            ProjectedKernel(kernel_two, second_bounded),
            kernel_two.record,
        ).run(
            ConversationIntelligence(
                current_state=second_context.state,
                provider_command=second_provider,
            ),
            provenance=SubmissionProvenance("model", "replacement-provider-2", "round-two"),
            context_scope={"kind": "application", "application_id": "conversation"},
        )
        self.assertEqual(second_result.run.receipt.status, "accepted")

        # One more fresh reconstruction proves the final transcript is database state.
        registry_three = ApplicationRegistry((CONVERSATION_APPLICATION,))
        final_kernel = Kernel(Record(self.path), Governance(application_registry=registry_three))
        final_state = ApplicationHost(final_kernel, registry_three, "conversation").context().state
        self.assertEqual(
            final_state["turns"],
            [
                {"role": "human", "content": "First question"},
                {"role": "assistant", "content": "First answer"},
                {"role": "human", "content": "Second question"},
                {"role": "assistant", "content": "Second answer"},
            ],
        )

    def test_conversation_survives_separate_python_processes(self) -> None:
        """Phase D exit: separate interpreters continue one conversation from SQLite only."""
        root = Path(__file__).resolve().parents[1]
        first_round = r"""
from pathlib import Path
import json, sys
from scripts.conversation_sudofx import commit_human_turn, commit_assistant_turn
from sudofx import SubmissionProvenance

path = Path(sys.argv[1])
commit_human_turn(
    "First process question",
    data_path=path,
    provenance=SubmissionProvenance("human", "operator", "fresh-process-one"),
)
provider = (
    sys.executable,
    "-c",
    "import json,sys; json.load(sys.stdin); "
    "json.dump({'content':'First process answer'}, sys.stdout)",
)
reply = commit_assistant_turn(
    data_path=path,
    provider_command=provider,
    provenance=SubmissionProvenance("model", "fixture", "fresh-process-one"),
)
assert reply == "First process answer"
"""
        second_round = r"""
from pathlib import Path
import sys
from scripts.conversation_sudofx import commit_human_turn, commit_assistant_turn
from sudofx import SubmissionProvenance

path = Path(sys.argv[1])
commit_human_turn(
    "Second process question",
    data_path=path,
    provenance=SubmissionProvenance("human", "operator", "fresh-process-two"),
)
provider = (
    sys.executable,
    "-c",
    "import json,sys; data=json.load(sys.stdin); "
    "turns=data['state']['app:conversation']['turns']; "
    "assert turns[-2] == {'role':'assistant','content':'First process answer'}; "
    "assert turns[-1] == {'role':'human','content':'Second process question'}; "
    "json.dump({'content':'Second process answer'}, sys.stdout)",
)
reply = commit_assistant_turn(
    data_path=path,
    provider_command=provider,
    provenance=SubmissionProvenance("model", "fixture", "fresh-process-two"),
)
assert reply == "Second process answer"
"""
        inspect_round = r"""
from pathlib import Path
import json, sys
from applications.conversation import CONVERSATION_APPLICATION
from sudofx import ApplicationHost, ApplicationRegistry, Kernel
from sudofx.governance import Governance
from sudofx.record import Record

path = Path(sys.argv[1])
registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
kernel = Kernel(Record(path), Governance(application_registry=registry))
state = ApplicationHost(kernel, registry, "conversation").context().state
print(json.dumps(state["turns"]))
"""
        for script in (first_round, second_round):
            completed = subprocess.run(
                [sys.executable, "-c", script, str(self.path)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

        inspected = subprocess.run(
            [sys.executable, "-c", inspect_round, str(self.path)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(inspected.returncode, 0, inspected.stderr or inspected.stdout)
        self.assertEqual(
            json.loads(inspected.stdout),
            [
                {"role": "human", "content": "First process question"},
                {"role": "assistant", "content": "First process answer"},
                {"role": "human", "content": "Second process question"},
                {"role": "assistant", "content": "Second process answer"},
            ],
        )

    def test_conversation_projection_discloses_omitted_history(self) -> None:
        """Bounded provider context must make compression visible rather than silent."""
        turns = [
            {"role": "human" if index % 2 == 0 else "assistant", "content": f"turn-{index}"}
            for index in range(10)
        ]
        projection = bounded_context({"turns": turns, "turn_count": 10}, max_turns=4)
        self.assertEqual(projection["turn_count"], 10)
        self.assertEqual(projection["omitted_turn_count"], 6)
        self.assertEqual(len(projection["turns"]), 4)
        self.assertEqual(len(projection["omitted_turns_digest"]), 64)
        self.assertEqual(projection["turns"][0]["content"], "turn-6")

    def test_pages_renders_governed_conversation_projection(self) -> None:
        """The browser view must derive the transcript from replayed application state."""
        registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
        kernel = Kernel(self.kernel.record, Governance(application_registry=registry))
        host = ApplicationHost(kernel, registry, "conversation")
        host.submit(ApplicationIntent("page-human", 0, "human_message", "Visible human turn"))
        host.submit(ApplicationIntent("page-assistant", 1, "assistant_message", "Visible assistant turn"))
        page = render(kernel)
        self.assertIn("Governed conversation", page)
        self.assertIn("Visible human turn", page)
        self.assertIn("Visible assistant turn", page)
        self.assertIn("Send next message", page)
        self.assertIn("actions/workflows/conversation.yml", page)

    def test_dedicated_workflow_exposes_governed_conversation_browser_path(self) -> None:
        """The zero-cost browser proof is a one-message authenticated workflow surface."""
        workflow = (
            Path(__file__).parents[1] / ".github" / "workflows" / "conversation.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("message:", workflow)
        self.assertIn("scripts/conversation_sudofx.py", workflow)
        self.assertIn("--summary-file \"$GITHUB_STEP_SUMMARY\"", workflow)
        self.assertIn("group: sudofx-authority-v4", workflow)
        self.assertIn("preserving operator Stop", workflow)

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

    def test_invocation_lifecycle_can_record_application_specific_provider_boundary(self) -> None:
        """Applications may reuse generic invocation evidence without yielding a sudofx Proposal."""
        context = Context(
            revision=0,
            state={"app:test": {"request": "application-specific"}},
            recent_receipts=(),
        )
        provenance = SubmissionProvenance("model", "application-provider", "unit-test")
        lifecycle = InvocationLifecycle.begin(
            self.kernel.record,
            context,
            provenance=provenance,
            context_scope={"kind": "application", "application_id": "test"},
            invocation_id="application-lifecycle-1",
        )
        lifecycle.proposal_received("application-response-1")
        lifecycle.governed("application-response-1", "application-receipt-1", "accepted")
        lifecycle.complete(
            proposal_id="application-response-1",
            receipt_id="application-receipt-1",
            detail="accepted",
        )

        events = self.kernel.record.invocation_history("application-lifecycle-1")
        self.assertEqual(
            [event["stage"] for event in events],
            [
                "requested",
                "context_delivered",
                "attempt_started",
                "proposal_received",
                "governed",
                "completed",
            ],
        )
        self.assertEqual(
            events[1]["context_receipt"]["scope"],
            {"kind": "application", "application_id": "test"},
        )
        self.assertEqual(events[-1]["outcome"], "success")
        self.assertEqual(self.kernel.record.history(), ())

    def test_runtime_records_provider_failure_without_fabricating_proposal_receipt(self) -> None:
        """Provider failure is durable invocation evidence but never a proposal event."""
        runtime = Runtime(self.kernel, self.kernel.record)
        provider = CommandIntelligence((sys.executable, "-c", "print('not json')"))
        provenance = SubmissionProvenance("model", "test-provider", "unit-test")

        with self.assertRaises(ProviderError):
            runtime.run(provider, provenance=provenance)

        self.assertEqual(self.kernel.record.history(), ())
        lifecycle = self.kernel.record.invocation_history()
        self.assertEqual(
            [event["stage"] for event in lifecycle],
            ["requested", "context_delivered", "attempt_started", "failed"],
        )
        self.assertEqual(lifecycle[-1]["provenance"], provenance.to_dict())
        delivered = lifecycle[1]["context_receipt"]
        self.assertEqual(delivered["policy_version"], "kernel-context-v1")
        self.assertGreater(delivered["payload_bytes"], 0)
        self.assertEqual(delivered["included_categories"], ["state", "recent_receipts"])
        self.assertEqual(delivered["scope"], {"kind": "global"})
        self.assertIsNone(lifecycle[0]["context_receipt"])
        self.assertIsNone(lifecycle[2]["context_receipt"])
        self.assertEqual(lifecycle[-1]["detail"], "ProviderError")
        self.assertNotIn("not json", json.dumps(lifecycle[-1]))
        self.assertEqual(lifecycle[-1]["outcome"], "provider_failure")
        self.assertEqual(self.kernel.record.incomplete_invocations(), ())

    def test_runtime_success_records_proposal_governance_and_completion(self) -> None:
        """Successful provider execution must connect lifecycle evidence to its receipt."""
        runtime = Runtime(self.kernel, self.kernel.record)
        result = runtime.run(
            FakeIntelligence(
                [
                    Proposal(
                        "runtime-success",
                        0,
                        (Operation("set", "runtime", "recorded"),),
                    )
                ]
            ),
            provenance=SubmissionProvenance("model", "fake", "unit-test"),
        )

        self.assertEqual(result.run.receipt.status, "accepted")
        lifecycle = self.kernel.record.invocation_history(result.invocation_id)
        self.assertEqual(
            [event["stage"] for event in lifecycle],
            [
                "requested",
                "context_delivered",
                "attempt_started",
                "proposal_received",
                "governed",
                "completed",
            ],
        )
        self.assertEqual(lifecycle[-1]["proposal_id"], "runtime-success")
        self.assertEqual(lifecycle[-1]["receipt_id"], result.run.receipt.receipt_id)
        self.assertEqual(lifecycle[1]["context_receipt"]["scope"], {"kind": "global"})
        self.assertEqual(lifecycle[-1]["outcome"], "success")
        self.assertEqual(self.kernel.context().state, {"runtime": "recorded"})

    def test_incomplete_invocation_survives_process_reopen_without_guessing_success(self) -> None:
        """A successor must see interrupted work as incomplete rather than completed."""
        common = {
            "invocation_id": "interrupted-1",
            "source_revision": 0,
            "context_digest": "d" * 64,
            "provenance": {"origin": "runtime", "actor": "test"},
        }
        self.kernel.record.append_invocation_event(
            InvocationEvent(stage="requested", **common)
        )
        self.kernel.record.append_invocation_event(
            InvocationEvent(stage="context_delivered", **common)
        )
        self.kernel.record.append_invocation_event(
            InvocationEvent(stage="attempt_started", **common)
        )

        reopened = Record(self.path)
        incomplete = reopened.incomplete_invocations()
        self.assertEqual(len(incomplete), 1)
        self.assertEqual(incomplete[0]["invocation_id"], "interrupted-1")
        self.assertEqual(incomplete[0]["stage"], "attempt_started")
        self.assertIsNone(incomplete[0]["proposal_id"])
        self.assertIsNone(incomplete[0]["receipt_id"])

        runtime = Runtime(Kernel(reopened), reopened)
        self.assertEqual(runtime.recover_incomplete_invocations(), ("interrupted-1",))
        self.assertEqual(reopened.incomplete_invocations(), ())
        terminal = reopened.invocation_history("interrupted-1")[-1]
        self.assertEqual(terminal["stage"], "failed")
        self.assertEqual(terminal["detail"], "interrupted")
        self.assertIsNone(terminal["outcome"])

    def test_runtime_accounting_classifies_quota_and_temporary_failures(self) -> None:
        """Generic accounting must preserve outcomes without embedding vendor quota policy."""
        runtime = Runtime(self.kernel, self.kernel.record)
        provenance = SubmissionProvenance("model", "process-provider", "unit-test")
        for exit_code, expected in ((75, "temporary_failure"), (78, "quota_exhausted")):
            provider = CommandIntelligence(
                (sys.executable, "-c", f"import sys; sys.exit({exit_code})")
            )
            with self.assertRaises(ProviderError):
                runtime.run(provider, provenance=provenance)
            self.assertEqual(
                self.kernel.record.invocation_history()[-1]["outcome"],
                expected,
            )

        accounting = self.kernel.record.invocation_accounting()
        self.assertEqual(accounting["invocations"], 2)
        self.assertEqual(accounting["attempts"], 2)
        self.assertEqual(accounting["failed"], 2)
        self.assertEqual(accounting["completed"], 0)
        self.assertEqual(accounting["temporary_failures"], 1)
        self.assertEqual(accounting["quota_exhausted"], 1)
        self.assertEqual(accounting["provider_failures"], 0)

    def test_invocation_journal_detects_tampering(self) -> None:
        """Changing lifecycle bytes must make operational history unverifiable."""
        runtime = Runtime(self.kernel, self.kernel.record)
        runtime.run(
            FakeIntelligence(
                [Proposal("invocation-chain", 0, (Operation("set", "x", 1),))]
            ),
            provenance=SubmissionProvenance("model", "fake", "unit-test"),
        )
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "UPDATE invocation_events SET detail = ? WHERE sequence = 1",
                ("forged",),
            )
            connection.commit()
        with self.assertRaises(IntegrityError):
            self.kernel.record.invocation_history()

    def test_invocation_lifecycle_rejects_out_of_order_new_events(self) -> None:
        """New lifecycle evidence may not skip the durable boundary sequence."""
        with self.assertRaisesRegex(ValueError, "invalid invocation lifecycle transition"):
            self.kernel.record.append_invocation_event(
                InvocationEvent(
                    invocation_id="out-of-order",
                    stage="attempt_started",
                    source_revision=0,
                    context_digest="d" * 64,
                )
            )

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
        # Operational context uses the hash-bound materialized checkpoint;
        # explicit audit replay verifies the complete historical chain.
        self.assertEqual(self.kernel.context().state["x"], 1)
        with self.assertRaises(IntegrityError):
            self.kernel.record.full_replay()
    def test_submission_provenance_is_durable_and_hash_bound(self) -> None:
        """Trusted caller attribution must survive replay and detect later rewriting."""
        provenance = SubmissionProvenance("human", "operator", "phone")
        receipt = self.kernel.submit(
            Proposal("attributed", 0, (Operation("set", "x", 1),)),
            provenance=provenance,
        )
        self.assertEqual(receipt.status, "accepted")
        event = self.kernel.record.history()[0]
        self.assertEqual(
            event["provenance"],
            {"origin": "human", "actor": "operator", "source": "phone"},
        )

        # Provenance is semantic evidence, not mutable display metadata.
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "UPDATE events SET provenance = ? WHERE sequence = 1",
                (json.dumps({"origin": "model", "actor": "forged"}),),
            )
            connection.commit()
        self.assertEqual(self.kernel.context().state["x"], 1)
        with self.assertRaises(IntegrityError):
            self.kernel.record.full_replay()

    def test_v1_record_without_provenance_column_migrates_without_rehashing_history(self) -> None:
        """Schema v2 adds attribution support without invalidating legacy event identity."""
        legacy_path = Path(self.tempdir.name) / "legacy-v1.sqlite"
        proposal = Proposal("legacy", 0, (Operation("set", "carried", True),)).to_dict()
        material = {
            "receipt_id": "legacy-receipt",
            "proposal_id": "legacy",
            "status": "accepted",
            "revision_before": 0,
            "revision_after": 1,
            "payload": proposal,
            "reasons": [],
        }
        event_hash = Record.hash_event("0" * 64, material)
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            connection.execute("PRAGMA user_version = 1")
            connection.execute(
                "CREATE TABLE events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                "receipt_id TEXT NOT NULL UNIQUE, proposal_id TEXT NOT NULL UNIQUE, "
                "status TEXT NOT NULL, revision_before INTEGER NOT NULL, "
                "revision_after INTEGER NOT NULL, payload TEXT NOT NULL, reasons TEXT NOT NULL, "
                "previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "INSERT INTO events (receipt_id, proposal_id, status, revision_before, "
                "revision_after, payload, reasons, previous_hash, event_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "legacy-receipt", "legacy", "accepted", 0, 1,
                    json.dumps(proposal), json.dumps([]), "0" * 64, event_hash,
                ),
            )
            connection.commit()

        migrated = Record(legacy_path)
        self.assertTrue(migrated.schema_changed)
        revision, state = migrated.replay()
        self.assertEqual(revision, 1)
        self.assertEqual(state, {"carried": True})
        self.assertIsNone(migrated.history()[0]["provenance"])
        with closing(sqlite3.connect(legacy_path)) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(events)")}
            self.assertIn("provenance", columns)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)

    def test_v3_invocation_journal_migrates_without_inventing_delivery_evidence(self) -> None:
        """
        Schema v4 may enrich future context delivery rows but must preserve v3 truth.

        A pre-v4 invocation has a durable digest and revision but no structured
        delivery receipt. Migration must keep that absence explicit as NULL
        rather than fabricating metadata a fresh process cannot actually know.
        """
        legacy_path = Path(self.tempdir.name) / "legacy-v3.sqlite"
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            connection.execute("PRAGMA user_version = 3")
            connection.execute(
                "CREATE TABLE events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                "receipt_id TEXT NOT NULL UNIQUE, proposal_id TEXT NOT NULL UNIQUE, "
                "status TEXT NOT NULL, revision_before INTEGER NOT NULL, "
                "revision_after INTEGER NOT NULL, payload TEXT NOT NULL, reasons TEXT NOT NULL, "
                "provenance TEXT, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "CREATE TABLE invocation_events ("
                "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                "invocation_id TEXT NOT NULL, stage TEXT NOT NULL, "
                "source_revision INTEGER NOT NULL, context_digest TEXT NOT NULL, "
                "provenance TEXT, proposal_id TEXT, receipt_id TEXT, "
                "detail TEXT NOT NULL DEFAULT '', "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "INSERT INTO invocation_events "
                "(invocation_id, stage, source_revision, context_digest, provenance) "
                "VALUES (?, ?, ?, ?, ?)",
                ("legacy-invocation", "context_delivered", 0, "d" * 64, json.dumps({
                    "origin": "model", "actor": "legacy-provider"
                })),
            )
            connection.commit()

        migrated = Record(legacy_path)
        self.assertTrue(migrated.schema_changed)
        lifecycle = migrated.invocation_history("legacy-invocation")
        self.assertEqual(len(lifecycle), 1)
        self.assertEqual(lifecycle[0]["stage"], "context_delivered")
        self.assertIsNone(lifecycle[0]["context_receipt"])
        self.assertEqual(lifecycle[0]["event_id"], "legacy-invocation-1")
        self.assertEqual(lifecycle[0]["previous_hash"], "0" * 64)
        self.assertEqual(len(lifecycle[0]["event_hash"]), 64)
        with closing(sqlite3.connect(legacy_path)) as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(invocation_events)")
            }
            self.assertIn("context_receipt", columns)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)

    def test_static_report_exposes_state_and_receipt_provenance(self) -> None:
        """Pages is a public observer; GitHub Actions is the operator surface."""
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
                "semantic_review": {"evidence": {"objective": "Preserve the work across model replacement"}},
            },
        )
        self.assertIn("Can a fresh AI pick up where the last one left off?", page)
        self.assertIn("Gemini understood: continue safely.", page)
        self.assertIn('href="https://github.com/sudofx/sudofx/actions"', page)
        self.assertIn('class="actions-light"', page)
        self.assertIn('class="technical-view"', page)
        self.assertIn("DERIVED VIEW", page)
        self.assertNotIn('data-owner-technical', page)
        self.assertIn("actions/workflows/'+runner", page)
        self.assertIn("actions/workflows/'+workflow+'/runs?branch=sudofx-runtime", page)
        self.assertIn("setActionsLight(actionsLightForVisualState(visualState))", page)
        self.assertNotIn("SUDOFX_CONTROL_URL", page)
        self.assertNotIn("sudofx-owner-session", page)
        self.assertNotIn("/auth/login", page)
        self.assertNotIn("/api/session", page)
        self.assertNotIn("ownerRequest", page)
        self.assertNotIn("GITHUB_CLIENT_SECRET", page)
        self.assertIn('data-published-run-id="123"', page)
        self.assertIn("Activity history", page)
        self.assertIn("objective", page)
        self.assertIn("continue", page)
        self.assertIn("proposal p1", page)
        self.assertIn("wake-theme", page)
        self.assertIn('href="https://sudofx.github.io/wake/" target="_blank"', page)

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
        self.assertIn('inputs.operator_start', workflow)
        self.assertIn("actions/workflows/sudofx-runner.yml", workflow)
        self.assertIn('latch_state', workflow)
        self.assertIn("runtime_ref:", workflow)
        self.assertIn("--ref sudofx-runtime", workflow)
        self.assertIn('-f "runtime_ref=$RUNTIME_REF"', workflow)
        self.assertNotIn("name: Verify the kernel", workflow)
        self.assertFalse((Path(__file__).parents[1] / ".github/workflows/promote-runtime.yml").exists())
        self.assertNotIn("cron:", workflow)
        self.assertNotIn("\n  push:", workflow)
        start = (Path(__file__).parents[1] / ".github/workflows/operator-start.yml").read_text(encoding="utf-8")
        stop = (Path(__file__).parents[1] / ".github/workflows/operator-stop.yml").read_text(encoding="utf-8")
        self.assertIn("Verify candidate", start)
        self.assertIn("git/refs/heads/sudofx-runtime", start)
        self.assertIn("-F force=true", start)
        self.assertIn("actions/workflows/sudofx-runner.yml/enable", start)
        self.assertIn('runtime_ref', start)
        self.assertIn('-f "operator_start=true"', start)
        # Start/Stop have one control authority: the runner workflow's enabled state.
        # prove-model remains dispatchable infrastructure, never a second stop latch.
        self.assertIn("actions/workflows/prove-model.yml/enable", start)
        self.assertIn("actions/workflows/sudofx-runner.yml/enable", start)
        self.assertIn("group: sudofx-operator-control", start)
        self.assertIn("group: sudofx-operator-control", stop)
        self.assertIn("actions/workflows/sudofx-runner.yml/disable", stop)
        self.assertNotIn("actions/workflows/prove-model.yml/disable", stop)
        self.assertIn("Cancel current-runtime continuity cycles", stop)
        self.assertIn("Wait until current runtime is stopped", stop)
        self.assertIn("runtime_ref", stop)
        self.assertIn("head_sha", stop)
        self.assertLess(stop.index("sudofx-runner.yml/disable"), stop.index("actions/runs/$run_id/cancel"))

    def test_semantic_review_ui_defaults_to_pass_and_confirms_submission(self) -> None:
        """Semantic review remains visible evidence without a Pages authentication path."""
        page = render(self.kernel)
        self.assertIn("Semantic review", page)
        self.assertIn("data-semantic-review-criteria", page)
        self.assertNotIn("data-semantic-review-submit", page)
        self.assertNotIn("data-semantic-review-form", page)
        self.assertNotIn("SUDOFX_CONTROL_URL", page)
        self.assertNotIn("/api/operate", page)

    def test_semantic_review_resolves_historical_authoritative_target(self) -> None:
        """Human review must survive runner advancement without accepting invented targets."""
        repository_root = Path(__file__).resolve().parents[1]
        source = (repository_root / "scripts" / "github_sudofx.py").read_text(encoding="utf-8")
        workflow = (repository_root / ".github" / "workflows" / "sudofx.yml").read_text(encoding="utf-8")
        self.assertIn("def frozen_overnight_proof(", source)
        self.assertIn('git("rev-list", f"origin/{STATE_BRANCH}"', source)
        self.assertIn('raise ValueError("semantic review names no overnight observation in durable state history")', source)
        self.assertIn("semantic review for this exact run, context, and reviewer is already recorded", source)
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
        # Projection adapters are allowed to trigger a rerender. The authority
        # boundary is permission + publish-only behavior, not ignorance of the
        # code that reconstructs the view.
        self.assertIn("'scripts/github_sudofx.py'", pages_triggers)
        self.assertNotIn("contents: write", pages)
        self.assertIn("pages: write", pages)
        self.assertNotIn("GEMINI_API_KEY", pages)

        self.assertNotIn("\n  push:", operator)
        self.assertNotIn("gh workflow run pages.yml", operator)
        self.assertIn("group: sudofx-authority-v4", operator)
        self.assertIn("group: sudofx-authority-v4", continuity)
        self.assertNotIn("group: sudofx-pages", operator)
        self.assertNotIn("group: sudofx-pages", continuity)
        self.assertIn("Resume enabled continuity after operator work", operator)
        self.assertIn("actions: write", operator)
        self.assertNotIn("operator-stop", operator)
        self.assertIn("sudofx-runner.yml", operator)
        self.assertIn('.head_branch == "sudofx-runtime"', operator)
        self.assertIn("--ref sudofx-runtime", operator)

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

    def test_github_state_transport_contains_no_experiment_semantics(self) -> None:
        """Replaceable Git transport must move verified database bytes, not domain meaning."""
        source = (
            Path(__file__).parents[1] / "scripts" / "github_state.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def restore()", source)
        self.assertIn("def checkpoint()", source)
        self.assertIn("Record(DATA).backup_to(snapshot)", source)
        self.assertNotIn("experiments.", source)
        self.assertNotIn("Gemini", source)
        self.assertNotIn("handoff", source.lower())
        self.assertNotIn("semantic_review", source)

    def test_recovery_workflow_retains_verified_backup_outside_pages(self) -> None:
        """Recovery backup must be finite, authenticated by GitHub, and excluded from public output."""
        workflow = (Path(__file__).parents[1] / ".github/workflows/sudofx.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("operator-stop", workflow)
        self.assertNotIn("--operator-transition", workflow)
        self.assertIn("inputs.action == 'backup'", workflow)
        self.assertIn("--backup recovery/sudofx.sqlite", workflow)
        # Keep the backup action on the Node.js 24-compatible generation. An
        # obsolete runner dependency would make recovery decay even while the
        # storage contract itself remained correct.
        self.assertIn("actions/upload-artifact@v7", workflow)
        self.assertIn("retention-days: 30", workflow)
        self.assertNotIn("path: recovery\n", workflow)

    def test_handoff_packet_is_bounded_and_portable(self) -> None:
        """The portable packet stays bounded and independent of web authentication."""
        self.kernel.submit(
            Proposal(
                "handoff-create",
                0,
                (
                    Operation(
                        "create_work",
                        "handoff-v1",
                        {
                            "objective": "Carry useful governed context across a fresh intelligence",
                            "constraints": ["Unknown means unknown"],
                        },
                    ),
                ),
            )
        )
        packet = build_handoff_packet(self.kernel, "handoff-v1")
        self.assertEqual(packet["handoff_version"], 1)
        self.assertIn("packet_digest", packet)
        self.assertEqual(len(packet["packet_digest"]), 64)

        with tempfile.TemporaryDirectory() as temporary:
            json_path, prompt_path = export_handoff_packet(self.kernel, temporary, "handoff-v1")
            self.assertTrue(json_path.exists())
            self.assertTrue(prompt_path.exists())
            self.assertIn("SUDOFX_HANDOFF v1", prompt_path.read_text())

        page = render(self.kernel)
        self.assertIn("Manual AI continuity test", page)
        self.assertIn('data-manual-vendor="ChatGPT"', page)
        self.assertIn('data-manual-vendor="Claude"', page)
        self.assertIn('data-manual-vendor="Gemini"', page)
        self.assertIn('data-manual-vendor="DeepSeek"', page)
        self.assertIn("data-manual-dialog", page)
        self.assertIn("data-manual-open", page)
        self.assertIn("navigator.clipboard.writeText", page)
        self.assertIn('data-manual-url="com.openai.chat://"', page)
        self.assertIn('data-manual-url="claude://"', page)
        self.assertIn('data-manual-url="googlegemini://"', page)
        self.assertIn('data-manual-url="deepseek://"', page)
        self.assertIn("document.execCommand('copy')", page)
        self.assertIn("data-manual-launch", page)
        self.assertIn("<textarea data-manual-prompt>", page)
        self.assertNotIn("<textarea data-manual-prompt readonly>", page)
        self.assertIn("Packet ready. Copy it, then tap Open ", page)
        self.assertIn("if(manualLaunch){manualLaunch.hidden=false;manualLaunch.textContent='Open '+button.dataset.manualVendor;}", page)
        self.assertIn("if(!copied)copied=copyManualFromField();", page)
        self.assertIn("if(!value||!navigator.clipboard?.writeText)return false", page)
        self.assertIn("Packet generation failed: unresolved transport metadata.", page)
        self.assertIn("Copy blocked: regenerate the packet; transport metadata is unresolved.", page)
        self.assertNotIn("return copyManualFromField();", page)
        self.assertIn("launchManualProvider(selectedManualProvider);", page)
        self.assertNotIn("setManualStatus('Prompt copied. Opening '+button.dataset.manualVendor", page)
        self.assertNotIn("await copyText(manualPrompt.value)", page)
        self.assertNotIn("await copyManual(", page)
        self.assertIn("event.preventDefault();", page)
        self.assertNotIn("providerLaunchUrl", page)
        self.assertNotIn("navigator.share", page)
        self.assertIn("manualDialog.showModal()", page)
        self.assertIn('id="manual-handoff-dialog"', page)
        self.assertIn("getElementById('manual-handoff-dialog').showModal()", page)
        self.assertIn("data-manual-analyze", page)
        self.assertIn("Local grounding score", page)
        self.assertIn("/issues/new", page)
        self.assertIn("/actions/workflows/sudofx.yml", page)
        self.assertIn("manualDimensions=['objective_fidelity','authority_fidelity','history_fidelity','constraint_fidelity','frontier_fidelity','epistemic_discipline','transfer_usability']", page)
        self.assertNotIn("data-handoff-dialog", page)
        self.assertNotIn("data-handoff-submit", page)
        self.assertNotIn("/auth/login", page)
        self.assertNotIn("sudofx-owner-session", page)

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


