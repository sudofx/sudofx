"""
GENERIC APPLICATION OBSERVABILITY
=================================

This module projects already-durable sudofx evidence into a bounded,
application-oriented view suitable for diagnostics and presentation.

It does not add telemetry events, mutate the record, register applications, or
create a second source of truth. A deployment may discard and regenerate the
result at any time from its authoritative Record.

The implementation deliberately understands only generic sudofx contracts:
application envelopes, governed apply_application operations, and
application-scoped invocation lifecycle evidence. Domain meaning remains owned
by the application.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Protocol


PROJECTION_SCHEMA = 1
PROJECTION_KIND = "sudofx-application-observability"


class ObservableRecord(Protocol):
    """Small backend-neutral read surface required by observability."""

    def full_replay(self) -> tuple[int, dict[str, Any]]: ...

    def history(self) -> tuple[dict[str, Any], ...]: ...

    def invocation_history(
        self, invocation_id: str | None = None
    ) -> tuple[dict[str, Any], ...]: ...


def _application_operation(operation: Any) -> tuple[str, str] | None:
    """
    Return generic application identity/action without exposing the action input.

    The durable operation already passed kernel governance. Observability uses
    only its stable envelope metadata and never copies next_state, input, or
    projection_state into the public-safe projection.
    """
    if not isinstance(operation, dict) or operation.get("action") != "apply_application":
        return None
    application_id = operation.get("key")
    value = operation.get("value")
    if not isinstance(application_id, str) or not isinstance(value, dict):
        return None
    action = value.get("action")
    if not isinstance(action, str) or not action:
        return None
    return application_id, action


def _invocation_application(event: dict[str, Any]) -> str | None:
    """
    Resolve application scope from the structured context-delivery receipt.

    Invocation IDs are intentionally not interpreted. The durable scope receipt
    is the evidence that one runtime boundary belonged to an application.
    """
    receipt = event.get("context_receipt")
    if not isinstance(receipt, dict):
        return None
    scope = receipt.get("scope")
    if not isinstance(scope, dict) or scope.get("kind") != "application":
        return None
    application_id = scope.get("application_id")
    return application_id if isinstance(application_id, str) and application_id else None


def build_application_observability(
    record: ObservableRecord,
    *,
    recent_actions: int = 12,
    recent_invocations: int = 8,
) -> dict[str, Any]:
    """
    Build a bounded generic view of application use from authoritative evidence.

    Inputs are verified read contracts only. The function performs no mutation
    and emits no arbitrary state or proposal payloads. Counts cover complete
    verified history; recent lists are independently bounded for browser use.
    """
    revision, state = record.full_replay()
    semantic_history = record.history()
    invocation_history = record.invocation_history()

    applications: dict[str, dict[str, Any]] = {}

    # Current envelopes establish installed/durable identity without requiring
    # application code to be present in this process.
    for key, envelope in state.items():
        if not isinstance(key, str) or not key.startswith("app:") or not isinstance(envelope, dict):
            continue
        application_id = key.removeprefix("app:")
        applications[application_id] = {
            "id": application_id,
            "version": envelope.get("application_version"),
            "storage": envelope.get("storage", "snapshot"),
            "actions": {
                "accepted": 0,
                "rejected": 0,
                "recent": [],
            },
            "invocations": {
                "total": 0,
                "attempts": 0,
                "completed": 0,
                "failed": 0,
                "quota_exhausted": 0,
                "temporary_failures": 0,
                "provider_failures": 0,
                "effect_barrier_failures": 0,
                "recent": [],
            },
        }

    # Governed proposal history proves how applications used the semantic
    # authority boundary. Only action names and outcomes leave this helper.
    for receipt in semantic_history:
        proposal = receipt.get("proposal", {})
        operations = proposal.get("operations", []) if isinstance(proposal, dict) else []
        for operation in operations if isinstance(operations, list) else []:
            parsed = _application_operation(operation)
            if parsed is None:
                continue
            application_id, action = parsed
            app = applications.setdefault(
                application_id,
                {
                    "id": application_id,
                    "version": (
                        operation.get("value", {}).get("application_version")
                        if isinstance(operation.get("value"), dict)
                        else None
                    ),
                    "storage": (
                        operation.get("value", {}).get("storage", "snapshot")
                        if isinstance(operation.get("value"), dict)
                        else "snapshot"
                    ),
                    "actions": {"accepted": 0, "rejected": 0, "recent": []},
                    "invocations": {
                        "total": 0,
                        "attempts": 0,
                        "completed": 0,
                        "failed": 0,
                        "quota_exhausted": 0,
                        "temporary_failures": 0,
                        "provider_failures": 0,
                        "effect_barrier_failures": 0,
                        "recent": [],
                    },
                },
            )
            status = str(receipt.get("status", "rejected"))
            if status == "accepted":
                app["actions"]["accepted"] += 1
            else:
                app["actions"]["rejected"] += 1
            app["actions"]["recent"].append(
                {
                    "action": action,
                    "status": status,
                    "revision_before": receipt.get("revision_before"),
                    "revision_after": receipt.get("revision_after"),
                    "created_at": receipt.get("created_at"),
                }
            )

    for app in applications.values():
        app["actions"]["recent"] = app["actions"]["recent"][-max(0, recent_actions):]

    # Scope may be recorded only on context_delivered. Discover the application
    # for an invocation first, then associate the complete lifecycle with it.
    invocation_to_application: dict[str, str] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in invocation_history:
        invocation_id = event.get("invocation_id")
        if not isinstance(invocation_id, str) or not invocation_id:
            continue
        grouped[invocation_id].append(event)
        application_id = _invocation_application(event)
        if application_id is not None:
            invocation_to_application[invocation_id] = application_id

    by_application: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for invocation_id, events in grouped.items():
        application_id = invocation_to_application.get(invocation_id)
        if application_id is None:
            continue

        app = applications.setdefault(
            application_id,
            {
                "id": application_id,
                "version": None,
                "storage": None,
                "actions": {"accepted": 0, "rejected": 0, "recent": []},
                "invocations": {
                    "total": 0,
                    "attempts": 0,
                    "completed": 0,
                    "failed": 0,
                    "quota_exhausted": 0,
                    "temporary_failures": 0,
                    "provider_failures": 0,
                    "effect_barrier_failures": 0,
                    "recent": [],
                },
            },
        )
        metrics = app["invocations"]
        metrics["total"] += 1
        metrics["attempts"] += sum(event.get("stage") == "attempt_started" for event in events)
        metrics["completed"] += int(any(event.get("stage") == "completed" for event in events))
        metrics["failed"] += int(any(event.get("stage") == "failed" for event in events))

        outcomes = [event.get("outcome") for event in events if event.get("outcome")]
        metrics["quota_exhausted"] += int("quota_exhausted" in outcomes)
        metrics["temporary_failures"] += int("temporary_failure" in outcomes)
        metrics["provider_failures"] += int("provider_failure" in outcomes)
        metrics["effect_barrier_failures"] += int("effect_barrier_failure" in outcomes)

        context_event = next(
            (event for event in events if _invocation_application(event) == application_id),
            None,
        )
        context_receipt = (
            context_event.get("context_receipt")
            if isinstance(context_event, dict)
            and isinstance(context_event.get("context_receipt"), dict)
            else {}
        )
        last = events[-1]
        by_application[application_id].append(
            {
                "invocation_id": invocation_id,
                "source_revision": events[0].get("source_revision"),
                "stages": [event.get("stage") for event in events],
                "latest_stage": last.get("stage"),
                "outcome": next(
                    (event.get("outcome") for event in reversed(events) if event.get("outcome")),
                    None,
                ),
                "started_at": events[0].get("created_at"),
                "updated_at": last.get("created_at"),
                "context": {
                    "policy_version": context_receipt.get("policy_version"),
                    "payload_bytes": context_receipt.get("payload_bytes"),
                    "included_categories": context_receipt.get("included_categories", []),
                },
            }
        )

    for application_id, invocations in by_application.items():
        applications[application_id]["invocations"]["recent"] = invocations[
            -max(0, recent_invocations):
        ]

    return {
        "projection_schema": PROJECTION_SCHEMA,
        "projection_kind": PROJECTION_KIND,
        "authoritative": False,
        "generated": datetime.now(timezone.utc).isoformat(),
        "record_revision": revision,
        "applications": [
            applications[application_id]
            for application_id in sorted(applications)
        ],
    }
