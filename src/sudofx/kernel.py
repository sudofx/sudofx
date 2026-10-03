"""
SUDOFX KERNEL
=============

Kernel coordinates the governed-work loop:

    Record -> Context -> Proposal -> Governance -> Transition -> Receipt

It owns sequencing, not policy and not database mechanics. RecordStore verifies
and replays history. Governance decides whether a proposal is permitted.
Providers only produce proposals. Kernel makes those owners meet inside one
coherent operation without allowing any of them to impersonate another.

The key boundary is deliberate: Kernel knows semantic transactions but knows
nothing about SQLite, SQL, connection objects, commits, or rollbacks. A storage
backend must provide one serialized write transaction spanning authoritative
replay, duplicate detection, governance, and append. This lets the initial
SQLite implementation be replaced without changing kernel behavior.

Rejected proposals follow the same append path as accepted proposals. Their
revision does not advance and replay applies none of their operations, but their
receipt remains durable evidence. Provider exceptions before proposal creation
remain outside this boundary and do not fabricate a proposal receipt.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from .governance import Governance, WORK_ACTIONS, work_key

# Historical records may contain the pre-application handoff work action. It is
# replay compatibility only; new governance accepts only WORK_ACTIONS.
HISTORICAL_WORK_RECEIPT_ACTIONS = {*WORK_ACTIONS, "record_handoff_evaluation"}
from .models import Context, Proposal, Receipt, SubmissionProvenance
from .storage import ApplicationAccessState, EventAppend, RecordStore, hash_event


@dataclass(frozen=True)
class RunResult:
    """Keep supplied context, untrusted proposal, and durable outcome together."""

    context: Context
    proposal: Proposal
    receipt: Receipt


class Kernel:
    """
    Coordinate bounded reads and atomic governed submission for one RecordStore.

    The constructor accepts a structural storage contract instead of a concrete
    SQLite type. Correctness therefore depends on the record semantics described
    by RecordStore, not on one backend's connection API or schema.
    """

    def __init__(self, record: RecordStore, governance: Governance | None = None) -> None:
        self.record = record
        self.governance = governance or Governance()

    def application_access_state(self) -> ApplicationAccessState:
        """Expose the storage-owned global application latch without duplicating authority."""
        return self.record.application_access_state()

    def require_application_access(self, expected_generation: int) -> None:
        """Fail closed unless application access still matches the captured generation."""
        self.record.require_application_access(expected_generation)

    def context(self, *, receipt_limit: int = 10, work_id: str | None = None) -> Context:
        """
        Build a snapshot-consistent working view from verified history.

        State and receipts are read through one backend-owned transaction. A
        future storage implementation may realize that snapshot differently,
        but it must preserve the same semantic pairing.
        """
        with self.record.read_transaction() as transaction:
            revision, state = transaction.replay()
            receipts = transaction.recent(receipt_limit)

        if work_id is not None:
            # Absence produces an empty bounded view rather than leaking all
            # state. Governance will later reject transitions for a missing item.
            state = (
                {work_key(work_id): state[work_key(work_id)]}
                if work_key(work_id) in state
                else {}
            )
            receipts = tuple(
                receipt
                for receipt in receipts
                if any(
                    operation.get("key") == work_id
                    and operation.get("action") in HISTORICAL_WORK_RECEIPT_ACTIONS
                    for operation in receipt["proposal"].get("operations", [])
                )
            )
        return Context(revision=revision, state=state, recent_receipts=receipts)

    def submit(
        self,
        proposal: Proposal,
        *,
        provenance: SubmissionProvenance | None = None,
        application_access_generation: int | None = None,
    ) -> Receipt:
        """
        Govern and durably record one proposal as a single semantic transaction.

        The storage backend must serialize writers before replay and must commit
        only after this method exits the transaction successfully. Duplicate
        proposal IDs fail explicitly rather than returning a prior receipt,
        because silent idempotent replay could hide mismatched reused identity.
        """
        payload = proposal.to_dict()
        provenance_payload = provenance.to_dict() if provenance is not None else None

        with self.record.write_transaction() as transaction:
            # Application callers capture the access generation before doing
            # work. Rechecking inside the serialized commit transaction makes an
            # operator STOP invalidate any request that crossed the boundary
            # before the latch changed.
            if application_access_generation is not None:
                transaction.require_application_access(application_access_generation)
            revision, state = transaction.replay()
            if transaction.proposal_exists(proposal.proposal_id):
                raise ValueError(f"proposal_id already recorded: {proposal.proposal_id}")

            # Governance sees the exact state/revision snapshot owned by this
            # write transaction. Permission is decided before any append occurs.
            decision = self.governance.evaluate(
                proposal,
                current_revision=revision,
                current_state=state,
            )
            status = "accepted" if decision.accepted else "rejected"
            revision_after = revision + 1 if decision.accepted else revision
            previous_hash = transaction.head_hash()
            receipt_id = str(uuid.uuid4())

            # Application materialized state is a derived projection hint, not
            # semantic event content. Governance has already recomputed and
            # validated it. Strip it before hashing/persistence, then hand the
            # verified value separately to storage for atomic projection update.
            projection_overrides = {}
            durable_payload = proposal.to_dict()
            for operation in durable_payload.get("operations", []):
                if operation.get("action") != "apply_application":
                    continue
                value = operation.get("value")
                if not isinstance(value, dict) or "projection_state" not in value:
                    continue
                projection_state = value.pop("projection_state")
                if decision.accepted:
                    projection_overrides[operation["key"]] = projection_state

            # Semantic hash material excludes physical storage metadata. A later
            # backend can change tables, timestamps, or sequence representation
            # while preserving the same durable event identity contract.
            material = {
                "receipt_id": receipt_id,
                "proposal_id": proposal.proposal_id,
                "status": status,
                "revision_before": revision,
                "revision_after": revision_after,
                "payload": durable_payload,
                "reasons": list(decision.reasons),
            }
            # Legacy events predate trusted provenance and intentionally omit the
            # field from their hash material. New attributed events bind origin
            # evidence into the same semantic hash chain as the proposal.
            if provenance_payload is not None:
                material["provenance"] = provenance_payload
            event_hash = hash_event(previous_hash, material)

            # Storage receives one complete event. Commit/rollback remains inside
            # the backend transaction context; Kernel never performs native
            # recovery calls and therefore cannot accidentally become SQLite-aware.
            transaction.append(
                EventAppend(
                    receipt_id=receipt_id,
                    proposal_id=proposal.proposal_id,
                    status=status,
                    revision_before=revision,
                    revision_after=revision_after,
                    payload=durable_payload,
                    reasons=decision.reasons,
                    provenance=provenance_payload,
                    previous_hash=previous_hash,
                    event_hash=event_hash,
                ),
                projection_overrides=projection_overrides or None,
            )

        return Receipt(
            receipt_id=receipt_id,
            proposal_id=proposal.proposal_id,
            status=status,
            revision_before=revision,
            revision_after=revision_after,
            reasons=decision.reasons,
            event_hash=event_hash,
        )
