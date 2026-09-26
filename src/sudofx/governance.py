"""Deterministic proposal policy."""

from __future__ import annotations

from .models import GovernanceDecision, Proposal


class Governance:
    """Validate proposals without consulting the intelligence that created them."""

    def __init__(self, *, max_operations: int = 100, max_key_length: int = 200) -> None:
        self.max_operations = max_operations
        self.max_key_length = max_key_length

    def evaluate(self, proposal: Proposal, *, current_revision: int) -> GovernanceDecision:
        reasons: list[str] = []
        if proposal.based_on_revision != current_revision:
            reasons.append(
                f"stale proposal: based on revision {proposal.based_on_revision}, "
                f"current revision is {current_revision}"
            )
        if not proposal.proposal_id.strip():
            reasons.append("proposal_id must not be empty")
        if not proposal.operations:
            reasons.append("proposal must contain at least one operation")
        if len(proposal.operations) > self.max_operations:
            reasons.append(f"proposal exceeds {self.max_operations} operations")

        seen: set[str] = set()
        for operation in proposal.operations:
            if operation.action not in {"set", "delete"}:
                reasons.append(f"unsupported action: {operation.action}")
            if not operation.key or len(operation.key) > self.max_key_length:
                reasons.append(f"invalid key: {operation.key!r}")
            if operation.key in seen:
                reasons.append(f"duplicate key in proposal: {operation.key}")
            seen.add(operation.key)

        return GovernanceDecision(accepted=not reasons, reasons=tuple(reasons))
