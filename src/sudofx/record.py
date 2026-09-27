"""
SUDOFX DURABLE RECORD
=====================

This module owns the authoritative history and the deterministic projection from
that history into current state. SQLite is used as a durable append-only event
container, not as a mutable table of current objects.

Every meaningful proposal produces exactly one event:

    accepted -> receipt + transition + revision advance
    rejected -> receipt + no transition + unchanged revision

Rejected events remain in the chain because they are evidence of what the
system refused. They do not alter state. That distinction makes correction
possible without silently rewriting history.

Events are linked by SHA-256 hashes over canonical JSON and the previous hash.
The chain detects accidental or unauthorized row changes during replay. It is
not a signature and does not prove who authored an event; anyone with write
access to the entire database could rebuild the chain. Its guarantee is local
integrity detection against the expected stored head, not external notarization.

Current state is never trusted as a separate cache. ``replay`` starts from an
empty mapping, verifies every event in sequence, and applies only accepted
operations. If an event hash, revision edge, or operation is invalid, replay
stops rather than returning a plausible partial state.

The record does not decide whether an operation is allowed. Governance owns
permission before append. ``apply_operation`` owns the exact semantics needed
to reconstruct already accepted history. Keeping those responsibilities
separate prevents historical data from becoming valid merely because replay can
mechanically interpret it.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import JsonValue
from .governance import work_key
from .storage import EventAppend, GENESIS_HASH, canonical_json, hash_event


# These header values identify the file before table-level parsing begins. The
# application ID prevents an arbitrary SQLite file from being accepted as a
# sudofx record; user_version gives storage evolution one ordered owner instead
# of scattering opportunistic CREATE/ALTER statements through runtime paths.
APPLICATION_ID = 0x53444658  # "SDFX"
SCHEMA_VERSION = 1


def apply_operation(state: dict[str, JsonValue], operation: dict[str, Any]) -> None:
    """
    Apply one previously accepted operation to an in-memory projection.

    This function assumes governance approved the original event. It still
    rejects unknown actions because silently ignoring an operation would return
    a false state while claiming successful replay.

    Work transitions copy nested containers before changing them. Historical
    replay currently builds a fresh state, but copy-on-transition prevents a
    future caller from observing an earlier projection mutate through a shared
    reference.
    """
    action = operation["action"]
    key = operation["key"]
    if action == "set":
        state[key] = operation.get("value")
    elif action == "delete":
        state.pop(key, None)
    elif action == "create_work":
        # Creation derives lifecycle-owned fields here rather than accepting
        # provider-supplied status, revisions, or results. The proposer controls
        # the objective and constraints; the system controls lifecycle state.
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
        # Accepted results are append-only within the work projection. Open
        # obligations describe the newest known frontier and therefore replace,
        # rather than append to, the previous set.
        value = operation["value"]
        work = dict(state[work_key(key)])
        results = list(work.get("accepted_results", []))
        results.append(value["result"])
        work["accepted_results"] = results
        work["open_obligations"] = list(value.get("open_obligations", []))
        work["work_revision"] = int(work.get("work_revision", 0)) + 1
        state[work_key(key)] = work
    elif action == "complete_work":
        # Completion preserves accepted progress, records the final result,
        # clears resolved obligations, and advances the work-local revision.
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
    """
    Signal that authoritative history cannot be verified safely.

    Callers must not recover by skipping the row or trusting a cached projection.
    Repair requires an explicit recovery process with stronger evidence.
    """


class StorageVersionError(IntegrityError):
    """Reject a database whose identity or schema cannot be interpreted safely."""


class _SQLiteTransaction:
    """
    Adapt one live SQLite transaction to the kernel's storage contract.

    Only semantic operations cross this wrapper. SQL, native connection objects,
    commit/rollback calls, and table layout stay owned by this module.
    """

    def __init__(self, record: "Record", connection: sqlite3.Connection) -> None:
        self._record = record
        self._connection = connection

    def replay(self) -> tuple[int, dict[str, JsonValue]]:
        """Verify and reconstruct state inside this transaction snapshot."""
        return self._record.replay(self._connection)

    def recent(self, limit: int = 10) -> tuple[dict[str, Any], ...]:
        """Return bounded receipt evidence from the same transaction snapshot."""
        return self._record.recent(limit, self._connection)

    def proposal_exists(self, proposal_id: str) -> bool:
        """Check durable proposal identity without exposing the events table."""
        row = self._connection.execute(
            "SELECT 1 FROM events WHERE proposal_id = ? LIMIT 1",
            (proposal_id,),
        ).fetchone()
        return row is not None

    def head_hash(self) -> str:
        """Return the predecessor hash for the next semantic event."""
        row = self._connection.execute(
            "SELECT event_hash FROM events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        return row["event_hash"] if row else GENESIS_HASH

    def append(self, event: EventAppend) -> None:
        """
        Append one complete event inside the already-open write transaction.

        Commit/rollback belongs to Record.write_transaction, so no partial
        publication can occur between event fields.
        """
        self._connection.execute(
            """
            INSERT INTO events (
                receipt_id, proposal_id, status, revision_before, revision_after,
                payload, reasons, previous_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.receipt_id,
                event.proposal_id,
                event.status,
                event.revision_before,
                event.revision_after,
                canonical_json(event.payload),
                canonical_json(list(event.reasons)),
                event.previous_hash,
                event.event_hash,
            ),
        )


