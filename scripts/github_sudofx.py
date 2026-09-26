"""GitHub Actions adapter: restore, mutate, verify, publish, and checkpoint."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from sudofx import Kernel, Operation, Proposal
from sudofx.record import Record
from sudofx.report import export_site

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "sudofx.sqlite"
STATE_BRANCH = "sudofx-state"


def git(*args: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def restore() -> bool:
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
    with tempfile.TemporaryDirectory() as temporary:
        checkout = Path(temporary) / "state"
        branch_exists = git("rev-parse", "--verify", f"origin/{STATE_BRANCH}", check=False, capture=True).returncode == 0
        if branch_exists:
            git("worktree", "add", "--detach", str(checkout), f"origin/{STATE_BRANCH}")
        else:
            git("worktree", "add", "--detach", str(checkout), "HEAD")
            git("-C", str(checkout), "checkout", "--orphan", STATE_BRANCH)
            for child in checkout.iterdir():
                if child.name != ".git":
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
        try:
            (checkout / "sudofx.sqlite").write_bytes(DATA.read_bytes())
            git("-C", str(checkout), "add", "sudofx.sqlite")
            if git("-C", str(checkout), "diff", "--cached", "--quiet", check=False).returncode == 0:
                return
            git("-C", str(checkout), "-c", "user.name=sudofx-bot", "-c", "user.email=sudofx-bot@users.noreply.github.com", "commit", "-m", "Checkpoint durable record")
            git("-C", str(checkout), "push", "origin", f"HEAD:{STATE_BRANCH}")
        finally:
            git("worktree", "remove", "--force", str(checkout), check=False)


def value_from(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish-only", action="store_true")
    parser.add_argument("--action", choices=("set", "delete"))
    parser.add_argument("--key")
    parser.add_argument("--value", default="null")
    args = parser.parse_args()

    restored = restore()
    kernel = Kernel(Record(DATA))
    if not args.publish_only:
        if not args.action or not args.key:
            parser.error("--action and --key are required for a mutation")
        context = kernel.context()
        operation = Operation(args.action, args.key, value_from(args.value))
        receipt = kernel.submit(Proposal(str(uuid.uuid4()), context.revision, (operation,), "GitHub operator proposal"))
        print(json.dumps({"restored": restored, "receipt": receipt.__dict__}, default=list))
        checkpoint()
    export_site(kernel, ROOT / "site", repository=os.environ.get("GITHUB_REPOSITORY", "sudofx/sudofx"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
