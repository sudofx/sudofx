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
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sudofx import Kernel, Operation, Proposal, SubmissionProvenance
from sudofx.record import Record
from sudofx.continuity import (
    run_compressed_model_continuity_probe,
    run_continuity_proof,
    run_default_model_continuity_probe,
    run_model_continuity_probe,
    run_work_continuity_probe,
)
from sudofx.report import export_site
from sudofx.handoff import build_handoff_packet, export_handoff_packet
from plugins.manual_handoff.scoring import (
    evaluate_handoff_response,
    handoff_packet_digest,
    handoff_work_id,
)
from sudofx.overnight import EXPERIMENT_STATE_KEY

DATA = ROOT / "data" / "sudofx.sqlite"
STATE_BRANCH = "sudofx-state"
LIVE_BRANCH = "sudofx-live"
AUTO_HANDOFF_ID = "handoff-v1"
AUTO_HANDOFF_OBJECTIVE = (
    "Test whether a fresh intelligence with no prior conversation can reconstruct sudofx: "
    "durable governed context must survive model replacement; WAKE✳︎ was the experimental "
    "predecessor; SQLite is authoritative; models propose and the system governs; the current "
    "frontier is proving portable continuity from sanitized context alone; working style favors "
    "plain language, compression, direct correction, and action over unnecessary explanation."
)


def latest_overnight_proof(kernel: Kernel) -> dict[str, object] | None:
    """Rebuild the public exchange from durable experiment state.

    Pages is deliberately independent from the Gemini runner, so publication
    cannot depend on a transient site artifact from that runner. The latest
    observation was already recorded in authoritative SQLite as untrusted model
    evidence; this helper projects that durable record back into the proof shape
    expected by the observer UI.
    """
    experiment = kernel.context().state.get(EXPERIMENT_STATE_KEY)
    if not isinstance(experiment, dict):
        return None
    observation = experiment.get("latest_observation")
    if not isinstance(observation, dict):
        return None
    candidate_result = observation.get("candidate_result")
    if not isinstance(candidate_result, str) or not candidate_result.strip():
        return None

    cycle = observation.get("cycle", experiment.get("cycle"))
    phase = observation.get("phase", experiment.get("phase"))
    task = observation.get("task", "")
    work = kernel.context(work_id=AUTO_HANDOFF_ID).state.get(f"work:{AUTO_HANDOFF_ID}", {})
    assessments = work.get("semantic_assessments", []) if isinstance(work, dict) else []
    matching_reviews: dict[str, dict[str, object]] = {}
    for assessment in reversed(assessments if isinstance(assessments, list) else []):
        if not isinstance(assessment, dict) or assessment.get("kind") != "human_semantic_review_v1":
            continue
        provenance = assessment.get("provenance", {})
        if (
            not isinstance(provenance, dict)
            or provenance.get("artifact_run_id") != observation.get("artifact_run_id")
            or provenance.get("context_digest") != observation.get("context_digest")
        ):
            continue
        reviewer = str(provenance.get("reviewer", "operator")).strip().lower()
        if reviewer in {"operator", "chatgpt"} and reviewer not in matching_reviews:
            matching_reviews[reviewer] = assessment

    reviewer_statuses = {
        reviewer: str(matching_reviews.get(reviewer, {}).get("verdict", "pending"))
        for reviewer in ("operator", "chatgpt")
    }
    if any(status == "pending" for status in reviewer_statuses.values()):
        review_status = "pending"
    elif any(status == "fail" for status in reviewer_statuses.values()):
        review_status = "fail"
    elif any(status == "uncertain" for status in reviewer_statuses.values()):
        review_status = "uncertain"
    else:
        review_status = "pass"

    review_criteria: dict[str, str] = {}
    criterion_names = (
        "objective_fidelity",
        "history_fidelity",
        "frontier_fidelity",
        "compression_awareness",
        "unsupported_claims",
        "actionability",
    )
    for criterion in criterion_names:
        values = []
        for reviewer in ("operator", "chatgpt"):
            criteria = matching_reviews.get(reviewer, {}).get("criteria", {})
            values.append(criteria.get(criterion, "pending") if isinstance(criteria, dict) else "pending")
        if "pending" in values:
            review_criteria[criterion] = "pending"
        elif "fail" in values:
            review_criteria[criterion] = "fail"
        elif "uncertain" in values:
            review_criteria[criterion] = "uncertain"
        else:
            review_criteria[criterion] = "pass"
    return {
        # Preserve the legacy generic flag for consumers that predate the
        # explicit proof contract; never let it stand in for semantic fidelity.
        "passed": True,
        "protocol_gate_passed": True,
        "semantic_review_status": review_status,
        # Keep runner continuation independent from human review. Recording a
        # verdict does not grant Stop/Start authority or terminate the experiment.
        "assessment_status": "semantic_review_pending",
        "kind": "evolving overnight Gemini continuity observation",
        "provider": observation.get("provider", "Google Gemini"),
        "model": observation.get("model", ""),
        "artifact_run_id": observation.get("artifact_run_id", ""),
        # Empty is deliberate for legacy observations that predate durable
        # runtime provenance. Never substitute a Pages renderer commit for the
        # model-execution commit.
        "artifact_commit": observation.get("artifact_commit", ""),
        "source_event_head": observation.get("source_event_head", ""),
        "context_digest": observation.get("context_digest", ""),
        "candidate_result": candidate_result,
        "candidate_rationale": observation.get("candidate_rationale", ""),
        "candidate_open_obligations": observation.get("candidate_open_obligations", []),
        "overnight_trial": {
            "version": experiment.get("version"),
            "cycle": cycle,
            "matrix_cycle": experiment.get("matrix_cycle"),
            "matrix_size": experiment.get("matrix_size"),
            "coordinate": experiment.get("coordinate", {}),
            "phase": phase,
            "task": task,
        },
        "semantic_review": {
            "version": 2,
            "status": review_status,
            "reviewers": {
                reviewer: {
                    "status": reviewer_statuses[reviewer],
                    "criteria": (
                        matching_reviews.get(reviewer, {}).get("criteria", {})
                        if isinstance(matching_reviews.get(reviewer, {}).get("criteria", {}), dict)
                        else {}
                    ),
                }
                for reviewer in ("operator", "chatgpt")
            },
            "criteria": [
                {"id": criterion, "status": review_criteria.get(criterion, "pending")}
                for criterion in criterion_names
            ],
            "evidence": {
                "candidate_result": candidate_result,
                "trial_cycle": cycle,
                "trial_phase": phase,
            },
        },
    }


