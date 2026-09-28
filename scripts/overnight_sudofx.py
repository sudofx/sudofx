"""
SUDOFX OVERNIGHT CONTINUITY RUNNER
==================================

One workflow invocation equals one fresh Gemini instance.

The model's proposal is governed only on an isolated SQLite snapshot. Production
work is never advanced from provider output. After the probe succeeds, this
adapter records a smaller system-owned fact in authoritative SQLite: what Gemini
said, which deterministic trial phase produced it, and the chained digest of
earlier observations. The next fresh Gemini receives that latest observation as
explicitly untrusted evidence.

This creates an evolving overnight conversation through sudofx without turning
model prose into truth or maintaining a second transcript file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import github_sudofx as cloud
from sudofx import Kernel, Operation, Proposal
from sudofx.models import Context
from sudofx.overnight import (
    EXPERIMENT_STATE_KEY,
    advance_experiment_state,
    build_trial_directive,
)
from sudofx.providers import CommandIntelligence, ProviderTemporaryError
from sudofx.record import Record
from sudofx.storage import GENESIS_HASH, canonical_json


def _checked_out_commit() -> str:
    """Identify the immutable source commit that actually executed this cycle."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if not commit:
        raise RuntimeError("could not identify checked-out runtime commit")
    return commit


def _digest_context(context: Context) -> str:
    """Fingerprint the exact bounded input shown to one fresh Gemini process."""
    payload = {
        "revision": context.revision,
        "state": context.state,
        "recent_receipts": context.recent_receipts,
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def _ensure_work(kernel: Kernel) -> Kernel:
    """Create the public-safe continuity work item exactly once."""
    context = kernel.context()
    key = f"work:{cloud.AUTO_HANDOFF_ID}"
    if key in context.state:
        return kernel
    receipt = kernel.submit(
        Proposal(
            str(uuid.uuid4()),
            context.revision,
            (
                Operation(
                    "create_work",
                    cloud.AUTO_HANDOFF_ID,
                    {
                        "objective": cloud.AUTO_HANDOFF_OBJECTIVE,
                        "constraints": [
                            "Gemini observations are evidence of model behavior, not authoritative project truth.",
                            "Only bounded derived context may cross the provider boundary.",
                        ],
                    },
                ),
            ),
            "Seed evolving continuity experiment",
        )
    )
    if receipt.status != "accepted":
        raise RuntimeError(f"automatic handoff creation was {receipt.status}")
    cloud.checkpoint()
    return Kernel(Record(cloud.DATA))


def _record_start(kernel: Kernel) -> Kernel:
    """Make the operator's Start durable before any fresh Gemini is invoked."""
    context = kernel.context()
    receipt = kernel.submit(
        Proposal(
            str(uuid.uuid4()),
            context.revision,
            (
                Operation(
                    "advance_work",
                    cloud.AUTO_HANDOFF_ID,
                    {
                        "result": "Operator explicitly authorized the evolving overnight Gemini continuity trial.",
                        "open_obligations": [
                            "Run bounded fresh-Gemini continuity cycles until the operator stops the chain; preserve model output as untrusted observation, not truth."
                        ],
                    },
                ),
            ),
            "Authenticated operator start transition for evolving continuity",
        )
    )
    if receipt.status != "accepted":
        raise RuntimeError(f"operator start transition was {receipt.status}")
    cloud.checkpoint()
    return Kernel(Record(cloud.DATA))


def _assert_running(kernel: Kernel, operator_start: bool) -> None:
    """
    Fail closed when durable work still says to await Start.

    GitHub workflow state is operational coordination. The durable obligation is
    the semantic boundary, so a stray manual dispatch cannot silently restart a
    stopped experiment without recording operator intent.
    """
    work = kernel.context(work_id=cloud.AUTO_HANDOFF_ID).state[f"work:{cloud.AUTO_HANDOFF_ID}"]
    obligations = work.get("open_obligations", [])
    if operator_start:
        return
    if isinstance(obligations, list) and any(
        isinstance(item, str) and "await explicit operator start" in item.lower()
        for item in obligations
    ):
        raise RuntimeError("overnight continuity is stopped; explicit operator Start is required")


def _probe(
    *,
    kernel: Kernel,
    previous_experiment: object,
    model: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Run one fresh Gemini proposal against a temporary snapshot.

    The compressed work shape preserves the already-proven one-milestone,
    zero-receipt handoff floor. The only added semantic material is the bounded
    trial directive and latest untrusted observation.
    """
    work_id = cloud.AUTO_HANDOFF_ID
    full = kernel.context(work_id=work_id, receipt_limit=100)
    work_key = f"work:{work_id}"
    work = full.state.get(work_key)
    if not isinstance(work, dict) or work.get("status") != "open":
        raise RuntimeError("overnight continuity requires the open handoff-v1 work item")

    results = work.get("accepted_results", [])
    assessments = work.get("semantic_assessments", [])
    if not isinstance(results, list) or not all(isinstance(item, str) for item in results):
        raise RuntimeError("handoff accepted results are malformed")
    if not isinstance(assessments, list) or not all(isinstance(item, dict) for item in assessments):
        raise RuntimeError("handoff semantic assessments are malformed")

    directive = build_trial_directive(previous_experiment)
    exposure = directive.get("exposure", {})
    result_limit = exposure.get("accepted_results_limit", 1)
    if result_limit not in (0, 1, 2):
        raise RuntimeError("overnight exposure profile has invalid accepted_results_limit")
    include_counts = exposure.get("include_counts", True)
    include_digests = exposure.get("include_digests", True)
    if not isinstance(include_counts, bool) or not isinstance(include_digests, bool):
        raise RuntimeError("overnight exposure profile has invalid count/digest controls")

    # The experiment now changes the packet itself, not merely the question.
    # Zero deliberately removes the last readable milestone while preserving its
    # count and digest so the model cannot confuse absence with nonexistence.
    recent = results[-result_limit:] if result_limit else []
    omitted = results[:-result_limit] if result_limit else list(results)

    compressed_work = dict(work)
    compressed_work.pop("accepted_results", None)
    compressed_work.pop("semantic_assessments", None)
    compressed_work["accepted_results_recent"] = recent
    if include_counts:
        compressed_work["accepted_result_count"] = len(results)
        compressed_work["omitted_accepted_results_count"] = len(omitted)
        compressed_work["semantic_assessment_count"] = len(assessments)
    if include_digests:
        compressed_work["omitted_accepted_results_digest"] = hashlib.sha256(
            canonical_json(omitted).encode()
        ).hexdigest()
        compressed_work["semantic_assessments_digest"] = hashlib.sha256(
            canonical_json(assessments).encode()
        ).hexdigest()
    compressed_work["continuity_trial"] = directive

    bounded = Context(
        revision=full.revision,
        state={work_key: compressed_work},
        recent_receipts=(),
    )
    digest = _digest_context(bounded)
    full_bytes = len(
        canonical_json(
            {
                "revision": full.revision,
                "state": full.state,
                "recent_receipts": full.recent_receipts,
            }
        ).encode()
    )
    bounded_bytes = len(
        canonical_json(
            {
                "revision": bounded.revision,
                "state": bounded.state,
                "recent_receipts": bounded.recent_receipts,
            }
        ).encode()
    )

    source_history = kernel.record.history()
    source_head = source_history[-1]["event_hash"] if source_history else GENESIS_HASH
    starting_revision = full.revision
    starting_work_revision = int(work.get("work_revision", 0))

    with tempfile.TemporaryDirectory() as temporary:
        snapshot_path = Path(temporary) / "overnight.sqlite"
        Record(cloud.DATA).backup_to(snapshot_path)
        snapshot_kernel = Kernel(Record(snapshot_path))
        intelligence = CommandIntelligence(
            (sys.executable, str(cloud.ROOT / "scripts" / "gemini_overnight_provider.py")),
            timeout_seconds=150,
        )
        proposal = intelligence.propose(bounded)
        receipt = snapshot_kernel.submit(proposal)
        if receipt.status != "accepted":
            raise RuntimeError(f"overnight Gemini proposal was {receipt.status}")

        after = Kernel(Record(snapshot_path)).context(work_id=work_id, receipt_limit=100)
        after_work = after.state[work_key]
        after_results = after_work.get("accepted_results", [])
        obligations = after_work.get("open_obligations", [])
        if not isinstance(after_results, list) or len(after_results) != len(results) + 1:
            raise AssertionError("snapshot did not append exactly one candidate result")
        if int(after_work.get("work_revision", -1)) != starting_work_revision + 1:
            raise AssertionError("snapshot did not advance work revision exactly once")
        if not isinstance(obligations, list):
            raise AssertionError("snapshot produced malformed obligations")
        candidate_result = after_results[-1]

    # The model itself must not have changed source authority. The only durable
    # write happens later, when the system records the response as observation.
    source_after = Kernel(Record(cloud.DATA))
    after_history = source_after.record.history()
    after_head = after_history[-1]["event_hash"] if after_history else GENESIS_HASH
    if source_after.context().revision != starting_revision or after_head != source_head:
        raise AssertionError("Gemini probe changed production authority")

    proof: dict[str, Any] = {
        "passed": True,
        "assessment_status": "semantic_review_pending",
        "kind": "evolving overnight Gemini continuity observation",
        "scope": "bounded derived context over isolated authoritative snapshot",
        "work_id": work_id,
        "provider": "Google Gemini",
        "model": model,
        "context_digest": digest,
        "source_event_head": source_head,
        "revision_before_provider": starting_revision,
        "revision_after_provider_on_snapshot": receipt.revision_after,
        "starting_work_revision": starting_work_revision,
        "candidate_result": candidate_result,
        "candidate_rationale": proposal.rationale,
        "candidate_open_obligations": obligations,
        "overnight_trial": directive,
        "exposure_profile": exposure,
        "compression": {
            "full_context_bytes": full_bytes,
            "compressed_context_bytes": bounded_bytes,
            "bytes_removed": full_bytes - bounded_bytes,
            "reduction_ratio": round(1 - (bounded_bytes / full_bytes), 4) if full_bytes else 0.0,
            "accepted_result_count": len(results),
            "accepted_results_exposed": len(recent),
            "accepted_results_omitted": len(omitted),
            "receipt_count_exposed": 0,
            "previous_model_observation_exposed": bool(
                exposure.get("include_previous_observation", True)
            ),
        },
        "semantic_review": {
            "version": 1,
            "status": "pending",
            "decision_options": ["pass", "fail", "uncertain"],
            "criteria": [
                {"id": "objective_fidelity", "status": "pending"},
                {"id": "history_fidelity", "status": "pending"},
                {"id": "frontier_fidelity", "status": "pending"},
                {"id": "compression_awareness", "status": "pending"},
                {"id": "unsupported_claims", "status": "pending"},
                {"id": "actionability", "status": "pending"},
            ],
            "evidence": {
                "objective": work.get("objective"),
                "constraints": work.get("constraints", []),
                "accepted_results": recent,
                "open_obligations": work.get("open_obligations", []),
                "candidate_result": candidate_result,
                "candidate_open_obligations": obligations,
                "context_digest": digest,
                "trial_cycle": directive["cycle"],
                "trial_phase": directive["phase"],
                "exposure_profile": exposure,
            },
        },
        "receipt": {
            "proposal_id": receipt.proposal_id,
            "status": receipt.status,
            "event_hash": receipt.event_hash,
        },
        "checks": {
            "provider_is_fresh_external_process": True,
            "previous_model_output_labeled_untrusted": True,
            "older_observations_not_exposed_as_transcript": True,
            "packet_exposure_selected_by_system_not_model": True,
            "proposal_crossed_governance_only_on_snapshot": True,
            "production_work_mutated_by_model": False,
        },
    }
    return proof, directive


def _record_observation(
    kernel: Kernel,
    *,
    previous_experiment: object,
    proof: dict[str, Any],
    directive: dict[str, Any],
    run_id: str,
) -> Kernel:
    """Persist the model response as experiment evidence without advancing work."""
    observation = {
        "cycle": directive["cycle"],
        "phase": directive["phase"],
        "task": directive["task"],
        "candidate_result": proof["candidate_result"],
        "candidate_rationale": proof["candidate_rationale"],
        "candidate_open_obligations": proof["candidate_open_obligations"],
        "context_digest": proof["context_digest"],
        "provider": proof["provider"],
        "model": proof["model"],
        "artifact_run_id": run_id,
        "source_event_head": proof["source_event_head"],
    }
    next_state = advance_experiment_state(
        previous_experiment,
        directive=directive,
        observation=observation,
    )
    context = kernel.context()
    receipt = kernel.submit(
        Proposal(
            str(uuid.uuid4()),
            context.revision,
            (Operation("set", EXPERIMENT_STATE_KEY, next_state),),
            "System-owned overnight observation; provider prose remains untrusted evidence",
        )
    )
    if receipt.status != "accepted":
        raise RuntimeError(f"overnight observation recording was {receipt.status}")
    cloud.checkpoint()
    return Kernel(Record(cloud.DATA))


def _patch_projection(proof: dict[str, Any]) -> None:
    """
    Correct the generic observer wording and expose the active trial lens.

    This edits only generated HTML. It never feeds presentation text back into
    SQLite or provider context.
    """
    path = cloud.ROOT / "site" / "index.html"
    if not path.exists():
        return
    html = path.read_text(encoding="utf-8")
    html = html.replace(
        "Governance accepted the proposal on an isolated verification snapshot. "
        "The durable record was not changed; the next test cycle starts automatically.",
        "Gemini's proposal was governed only on an isolated snapshot. sudofx then "
        "recorded the response as an untrusted observation in SQLite so the next "
        "fresh Gemini can inherit that bounded residue.",
    )
    trial = proof.get("overnight_trial", {})
    if isinstance(trial, dict):
        cycle = trial.get("cycle", "?")
        phase = str(trial.get("phase", "unknown")).upper().replace("_", " ")
        html = html.replace(
            '<span class="exchange-status" data-exchange-status>LAST EXCHANGE</span>',
            f'<span class="exchange-status" data-exchange-status>OVERNIGHT · CYCLE {cycle} · {phase}</span>',
        )
    path.write_text(html, encoding="utf-8")


def main() -> int:
    """Run one governed evolving continuity cycle and render the phone observer."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator-start", action="store_true")
    args = parser.parse_args()

    restored, restored_schema_changed = cloud.restore()
    cloud.DATA.parent.mkdir(parents=True, exist_ok=True)
    record = Record(cloud.DATA)
    kernel = Kernel(record)
    if restored and (restored_schema_changed or record.schema_changed):
        cloud.checkpoint()
        kernel = Kernel(Record(cloud.DATA))

    kernel = _ensure_work(kernel)
    if args.operator_start:
        kernel = _record_start(kernel)
    _assert_running(kernel, args.operator_start)

    global_context = kernel.context()
    previous_experiment = global_context.state.get(EXPERIMENT_STATE_KEY)
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        raise RuntimeError("GEMINI_API_KEY is required for evolving continuity")

    try:
        proof, directive = _probe(
            kernel=kernel,
            previous_experiment=previous_experiment,
            model=model,
        )
    except ProviderTemporaryError as error:
        # A disposable provider cycle is allowed to fail without poisoning the
        # durable chain. No authoritative state is changed, so the successor
        # safely retries the same cube coordinate with a fresh model process.
        print(
            json.dumps(
                {
                    "overnight_cycle_recovered": True,
                    "reason": str(error),
                    "authoritative_state_changed": False,
                    "next_cycle_retries_same_coordinate": True,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 0

    repository = os.environ.get("GITHUB_REPOSITORY", "sudofx/sudofx")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    proof["artifact_run_id"] = run_id
    # workflow_dispatch reports the current branch SHA even when actions/checkout
    # intentionally runs an immutable runtime_ref. Provenance must name the code
    # that actually executed, not the commit that happened to be at master when
    # the successor was dispatched.
    proof["artifact_commit"] = _checked_out_commit()

    # Persist only the observation after the model boundary has proved source
    # authority remained unchanged. This is the handoff residue the next fresh
    # Gemini inherits; it is not accepted work progress.
    kernel = _record_observation(
        kernel,
        previous_experiment=previous_experiment,
        proof=proof,
        directive=directive,
        run_id=run_id,
    )

    # Runtime cycles never rebuild or deploy GitHub Pages. They refresh one
    # replaceable public-safe projection after SQLite has been checkpointed.
    # Projection failure is visible in logs but cannot stop authoritative work
    # or the next fresh-model cycle.
    live_projection = dict(proof)
    live_projection["projection_schema"] = 1
    live_projection["projection_kind"] = "disposable-live-view"
    live_projection["source_run_id"] = run_id
    try:
        cloud.publish_live_projection(
            live_projection,
            handoff_packet=cloud.build_handoff_packet(kernel, cloud.AUTO_HANDOFF_ID),
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "live_projection_updated": False,
                    "live_projection_error": str(error),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )

    print(
        json.dumps(
            {
                "overnight_cycle": directive["cycle"],
                "phase": directive["phase"],
                "context_digest": proof["context_digest"],
                "observation_recorded": True,
                "production_work_mutated_by_model": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
