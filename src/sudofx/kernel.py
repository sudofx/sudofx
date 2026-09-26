"""The governed Record → Context → Proposal → Receipt loop."""

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
    context: Context
    proposal: Proposal
    receipt: Receipt


class Kernel:
    def __init__(self, record: Record, governance: Governance | None = None) -> None:
        self.record = record
        self.governance = governance or Governance()

    def context(self, *, receipt_limit: int = 10, work_id: str | None = None) -> Context:
        with self.record.connect() as connection:
            connection.execute("BEGIN")
            revision, state = self.record.replay(connection)
            receipts = self.record.recent(receipt_limit, connection)
        if work_id is not None:
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
        context = self.context()
        proposal = intelligence.propose(context)
        receipt = self.submit(proposal)
        return RunResult(context=context, proposal=proposal, receipt=receipt)

    def submit(self, proposal: Proposal) -> Receipt:
        payload = proposal.to_dict()
        with self.record.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            revision, state = self.record.replay(connection)
            existing = connection.execute(
                "SELECT receipt_id FROM events WHERE proposal_id = ?", (proposal.proposal_id,)
            ).fetchone()
            if existing is not None:
                raise ValueError(f"proposal_id already recorded: {proposal.proposal_id}")

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
