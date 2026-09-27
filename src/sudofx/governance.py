"""
SUDOFX GOVERNANCE
=================

This module is the mechanical authority between untrusted proposals and durable
state. Intelligence may suggest a transition. Only these deterministic rules
decide whether the transition is permitted.

The separation is the kernel's central trust boundary:

    provider output  = untrusted proposal
    governance       = deterministic permission
    replay           = accepted state transition
    record           = durable evidence

Governance never calls a model, interprets persuasive prose, or changes policy
based on the provider that submitted a proposal. Given the same state, revision,
and proposal, it must return the same decision.

Evaluation is whole-proposal atomic. If any operation is stale, malformed,
duplicated, or invalid for the current lifecycle, the complete proposal is
rejected. We do not partially accept the safe-looking operations because doing
so would create state the proposer never observed or intended as a standalone
transition.

Rejection is expected product behavior, not exceptional corruption. A rejected
proposal becomes a hash-linked receipt while authoritative state and revision
remain unchanged. This lets failure teach future disposable invocations without
letting failure become accepted state.

Rules in this module validate whether a change may happen. They must not mutate
state. Record replay owns how an accepted action changes state. Whenever an
action is added, its models, governance, replay, proof, and presentation must be
updated together.
"""

from __future__ import annotations

from .models import GovernanceDecision, JsonValue, Proposal

WORK_ACTIONS = {"create_work", "advance_work", "record_assessment", "complete_work"}

# Work state occupies an explicit namespace inside the generic JSON state map.
# The prefix prevents a work identifier from colliding with an operator's plain
# key while keeping replay transparent and serializable. All owners must call
# this helper rather than reproducing the prefix ad hoc.


def work_key(work_id: str) -> str:
    """Return the canonical state key for a governed work identifier."""
    return f"work:{work_id}"


