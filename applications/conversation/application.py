"""Governed Conversation application semantics and privacy-bounded projections."""

from __future__ import annotations

import hashlib
import json
import re

from sudofx import ApplicationAction, ApplicationDecision, ApplicationDefinition
from sudofx.models import JsonValue


APPLICATION_ID = "conversation"
APPLICATION_VERSION = "1"
MAX_MESSAGE_CHARS = 4000
DEFAULT_CONTEXT_TURNS = 8

# Privacy-preserving runtime state is intentionally not a transcript.  These
# limits keep durable observations bounded while still allowing continuity to
# accumulate over many fresh provider invocations.
MAX_OBSERVATION_CHARS = 240
MAX_OBSERVATIONS_PER_TURN = 4
MAX_DURABLE_OBSERVATIONS = 32
MAX_ACTIVE_COMMITMENTS = 8
MAX_COMMITMENT_CHARS = 240

_DIRECT_IDENTIFIER_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"\bhttps?://\S+\b", re.I),
    re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:my name is|i am named|call me|i live at|my address is)\b", re.I),
)


def _turns(current: JsonValue) -> list[dict[str, str]]:
    """Legacy transcript state used only by the original continuity proof tests."""
    if current is None:
        return []
    if not isinstance(current, dict):
        raise ValueError("conversation state must be an object")
    turns = current.get("turns", [])
    if not isinstance(turns, list):
        raise ValueError("conversation turns must be a list")
    normalized: list[dict[str, str]] = []
    for turn in turns:
        if (
            not isinstance(turn, dict)
            or turn.get("role") not in {"human", "assistant"}
            or not isinstance(turn.get("content"), str)
        ):
            raise ValueError("conversation contains an invalid turn")
        normalized.append({"role": turn["role"], "content": turn["content"]})
    return normalized


def _message(current: JsonValue, payload: JsonValue, *, role: str) -> ApplicationDecision:
    """Legacy transcript action retained so historical proof semantics still replay."""
    if not isinstance(payload, str) or not payload.strip():
        return ApplicationDecision(False, reasons=(f"{role} message must be non-empty text",))
    content = payload.strip()
    if len(content) > MAX_MESSAGE_CHARS:
        return ApplicationDecision(
            False,
            reasons=(f"{role} message exceeds {MAX_MESSAGE_CHARS} characters",),
        )
    try:
        turns = _turns(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))
    expected = "human" if not turns or turns[-1]["role"] == "assistant" else "assistant"
    if role != expected:
        return ApplicationDecision(
            False,
            reasons=(f"conversation expects {expected} message next",),
        )
    updated = [*turns, {"role": role, "content": content}]
    state = dict(current) if isinstance(current, dict) else {}
    state.update({"turns": updated, "turn_count": len(updated)})
    return ApplicationDecision(True, state)


