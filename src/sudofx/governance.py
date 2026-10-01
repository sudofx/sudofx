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

import hashlib

from .applications import (
    APPLICATION_PREFIX,
    ApplicationRegistry,
    application_key,
    application_state,
)
from .models import GovernanceDecision, JsonValue, Proposal
from .storage import canonical_json

WORK_ACTIONS = {"create_work", "advance_work", "record_assessment", "record_handoff_evaluation", "complete_work"}

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

    def __init__(
        self,
        *,
        max_operations: int = 100,
        max_key_length: int = 200,
        application_registry: ApplicationRegistry | None = None,
    ) -> None:
        # Store limits on the authority object so deployments can tighten them
        # deliberately without teaching providers a second policy language.
        self.max_operations = max_operations
        self.max_key_length = max_key_length
        self.application_registry = application_registry or ApplicationRegistry()

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
            if operation.action not in {"set", "delete", "apply_application", *WORK_ACTIONS}:
                reasons.append(f"unsupported action: {operation.action}")
            if not operation.key or len(operation.key) > self.max_key_length:
                reasons.append(f"invalid key: {operation.key!r}")
            if operation.key in seen:
                reasons.append(f"duplicate key in proposal: {operation.key}")
            seen.add(operation.key)

            # Application namespaces are sealed from generic set/delete. Domain
            # state can move only through apply_application, where current policy
            # is independently recomputed before acceptance.
            if (
                operation.action in {"set", "delete"}
                and operation.key.startswith(APPLICATION_PREFIX)
            ):
                reasons.append("application namespace requires apply_application")

            # Multiple operations targeting one key are rejected above because
            # their internal ordering would become an additional mini-language.
            # One durable action per key keeps proposals reviewable and replay
            # semantics unsurprising.
            if operation.action == "apply_application":
                self._validate_application(operation.key, operation.value, current_state, reasons)
            elif operation.action == "create_work":
                self._validate_create(operation.key, operation.value, current_state, reasons)
            elif operation.action in {"advance_work", "record_assessment", "record_handoff_evaluation", "complete_work"}:
                self._validate_transition(operation.action, operation.key, operation.value, current_state, reasons)

        return GovernanceDecision(accepted=not reasons, reasons=tuple(reasons))

    def _validate_application(
        self,
        application_id: str,
        value: JsonValue,
        state: dict[str, JsonValue],
        reasons: list[str],
    ) -> None:
        """Recompute one registered application transition before accepting it."""
        if not isinstance(value, dict):
            reasons.append("apply_application requires an object")
            return
        if value.get("application_id") != application_id:
            reasons.append("application identity does not match operation key")
            return
        version = value.get("application_version")
        action_name = value.get("action")
        if not isinstance(version, str) or not version.strip():
            reasons.append("application version is required")
            return
        if not isinstance(action_name, str) or not action_name.strip():
            reasons.append("application action is required")
            return

        definition = self.application_registry.get(application_id)
        if definition is None:
            reasons.append(f"application is not registered: {application_id}")
            return
        if definition.version != version:
            reasons.append(
                f"application version mismatch: registered {definition.version}, proposed {version}"
            )
            return

        envelope = state.get(application_key(application_id))
        try:
            current_state = application_state(definition, envelope)
        except ValueError as error:
            reasons.append(str(error))
            return

        action = definition.action(action_name)
        if action is None:
            reasons.append(f"unknown application action: {action_name}")
            return
        try:
            decision = action.evaluate(current_state, value.get("input"))
        except Exception:
            reasons.append(f"application policy could not evaluate action: {action_name}")
            return
        if not decision.accepted:
            reasons.extend(
                decision.reasons or (f"application action rejected: {action_name}",)
            )
            return
        if definition.state_storage == "event_log":
            if value.get("storage") != "event_log":
                reasons.append("application event-log storage mode is required")
                return
            if "next_state" in value:
                reasons.append("event-log application events must not persist full next_state")
                return
            result_digest = value.get("result_digest")
            expected_digest = hashlib.sha256(canonical_json(decision.next_state).encode()).hexdigest()
            if result_digest != expected_digest:
                reasons.append("application result_digest does not match deterministic policy result")
        elif canonical_json(decision.next_state) != canonical_json(value.get("next_state")):
            reasons.append("application next_state does not match deterministic policy result")

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
        elif action == "record_handoff_evaluation":
            Governance._validate_handoff_evaluation(value, reasons)
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

        assessment_kind = value.get("kind")
        if assessment_kind == "human_semantic_review_v1":
            # The pinned overnight runner durably records run identity, digest,
            # provider, model, and candidate semantics, but not its transient
            # byte-count diagnostics. A human review must never invent those
            # missing metrics merely to fit the older assessment envelope.
            expected_criteria = {
                "objective_fidelity",
                "history_fidelity",
                "frontier_fidelity",
                "compression_awareness",
                "unsupported_claims",
                "actionability",
            }
            if not isinstance(criteria, dict) or set(criteria) != expected_criteria:
                reasons.append("human semantic review requires exactly the six review criteria")
            elif verdict != (
                "fail" if "fail" in criteria.values()
                else "uncertain" if "uncertain" in criteria.values()
                else "pass"
            ):
                reasons.append("human semantic review verdict must be derived from its criteria")
        else:
            # Legacy/manual continuity assessments carry compression metrics when
            # those measurements were actually captured at the reviewed boundary.
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
        if assessment_kind == "human_semantic_review_v1":
            required_provenance = {"artifact_run_id", "context_digest", "reviewer"}
            optional_provenance = {"artifact_commit", "provider", "model"}
            if (
                not isinstance(provenance, dict)
                or any(
                    not isinstance(provenance.get(key), str) or not provenance[key].strip()
                    for key in required_provenance
                )
                or provenance.get("reviewer") not in {"operator", "chatgpt"}
                or any(
                    key in provenance
                    and (not isinstance(provenance[key], str) or not provenance[key].strip())
                    for key in optional_provenance
                )
            ):
                reasons.append("human semantic review provenance is incomplete or reviewer is invalid")
        else:
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

    @staticmethod
    def _validate_handoff_evaluation(value: JsonValue, reasons: list[str]) -> None:
        """Validate one immutable, human-transported continuity result.

        The workflow, not the tested intelligence, calculates ``score`` and
        ``criteria``. Governance accepts only the normalized shape so a shared
        answer cannot promote its own claims into a trusted grade.
        """
        if not isinstance(value, dict):
            reasons.append("record_handoff_evaluation requires an object")
            return
        required_text = {"test_id", "nonce", "vendor", "packet_digest", "raw_response", "submitted_at"}
        if any(not isinstance(value.get(key), str) or not value[key].strip() for key in required_text):
            reasons.append("handoff evaluation identity, provenance, response, and timestamp are required")
        criteria = value.get("criteria")
        if (
            not isinstance(criteria, dict)
            or set(criteria) != {
                "objective_fidelity", "authority_fidelity", "history_fidelity",
                "constraint_fidelity", "frontier_fidelity", "epistemic_discipline",
                "transfer_usability",
            }
            or any(result not in {"pass", "fail"} for result in criteria.values())
        ):
            reasons.append("handoff evaluation criteria must contain all seven pass/fail dimensions")
        score = value.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 7:
            reasons.append("handoff evaluation score must be an integer from zero through seven")
        if not isinstance(value.get("answers"), dict):
            reasons.append("handoff evaluation parsed answers are required")
