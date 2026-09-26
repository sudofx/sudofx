"""
SUDOFX BOUNDARY VALUES
======================

This module defines the small vocabulary allowed to cross the kernel's trust
boundaries. The classes here do not perform work, consult providers, govern
proposals, or mutate the record. They make the shape of those handoffs explicit.

That restraint matters because sudofx is designed around replaceable
intelligence. A provider can disappear immediately after producing a Proposal.
The durable system must still know exactly what was proposed, which record
revision informed it, and how to describe the resulting receipt without relying
on provider-local memory or Python object identity.

The value objects intentionally remain plain frozen dataclasses:

    Context  -> bounded evidence supplied to an intelligence
    Proposal -> untrusted requested operations
    Decision -> deterministic governance result
    Receipt  -> durable evidence of acceptance or rejection

They are frozen so later code cannot quietly rewrite a proposal or receipt after
it has crossed a boundary. Freezing is not a security sandbox; callers can still
place mutable JSON containers inside a value. The durable protection comes from
canonical serialization inside one SQLite transaction. The dataclasses provide
legibility and discourage accidental mutation before that point.

JSON is the interchange substrate because proposals and state must survive
process, language, and provider replacement. Do not add arbitrary Python
objects, datetime instances, callbacks, database handles, or provider SDK types
to these contracts. If a value cannot be serialized and replayed deterministically,
it does not belong in authoritative state.

Operation is deliberately generic at the transport layer while its action names
remain governed. Adding a Literal here does not authorize the action. Governance
must validate it and replay must define its exact state transition. Those three
owners must move together or the record could accept behavior it cannot rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

# JsonValue is recursive by design. Durable work may contain structured lists
# and objects, but every leaf remains provider-neutral JSON. This alias is a
# documentation and static-analysis boundary; runtime shape enforcement belongs
# to governance because only governance knows the semantic purpose of a field.


@dataclass(frozen=True)
class Operation:
    """
    Describe one requested state transition without performing it.

    ``action`` selects a transition owned jointly by governance and replay.
    ``key`` identifies either a generic state key or a durable work item.
    ``value`` carries only the structured input needed by that transition.

    Operations are not commands with authority. A provider, CLI, or browser may
    construct one freely; nothing changes until Kernel.submit evaluates the
    complete Proposal and appends one accepted or rejected event atomically.
    """
    action: Literal["set", "delete", "create_work", "advance_work", "complete_work"]
    key: str
    value: JsonValue = None

    def to_dict(self) -> dict[str, Any]:
        """
        Project the operation into its canonical JSON-facing representation.

        Delete omits ``value`` because absence is part of that action's stable
        contract. Other actions retain the value even when it is JSON null so
        governance can distinguish malformed input from a missing field during
        audit and rejection analysis.
        """
        data: dict[str, Any] = {"action": self.action, "key": self.key}
        if self.action != "delete":
            data["value"] = self.value
        return data


@dataclass(frozen=True)
class Proposal:
    """
    Carry an intelligence's complete, untrusted suggestion.

    ``proposal_id`` provides replay/idempotency identity. ``based_on_revision``
    is optimistic concurrency control: governance rejects a proposal reasoned
    from stale state instead of allowing it to overwrite newer accepted work.
    Operations are a tuple so their requested order cannot drift accidentally.

    ``rationale`` is provenance for humans and later invocations. It never
    grants permission and governance must not become more permissive because a
    rationale sounds persuasive.
    """
    proposal_id: str
    based_on_revision: int
    operations: tuple[Operation, ...]
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the exact structure hashed into an event and replayed later."""
        return {
            "proposal_id": self.proposal_id,
            "based_on_revision": self.based_on_revision,
            "operations": [operation.to_dict() for operation in self.operations],
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class Context:
    """
    Represent one bounded working view derived from the durable record.

    The global revision remains present even for work-scoped contexts because a
    proposal must be rejected when any accepted transition made its source view
    stale. ``recent_receipts`` is evidence, not an alternate state store.
    """
    revision: int
    state: dict[str, JsonValue]
    recent_receipts: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Receipt:
    """
    Report what the durable system actually recorded.

    Accepted receipts advance the global revision; rejected receipts preserve
    the same revision while still extending the append-only evidence chain.
    ``event_hash`` lets callers anchor the receipt to the verified record.
    """
    receipt_id: str
    proposal_id: str
    status: Literal["accepted", "rejected"]
    revision_before: int
    revision_after: int
    reasons: tuple[str, ...]
    event_hash: str


@dataclass(frozen=True)
class GovernanceDecision:
    """
    Separate deterministic permission from mutation.

    Governance returns all mechanically discoverable rejection reasons so a
    fresh invocation can correct its proposal. The decision contains no mutated
    state; replay remains the sole owner of accepted transition semantics.
    """
    accepted: bool
    reasons: tuple[str, ...] = ()
