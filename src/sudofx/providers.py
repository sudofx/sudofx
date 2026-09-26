"""
REPLACEABLE INTELLIGENCE BOUNDARY
=================================

Providers receive bounded Context and return untrusted Proposal. They never
receive a database connection, governance object, transition callback, or other
capability that can mutate authoritative state.

The Protocol is intentionally tiny so real model vendors and deterministic test
providers cross the same boundary. Provider substitution should alter proposal
quality or metadata, not persistence, governance, replay, or receipts.

The fake implementations are product evidence, not toys. They remove model
behavior as a variable while proving that continuity comes from the record. A
fresh fake instance can continue work because Context contains the durable
facts; no instance retains a conversation or private scratch state.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from .models import Context, Operation, Proposal


class Intelligence(Protocol):
    """Structural contract implemented by every disposable provider adapter."""
    def propose(self, context: Context) -> Proposal: ...


class FakeIntelligence:
    """
    Return predetermined or context-derived proposals deterministically.

    Iterable mode is useful for exact fixtures. Callable mode demonstrates that
    a fresh invocation can derive its next proposal solely from supplied context.
    Exhausting iterable mode raises StopIteration before submission and therefore
    creates no misleading receipt.
    """

    def __init__(self, proposals: Iterable[Proposal] | Callable[[Context], Proposal]) -> None:
        self._factory = proposals if callable(proposals) else None
        self._proposals = None if callable(proposals) else iter(proposals)

    def propose(self, context: Context) -> Proposal:
        """Produce exactly one proposal without mutating context or durable state."""
        if self._factory is not None:
            return self._factory(context)
        assert self._proposals is not None
        return next(self._proposals)


class FakeWorkIntelligence:
    """
    Model one fresh invocation that advances a named durable work item.

    Proposal identity includes the global revision, which makes separate fresh
    invocations deterministic for a given state while avoiding collisions as
    accepted work advances. Production adapters should use stronger globally
    unique request identity but preserve the same proposal boundary.
    """

    def __init__(self, work_id: str, result: str, *, open_obligations: Iterable[str] = ()) -> None:
        self.work_id = work_id
        self.result = result
        self.open_obligations = tuple(open_obligations)

    def propose(self, context: Context) -> Proposal:
        """Translate configured progress into one governed advance operation."""
        return Proposal(
            proposal_id=f"fake-{self.work_id}-{context.revision}",
            based_on_revision=context.revision,
            operations=(
                Operation(
                    "advance_work",
                    self.work_id,
                    {"result": self.result, "open_obligations": list(self.open_obligations)},
                ),
            ),
            rationale="Deterministic work advance",
        )