def human_message(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    return _message(current, payload, role="human")


def assistant_message(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    return _message(current, payload, role="assistant")


def validate_private_message(message: str) -> str:
    """Validate one transient message before it may cross the provider boundary.

    The guard deliberately rejects obvious direct identifiers instead of trying
    to pretend that heuristic redaction is perfect.  The current message remains
    transient even after validation; only a digest and character count may be
    committed to authoritative state.
    """
    if not isinstance(message, str) or not message.strip():
        raise ValueError("conversation message must be non-empty text")
    content = message.strip()
    if len(content) > MAX_MESSAGE_CHARS:
        raise ValueError(f"conversation message exceeds {MAX_MESSAGE_CHARS} characters")
    for pattern in _DIRECT_IDENTIFIER_PATTERNS:
        if pattern.search(content):
            raise ValueError(
                "conversation message contains a direct identifier; remove identifying information"
            )
    return content


def private_message_descriptor(message: str) -> dict[str, JsonValue]:
    """Return durable evidence about a message without persisting its contents."""
    content = validate_private_message(message)
    return {
        "message_digest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "message_chars": len(content),
    }


def _privacy_state(current: JsonValue) -> dict[str, JsonValue]:
    if current is None:
        return {
            "turn_count": 0,
            "next_role": "human",
            "observations": [],
            "commitments": [],
        }
    if not isinstance(current, dict):
        raise ValueError("conversation state must be an object")
    raw = current.get("privacy")
    if raw is None:
        return {
            "turn_count": 0,
            "next_role": "human",
            "observations": [],
            "commitments": [],
        }
    if not isinstance(raw, dict):
        raise ValueError("conversation privacy state must be an object")
    turn_count = raw.get("turn_count")
    next_role = raw.get("next_role")
    observations = raw.get("observations")
    commitments = raw.get("commitments", [])
    if not isinstance(turn_count, int) or turn_count < 0:
        raise ValueError("conversation privacy turn count is invalid")
    if next_role not in {"human", "assistant"}:
        raise ValueError("conversation privacy next role is invalid")
    if not isinstance(observations, list) or any(not isinstance(item, str) for item in observations):
        raise ValueError("conversation privacy observations are invalid")
    if not isinstance(commitments, list):
        raise ValueError("conversation privacy commitments are invalid")
    normalized_commitments: list[dict[str, str]] = []
    for commitment in commitments:
        if (
            not isinstance(commitment, dict)
            or commitment.get("kind") != "response_suffix"
            or not isinstance(commitment.get("text"), str)
            or not commitment["text"].strip()
        ):
            raise ValueError("conversation privacy commitments are invalid")
        normalized = {"kind": "response_suffix", "text": commitment["text"]}
        source_proposal_id = commitment.get("source_proposal_id")
        if source_proposal_id is not None:
            if (
                not isinstance(source_proposal_id, str)
                or not source_proposal_id.strip()
                or len(source_proposal_id) > 128
            ):
                raise ValueError("conversation commitment source proposal id is invalid")
            normalized["source_proposal_id"] = source_proposal_id.strip()
        normalized_commitments.append(normalized)
    return {
        "turn_count": turn_count,
        "next_role": next_role,
        "observations": list(observations),
        "commitments": normalized_commitments,
    }


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def private_human_message(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    """Commit only metadata for one human turn; the message body stays transient."""
    if not isinstance(payload, dict):
        return ApplicationDecision(False, reasons=("private human message metadata must be an object",))
    if not _valid_digest(payload.get("message_digest")):
        return ApplicationDecision(False, reasons=("private human message digest is invalid",))
    message_chars = payload.get("message_chars")
    if not isinstance(message_chars, int) or not (1 <= message_chars <= MAX_MESSAGE_CHARS):
        return ApplicationDecision(False, reasons=("private human message length is invalid",))
    try:
        privacy = _privacy_state(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))
    if privacy["next_role"] != "human":
        return ApplicationDecision(False, reasons=("conversation expects assistant message next",))
    state = dict(current) if isinstance(current, dict) else {}
    state["privacy"] = {
        **privacy,
        "turn_count": int(privacy["turn_count"]) + 1,
        "next_role": "assistant",
        "last_human": {
            "message_digest": payload["message_digest"],
            "message_chars": message_chars,
        },
    }
    return ApplicationDecision(True, state)


def _normalize_observations(values: object) -> tuple[list[str], str | None]:
    if not isinstance(values, list):
        return [], "assistant observations must be a list"
    if len(values) > MAX_OBSERVATIONS_PER_TURN:
        return [], f"assistant may add at most {MAX_OBSERVATIONS_PER_TURN} observations"
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            return [], "assistant observations must be non-empty text"
        text = " ".join(value.split())
        if len(text) > MAX_OBSERVATION_CHARS:
            return [], f"assistant observation exceeds {MAX_OBSERVATION_CHARS} characters"
        for pattern in _DIRECT_IDENTIFIER_PATTERNS:
            if pattern.search(text):
                return [], "assistant observation contains a direct identifier"
        normalized.append(text)
    return normalized, None


def _normalize_commitment_updates(
    values: object,
    *,
    source_proposal_id: str | None = None,
) -> tuple[list[dict[str, str]], str | None]:
    if not isinstance(values, list):
        return [], "assistant commitment updates must be a list"
    if len(values) > 2:
        return [], "assistant may propose at most 2 commitment updates per turn"
    normalized: list[dict[str, str]] = []
    for value in values:
        if not isinstance(value, dict):
            return [], "assistant commitment update must be an object"
        op = value.get("op")
        kind = value.get("kind")
        if kind != "response_suffix" or op not in {"upsert", "clear"}:
            return [], "assistant commitment update is invalid"
        if op == "clear":
            normalized.append({"op": "clear", "kind": "response_suffix"})
            continue
        text = value.get("text")
        if not isinstance(text, str) or not text.strip():
            return [], "assistant response suffix commitment must contain text"
        text = text.strip()
        if len(text) > MAX_COMMITMENT_CHARS:
            return [], f"assistant commitment exceeds {MAX_COMMITMENT_CHARS} characters"
        for pattern in _DIRECT_IDENTIFIER_PATTERNS:
            if pattern.search(text):
                return [], "assistant commitment contains a direct identifier"
        item = {"op": "upsert", "kind": "response_suffix", "text": text}
        if source_proposal_id is not None:
            if not source_proposal_id.strip() or len(source_proposal_id) > 128:
                return [], "assistant commitment source proposal id is invalid"
            item["source_proposal_id"] = source_proposal_id.strip()
        normalized.append(item)
    return normalized, None


def _apply_commitment_updates(
    commitments: list[dict[str, str]],
    updates: list[dict[str, str]],
) -> list[dict[str, str]]:
    active = [dict(item) for item in commitments]
    for update in updates:
        if update["op"] == "clear":
            active = [item for item in active if item["kind"] != update["kind"]]
            continue
        active = [item for item in active if item["kind"] != update["kind"]]
        item = {"kind": update["kind"], "text": update["text"]}
        if "source_proposal_id" in update:
            item["source_proposal_id"] = update["source_proposal_id"]
        active.append(item)
    return active[-MAX_ACTIVE_COMMITMENTS:]


def enforce_response_commitments(
    current: JsonValue,
    response: str,
    commitment_updates: object,
) -> str:
    """Deterministically enforce active/new response obligations on transient output."""
    privacy = _privacy_state(current)
    updates, error = _normalize_commitment_updates(commitment_updates)
    if error is not None:
        raise ValueError(error)
    commitments = _apply_commitment_updates(
        [dict(item) for item in privacy["commitments"]],
        updates,
    )
    content = response.strip()
    for commitment in commitments:
        if commitment["kind"] == "response_suffix":
            suffix = commitment["text"]
            if not content.endswith(suffix):
                content = content.rstrip() + "\n\n" + suffix
    return content


def private_governance_rejection(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    """Close one governed rejection without misclassifying it as provider failure."""
    if not isinstance(payload, dict):
        return ApplicationDecision(False, reasons=("private governance rejection metadata must be an object",))
    receipt_id = payload.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id.strip() or len(receipt_id) > 128:
        return ApplicationDecision(False, reasons=("private governance rejection receipt id is invalid",))
    try:
        privacy = _privacy_state(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))
    if privacy["next_role"] != "assistant":
        return ApplicationDecision(False, reasons=("conversation has no pending assistant turn",))
    state = dict(current) if isinstance(current, dict) else {}
    state["privacy"] = {
        **privacy,
        "next_role": "human",
        "last_governance_rejection": {"receipt_id": receipt_id.strip()},
    }
    return ApplicationDecision(True, state)


def private_provider_failure(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    """Close one failed private provider turn without persisting transcript text."""
    if not isinstance(payload, dict):
        return ApplicationDecision(False, reasons=("private provider failure metadata must be an object",))
    category = payload.get("category")
    if not isinstance(category, str) or not category.strip() or len(category) > 80:
        return ApplicationDecision(False, reasons=("private provider failure category is invalid",))
    try:
        privacy = _privacy_state(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))
    if privacy["next_role"] != "assistant":
        return ApplicationDecision(False, reasons=("conversation has no pending assistant turn",))
    state = dict(current) if isinstance(current, dict) else {}
    state["privacy"] = {
        **privacy,
        "next_role": "human",
        "last_provider_failure": {"category": category.strip()},
    }
    return ApplicationDecision(True, state)


def private_assistant_message(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    """Commit response metadata plus compact observations, never response text."""
    if not isinstance(payload, dict):
        return ApplicationDecision(False, reasons=("private assistant metadata must be an object",))
    if not _valid_digest(payload.get("message_digest")):
        return ApplicationDecision(False, reasons=("private assistant message digest is invalid",))
    message_chars = payload.get("message_chars")
    if not isinstance(message_chars, int) or message_chars <= 0:
        return ApplicationDecision(False, reasons=("private assistant message length is invalid",))
    observations, error = _normalize_observations(payload.get("observations", []))
    if error is not None:
        return ApplicationDecision(False, reasons=(error,))
    commitment_updates, commitment_error = _normalize_commitment_updates(
        payload.get("commitment_updates", [])
    )
    if commitment_error is not None:
        return ApplicationDecision(False, reasons=(commitment_error,))
    try:
        privacy = _privacy_state(current)
    except ValueError as state_error:
        return ApplicationDecision(False, reasons=(str(state_error),))
    if privacy["next_role"] != "assistant":
        return ApplicationDecision(False, reasons=("conversation expects human message next",))

    previous = [str(item) for item in privacy["observations"]]
    merged: list[str] = []
    for item in [*previous, *observations]:
        if item not in merged:
            merged.append(item)
    merged = merged[-MAX_DURABLE_OBSERVATIONS:]

    state = dict(current) if isinstance(current, dict) else {}
    state["privacy"] = {
        **privacy,
        "turn_count": int(privacy["turn_count"]) + 1,
        "next_role": "human",
        "observations": merged,
        "commitments": _apply_commitment_updates(
            [dict(item) for item in privacy["commitments"]],
            commitment_updates,
        ),
        "last_assistant": {
            "message_digest": payload["message_digest"],
            "message_chars": message_chars,
        },
    }
    return ApplicationDecision(True, state)


CONVERSATION_APPLICATION = ApplicationDefinition(
    APPLICATION_ID,
    APPLICATION_VERSION,
    (
        # Legacy transcript actions remain registered so existing authoritative
        # v1 proof events replay. Production/private runtime uses only the two
        # metadata actions below.
        ApplicationAction("human_message", human_message),
        ApplicationAction("assistant_message", assistant_message),
        ApplicationAction("private_human_message", private_human_message),
        ApplicationAction("private_assistant_message", private_assistant_message),
        ApplicationAction("private_governance_rejection", private_governance_rejection),
        ApplicationAction("private_provider_failure", private_provider_failure),
    ),
)


def bounded_context(state: JsonValue, *, max_turns: int = DEFAULT_CONTEXT_TURNS) -> dict[str, JsonValue]:
    """Legacy bounded transcript projection retained for historical proof tests."""
    if max_turns <= 0:
        raise ValueError("max_turns must be positive")
    turns = _turns(state)
    omitted = turns[:-max_turns] if len(turns) > max_turns else []
    recent = turns[-max_turns:]
    digest = hashlib.sha256(
        json.dumps(omitted, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return {
        "application_id": APPLICATION_ID,
        "application_version": APPLICATION_VERSION,
        "turns": recent,
        "turn_count": len(turns),
        "omitted_turn_count": len(omitted),
        "omitted_turns_digest": digest,
    }


def private_bounded_context(state: JsonValue) -> dict[str, JsonValue]:
    """Return only durable continuity observations, never prior transcript text."""
    privacy = _privacy_state(state)
    observations = [str(item) for item in privacy["observations"]]
    return {
        "application_id": APPLICATION_ID,
        "application_version": APPLICATION_VERSION,
        "turn_count": privacy["turn_count"],
        "next_role": privacy["next_role"],
        "observations": observations,
        "observation_count": len(observations),
        "active_commitments": [dict(item) for item in privacy["commitments"]],
        "active_commitment_count": len(privacy["commitments"]),
    }


def private_assistant_descriptor(
    response: str,
    observations: object,
    commitment_updates: object = (),
    *,
    source_proposal_id: str | None = None,
) -> dict[str, JsonValue]:
    """Build safe durable assistant metadata after provider output validation."""
    if not isinstance(response, str) or not response.strip():
        raise ValueError("assistant response must be non-empty text")
    content = response.strip()
    normalized, error = _normalize_observations(observations)
    if error is not None:
        raise ValueError(error)
    normalized_updates, update_error = _normalize_commitment_updates(
        list(commitment_updates),
        source_proposal_id=source_proposal_id,
    )
    if update_error is not None:
        raise ValueError(update_error)
    return {
        "message_digest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "message_chars": len(content),
        "observations": normalized,
        "commitment_updates": normalized_updates,
    }
