"""
SUDOFX RUNTIME
=============

Runtime coordinates disposable intelligence execution around the kernel without
moving authority into provider code.

The kernel still owns bounded context plus governed proposal submission.
Runtime owns provider-attempt lifecycle evidence: it records what context was
delivered, whether a provider attempt began, whether a complete proposal was
received, and whether governance produced a durable receipt.

Provider failure before proposal creation never fabricates a proposal receipt.
It does, however, leave durable invocation evidence in the same authoritative
database so a fresh process can reconstruct that an attempt occurred.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from .kernel import Kernel, RunResult
from .models import Context, SubmissionProvenance
from .providers import Intelligence
from .storage import GENESIS_HASH, InvocationEvent, InvocationJournal, canonical_json


@dataclass(frozen=True)
class InvocationResult:
    """Pair the durable invocation identity with the ordinary kernel run result."""

    invocation_id: str
    run: RunResult


def context_payload(context: Context) -> dict[str, object]:
    """Return the provider-neutral representation whose delivery is receipted."""
    return {
        "revision": context.revision,
        "state": context.state,
        "recent_receipts": context.recent_receipts,
    }


def context_digest(context: Context) -> str:
    """Fingerprint exactly the bounded context delivered to one intelligence."""
    return hashlib.sha256(canonical_json(context_payload(context)).encode()).hexdigest()


class Runtime:
    """
    Coordinate one provider invocation while keeping the kernel authoritative.

    The journal may share the same physical database as the kernel store, but
    the contracts remain separate: invocation evidence cannot mutate governed
    semantic state merely because it is durable.
    """

    def __init__(self, kernel: Kernel, journal: InvocationJournal) -> None:
        self.kernel = kernel
        self.journal = journal

    def recover_incomplete_invocations(self) -> tuple[str, ...]:
        """
        Close abandoned prior lifecycles as failed/interrupted evidence.

        A fresh process cannot know whether an external request succeeded before
        its predecessor vanished. Recovery therefore records the interruption and
        explicitly refuses to infer external success.
        """
        recovered: list[str] = []
        for pending in self.journal.incomplete_invocations():
            self.journal.append_invocation_event(
                InvocationEvent(
                    invocation_id=str(pending["invocation_id"]),
                    stage="failed",
                    source_revision=int(pending["source_revision"]),
                    context_digest=str(pending["context_digest"]),
                    provenance=pending.get("provenance"),
                    proposal_id=pending.get("proposal_id"),
                    receipt_id=pending.get("receipt_id"),
                    detail="interrupted",
                    metadata={
                        "failure_stage": "recovery",
                        "observed_prior_stage": str(pending["stage"]),
                        "external_success_assumed": False,
                    },
                )
            )
            recovered.append(str(pending["invocation_id"]))
        return tuple(recovered)

    def run(
        self,
        intelligence: Intelligence,
        *,
        provenance: SubmissionProvenance,
        work_id: str | None = None,
        context_policy: str = "kernel-context-v1",
    ) -> InvocationResult:
        """Execute one disposable intelligence with reconstructable lifecycle evidence."""
        if not context_policy.strip():
            raise ValueError("context_policy must not be empty")

        context = self.kernel.context(work_id=work_id)
        serialized_context = canonical_json(context_payload(context)).encode("utf-8")
        digest = hashlib.sha256(serialized_context).hexdigest()
        history = self.kernel.record.history()
        source_event_head = history[-1]["event_hash"] if history else GENESIS_HASH
        invocation_id = str(uuid.uuid4())
        provenance_payload = provenance.to_dict()
        delivery_metadata = {
            "context_policy": context_policy,
            "context_bytes": len(serialized_context),
            "state_keys": sorted(context.state),
            "receipt_count": len(context.recent_receipts),
            "source_event_head": source_event_head,
            "work_id": work_id,
        }

        self.journal.append_invocation_event(
            InvocationEvent(
                invocation_id=invocation_id,
                stage="requested",
                source_revision=context.revision,
                context_digest=digest,
                provenance=provenance_payload,
                metadata={"context_policy": context_policy, "work_id": work_id},
            )
        )
        self.journal.append_invocation_event(
            InvocationEvent(
                invocation_id=invocation_id,
                stage="context_delivered",
                source_revision=context.revision,
                context_digest=digest,
                provenance=provenance_payload,
                metadata=delivery_metadata,
            )
        )
        self.journal.append_invocation_event(
            InvocationEvent(
                invocation_id=invocation_id,
                stage="attempt_started",
                source_revision=context.revision,
                context_digest=digest,
                provenance=provenance_payload,
            )
        )

        try:
            proposal = intelligence.propose(context)
        except Exception as error:
            self.journal.append_invocation_event(
                InvocationEvent(
                    invocation_id=invocation_id,
                    stage="failed",
                    source_revision=context.revision,
                    context_digest=digest,
                    provenance=provenance_payload,
                    # Exception messages may contain request/provider detail.
                    # Public durable evidence keeps only the stable error class.
                    detail=type(error).__name__,
                    metadata={
                        "failure_stage": "provider",
                        "external_success_assumed": False,
                    },
                )
            )
            raise

        self.journal.append_invocation_event(
            InvocationEvent(
                invocation_id=invocation_id,
                stage="proposal_received",
                source_revision=context.revision,
                context_digest=digest,
                provenance=provenance_payload,
                proposal_id=proposal.proposal_id,
            )
        )

        try:
            receipt = self.kernel.submit(proposal, provenance=provenance)
        except Exception as error:
            self.journal.append_invocation_event(
                InvocationEvent(
                    invocation_id=invocation_id,
                    stage="failed",
                    source_revision=context.revision,
                    context_digest=digest,
                    provenance=provenance_payload,
                    proposal_id=proposal.proposal_id,
                    detail=type(error).__name__,
                    metadata={"failure_stage": "submission"},
                )
            )
            raise

        self.journal.append_invocation_event(
            InvocationEvent(
                invocation_id=invocation_id,
                stage="governed",
                source_revision=context.revision,
                context_digest=digest,
                provenance=provenance_payload,
                proposal_id=proposal.proposal_id,
                receipt_id=receipt.receipt_id,
                detail=receipt.status,
            )
        )
        self.journal.append_invocation_event(
            InvocationEvent(
                invocation_id=invocation_id,
                stage="completed",
                source_revision=context.revision,
                context_digest=digest,
                provenance=provenance_payload,
                proposal_id=proposal.proposal_id,
                receipt_id=receipt.receipt_id,
                detail=receipt.status,
                metadata={"receipt_event_hash": receipt.event_hash},
            )
        )
        return InvocationResult(
            invocation_id=invocation_id,
            run=RunResult(context=context, proposal=proposal, receipt=receipt),
        )