def git(*args: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one explicit Git operation from the source repository."""
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def restore() -> tuple[bool, bool]:
    """
    Restore the remote durable database when the state branch exists.

    Missing state is valid only before the first mutation and returns
    ``(False, False)``. The second result reports a storage migration that must
    be checkpointed before projections can claim the new schema is durable.
    Other fetch or extraction failures remain exceptions; silently initializing
    after a damaged/unreadable branch would erase continuity.
    """
    # Absence is a valid first-run state; provider, permission, and transport
    # failures are not. Conflating them would let a temporary GitHub outage
    # silently replace durable continuity with a new empty record.
    remote = git("ls-remote", "--exit-code", "--heads", "origin", STATE_BRANCH, check=False, capture=True)
    if remote.returncode == 2:
        return False, False
    if remote.returncode != 0:
        raise RuntimeError(f"could not inspect durable state branch: {remote.stderr.strip()}")
    git("fetch", "origin", f"refs/heads/{STATE_BRANCH}:refs/remotes/origin/{STATE_BRANCH}")

    DATA.parent.mkdir(parents=True, exist_ok=True)
    # Restore into the destination directory so os.replace is atomic on the same
    # filesystem. The live path remains untouched unless both SQLite structure
    # and sudofx event replay verify successfully.
    with tempfile.NamedTemporaryFile(dir=DATA.parent, prefix="restore-", suffix=".sqlite", delete=False) as candidate:
        candidate_path = Path(candidate.name)
        shown = subprocess.run(
            ["git", "show", f"origin/{STATE_BRANCH}:sudofx.sqlite"],
            cwd=ROOT, check=False, stdout=candidate, stderr=subprocess.DEVNULL,
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
        # A stale WAL belongs to the replaced database identity and must never be
        # replayed against the new main file. This adapter is the sole process in
        # its Actions workspace, so sidecar removal is an owned recovery action.
        for suffix in ("-wal", "-shm"):
            Path(f"{DATA}{suffix}").unlink(missing_ok=True)
        os.replace(candidate_path, DATA)
    finally:
        candidate_path.unlink(missing_ok=True)
    return True, schema_changed


def checkpoint() -> None:
    """
    Commit the exact verified database to ``sudofx-state`` without rewriting history.

    An existing branch is checked out detached at its remote head. The first
    checkpoint starts an orphan branch so implementation files never become part
    of durable state. No-change checkpoints return without empty commits.
    """
    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / "verified.sqlite"
        # Snapshot through SQLite rather than copying the main file. This keeps
        # WAL-resident committed pages inside the checkpoint and verifies both
        # file structure and semantic replay before Git can publish new authority.
        Record(DATA).backup_to(snapshot)
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
            (checkout / "sudofx.sqlite").write_bytes(snapshot.read_bytes())
            git("-C", str(checkout), "add", "sudofx.sqlite")
            if git("-C", str(checkout), "diff", "--cached", "--quiet", check=False).returncode == 0:
                return

            # The bot identity labels provenance; it does not establish trust.
            # Trust comes from verified replay and protected repository access.
            git("-C", str(checkout), "-c", "user.name=sudofx-bot", "-c", "user.email=sudofx-bot@users.noreply.github.com", "commit", "-m", "Checkpoint durable record")
            git("-C", str(checkout), "push", "origin", f"HEAD:{STATE_BRANCH}")
        finally:
            git("worktree", "remove", "--force", str(checkout), check=False)


def frozen_overnight_proof(
    artifact_run_id: str,
    context_digest: str,
    current_kernel: Kernel,
) -> dict[str, object]:
    """Resolve the exact durable overnight observation a human actually reviewed.

    The continuity runner can advance several times while a person reads one
    answer. "Not latest anymore" is therefore not the same as "stale evidence."
    State-branch history contains verified SQLite checkpoints for prior cycles,
    so review binding searches that authoritative history rather than weakening
    provenance to whatever happens to be newest at workflow execution time.

    Disposable live.json is never read here. A run/digest pair that cannot be
    reconstructed from durable SQLite history still fails closed.
    """
    current = latest_overnight_proof(current_kernel)
    if (
        current is not None
        and str(current.get("artifact_run_id", "")) == artifact_run_id
        and str(current.get("context_digest", "")) == context_digest
    ):
        return current

    revisions = git("rev-list", f"origin/{STATE_BRANCH}", capture=True).stdout.splitlines()
    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / "historical-review.sqlite"
        for revision in revisions:
            with snapshot.open("wb") as destination:
                shown = subprocess.run(
                    ["git", "show", f"{revision}:sudofx.sqlite"],
                    cwd=ROOT, stdout=destination, stderr=subprocess.DEVNULL,
                )
            if shown.returncode != 0:
                continue
            try:
                candidate = latest_overnight_proof(Kernel(Record(snapshot)))
            except (ValueError, sqlite3.DatabaseError):
                continue
            if (
                candidate is not None
                and str(candidate.get("artifact_run_id", "")) == artifact_run_id
                and str(candidate.get("context_digest", "")) == context_digest
            ):
                return candidate
    raise ValueError("semantic review names no overnight observation in durable state history")


def frozen_handoff_packet(
    packet_digest: str,
    current_kernel: Kernel,
    work_id: str = AUTO_HANDOFF_ID,
) -> dict[str, object]:
    """Resolve the exact governed packet snapshot named by a returned answer.

    A manual handoff evaluation may be in flight while other governed work advances. The state
    branch is append-only Git history, so it can reproduce the packet that was
    actually tested without turning disposable Pages output into authority.
    """
    current = build_handoff_packet(current_kernel, work_id)
    if current.get("packet_digest") == packet_digest:
        return current

    revisions = git("rev-list", f"origin/{STATE_BRANCH}", capture=True).stdout.splitlines()
    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / "historical.sqlite"
        for revision in revisions:
            with snapshot.open("wb") as destination:
                shown = subprocess.run(
                    ["git", "show", f"{revision}:sudofx.sqlite"],
                    cwd=ROOT, stdout=destination, stderr=subprocess.DEVNULL,
                )
            if shown.returncode != 0:
                continue
            try:
                candidate = build_handoff_packet(Kernel(Record(snapshot)), work_id)
            except (ValueError, sqlite3.DatabaseError):
                continue
            if candidate.get("packet_digest") == packet_digest:
                return candidate
    raise ValueError("handoff response names no packet in durable state history")


def _read_live_projection_files() -> dict[str, str]:
    """Read the bounded disposable projection set without making it authority."""
    remote = git(
        "ls-remote", "--exit-code", "--heads", "origin", LIVE_BRANCH,
        check=False, capture=True,
    )
    if remote.returncode == 2:
        return {}
    if remote.returncode != 0:
        raise RuntimeError(f"could not inspect live projection branch: {remote.stderr.strip()}")
    git("fetch", "origin", f"refs/heads/{LIVE_BRANCH}:refs/remotes/origin/{LIVE_BRANCH}")

    files: dict[str, str] = {}
    for name in ("live.json", "handoff-v1.json", "handoff-current.json"):
        shown = git(
            "show", f"origin/{LIVE_BRANCH}:{name}",
            check=False, capture=True,
        )
        if shown.returncode == 0:
            files[name] = shown.stdout
    return files


def _replace_live_projection_files(files: dict[str, str]) -> None:
    """Force-replace the historyless live branch with one bounded projection set."""
    with tempfile.TemporaryDirectory() as temporary:
        checkout = Path(temporary) / "live"
        git("worktree", "add", "--detach", str(checkout), "HEAD")
        try:
            git("-C", str(checkout), "checkout", "--orphan", LIVE_BRANCH)
            git("-C", str(checkout), "rm", "-rf", "--ignore-unmatch", ".")
            for name, content in files.items():
                (checkout / name).write_text(content, encoding="utf-8")
            git("-C", str(checkout), "add", ".")
            git(
                "-C", str(checkout),
                "-c", "user.name=sudofx-bot",
                "-c", "user.email=sudofx-bot@users.noreply.github.com",
                "commit", "-m", "Refresh disposable live projection",
            )
            git("-C", str(checkout), "push", "--force", "origin", f"HEAD:{LIVE_BRANCH}")
        finally:
            git("worktree", "remove", "--force", str(checkout), check=False)


def build_manual_evaluation_projection(
    kernel: Kernel,
    work_id: str = AUTO_HANDOFF_ID,
) -> dict[str, object]:
    """Project compact manual-test evidence from authoritative SQLite state."""
    context = kernel.context()
    work = context.state.get(f"work:{work_id}", {})
    evaluations = work.get("handoff_evaluations", []) if isinstance(work, dict) else []
    if not isinstance(evaluations, list):
        evaluations = []
    clean = [item for item in evaluations if isinstance(item, dict)]
    latest = clean[-1] if clean else None
    comparable: list[dict[str, object]] = []
    if latest is not None:
        digest = latest.get("packet_digest")
        scorer = latest.get("scorer_version")
        comparable = [
            item for item in clean
            if item.get("packet_digest") == digest
            and item.get("scorer_version") == scorer
        ]
    vendors = sorted({
        str(item.get("vendor", "")).strip()
        for item in comparable
        if str(item.get("vendor", "")).strip()
    })
    score = sum(
        int(item.get("score", 0))
        for item in comparable
        if isinstance(item.get("score"), int)
    )
    recent = [
        {
            "vendor": item.get("vendor", ""),
            "test_id": item.get("test_id", ""),
            "score": item.get("score", 0),
            "scorer_version": item.get("scorer_version"),
            "packet_digest": item.get("packet_digest", ""),
        }
        for item in clean[-8:]
    ]
    return {
        "projection_schema": 1,
        "projection_kind": "disposable-manual-evaluation-view",
        "record_revision": context.revision,
        "work_id": work_id,
        "total_tests": len(clean),
        "latest": {
            "vendor": latest.get("vendor", ""),
            "test_id": latest.get("test_id", ""),
            "score": latest.get("score", 0),
            "scorer_version": latest.get("scorer_version"),
            "packet_digest": latest.get("packet_digest", ""),
        } if latest is not None else None,
        "comparable_batch": {
            "tests": len(comparable),
            "vendors": vendors,
            "score": score,
            "max_score": len(comparable) * 7,
            "packet_digest": latest.get("packet_digest", "") if latest is not None else "",
            "scorer_version": latest.get("scorer_version") if latest is not None else None,
        },
        "recent": recent,
    }


def publish_manual_evaluation_projection(payload: dict[str, object]) -> None:
    """Replace only the manual-test observer view without touching authority."""
    files = _read_live_projection_files()
    files["manual-evaluations.json"] = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    _replace_live_projection_files(files)


def publish_live_projection(
    payload: dict[str, object],
    handoff_packet: dict[str, object] | None = None,
    manual_evaluations: dict[str, object] | None = None,
) -> None:
    """Replace current observer projections while preserving the manual handoff view."""
    files = _read_live_projection_files()
    files["live.json"] = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if handoff_packet is not None:
        files["handoff-v1.json"] = json.dumps(
            handoff_packet, indent=2, sort_keys=True
        ) + "\n"
    if manual_evaluations is not None:
        files["manual-evaluations.json"] = json.dumps(
            manual_evaluations, indent=2, sort_keys=True
        ) + "\n"
    _replace_live_projection_files(files)


def publish_current_handoff(packet: dict[str, object]) -> None:
    """Publish the explicitly selected manual handoff as a disposable stable view."""
    files = _read_live_projection_files()
    files["handoff-current.json"] = json.dumps(
        packet, indent=2, sort_keys=True
    ) + "\n"
    _replace_live_projection_files(files)

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
    parser.add_argument("--prove-model")
    parser.add_argument("--prove-model-uncompressed")
    parser.add_argument("--prove-model-compressed")
    parser.add_argument("--compressed-results", type=int, default=4)
    parser.add_argument("--compressed-receipts", type=int, default=8)
    parser.add_argument("--export-handoff")
    parser.add_argument("--backup")
    parser.add_argument("--prove-vacuum-recovery", action="store_true")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--record-handoff-evaluation", action="store_true")
    parser.add_argument("--record-semantic-review", action="store_true")
    parser.add_argument("--record-chatgpt-semantic-review")
    parser.add_argument("--handoff-work-id", default="")
    parser.add_argument(
        "--action", choices=("set", "delete", "work-create", "work-advance", "record-assessment", "work-complete")
    )
    parser.add_argument("--key")
    parser.add_argument("--value", default="null")
    args = parser.parse_args()

    restored, restored_schema_changed = restore()
    # A first-ever run has no state branch, so the database parent must exist
    # before SQLite can create the empty authoritative record.
    DATA.parent.mkdir(parents=True, exist_ok=True)
    record = Record(DATA)
    kernel = Kernel(record)
    if restored and (restored_schema_changed or record.schema_changed):
        # Storage migrations are system-owned authority changes. Persist them
        # before any projection or semantic operation uses the newer schema.
        checkpoint()
        record = Record(DATA)
        kernel = Kernel(record)
    if args.record_semantic_review or args.record_chatgpt_semantic_review:
        # Human review is intentionally stricter than generic record-assessment.
        # Human reviews arrive through GitHub-controlled operator paths. ChatGPT
        # reviews arrive through the dedicated GitHub transport branch and have
        # their reviewer identity forced here rather than trusted from payload.
        if args.record_chatgpt_semantic_review:
            raw_review = Path(args.record_chatgpt_semantic_review).read_text(encoding="utf-8")
        else:
            raw_review = os.environ.get("SEMANTIC_REVIEW", "")
        try:
            submitted = json.loads(raw_review)
        except json.JSONDecodeError as error:
            raise ValueError("SEMANTIC_REVIEW must be one JSON object") from error
        if not isinstance(submitted, dict):
            raise ValueError("SEMANTIC_REVIEW must be one JSON object")
        submitted_run_id = submitted.get("artifact_run_id")
        submitted_digest = submitted.get("context_digest")
        if args.record_chatgpt_semantic_review:
            reviewer = "chatgpt"
        else:
            reviewer = str(submitted.get("reviewer", "operator")).strip().lower()
            if reviewer != "operator":
                raise ValueError("website semantic review reviewer must be operator")
        if not isinstance(submitted_run_id, str) or not submitted_run_id.strip():
            raise ValueError("semantic review requires artifact_run_id")
        if not isinstance(submitted_digest, str) or not submitted_digest.strip():
            raise ValueError("semantic review requires context_digest")
        proof = frozen_overnight_proof(
            submitted_run_id.strip(),
            submitted_digest.strip(),
            kernel,
        )
        expected_run_id = str(proof.get("artifact_run_id", ""))
        expected_digest = str(proof.get("context_digest", ""))
        criteria = submitted.get("criteria")
        allowed_criteria = {
            "objective_fidelity",
            "history_fidelity",
            "frontier_fidelity",
            "compression_awareness",
            "unsupported_claims",
            "actionability",
        }
        if (
            not isinstance(criteria, dict)
            or set(criteria) != allowed_criteria
            or any(value not in {"pass", "fail", "uncertain"} for value in criteria.values())
        ):
            raise ValueError("semantic review requires exactly six pass/fail/uncertain criteria")
        verdict = (
            "fail" if "fail" in criteria.values()
            else "uncertain" if "uncertain" in criteria.values()
            else "pass"
        )
        existing_work = kernel.context(work_id=AUTO_HANDOFF_ID).state.get(f"work:{AUTO_HANDOFF_ID}", {})
        existing_assessments = (
            existing_work.get("semantic_assessments", [])
            if isinstance(existing_work, dict)
            else []
        )
        for prior in existing_assessments if isinstance(existing_assessments, list) else []:
            provenance = prior.get("provenance", {}) if isinstance(prior, dict) else {}
            if (
                isinstance(provenance, dict)
                and provenance.get("artifact_run_id") == expected_run_id
                and provenance.get("context_digest") == expected_digest
                and provenance.get("reviewer", "operator") == reviewer
            ):
                raise RuntimeError("semantic review for this exact run, context, and reviewer is already recorded")

        provenance = {
            "artifact_run_id": expected_run_id,
            "context_digest": expected_digest,
            "reviewer": reviewer,
        }
        for key in ("artifact_commit", "provider", "model"):
            value = str(proof.get(key, "")).strip()
            if value:
                provenance[key] = value
        assessment = {
            "kind": "human_semantic_review_v1",
            "verdict": verdict,
            "criteria": criteria,
            "provenance": provenance,
        }
        context = kernel.context(work_id=AUTO_HANDOFF_ID)
        receipt = kernel.submit(
            Proposal(
                str(uuid.uuid4()),
                context.revision,
                (Operation("record_assessment", AUTO_HANDOFF_ID, assessment),),
                "Authenticated human semantic review bound to exact overnight evidence",
            ),
            provenance=SubmissionProvenance("human", reviewer, "github-actions"),
        )
        if receipt.status != "accepted":
            raise RuntimeError(f"semantic review recording was {receipt.status}: {receipt.reasons}")
        print(json.dumps({"semantic_review": assessment, "receipt": receipt.__dict__}, default=list))
        checkpoint()
        kernel = Kernel(Record(DATA))
        current_proof = latest_overnight_proof(kernel)
        if current_proof is not None:
            publish_live_projection(
                current_proof,
                build_handoff_packet(kernel, AUTO_HANDOFF_ID),
                build_manual_evaluation_projection(kernel, AUTO_HANDOFF_ID),
            )

    if args.backup:
        if not restored:
            raise RuntimeError("a recovery backup requires an existing authoritative record")
        backup_path = Path(args.backup)
        record.backup_to(backup_path)
        print(json.dumps({"backup": str(backup_path), "health": record.health()}, sort_keys=True))
        return 0
    if args.prove_vacuum_recovery:
        if not restored:
            raise RuntimeError("VACUUM recovery proof requires an existing authoritative record")
        before_revision, before_state = record.replay()
        before_history = record.history()
        before_head = before_history[-1]["event_hash"] if before_history else ""
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "vacuum-recovery.sqlite"
            record.vacuum_snapshot_to(snapshot)
            recovered_revision, recovered_state = Record(snapshot).replay()
            with closing(sqlite3.connect(snapshot)) as connection:
                integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        after_revision, after_state = record.replay()
        after_history = record.history()
        after_head = after_history[-1]["event_hash"] if after_history else ""
        checks = {
            "snapshot_integrity_check": integrity == "ok",
            "snapshot_revision_matches_authority": recovered_revision == before_revision,
            "snapshot_state_matches_authority": recovered_state == before_state,
            "authority_revision_unchanged": after_revision == before_revision,
            "authority_state_unchanged": after_state == before_state,
            "authority_event_head_unchanged": after_head == before_head,
        }
        if not all(checks.values()):
            raise AssertionError(f"VACUUM recovery proof failed: {checks}")
        print(json.dumps({"passed": True, "kind": "vacuum-into-recovery", "checks": checks}, sort_keys=True))
        return 0
    # Observer-mode automation: one stable operator command advances the current
    # milestone without asking the human to shuttle IDs or long text between devices.
    # The database remains authoritative: code may seed the work once, then all
    # subsequent exports derive from the governed record.
    auto_handoff_id: str | None = None
    if args.auto:
        context = kernel.context()
        work_key = f"work:{AUTO_HANDOFF_ID}"
        if work_key not in context.state:
            receipt = kernel.submit(
                Proposal(
                    str(uuid.uuid4()),
                    context.revision,
                    (
                        Operation(
                            "create_work",
                            AUTO_HANDOFF_ID,
                            {"objective": AUTO_HANDOFF_OBJECTIVE, "constraints": []},
                        ),
                    ),
                    "Observer-mode automatic milestone seed",
                ),
                provenance=SubmissionProvenance("runtime", "github-operations", "auto-handoff"),
            )
            if receipt.status != "accepted":
                raise RuntimeError(f"automatic handoff work creation was {receipt.status}")
            checkpoint()
            kernel = Kernel(Record(DATA))
        auto_handoff_id = AUTO_HANDOFF_ID
    if args.record_handoff_evaluation:
        raw_response = os.environ.get("HANDOFF_RESPONSE", "")
        response_work_id = handoff_work_id(raw_response)
        requested_work_id = args.handoff_work_id.strip()
        if requested_work_id and requested_work_id != response_work_id:
            raise ValueError("handoff workflow work ID does not match response work_id")
        selected_work_id = requested_work_id or response_work_id
        packet = frozen_handoff_packet(
            handoff_packet_digest(raw_response),
            kernel,
            selected_work_id,
        )
        result = evaluate_handoff_response(raw_response, packet)
        context = kernel.context()
        receipt = kernel.submit(
            Proposal(
                str(uuid.uuid4()), context.revision,
                (Operation("record_handoff_evaluation", selected_work_id, result),),
                # GitHub Actions supplies the authenticated operator boundary; the kernel remains the only path that can record the untrusted result.
                "GitHub operator submitted one human-transported handoff evaluation",
            ),
            provenance=SubmissionProvenance("human", "operator", "github-actions"),
        )
        if receipt.status != "accepted":
            raise RuntimeError(f"handoff evaluation was {receipt.status}: {receipt.reasons}")
        checkpoint()
        kernel = Kernel(Record(DATA))
        try:
            publish_manual_evaluation_projection(
                build_manual_evaluation_projection(kernel, selected_work_id)
            )
        except Exception as error:
            # The database commit is authoritative. A disposable observer-view
            # failure must not make a successfully recorded evaluation look
            # rejected or encourage the operator to replay the same response.
            print(
                json.dumps(
                    {
                        "manual_evaluation_projection_updated": False,
                        "manual_evaluation_projection_error": str(error),
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
    if not args.publish_only and not args.prove_work and not args.prove_model and not args.prove_model_uncompressed and not args.prove_model_compressed and not args.export_handoff and not args.prove_vacuum_recovery and not args.auto and not args.record_handoff_evaluation and not args.record_semantic_review and not args.record_chatgpt_semantic_review:
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
            # Workflow inputs are text transport, not authority. Accept either the
            # original plain result string or a structured object carrying the
            # current frontier. This preserves CLI parity and prevents a remote
            # operator from accidentally erasing open obligations.
            parsed = value_from(args.value)
            if isinstance(parsed, dict):
                result_text = parsed.get("result")
                open_obligations = parsed.get("open_obligations", [])
                if not isinstance(result_text, str) or not result_text.strip():
                    raise ValueError("work-advance structured value requires non-empty result text")
                if not isinstance(open_obligations, list) or not all(
                    isinstance(item, str) and item.strip() for item in open_obligations
                ):
                    raise ValueError("work-advance open_obligations must be non-empty strings")
                operation = Operation(
                    "advance_work",
                    args.key,
                    {"result": result_text.strip(), "open_obligations": open_obligations},
                )
            else:
                operation = Operation(
                    "advance_work", args.key, {"result": args.value, "open_obligations": []}
                )
        elif args.action == "record-assessment":
            parsed = value_from(args.value)
            if not isinstance(parsed, dict):
                raise ValueError("record-assessment requires a structured JSON object")
            operation = Operation("record_assessment", args.key, parsed)
        else:
            operation = Operation("complete_work", args.key, {"result": args.value})
        receipt = kernel.submit(
            Proposal(str(uuid.uuid4()), context.revision, (operation,), "GitHub operator proposal"),
            provenance=SubmissionProvenance("human", "operator", "github-actions"),
        )

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
    prove_work_id = args.prove_work.strip() if args.prove_work is not None else None
    prove_model_id = args.prove_model.strip() if args.prove_model is not None else None
    prove_model_uncompressed_id = args.prove_model_uncompressed.strip() if args.prove_model_uncompressed is not None else None
    prove_model_compressed_id = args.prove_model_compressed.strip() if args.prove_model_compressed is not None else None
    handoff_id = args.export_handoff.strip() if args.export_handoff is not None else None
    if args.prove_work is not None and not prove_work_id:
        parser.error("--prove-work requires a non-empty work ID")
    if args.prove_model is not None and not prove_model_id:
        parser.error("--prove-model requires a non-empty work ID")
    if args.prove_model_uncompressed is not None and not prove_model_uncompressed_id:
        parser.error("--prove-model-uncompressed requires a non-empty work ID")
    if args.prove_model_compressed is not None and not prove_model_compressed_id:
        parser.error("--prove-model-compressed requires a non-empty work ID")
    if args.export_handoff is not None and not handoff_id:
        parser.error("--export-handoff requires a non-empty work ID")
    selected_read_only = [value for value in (prove_work_id, prove_model_id, prove_model_uncompressed_id, prove_model_compressed_id, handoff_id, auto_handoff_id) if value]
    if len(selected_read_only) > 1:
        parser.error("--prove-work, --prove-model, --prove-model-uncompressed, --prove-model-compressed, --export-handoff, and --auto are mutually exclusive")

    if prove_model_id:
        # Normal live-model policy: provider context is a derived bounded view.
        # Full append-only work history remains authoritative in SQLite and is
        # used for governance/replay on the temporary snapshot.
        model = os.environ.get("GEMINI_MODEL", "").strip()
        if not model:
            parser.error("GEMINI_MODEL is required for --prove-model")
        continuity_proof = run_default_model_continuity_probe(
            DATA,
            prove_model_id,
            (sys.executable, str(ROOT / "scripts" / "gemini_provider.py")),
            provider="Google Gemini",
            model=model,
        )
    elif prove_model_uncompressed_id:
        # Explicit diagnostic baseline only. This preserves the old full-context
        # experiment so compression can be compared without making it the normal
        # model-facing policy.
        model = os.environ.get("GEMINI_MODEL", "").strip()
        if not model:
            parser.error("GEMINI_MODEL is required for --prove-model-uncompressed")
        continuity_proof = run_model_continuity_probe(
            DATA,
            prove_model_uncompressed_id,
            (sys.executable, str(ROOT / "scripts" / "gemini_provider.py")),
            provider="Google Gemini",
            model=model,
        )
    elif prove_model_compressed_id:
        model = os.environ.get("GEMINI_MODEL", "").strip()
        if not model:
            parser.error("GEMINI_MODEL is required for --prove-model-compressed")
        continuity_proof = run_compressed_model_continuity_probe(
            DATA,
            prove_model_compressed_id,
            (sys.executable, str(ROOT / "scripts" / "gemini_provider.py")),
            provider="Google Gemini",
            model=model,
            recent_result_limit=args.compressed_results,
            receipt_limit=args.compressed_receipts,
        )
    elif prove_work_id:
        continuity_proof = run_work_continuity_probe(DATA, prove_work_id)
    elif auto_handoff_id:
        # Continuous observer mode deliberately asks a fresh Gemini invocation
        # on every bounded cycle. Its proposal is evaluated only on a temporary
        # snapshot, so nonstop testing cannot silently advance authoritative work.
        # The proof is published for inspection but is not appended to SQLite;
        # otherwise an around-the-clock probe would manufacture unbounded durable
        # history whose only meaning was that another test happened to run.
        model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
        if not os.environ.get("GEMINI_API_KEY", "").strip():
            raise RuntimeError("GEMINI_API_KEY is required for observer-mode handoff")
        continuity_proof = run_default_model_continuity_probe(
            DATA,
            auto_handoff_id,
            (sys.executable, str(ROOT / "scripts" / "gemini_provider.py")),
            provider="Google Gemini",
            model=model,
        )
        if continuity_proof.get("assessment_status") != "semantic_review_pending":
            raise AssertionError("observer model probe did not reach semantic review")
    else:
        # Independent Pages publication must recover the latest completed Gemini
        # exchange from SQLite rather than falling back to a synthetic proof and
        # erasing the answer that the continuity runner just recorded.
        continuity_proof = latest_overnight_proof(kernel) or run_continuity_proof()
    # Projection metadata binds a disposable proof artifact to the exact Actions
    # run that produced it. Repeated probes can share the same context digest, so
    # run identity—not digest inequality—is the stale-result discriminator.
    continuity_proof = dict(continuity_proof)
    # Preserve the Gemini run that produced the exchange. Publication has its own
    # provenance so a later Pages rebuild cannot masquerade as the model source.
    continuity_proof.setdefault("artifact_run_id", run_id)
    continuity_proof.setdefault("artifact_commit", verification["commit"])
    continuity_proof["projection_run_id"] = run_id
    continuity_proof["projection_commit"] = verification["commit"]
    export_site(
        kernel,
        ROOT / "site",
        repository=repository,
        verification=verification,
        continuity_proof=continuity_proof,
    )
    # Explicit one-shot probes are diagnostic evidence. Emit their bounded
    # proof to the Actions log so the result survives the disposable runner
    # without creating another durable state artifact or requiring Pages.
    if prove_work_id or prove_model_id or prove_model_uncompressed_id or prove_model_compressed_id:
        print(json.dumps({"continuity_proof": continuity_proof}, sort_keys=True))
    export_id = handoff_id or auto_handoff_id
    if export_id:
        json_path, prompt_path = export_handoff_packet(kernel, ROOT / "site", export_id)
        if handoff_id:
            publish_current_handoff(build_handoff_packet(kernel, handoff_id))
        print(json.dumps({"handoff_json": str(json_path), "handoff_prompt": str(prompt_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
