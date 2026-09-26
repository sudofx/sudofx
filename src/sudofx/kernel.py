"""
SUDOFX KERNEL
=============

Kernel is the transaction coordinator for the governed-work loop:

    Record -> Context -> Proposal -> Governance -> Transition -> Receipt

It owns sequencing, not policy or persistence semantics. Record verifies and
replays history. Governance decides whether a proposal is permitted. Providers
only produce proposals. Kernel makes those owners meet inside one coherent
operation without allowing any of them to impersonate another.

The most important method is ``submit``. It acquires the SQLite write intent,
replays authoritative state, checks proposal identity, evaluates governance,
and appends the receipt before releasing the transaction. Keeping those steps
together prevents two concurrent writers from both accepting proposals based on
the same revision.

Rejected proposals follow the same append path as accepted proposals. Their
revision does not advance and replay applies none of their operations, but their
receipt becomes durable evidence. Provider exceptions before proposal creation
are outside this boundary and therefore do not fabricate a proposal receipt.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from .governance import Governance
from .models import Context, Proposal, Receipt
from .providers import Intelligence
from .record import GENESIS_HASH, Record, canonical_json
from .governance import WORK_ACTIONS, work_key


@dataclass(frozen=True)
class RunResult:
    """Keep the supplied context, untrusted proposal, and durable outcome together."""
    context: Context
    proposal: Proposal
    receipt: Receipt


class Kernel:
    """Coordinate bounded reads and atomic governed submission for one Record."""
    def __init__(self, record: Record, governance: Governance | None = None) -> None:
        self.record = record
        self.governance = governance or Governance()

    def context(self, *, receipt_limit: int = 10, work_id: str | None = None) -> Context:
        """
        Build a snapshot-consistent working view from verified history.

        State and receipts are read in one transaction so a provider never sees
        state from one revision paired with evidence from another. Work-scoped
        context filters both state and receipts while retaining the global
        revision needed for conservative stale-proposal rejection.
        """
        with self.record.connect() as connection:
            connection.execute("BEGIN")
            revision, state = self.record.replay(connection)
            receipts = self.record.recent(receipt_limit, connection)
        if work_id is not None:
            # Absence produces an empty bounded view rather than leaking all
            # state. Governance will later reject transitions for a missing item.
            state = {work_key(work_id): state[work_key(work_id)]} if work_key(work_id) in state else {}
            receipts = tuple(
                receipt
                for receipt in receipts
                if any(
                    operation.get("key") == work_id and operation.get("action") in WORK_ACTIONS
                    for operation in receipt["proposal"].get("operations", [])
                )
            )
        return Context(revision=revision, state=state, recent_receipts=receipts)

    def run(self, intelligence: Intelligence) -> RunResult:
        """
        Give one disposable intelligence a context and submit its proposal.

        No provider reference or hidden memory is retained after this call. A
        later run must reconstruct everything it needs from the Record.
        """
        context = self.context()
        proposal = intelligence.propose(context)
        receipt = self.submit(proposal)
        return RunResult(context=context, proposal=proposal, receipt=receipt)

    def submit(self, proposal: Proposal) -> Receipt:
        """
        Govern and durably record one proposal as an atomic transaction.

        ``BEGIN IMMEDIATE`` serializes writers before the authoritative replay.
        Duplicate proposal IDs fail explicitly rather than returning a prior
        receipt, because silent idempotent replay could hide a caller bug or a
        payload mismatch under reused identity.
        """
        payload = proposal.to_dict()
        with self.record.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            revision, state = self.record.replay(connection)
            existing = connection.execute(
                "SELECT receipt_id FROM events WHERE proposal_id = ?", (proposal.proposal_id,)
            ).fetchone()
            if existing is not None:
                raise ValueError(f"proposal_id already recorded: {proposal.proposal_id}")

            # Governance receives the revision and state from this exact write
            # transaction. It returns permission only; mutation is deferred to
            # replay after the event has become durable.
            decision = self.governance.evaluate(
                proposal, current_revision=revision, current_state=state
            )
            status = "accepted" if decision.accepted else "rejected"
            revision_after = revision + 1 if decision.accepted else revision
            prior = connection.execute(
                "SELECT event_hash FROM events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = prior["event_hash"] if prior else GENESIS_HASH
            receipt_id = str(uuid.uuid4())

            # Hash material excludes wall-clock metadata and SQLite sequence.
            # The semantic receipt can therefore be verified from its durable
            # fields without treating database implementation details as state.
            material = {
                "receipt_id": receipt_id,
                "proposal_id": proposal.proposal_id,
                "status": status,
                "revision_before": revision,
                "revision_after": revision_after,
                "payload": payload,
                "reasons": list(decision.reasons),
            }
            event_hash = self.record.hash_event(previous_hash, material)
            try:
                # One row is the atomic unit for one complete proposal. SQLite
                # uniqueness constraints reinforce proposal and receipt identity
                # even if a future caller bypasses the earlier friendly check.
                connection.execute(
                    """
                    INSERT INTO events (
                        receipt_id, proposal_id, status, revision_before, revision_after,
                        payload, reasons, previous_hash, event_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receipt_id,
                        proposal.proposal_id,
                        status,
                        revision,
                        revision_after,
                        canonical_json(payload),
                        canonical_json(list(decision.reasons)),
                        previous_hash,
                        event_hash,
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                # Explicit rollback makes the recovery boundary visible. Never
                # retry this mutation blindly; first establish whether another
                # writer committed an event with the same identity.
                connection.rollback()
                raise

        return Receipt(
            receipt_id=receipt_id,
            proposal_id=proposal.proposal_id,
            status=status,
            revision_before=revision,
            revision_after=revision_after,
            reasons=decision.reasons,
            event_hash=event_hash,
        )
