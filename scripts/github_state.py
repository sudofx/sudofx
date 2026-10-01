"""
GITHUB STATE TRANSPORT ADAPTER
==============================

This module is replaceable infrastructure around the authoritative sudofx database.

GitHub is not part of kernel semantics. It is currently one transport for moving
a verified SQLite checkpoint between disposable runners. The adapter restores
only a database snapshot, verifies SQLite integrity plus sudofx replay before
installation, and checkpoints through SQLite's backup API so WAL-resident commits
cannot be omitted.

No experiment, provider, application, presentation, or governance meaning belongs
here. A future object store, private database host, or other transport can replace
this module without changing the kernel or durable record contract.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path

from sudofx.record import Record


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "sudofx.sqlite"
STATE_BRANCH = "sudofx-state"


def git(*args: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one explicit Git operation from the source repository."""
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def restore() -> tuple[bool, bool]:
    """
    Restore and verify the remote database snapshot when the state branch exists.

    Missing state is valid only before the first checkpoint. Provider, permission,
    transport, corrupt-file, and replay failures stay visible rather than falling
    back to a new empty authority.
    """
    remote = git(
        "ls-remote",
        "--exit-code",
        "--heads",
        "origin",
        STATE_BRANCH,
        check=False,
        capture=True,
    )
    if remote.returncode == 2:
        return False, False
    if remote.returncode != 0:
        raise RuntimeError(f"could not inspect durable state branch: {remote.stderr.strip()}")
    git("fetch", "origin", f"refs/heads/{STATE_BRANCH}:refs/remotes/origin/{STATE_BRANCH}")

    DATA.parent.mkdir(parents=True, exist_ok=True)
    # The candidate lives beside the destination so final replacement is atomic
    # on one filesystem. Authority never points at partially verified bytes.
    with tempfile.NamedTemporaryFile(
        dir=DATA.parent,
        prefix="restore-",
        suffix=".sqlite",
        delete=False,
    ) as candidate:
        candidate_path = Path(candidate.name)
        shown = subprocess.run(
            ["git", "show", f"origin/{STATE_BRANCH}:sudofx.sqlite"],
            cwd=ROOT,
            check=False,
            stdout=candidate,
            stderr=subprocess.DEVNULL,
        )
    if shown.returncode != 0:
        candidate_path.unlink(missing_ok=True)
        return False, False

    try:
        with closing(sqlite3.connect(candidate_path)) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"restored database failed SQLite quick_check: {result}")
        candidate_record = Record(candidate_path)
        candidate_record.replay()
        schema_changed = candidate_record.schema_changed

        # Sidecars belong to the database identity they were created beside. A
        # stale WAL must never replay into a newly installed verified snapshot.
        for suffix in ("-wal", "-shm"):
            Path(f"{DATA}{suffix}").unlink(missing_ok=True)
        os.replace(candidate_path, DATA)
    finally:
        candidate_path.unlink(missing_ok=True)
    return True, schema_changed


def checkpoint() -> None:
    """
    Publish one verified SQLite snapshot to the Git state transport.

    The state branch carries one current-tree authority artifact: sudofx.sqlite.
    Git history is transport history; the database remains the operational source
    of truth and is independently replay-verified before publication.
    """
    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / "verified.sqlite"
        Record(DATA).backup_to(snapshot)
        checkout = Path(temporary) / "state"
        branch_exists = (
            git(
                "rev-parse",
                "--verify",
                f"origin/{STATE_BRANCH}",
                check=False,
                capture=True,
            ).returncode
            == 0
        )
        if branch_exists:
            git("worktree", "add", "--detach", str(checkout), f"origin/{STATE_BRANCH}")
        else:
            git("worktree", "add", "--detach", str(checkout), "HEAD")
            git("-C", str(checkout), "checkout", "--orphan", STATE_BRANCH)

        try:
            git("-C", str(checkout), "rm", "-rf", "--ignore-unmatch", ".")
            (checkout / "sudofx.sqlite").write_bytes(snapshot.read_bytes())
            git("-C", str(checkout), "add", "sudofx.sqlite")
            if (
                git(
                    "-C",
                    str(checkout),
                    "diff",
                    "--cached",
                    "--quiet",
                    check=False,
                ).returncode
                == 0
            ):
                return

            git(
                "-C",
                str(checkout),
                "-c",
                "user.name=sudofx-bot",
                "-c",
                "user.email=sudofx-bot@users.noreply.github.com",
                "commit",
                "-m",
                "Checkpoint durable record",
            )
            git("-C", str(checkout), "push", "origin", f"HEAD:{STATE_BRANCH}")
        finally:
            git("worktree", "remove", "--force", str(checkout), check=False)
