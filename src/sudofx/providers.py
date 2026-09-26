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

import json
import subprocess
from collections.abc import Callable, Iterable, Sequence
from typing import Protocol

from .models import Context, Operation, Proposal


class ProviderError(RuntimeError):
    """
    Report failure before a valid proposal crosses into the kernel.

    Provider failure is not governed rejection: there is no complete proposal
    to evaluate or preserve as a receipt. Callers may retry after inspecting the
    external process, but must not invent a durable proposal on its behalf.
    """


def _proposal_from_json(raw: str) -> Proposal:
    """
    Convert provider JSON into the narrow, provider-neutral proposal contract.

    This parser validates transport shape, not permission. An operation can be
    well-formed here and still be rejected by Governance for staleness, an
    unsupported action, lifecycle state, or another deterministic rule.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProviderError(f"provider returned invalid JSON: {error.msg}") from error
    if not isinstance(data, dict):
        raise ProviderError("provider response must be a JSON object")

    proposal_id = data.get("proposal_id")
    revision = data.get("based_on_revision")
    operations = data.get("operations")
    rationale = data.get("rationale", "")
    if not isinstance(proposal_id, str):
        raise ProviderError("proposal_id must be a string")
    if not isinstance(revision, int) or isinstance(revision, bool):
        raise ProviderError("based_on_revision must be an integer")
    if not isinstance(operations, list):
        raise ProviderError("operations must be a JSON array")
    if not isinstance(rationale, str):
        raise ProviderError("rationale must be a string")

    parsed: list[Operation] = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ProviderError(f"operation {index} must be a JSON object")
        action = operation.get("action")
        key = operation.get("key")
        if not isinstance(action, str) or not isinstance(key, str):
            raise ProviderError(f"operation {index} requires string action and key")
        # Runtime input cannot be trusted merely because Operation's annotation
        # is a Literal. Governance performs the authoritative action check.
        parsed.append(Operation(action, key, operation.get("value")))  # type: ignore[arg-type]
    return Proposal(proposal_id, revision, tuple(parsed), rationale)


class Intelligence(Protocol):
    """Structural contract implemented by every disposable provider adapter."""
    def propose(self, context: Context) -> Proposal: ...


class CommandIntelligence:
    """
    Run one disposable external intelligence through a JSON process boundary.

    The command receives exactly one Context document on standard input and
    must return exactly one Proposal document on standard output. It receives
    no Record, Kernel, governance object, or mutation callback. ``shell=False``
    is intentional: executable identity and arguments remain explicit rather
    than becoming a second command language interpreted by a shell.

    A timeout, nonzero exit, undecodable output, or malformed proposal raises
    ProviderError before Kernel.submit. Standard error is diagnostic only and
    is never copied into authoritative state or mistaken for rationale.
    """

    def __init__(self, command: Sequence[str], *, timeout_seconds: float = 60.0) -> None:
        if not command:
            raise ValueError("provider command must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def propose(self, context: Context) -> Proposal:
        """Execute one isolated request and parse its untrusted proposal output."""
        request = json.dumps(
            {
                "revision": context.revision,
                "state": context.state,
                "recent_receipts": context.recent_receipts,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            completed = subprocess.run(
                self.command,
                input=request,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProviderError(f"provider command failed before proposing: {error}") from error
        if completed.returncode != 0:
            detail = completed.stderr.strip() or f"exit status {completed.returncode}"
            raise ProviderError(f"provider command did not produce a proposal: {detail}")
        return _proposal_from_json(completed.stdout)


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
