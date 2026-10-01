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
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import JsonValue
from .governance import work_key
from .storage import EventAppend, GENESIS_HASH, InvocationEvent, canonical_json, hash_event


# These header values identify the file before table-level parsing begins. The
# application ID prevents an arbitrary SQLite file from being accepted as a
# sudofx record; user_version gives storage evolution one ordered owner instead
# of scattering opportunistic CREATE/ALTER statements through runtime paths.
APPLICATION_ID = 0x53444658  # "SDFX"
SCHEMA_VERSION = 4


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
            "semantic_assessments": [],
            "handoff_evaluations": [],
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
    elif action == "record_assessment":
        value = operation["value"]
        work = dict(state[work_key(key)])
        assessments = list(work.get("semantic_assessments", []))
        assessments.append(value)
        work["semantic_assessments"] = assessments
        work["work_revision"] = int(work.get("work_revision", 0)) + 1
        state[work_key(key)] = work
    elif action == "record_handoff_evaluation":
        # Raw vendor output is durable evidence, not authority over the work.
        # Keeping it under the governed work item preserves provenance while
        # preventing any answer text from mutating objective or frontier fields.
        value = operation["value"]
        work = dict(state[work_key(key)])
        runs = list(work.get("handoff_evaluations", []))
        runs.append(value)
        work["handoff_evaluations"] = runs
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
                payload, reasons, provenance, previous_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.receipt_id,
                event.proposal_id,
                event.status,
                event.revision_before,
                event.revision_after,
                canonical_json(event.payload),
                canonical_json(list(event.reasons)),
                canonical_json(event.provenance) if event.provenance is not None else None,
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
                    provenance TEXT,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Versions zero and one predate durable trusted provenance. The v2
            # migration adds one nullable column: existing event bytes and hashes
            # remain valid because historical rows keep provenance NULL and replay
            # omits absent provenance from legacy semantic hash material.
            columns = {row[1] for row in connection.execute("PRAGMA table_info(events)")}
            if "provenance" not in columns:
                connection.execute("ALTER TABLE events ADD COLUMN provenance TEXT")

            # v3 adds a separate append-only operational journal for provider
            # invocation lifecycle. These rows never advance semantic revision
            # and never impersonate proposal receipts.
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS invocation_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    invocation_id TEXT NOT NULL,
                    stage TEXT NOT NULL CHECK (
                        stage IN (
                            'requested',
                            'context_delivered',
                            'attempt_started',
                            'proposal_received',
                            'governed',
                            'completed',
                            'failed'
                        )
                    ),
                    source_revision INTEGER NOT NULL,
                    context_digest TEXT NOT NULL,
                    provenance TEXT,
                    proposal_id TEXT,
                    receipt_id TEXT,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS invocation_events_id_sequence "
                "ON invocation_events(invocation_id, sequence)"
            )

            # v4 makes invocation evidence self-verifying and gives context
            # delivery receipts room for bounded structured metadata. Existing
            # v3 rows are deterministically backfilled in append order rather
            # than treated as if they had always been hash-linked.
            invocation_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(invocation_events)")
            }
            if "event_id" not in invocation_columns:
                connection.execute("ALTER TABLE invocation_events ADD COLUMN event_id TEXT")
            if "metadata" not in invocation_columns:
                connection.execute(
                    "ALTER TABLE invocation_events ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'"
                )
            if "previous_hash" not in invocation_columns:
                connection.execute("ALTER TABLE invocation_events ADD COLUMN previous_hash TEXT")
            if "event_hash" not in invocation_columns:
                connection.execute("ALTER TABLE invocation_events ADD COLUMN event_hash TEXT")

            previous_invocation_hash = GENESIS_HASH
            invocation_rows = list(
                connection.execute("SELECT * FROM invocation_events ORDER BY sequence")
            )
            for row in invocation_rows:
                event_id = row["event_id"] or f"legacy-invocation-{row['sequence']}"
                metadata = json.loads(row["metadata"]) if row["metadata"] else {}
                provenance_value = (
                    json.loads(row["provenance"]) if row["provenance"] else None
                )
                material = {
                    "event_id": event_id,
                    "invocation_id": row["invocation_id"],
                    "stage": row["stage"],
                    "source_revision": row["source_revision"],
                    "context_digest": row["context_digest"],
                    "provenance": provenance_value,
                    "proposal_id": row["proposal_id"],
                    "receipt_id": row["receipt_id"],
                    "detail": row["detail"],
                    "metadata": metadata,
                }
                event_hash = hash_event(previous_invocation_hash, material)
                if (
                    row["event_id"] is None
                    or row["previous_hash"] is None
                    or row["event_hash"] is None
                ):
                    connection.execute(
                        """
                        UPDATE invocation_events
                        SET event_id = ?, metadata = ?, previous_hash = ?, event_hash = ?
                        WHERE sequence = ?
                        """,
                        (
                            event_id,
                            canonical_json(metadata),
                            previous_invocation_hash,
                            event_hash,
                            row["sequence"],
                        ),
                    )
                previous_invocation_hash = event_hash
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS invocation_events_event_id "
                "ON invocation_events(event_id)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS invocation_events_event_hash "
                "ON invocation_events(event_hash)"
            )
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
            return changed

    @staticmethod
    def _invocation_material(row: sqlite3.Row) -> dict[str, Any]:
        """Rebuild exactly the semantic material bound into one lifecycle hash."""
        return {
            "event_id": row["event_id"],
            "invocation_id": row["invocation_id"],
            "stage": row["stage"],
            "source_revision": row["source_revision"],
            "context_digest": row["context_digest"],
            "provenance": json.loads(row["provenance"]) if row["provenance"] else None,
            "proposal_id": row["proposal_id"],
            "receipt_id": row["receipt_id"],
            "detail": row["detail"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        }

    def _verified_invocation_history(
        self,
        connection: sqlite3.Connection,
    ) -> tuple[dict[str, Any], ...]:
        """Verify the global invocation hash chain and each invocation's stage order."""
        rows = list(connection.execute("SELECT * FROM invocation_events ORDER BY sequence"))
        previous_hash = GENESIS_HASH
        prior_stage: dict[str, str] = {}
        allowed_next = {
            None: {"requested"},
            "requested": {"context_delivered", "failed"},
            "context_delivered": {"attempt_started", "failed"},
            "attempt_started": {"proposal_received", "failed"},
            "proposal_received": {"governed", "failed"},
            "governed": {"completed", "failed"},
            "completed": set(),
            "failed": set(),
        }
        result: list[dict[str, Any]] = []
        for row in rows:
            material = self._invocation_material(row)
            expected_hash = hash_event(previous_hash, material)
            if row["previous_hash"] != previous_hash or row["event_hash"] != expected_hash:
                raise IntegrityError(
                    f"invocation chain is invalid at sequence {row['sequence']}"
                )
            invocation_id = str(row["invocation_id"])
            stage = str(row["stage"])
            prior = prior_stage.get(invocation_id)
            if stage not in allowed_next.get(prior, set()):
                raise IntegrityError(
                    f"invalid invocation lifecycle transition {prior!r} -> {stage!r} "
                    f"for {invocation_id}"
                )
            prior_stage[invocation_id] = stage
            previous_hash = row["event_hash"]
            result.append(
                {
                    "sequence": row["sequence"],
                    **material,
                    "previous_hash": row["previous_hash"],
                    "event_hash": row["event_hash"],
                    "created_at": row["created_at"],
                }
            )
        return tuple(result)

    def append_invocation_event(self, event: InvocationEvent) -> None:
        """
        Append one runtime lifecycle fact independently of semantic revision.

        Invocation rows share the authoritative database but form their own
        globally hash-linked evidence stream. A provider failure therefore stays
        durable without becoming a fake Proposal receipt or advancing state.
        """
        if not event.invocation_id.strip():
            raise ValueError("invocation_id must not be empty")
        if event.source_revision < 0:
            raise ValueError("source_revision must not be negative")
        if not event.context_digest.strip():
            raise ValueError("context_digest must not be empty")

        provenance = (
            canonical_json(event.provenance) if event.provenance is not None else None
        )
        metadata = canonical_json(event.metadata or {})
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                verified = self._verified_invocation_history(connection)
                prior = next(
                    (
                        item["stage"]
                        for item in reversed(verified)
                        if item["invocation_id"] == event.invocation_id
                    ),
                    None,
                )
                allowed_next = {
                    None: {"requested"},
                    "requested": {"context_delivered", "failed"},
                    "context_delivered": {"attempt_started", "failed"},
                    "attempt_started": {"proposal_received", "failed"},
                    "proposal_received": {"governed", "failed"},
                    "governed": {"completed", "failed"},
                    "completed": set(),
                    "failed": set(),
                }
                if event.stage not in allowed_next.get(prior, set()):
                    raise ValueError(
                        f"invalid invocation lifecycle transition {prior!r} -> {event.stage!r}"
                    )

                previous_hash = verified[-1]["event_hash"] if verified else GENESIS_HASH
                event_id = str(uuid.uuid4())
                material = {
                    "event_id": event_id,
                    "invocation_id": event.invocation_id,
                    "stage": event.stage,
                    "source_revision": event.source_revision,
                    "context_digest": event.context_digest,
                    "provenance": event.provenance,
                    "proposal_id": event.proposal_id,
                    "receipt_id": event.receipt_id,
                    "detail": event.detail,
                    "metadata": event.metadata or {},
                }
                event_hash = hash_event(previous_hash, material)
                connection.execute(
                    """
                    INSERT INTO invocation_events (
                        invocation_id, stage, source_revision, context_digest,
                        provenance, proposal_id, receipt_id, detail,
                        event_id, metadata, previous_hash, event_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.invocation_id,
                        event.stage,
                        event.source_revision,
                        event.context_digest,
                        provenance,
                        event.proposal_id,
                        event.receipt_id,
                        event.detail,
                        event_id,
                        metadata,
                        previous_hash,
                        event_hash,
                    ),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def invocation_history(
        self, invocation_id: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        """Return verified durable invocation evidence in append order."""
        with self.connect() as connection:
            connection.execute("BEGIN")
            verified = self._verified_invocation_history(connection)
        if invocation_id is None:
            return verified
        return tuple(
            event for event in verified if event["invocation_id"] == invocation_id
        )

    def incomplete_invocations(self) -> tuple[dict[str, Any], ...]:
        """
        Return latest evidence for invocations that never reached a terminal stage.

        A fresh process can explicitly close these as failed/interrupted. It must
        never infer that an external provider or side effect succeeded.
        """
        history = self.invocation_history()
        latest: dict[str, dict[str, Any]] = {}
        for event in history:
            latest[event["invocation_id"]] = event
        return tuple(
            event
            for event in latest.values()
            if event["stage"] not in {"completed", "failed"}
        )

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
            "provenance": json.loads(row["provenance"]) if row["provenance"] else None,
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
            provenance = json.loads(row["provenance"]) if row["provenance"] else None
            # Historical v0/v1 rows did not hash a provenance field at all.
            # Omitting NULL here preserves their original semantic identity while
            # every newly attributed v2 event binds provenance into its hash.
            if provenance is not None:
                material["provenance"] = provenance
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
                "provenance": json.loads(row["provenance"]) if row["provenance"] else None,
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