class Governance:
    """
    Validate proposals without consulting the intelligence that created them.

    The configurable bounds are operational guardrails, not provider hints.
    They cap proposal breadth and identifier growth before either can inflate
    durable history or future bounded context indefinitely.
    """

    def __init__(self, *, max_operations: int = 100, max_key_length: int = 200) -> None:
        # Store limits on the authority object so deployments can tighten them
        # deliberately without teaching providers a second policy language.
        self.max_operations = max_operations
        self.max_key_length = max_key_length

    def evaluate(
        self,
        proposal: Proposal,
        *,
        current_revision: int,
        current_state: dict[str, JsonValue] | None = None,
    ) -> GovernanceDecision:
        """
        Evaluate the complete proposal against one authoritative snapshot.

        ``current_revision`` and ``current_state`` must come from the same
        database transaction. Passing values from different snapshots would
        make stale detection truthful while lifecycle validation used newer or
        older state. Kernel.submit owns that atomic read.

        Reasons accumulate instead of failing fast. A rejected proposal can
        therefore tell a future invocation everything mechanically wrong with
        its shape in one receipt, reducing corrective retries without weakening
        the all-or-nothing decision.
        """
        current_state = current_state or {}
        reasons: list[str] = []

        # Optimistic concurrency is global. Even a work-scoped provider reasons
        # from a record revision, so unrelated accepted work makes that view
        # stale. This conservative rule prevents hidden lost updates until a
        # more granular concurrency contract is designed explicitly.
        if proposal.based_on_revision != current_revision:
            reasons.append(
                f"stale proposal: based on revision {proposal.based_on_revision}, "
                f"current revision is {current_revision}"
            )
        if not proposal.proposal_id.strip():
            reasons.append("proposal_id must not be empty")
        if not proposal.operations:
            reasons.append("proposal must contain at least one operation")

        # A bounded operation count protects record inspectability and keeps one
        # accepted receipt from becoming an unreviewable bulk mutation.
        if len(proposal.operations) > self.max_operations:
            reasons.append(f"proposal exceeds {self.max_operations} operations")

        seen: set[str] = set()
        for operation in proposal.operations:
            # Literal annotations help callers, but runtime input may originate
            # outside Python. Governance therefore checks the action explicitly.
            if operation.action not in {"set", "delete", *WORK_ACTIONS}:
                reasons.append(f"unsupported action: {operation.action}")
            if not operation.key or len(operation.key) > self.max_key_length:
                reasons.append(f"invalid key: {operation.key!r}")
            if operation.key in seen:
                reasons.append(f"duplicate key in proposal: {operation.key}")
            seen.add(operation.key)

            # Multiple operations targeting one key are rejected above because
            # their internal ordering would become an additional mini-language.
            # One durable action per key keeps proposals reviewable and replay
            # semantics unsurprising.
            if operation.action == "create_work":
                self._validate_create(operation.key, operation.value, current_state, reasons)
            elif operation.action in {"advance_work", "record_assessment", "complete_work"}:
                self._validate_transition(operation.action, operation.key, operation.value, current_state, reasons)

        return GovernanceDecision(accepted=not reasons, reasons=tuple(reasons))

    @staticmethod
    def _validate_create(
        work_id: str,
        value: JsonValue,
        state: dict[str, JsonValue],
        reasons: list[str],
    ) -> None:
        """
        Protect the creation boundary for durable work.

        Creation is the only transition allowed to establish identity,
        objective, and constraints. Later providers may advance results or
        complete the work, but cannot silently rewrite its original purpose.
        """
        if work_key(work_id) in state:
            reasons.append(f"work item already exists: {work_id}")
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("objective"), str)
            or not value["objective"].strip()
        ):
            reasons.append("create_work requires a non-empty objective")
        constraints = value.get("constraints", []) if isinstance(value, dict) else []

        # Constraints are durable product meaning. Empty or non-text entries
        # would produce ambiguity that later invocations could not reconstruct.
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
        """
        Enforce the open -> progress* -> completed lifecycle.

        An absent item cannot be advanced into existence. A completed item is
        immutable because reopening would erase the meaning of completion; a
        future reopen operation would need its own explicit product contract and
        receipt semantics.
        """
        work = state.get(work_key(work_id))
        if not isinstance(work, dict):
            reasons.append(f"work item does not exist: {work_id}")
            return
        if work.get("status") != "open":
            reasons.append(f"work item is not open: {work_id}")
        if action == "advance_work":
            # Progress must contribute a concrete accepted result. Obligations
            # replace the prior open set so the record always states what remains
            # after this revision rather than accumulating stale todos forever.
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
        elif action == "record_assessment":
            Governance._validate_assessment(value, reasons)
        # Completion requires an explicit final result. Merely toggling a status
        # would leave future readers unable to tell what outcome was accepted.
        elif (
            not isinstance(value, dict)
            or not isinstance(value.get("result"), str)
            or not value["result"].strip()
        ):
            reasons.append("complete_work requires a non-empty final result")

    @staticmethod
    def _validate_assessment(value: JsonValue, reasons: list[str]) -> None:
        """Validate one structured human semantic judgment and its provenance."""
        if not isinstance(value, dict):
            reasons.append("record_assessment requires an object")
            return

        verdict = value.get("verdict")
        if verdict not in {"pass", "fail", "uncertain"}:
            reasons.append("assessment verdict must be pass, fail, or uncertain")

        criteria = value.get("criteria")
        allowed_criteria = {
            "objective_fidelity",
            "history_fidelity",
            "frontier_fidelity",
            "compression_awareness",
            "unsupported_claims",
            "actionability",
        }
        if (
            not isinstance(criteria, dict)
            or not criteria
            or any(
                key not in allowed_criteria
                or result not in {"pass", "fail", "uncertain"}
                for key, result in criteria.items()
            )
        ):
            reasons.append("assessment criteria must contain recognized pass/fail/uncertain judgments")

        metrics = value.get("metrics")
        required_metrics = {
            "context_bytes",
            "full_context_bytes",
            "compression_ratio",
            "accepted_results_exposed",
            "receipt_count_exposed",
        }
        if not isinstance(metrics, dict) or not required_metrics.issubset(metrics):
            reasons.append("assessment metrics are incomplete")
        elif (
            any(isinstance(metrics[key], bool) for key in required_metrics)
            or not isinstance(metrics["context_bytes"], int)
            or not isinstance(metrics["full_context_bytes"], int)
            or not isinstance(metrics["compression_ratio"], (int, float))
            or not isinstance(metrics["accepted_results_exposed"], int)
            or not isinstance(metrics["receipt_count_exposed"], int)
            or metrics["context_bytes"] < 0
            or metrics["full_context_bytes"] < 0
            or not 0 <= float(metrics["compression_ratio"]) <= 1
            or metrics["accepted_results_exposed"] < 0
            or metrics["receipt_count_exposed"] < 0
        ):
            reasons.append("assessment metrics contain invalid values")

        provenance = value.get("provenance")
        required_provenance = {
            "artifact_run_id",
            "artifact_commit",
            "context_digest",
            "provider",
            "model",
        }
        if (
            not isinstance(provenance, dict)
            or any(
                not isinstance(provenance.get(key), str) or not provenance[key].strip()
                for key in required_provenance
            )
        ):
            reasons.append("assessment provenance is incomplete")

        note = value.get("note")
        if note is not None and (not isinstance(note, str) or not note.strip()):
            reasons.append("assessment note must be a non-empty string when supplied")
