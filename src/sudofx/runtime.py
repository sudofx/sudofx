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
from collections.abc import Callable
from dataclasses import dataclass

from .kernel import Kernel, RunResult
from .models import SubmissionProvenance
from .providers import Intelligence, ProviderQuotaError, ProviderTemporaryError
from .storage import (
    ApplicationAccessError,
    ContextDeliveryReceipt,
    InvocationEvent,
    InvocationJournal,
    canonical_json,
)


class InvocationBarrierError(RuntimeError):
    """Distinguish pre-effect durability failure from provider failure."""

    def __init__(self, cause: Exception) -> None:
        super().__init__(f"external effect barrier failed: {type(cause).__name__}")
        self.cause = cause


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


@dataclass(frozen=True)
class InvocationLifecycle:
    """Application-neutral durable provider-attempt lifecycle recorder."""

    journal: InvocationJournal
    invocation_id: str
    source_revision: int
    context_digest: str
    provenance: dict[str, object]

    @classmethod
    def begin(
        cls,
        journal: InvocationJournal,
        context: object,
        *,
        provenance: SubmissionProvenance,
        work_id: str | None = None,
        context_scope: dict[str, str] | None = None,
        invocation_id: str | None = None,
    ) -> "InvocationLifecycle":
        """Record request, context delivery, and attempt start for one provider boundary."""
        digest = context_digest(context)
        delivery_receipt = context_delivery_receipt(
            context,
            work_id=work_id,
            scope=context_scope,
        )
        resolved_id = invocation_id or str(uuid.uuid4())
        provenance_payload = provenance.to_dict()
        common = {
            "invocation_id": resolved_id,
            "source_revision": context.revision,
            "context_digest": digest,
            "provenance": provenance_payload,
        }
        journal.append_invocation_event(InvocationEvent(stage="requested", **common))
        journal.append_invocation_event(
            InvocationEvent(
                stage="context_delivered",
                context_receipt=delivery_receipt,
                **common,
            )
        )
        journal.append_invocation_event(InvocationEvent(stage="attempt_started", **common))
        return cls(
            journal=journal,
            invocation_id=resolved_id,
            source_revision=context.revision,
            context_digest=digest,
            provenance=provenance_payload,
        )

    def _event(self, stage: str, **fields: object) -> None:
        self.journal.append_invocation_event(
            InvocationEvent(
                invocation_id=self.invocation_id,
                stage=stage,
                source_revision=self.source_revision,
                context_digest=self.context_digest,
                provenance=self.provenance,
                **fields,
            )
        )

    def invoke(
        self,
        effect: Callable[[], object],
        *,
        effect_barrier: Callable[[], None] | None = None,
        classify_error: Callable[[Exception], str | None] | None = None,
    ) -> object:
        """Execute one external effect after its durability barrier.

        Generic sequencing lives here so applications cannot accidentally call
        a provider before request/attempt evidence is durably checkpointed.
        Applications may classify provider-specific exceptions, but the
        classifier receives only the exception and cannot perform the effect.
        """
        if effect_barrier is not None:
            try:
                effect_barrier()
            except Exception as error:
                self.fail(
                    outcome=None,
                    detail=f"effect_barrier:{type(error).__name__}",
                )
                raise InvocationBarrierError(error) from error

        try:
            return effect()
        except Exception as error:
            if classify_error is not None:
                outcome = classify_error(error)
            elif isinstance(error, ProviderQuotaError):
                outcome = "quota_exhausted"
            elif isinstance(error, ProviderTemporaryError):
                outcome = "temporary_failure"
            else:
                outcome = "provider_failure"
            self.fail(outcome=outcome, detail=type(error).__name__)
            raise

    def proposal_received(self, proposal_id: str) -> None:
        self._event("proposal_received", proposal_id=proposal_id)

    def governed(self, proposal_id: str, receipt_id: str | None, status: str) -> None:
        self._event(
            "governed",
            proposal_id=proposal_id,
            receipt_id=receipt_id,
            detail=status,
        )

    def fail(
        self,
        *,
        outcome: str | None = None,
        proposal_id: str | None = None,
        receipt_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        self._event(
            "failed",
            outcome=outcome,
            proposal_id=proposal_id,
            receipt_id=receipt_id,
            detail=detail,
        )

    def complete(
        self,
        *,
        proposal_id: str | None = None,
        receipt_id: str | None = None,
        outcome: str = "success",
        detail: str | None = None,
    ) -> None:
        self._event(
            "completed",
            outcome=outcome,
            proposal_id=proposal_id,
            receipt_id=receipt_id,
            detail=detail,
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
        effect_barrier: Callable[[], None] | None = None,
    ) -> InvocationResult:
        """Execute one disposable intelligence with reconstructable lifecycle evidence."""
        application_generation: int | None = None
        if context_scope is not None and context_scope.get("kind") == "application":
            access = self.kernel.application_access_state()
            if not access.enabled:
                raise ApplicationAccessError()
            application_generation = access.generation

        context = self.kernel.context(work_id=work_id)
        lifecycle = InvocationLifecycle.begin(
            self.journal,
            context,
            provenance=provenance,
            work_id=work_id,
            context_scope=context_scope,
        )

        def guarded_barrier() -> None:
            if application_generation is not None:
                self.kernel.require_application_access(application_generation)
            if effect_barrier is not None:
                effect_barrier()

        try:
            proposal = lifecycle.invoke(
                lambda: intelligence.propose(context),
                effect_barrier=guarded_barrier if application_generation is not None or effect_barrier is not None else None,
            )
        except InvocationBarrierError as error:
            raise error.cause

        lifecycle.proposal_received(proposal.proposal_id)
        try:
            receipt = self.kernel.submit(
                proposal,
                provenance=provenance,
                application_access_generation=application_generation,
            )
        except Exception as error:
            lifecycle.fail(proposal_id=proposal.proposal_id, detail=type(error).__name__)
            raise

        lifecycle.governed(proposal.proposal_id, receipt.receipt_id, receipt.status)
        lifecycle.complete(
            proposal_id=proposal.proposal_id,
            receipt_id=receipt.receipt_id,
            detail=receipt.status,
        )
        return InvocationResult(
            invocation_id=lifecycle.invocation_id,
            run=RunResult(context=context, proposal=proposal, receipt=receipt),
        )
