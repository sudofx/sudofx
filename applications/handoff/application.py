"""Deterministic domain semantics for the sudofx Handoff application."""

from __future__ import annotations

from sudofx import ApplicationAction, ApplicationDecision, ApplicationDefinition
from sudofx.models import JsonValue

APPLICATION_ID = "handoff"
APPLICATION_VERSION = "1"

DIMENSIONS = (
    "objective_fidelity",
    "authority_fidelity",
    "history_fidelity",
    "constraint_fidelity",
    "frontier_fidelity",
    "epistemic_discipline",
    "transfer_usability",
)


def _state(current: JsonValue) -> dict[str, JsonValue]:
    if current is None:
        return {"targets": {}}
    if not isinstance(current, dict):
        raise ValueError("handoff state must be an object")
    targets = current.get("targets", {})
    if not isinstance(targets, dict):
        raise ValueError("handoff targets must be an object")
    return {"targets": dict(targets)}


def _valid_work_id(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value.strip()) <= 200


def _validate_evaluation(value: object) -> str | None:
    if not isinstance(value, dict):
        return "handoff evaluation must be an object"
    required_text = {
        "test_id", "nonce", "vendor", "work_id", "packet_digest",
        "raw_response", "submitted_at", "score_kind",
    }
    if any(not isinstance(value.get(key), str) or not value[key].strip() for key in required_text):
        return "handoff evaluation identity, provenance, response, and timestamp are required"
    criteria = value.get("criteria")
    if (
        not isinstance(criteria, dict)
        or set(criteria) != set(DIMENSIONS)
        or any(result not in {"pass", "fail"} for result in criteria.values())
    ):
        return "handoff evaluation criteria must contain all seven pass/fail dimensions"
    score = value.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= len(DIMENSIONS):
        return "handoff evaluation score must be an integer from zero through seven"
    if not isinstance(value.get("answers"), dict):
        return "handoff evaluation parsed answers are required"
    scorer_version = value.get("scorer_version")
    if isinstance(scorer_version, bool) or not isinstance(scorer_version, int) or scorer_version < 1:
        return "handoff evaluation scorer_version must be a positive integer"
    return None


def register_target(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    if not isinstance(payload, dict) or not _valid_work_id(payload.get("work_id")):
        return ApplicationDecision(False, reasons=("handoff target requires a valid work_id",))
    work_id = str(payload["work_id"]).strip()
    try:
        state = _state(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))
    targets = dict(state["targets"])
    if work_id in targets:
        return ApplicationDecision(False, reasons=(f"handoff target already exists: {work_id}",))
    targets[work_id] = {"work_id": work_id, "evaluations": []}
    state["targets"] = targets
    return ApplicationDecision(True, state)


def record_evaluation(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    if not isinstance(payload, dict):
        return ApplicationDecision(False, reasons=("record_evaluation requires an object",))
    work_id = payload.get("work_id")
    evaluation = payload.get("evaluation")
    if not _valid_work_id(work_id):
        return ApplicationDecision(False, reasons=("record_evaluation requires a valid work_id",))
    error = _validate_evaluation(evaluation)
    if error is not None:
        return ApplicationDecision(False, reasons=(error,))
    assert isinstance(work_id, str)
    assert isinstance(evaluation, dict)
    if evaluation.get("work_id") != work_id:
        return ApplicationDecision(False, reasons=("handoff evaluation work_id does not match target",))
    try:
        state = _state(current)
    except ValueError as state_error:
        return ApplicationDecision(False, reasons=(str(state_error),))
    targets = dict(state["targets"])
    target = targets.get(work_id)
    if not isinstance(target, dict):
        return ApplicationDecision(False, reasons=(f"handoff target does not exist: {work_id}",))
    evaluations = target.get("evaluations", [])
    if not isinstance(evaluations, list):
        return ApplicationDecision(False, reasons=("handoff target evaluations are invalid",))
    test_id = evaluation.get("test_id")
    if any(isinstance(item, dict) and item.get("test_id") == test_id for item in evaluations):
        return ApplicationDecision(False, reasons=(f"handoff evaluation already recorded: {test_id}",))
    updated_target = dict(target)
    updated_target["evaluations"] = [*evaluations, dict(evaluation)]
    targets[work_id] = updated_target
    state["targets"] = targets
    return ApplicationDecision(True, state)


def evaluations_for_work(state: JsonValue, work_id: str) -> list[dict[str, JsonValue]]:
    """Return application-owned evaluations for one target."""
    normalized = _state(state)
    target = normalized["targets"].get(work_id)
    if not isinstance(target, dict):
        return []
    evaluations = target.get("evaluations", [])
    if not isinstance(evaluations, list):
        return []
    return [dict(item) for item in evaluations if isinstance(item, dict)]


HANDOFF_APPLICATION = ApplicationDefinition(
    APPLICATION_ID,
    APPLICATION_VERSION,
    (
        ApplicationAction("register_target", register_target),
        ApplicationAction("record_evaluation", record_evaluation),
    ),
    state_storage="event_log",
)
