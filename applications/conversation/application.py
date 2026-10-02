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
        }
    if not isinstance(current, dict):
        raise ValueError("conversation state must be an object")
    raw = current.get("privacy")
    if raw is None:
        return {
            "turn_count": 0,
            "next_role": "human",
            "observations": [],
        }
    if not isinstance(raw, dict):
        raise ValueError("conversation privacy state must be an object")
    turn_count = raw.get("turn_count")
    next_role = raw.get("next_role")
    observations = raw.get("observations")
    if not isinstance(turn_count, int) or turn_count < 0:
        raise ValueError("conversation privacy turn count is invalid")
    if next_role not in {"human", "assistant"}:
        raise ValueError("conversation privacy next role is invalid")
    if not isinstance(observations, list) or any(not isinstance(item, str) for item in observations):
        raise ValueError("conversation privacy observations are invalid")
    return {
        "turn_count": turn_count,
        "next_role": next_role,
        "observations": list(observations),
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
    }


def private_assistant_descriptor(
    response: str,
    observations: object,
) -> dict[str, JsonValue]:
    """Build safe durable assistant metadata after provider output validation."""
    if not isinstance(response, str) or not response.strip():
        raise ValueError("assistant response must be non-empty text")
    content = response.strip()
    normalized, error = _normalize_observations(observations)
    if error is not None:
        raise ValueError(error)
    return {
        "message_digest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "message_chars": len(content),
        "observations": normalized,
    }
