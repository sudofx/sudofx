"""Portable, sanitized packet exports for the Handoff application."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sudofx.kernel import Kernel
from sudofx.storage import GENESIS_HASH, canonical_json

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
_MANUAL_RECENT_RESULT_LIMIT = 1


def build_handoff_packet(kernel: Kernel, work_id: str = HANDOFF_WORK_ID) -> dict[str, Any]:
    """Build one portable view from generic governed work state."""
    context = kernel.context(work_id=work_id, receipt_limit=100)
    work_key = f"work:{work_id}"
    work = context.state.get(work_key)
    if not isinstance(work, dict):
        raise ValueError(f"work item does not exist: {work_id}")

    projected_work = {field: work[field] for field in _ALLOWED_WORK_FIELDS if field in work}
    accepted_results = projected_work.pop("accepted_results", [])
    if not isinstance(accepted_results, list) or not all(isinstance(result, str) for result in accepted_results):
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
    body["packet_digest"] = hashlib.sha256(canonical_json(body).encode()).hexdigest()
    return body


def build_manual_prompt(packet: dict[str, Any]) -> str:
    return (
        "SUDOFX MANUAL CONTINUITY TEST\n"
        "You are a fresh intelligence with no prior conversation, memory, files, tools, or hidden context.\n"
        "Use only the bounded durable packet below. Treat digests as unreadable commitments, not readable history.\n"
        "Do not claim you performed work or inspected anything outside the packet.\n\n"
        "TRANSPORT METADATA\n"
        "vendor: __SUDOFX_VENDOR__\n"
        "test_id: __SUDOFX_TEST_ID__\n"
        "nonce: __SUDOFX_NONCE__\n"
        f"work_id: {packet['work_id']}\n"
        f"packet_digest: {packet['packet_digest']}\n\n"
        "Return only one JSON object. Do not use Markdown fences or add prose before or after it.\n"
        "The object must contain exactly these top-level fields: test_id, nonce, vendor, work_id, packet_digest, answers.\n"
        "Copy the transport metadata above exactly into those fields.\n"
        "answers must contain exactly: objective_fidelity, authority_fidelity, history_fidelity, constraint_fidelity, frontier_fidelity, epistemic_discipline, transfer_usability.\n"
        "Each answer must be an object with non-empty answer and evidence fields.\n"
        "Every evidence value must be an exact quote of at least 8 characters from the COMPLETE JSON PACKET below.\n"
        "If the packet does not support a claim, say that in answer and quote packet text that establishes the limit.\n\n"
        "COMPLETE JSON PACKET\n"
        + json.dumps(packet, indent=2, sort_keys=True)
    )


def export_handoff_packet(kernel: Kernel, directory: str | Path, work_id: str = HANDOFF_WORK_ID) -> tuple[Path, Path]:
    """Write replaceable packet views; SQLite remains authority."""
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
        "Return: objective, recovered_history, current_frontier, next_action, evidence_vs_inference.\n\n"
        + json.dumps(packet, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return json_path, prompt_path
