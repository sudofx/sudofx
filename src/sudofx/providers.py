"""Replaceable intelligence boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from .models import Context, Proposal


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
