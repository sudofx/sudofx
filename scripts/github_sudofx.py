"""
SUDOFX GITHUB OPERATIONS ADAPTER
================================

This script bridges an ephemeral GitHub Actions runner to the durable sudofx
record. The runner itself has no continuity. Before a stateful operation it
restores the latest ``sudofx-state`` branch, verifies that record through Kernel,
submits exactly one governed proposal, checkpoints the database, and renders the
public projection.

There are deliberately three different authorities:

    master        -> implementation and workflow definition
    sudofx-state  -> durable SQLite record
    Pages artifact-> disposable, derived public projection

The published HTML is never read back as state. The source branch never embeds
the live database. A stateful run pushes the record before publishing so a
successful page can never advertise a transition that was not first made
durable.

GitHub workflow concurrency serializes stateful runs. Kernel's SQLite transaction
and proposal revision still enforce correctness because workflow configuration
is operational coordination, not the final authority boundary.

This entry point performs Git operations only inside the repository or a newly
created temporary worktree. It never force-pushes durable history. A push conflict
must fail visibly rather than choosing one writer's history by accident.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from sudofx import Kernel, Operation, Proposal
from sudofx.record import Record
from sudofx.continuity import run_continuity_proof, run_work_continuity_probe
from sudofx.report import export_site

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "sudofx.sqlite"
STATE_BRANCH = "sudofx-state"


def git(*args: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one explicit Git operation from the source repository."""
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def restore() -> bool:
    """
    Restore the remote durable database when the state branch exists.

    Missing state is valid only before the first mutation and returns False.
    Other fetch or extraction failures remain exceptions; silently initializing
    after a damaged/unreadable branch would erase continuity.
    """
    fetched = git("fetch", "origin", STATE_BRANCH, check=False, capture=True)
    if fetched.returncode != 0:
        return False
    DATA.parent.mkdir(parents=True, exist_ok=True)
    with DATA.open("wb") as destination:
        subprocess.run(
            ["git", "show", f"origin/{STATE_BRANCH}:sudofx.sqlite"],
            cwd=ROOT, check=True, stdout=destination,
        )
    return True


def checkpoint() -> None:
    """
    Commit the exact verified database to ``sudofx-state`` without rewriting history.

    An existing branch is checked out detached at its remote head. The first
    checkpoint starts an orphan branch so implementation files never become part
    of durable state. No-change checkpoints return without empty commits.
    """
    with tempfile.TemporaryDirectory() as temporary:
        checkout = Path(temporary) / "state"
        branch_exists = git("rev-parse", "--verify", f"origin/{STATE_BRANCH}", check=False, capture=True).returncode == 0
        if branch_exists:
            # Detached checkout makes the eventual push target explicit and
            # avoids teaching the temporary worktree a misleading local branch.
            git("worktree", "add", "--detach", str(checkout), f"origin/{STATE_BRANCH}")
        else:
            # The first checkpoint starts from source only as a Git worktree
            # bootstrap. The orphan ref prevents that source ancestry from
            # becoming state history.
            git("worktree", "add", "--detach", str(checkout), "HEAD")
            git("-C", str(checkout), "checkout", "--orphan", STATE_BRANCH)
        try:
            # The state branch has exactly one current-tree authority artifact:
            # the SQLite database. Removing every tracked path before re-adding
            # it also repairs older contaminated state heads without rewriting
            # history or changing the database bytes.
            git("-C", str(checkout), "rm", "-rf", "--ignore-unmatch", ".")
            (checkout / "sudofx.sqlite").write_bytes(DATA.read_bytes())
            git("-C", str(checkout), "add", "sudofx.sqlite")
            if git("-C", str(checkout), "diff", "--cached", "--quiet", check=False).returncode == 0:
                return

            # The bot identity labels provenance; it does not establish trust.
            # Trust comes from verified replay and protected repository access.
            git("-C", str(checkout), "-c", "user.name=sudofx-bot", "-c", "user.email=sudofx-bot@users.noreply.github.com", "commit", "-m", "Checkpoint durable record")
            git("-C", str(checkout), "push", "origin", f"HEAD:{STATE_BRANCH}")
        finally:
            git("worktree", "remove", "--force", str(checkout), check=False)


def value_from(raw: str) -> object:
    """Share the CLI convention: structured JSON when valid, plain text otherwise."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def main() -> int:
    """
    Execute either a read-only publication or one serialized governed mutation.

    Publish-only runs may initialize a temporary empty local database when no
    state branch exists, but they never checkpoint it. Stateful runs require an
    action and key, append one receipt, checkpoint, then render that same state.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish-only", action="store_true")
    parser.add_argument("--prove-work")
    parser.add_argument(
        "--action", choices=("set", "delete", "work-create", "work-advance", "work-complete")
    )
    parser.add_argument("--key")
    parser.add_argument("--value", default="null")
    args = parser.parse_args()

    restored = restore()
    # A first-ever run has no state branch, so the database parent must exist
    # before SQLite can create the empty authoritative record.
    DATA.parent.mkdir(parents=True, exist_ok=True)
    kernel = Kernel(Record(DATA))
    if not args.publish_only and not args.prove_work:
        if not args.action or not args.key:
            parser.error("--action and --key are required for a mutation")
        context = kernel.context()
        # Workflow strings are mapped into the same typed operations as the CLI.
        # GitHub inputs cannot supply lifecycle-owned status or revisions.
        if args.action == "set":
            operation = Operation("set", args.key, value_from(args.value))
        elif args.action == "delete":
            operation = Operation("delete", args.key)
        elif args.action == "work-create":
            operation = Operation(
                "create_work", args.key, {"objective": args.value, "constraints": []}
            )
        elif args.action == "work-advance":
            operation = Operation(
                "advance_work", args.key, {"result": args.value, "open_obligations": []}
            )
        else:
            operation = Operation("complete_work", args.key, {"result": args.value})
        receipt = kernel.submit(Proposal(str(uuid.uuid4()), context.revision, (operation,), "GitHub operator proposal"))

        # Checkpoint precedes export. A failed push stops publication so Pages
        # cannot get ahead of the durable branch.
        print(json.dumps({"restored": restored, "receipt": receipt.__dict__}, default=list))
        checkpoint()
    # Verification metadata is projection-only evidence from the current Actions
    # run. It never enters the database or governance path. Because this script is
    # reached only after the workflow's test gate succeeds, the page can state
    # exactly which source commit and Actions run produced the visible projection.
    repository = os.environ.get("GITHUB_REPOSITORY", "sudofx/sudofx")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    verification = {
        "commit": os.environ.get("GITHUB_SHA", ""),
        "run_id": run_id,
        "run_url": (
            f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repository}/actions/runs/{run_id}"
            if run_id
            else ""
        ),
    }
    # A phone-triggered real-work probe uses a temporary SQLite snapshot of the
    # restored authoritative record. Ordinary publication runs the synthetic
    # deterministic fixture so every build still checks the mechanism.
    continuity_proof = (
        run_work_continuity_probe(DATA, args.prove_work)
        if args.prove_work
        else run_continuity_proof()
    )
    export_site(
        kernel,
        ROOT / "site",
        repository=repository,
        verification=verification,
        continuity_proof=continuity_proof,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