class Record:
    """
    Provide transactional access to one append-only SQLite event stream.

    A Record may be reopened by a fresh process at any time. No correctness
    depends on a long-lived Python instance, which is essential to disposable
    invocation continuity.
    """
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.schema_changed = self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """
        Yield a short-lived row-aware connection and always close it.

        Transaction ownership stays with the calling operation because reads,
        governance, and append sometimes need one shared snapshot.
        """
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def read_transaction(self) -> Iterator[_SQLiteTransaction]:
        """
        Provide one snapshot-consistent semantic read transaction.

        Kernel receives no SQLite object. Ending the context closes the snapshot
        without publishing any state.
        """
        with self.connect() as connection:
            connection.execute("BEGIN")
            try:
                yield _SQLiteTransaction(self, connection)
            finally:
                connection.rollback()

    @contextmanager
    def write_transaction(self) -> Iterator[_SQLiteTransaction]:
        """
        Serialize and atomically publish one governed submission.

        BEGIN IMMEDIATE is SQLite's implementation of the stronger storage
        contract: replay, identity check, governance, and append share one
        serialized view. Any exception rolls back before escaping.
        """
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield _SQLiteTransaction(self, connection)
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _initialize(self) -> bool:
        """
        Create or migrate storage idempotently without creating semantic state.

        Initialization may establish the empty schema, but the first meaningful
        revision exists only after an accepted proposal is appended. Migrations
        are storage-authority changes and are reported to the caller so a cloud
        adapter can checkpoint them before publishing a projection.
        """
        with self.connect() as connection:
            application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if application_id not in (0, APPLICATION_ID):
                raise StorageVersionError("database application identity is not sudofx")
            if version > SCHEMA_VERSION:
                raise StorageVersionError(
                    f"database schema {version} is newer than supported schema {SCHEMA_VERSION}"
                )

            # Journal configuration is allowed only after file identity and
            # compatibility pass. Even a harmless header write would otherwise
            # mutate an unrelated or future database before rejecting it.
            connection.execute("PRAGMA journal_mode=WAL")
            changed = application_id != APPLICATION_ID or version != SCHEMA_VERSION
            connection.execute("BEGIN IMMEDIATE")
            # WAL supports readers alongside the serialized writer. Kernel.submit
            # still uses BEGIN IMMEDIATE so two writers cannot govern from the
            # same revision and both commit conflicting accepted transitions.
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
            # Version zero is the only legacy shape and is structurally identical
            # to v1. Recording identity/version makes that fact explicit; future
            # versions must add ordered migration steps here rather than guessing
            # from whichever tables happen to exist.
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
            return changed

    def backup_to(self, destination: str | Path) -> None:
        """
        Write one transactionally coherent, verified SQLite snapshot.

        Copying the main file bytes can omit WAL-resident changes. SQLite's
        backup API owns that boundary and produces a complete destination view.
        The snapshot is then checked physically and semantically before callers
        may publish it as a checkpoint or recovery artifact.
        """
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # sqlite3.Connection's context manager owns commit/rollback but does not
        # close the handle. ``closing`` prevents backup verification from
        # leaking descriptors as maintenance frequency grows.
        with self.connect() as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
        with closing(sqlite3.connect(destination)) as check:
            result = check.execute("PRAGMA quick_check").fetchone()[0]
            if result != "ok":
                raise IntegrityError(f"snapshot failed SQLite quick_check: {result}")
        Record(destination).replay()

    def vacuum_snapshot_to(self, destination: str | Path) -> None:
        """
        Create one compact derived recovery snapshot with SQLite VACUUM INTO.

        The source database remains authoritative. The destination is recovery
        evidence only and must pass both SQLite integrity checking and complete
        sudofx semantic replay before callers may treat it as usable.
        """
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(f"VACUUM INTO destination already exists: {destination}")
        quoted = str(destination).replace("'", "''")
        with self.connect() as source:
            source.execute(f"VACUUM INTO '{quoted}'")
        with closing(sqlite3.connect(destination)) as check:
            result = check.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise IntegrityError(f"VACUUM INTO snapshot failed SQLite integrity_check: {result}")
        Record(destination).replay()

    def health(self) -> dict[str, int | float | str]:
        """
        Return bounded maintenance evidence derived from a verified snapshot.

        This is diagnostic projection data, never authority. It deliberately
        excludes proposal content so it can be shown without leaking durable
        context while still revealing growth and replay cost.
        """
        started = time.perf_counter()
        revision, _ = self.replay()
        replay_ms = (time.perf_counter() - started) * 1000
        with self.connect() as connection:
            event_count = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            free_pages = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        return {
            "schema_version": SCHEMA_VERSION,
            "revision": revision,
            "event_count": event_count,
            "database_bytes": page_size * page_count,
            "free_bytes": page_size * free_pages,
            "replay_ms": round(replay_ms, 3),
            "quick_check": quick_check,
        }

    def projection_snapshot(
        self, history_limit: int = 50
    ) -> tuple[int, dict[str, JsonValue], tuple[dict[str, Any], ...], dict[str, int | float | str]]:
        """
        Build state, bounded history, and health from one verified read snapshot.

        Presentation used to replay independently for state, history, and health.
        That multiplied linear work and could mix adjacent revisions. This method
        keeps the public projection internally coherent while preserving the
        kernel's backend-neutral transaction contract for provider work.
        """
        started = time.perf_counter()
        with self.connect() as connection:
            connection.execute("BEGIN")
            revision, state = self.replay(connection)
            rows = list(
                connection.execute(
                    "SELECT * FROM events ORDER BY sequence DESC LIMIT ?",
                    (max(0, history_limit),),
                )
            )
            event_count = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            free_pages = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        rows.reverse()
        health: dict[str, int | float | str] = {
            "schema_version": SCHEMA_VERSION,
            "revision": revision,
            "event_count": event_count,
            "database_bytes": page_size * page_count,
            "free_bytes": page_size * free_pages,
            "replay_ms": round((time.perf_counter() - started) * 1000, 3),
            "quick_check": quick_check,
        }
        return revision, state, tuple(self._event_from_row(row) for row in rows), health

    def history_tail(self, limit: int = 50) -> tuple[dict[str, Any], ...]:
        """
        Verify the complete chain but materialize only the newest receipt window.

        Verification remains exhaustive because a corrupt predecessor invalidates
        every later hash. Presentation is bounded independently so page size and
        browser work do not grow with authoritative history.
        """
        with self.connect() as connection:
            connection.execute("BEGIN")
            self.replay(connection)
            rows = list(
                connection.execute(
                    "SELECT * FROM events ORDER BY sequence DESC LIMIT ?", (max(0, limit),)
                )
            )
        rows.reverse()
        return tuple(self._event_from_row(row) for row in rows)

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
        """Translate one verified storage row into the backend-neutral receipt view."""
        return {
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

    @staticmethod
    def hash_event(previous_hash: str, event: dict[str, Any]) -> str:
        """
        Preserve the historical helper while delegating the durable hash contract.

        New kernel code imports the backend-neutral function directly; keeping
        this method avoids needless breakage for inspection/recovery callers.
        """
        return hash_event(previous_hash, event)

    def rows(self, connection: sqlite3.Connection | None = None) -> list[sqlite3.Row]:
        """
        Return events strictly in append order.

        Accepting an existing connection lets replay participate in the caller's
        transaction instead of accidentally reading a second database snapshot.
        """
        if connection is not None:
            return list(connection.execute("SELECT * FROM events ORDER BY sequence"))
        with self.connect() as own_connection:
            return list(own_connection.execute("SELECT * FROM events ORDER BY sequence"))

    def replay(self, connection: sqlite3.Connection | None = None) -> tuple[int, dict[str, JsonValue]]:
        """
        Verify the complete chain and reconstruct authoritative current state.

        Revision continuity is checked independently of hashes. That redundant
        invariant catches logically impossible histories even if their bytes
        were re-hashed consistently by a faulty writer.
        """
        state: dict[str, JsonValue] = {}
        revision = 0
        previous_hash = GENESIS_HASH
        for row in self.rows(connection):
            # Recreate exactly the material used at append time. Timestamps and
            # SQLite sequence numbers are metadata, not semantic hash input.
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
                # All operations in an accepted proposal are applied together.
                # Rejected payloads are retained for evidence but never executed.
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
        """
        Return a bounded chronological receipt window for provider context.

        SQL reads newest rows efficiently, then Python reverses them so context
        presents cause before effect. Proposal payloads remain attached because
        work-scoped context must filter receipts by semantic target.
        """
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
        """
        Return the complete verified history in record order.

        Verification and row capture share one read transaction. A concurrent
        append may happen before or after that snapshot, but cannot produce a
        history whose verification covered fewer rows than the returned result.
        """
        with self.connect() as connection:
            connection.execute("BEGIN")
            self.replay(connection)
            rows = self.rows(connection)
        return tuple(self._event_from_row(row) for row in rows)
