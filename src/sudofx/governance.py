"""Deterministic proposal policy."""

from __future__ import annotations

from .models import GovernanceDecision, JsonValue, Proposal

WORK_ACTIONS = {"create_work", "advance_work", "complete_work"}


def work_key(work_id: str) -> str:
    return f"work:{work_id}"


class Governance:
    """Validate proposals without consulting the intelligence that created them."""

    def __init__(self, *, max_operations: int = 100, max_key_length: int = 200) -> None:
        self.max_operations = max_operations
        self.max_key_length = max_key_length

    def evaluate(
        self,
        proposal: Proposal,
        *,
        current_revision: int,
        current_state: dict[str, JsonValue] | None = None,
    ) -> GovernanceDecision:
        current_state = current_state or {}
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
            if operation.action not in {"set", "delete", *WORK_ACTIONS}:
                reasons.append(f"unsupported action: {operation.action}")
            if not operation.key or len(operation.key) > self.max_key_length:
                reasons.append(f"invalid key: {operation.key!r}")
            if operation.key in seen:
                reasons.append(f"duplicate key in proposal: {operation.key}")
            seen.add(operation.key)
            if operation.action == "create_work":
                self._validate_create(operation.key, operation.value, current_state, reasons)
            elif operation.action in {"advance_work", "complete_work"}:
                self._validate_transition(operation.action, operation.key, operation.value, current_state, reasons)

        return GovernanceDecision(accepted=not reasons, reasons=tuple(reasons))

    @staticmethod
    def _validate_create(
        work_id: str,
        value: JsonValue,
        state: dict[str, JsonValue],
        reasons: list[str],
    ) -> None:
        if work_key(work_id) in state:
            reasons.append(f"work item already exists: {work_id}")
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("objective"), str)
            or not value["objective"].strip()
        ):
            reasons.append("create_work requires a non-empty objective")
        constraints = value.get("constraints", []) if isinstance(value, dict) else []
        if not isinstance(constraints, list) or not all(
            isinstance(constraint, str) and constraint.strip() for constraint in constraints
        ):
            reasons.append("work constraints must be non-empty strings")

    @staticmethod
    def _validate_transition(
        action: str,
        work_id: str,
        value: JsonValue,
        state: dict[str, JsonValue],
        reasons: list[str],
    ) -> None:
        work = state.get(work_key(work_id))
        if not isinstance(work, dict):
            reasons.append(f"work item does not exist: {work_id}")
            return
        if work.get("status") != "open":
            reasons.append(f"work item is not open: {work_id}")
        if action == "advance_work":
            if (
                not isinstance(value, dict)
                or not isinstance(value.get("result"), str)
                or not value["result"].strip()
            ):
                reasons.append("advance_work requires a non-empty result")
            obligations = value.get("open_obligations", []) if isinstance(value, dict) else []
            if not isinstance(obligations, list) or not all(
                isinstance(obligation, str) and obligation.strip() for obligation in obligations
            ):
                reasons.append("open obligations must be non-empty strings")
        elif (
            not isinstance(value, dict)
            or not isinstance(value.get("result"), str)
            or not value["result"].strip()
        ):
            reasons.append("complete_work requires a non-empty final result")
