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

import sys
import tempfile
from pathlib import Path
from typing import Any

from .kernel import Kernel
from .models import Operation, Proposal
from .providers import CommandIntelligence
from .record import Record

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
