"""Governed Conversation application semantics and bounded provider projection."""

from __future__ import annotations

import hashlib
import json

from sudofx import ApplicationAction, ApplicationDecision, ApplicationDefinition
from sudofx.models import JsonValue


APPLICATION_ID = "conversation"
APPLICATION_VERSION = "1"
MAX_MESSAGE_CHARS = 4000
DEFAULT_CONTEXT_TURNS = 8


def _turns(current: JsonValue) -> list[dict[str, str]]:
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
    return ApplicationDecision(
        True,
        {
            "turns": updated,
            "turn_count": len(updated),
        },
    )


def human_message(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    return _message(current, payload, role="human")


def assistant_message(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    return _message(current, payload, role="assistant")


CONVERSATION_APPLICATION = ApplicationDefinition(
    APPLICATION_ID,
    APPLICATION_VERSION,
    (
        ApplicationAction("human_message", human_message),
        ApplicationAction("assistant_message", assistant_message),
    ),
)


def bounded_context(state: JsonValue, *, max_turns: int = DEFAULT_CONTEXT_TURNS) -> dict[str, JsonValue]:
    """Return a bounded provider view with explicit omission evidence."""
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
