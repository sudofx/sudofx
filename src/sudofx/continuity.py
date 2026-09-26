"""
DETERMINISTIC CONTINUITY PROOF
==============================

This module proves the narrow v0.1 claim at the real process and record
boundaries without mutating production state.

The proof deliberately uses a temporary SQLite record. It creates one governed
work item plus unrelated durable state, destroys the setup Kernel, reopens the
record, exports only the selected work context to a fresh external Python
process, accepts that process's proposal through normal governance, reopens the
record again, and verifies replayed progress.

The external process receives JSON only. It receives no Record, database path,
Kernel, governance object, provider memory, or mutation capability. An assertion
inside that process fails if unrelated durable state leaks across the bounded
context boundary.

This is an infrastructure proof, not an intelligence-quality evaluation. The
external process is deterministic on purpose so model behavior cannot disguise
a continuity failure. Later experiments can replace that process with a real
model while preserving the same boundary and evidence shape.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

from .kernel import Kernel
from .models import Operation, Proposal
from .providers import CommandIntelligence
from .record import Record
from .storage import GENESIS_HASH, canonical_json

WORK_ID = "continuity-proof"
RESULT = "Fresh process reconstructed bounded work and continued it."
OBLIGATION = "Replace deterministic proposer with a real model experiment."


def run_continuity_proof() -> dict[str, Any]:
    """
    Execute one disposable-process continuity proof and return derived evidence.

    The returned mapping is safe to publish because it contains only synthetic
    fixture data and receipt identifiers from the temporary database. No
    production database bytes, private state, or provider credentials are read.

    Any violated invariant raises rather than returning a plausible partial
    success. GitHub Actions therefore stops before Pages publication when the
    proof cannot establish its claim.
    """
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "continuity.sqlite"

        # Seed two different kinds of durable state. Only the selected work item
        # may cross the provider boundary; the decoy proves the filter is real.
        seed = Kernel(Record(path))
        created = seed.submit(
            Proposal(
                "proof-create",
                0,
                (
                    Operation(
                        "create_work",
                        WORK_ID,
                        {
                            "objective": "Prove work survives intelligence replacement.",
                            "constraints": [
                                "Provider sees bounded durable context only.",
                                "Production state must not be mutated.",
                            ],
                        },
                    ),
                ),
                "Synthetic continuity fixture",
            )
        )
        if created.status != "accepted":
            raise AssertionError("continuity fixture work creation was rejected")
        decoy = seed.submit(
            Proposal(
                "proof-decoy",
                1,
                (Operation("set", "decoy:private", "must not cross provider boundary"),),
                "Synthetic unrelated state",
            )
        )
        if decoy.status != "accepted":
            raise AssertionError("continuity fixture decoy creation was rejected")

        # Destroy the active setup objects before continuation. The replacement
        # must derive everything from durable replay rather than surviving Python
        # references or provider-local memory.
        del seed

        provider = r"""
import json
import sys

