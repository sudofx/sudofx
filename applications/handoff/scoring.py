"""Deterministic packet-grounding scorer for human-transported Handoff responses."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .application import DIMENSIONS


def parse_handoff_response(raw_response: str) -> dict[str, Any]:
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
    response = parse_handoff_response(raw_response)
    digest = response.get("packet_digest")
    if not isinstance(digest, str) or not digest:
        raise ValueError("handoff response is missing transport metadata")
    return digest


def handoff_work_id(raw_response: str) -> str:
    response = parse_handoff_response(raw_response)
    work_id = response.get("work_id")
    if not isinstance(work_id, str) or not work_id.strip():
        raise ValueError("handoff response is missing work_id")
    return work_id.strip()


def evaluate_handoff_response(raw_response: str, packet: dict[str, Any]) -> dict[str, Any]:
    response = parse_handoff_response(raw_response)
    required = ("test_id", "nonce", "vendor", "work_id", "packet_digest", "answers")
    if any(key not in response for key in required):
        raise ValueError("handoff response is missing transport metadata")
    if response["packet_digest"] != packet.get("packet_digest"):
        raise ValueError("handoff response belongs to a different packet")
    if response["work_id"] != packet.get("work_id"):
        raise ValueError("handoff response belongs to a different work item")
    if not isinstance(response["test_id"], str) or not re.fullmatch(r"UUID-[0-9]{6}", response["test_id"]):
        raise ValueError("handoff test_id must use the Shortcut UUID-NNNNNN form")
    if not isinstance(response["nonce"], str) or not re.fullmatch(r"HANDOFF-UUID-[0-9]{6}", response["nonce"]):
        raise ValueError("handoff nonce is invalid")
    if not isinstance(response["vendor"], str) or not response["vendor"].strip():
        raise ValueError("handoff vendor is required")

    answers = response["answers"]
    if not isinstance(answers, dict):
        raise ValueError("handoff answers must be an object")
    packet_text = json.dumps(packet, indent=2, sort_keys=True, ensure_ascii=False)
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
        "work_id": response["work_id"],
        "packet_digest": response["packet_digest"],
        "raw_response": raw_response,
        "answers": normalized_answers,
        "criteria": criteria,
        "score": sum(result == "pass" for result in criteria.values()),
        "scorer_version": 2,
        "score_kind": "deterministic packet-grounding against visible COMPLETE JSON PACKET; semantic review remains separate",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
