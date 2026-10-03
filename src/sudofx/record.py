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

import base64
import hashlib
import json
import sqlite3
import time
import uuid
import zlib
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import JsonValue
from .applications import application_key
from .governance import work_key
from .storage import (
    ApplicationAccessError,
    ApplicationAccessState,
    EventAppend,
    GENESIS_HASH,
    InvocationEvent,
    canonical_json,
    hash_event,
)


# These header values identify the file before table-level parsing begins. The
# application ID prevents an arbitrary SQLite file from being accepted as a
# sudofx record; user_version gives storage evolution one ordered owner instead
# of scattering opportunistic CREATE/ALTER statements through runtime paths.
APPLICATION_ID = 0x53444658  # "SDFX"
SCHEMA_VERSION = 11


_PROJECTION_CODEC_PREFIX = "zlib:"


def _encode_projection_state(state_json: str) -> str:
    """Compress derived projection bytes without changing semantic state."""
    compressed = zlib.compress(state_json.encode(), level=9)
    return _PROJECTION_CODEC_PREFIX + base64.b64encode(compressed).decode("ascii")


def _decode_projection_state(stored: str) -> str:
    """Decode current or legacy projection storage into canonical JSON text."""
    if not stored.startswith(_PROJECTION_CODEC_PREFIX):
        return stored
    try:
        payload = base64.b64decode(stored[len(_PROJECTION_CODEC_PREFIX):], validate=True)
        return zlib.decompress(payload).decode()
    except (ValueError, zlib.error, UnicodeDecodeError) as error:
        raise IntegrityError("record projection compression is invalid") from error


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
    elif action == "apply_application":
        # Snapshot mode retains the verified result directly. Event-log mode
        # stores only the governed domain input plus a result digest, allowing
        # large applications to grow with transition size instead of repeatedly
        # copying their complete state into every semantic event.
        value = operation["value"]
        application_id = value["application_id"]
        storage = value.get("storage", "snapshot")
        if storage == "snapshot":
            state[application_key(application_id)] = {
                "application_id": application_id,
                "application_version": value["application_version"],
                "state": value["next_state"],
            }
        elif storage == "event_log":
            key_name = application_key(application_id)
            prior = state.get(key_name)
            if prior is None:
                events = []
            elif (
                isinstance(prior, dict)
                and prior.get("application_id") == application_id
                and prior.get("application_version") == value["application_version"]
                and prior.get("storage") == "event_log"
                and isinstance(prior.get("events"), list)
            ):
                # Replay owns this fresh in-memory projection. Reuse its event
                # list instead of copying the full accumulated history for every
                # subsequent application event; copying here makes event-log
                # replay quadratic while adding no isolation boundary.
                events = prior["events"]
            else:
                raise IntegrityError(f"invalid application event-log envelope: {application_id}")
            events.append({
                "action": value["action"],
                "input": value.get("input"),
                "result_digest": value["result_digest"],
            })
            state[key_name] = {
                "application_id": application_id,
                "application_version": value["application_version"],
                "storage": "event_log",
                "events": events,
            }
        else:
            raise IntegrityError(f"unsupported application storage mode: {storage}")
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
        self._replayed_revision: int | None = None
        self._replayed_state: dict[str, JsonValue] | None = None

    def replay(self) -> tuple[int, dict[str, JsonValue]]:
        """Verify history and return the database-resident current projection."""
        revision, state = self._record.replay(self._connection)
        self._replayed_revision = revision
        self._replayed_state = state
        return revision, state

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

    def require_application_access(self, expected_generation: int) -> None:
        """Validate the global application latch inside the active write transaction."""
        self._record._require_application_access(self._connection, expected_generation)

    def append(
        self,
        event: EventAppend,
        projection_overrides: dict[str, JsonValue] | None = None,
    ) -> None:
        """
        Append one complete event inside the already-open write transaction.

        Commit/rollback belongs to Record.write_transaction, so no partial
        publication can occur between event fields.
        """
        cursor = self._connection.execute(
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
        if self._replayed_state is None or self._replayed_revision != event.revision_before:
            raise IntegrityError("append requires the verified transaction projection")

        state = self._replayed_state
        if event.status == "accepted":
            for operation in event.payload["operations"]:
                apply_operation(state, operation)
            for application_id, projection_state in (projection_overrides or {}).items():
                key_name = application_key(application_id)
                envelope = state.get(key_name)
                if not isinstance(envelope, dict) or envelope.get("storage") != "event_log":
                    raise IntegrityError(
                        f"application projection override has no event-log envelope: {application_id}"
                    )
                projected = dict(envelope)
                projected["projection_state"] = projection_state
                state[key_name] = projected

        state_json = canonical_json(state)
        state_digest = hashlib.sha256(state_json.encode()).hexdigest()
        self._connection.execute(
            """
            INSERT INTO record_projection (
                singleton, sequence, revision, event_hash, state, state_digest
            ) VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(singleton) DO UPDATE SET
                sequence = excluded.sequence,
                revision = excluded.revision,
                event_hash = excluded.event_hash,
                state = excluded.state,
                state_digest = excluded.state_digest
            """,
            (cursor.lastrowid, event.revision_after, event.event_hash, _encode_projection_state(state_json), state_digest),
        )
        self._replayed_revision = event.revision_after


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
                    context_receipt TEXT,
                    outcome TEXT CHECK (
                        outcome IS NULL OR outcome IN (
                            'success', 'temporary_failure', 'quota_exhausted', 'provider_failure',
                            'effect_barrier_failure'
                        )
                    ),
                    proposal_id TEXT,
                    receipt_id TEXT,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            invocation_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(invocation_events)")
            }
            if "context_receipt" not in invocation_columns:
                # v4 adds structured evidence describing the bounded context
                # delivered at the runtime boundary. Existing v3 rows remain
                # valid with NULL because their digest and revision still survive.
                connection.execute(
                    "ALTER TABLE invocation_events ADD COLUMN context_receipt TEXT"
                )
            if "outcome" not in invocation_columns:
                # v5 makes provider/runtime outcomes queryable without parsing
                # diagnostic strings. NULL remains truthful for older rows.
                connection.execute("ALTER TABLE invocation_events ADD COLUMN outcome TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS invocation_events_id_sequence "
                "ON invocation_events(invocation_id, sequence)"
            )

            # v6 makes the operational lifecycle independently tamper-evident.
            # Existing rows are deterministically backfilled in append order;
            # this does not alter proposal-event hashes or semantic state revision.
            invocation_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(invocation_events)")
            }
            if "event_id" not in invocation_columns:
                connection.execute("ALTER TABLE invocation_events ADD COLUMN event_id TEXT")
            if "previous_hash" not in invocation_columns:
                connection.execute("ALTER TABLE invocation_events ADD COLUMN previous_hash TEXT")
            if "event_hash" not in invocation_columns:
                connection.execute("ALTER TABLE invocation_events ADD COLUMN event_hash TEXT")

            previous_invocation_hash = GENESIS_HASH
            for row in connection.execute("SELECT * FROM invocation_events ORDER BY sequence"):
                event_id = row["event_id"] or f"legacy-invocation-{row['sequence']}"
                material = self._invocation_material(row, event_id=event_id)
                event_hash = hash_event(previous_invocation_hash, material)
                if (
                    row["event_id"] is None
                    or row["previous_hash"] is None
                    or row["event_hash"] is None
                ):
                    connection.execute(
                        """
                        UPDATE invocation_events
                        SET event_id = ?, previous_hash = ?, event_hash = ?
                        WHERE sequence = ?
                        """,
                        (event_id, previous_invocation_hash, event_hash, row["sequence"]),
                    )
                previous_invocation_hash = event_hash

            # v9 widens the invocation outcome contract to distinguish
            # durability-barrier failures from provider failures. SQLite cannot
            # alter a CHECK constraint in place, so existing v1-v8 databases
            # are rebuilt row-for-row after all older column/hash migrations
            # have completed. Sequence numbers, timestamps, IDs, and hashes are
            # preserved exactly.
            if 0 < version < 9:
                connection.execute(
                    "ALTER TABLE invocation_events RENAME TO invocation_events_v8"
                )
                connection.execute(
                    """
                    CREATE TABLE invocation_events (
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
                        context_receipt TEXT,
                        outcome TEXT CHECK (
                            outcome IS NULL OR outcome IN (
                                'success',
                                'temporary_failure',
                                'quota_exhausted',
                                'provider_failure',
                                'effect_barrier_failure'
                            )
                        ),
                        proposal_id TEXT,
                        receipt_id TEXT,
                        detail TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        event_id TEXT,
                        previous_hash TEXT,
                        event_hash TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO invocation_events (
                        sequence, invocation_id, stage, source_revision,
                        context_digest, provenance, context_receipt, outcome,
                        proposal_id, receipt_id, detail, created_at,
                        event_id, previous_hash, event_hash
                    )
                    SELECT
                        sequence, invocation_id, stage, source_revision,
                        context_digest, provenance, context_receipt, outcome,
                        proposal_id, receipt_id, detail, created_at,
                        event_id, previous_hash, event_hash
                    FROM invocation_events_v8
                    ORDER BY sequence
                    """
                )
                connection.execute("DROP TABLE invocation_events_v8")

            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS invocation_events_event_id "
                "ON invocation_events(event_id)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS invocation_events_event_hash "
                "ON invocation_events(event_hash)"
            )

            # v10 adds a single authoritative application-access latch plus an
            # append-only audit trail. This state is operational authority, not
            # semantic work state, so toggling it does not advance record revision.
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS application_access (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    generation INTEGER NOT NULL CHECK (generation >= 0),
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS application_access_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    generation INTEGER NOT NULL CHECK (generation >= 0),
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    event_id TEXT,
                    previous_hash TEXT,
                    event_hash TEXT
                )
                """
            )
            # v11 makes kill-switch transitions independently tamper-evident.
            # Existing v10 rows are deterministically backfilled in append order.
            access_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(application_access_events)")
            }
            if "event_id" not in access_columns:
                connection.execute("ALTER TABLE application_access_events ADD COLUMN event_id TEXT")
            if "previous_hash" not in access_columns:
                connection.execute("ALTER TABLE application_access_events ADD COLUMN previous_hash TEXT")
            if "event_hash" not in access_columns:
                connection.execute("ALTER TABLE application_access_events ADD COLUMN event_hash TEXT")
            previous_access_hash = GENESIS_HASH
            for row in connection.execute(
                "SELECT * FROM application_access_events ORDER BY sequence"
            ):
                event_id = row["event_id"] or f"legacy-application-access-{row['sequence']}"
                material = self._application_access_material(row, event_id=event_id)
                event_hash = hash_event(previous_access_hash, material)
                if (
                    row["event_id"] is None
                    or row["previous_hash"] is None
                    or row["event_hash"] is None
                ):
                    connection.execute(
                        """
                        UPDATE application_access_events
                        SET event_id = ?, previous_hash = ?, event_hash = ?
                        WHERE sequence = ?
                        """,
                        (event_id, previous_access_hash, event_hash, row["sequence"]),
                    )
                previous_access_hash = event_hash
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS application_access_events_event_id "
                "ON application_access_events(event_id)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS application_access_events_event_hash "
                "ON application_access_events(event_hash)"
            )
            if connection.execute(
                "SELECT 1 FROM application_access WHERE singleton = 1"
            ).fetchone() is None:
                connection.execute(
                    """
                    INSERT INTO application_access (singleton, enabled, generation, actor, reason)
                    VALUES (1, 1, 0, 'system', 'default enabled during schema initialization')
                    """
                )

            # v7 stores one derived current projection in the same authoritative
            # database. The append-only event chain remains reconstructable
            # evidence; this row removes repeated state reconstruction from
            # normal fresh-process reads.
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS record_projection (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    sequence INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    event_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    state_digest TEXT NOT NULL
                )
                """
            )
            projection = connection.execute(
                "SELECT state, state_digest FROM record_projection WHERE singleton = 1"
            ).fetchone()
            if projection is not None and version < 8:
                state_json = _decode_projection_state(projection["state"])
                if hashlib.sha256(state_json.encode()).hexdigest() != projection["state_digest"]:
                    raise IntegrityError("record projection state digest is invalid")
                connection.execute(
                    "UPDATE record_projection SET state = ? WHERE singleton = 1",
                    (_encode_projection_state(state_json),),
                )
            if projection is None:
                revision, state, sequence, event_hash = self._full_replay(connection)
                state_json = canonical_json(state)
                connection.execute(
                    """
                    INSERT INTO record_projection (
                        singleton, sequence, revision, event_hash, state, state_digest
                    ) VALUES (1, ?, ?, ?, ?, ?)
                    """,
                    (
                        sequence,
                        revision,
                        event_hash,
                        _encode_projection_state(state_json),
                        hashlib.sha256(state_json.encode()).hexdigest(),
                    ),
                )

            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
            return changed

    @staticmethod
    def _invocation_material(
        row: sqlite3.Row,
        *,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        """Rebuild the exact semantic material bound into an invocation hash."""
        return {
            "event_id": event_id if event_id is not None else row["event_id"],
            "invocation_id": row["invocation_id"],
            "stage": row["stage"],
            "source_revision": row["source_revision"],
            "context_digest": row["context_digest"],
            "provenance": json.loads(row["provenance"]) if row["provenance"] else None,
            "context_receipt": (
                json.loads(row["context_receipt"]) if row["context_receipt"] else None
            ),
            "outcome": row["outcome"],
            "proposal_id": row["proposal_id"],
            "receipt_id": row["receipt_id"],
            "detail": row["detail"],
        }

    @staticmethod
    def _allowed_invocation_next(stage: str | None) -> set[str]:
        """Return legal next stages for one invocation lifecycle."""
        return {
            None: {"requested"},
            "requested": {"context_delivered", "failed"},
            "context_delivered": {"attempt_started", "failed"},
            "attempt_started": {"proposal_received", "failed"},
            "proposal_received": {"governed", "failed"},
            "governed": {"completed", "failed"},
            "completed": set(),
            "failed": set(),
        }.get(stage, set())

    def _verified_invocation_history(
        self,
        connection: sqlite3.Connection,
    ) -> tuple[dict[str, Any], ...]:
        """Verify the global hash chain and each invocation's stage ordering."""
        previous_hash = GENESIS_HASH
        latest_stage: dict[str, str] = {}
        result: list[dict[str, Any]] = []
        rows = list(connection.execute("SELECT * FROM invocation_events ORDER BY sequence"))
        for row in rows:
            material = self._invocation_material(row)
            expected_hash = hash_event(previous_hash, material)
            if row["previous_hash"] != previous_hash or row["event_hash"] != expected_hash:
                raise IntegrityError(
                    f"invocation chain is invalid at sequence {row['sequence']}"
                )

            invocation_id = str(row["invocation_id"])
            stage = str(row["stage"])
            prior = latest_stage.get(invocation_id)
            if stage not in self._allowed_invocation_next(prior):
                # v3-v5 allowed lifecycle rows without stage-order enforcement.
                # Their deterministic migration IDs preserve that historical
                # truth while all v6+ writes are validated before append.
                if not str(row["event_id"]).startswith("legacy-invocation-"):
                    raise IntegrityError(
                        f"invalid invocation lifecycle transition {prior!r} -> {stage!r} "
                        f"for {invocation_id}"
                    )
            latest_stage[invocation_id] = stage
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

        Each lifecycle row is globally hash-linked and stage-validated before
        commit. It remains operational evidence, never a fabricated Proposal
        receipt and never a semantic-state revision by itself.
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
        context_receipt = (
            canonical_json(
                {
                    "policy_version": event.context_receipt.policy_version,
                    "payload_bytes": event.context_receipt.payload_bytes,
                    "included_categories": list(event.context_receipt.included_categories),
                    "scope": event.context_receipt.scope,
                }
            )
            if event.context_receipt is not None
            else None
        )
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
                if event.stage not in self._allowed_invocation_next(prior):
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
                    "context_receipt": (
                        {
                            "policy_version": event.context_receipt.policy_version,
                            "payload_bytes": event.context_receipt.payload_bytes,
                            "included_categories": list(event.context_receipt.included_categories),
                            "scope": event.context_receipt.scope,
                        }
                        if event.context_receipt is not None
                        else None
                    ),
                    "outcome": event.outcome,
                    "proposal_id": event.proposal_id,
                    "receipt_id": event.receipt_id,
                    "detail": event.detail,
                }
                event_hash = hash_event(previous_hash, material)
                connection.execute(
                    """
                    INSERT INTO invocation_events (
                        invocation_id, stage, source_revision, context_digest,
                        provenance, context_receipt, outcome, proposal_id, receipt_id, detail,
                        event_id, previous_hash, event_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.invocation_id,
                        event.stage,
                        event.source_revision,
                        event.context_digest,
                        provenance,
                        context_receipt,
                        event.outcome,
                        event.proposal_id,
                        event.receipt_id,
                        event.detail,
                        event_id,
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

        A fresh runtime may close these explicitly as interrupted failures. It
        must never infer that an external call succeeded.
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

    @staticmethod
    def _application_access_material(
        row: sqlite3.Row,
        *,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        """Rebuild the exact material bound into one access-transition hash."""
        return {
            "event_id": event_id if event_id is not None else row["event_id"],
            "enabled": bool(row["enabled"]),
            "generation": int(row["generation"]),
            "actor": str(row["actor"]),
            "reason": str(row["reason"]),
        }

    def _verified_application_access_history(
        self,
        connection: sqlite3.Connection,
    ) -> tuple[dict[str, Any], ...]:
        """Verify access-transition hashes, generations, and current latch head."""
        previous_hash = GENESIS_HASH
        previous_generation = 0
        history: list[dict[str, Any]] = []
        rows = list(connection.execute(
            "SELECT * FROM application_access_events ORDER BY sequence"
        ))
        for row in rows:
            if not row["event_id"] or not row["previous_hash"] or not row["event_hash"]:
                raise IntegrityError("application access event integrity metadata is missing")
            if row["previous_hash"] != previous_hash:
                raise IntegrityError("application access event previous hash is invalid")
            expected_hash = hash_event(
                previous_hash,
                self._application_access_material(row),
            )
            if row["event_hash"] != expected_hash:
                raise IntegrityError("application access event hash is invalid")
            generation = int(row["generation"])
            if generation != previous_generation + 1:
                raise IntegrityError("application access generation sequence is invalid")
            history.append({
                "sequence": int(row["sequence"]),
                "enabled": bool(row["enabled"]),
                "generation": generation,
                "actor": str(row["actor"]),
                "reason": str(row["reason"]),
                "changed_at": str(row["changed_at"]),
                "event_id": str(row["event_id"]),
                "previous_hash": str(row["previous_hash"]),
                "event_hash": str(row["event_hash"]),
            })
            previous_generation = generation
            previous_hash = str(row["event_hash"])

        latch = connection.execute(
            "SELECT enabled, generation, actor, reason FROM application_access WHERE singleton = 1"
        ).fetchone()
        if latch is None:
            raise IntegrityError("application access latch is missing")
        latch_generation = int(latch["generation"])
        if history:
            latest = history[-1]
            if (
                latch_generation != latest["generation"]
                or bool(latch["enabled"]) != latest["enabled"]
                or str(latch["actor"]) != latest["actor"]
                or str(latch["reason"]) != latest["reason"]
            ):
                raise IntegrityError("application access latch does not match verified audit head")
        elif latch_generation != 0:
            raise IntegrityError("application access latch has generation without audit history")
        return tuple(history)

    def application_access_history(self) -> tuple[dict[str, Any], ...]:
        """Return the fully verified operational kill-switch audit trail."""
        with self.connect() as connection:
            connection.execute("BEGIN")
            return self._verified_application_access_history(connection)

    @staticmethod
    def _access_state_from_row(row: sqlite3.Row) -> ApplicationAccessState:
        """Translate one latch row without leaking SQLite through the storage contract."""
        return ApplicationAccessState(
            enabled=bool(row["enabled"]),
            generation=int(row["generation"]),
            actor=str(row["actor"]),
            reason=str(row["reason"]),
            changed_at=str(row["changed_at"]),
        )

    def application_access_state(self) -> ApplicationAccessState:
        """Return the authoritative global application-access latch."""
        with self.connect() as connection:
            connection.execute("BEGIN")
            self._verified_application_access_history(connection)
            row = connection.execute(
                "SELECT enabled, generation, actor, reason, changed_at "
                "FROM application_access WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise IntegrityError("application access latch is missing")
        return self._access_state_from_row(row)

    def _require_application_access(
        self,
        connection: sqlite3.Connection,
        expected_generation: int,
    ) -> None:
        """Fail closed if access is off or changed since the caller captured it."""
        row = connection.execute(
            "SELECT enabled, generation FROM application_access WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise ApplicationAccessError()
        if not bool(row["enabled"]) or int(row["generation"]) != expected_generation:
            raise ApplicationAccessError()

    def require_application_access(self, expected_generation: int) -> None:
        """Verify app access in a fresh read transaction."""
        with self.connect() as connection:
            connection.execute("BEGIN")
            self._require_application_access(connection, expected_generation)

    def set_application_access(
        self,
        enabled: bool,
        *,
        actor: str,
        reason: str = "",
    ) -> ApplicationAccessState:
        """Atomically change the global latch and append its audit event."""
        if not actor.strip():
            raise ValueError("application access actor must not be empty")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT enabled, generation FROM application_access WHERE singleton = 1"
                ).fetchone()
                if row is None:
                    raise IntegrityError("application access latch is missing")
                current_enabled = bool(row["enabled"])
                generation = int(row["generation"])
                if current_enabled != enabled:
                    generation += 1
                    connection.execute(
                        """
                        UPDATE application_access
                        SET enabled = ?, generation = ?, actor = ?, reason = ?, changed_at = CURRENT_TIMESTAMP
                        WHERE singleton = 1
                        """,
                        (1 if enabled else 0, generation, actor.strip(), reason.strip()),
                    )
                    previous = connection.execute(
                        "SELECT event_hash FROM application_access_events "
                        "ORDER BY sequence DESC LIMIT 1"
                    ).fetchone()
                    previous_hash = previous["event_hash"] if previous else GENESIS_HASH
                    event_id = str(uuid.uuid4())
                    material = {
                        "event_id": event_id,
                        "enabled": bool(enabled),
                        "generation": generation,
                        "actor": actor.strip(),
                        "reason": reason.strip(),
                    }
                    event_hash = hash_event(previous_hash, material)
                    connection.execute(
                        """
                        INSERT INTO application_access_events (
                            enabled, generation, actor, reason,
                            event_id, previous_hash, event_hash
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            1 if enabled else 0,
                            generation,
                            actor.strip(),
                            reason.strip(),
                            event_id,
                            previous_hash,
                            event_hash,
                        ),
                    )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return self.application_access_state()

    def invocation_accounting(self) -> dict[str, int]:
        """Derive provider/runtime resource counts from verified lifecycle evidence."""
        history = self.invocation_history()
        return {
            "invocations": len({event["invocation_id"] for event in history}),
            "attempts": sum(event["stage"] == "attempt_started" for event in history),
            "completed": sum(event["stage"] == "completed" for event in history),
            "failed": sum(event["stage"] == "failed" for event in history),
            "quota_exhausted": sum(event["outcome"] == "quota_exhausted" for event in history),
            "temporary_failures": sum(event["outcome"] == "temporary_failure" for event in history),
            "provider_failures": sum(event["outcome"] == "provider_failure" for event in history),
        }

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
        verified = Record(destination)
        verified.full_replay()
        verified.invocation_history()
        verified.application_access_history()

    def compact(self) -> None:
        """
        Reclaim unused SQLite pages without changing semantic authority.

        This is intended for explicit maintenance after write-heavy migrations.
        The append-only event chain, revisions, hashes, and derived projection
        bytes remain semantically identical; only physical page layout changes.
        """
        before_revision, before_state = self.full_replay()
        with self.connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("VACUUM")
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        if quick_check != "ok":
            raise IntegrityError(f"database compaction failed SQLite quick_check: {quick_check}")
        after_revision, after_state = self.full_replay()
        if after_revision != before_revision or after_state != before_state:
            raise IntegrityError("database compaction changed authoritative state")

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
        verified = Record(destination)
        verified.replay()
        verified.invocation_history()
        verified.application_access_history()

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
            invocation_event_count = len(self._verified_invocation_history(connection))
            application_access_event_count = len(
                self._verified_application_access_history(connection)
            )
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            free_pages = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        return {
            "schema_version": SCHEMA_VERSION,
            "revision": revision,
            "event_count": event_count,
            "invocation_event_count": invocation_event_count,
            "application_access_event_count": application_access_event_count,
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
            invocation_event_count = len(self._verified_invocation_history(connection))
            application_access_event_count = len(
                self._verified_application_access_history(connection)
            )
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            free_pages = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        rows.reverse()
        health: dict[str, int | float | str] = {
            "schema_version": SCHEMA_VERSION,
            "revision": revision,
            "event_count": event_count,
            "invocation_event_count": invocation_event_count,
            "application_access_event_count": application_access_event_count,
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

    def _verified_chain(
        self, connection: sqlite3.Connection
    ) -> tuple[int, int, str]:
        """Verify semantic hashes and revision continuity without rebuilding state."""
        revision = 0
        previous_hash = GENESIS_HASH
        sequence = 0
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
            provenance = json.loads(row["provenance"]) if row["provenance"] else None
            if provenance is not None:
                material["provenance"] = provenance
            expected_hash = self.hash_event(previous_hash, material)
            if row["previous_hash"] != previous_hash or row["event_hash"] != expected_hash:
                raise IntegrityError(f"event chain is invalid at sequence {row['sequence']}")
            if row["revision_before"] != revision:
                raise IntegrityError(f"revision discontinuity at sequence {row['sequence']}")
            if row["status"] == "accepted":
                revision += 1
            if row["revision_after"] != revision:
                raise IntegrityError(f"invalid resulting revision at sequence {row['sequence']}")
            sequence = row["sequence"]
            previous_hash = row["event_hash"]
        return revision, sequence, previous_hash

    def _full_replay(
        self, connection: sqlite3.Connection
    ) -> tuple[int, dict[str, JsonValue], int, str]:
        """Verify and reconstruct state solely from append-only semantic events."""
        state: dict[str, JsonValue] = {}
        revision = 0
        previous_hash = GENESIS_HASH
        sequence = 0
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
            provenance = json.loads(row["provenance"]) if row["provenance"] else None
            if provenance is not None:
                material["provenance"] = provenance
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
            sequence = row["sequence"]
            previous_hash = row["event_hash"]
        return revision, state, sequence, previous_hash

    def full_replay(
        self, connection: sqlite3.Connection | None = None
    ) -> tuple[int, dict[str, JsonValue]]:
        """Explicitly reconstruct state from genesis for audit/recovery paths."""
        if connection is not None:
            revision, state, _, _ = self._full_replay(connection)
            return revision, state
        with self.connect() as own_connection:
            own_connection.execute("BEGIN")
            revision, state, _, _ = self._full_replay(own_connection)
            return revision, state

    def replay(self, connection: sqlite3.Connection | None = None) -> tuple[int, dict[str, JsonValue]]:
        """
        Load the atomically hash-bound current projection from the durable head.

        Normal reads validate the materialized checkpoint against the latest
        semantic event instead of rescanning genesis. Explicit full_replay()
        remains the complete historical integrity and drift-verification path.
        If the projection is unavailable or stale, replay falls back to full
        reconstruction.
        """
        if connection is None:
            with self.connect() as own_connection:
                own_connection.execute("BEGIN")
                return self.replay(own_connection)

        # Normal operational reads use the atomically committed, hash-bound
        # projection as their checkpoint.  Re-scanning genesis here would make
        # every fresh process O(history) and defeat the purpose of a durable
        # materialized projection.  The latest event row is sufficient to prove
        # that the checkpoint is current because append publishes the event and
        # checkpoint in one SQLite transaction.  Explicit full_replay() remains
        # the complete historical integrity/drift verification path.
        head = connection.execute(
            "SELECT sequence, revision_after, event_hash "
            "FROM events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        row = connection.execute(
            "SELECT * FROM record_projection WHERE singleton = 1"
        ).fetchone()
        if head is None:
            if row is None:
                return 0, {}
            # Schema initialization materializes the canonical empty checkpoint.
            # Accept only that exact revision-0/genesis shape; any other
            # projection without semantic history is inconsistent.
            if (
                row["sequence"] != 0
                or row["revision"] != 0
                or row["event_hash"] != GENESIS_HASH
            ):
                raise IntegrityError("record projection exists without semantic history")
            state_json = _decode_projection_state(row["state"])
            if hashlib.sha256(state_json.encode()).hexdigest() != row["state_digest"]:
                raise IntegrityError("record projection state digest is invalid")
            state = json.loads(state_json)
            if state != {}:
                raise IntegrityError("empty record projection contains semantic state")
            return 0, {}
        if (
            row is None
            or row["sequence"] != head["sequence"]
            or row["revision"] != head["revision_after"]
            or row["event_hash"] != head["event_hash"]
        ):
            # Missing/stale checkpoints are recoverable only by deterministic
            # reconstruction; a successfully reconstructed state can then be
            # materialized by the next governed append.
            full_revision, state, _, _ = self._full_replay(connection)
            return full_revision, state

        revision = int(row["revision"])
        state_json = _decode_projection_state(row["state"])
        if hashlib.sha256(state_json.encode()).hexdigest() != row["state_digest"]:
            raise IntegrityError("record projection state digest is invalid")
        state = json.loads(state_json)
        if not isinstance(state, dict):
            raise IntegrityError("record projection state is invalid")
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
