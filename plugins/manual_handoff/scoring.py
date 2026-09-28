"""Normalize and score human-transported manual handoff evaluation responses.

The scorer proves freshness, packet identity, response shape, and explicit
packet-grounding. It deliberately does not claim that string checks establish
semantic truth: each answer must cite exact packet text, while later human or
model review may judge whether the interpretation is actually faithful.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from sudofx.storage import canonical_json


DIMENSIONS = (
    "objective_fidelity",
    "authority_fidelity",
    "history_fidelity",
    "constraint_fidelity",
    "frontier_fidelity",
    "epistemic_discipline",
    "transfer_usability",
)


def parse_handoff_response(raw_response: str) -> dict[str, Any]:
    """Parse one response while tolerating consumer-chat transport decoration."""
    # Consumer chat surfaces sometimes typography-substitute JSON quotes even
    # when explicitly asked for machine output, and some wrap the object in a
    # Markdown fence. Normalize only those transport decorations; malformed
    # structure, missing fields, and packet mismatches still fail closed.
    candidate = raw_response.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
    candidate = candidate.replace("\u201c", '"').replace("\u201d", '"')
    try:
        response = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise ValueError("handoff response must be one JSON object") from error
    if not isinstance(response, dict):
        raise ValueError("handoff response must be one JSON object")

    return response


def handoff_packet_digest(raw_response: str) -> str:
    """Read the frozen-packet identity before resolving its durable snapshot."""
    response = parse_handoff_response(raw_response)
    digest = response.get("packet_digest")
    if not isinstance(digest, str) or not digest:
        raise ValueError("handoff response is missing transport metadata")
    return digest


def evaluate_handoff_response(raw_response: str, packet: dict[str, Any]) -> dict[str, Any]:
    """Return a governance-ready result or reject stale/unparseable transport.

    A pass means the answer is non-empty and cites a literal fragment from the
    frozen packet. This is a reproducible grounding score, not an LLM-as-judge
    semantic score. Packet and nonce checks keep accidental response reuse from
    being recorded as evidence for the current test.
    """
    response = parse_handoff_response(raw_response)

    required = ("test_id", "nonce", "vendor", "packet_digest", "answers")
    if any(key not in response for key in required):
        raise ValueError("handoff response is missing transport metadata")
    if response["packet_digest"] != packet.get("packet_digest"):
        raise ValueError("handoff response belongs to a different packet")
    # Apple's cross-platform Shortcuts action set can generate a random number
    # everywhere, while a UUID action is not consistently offered on both OSes.
    # A six-digit per-launch ID is sufficient to catch accidental answer reuse;
    # the packet digest supplies the stronger frozen-packet binding.
    if not isinstance(response["test_id"], str) or not re.fullmatch(r"UUID-[0-9]{6}", response["test_id"]):
        raise ValueError("handoff test_id must use the Shortcut UUID-NNNNNN form")
    if not isinstance(response["nonce"], str) or not re.fullmatch(r"HANDOFF-UUID-[0-9]{6}", response["nonce"]):
        raise ValueError("handoff nonce is invalid")
    if not isinstance(response["vendor"], str) or not response["vendor"].strip():
        raise ValueError("handoff vendor is required")

    answers = response["answers"]
    if not isinstance(answers, dict):
        raise ValueError("handoff answers must be an object")
    packet_text = canonical_json(packet)
    criteria: dict[str, str] = {}
    normalized_answers: dict[str, dict[str, str]] = {}
    for dimension in DIMENSIONS:
        answer = answers.get(dimension)
        valid = isinstance(answer, dict)
        text = answer.get("answer", "") if valid else ""
        evidence = answer.get("evidence", "") if valid else ""
        passed = (
            isinstance(text, str) and bool(text.strip())
            and isinstance(evidence, str) and len(evidence.strip()) >= 8
            and evidence.strip() in packet_text
        )
        criteria[dimension] = "pass" if passed else "fail"
        normalized_answers[dimension] = {
            "answer": text.strip() if isinstance(text, str) else "",
            "evidence": evidence.strip() if isinstance(evidence, str) else "",
        }

    return {
        "test_id": response["test_id"],
        "nonce": response["nonce"],
        "vendor": response["vendor"].strip(),
        "packet_digest": response["packet_digest"],
        "raw_response": raw_response,
        "answers": normalized_answers,
        "criteria": criteria,
        "score": sum(result == "pass" for result in criteria.values()),
        "score_kind": "deterministic packet-grounding; semantic review remains separate",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
