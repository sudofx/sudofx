"""Portable, sanitized handoff exports for fresh-intelligence tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .kernel import Kernel
from .storage import GENESIS_HASH, canonical_json


HANDOFF_VERSION = 1
HANDOFF_WORK_ID = "handoff-v1"

_ALLOWED_WORK_FIELDS = (
    "id",
    "status",
    "objective",
    "constraints",
    "accepted_results",
    "open_obligations",
    "work_revision",
)

# Manual transport must not quietly receive more semantic evidence than the
# automated Gemini baseline. One accepted milestone and no receipt prose are
# the promoted provider-facing policy; counts and digests disclose omissions.
_MANUAL_RECENT_RESULT_LIMIT = 1


def build_handoff_packet(kernel: Kernel, work_id: str = HANDOFF_WORK_ID) -> dict[str, Any]:
    """Build a portable packet from one governed work item only.

    The export is deliberately narrower than Kernel context. It excludes unrelated
    state and strips lifecycle fields that are not explicitly allowlisted here.
    Content is not magically de-identified: the dedicated work item itself must
    contain only material the operator intends to export.
    """
    context = kernel.context(work_id=work_id, receipt_limit=100)
    work_key = f"work:{work_id}"
    work = context.state.get(work_key)
    if not isinstance(work, dict):
        raise ValueError(f"work item does not exist: {work_id}")

    projected_work = {
        field: work[field]
        for field in _ALLOWED_WORK_FIELDS
        if field in work
    }
    accepted_results = projected_work.pop("accepted_results", [])
    if not isinstance(accepted_results, list) or not all(
        isinstance(result, str) for result in accepted_results
    ):
        raise ValueError("work item has invalid accepted results")
    recent_results = accepted_results[-_MANUAL_RECENT_RESULT_LIMIT:]
    omitted_results = accepted_results[:-_MANUAL_RECENT_RESULT_LIMIT]
    projected_work["accepted_results_recent"] = recent_results
    projected_work["accepted_result_count"] = len(accepted_results)
    projected_work["omitted_accepted_results_count"] = len(omitted_results)
    projected_work["omitted_accepted_results_digest"] = hashlib.sha256(
        canonical_json(omitted_results).encode()
    ).hexdigest()

    history = kernel.record.history()
    source_event_head = history[-1]["event_hash"] if history else GENESIS_HASH
    body = {
        "handoff_version": HANDOFF_VERSION,
        "work_id": work_id,
        "record_revision": context.revision,
        "source_event_head": source_event_head,
        "work": projected_work,
        # A human may carry this packet, but that does not expand the provider's
        # evidence. Source head and packet digest retain provenance without
        # exposing receipt prose that Gemini did not receive.
        "receipt_provenance": [],
        "instructions": {
            "assumption": "You have no prior conversation or hidden project context.",
            "task": (
                "Reconstruct the current objective, summarize what has already happened, "
                "identify the current frontier, and propose exactly one next action."
            ),
            "grounding_rule": (
                "Use only this packet. Distinguish packet evidence from inference, "
                "treat digests as unreadable commitments, and do not invent omitted history."
            ),
        },
    }
    digest_payload = dict(body)
    digest_payload.pop("packet_digest", None)
    body["packet_digest"] = hashlib.sha256(
        canonical_json(digest_payload).encode()
    ).hexdigest()
    return body


def export_handoff_packet(
    kernel: Kernel,
    directory: str | Path,
    work_id: str = HANDOFF_WORK_ID,
) -> tuple[Path, Path]:
    """Write replaceable handoff views; authoritative state remains in the database."""
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    packet = build_handoff_packet(kernel, work_id)
    json_path = destination / "handoff-v1.json"
    prompt_path = destination / "handoff-v1.txt"
    json_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    prompt_path.write_text(
        "SUDOFX_HANDOFF v1\n"
        "You are a fresh intelligence. Do not assume any prior conversation.\n"
        "Use only the JSON packet below.\n"
        "Return: objective, recovered_history, current_frontier, next_action, "
        "evidence_vs_inference.\n\n"
        + json.dumps(packet, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return json_path, prompt_path
