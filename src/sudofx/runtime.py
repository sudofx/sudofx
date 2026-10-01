"""Durable execution boundary around disposable intelligence providers.

Kernel owns governed proposal submission. Runtime owns the lifecycle around an
external invocation: what bounded context was delivered, whether a proposal
arrived, whether submission completed, and whether an earlier process vanished
mid-flight.

These lifecycle receipts are durable evidence, not replayable application state.
They therefore do not advance the governed state revision and never substitute
for Proposal/Receipt history.
"""

from __future__ import annotations

import hashlib
import uuid

from .kernel import Kernel, RunResult
from .models import Context, SubmissionProvenance
from .providers import Intelligence
from .storage import canonical_json


def _context_payload(context: Context) -> dict[str, object]:
    """Return the exact provider-neutral Context representation used for hashing."""
    return {
        "revision": context.revision,
        "state": context.state,
        "recent_receipts": context.recent_receipts,
    }


class Runtime:
    """Coordinate disposable provider calls while preserving durable lifecycle evidence."""

    def __init__(self, kernel: Kernel) -> None:
        self.kernel = kernel

    def recover_incomplete_invocations(self) -> tuple[dict[str, object], ...]:
        """Mark abandoned prior lifecycles explicitly without guessing external success."""
        recovered: list[dict[str, object]] = []
        for pending in self.kernel.record.incomplete_invocations():
            recovered.append(
                self.kernel.record.append_invocation_event(
                    str(pending["invocation_id"]),
                    "interrupted",
                    {
                        "observed_prior_phase": pending["phase"],
                        "recovery": "fresh runtime observed unfinished invocation",
                        "external_success_assumed": False,
                    },
                )
            )
        return tuple(recovered)

    def run(
        self,
        intelligence: Intelligence,
        *,
        provenance: SubmissionProvenance,
        work_id: str | None = None,
        context_policy: str = "kernel-context-v1",
    ) -> RunResult:
        """Invoke one provider and bind its full execution lifecycle to the database."""
        if not context_policy.strip():
            raise ValueError("context_policy must not be empty")

        context = self.kernel.context(work_id=work_id)
        payload = _context_payload(context)
        serialized = canonical_json(payload).encode("utf-8")
        history = self.kernel.record.history()
        source_event_head = history[-1]["event_hash"] if history else "0" * 64
        invocation_id = str(uuid.uuid4())

        self.kernel.record.append_invocation_event(
            invocation_id,
            "started",
            {
                "source_revision": context.revision,
                "source_event_head": source_event_head,
                "context_policy": context_policy,
                "context_digest": hashlib.sha256(serialized).hexdigest(),
                "context_bytes": len(serialized),
                "state_keys": sorted(context.state),
                "receipt_count": len(context.recent_receipts),
                "scope": {"work_id": work_id} if work_id is not None else {"work_id": None},
                "provenance": provenance.to_dict(),
            },
        )

        try:
            proposal = intelligence.propose(context)
        except Exception as error:
            self.kernel.record.append_invocation_event(
                invocation_id,
                "failed",
                {
                    "stage": "provider",
                    "error_type": type(error).__name__,
                    # Durable public-safe evidence deliberately excludes raw
                    # exception text, which can contain provider/request detail.
                    "external_success_assumed": False,
                },
            )
            raise

        self.kernel.record.append_invocation_event(
            invocation_id,
            "proposal_received",
            {"proposal_id": proposal.proposal_id},
        )

        try:
            receipt = self.kernel.submit(proposal, provenance=provenance)
        except BaseException as error:
            self.kernel.record.append_invocation_event(
                invocation_id,
                "failed",
                {
                    "stage": "submission",
                    "proposal_id": proposal.proposal_id,
                    "error_type": type(error).__name__,
                },
            )
            raise

        self.kernel.record.append_invocation_event(
            invocation_id,
            "completed",
            {
                "proposal_id": proposal.proposal_id,
                "receipt_id": receipt.receipt_id,
                "receipt_status": receipt.status,
                "receipt_event_hash": receipt.event_hash,
            },
        )
        return RunResult(context=context, proposal=proposal, receipt=receipt)
