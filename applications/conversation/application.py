"""Governed Conversation application semantics and privacy-bounded projections."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from urllib.parse import parse_qsl, urlsplit

from sudofx import (
    ApplicationAction,
    ApplicationDecision,
    ApplicationDefinition,
    continuity_matrix,
)
from sudofx.models import JsonValue


APPLICATION_ID = "conversation"
APPLICATION_VERSION = "1"
MAX_MESSAGE_CHARS = 10000
DEFAULT_CONTEXT_TURNS = 8

# Privacy-preserving runtime state is intentionally not a transcript.  These
# limits keep durable observations bounded while still allowing continuity to
# accumulate over many fresh provider invocations.
MAX_OBSERVATION_CHARS = 240
MAX_OBSERVATIONS_PER_TURN = 4
MAX_DURABLE_OBSERVATIONS = 32
MAX_ACTIVE_COMMITMENTS = 8
MAX_COMMITMENT_CHARS = 240
RESPONSE_SUFFIX_PLACEMENTS = {"end", "new_line"}
COMMITMENT_KINDS = {
    "response_suffix",
    "follow_up_question",
    "response_instruction",
}

_DIRECT_IDENTIFIER_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:my name is|i am named|call me|i live at|my address is)\b", re.I),
)

_URL_PATTERN = re.compile(r"https?://[^\s<>\]\[{}]+", re.I)
_SENSITIVE_QUERY_KEYS = {"access_token", "api_key", "auth", "key", "secret", "token"}
_SEARCH_INTENT_PATTERNS = (
    re.compile(r"\b(?:search|browse)\s+(?:the\s+)?(?:web|internet)\b", re.I),
    re.compile(r"\bsearch\s+(?:online\s+)?for\b", re.I),
    re.compile(r"\blook\s+(?:it|this|that|them)\s+up\b", re.I),
    re.compile(r"\bfind\s+(?:it|this|that|information)\s+online\b", re.I),
)


def public_urls(message: str) -> tuple[str, ...]:
    """Return validated public HTTPS URLs explicitly present in one turn.

    Conversation delegates retrieval to a managed read-only provider tool, but
    application policy still rejects local/private targets and credential-like
    URL components before the message crosses that boundary. DNS resolution is
    intentionally not performed here: the app never fetches these URLs itself,
    and the managed URL tool independently blocks private-network retrieval.
    """
    urls: list[str] = []
    for match in _URL_PATTERN.finditer(message):
        candidate = match.group(0).rstrip(".,;:!?\"')")
        parsed = urlsplit(candidate)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ValueError("Conversation web access accepts public HTTPS URLs only")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Conversation URLs must not contain credentials")
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
            raise ValueError("Conversation cannot access local or private URLs")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("Conversation cannot access local or private URLs")
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
            if key.casefold() in _SENSITIVE_QUERY_KEYS:
                raise ValueError("Conversation URLs must not contain credential parameters")
        if candidate not in urls:
            urls.append(candidate)
        if len(urls) > 5:
            raise ValueError("Conversation accepts at most 5 public URLs per turn")
    return tuple(urls)


def conversation_web_tools(message: str) -> tuple[str, ...]:
    """Select bounded read-only web capabilities from explicit human intent."""
    urls = public_urls(message)
    tools: list[str] = []
    if urls:
        tools.append("read_public_url")
    if any(pattern.search(message) for pattern in _SEARCH_INTENT_PATTERNS):
        tools.append("search_public_web")
    return tuple(tools)


def _turns(current: JsonValue) -> list[dict[str, str]]:
    """Legacy transcript state used only by the original continuity proof tests."""
    if current is None:
        return []
    if not isinstance(current, dict):
        raise ValueError("conversation state must be an object")
    turns = current.get("turns", [])
    if not isinstance(turns, list):
        raise ValueError("conversation turns must be a list")
    normalized: list[dict[str, str]] = []
    for turn in turns:
        if (
            not isinstance(turn, dict)
            or turn.get("role") not in {"human", "assistant"}
            or not isinstance(turn.get("content"), str)
        ):
            raise ValueError("conversation contains an invalid turn")
        normalized.append({"role": turn["role"], "content": turn["content"]})
    return normalized


def _message(current: JsonValue, payload: JsonValue, *, role: str) -> ApplicationDecision:
    """Legacy transcript action retained so historical proof semantics still replay."""
    if not isinstance(payload, str) or not payload.strip():
        return ApplicationDecision(False, reasons=(f"{role} message must be non-empty text",))
    content = payload.strip()
    if len(content) > MAX_MESSAGE_CHARS:
        return ApplicationDecision(
            False,
            reasons=(f"{role} message exceeds {MAX_MESSAGE_CHARS} characters",),
        )
    try:
        turns = _turns(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))
    expected = "human" if not turns or turns[-1]["role"] == "assistant" else "assistant"
    if role != expected:
        return ApplicationDecision(
            False,
            reasons=(f"conversation expects {expected} message next",),
        )
    updated = [*turns, {"role": role, "content": content}]
    state = dict(current) if isinstance(current, dict) else {}
    state.update({"turns": updated, "turn_count": len(updated)})
    return ApplicationDecision(True, state)


def human_message(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    return _message(current, payload, role="human")


def assistant_message(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    return _message(current, payload, role="assistant")


def validate_private_message(message: str) -> str:
    """Validate one transient message before it may cross the provider boundary.

    The guard deliberately rejects obvious direct identifiers instead of trying
    to pretend that heuristic redaction is perfect.  The current message remains
    transient even after validation; only a digest and character count may be
    committed to authoritative state.
    """
    if not isinstance(message, str) or not message.strip():
        raise ValueError("conversation message must be non-empty text")
    content = message.strip()
    if len(content) > MAX_MESSAGE_CHARS:
        raise ValueError(f"conversation message exceeds {MAX_MESSAGE_CHARS} characters")
    for pattern in _DIRECT_IDENTIFIER_PATTERNS:
        if pattern.search(content):
            raise ValueError(
                "conversation message contains a direct identifier; remove identifying information"
            )
    # A URL is not inherently a personal identifier. Validate it as an
    # application capability target while continuing to reject identifiers in
    # ordinary prose and to exclude URLs from durable observations.
    public_urls(content)
    return content


def private_message_descriptor(message: str) -> dict[str, JsonValue]:
    """Return durable evidence about a message without persisting its contents."""
    content = validate_private_message(message)
    return {
        "message_digest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "message_chars": len(content),
    }


def _privacy_state(current: JsonValue) -> dict[str, JsonValue]:
    if current is None:
        return {
            "turn_count": 0,
            "next_role": "human",
            "observations": [],
            "verified_observations": [],
            "commitments": [],
        }
    if not isinstance(current, dict):
        raise ValueError("conversation state must be an object")
    raw = current.get("privacy")
    if raw is None:
        return {
            "turn_count": 0,
            "next_role": "human",
            "observations": [],
            "verified_observations": [],
            "commitments": [],
        }
    if not isinstance(raw, dict):
        raise ValueError("conversation privacy state must be an object")
    turn_count = raw.get("turn_count")
    next_role = raw.get("next_role")
    observations = raw.get("observations")
    verified_observations = raw.get("verified_observations", [])
    commitments = raw.get("commitments", [])
    last_human = raw.get("last_human")
    if not isinstance(turn_count, int) or turn_count < 0:
        raise ValueError("conversation privacy turn count is invalid")
    if next_role not in {"human", "assistant"}:
        raise ValueError("conversation privacy next role is invalid")
    if not isinstance(observations, list) or any(not isinstance(item, str) for item in observations):
        raise ValueError("conversation privacy observations are invalid")
    if not isinstance(verified_observations, list):
        raise ValueError("conversation verified observations are invalid")
    normalized_verified: list[dict[str, str]] = []
    for observation in verified_observations:
        if (
            not isinstance(observation, dict)
            or observation.get("support") != "exact_excerpt"
            or not isinstance(observation.get("text"), str)
            or not observation["text"].strip()
            or not _valid_digest(observation.get("source_message_digest"))
        ):
            raise ValueError("conversation verified observations are invalid")
        normalized_verified.append(
            {
                "text": " ".join(observation["text"].split()),
                "source_message_digest": observation["source_message_digest"],
                "support": "exact_excerpt",
            }
        )
    if not isinstance(commitments, list):
        raise ValueError("conversation privacy commitments are invalid")
    normalized_commitments: list[dict[str, str]] = []
    for commitment in commitments:
        if (
            not isinstance(commitment, dict)
            or commitment.get("kind") not in COMMITMENT_KINDS
            or not isinstance(commitment.get("text"), str)
            or not commitment["text"].strip()
        ):
            raise ValueError("conversation privacy commitments are invalid")
        kind = commitment["kind"]
        text = commitment["text"].strip()
        if len(text) > MAX_COMMITMENT_CHARS:
            raise ValueError("conversation commitment is too long")
        if kind in {"follow_up_question", "response_instruction"}:
            normalized_commitments.append({"kind": kind, "text": text})
            continue
        placement = commitment.get("placement", "end")
        if placement not in RESPONSE_SUFFIX_PLACEMENTS:
            raise ValueError("conversation response suffix placement is invalid")
        normalized = {
            "kind": kind,
            "text": text,
            "placement": placement,
        }
        normalized_commitments.append(normalized)
    normalized: dict[str, JsonValue] = {
        "turn_count": turn_count,
        "next_role": next_role,
        "observations": list(observations),
        "verified_observations": normalized_verified,
        "commitments": normalized_commitments,
    }
    # The current human-message digest is authority metadata, not transcript
    # content.  Verified observations must remain bound to that exact turn at
    # the commit boundary, so normalization may validate this field but must
    # not silently discard it before private_assistant_message compares it.
    if last_human is not None:
        if (
            not isinstance(last_human, dict)
            or not _valid_digest(last_human.get("message_digest"))
            or not isinstance(last_human.get("message_chars"), int)
            or not (1 <= last_human["message_chars"] <= MAX_MESSAGE_CHARS)
        ):
            raise ValueError("conversation last human message metadata is invalid")
        normalized["last_human"] = {
            "message_digest": last_human["message_digest"],
            "message_chars": last_human["message_chars"],
        }
    return normalized


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def private_human_message(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    """Commit only metadata for one human turn; the message body stays transient."""
    if not isinstance(payload, dict):
        return ApplicationDecision(False, reasons=("private human message metadata must be an object",))
    if not _valid_digest(payload.get("message_digest")):
        return ApplicationDecision(False, reasons=("private human message digest is invalid",))
    message_chars = payload.get("message_chars")
    if not isinstance(message_chars, int) or not (1 <= message_chars <= MAX_MESSAGE_CHARS):
        return ApplicationDecision(False, reasons=("private human message length is invalid",))
    try:
        privacy = _privacy_state(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))
    if privacy["next_role"] != "human":
        return ApplicationDecision(False, reasons=("conversation expects assistant message next",))
    state = dict(current) if isinstance(current, dict) else {}
    state["privacy"] = {
        **privacy,
        "turn_count": int(privacy["turn_count"]) + 1,
        "next_role": "assistant",
        "last_human": {
            "message_digest": payload["message_digest"],
            "message_chars": message_chars,
        },
    }
    return ApplicationDecision(True, state)


def _normalize_observations(
    values: object,
    *,
    allow_transient_urls: bool = False,
) -> tuple[list[str], str | None]:
    if not isinstance(values, list):
        return [], "assistant observations must be a list"
    if len(values) > MAX_OBSERVATIONS_PER_TURN:
        return [], f"assistant may add at most {MAX_OBSERVATIONS_PER_TURN} observations"
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            return [], "assistant observations must be non-empty text"
        text = " ".join(value.split())
        if len(text) > MAX_OBSERVATION_CHARS:
            return [], f"assistant observation exceeds {MAX_OBSERVATION_CHARS} characters"
        for pattern in _DIRECT_IDENTIFIER_PATTERNS:
            if pattern.search(text):
                return [], "assistant observation contains a direct identifier"
        if not allow_transient_urls and _URL_PATTERN.search(text):
            return [], "assistant observation must not persist a URL"
        normalized.append(text)
    return normalized, None


def _verified_observation_records(
    values: object,
    source_message: str,
) -> list[dict[str, str]]:
    """Keep only observations that are exact excerpts of the current human message."""
    # URL-bearing suggestions are valid untrusted provider output but are not
    # eligible for durable continuity. Drop them like any other unsupported
    # claim rather than failing the otherwise valid cited response.
    normalized, error = _normalize_observations(values, allow_transient_urls=True)
    if error is not None:
        raise ValueError(error)
    source = " ".join(validate_private_message(source_message).split())
    source_digest = hashlib.sha256(source_message.strip().encode("utf-8")).hexdigest()
    records: list[dict[str, str]] = []
    for text in normalized:
        if _URL_PATTERN.search(text):
            continue
        if text not in source:
            continue
        records.append(
            {
                "text": text,
                "source_message_digest": source_digest,
                "support": "exact_excerpt",
            }
        )
    return records


def _normalize_verified_observation_records(
    values: object,
) -> tuple[list[dict[str, str]], str | None]:
    if not isinstance(values, list):
        return [], "assistant verified observations must be a list"
    if len(values) > MAX_OBSERVATIONS_PER_TURN:
        return [], f"assistant may add at most {MAX_OBSERVATIONS_PER_TURN} verified observations"
    normalized: list[dict[str, str]] = []
    for value in values:
        if (
            not isinstance(value, dict)
            or value.get("support") != "exact_excerpt"
            or not isinstance(value.get("text"), str)
            or not value["text"].strip()
            or not _valid_digest(value.get("source_message_digest"))
        ):
            return [], "assistant verified observation is invalid"
        text = " ".join(value["text"].split())
        if len(text) > MAX_OBSERVATION_CHARS:
            return [], f"assistant observation exceeds {MAX_OBSERVATION_CHARS} characters"
        normalized.append(
            {
                "text": text,
                "source_message_digest": value["source_message_digest"],
                "support": "exact_excerpt",
            }
        )
    return normalized, None


def _normalize_commitment_updates(values: object) -> tuple[list[dict[str, str]], str | None]:
    if not isinstance(values, list):
        return [], "assistant commitment updates must be a list"
    if len(values) > 4:
        return [], "assistant may propose at most 4 commitment updates per turn"
    normalized: list[dict[str, str]] = []
    for value in values:
        if not isinstance(value, dict):
            return [], "assistant commitment update must be an object"
        op = value.get("op")
        kind = value.get("kind")
        if kind not in COMMITMENT_KINDS or op not in {"upsert", "clear"}:
            return [], "assistant commitment update is invalid"
        if op == "clear":
            item = {"op": "clear", "kind": kind}
            text = value.get("text")
            if text is not None:
                if not isinstance(text, str) or not text.strip():
                    return [], "assistant commitment clear target is invalid"
                item["text"] = text.strip()
            normalized.append(item)
            continue
        text = value.get("text")
        if not isinstance(text, str) or not text.strip():
            return [], "assistant commitment must contain text"
        text = text.strip()
        if len(text) > MAX_COMMITMENT_CHARS:
            return [], f"assistant commitment exceeds {MAX_COMMITMENT_CHARS} characters"
        for pattern in _DIRECT_IDENTIFIER_PATTERNS:
            if pattern.search(text):
                return [], "assistant commitment contains a direct identifier"
        if _URL_PATTERN.search(text):
            return [], "assistant commitment must not persist a URL"
        item: dict[str, str] = {
            "op": "upsert",
            "kind": kind,
            "text": text,
        }
        if kind == "response_suffix":
            placement = value.get("placement", "end")
            if placement not in RESPONSE_SUFFIX_PLACEMENTS:
                return [], "assistant response suffix placement is invalid"
            item["placement"] = placement
        normalized.append(item)
    return normalized, None


def grounded_commitment_updates(
    values: object,
    source_message: str,
) -> list[dict[str, str]]:
    """Keep only commitment creations literally authorized by this human turn.

    Clears may refer to already-governed commitments, but an upsert makes new
    durable instruction text authoritative. Requiring that text to be an exact
    excerpt prevents an untrusted provider from manufacturing persistent policy
    while still allowing it to structure explicit human directives.
    """
    normalized, error = _normalize_commitment_updates(values)
    if error is not None:
        raise ValueError(error)
    source = " ".join(validate_private_message(source_message).split())
    return [
        item
        for item in normalized
        if item["op"] == "clear" or item["text"] in source
    ]


def declared_commitment_updates(source_message: str) -> list[dict[str, str]]:
    """Parse the explicit Conversation init format without provider judgment.

    The init prompt is an operator-authored control surface, not ordinary prose:
    a ``following footer:`` block declares one exact suffix and each
    ``[DONT FORGET]`` bullet declares an independent semantic instruction.
    Parsing only those narrow markers avoids promoting casual requests while
    ensuring a disposable provider cannot silently omit explicit commitments.
    Returned text is copied from the validated message and therefore retains
    the same human-grounding invariant as provider-proposed updates.
    """
    source = validate_private_message(source_message)
    updates: list[dict[str, str]] = []

    footer_match = re.search(
        r"following footer:\s*\n+\s*([^\n]+?)\s*\n---(?:\n|$)",
        source,
        flags=re.IGNORECASE,
    )
    if footer_match is not None:
        updates.append(
            {
                "op": "upsert",
                "kind": "response_suffix",
                "text": footer_match.group(1).strip(),
                "placement": "new_line",
            }
        )

    for match in re.finditer(
        r"^\s*-\s*\[DONT FORGET\]\s*(.+?)\s*$",
        source,
        flags=re.IGNORECASE | re.MULTILINE,
    ):
        text = match.group(1).strip()
        if len(text) <= MAX_COMMITMENT_CHARS:
            # A recurring follow-up question has a small deterministic output
            # invariant, so give it a concrete kind instead of weakening it to
            # provider guidance. Other semantic obligations remain visible to
            # each fresh provider but cannot be fabricated by that provider.
            lowered = text.casefold()
            kind = (
                "follow_up_question"
                if "follow-up question" in lowered and "every response" in lowered
                else "response_instruction"
            )
            updates.append(
                {
                    "op": "upsert",
                    "kind": kind,
                    "text": text,
                }
            )

    normalized, error = _normalize_commitment_updates(updates[:4])
    if error is not None:
        raise ValueError(error)
    return normalized


def _apply_commitment_updates(
    commitments: list[dict[str, str]],
    updates: list[dict[str, str]],
) -> list[dict[str, str]]:
    active = [dict(item) for item in commitments]
    for update in updates:
        if update["op"] == "clear":
            clear_text = update.get("text")
            active = [
                item
                for item in active
                if not (
                    item["kind"] == update["kind"]
                    and (clear_text is None or item["text"] == clear_text)
                )
            ]
            continue
        if update["kind"] == "response_suffix":
            # Only one suffix can own the response ending. Semantic response
            # instructions are independent and therefore accumulate by text.
            active = [item for item in active if item["kind"] != update["kind"]]
        else:
            active = [
                item
                for item in active
                if not (item["kind"] == update["kind"] and item["text"] == update["text"])
            ]
        item = {
            "kind": update["kind"],
            "text": update["text"],
        }
        if update["kind"] == "response_suffix":
            item["placement"] = update.get("placement", "end")
        active.append(item)
    return active[-MAX_ACTIVE_COMMITMENTS:]


def enforce_response_commitments(
    current: JsonValue,
    response: str,
    commitment_updates: object,
) -> str:
    """Deterministically enforce active/new response obligations on transient output."""
    privacy = _privacy_state(current)
    updates, error = _normalize_commitment_updates(commitment_updates)
    if error is not None:
        raise ValueError(error)
    commitments = _apply_commitment_updates(
        [dict(item) for item in privacy["commitments"]],
        updates,
    )
    content = response.strip()

    # Provider instruction-following is useful but is not enforcement. When
    # the human explicitly requires a follow-up on every response, repair an
    # omitted question before applying any exact footer. The fallback is
    # intentionally generic because inventing a topical question would require
    # semantic authority the application does not possess.
    if any(item["kind"] == "follow_up_question" for item in commitments) and "?" not in content:
        content = content.rstrip() + "\n\nWhat would you like me to consider next?"

    for commitment in commitments:
        if commitment["kind"] != "response_suffix":
            continue
        suffix = commitment["text"]
        placement = commitment.get("placement", "end")
        if placement == "new_line":
            # Citations and deterministic follow-ups may be appended after a
            # provider-authored footer. Remove exact standalone copies from
            # every paragraph before installing one canonical final copy; the
            # visible response must never display the same commitment twice.
            paragraphs = [
                paragraph
                for paragraph in content.split("\n\n")
                if paragraph.strip() != suffix
            ]
            body = "\n\n".join(paragraphs).rstrip()
            # Some providers attach the requested footer directly to prose.
            # Preserve the older repair contract for that malformed ending,
            # after standalone copies elsewhere have already been removed.
            while body.endswith(suffix):
                body = body[: -len(suffix)].rstrip()
            content = suffix if not body else body + "\n\n" + suffix
        elif not content.endswith(suffix):
            content = content.rstrip() + "\n\n" + suffix
    return content


def private_governance_rejection(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    """Close one governed rejection without misclassifying it as provider failure."""
    if not isinstance(payload, dict):
        return ApplicationDecision(False, reasons=("private governance rejection metadata must be an object",))
    receipt_id = payload.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id.strip() or len(receipt_id) > 128:
        return ApplicationDecision(False, reasons=("private governance rejection receipt id is invalid",))
    try:
        privacy = _privacy_state(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))
    if privacy["next_role"] != "assistant":
        return ApplicationDecision(False, reasons=("conversation has no pending assistant turn",))
    state = dict(current) if isinstance(current, dict) else {}
    state["privacy"] = {
        **privacy,
        "next_role": "human",
        "last_governance_rejection": {"receipt_id": receipt_id.strip()},
    }
    return ApplicationDecision(True, state)


def private_provider_failure(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    """Close one failed private provider turn without persisting transcript text."""
    if not isinstance(payload, dict):
        return ApplicationDecision(False, reasons=("private provider failure metadata must be an object",))
    category = payload.get("category")
    if not isinstance(category, str) or not category.strip() or len(category) > 80:
        return ApplicationDecision(False, reasons=("private provider failure category is invalid",))
    try:
        privacy = _privacy_state(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))
    if privacy["next_role"] != "assistant":
        return ApplicationDecision(False, reasons=("conversation has no pending assistant turn",))
    state = dict(current) if isinstance(current, dict) else {}
    state["privacy"] = {
        **privacy,
        "next_role": "human",
        "last_provider_failure": {"category": category.strip()},
    }
    return ApplicationDecision(True, state)


def private_assistant_message(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    """Commit response metadata plus compact observations, never response text."""
    if not isinstance(payload, dict):
        return ApplicationDecision(False, reasons=("private assistant metadata must be an object",))
    if not _valid_digest(payload.get("message_digest")):
        return ApplicationDecision(False, reasons=("private assistant message digest is invalid",))
    message_chars = payload.get("message_chars")
    if not isinstance(message_chars, int) or message_chars <= 0:
        return ApplicationDecision(False, reasons=("private assistant message length is invalid",))
    observations, error = _normalize_observations(payload.get("observations", []))
    if error is not None:
        return ApplicationDecision(False, reasons=(error,))
    has_verified_observations = "verified_observations" in payload
    verified_observations: list[dict[str, str]] = []
    if has_verified_observations:
        verified_observations, verified_error = _normalize_verified_observation_records(
            payload.get("verified_observations", [])
        )
        if verified_error is not None:
            return ApplicationDecision(False, reasons=(verified_error,))
    commitment_updates, commitment_error = _normalize_commitment_updates(
        payload.get("commitment_updates", [])
    )
    if commitment_error is not None:
        return ApplicationDecision(False, reasons=(commitment_error,))
    try:
        privacy = _privacy_state(current)
    except ValueError as state_error:
        return ApplicationDecision(False, reasons=(str(state_error),))
    if privacy["next_role"] != "assistant":
        return ApplicationDecision(False, reasons=("conversation expects human message next",))

    previous = [str(item) for item in privacy["observations"]]
    merged: list[str] = []
    new_legacy_observations = [] if has_verified_observations else observations
    for item in [*previous, *new_legacy_observations]:
        if item not in merged:
            merged.append(item)
    merged = merged[-MAX_DURABLE_OBSERVATIONS:]

    verified_previous = [dict(item) for item in privacy["verified_observations"]]
    verified_merged = list(verified_previous)
    if has_verified_observations:
        last_human = privacy.get("last_human")
        source_digest = last_human.get("message_digest") if isinstance(last_human, dict) else None
        for item in verified_observations:
            if item["source_message_digest"] != source_digest:
                return ApplicationDecision(
                    False,
                    reasons=("verified observation source does not match current human message",),
                )
            if item not in verified_merged:
                verified_merged.append(item)
    verified_merged = verified_merged[-MAX_DURABLE_OBSERVATIONS:]

    state = dict(current) if isinstance(current, dict) else {}
    state["privacy"] = {
        **privacy,
        "turn_count": int(privacy["turn_count"]) + 1,
        "next_role": "human",
        "observations": merged,
        "verified_observations": verified_merged,
        "commitments": _apply_commitment_updates(
            [dict(item) for item in privacy["commitments"]],
            commitment_updates,
        ),
        "last_assistant": {
            "message_digest": payload["message_digest"],
            "message_chars": message_chars,
        },
    }
    return ApplicationDecision(True, state)


MATRIX_VERDICTS = {"pass", "fail", "uncertain"}


def _matrix_campaign_state(current: JsonValue) -> dict[str, JsonValue] | None:
    """Validate and normalize Conversation's optional governed matrix campaign.

    Matrix definitions remain source-level reusable semantics. Only campaign
    progress is operational truth, so completed cells live inside Conversation's
    existing governed application state rather than in a second store.
    """
    if not isinstance(current, dict):
        return None
    raw = current.get("matrix_campaign")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("conversation matrix campaign must be an object")

    matrix = continuity_matrix()
    if raw.get("matrix_id") != matrix.matrix_id or raw.get("matrix_version") != matrix.version:
        raise ValueError("conversation matrix campaign uses an unsupported matrix version")
    if raw.get("definition_digest") != matrix.definition_digest:
        raise ValueError("conversation matrix definition digest does not match installed semantics")
    active = raw.get("active")
    completed = raw.get("completed")
    if not isinstance(active, bool) or not isinstance(completed, list):
        raise ValueError("conversation matrix campaign state is invalid")

    normalized_completed: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in completed:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("coordinate_id"), str)
            or item.get("verdict") not in MATRIX_VERDICTS
        ):
            raise ValueError("conversation matrix result is invalid")
        coordinate = matrix.coordinate_by_id(item["coordinate_id"])
        if coordinate.coordinate_id in seen:
            raise ValueError("conversation matrix campaign contains duplicate coordinates")
        seen.add(coordinate.coordinate_id)
        normalized = {
            "coordinate_id": coordinate.coordinate_id,
            "verdict": str(item["verdict"]),
        }
        evidence_digest = item.get("evidence_digest")
        if evidence_digest is not None:
            if not _valid_digest(evidence_digest):
                raise ValueError("conversation matrix evidence digest is invalid")
            normalized["evidence_digest"] = evidence_digest
        normalized_completed.append(normalized)

    return {
        "matrix_id": matrix.matrix_id,
        "matrix_version": matrix.version,
        "definition_digest": matrix.definition_digest,
        "active": active,
        "completed": normalized_completed,
    }


def start_matrix_campaign(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    """Opt Conversation into the canonical continuity matrix without changing chat defaults."""
    if payload not in (None, {}, {"matrix_id": "continuity", "matrix_version": "1"}):
        return ApplicationDecision(False, reasons=("unsupported Conversation matrix campaign",))
    try:
        existing = _matrix_campaign_state(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))

    matrix = continuity_matrix()
    completed = list(existing["completed"]) if existing is not None else []
    state = dict(current) if isinstance(current, dict) else {}
    state["matrix_campaign"] = {
        "matrix_id": matrix.matrix_id,
        "matrix_version": matrix.version,
        "definition_digest": matrix.definition_digest,
        "active": True,
        "completed": completed,
    }
    return ApplicationDecision(True, state)


def record_matrix_result(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    """Persist one privacy-safe matrix outcome through normal Conversation governance."""
    if not isinstance(payload, dict):
        return ApplicationDecision(False, reasons=("Conversation matrix result must be an object",))
    coordinate_id = payload.get("coordinate_id")
    verdict = payload.get("verdict")
    evidence_digest = payload.get("evidence_digest")
    if not isinstance(coordinate_id, str) or verdict not in MATRIX_VERDICTS:
        return ApplicationDecision(False, reasons=("Conversation matrix result is invalid",))
    if evidence_digest is not None and not _valid_digest(evidence_digest):
        return ApplicationDecision(False, reasons=("Conversation matrix evidence digest is invalid",))

    try:
        campaign = _matrix_campaign_state(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))
    if campaign is None or not campaign["active"]:
        return ApplicationDecision(False, reasons=("Conversation matrix campaign is not active",))

    matrix = continuity_matrix()
    try:
        coordinate = matrix.coordinate_by_id(coordinate_id)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))

    completed = [dict(item) for item in campaign["completed"]]
    if any(item["coordinate_id"] == coordinate.coordinate_id for item in completed):
        return ApplicationDecision(False, reasons=("Conversation matrix coordinate is already completed",))

    result = {"coordinate_id": coordinate.coordinate_id, "verdict": str(verdict)}
    if evidence_digest is not None:
        result["evidence_digest"] = evidence_digest
    completed.append(result)

    state = dict(current) if isinstance(current, dict) else {}
    state["matrix_campaign"] = {**campaign, "completed": completed}
    return ApplicationDecision(True, state)


def stop_matrix_campaign(current: JsonValue, payload: JsonValue) -> ApplicationDecision:
    """Disable matrix execution while preserving governed results for later reconstruction."""
    if payload not in (None, {}):
        return ApplicationDecision(False, reasons=("Conversation matrix stop takes no payload",))
    try:
        campaign = _matrix_campaign_state(current)
    except ValueError as error:
        return ApplicationDecision(False, reasons=(str(error),))
    if campaign is None:
        return ApplicationDecision(False, reasons=("Conversation matrix campaign has not started",))

    state = dict(current) if isinstance(current, dict) else {}
    state["matrix_campaign"] = {**campaign, "active": False}
    return ApplicationDecision(True, state)


def matrix_campaign_projection(state: JsonValue) -> dict[str, JsonValue]:
    """Return bounded matrix progress and the next deterministic cell for a fresh provider."""
    campaign = _matrix_campaign_state(state)
    if campaign is None:
        return {"enabled": False}

    matrix = continuity_matrix()
    completed_ids = [str(item["coordinate_id"]) for item in campaign["completed"]]
    next_cell = matrix.next_uncovered(completed_ids) if campaign["active"] else None
    projection: dict[str, JsonValue] = {
        "enabled": bool(campaign["active"]),
        "matrix_id": matrix.matrix_id,
        "matrix_version": matrix.version,
        "definition_digest": matrix.definition_digest,
        "completed_count": len(completed_ids),
        "total_cells": matrix.cell_count,
    }
    if next_cell is not None:
        selections: dict[str, JsonValue] = {}
        for axis, key in zip(matrix.axes, next_cell.value_keys, strict=True):
            value = next(value for value in axis.values if value.key == key)
            selections[axis.key] = {
                "key": value.key,
                "label": value.label,
                "description": value.description,
            }
        projection["next_coordinate"] = {
            "coordinate_id": next_cell.coordinate_id,
            "ordinal": next_cell.ordinal,
            "selections": selections,
        }
    return projection


CONVERSATION_APPLICATION = ApplicationDefinition(
    APPLICATION_ID,
    APPLICATION_VERSION,
    (
        # Legacy transcript actions remain registered so existing authoritative
        # v1 proof events replay. Production/private runtime uses only the two
        # metadata actions below.
        ApplicationAction("human_message", human_message),
        ApplicationAction("assistant_message", assistant_message),
        ApplicationAction("private_human_message", private_human_message),
        ApplicationAction("private_assistant_message", private_assistant_message),
        ApplicationAction("private_governance_rejection", private_governance_rejection),
        ApplicationAction("private_provider_failure", private_provider_failure),
        ApplicationAction("start_matrix_campaign", start_matrix_campaign),
        ApplicationAction("record_matrix_result", record_matrix_result),
        ApplicationAction("stop_matrix_campaign", stop_matrix_campaign),
    ),
)


def bounded_context(state: JsonValue, *, max_turns: int = DEFAULT_CONTEXT_TURNS) -> dict[str, JsonValue]:
    """Legacy bounded transcript projection retained for historical proof tests."""
    if max_turns <= 0:
        raise ValueError("max_turns must be positive")
    turns = _turns(state)
    omitted = turns[:-max_turns] if len(turns) > max_turns else []
    recent = turns[-max_turns:]
    digest = hashlib.sha256(
        json.dumps(omitted, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return {
        "application_id": APPLICATION_ID,
        "application_version": APPLICATION_VERSION,
        "turns": recent,
        "turn_count": len(turns),
        "omitted_turn_count": len(omitted),
        "omitted_turns_digest": digest,
    }


def private_bounded_context(state: JsonValue) -> dict[str, JsonValue]:
    """Return only durable continuity observations, never prior transcript text."""
    privacy = _privacy_state(state)
    verified = [dict(item) for item in privacy["verified_observations"]]
    observations = [item["text"] for item in verified]
    projection: dict[str, JsonValue] = {
        "application_id": APPLICATION_ID,
        "application_version": APPLICATION_VERSION,
        "turn_count": privacy["turn_count"],
        "next_role": privacy["next_role"],
        "observations": observations,
        "observation_count": len(observations),
        "observation_provenance": verified,
        "legacy_unverified_observation_count": len(privacy["observations"]),
        "active_commitments": [dict(item) for item in privacy["commitments"]],
        "active_commitment_count": len(privacy["commitments"]),
    }
    matrix_projection = matrix_campaign_projection(state)
    if matrix_projection["enabled"]:
        projection["matrix_campaign"] = matrix_projection
    return projection


def private_assistant_descriptor(
    response: str,
    observations: object,
    commitment_updates: object = (),
    *,
    source_message: str | None = None,
) -> dict[str, JsonValue]:
    """Build safe durable assistant metadata after provider output validation."""
    if not isinstance(response, str) or not response.strip():
        raise ValueError("assistant response must be non-empty text")
    content = response.strip()
    normalized, error = _normalize_observations(
        observations,
        allow_transient_urls=source_message is not None,
    )
    if error is not None:
        raise ValueError(error)
    verified = (
        _verified_observation_records(normalized, source_message)
        if source_message is not None
        else []
    )
    normalized_updates, update_error = _normalize_commitment_updates(list(commitment_updates))
    if update_error is not None:
        raise ValueError(update_error)
    durable_observations = [item["text"] for item in verified] if source_message is not None else normalized
    descriptor: dict[str, JsonValue] = {
        "message_digest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "message_chars": len(content),
        "observations": durable_observations,
        "commitment_updates": normalized_updates,
    }
    if source_message is not None:
        descriptor["verified_observations"] = verified
    return descriptor
