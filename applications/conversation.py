"""
MINIMAL CONVERSATION APPLICATION
================================

This is the first human interaction proof for the sudofx application contract.
It owns conversation-domain meaning while the kernel continues to own durable
authority, governance, replay, provenance, and receipts.
"""

from __future__ import annotations

import hashlib

from sudofx import ApplicationAction, ApplicationDecision, ApplicationDefinition
from sudofx.models import JsonValue
from sudofx.storage import canonical_json


APPLICATION_ID = "conversation"
APPLICATION_VERSION = "1"


def _messages(current: JsonValue) -> list[dict[str, JsonValue]]:
    if current is None:
        return []
    if not isinstance(current, dict):
        raise ValueError("conversation state must be an object")
    messages = current.get("messages", [])
    if not isinstance(messages, list) or not all(isinstance(item, dict) for item in messages):
        raise ValueError("conversation messages must be objects")
    return [dict(item) for item in messages]


def _human_message(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    if not isinstance(payload, str) or not payload.strip():
        return ApplicationDecision(False, reasons=("human message must be non-empty text",))
    try:
        messages = _messages(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))
    messages.append({"role": "human", "text": payload.strip()})
    return ApplicationDecision(True, {"messages": messages})


def _assistant_message(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    if not isinstance(payload, dict):
        return ApplicationDecision(False, reasons=("assistant message requires an object",))
    required = ("text", "provider", "model", "context_digest")
    if any(not isinstance(payload.get(key), str) or not payload[key].strip() for key in required):
        return ApplicationDecision(
            False,
            reasons=("assistant message requires text, provider, model, and context_digest",),
        )
    try:
        messages = _messages(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))
    messages.append(
        {
            "role": "assistant",
            "text": payload["text"].strip(),
            "provider": payload["provider"].strip(),
            "model": payload["model"].strip(),
            "context_digest": payload["context_digest"].strip(),
        }
    )
    return ApplicationDecision(True, {"messages": messages})


def definition() -> ApplicationDefinition:
    """Return one immutable application definition for registry installation."""
    return ApplicationDefinition(
        APPLICATION_ID,
        APPLICATION_VERSION,
        (
            ApplicationAction("human_message", _human_message),
            ApplicationAction("assistant_message", _assistant_message),
        ),
    )


def bounded_context(state: JsonValue, *, message_limit: int = 12) -> dict[str, JsonValue]:
    """Build the exact bounded conversation view supplied to one fresh provider."""
    if message_limit < 1:
        raise ValueError("message_limit must be positive")
    messages = _messages(state)
    recent = messages[-message_limit:]
    omitted = messages[:-message_limit]
    return {
        "application_id": APPLICATION_ID,
        "application_version": APPLICATION_VERSION,
        "messages_recent": recent,
        "message_count": len(messages),
        "omitted_message_count": len(omitted),
        "omitted_messages_digest": hashlib.sha256(canonical_json(omitted).encode()).hexdigest(),
    }


def context_digest(context: dict[str, JsonValue]) -> str:
    """Fingerprint the exact bounded context shown to one provider."""
    return hashlib.sha256(canonical_json(context).encode()).hexdigest()
