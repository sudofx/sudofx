"""Append-only SQLite record and deterministic replay."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import JsonValue
from .governance import work_key

GENESIS_HASH = "0" * 64


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def apply_operation(state: dict[str, JsonValue], operation: dict[str, Any]) -> None:
    action = operation["action"]
    key = operation["key"]
    if action == "set":
        state[key] = operation.get("value")
    elif action == "delete":
        state.pop(key, None)
    elif action == "create_work":
        value = operation["value"]
        state[work_key(key)] = {
            "id": key,
            "objective": value["objective"],
            "constraints": list(value.get("constraints", [])),
            "status": "open",
            "accepted_results": [],
            "open_obligations": [],
            "work_revision": 0,
        }
    elif action == "advance_work":
        value = operation["value"]
        work = dict(state[work_key(key)])
        results = list(work.get("accepted_results", []))
        results.append(value["result"])
        work["accepted_results"] = results
        work["open_obligations"] = list(value.get("open_obligations", []))
        work["work_revision"] = int(work.get("work_revision", 0)) + 1
        state[work_key(key)] = work
    elif action == "complete_work":
        value = operation["value"]
        work = dict(state[work_key(key)])
        work["status"] = "completed"
        work["final_result"] = value["result"]
        work["open_obligations"] = []
        work["work_revision"] = int(work.get("work_revision", 0)) + 1
        state[work_key(key)] = work
    else:
        raise IntegrityError(f"unsupported recorded operation: {action}")


class IntegrityError(RuntimeError):
    """Raised when the durable record cannot be verified."""


class Record:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_id TEXT NOT NULL UNIQUE,
                    proposal_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK (status IN ('accepted', 'rejected')),
                    revision_before INTEGER NOT NULL,
                    revision_after INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    reasons TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.commit()

    @staticmethod
    def hash_event(previous_hash: str, event: dict[str, Any]) -> str:
        material = f"{previous_hash}\n{canonical_json(event)}".encode()
        return hashlib.sha256(material).hexdigest()

    def rows(self, connection: sqlite3.Connection | None = None) -> list[sqlite3.Row]:
        if connection is not None:
            return list(connection.execute("SELECT * FROM events ORDER BY sequence"))
        with self.connect() as own_connection:
            return list(own_connection.execute("SELECT * FROM events ORDER BY sequence"))

    def replay(self, connection: sqlite3.Connection | None = None) -> tuple[int, dict[str, JsonValue]]:
        state: dict[str, JsonValue] = {}
        revision = 0
        previous_hash = GENESIS_HASH
        for row in self.rows(connection):
            payload = json.loads(row["payload"])
            reasons = json.loads(row["reasons"])
            material = {
                "receipt_id": row["receipt_id"],
                "proposal_id": row["proposal_id"],
                "status": row["status"],
                "revision_before": row["revision_before"],
                "revision_after": row["revision_after"],
                "payload": payload,
                "reasons": reasons,
            }
            expected_hash = self.hash_event(previous_hash, material)
            if row["previous_hash"] != previous_hash or row["event_hash"] != expected_hash:
                raise IntegrityError(f"event chain is invalid at sequence {row['sequence']}")
            if row["revision_before"] != revision:
                raise IntegrityError(f"revision discontinuity at sequence {row['sequence']}")
            if row["status"] == "accepted":
                for operation in payload["operations"]:
                    apply_operation(state, operation)
                revision += 1
            if row["revision_after"] != revision:
                raise IntegrityError(f"invalid resulting revision at sequence {row['sequence']}")
            previous_hash = row["event_hash"]
        return revision, state

    def recent(
        self, limit: int = 10, connection: sqlite3.Connection | None = None
    ) -> tuple[dict[str, Any], ...]:
        if connection is not None:
            rows = list(
                connection.execute(
                    "SELECT * FROM events ORDER BY sequence DESC LIMIT ?", (max(0, limit),)
                )
            )
        else:
            with self.connect() as own_connection:
                rows = list(
                    own_connection.execute(
                        "SELECT * FROM events ORDER BY sequence DESC LIMIT ?", (max(0, limit),)
                    )
                )
        return tuple(
            {
                "receipt_id": row["receipt_id"],
                "proposal_id": row["proposal_id"],
                "status": row["status"],
                "revision_before": row["revision_before"],
                "revision_after": row["revision_after"],
                "reasons": json.loads(row["reasons"]),
                "proposal": json.loads(row["payload"]),
                "event_hash": row["event_hash"],
            }
            for row in reversed(rows)
        )

    def history(self) -> tuple[dict[str, Any], ...]:
        """Return the complete verified receipt history in record order."""
        with self.connect() as connection:
            connection.execute("BEGIN")
            self.replay(connection)
            rows = self.rows(connection)
        return tuple(
            {
                "sequence": row["sequence"],
                "receipt_id": row["receipt_id"],
                "proposal_id": row["proposal_id"],
                "status": row["status"],
                "revision_before": row["revision_before"],
                "revision_after": row["revision_after"],
                "proposal": json.loads(row["payload"]),
                "reasons": json.loads(row["reasons"]),
                "previous_hash": row["previous_hash"],
                "event_hash": row["event_hash"],
                "created_at": row["created_at"],
            }
            for row in rows
        )
