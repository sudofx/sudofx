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
from .providers import Intelligence, ProviderQuotaError, ProviderTemporaryError
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
    scope: dict[str, str] | None = None,
) -> ContextDeliveryReceipt:
    """
    Describe bounded context without durably copying the context itself.

    The lifecycle digest anchors the exact bytes. This receipt adds structural
    evidence about the policy, byte size, categories, and scope that crossed the
    boundary while keeping authoritative state singular.
    """
    encoded = canonical_json(context_payload(context)).encode()
    resolved_scope = (
        scope
        if scope is not None
        else {"kind": "work", "work_id": work_id}
        if work_id is not None
        else {"kind": "global"}
    )
    return ContextDeliveryReceipt(
        policy_version=CONTEXT_POLICY_VERSION,
        payload_bytes=len(encoded),
        included_categories=("state", "recent_receipts"),
        scope=resolved_scope,
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

    def recover_incomplete_invocations(self) -> tuple[str, ...]:
        """
        Close abandoned invocations without guessing what happened externally.

        Recovery turns an unfinished lifecycle into explicit interruption
        evidence. It does not manufacture a Proposal, receipt, or successful
        external effect.
        """
        recovered: list[str] = []
        for pending in self.journal.incomplete_invocations():
            invocation_id = str(pending["invocation_id"])
            self.journal.append_invocation_event(
                InvocationEvent(
                    invocation_id=invocation_id,
                    stage="failed",
                    source_revision=int(pending["source_revision"]),
                    context_digest=str(pending["context_digest"]),
                    provenance=pending.get("provenance"),
                    outcome=None,
                    proposal_id=pending.get("proposal_id"),
                    receipt_id=pending.get("receipt_id"),
                    detail="interrupted",
                )
            )
            recovered.append(invocation_id)
        return tuple(recovered)

    def run(
        self,
        intelligence: Intelligence,
        *,
        provenance: SubmissionProvenance,
        work_id: str | None = None,
        context_scope: dict[str, str] | None = None,
    ) -> InvocationResult:
        """Execute one disposable intelligence with reconstructable lifecycle evidence."""
        context = self.kernel.context(work_id=work_id)
        digest = context_digest(context)
        delivery_receipt = context_delivery_receipt(
            context,
            work_id=work_id,
            scope=context_scope,
        )
        invocation_id = str(uuid.uuid4())
        provenance_payload = provenance.to_dict()

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
        except Exception as error:
            if isinstance(error, ProviderQuotaError):
                outcome = "quota_exhausted"
            elif isinstance(error, ProviderTemporaryError):
                outcome = "temporary_failure"
            else:
                outcome = "provider_failure"
            self.journal.append_invocation_event(
                InvocationEvent(
                    invocation_id=invocation_id,
                    stage="failed",
                    source_revision=context.revision,
                    context_digest=digest,
                    provenance=provenance_payload,
                    outcome=outcome,
                    detail=type(error).__name__,
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
                outcome="success",
                detail=receipt.status,
            )
        )
        return InvocationResult(
            invocation_id=invocation_id,
            run=RunResult(context=context, proposal=proposal, receipt=receipt),
        )
