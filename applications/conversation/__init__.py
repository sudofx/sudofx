"""Conversation application package.

This package owns Conversation-specific semantics and execution adapters.
sudofx remains the authority substrate; importing this package grants no power.
"""

from .application import (
    APPLICATION_ID,
    APPLICATION_VERSION,
    CONVERSATION_APPLICATION,
    DEFAULT_CONTEXT_TURNS,
    MAX_MESSAGE_CHARS,
    assistant_message,
    bounded_context,
    human_message,
)

__all__ = [
    "APPLICATION_ID",
    "APPLICATION_VERSION",
    "CONVERSATION_APPLICATION",
    "DEFAULT_CONTEXT_TURNS",
    "MAX_MESSAGE_CHARS",
    "assistant_message",
    "bounded_context",
    "human_message",
]
