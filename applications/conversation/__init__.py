"""Conversation application package.

This package owns Conversation-specific semantics and execution adapters.
sudofx remains the authority substrate; importing this package grants no power.
"""

from .application import (
    APPLICATION_ID,
    APPLICATION_VERSION,
    CONVERSATION_APPLICATION,
    DEFAULT_CONTEXT_TURNS,
    MAX_DURABLE_OBSERVATIONS,
    MAX_MESSAGE_CHARS,
    MAX_OBSERVATION_CHARS,
    MAX_OBSERVATIONS_PER_TURN,
    assistant_message,
    bounded_context,
    human_message,
    private_assistant_descriptor,
    private_assistant_message,
    private_bounded_context,
    private_human_message,
    private_message_descriptor,
    validate_private_message,
)

__all__ = [
    "APPLICATION_ID",
    "APPLICATION_VERSION",
    "CONVERSATION_APPLICATION",
    "DEFAULT_CONTEXT_TURNS",
    "MAX_DURABLE_OBSERVATIONS",
    "MAX_MESSAGE_CHARS",
    "MAX_OBSERVATION_CHARS",
    "MAX_OBSERVATIONS_PER_TURN",
    "assistant_message",
    "bounded_context",
    "human_message",
    "private_assistant_descriptor",
    "private_assistant_message",
    "private_bounded_context",
    "private_human_message",
    "private_message_descriptor",
    "validate_private_message",
]