context = json.load(sys.stdin)
assert set(context["state"]) == {"work:continuity-proof"}
assert all(
    all(operation.get("key") == "continuity-proof" for operation in receipt["proposal"]["operations"])
    for receipt in context["recent_receipts"]
)
work = context["state"]["work:continuity-proof"]
json.dump(
    {
        "proposal_id": f"proof-external-{context['revision']}",
        "based_on_revision": context["revision"],
        "operations": [
            {
                "action": "advance_work",
                "key": work["id"],
                "value": {
                    "result": "Fresh process reconstructed bounded work and continued it.",
                    "open_obligations": [
                        "Replace deterministic proposer with a real model experiment."
                    ],
                },
            }
        ],
        "rationale": "Derived only from exported bounded durable context",
    },
    sys.stdout,
)
"""

        replacement = Kernel(Record(path))
        before = replacement.context(work_id=WORK_ID, receipt_limit=100)
        result = replacement.run(
            CommandIntelligence((sys.executable, "-c", provider)),
            work_id=WORK_ID,
        )
        if result.receipt.status != "accepted":
            raise AssertionError(f"fresh-process proposal was {result.receipt.status}")

        # Reopen once more after the external process has disappeared. Accepted
        # progress must survive in replayed state without either Kernel instance.
        final_kernel = Kernel(Record(path))
        final_context = final_kernel.context(receipt_limit=100)
        work = final_context.state[f"work:{WORK_ID}"]
        if work["accepted_results"] != [RESULT]:
            raise AssertionError("replayed work does not contain the fresh-process result")
        if work["open_obligations"] != [OBLIGATION]:
            raise AssertionError("replayed work does not contain the expected frontier")
        if final_context.state.get("decoy:private") != "must not cross provider boundary":
            raise AssertionError("unrelated durable state was lost")

        checks = {
            "record_reopened_before_provider": True,
            "provider_is_fresh_external_process": True,
            "provider_context_is_work_scoped": set(before.state) == {f"work:{WORK_ID}"},
            "unrelated_state_remained_outside_provider_context": "decoy:private" not in before.state,
            "proposal_crossed_normal_governance": result.receipt.status == "accepted",
            "record_reopened_after_provider": True,
            "accepted_result_survived_replay": work["accepted_results"] == [RESULT],
            "production_state_mutated": False,
        }
        if not all(value for key, value in checks.items() if key != "production_state_mutated"):
            raise AssertionError(f"continuity proof failed checks: {checks}")
        if checks["production_state_mutated"]:
            raise AssertionError("continuity proof must never mutate production state")

        return {
            "passed": True,
            "kind": "deterministic disposable-process continuity",
            "scope": "synthetic temporary record",
            "proves": (
                "bounded governed work can be reconstructed and continued after "
                "the active kernel/provider are replaced"
            ),
            "does_not_prove": (
                "that a real model reconstructs human context well; that is the "
                "next experiment"
            ),
            "revision_before_provider": before.revision,
            "revision_after_provider": result.receipt.revision_after,
            "visible_state_keys": sorted(before.state),
            "receipt": {
                "proposal_id": result.receipt.proposal_id,
                "status": result.receipt.status,
                "event_hash": result.receipt.event_hash,
            },
            "accepted_result": RESULT,
            "open_obligations": [OBLIGATION],
            "checks": checks,
        }


def _context_digest(context: object) -> str:
    """
    Fingerprint the exact JSON context exported to a disposable provider.

    The digest is evidence of input identity, not secrecy. It lets a later
    reviewer tie a probe result to the bounded packet without publishing that
    packet's potentially sensitive contents.
    """
    payload = {
        "revision": context.revision,
        "state": context.state,
        "recent_receipts": context.recent_receipts,
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def _sqlite_snapshot(source: str | Path, destination: Path) -> None:
    """
    Copy one SQLite record through SQLite's backup API.

    A filesystem copy can miss WAL-resident pages. The backup API produces a
    transactionally coherent temporary database while leaving source authority
    untouched. This helper is intentionally experiment infrastructure; Kernel
    remains storage-backend independent.
    """
    with sqlite3.connect(str(source)) as source_connection:
        with sqlite3.connect(str(destination)) as destination_connection:
            source_connection.backup(destination_connection)


def run_work_continuity_probe(record_path: str | Path, work_id: str) -> dict[str, Any]:
    """
    Probe one real work item using a temporary snapshot of the authoritative record.

    The source database is opened only for verified reads and SQLite backup.
    Proposal submission happens exclusively against the temporary copy. The
    published result contains counts, hashes, revisions, and booleans rather
    than the work objective/results themselves.

    Completed or missing work is rejected as an invalid probe target because
    this experiment specifically tests whether an open work item can be
    continued by a fresh process.
    """
    source = Kernel(Record(record_path))
    source_history_before = source.record.history()
    source_head_before = (
        source_history_before[-1]["event_hash"] if source_history_before else GENESIS_HASH
    )
    bounded = source.context(work_id=work_id, receipt_limit=100)
    work_key = f"work:{work_id}"
    work = bounded.state.get(work_key)
    if not isinstance(work, dict):
        raise ValueError(f"work item does not exist: {work_id}")
    if work.get("status") != "open":
        raise ValueError(f"work item is not open: {work_id}")

    digest = _context_digest(bounded)
    starting_work_revision = int(work.get("work_revision", 0))
    prior_results = work.get("accepted_results", [])
    obligations = work.get("open_obligations", [])
    if not isinstance(prior_results, list) or not isinstance(obligations, list):
        raise AssertionError("work projection has invalid continuity fields")

    with tempfile.TemporaryDirectory() as temporary:
        snapshot_path = Path(temporary) / "probe.sqlite"
        _sqlite_snapshot(record_path, snapshot_path)

        provider = r"""
import json
import sys

