"""Value objects crossing the sudofx kernel boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True)
class Operation:
    action: Literal["set", "delete", "create_work", "advance_work", "complete_work"]
    key: str
    value: JsonValue = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"action": self.action, "key": self.key}
        if self.action != "delete":
            data["value"] = self.value
        return data


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    based_on_revision: int
    operations: tuple[Operation, ...]
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "based_on_revision": self.based_on_revision,
            "operations": [operation.to_dict() for operation in self.operations],
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class Context:
    revision: int
    state: dict[str, JsonValue]
    recent_receipts: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    proposal_id: str
    status: Literal["accepted", "rejected"]
    revision_before: int
    revision_after: int
    reasons: tuple[str, ...]
    event_hash: str


@dataclass(frozen=True)
class GovernanceDecision:
    accepted: bool
    reasons: tuple[str, ...] = ()
