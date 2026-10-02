"""Application service boundary for governed Handoff targets and evaluations."""

from __future__ import annotations

import uuid

from sudofx import (
    ApplicationHost,
    ApplicationIntent,
    ApplicationRegistry,
    Kernel,
    SubmissionProvenance,
)
from sudofx.models import JsonValue

from .application import HANDOFF_APPLICATION, evaluations_for_work


class HandoffService:
    """Coordinate generic work state with application-owned handoff evidence."""

    def __init__(self, kernel: Kernel, registry: ApplicationRegistry | None = None) -> None:
        self.kernel = kernel
        kernel_registry = kernel.governance.application_registry
        if registry is not None and registry is not kernel_registry:
            raise ValueError("handoff registry must be the kernel governance registry")
        self.registry = kernel_registry
        if self.registry.get(HANDOFF_APPLICATION.application_id) is None:
            self.registry.register(HANDOFF_APPLICATION)
        self.host = ApplicationHost(kernel, self.registry, HANDOFF_APPLICATION.application_id)

    def ensure_target(
        self,
        work_id: str,
        *,
        provenance: SubmissionProvenance | None = None,
    ) -> None:
        # Target registration is meaningful only for a real generic work item.
        scoped = self.kernel.context(work_id=work_id)
        if f"work:{work_id}" not in scoped.state:
            raise ValueError(f"work item does not exist: {work_id}")
        state = self.host.context().state
        targets = state.get("targets", {}) if isinstance(state, dict) else {}
        if isinstance(targets, dict) and work_id in targets:
            return
        receipt = self.host.submit(
            ApplicationIntent(
                proposal_id=str(uuid.uuid4()),
                based_on_revision=self.host.context().revision,
                action="register_target",
                payload={"work_id": work_id},
                rationale="Register governed work as a Handoff application target",
            ),
            provenance=provenance or SubmissionProvenance("runtime", "handoff", "application"),
        )
        if receipt.status != "accepted":
            raise RuntimeError(f"handoff target registration was {receipt.status}: {receipt.reasons}")

    def record_evaluation(
        self,
        work_id: str,
        evaluation: dict[str, JsonValue],
        *,
        provenance: SubmissionProvenance | None = None,
    ):
        self.ensure_target(work_id, provenance=provenance)
        context = self.host.context()
        receipt = self.host.submit(
            ApplicationIntent(
                proposal_id=str(uuid.uuid4()),
                based_on_revision=context.revision,
                action="record_evaluation",
                payload={"work_id": work_id, "evaluation": evaluation},
                rationale="Record one deterministic Handoff grounding evaluation",
            ),
            provenance=provenance or SubmissionProvenance("human", "operator", "handoff"),
        )
        if receipt.status != "accepted":
            raise RuntimeError(f"handoff evaluation was {receipt.status}: {receipt.reasons}")
        return receipt

    def evaluations(self, work_id: str, *, include_legacy: bool = True) -> list[dict[str, JsonValue]]:
        current = evaluations_for_work(self.host.context().state, work_id)
        if not include_legacy:
            return current
        # Compatibility only: historical pre-application handoff evaluations
        # remain inside legacy work projections so old SQLite history replays.
        work = self.kernel.context().state.get(f"work:{work_id}", {})
        legacy = work.get("handoff_evaluations", []) if isinstance(work, dict) else []
        legacy_clean = [dict(item) for item in legacy if isinstance(item, dict)] if isinstance(legacy, list) else []
        legacy_ids = {str(item.get("test_id", "")) for item in legacy_clean if str(item.get("test_id", ""))}
        return [*legacy_clean, *(item for item in current if str(item.get("test_id", "")) not in legacy_ids)]


def build_manual_evaluation_projection(
    kernel: Kernel,
    work_id: str,
    registry: ApplicationRegistry | None = None,
) -> dict[str, object]:
    """Project compact handoff evidence from application state plus legacy compatibility."""
    evaluations = HandoffService(kernel, registry).evaluations(work_id)
    clean = [item for item in evaluations if isinstance(item, dict)]
    latest = clean[-1] if clean else None
    comparable: list[dict[str, object]] = []
    if latest is not None:
        digest = latest.get("packet_digest")
        scorer = latest.get("scorer_version")
        comparable = [
            item for item in clean
            if item.get("packet_digest") == digest and item.get("scorer_version") == scorer
        ]
    vendors = sorted({
        str(item.get("vendor", "")).strip()
        for item in comparable
        if str(item.get("vendor", "")).strip()
    })
    score = sum(int(item.get("score", 0)) for item in comparable if isinstance(item.get("score"), int))
    recent = [
        {
            "vendor": item.get("vendor", ""),
            "test_id": item.get("test_id", ""),
            "score": item.get("score", 0),
            "scorer_version": item.get("scorer_version"),
            "packet_digest": item.get("packet_digest", ""),
        }
        for item in clean[-8:]
    ]
    return {
        "projection_schema": 2,
        "projection_kind": "disposable-handoff-application-view",
        "record_revision": kernel.context().revision,
        "application_id": HANDOFF_APPLICATION.application_id,
        "work_id": work_id,
        "total_tests": len(clean),
        "latest": {
            "vendor": latest.get("vendor", ""),
            "test_id": latest.get("test_id", ""),
            "score": latest.get("score", 0),
            "scorer_version": latest.get("scorer_version"),
            "packet_digest": latest.get("packet_digest", ""),
        } if latest is not None else None,
        "comparable_batch": {
            "tests": len(comparable),
            "vendors": vendors,
            "score": score,
            "max_score": len(comparable) * 7,
            "packet_digest": latest.get("packet_digest", "") if latest is not None else "",
            "scorer_version": latest.get("scorer_version") if latest is not None else None,
        },
        "recent": recent,
    }