context = json.load(sys.stdin)
assert len(context["state"]) == 1
key, work = next(iter(context["state"].items()))
assert key.startswith("work:")
assert work["status"] == "open"
result = (
    f"Continuity probe reconstructed work revision {work['work_revision']} "
    f"with {len(work.get('accepted_results', []))} prior accepted results."
)
json.dump(
    {
        "proposal_id": f"real-probe-{context['revision']}-{work['work_revision']}",
        "based_on_revision": context["revision"],
        "operations": [
            {
                "action": "advance_work",
                "key": work["id"],
                "value": {
                    "result": result,
                    "open_obligations": work.get("open_obligations", []),
                },
            }
        ],
        "rationale": "Reconstructed solely from bounded production-record context",
    },
    sys.stdout,
)
"""
        probe_kernel = Kernel(Record(snapshot_path))
        result = probe_kernel.run(
            CommandIntelligence((sys.executable, "-c", provider)),
            work_id=work_id,
        )
        if result.receipt.status != "accepted":
            raise AssertionError(f"real-record probe proposal was {result.receipt.status}")

        reopened = Kernel(Record(snapshot_path))
        after = reopened.context(work_id=work_id, receipt_limit=100)
        after_work = after.state[work_key]
        if int(after_work["work_revision"]) != starting_work_revision + 1:
            raise AssertionError("temporary replay did not advance work revision")
        if len(after_work["accepted_results"]) != len(prior_results) + 1:
            raise AssertionError("temporary replay did not append exactly one result")
        if after_work["open_obligations"] != obligations:
            raise AssertionError("probe changed the real work frontier semantics")

    # Re-read source authority after the temporary probe. Semantic head equality
    # is stronger evidence than assuming a temp path was used correctly.
    source_after = Kernel(Record(record_path))
    source_history_after = source_after.record.history()
    source_head_after = (
        source_history_after[-1]["event_hash"] if source_history_after else GENESIS_HASH
    )
    source_work_after = source_after.context(work_id=work_id).state[work_key]
    source_unchanged = (
        source_head_before == source_head_after
        and int(source_work_after["work_revision"]) == starting_work_revision
        and len(source_work_after["accepted_results"]) == len(prior_results)
    )
    if not source_unchanged:
        raise AssertionError("production record changed during continuity probe")

    checks = {
        "source_record_verified": True,
        "provider_is_fresh_external_process": True,
        "provider_context_contains_only_selected_work": set(bounded.state) == {work_key},
        "proposal_crossed_normal_governance_on_snapshot": result.receipt.status == "accepted",
        "snapshot_replay_advanced_exactly_once": True,
        "production_record_head_unchanged": source_head_before == source_head_after,
        "production_state_mutated": False,
    }
    return {
        "passed": True,
        "kind": "production-record disposable-process continuity probe",
        "scope": "temporary snapshot of authoritative record",
        "work_id": work_id,
        "proves": (
            "a fresh external process can reconstruct and governably continue "
            "this real work item from bounded durable context"
        ),
        "does_not_prove": (
            "semantic quality of a real language model; the proposer remains "
            "deterministic in this probe"
        ),
        "context_digest": digest,
        "source_event_head": source_head_before,
        "revision_before_provider": bounded.revision,
        "revision_after_provider_on_snapshot": result.receipt.revision_after,
        "starting_work_revision": starting_work_revision,
        "prior_accepted_result_count": len(prior_results),
        "open_obligation_count": len(obligations),
        "receipt": {
            "proposal_id": result.receipt.proposal_id,
            "status": result.receipt.status,
            "event_hash": result.receipt.event_hash,
        },
        "checks": checks,
    }


def run_model_continuity_probe(
    record_path: str | Path,
    work_id: str,
    provider_command: tuple[str, ...],
    *,
    provider: str,
    model: str,
) -> dict[str, Any]:
    """
    Produce one real-model continuation candidate against a temporary record snapshot.

    Technical success means the fresh provider consumed bounded context, emitted
    a valid proposal, ordinary governance accepted it on the snapshot, replay
    preserved it, and source authority stayed unchanged. It does NOT mean the
    semantic continuation is good; that remains an explicit human evaluation.

    The returned artifact includes the model's proposed reconstruction/result so
    the operator can judge whether continuity of meaning actually survived.
    """
    source = Kernel(Record(record_path))
    source_history_before = source.record.history()
    source_head_before = (
        source_history_before[-1]["event_hash"] if source_history_before else GENESIS_HASH
    )
    bounded = source.context(work_id=work_id, receipt_limit=100)
    work_key = f"work:{work_id}"
    work = bounded.state.get(work_key)
    if not isinstance(work, dict):
        raise ValueError(f"work item does not exist: {work_id}")
    if work.get("status") != "open":
        raise ValueError(f"work item is not open: {work_id}")

    digest = _context_digest(bounded)
    starting_work_revision = int(work.get("work_revision", 0))
    prior_results = work.get("accepted_results", [])
    if not isinstance(prior_results, list):
        raise AssertionError("work projection has invalid accepted_results")

    with tempfile.TemporaryDirectory() as temporary:
        snapshot_path = Path(temporary) / "model-probe.sqlite"
        _sqlite_snapshot(record_path, snapshot_path)
        probe_kernel = Kernel(Record(snapshot_path))
        result = probe_kernel.run(
            CommandIntelligence(provider_command, timeout_seconds=90),
            work_id=work_id,
        )
        if result.receipt.status != "accepted":
            raise AssertionError(f"real-model probe proposal was {result.receipt.status}")

        reopened = Kernel(Record(snapshot_path))
        after = reopened.context(work_id=work_id, receipt_limit=100)
        after_work = after.state[work_key]
        accepted_results = after_work.get("accepted_results", [])
        obligations = after_work.get("open_obligations", [])
        if int(after_work["work_revision"]) != starting_work_revision + 1:
            raise AssertionError("model snapshot replay did not advance work revision")
        if not isinstance(accepted_results, list) or len(accepted_results) != len(prior_results) + 1:
            raise AssertionError("model snapshot replay did not append exactly one result")
        if not isinstance(obligations, list):
            raise AssertionError("model snapshot replay produced invalid obligations")
        candidate_result = accepted_results[-1]

    # Source authority must remain byte-semantically untouched by the experiment.
    source_after = Kernel(Record(record_path))
    source_history_after = source_after.record.history()
    source_head_after = (
        source_history_after[-1]["event_hash"] if source_history_after else GENESIS_HASH
    )
    source_work_after = source_after.context(work_id=work_id).state[work_key]
    source_unchanged = (
        source_head_before == source_head_after
        and int(source_work_after["work_revision"]) == starting_work_revision
        and len(source_work_after.get("accepted_results", [])) == len(prior_results)
    )
    if not source_unchanged:
        raise AssertionError("production record changed during real-model continuity probe")

    review_contract = {
        "version": 1,
        "status": "pending",
        "decision_options": ["pass", "fail", "uncertain"],
        "rule": (
            "No aggregate score is computed. The human reviewer decides each "
            "criterion from the supplied durable evidence, then records an "
            "overall semantic verdict."
        ),
        "criteria": [
            {
                "id": "objective_fidelity",
                "question": "Does the reconstruction preserve the stated objective?",
                "status": "pending",
            },
            {
                "id": "history_fidelity",
                "question": "Does it respect what has already been accepted as progress?",
                "status": "pending",
            },
            {
                "id": "frontier_fidelity",
                "question": "Does the proposed next step follow the current open frontier?",
                "status": "pending",
            },
            {
                "id": "constraint_fidelity",
                "question": "Does it preserve the work item's explicit constraints?",
                "status": "pending",
            },
            {
                "id": "unsupported_claims",
                "question": "Does it avoid claiming knowledge or work absent from the bounded record?",
                "status": "pending",
            },
            {
                "id": "actionability",
                "question": "Is the proposed next step concrete enough to continue the work?",
                "status": "pending",
            },
        ],
        "evidence": {
            "objective": work.get("objective"),
            "constraints": work.get("constraints", []),
            "accepted_results": prior_results,
            "open_obligations": work.get("open_obligations", []),
            "candidate_result": candidate_result,
            "candidate_open_obligations": obligations,
            "context_digest": digest,
        },
    }

    return {
        "passed": True,
        "assessment_status": "semantic_review_pending",
        "semantic_review": review_contract,
        "kind": "real-model disposable continuity candidate",
        "scope": "temporary snapshot of authoritative record",
        "work_id": work_id,
        "provider": provider,
        "model": model,
        "proves": (
            "the named real model received bounded durable context and produced "
            "a governance-accepted continuation candidate on an isolated snapshot"
        ),
        "does_not_prove": (
            "that the candidate preserves meaning well enough; semantic continuity "
            "requires explicit human review"
        ),
        "context_digest": digest,
        "source_event_head": source_head_before,
        "revision_before_provider": bounded.revision,
        "revision_after_provider_on_snapshot": result.receipt.revision_after,
        "starting_work_revision": starting_work_revision,
        "prior_accepted_result_count": len(prior_results),
        "candidate_result": candidate_result,
        "candidate_open_obligations": obligations,
        "receipt": {
            "proposal_id": result.receipt.proposal_id,
            "status": result.receipt.status,
            "event_hash": result.receipt.event_hash,
        },
        "checks": {
            "source_record_verified": True,
            "provider_is_fresh_external_process": True,
            "provider_context_contains_only_selected_work": set(bounded.state) == {work_key},
            "proposal_crossed_normal_governance_on_snapshot": result.receipt.status == "accepted",
            "snapshot_replay_advanced_exactly_once": True,
            "production_record_head_unchanged": source_head_before == source_head_after,
            "production_state_mutated": False,
        },
    }
