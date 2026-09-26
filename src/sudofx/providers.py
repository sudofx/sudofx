"""Replaceable intelligence boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from .models import Context, Operation, Proposal


class Intelligence(Protocol):
    def propose(self, context: Context) -> Proposal: ...


class FakeIntelligence:
    """Deterministic provider used to prove the kernel without model behavior."""

    def __init__(self, proposals: Iterable[Proposal] | Callable[[Context], Proposal]) -> None:
        self._factory = proposals if callable(proposals) else None
        self._proposals = None if callable(proposals) else iter(proposals)

    def propose(self, context: Context) -> Proposal:
        if self._factory is not None:
            return self._factory(context)
        assert self._proposals is not None
        return next(self._proposals)


class FakeWorkIntelligence:
    """A fresh deterministic invocation that advances one durable work item."""

    def __init__(self, work_id: str, result: str, *, open_obligations: Iterable[str] = ()) -> None:
        self.work_id = work_id
        self.result = result
        self.open_obligations = tuple(open_obligations)

    def propose(self, context: Context) -> Proposal:
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
