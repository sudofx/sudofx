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
from .models import SubmissionProvenance
from .providers import Intelligence
from .storage import (
    ContextDeliveryReceipt,
    InvocationEvent,
    InvocationJournal,
    canonical_json,
)


@dataclass(frozen=True)
class InvocationResult:
    """Pair the durable invocation identity with the ordinary kernel run result."""

    invocation_id: str
    run: RunResult


CONTEXT_POLICY_VERSION = "kernel-context-v1"


def context_payload(context: object) -> dict[str, object]:
    """Project the exact provider-neutral payload fingerprinted for delivery evidence."""
    return {
        "revision": context.revision,
        "state": context.state,
        "recent_receipts": context.recent_receipts,
    }


def context_digest(context: object) -> str:
    """Fingerprint exactly the bounded context delivered to one intelligence."""
    return hashlib.sha256(canonical_json(context_payload(context)).encode()).hexdigest()


def context_delivery_receipt(
    context: object,
    *,
    work_id: str | None,
) -> ContextDeliveryReceipt:
    """
    Describe bounded context without durably copying the context itself.

    The lifecycle digest anchors the exact bytes. This receipt adds structural
    evidence about the policy, byte size, categories, and scope that crossed the
    boundary while keeping authoritative state singular.
    """
    encoded = canonical_json(context_payload(context)).encode()
    scope = {"kind": "work", "work_id": work_id} if work_id is not None else {"kind": "global"}
    return ContextDeliveryReceipt(
        policy_version=CONTEXT_POLICY_VERSION,
        payload_bytes=len(encoded),
        included_categories=("state", "recent_receipts"),
        scope=scope,
    )


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

    def run(
        self,
        intelligence: Intelligence,
        *,
        work_id: str | None = None,
        provenance: SubmissionProvenance | None = None,
    ) -> InvocationResult:
        """Execute one disposable intelligence with reconstructable lifecycle evidence."""
        context = self.kernel.context(work_id=work_id)
        digest = context_digest(context)
        delivery_receipt = context_delivery_receipt(context, work_id=work_id)
        invocation_id = str(uuid.uuid4())
        provenance_payload = provenance.to_dict() if provenance is not None else None

        self.journal.append_invocation_event(
            InvocationEvent(
                invocation_id=invocation_id,
                stage="requested",
                source_revision=context.revision,
                context_digest=digest,
                provenance=provenance_payload,
            )
        )
        self.journal.append_invocation_event(
            InvocationEvent(
                invocation_id=invocation_id,
                stage="context_delivered",
                source_revision=context.revision,
                context_digest=digest,
                provenance=provenance_payload,
                context_receipt=delivery_receipt,
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
        except BaseException as error:
            self.journal.append_invocation_event(
                InvocationEvent(
                    invocation_id=invocation_id,
                    stage="failed",
                    source_revision=context.revision,
                    context_digest=digest,
                    provenance=provenance_payload,
                    detail=f"{type(error).__name__}: {error}",
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
        receipt = self.kernel.submit(proposal, provenance=provenance)
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
            )
        )
        return InvocationResult(
            invocation_id=invocation_id,
            run=RunResult(context=context, proposal=proposal, receipt=receipt),
        )
