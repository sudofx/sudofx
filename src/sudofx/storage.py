"""
SUDOFX STORAGE CONTRACT
=======================

This module defines the persistence boundary consumed by the kernel. The
contract describes semantic transactions, verified replay, durable append, and
proposal identity without naming SQLite, SQL, files, branches, or any future
database technology.

SQLite is the first implementation because it is simple and local. It is not
the product contract. A PostgreSQL or other durable backend should be able to
replace it by implementing these interfaces while preserving event semantics.

Hashing also lives here because event identity must remain backend-independent.
A storage implementation may choose different physical tables or transaction
primitives, but it must not silently invent a different semantic event chain.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, ContextManager, Literal, Protocol

from .models import JsonValue

GENESIS_HASH = "0" * 64

# The genesis value is deliberately fixed and obvious. It is a chain sentinel,
# not a secret, signature, or proof of authorship.


def canonical_json(value: Any) -> str:
    """
    Serialize semantic event material identically across storage backends.

    Sorted keys and compact separators remove incidental dictionary and
    whitespace differences from the durable hash contract.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_event(previous_hash: str, event: dict[str, Any]) -> str:
    """
    Bind one semantic event to the verified event immediately before it.

    This detects chain mutation during replay. It does not authenticate the
    writer; a separately authenticated/notarized layer would be needed for that.
    """
    material = f"{previous_hash}\n{canonical_json(event)}".encode()
    return hashlib.sha256(material).hexdigest()


@dataclass(frozen=True)
class EventAppend:
    """
    Carry one complete governed event across the storage boundary.

    Physical sequence numbers, timestamps, row IDs, and backend metadata are
    intentionally absent. Those may vary by implementation without changing
    the semantic record that fresh intelligences reconstruct.
    """
    receipt_id: str
    proposal_id: str
    status: Literal["accepted", "rejected"]
    revision_before: int
    revision_after: int
    payload: dict[str, Any]
    reasons: tuple[str, ...]
    previous_hash: str
    event_hash: str


class ReadTransaction(Protocol):
    """
    Snapshot-consistent read surface required by Kernel.context.

    Replay and receipt evidence must observe the same logical snapshot so a
    provider is never given state from one revision and receipts from another.
    """

    def replay(self) -> tuple[int, dict[str, JsonValue]]: ...

    def recent(self, limit: int = 10) -> tuple[dict[str, Any], ...]: ...


class WriteTransaction(ReadTransaction, Protocol):
    """
    Serialized mutation surface required by Kernel.submit.

    The backend owns isolation, commit, rollback, and duplicate enforcement.
    Kernel owns sequencing and governance but never receives a native connection.
    """

    def proposal_exists(self, proposal_id: str) -> bool: ...

    def head_hash(self) -> str: ...

    def append(self, event: EventAppend) -> None: ...


class RecordStore(Protocol):
    """
    Backend-independent authoritative record contract.

    Implementations may differ physically, but a successful write context must
    atomically cover replay -> identity check -> governance -> append. Escaping
    with an exception must publish none of that attempted mutation.
    """

    def read_transaction(self) -> ContextManager[ReadTransaction]: ...

    def write_transaction(self) -> ContextManager[WriteTransaction]: ...

    def history(self) -> tuple[dict[str, Any], ...]: ...

    def projection_snapshot(
        self, history_limit: int = 50
    ) -> tuple[
        int,
        dict[str, JsonValue],
        tuple[dict[str, Any], ...],
        dict[str, int | float | str],
    ]:
        """
        Return one verified state/history/health view for bounded presentation.

        Backends choose their snapshot mechanism. The result is derived evidence,
        not a mutation surface or permission for presentation to become authority.
        """
