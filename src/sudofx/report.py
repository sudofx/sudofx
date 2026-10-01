"""
SUDOFX PUBLIC PROJECTION
========================

This module turns verified replayed state into a self-contained, phone-friendly
HTML artifact. The artifact is a projection: useful for inspection and navigation,
but never an input to governance, replay, or recovery.

Rendering is intentionally dependency-free so a fresh GitHub runner can publish
without a JavaScript toolchain or package registry. State-derived text is escaped
before interpolation. Interactive behavior is limited to live observer telemetry, the public manual
continuity workbench, history filtering, disclosure, and theme preference.

The browser receives no GitHub token and cannot mutate the record directly.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .handoff import HANDOFF_WORK_ID, build_handoff_packet, export_handoff_packet
from .kernel import Kernel
from .models import Context


def _escape(value: object) -> str:
    """Escape all durable or operator text before placing it in HTML attributes or content."""
    return html.escape(str(value), quote=True)


def _format_bytes(value: object) -> str:
    """Format a byte count for the compact operator view.

    SQLite remains authoritative for the integer byte count; this conversion is
    presentation only. Binary 1024-byte thresholds keep the displayed magnitude
    stable as the database crosses B, KB, MB, and GB boundaries, while the short
    labels match the phone interface's requested vocabulary.
    """
    size = max(0, int(value))
    units = ("B", "KB", "MB", "GB")
    unit_index = 0
    amount = float(size)
    while amount >= 1024 and unit_index < len(units) - 1:
        amount /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{size} B"
    precision = 0 if amount >= 100 else 1
    number = f"{amount:.0f}" if precision == 0 else f"{amount:.1f}".rstrip("0").rstrip(".")
    return f"{number} {units[unit_index]}"


def _public_model_response(proof: dict[str, object]) -> str:
    """Translate stored model output into a plain-language public reading view.

    The public technical view still exposes exact durable work and receipt
    material. This helper changes presentation only; it never rewrites evidence.
    """
    raw = str(proof.get("candidate_result", "")).strip()
    if not raw:
        return "No Gemini answer has been published yet."

    # New overnight responses are already written for a human reader.
    if raw.startswith("Gemini understood:"):
        return raw

    # Older continuity probes used transport-oriented labels. Preserve their
    # actual content while removing labels that make the public page read like
    # an internal test report.
    if raw.startswith("Reconstruction:"):
        label = None
        if " Chosen action:" in raw:
            label = " Chosen action:"
        elif " Proposed next step:" in raw:
            label = " Proposed next step:"
        if label:
            understood, rest = raw[len("Reconstruction:"):].split(label, 1)
            suggestion = rest
            verification = ""
            if " Verification:" in suggestion:
                suggestion, verification = suggestion.split(" Verification:", 1)
            if " Target:" in suggestion:
                suggestion = suggestion.split(" Target:", 1)[0]
            text = f"Gemini understood: {understood.strip()} Gemini suggests: {suggestion.strip()}"
            if verification.strip():
                text += f" We would know it worked if: {verification.strip()}"
            return text

    return raw


def _work_cards(state: dict[str, object]) -> str:
    """
    Render governed work as human-readable lifecycle cards.

    Work-local revision, constraints, progress, obligations, and final result
    remain visually distinct so presentation does not flatten different semantic
    roles into an attractive but ambiguous blob.
    """
    work_items = [
        value for key, value in sorted(state.items())
        if key.startswith("work:") and isinstance(value, dict)
    ]
    if not work_items:
        return '<div class="empty">No work items yet. Create the first durable objective.</div>'
    cards: list[str] = []
    for work in work_items:
        status = _escape(work.get("status", "unknown"))
        constraints = work.get("constraints", [])
        results = work.get("accepted_results", [])
        obligations = work.get("open_obligations", [])
        assessments = work.get("semantic_assessments", [])
        latest_assessment = (
            assessments[-1]
            if isinstance(assessments, list) and assessments and isinstance(assessments[-1], dict)
            else None
        )
        assessment_html = ""
        if latest_assessment:
            criteria = latest_assessment.get("criteria", {})
            metrics = latest_assessment.get("metrics", {})
            provenance = latest_assessment.get("provenance", {})
            verdict = str(latest_assessment.get("verdict", "unknown")).upper()
            criterion_labels = {
                "objective_fidelity": "Objective",
                "history_fidelity": "History",
                "frontier_fidelity": "Frontier",
                "compression_awareness": "Compression awareness",
                "unsupported_claims": "Unsupported claims",
                "actionability": "Actionability",
            }
            criteria_html = "".join(
                f'<div><span>{_escape(criterion_labels.get(key, key.replace("_", " ")))}</span>'
                f'<strong class="quality-{_escape(value)}">{_escape(str(value).upper())}</strong></div>'
                for key, value in criteria.items()
            ) if isinstance(criteria, dict) else ""
            context_bytes = int(metrics.get("context_bytes", 0)) if isinstance(metrics, dict) else 0
            full_bytes = int(metrics.get("full_context_bytes", 0)) if isinstance(metrics, dict) else 0
            ratio = float(metrics.get("compression_ratio", 0)) if isinstance(metrics, dict) else 0.0
            exposed = int(metrics.get("accepted_results_exposed", 0)) if isinstance(metrics, dict) else 0
            receipt_count = int(metrics.get("receipt_count_exposed", 0)) if isinstance(metrics, dict) else 0
            run_id = provenance.get("artifact_run_id", "") if isinstance(provenance, dict) else ""
            provider = provenance.get("provider", "") if isinstance(provenance, dict) else ""
            model = provenance.get("model", "") if isinstance(provenance, dict) else ""
            assessment_html = f"""
              <div class="quality-block">
                <div class="quality-head"><b>Continuity quality</b><span class="quality-verdict quality-{_escape(verdict.lower())}">{_escape(verdict)}</span></div>
                <div class="quality-grid">{criteria_html}</div>
                <div class="quality-metrics">
                  <span>Context <b>{context_bytes:,} / {full_bytes:,} B</b></span>
                  <span>Compression <b>{ratio * 100:.1f}%</b></span>
                  <span>Milestones exposed <b>{exposed}</b></span>
                  <span>Receipts <b>{receipt_count}</b></span>
                </div>
                <div class="quality-provenance">{_escape(provider)} · {_escape(model)}{f' · run {_escape(run_id)}' if run_id else ''}</div>
              </div>
            """
        handoff_evaluations = work.get("handoff_evaluations", [])
        handoff_evaluation_html = ""
        if isinstance(handoff_evaluations, list) and handoff_evaluations:
            latest_handoff_evaluation = handoff_evaluations[-1]
            if isinstance(latest_handoff_evaluation, dict):
                criteria = latest_handoff_evaluation.get("criteria", {})
                passed = int(latest_handoff_evaluation.get("score", 0))
                grounding_labels = {
                    "objective_fidelity": "Objective grounding",
                    "authority_fidelity": "Authority grounding",
                    "history_fidelity": "History grounding",
                    "constraint_fidelity": "Constraint grounding",
                    "frontier_fidelity": "Frontier grounding",
                    "epistemic_discipline": "Epistemic grounding",
                    "transfer_usability": "Transfer grounding",
                }
                criteria_html = "".join(
                    f'<div><span>{_escape(grounding_labels.get(key, key.replace("_", " ")))}</span>'
                    f'<strong class="quality-{_escape(result)}">{_escape(str(result).upper())}</strong></div>'
                    for key, result in criteria.items()
                ) if isinstance(criteria, dict) else ""
                scorer_version = latest_handoff_evaluation.get("scorer_version")
                scorer_label = f" · scorer v{_escape(scorer_version)}" if scorer_version is not None else " · legacy scorer"
                recent_handoff_rows = []
                for evaluation in reversed(handoff_evaluations[-8:]):
                    if not isinstance(evaluation, dict):
                        continue
                    evaluation_scorer = evaluation.get("scorer_version")
                    evaluation_scorer_label = (
                        f"v{evaluation_scorer}" if evaluation_scorer is not None else "legacy"
                    )
                    digest = str(evaluation.get("packet_digest", ""))
                    digest_label = digest[:10] + "…" if len(digest) > 10 else digest
                    recent_handoff_rows.append(
                        f'<div class="quality-provenance">'
                        f'{_escape(evaluation.get("vendor", ""))} · '
                        f'{int(evaluation.get("score", 0))}/7 · '
                        f'{_escape(evaluation.get("test_id", ""))} · '
                        f'scorer {_escape(evaluation_scorer_label)} · '
                        f'packet {_escape(digest_label)}</div>'
                    )
                latest_digest = latest_handoff_evaluation.get("packet_digest")
                latest_scorer = latest_handoff_evaluation.get("scorer_version")
                comparable = [
                    item for item in handoff_evaluations
                    if isinstance(item, dict)
                    and item.get("packet_digest") == latest_digest
                    and item.get("scorer_version") == latest_scorer
                ]
                comparable_vendors = {
                    str(item.get("vendor", "")).strip()
                    for item in comparable
                    if str(item.get("vendor", "")).strip()
                }
                comparable_scores = [
                    int(item.get("score", 0))
                    for item in comparable
                    if isinstance(item.get("score"), int)
                ]
                batch_score = (
                    f"{sum(comparable_scores)}/{len(comparable_scores) * 7}"
                    if comparable_scores else "0/0"
                )
                handoff_evaluation_html = f"""
                  <div class="quality-block">
                    <div class="quality-head"><b>Manual handoff grounding</b><span class="quality-verdict quality-{'pass' if passed == 7 else 'uncertain'}">{passed}/7</span></div>
                    <div class="quality-grid">{criteria_html}</div>
                    <div class="quality-provenance">{_escape(latest_handoff_evaluation.get('vendor', ''))} · test {_escape(latest_handoff_evaluation.get('test_id', ''))}{scorer_label}</div>
                    <div class="quality-metrics">
                      <span>Manual tests recorded <b>{len(handoff_evaluations)}</b></span>
                      <span>Comparable grounding batch <b>{len(comparable)} tests · {len(comparable_vendors)} vendors · {batch_score}</b></span>
                    </div>
                    <div class="quality-provenance">Exact packet grounding only · semantic fidelity is reviewed separately.</div>
                    <div class="work-section"><b>Recent manual test history</b>{''.join(recent_handoff_rows)}</div>
                  </div>
                """
        constraints_html = "".join(f"<li>{_escape(item)}</li>" for item in constraints)
        results_html = "".join(f"<li>{_escape(item)}</li>" for item in results)
        obligations_html = "".join(f"<li>{_escape(item)}</li>" for item in obligations)
        final = work.get("final_result")
        cards.append(
            f"""
            <article class="work-card">
              <div class="work-head"><code>{_escape(work.get('id', ''))}</code><span class="work-status {status}">{status}</span></div>
              <h3>{_escape(work.get('objective', 'Untitled work'))}</h3>
              <div class="work-meta">WORK REVISION {int(work.get('work_revision', 0))}</div>
              {f'<div class="work-section"><b>Constraints</b><ul>{constraints_html}</ul></div>' if constraints else ''}
              {f'<div class="work-section"><b>Accepted results</b><ol>{results_html}</ol></div>' if results else ''}
              {f'<div class="work-section"><b>Open obligations</b><ul>{obligations_html}</ul></div>' if obligations else ''}
              {assessment_html}
              {handoff_evaluation_html}
              {f'<div class="final-result"><b>Final result</b><p>{_escape(final)}</p></div>' if final else ''}
            </article>
            """
        )
    return "".join(cards)


def _receipt_rows(history: tuple[dict[str, object], ...]) -> str:
    """
    Render newest-first receipt summaries with expandable exact provenance.

    Search text includes action, target, and rejection details. Full payloads
    remain in the durable record; the page exposes enough identifiers and hashes
    to trace a visible outcome without pretending to be the record itself.
    """
    if not history:
        return '<div class="empty">Receipts will appear here after the first proposal.</div>'
    rows: list[str] = []
    for event in reversed(history):
        proposal = event["proposal"]
        assert isinstance(proposal, dict)
        operations = proposal.get("operations", [])
        summary = ", ".join(
            f"{str(operation.get('action', '')).replace('_', ' ')} {operation.get('key')}"
            for operation in operations
        )
        reasons = event["reasons"]
        detail = "; ".join(str(reason) for reason in reasons) if reasons else summary
        status = _escape(event["status"])
        rows.append(
            f"""
            <button class="receipt" data-search="{_escape(summary)} {_escape(detail)}"
                    onclick="this.classList.toggle('open')" aria-expanded="false">
              <span class="sequence">#{event['sequence']}</span>
              <span class="status {status}">{status}</span>
              <span class="receipt-summary">{_escape(summary or 'No operations')}</span>
              <span class="revision">r{event['revision_before']} → r{event['revision_after']}</span>
              <span class="receipt-detail">
                <b>{_escape(detail or 'Accepted')}</b>
                <code>proposal {_escape(event['proposal_id'])}</code>
                <code>receipt {_escape(event['receipt_id'])}</code>
                <code>hash {_escape(event['event_hash'])}</code>
              </span>
            </button>
            """
        )
    return "".join(rows)


def _exchange_panel(proof: dict[str, object]) -> str:
    """
    Render the continuity experiment as three human-readable windows.

    Technical evidence still exists in SQLite and the derived JSON proof, but the
    main site is intentionally an observational surface rather than a debugging
    dashboard. The operator should be able to see the question, the answer, and
    the governed consequence without reading transport or storage mechanics.
    """
    review = proof.get("semantic_review", {})
    evidence = review.get("evidence", {}) if isinstance(review, dict) else {}
    if not isinstance(evidence, dict):
        evidence = {}

    trial = proof.get("overnight_trial", {})
    if not isinstance(trial, dict):
        trial = {}
    task = str(
        trial.get("task")
        or "Read what was left from the earlier run, explain where the experiment stands, and suggest what should happen next without making up missing information."
    )
    cycle = trial.get("cycle")

    response = _public_model_response(proof)
    if proof.get("kind") == "evolving overnight Gemini continuity observation":
        summary = (
            "Gemini read the information left from the earlier run and suggested what should happen next. "
            "sudofx saved the exchange so a brand-new Gemini can pick up from it next time. "
            "Gemini did not get to change the project's facts by itself."
        )
    elif proof.get("assessment_status") == "semantic_review_pending":
        summary = (
            "Gemini read what it was given and suggested a next step. The system checked the answer "
            "without letting Gemini change the project's recorded facts."
        )
    else:
        summary = "No completed Gemini exchange is available yet."

    status = "LATEST"
    if cycle:
        status = f"TEST {cycle}"
    matrix_cycle = trial.get("matrix_cycle")
    matrix_size = trial.get("matrix_size")
    coordinate = trial.get("coordinate", {})
    if not isinstance(coordinate, dict):
        coordinate = {}
    matrix_progress = ""
    if isinstance(matrix_cycle, int) and isinstance(matrix_size, int) and matrix_cycle > 0 and matrix_size > 0:
        matrix_pass = (matrix_cycle - 1) // matrix_size + 1
        matrix_position = (matrix_cycle - 1) % matrix_size + 1
        matrix_progress = (
            f"pass {matrix_pass} · {matrix_position}/{matrix_size} "
            f"({matrix_position / matrix_size * 100:.1f}%)"
        )
    coordinate_text = " · ".join(
        str(coordinate.get(key, "")).strip()
        for key in ("semantic_lens", "exposure", "pressure")
        if str(coordinate.get(key, "")).strip()
    )
    protocol_passed = proof.get("protocol_gate_passed")
    if not isinstance(protocol_passed, bool):
        protocol_passed = proof.get("passed") is True
    protocol_status = "PASS" if protocol_passed else "NOT PASSED"
    semantic_status = str(
        proof.get(
            "semantic_review_status",
            "pending" if proof.get("assessment_status") == "semantic_review_pending" else proof.get("assessment_status", "unknown"),
        )
    ).upper()

    return f"""
      <section class="exchange" aria-label="Gemini exchange" data-artifact-run-id="{_escape(proof.get('artifact_run_id', ''))}">
        <div class="exchange-head">
          <div class="exchange-title"><span class="eyebrow">One AI to the next</span><h2>Can a fresh AI pick up where the last one left off?</h2></div>
          <span class="exchange-status" data-exchange-status>{_escape(status)}</span>
        </div>
        <div class="quality-metrics">
          <span>Stress matrix <b data-exchange-matrix>{_escape(matrix_progress or '—')}</b></span>
          <span>Coordinate <b data-exchange-coordinate>{_escape(coordinate_text or '—')}</b></span>
          <span>Protocol gate <b data-exchange-protocol>{_escape(protocol_status)}</b></span>
          <span>Semantic review <b data-exchange-semantic>{_escape(semantic_status)}</b></span>
        </div>

        <div class="exchange-window exchange-question">
          <span>What Gemini was asked</span>
          <p data-exchange-question>{_escape(task)}</p>
        </div>

        <div class="exchange-window exchange-answer">
          <span>What Gemini responded</span>
          <p data-exchange-response>{_escape(response)}</p>

        </div>

        <div class="exchange-window exchange-action">
          <span>What happened</span>
          <p data-exchange-action>{_escape(summary)}</p>
        </div>
      </section>
    """

def render(
    kernel: Kernel,
    *,
    repository: str = "sudofx/sudofx",
    verification: dict[str, str] | None = None,
    continuity_proof: dict[str, object] | None = None,
) -> str:
    """
    Produce one complete HTML document from a verified kernel snapshot.

    Theme preference deliberately reuses WAKE's origin-scoped key so the two
    related projects honor the same day/night choice on ``sudofx.github.io``.
    The hidden theme control has an explicit 1px box: global form-control width
    rules must not make an invisible element widen the mobile viewport.
    """
    # Replay remains exhaustive, but a phone projection must not grow one DOM
    # subtree per durable event forever. The newest bounded window preserves
    # useful audit navigation while the database retains the complete chain.
    # State, history, and health share one verified SQLite snapshot so growth
    # does not multiply replay work or mix adjacent revisions in one page.
    revision, state, history, health = kernel.record.projection_snapshot(50)
    context = Context(revision=revision, state=state, recent_receipts=())
    total_receipts = int(health["event_count"])
    work_items = [value for key, value in context.state.items() if key.startswith("work:")]
    open_work = sum(isinstance(item, dict) and item.get("status") == "open" for item in work_items)
    verification = verification or {}
    continuity_proof = continuity_proof or {}
    semantic_review = continuity_proof.get("semantic_review", {})
    if not isinstance(semantic_review, dict):
        semantic_review = {}
    semantic_criteria = semantic_review.get("criteria", [])
    if not isinstance(semantic_criteria, list):
        semantic_criteria = []
    semantic_rows = "".join(
        f'<div><span>{_escape(str(item.get("id", "")).replace("_", " "))}</span>'
        f'<strong class="quality-uncertain">{_escape(str(item.get("status", "pending")).upper())}</strong></div>'
        for item in semantic_criteria
        if isinstance(item, dict)
    )
    semantic_reviewers = semantic_review.get("reviewers", {})
    if not isinstance(semantic_reviewers, dict):
        semantic_reviewers = {}
    operator_review = semantic_reviewers.get("operator", {})
    chatgpt_review = semantic_reviewers.get("chatgpt", {})
    operator_review_status = (
        str(operator_review.get("status", "pending")).upper()
        if isinstance(operator_review, dict) else "PENDING"
    )
    chatgpt_review_status = (
        str(chatgpt_review.get("status", "pending")).upper()
        if isinstance(chatgpt_review, dict) else "PENDING"
    )
    semantic_run = str(continuity_proof.get("artifact_run_id", ""))
    semantic_digest = str(continuity_proof.get("context_digest", ""))
    # Pages is intentionally public. The manual exchange is a derived,
    # provider-neutral view of the same bounded handoff used for continuity
    # testing. It may be copied and evaluated by anyone, but browser-side work
    # never mutates authoritative SQLite state.
    manual_prompt = ""
    try:
        manual_packet = build_handoff_packet(kernel, HANDOFF_WORK_ID)
        manual_prompt = (
            "SUDOFX MANUAL CONTINUITY TEST\n"
            "You are a fresh intelligence with no prior conversation, memory, files, tools, or hidden context.\n"
            "Use only the bounded durable packet below. Treat digests as unreadable commitments, not readable history.\n"
            "Do not claim you performed work or inspected anything outside the packet.\n\n"
            "TRANSPORT METADATA\n"
            "vendor: __SUDOFX_VENDOR__\n"
            "test_id: __SUDOFX_TEST_ID__\n"
            "nonce: __SUDOFX_NONCE__\n"
            f"work_id: {manual_packet['work_id']}\n"
            f"packet_digest: {manual_packet['packet_digest']}\n\n"
            "Return only one JSON object. Do not use Markdown fences or add prose before or after it.\n"
            "The object must contain exactly these top-level fields: test_id, nonce, vendor, work_id, packet_digest, answers.\n"
            "Copy the transport metadata above exactly into those fields.\n"
            "answers must contain exactly: objective_fidelity, authority_fidelity, history_fidelity, constraint_fidelity, frontier_fidelity, epistemic_discipline, transfer_usability.\n"
            "Each answer must be an object with non-empty answer and evidence fields.\n"
            "Every evidence value must be an exact quote of at least 8 characters from the COMPLETE JSON PACKET below.\n"
            "Do not cite CURRENT OPERATOR AUTHORIZATION or TRANSPORT METADATA as evidence; they are transport context, not packet evidence.\n"
            "If the packet does not support a claim, say that in answer and quote packet text that establishes the limit.\n\n"
            "COMPLETE JSON PACKET\n"
            + json.dumps(manual_packet, indent=2, sort_keys=True)
        )
    except ValueError:
        # A projection without the experiment work item remains valid; the
        # public manual workbench stays unavailable instead of inventing a
        # prompt from unrelated state.
        pass
    observer_continuous = continuity_proof.get("assessment_status") == "semantic_review_pending"
    # A semantic review result remains evidence rather than authoritative state,
    # but continuous test authorization means it no longer pauses the observer.
    # The presentation therefore describes execution truth without pretending
    # that Gemini's proposal was applied to the durable work item.
    observer_static_state = "CONTINUOUS" if observer_continuous else "IDLE"
    observer_static_activity = (
        "The experiment is running"
        if observer_continuous
        else "The experiment is stopped"
    )
    observer_static_detail = (
        "A new Gemini test starts after each successful exchange."
        if observer_continuous
        else "No Gemini test is running right now."
    )
    # GitHub Actions is the operator surface. Pages stays public and unauthenticated.
    actions_light_html = f'''<a class="actions-light" data-light-state="unknown"
      href="https://github.com/{_escape(repository)}/actions" aria-label="Open sudofx GitHub Actions" title="GitHub Actions">
      <span class="actions-light-track" aria-hidden="true"><i class="actions-light-dot"></i></span>
      <span class="sr-only">GitHub Actions</span>
    </a>'''
    observer_console_html = f"""
        <section class="observer-console checking observer-compact" aria-label="Live status"
                 data-repository="{_escape(repository)}" data-workflow="prove-model.yml" data-runner="sudofx-runner.yml"
                 data-fallback-state="{observer_static_state}"
                 data-fallback-activity="{_escape(observer_static_activity)}"
                 data-fallback-detail="{_escape(observer_static_detail)}">
          <div class="observer-signal" aria-live="polite">
            <span class="status-led checking" data-status-led aria-hidden="true"></span>
            <span class="observer-state checking" data-observer-state>CHECKING…</span>
            <strong data-current-activity>Loading current status…</strong>
          </div>
          <span data-current-step hidden>Checking GitHub…</span>
          <span data-latest-run hidden>{_escape(verification.get("run_id", "unknown"))}</span>
          <span data-next-check hidden>Checking chain…</span>
          <span data-observer-detail hidden>Connecting to GitHub…</span>
          <div data-machine-activity hidden><span data-machine-text>PROCESSING</span></div>
        </section>
        """
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <meta name="theme-color" media="(prefers-color-scheme: light)" content="#f4f5fb">
  <meta name="theme-color" media="(prefers-color-scheme: dark)" content="#24283b">
  <title>sudofx — governed work</title>
  <script>try{{const saved=localStorage.getItem('wake-theme');const dark=saved?saved==='dark':matchMedia('(prefers-color-scheme:dark)').matches;if(dark)document.documentElement.dataset.theme='dark'}}catch{{}}</script>
  <style>
    :root {{ color-scheme:light; --paper:#f4f5fb; --surface:#ffffff; --ink:#24283b; --muted:#626b8a;
      --line:#d9ddeb; --green:#3FB950; --accent:#7658b3; --hot:#c52f9b; --pale:#ffffff;
      --mono:ui-monospace,SFMono-Regular,Consolas,monospace; }}
    :root[data-theme=dark] {{ color-scheme:dark; --paper:#24283b; --surface:#1f2335; --ink:#c0caf5;
      --muted:#a9b1d6; --line:#3b4261; --green:#3FB950; --accent:#bb9af7; --hot:#7aa2f7; --pale:#1f2335; }}
    * {{ box-sizing:border-box }}
    html,body {{ width:100%; max-width:100%; overflow-x:hidden; overscroll-behavior-x:none }}
    body {{ margin:0; position:relative; background:var(--paper); color:var(--ink); font:16px/1.45 system-ui,-apple-system,sans-serif }}
    body:before {{ content:""; display:block; height:5px; background:var(--green) }}
    main {{ width:min(980px,100%); max-width:100%; min-width:0; margin:auto; padding:clamp(14px,4vw,40px) }}
    /* Identity stays compact because live status—not project explanation—is the
       first reason an operator opens this page on a phone. */
    header {{ position:relative; display:grid; grid-template-columns:minmax(0,1fr) auto; grid-template-areas:"brand actions";
      column-gap:18px; align-items:center; padding:30px 0 24px }}
    .brand-block {{ grid-area:brand; display:grid; justify-items:start; align-content:center; gap:8px; min-width:0 }}
    .masthead-actions {{ grid-area:actions; display:flex; align-items:center; justify-content:flex-end; gap:12px; min-width:max-content }}
    .brand {{ color:var(--ink); text-decoration:none; font:900 clamp(30px,8vw,48px)/.85 var(--mono); letter-spacing:-.08em }}
    .brand i {{ color:var(--green); font-style:normal }}
    .inspired {{ color:var(--muted); text-decoration:none; font:700 9px/1 var(--mono); letter-spacing:.12em; text-transform:uppercase; white-space:nowrap }}
    .inspired b {{ color:var(--green) }}
    .brand:hover,.inspired:hover {{ color:var(--hot) }}
    .eyebrow {{ font:700 11px/1 var(--mono); letter-spacing:.14em; text-transform:uppercase; color:var(--green) }}
    .observer-console {{ margin:0 0 32px; padding:18px; border:1px solid var(--line); border-top:4px solid var(--accent); background:var(--surface) }}
    .observer-console.working {{ border-top-color:var(--green) }}
    .observer-console.failed {{ border-top-color:#f7768e }}
    .observer-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:18px }}
    .observer-head h1 {{ margin:6px 0 16px; font-size:clamp(24px,6vw,34px); line-height:1; letter-spacing:-.04em }}
    .observer-signal {{ display:flex; align-items:center; gap:9px }}
    .status-led {{ width:9px; height:9px; border-radius:50%; flex:0 0 9px; background:#e7c35a; animation:none }}
    .status-led.checking,.status-led.waiting {{ background:#e7c35a }}
    .status-led.continuous,.status-led.working {{ background:#307444; animation:status-light-pulse 3.2s ease-in-out infinite }}
    .status-led.idle,.status-led.failed {{ background:#d65e6c; animation:status-light-blink 2.4s step-end infinite }}
    .observer-state {{ padding:0; border:0; font:700 10px var(--mono); letter-spacing:.08em; text-transform:uppercase }}
    .observer-state.working {{ color:var(--green) }}
    .observer-state.idle {{ color:#f7768e }}
    .observer-state.failed {{ color:var(--hot) }}
    .observer-state.waiting {{ color:var(--accent) }}
    .observer-state.continuous {{ color:var(--green) }}
    .observer-state.checking {{ color:var(--accent) }}
    .observer-grid {{ display:grid; grid-template-columns:2fr 1fr 1fr; gap:1px; background:var(--line); border:1px solid var(--line) }}
    .observer-cell {{ min-width:0; padding:14px; background:var(--paper) }}
    .observer-cell span {{ display:block; color:var(--muted); font:700 9px var(--mono); letter-spacing:.08em; text-transform:uppercase }}
    .observer-cell strong {{ display:block; margin-top:7px; font-size:13px; line-height:1.25; overflow-wrap:anywhere }}
    .observer-detail {{ display:flex; justify-content:space-between; gap:14px; margin-top:12px; color:var(--muted); font:11px var(--mono) }}
    .observer-detail a {{ color:var(--accent); text-decoration:none; white-space:nowrap }}
    /* GitHub Actions is the operator surface. The masthead light is only a link and status indicator. */
    .sr-only {{ position:absolute!important; width:1px!important; height:1px!important; padding:0!important; margin:-1px!important; overflow:hidden!important; clip:rect(0,0,0,0)!important; white-space:nowrap!important; border:0!important }}
    .actions-light {{ position:relative; z-index:2; width:30px; height:30px; display:inline-flex; align-items:center; justify-content:center; text-decoration:none; cursor:default }}
    .actions-light-track {{ width:18px; height:18px; box-sizing:border-box; flex:0 0 18px; padding:2px; border:1px solid var(--line); border-radius:20px; background:var(--surface); display:inline-flex; align-items:center; justify-content:center }}
    .actions-light-dot {{ display:block; width:12px; height:12px; flex:0 0 12px; border-radius:50%; background:#e7c35a }}
    .actions-light[data-light-state="running"] .actions-light-dot {{ background:#307444; animation:status-light-pulse 3.2s ease-in-out infinite }}
    .actions-light[data-light-state="stopped"] .actions-light-dot {{ background:#d65e6c; animation:status-light-blink 2.4s step-end infinite }}
    .manual-test-panel {{ margin-top:24px; padding:18px; border:1px solid var(--line); background:var(--surface) }}
    .manual-test-panel .quality-head {{ margin-bottom:12px }}
    .manual-test-intro {{ margin:0 0 14px; color:var(--muted); font:11px/1.5 var(--mono) }}
    .provider-buttons {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:7px; margin-bottom:14px }}
    .provider-buttons a,.manual-actions button,.manual-actions a {{ border:1px solid var(--line); border-radius:4px; background:var(--surface); color:var(--ink); padding:9px 11px; font:800 11px var(--mono); cursor:pointer; text-align:center; text-decoration:none }}
    .provider-buttons a:hover,.provider-buttons a:focus-visible,.manual-actions button:hover,.manual-actions a:hover {{ border-color:var(--accent); color:var(--accent) }}
    .provider-buttons a[aria-pressed="true"] {{ color:var(--green); border-color:var(--green) }}
    .manual-field {{ display:grid; gap:6px; margin-top:12px; color:var(--muted); font:700 10px var(--mono); letter-spacing:.05em; text-transform:uppercase }}
    .manual-field textarea {{ width:100%; min-height:180px; resize:vertical; border:1px solid var(--line); background:var(--paper); color:var(--ink); padding:12px; font:12px/1.45 var(--mono); text-transform:none; letter-spacing:normal }}
    .manual-actions {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px }}
    .manual-actions [data-manual-copy],.manual-actions [data-manual-analyze] {{ border-color:var(--accent); color:var(--accent) }}
    .manual-actions [hidden] {{ display:none!important }}
    .manual-note {{ min-height:1.5em; margin:10px 0 0; color:var(--muted); font:11px/1.45 var(--mono) }}
    .manual-local-score {{ margin-top:14px }}
    .manual-local-score[hidden] {{ display:none!important }}
    @keyframes status-light-pulse {{ 0%,100% {{ opacity:.3 }} 50% {{ opacity:1 }} }}
    @keyframes status-light-blink {{ 0%,49% {{ opacity:1 }} 50%,100% {{ opacity:.18 }} }}
    @media (prefers-reduced-motion: reduce) {{ .actions-light-dot,.status-led {{ animation:none!important; opacity:1!important }} }}
    .machine-activity {{ margin-top:12px; border:1px solid var(--line); background:var(--paper); overflow:hidden }}
    .machine-activity[hidden] {{ display:none }}
    .machine-lights {{ display:grid; grid-template-columns:repeat(8,1fr); gap:6px; padding:10px 12px 8px }}
    .machine-lights i {{ display:block; height:6px; background:var(--line); opacity:.45 }}
    .machine-activity.working .machine-lights i {{ background:var(--green); animation:machine-pulse 1s steps(1,end) infinite }}
    .machine-activity.working .machine-lights i:nth-child(2) {{ animation-delay:.125s }}
    .machine-activity.working .machine-lights i:nth-child(3) {{ animation-delay:.25s }}
    .machine-activity.working .machine-lights i:nth-child(4) {{ animation-delay:.375s }}
    .machine-activity.working .machine-lights i:nth-child(5) {{ animation-delay:.5s }}
    .machine-activity.working .machine-lights i:nth-child(6) {{ animation-delay:.625s }}
    .machine-activity.working .machine-lights i:nth-child(7) {{ animation-delay:.75s }}
    .machine-activity.working .machine-lights i:nth-child(8) {{ animation-delay:.875s }}
    .machine-track {{ overflow:hidden; border-top:1px solid var(--line); padding:8px 0; white-space:nowrap; color:var(--green); font:700 10px/1 var(--mono); letter-spacing:.12em; text-transform:uppercase }}
    .machine-track span {{ display:inline-block; min-width:100%; padding-left:100%; animation:machine-scroll 8s linear infinite }}
    @keyframes machine-pulse {{ 0%,24% {{ opacity:1; box-shadow:0 0 8px var(--green) }} 25%,100% {{ opacity:.18; box-shadow:none }} }}
    @keyframes machine-scroll {{ from {{ transform:translateX(0) }} to {{ transform:translateX(-200%) }} }}
    @media (prefers-reduced-motion: reduce) {{ .machine-activity.working .machine-lights i,.machine-track span {{ animation:none }} }}
    .exchange {{ margin:0 0 48px; padding:24px; border:1px solid var(--line); background:var(--surface) }}
    .exchange-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:22px; margin-bottom:22px }}
    .exchange-head h2 {{ max-width:560px; margin:7px 0 0; font-size:clamp(20px,4vw,28px); line-height:1.12; letter-spacing:-.035em }}
    .exchange-title {{ min-width:0 }}
    .exchange-status {{ padding:0; border:0; color:var(--muted); font:700 9px var(--mono); letter-spacing:.08em; text-transform:uppercase; white-space:nowrap }}
    .exchange-status.working {{ color:var(--green) }}
    .question {{ margin:18px 0; padding:14px; border-left:4px solid var(--accent); background:var(--paper); font-size:16px; font-weight:650 }}
    .context-brief {{ display:grid; gap:1px; margin:0; background:var(--line); border:1px solid var(--line) }}
    .context-brief>div {{ display:grid; grid-template-columns:140px 1fr; gap:14px; padding:12px; background:var(--paper) }}
    .context-brief dt,.exchange-answer>span,.exchange-action>span {{ color:var(--accent); font:700 10px var(--mono); letter-spacing:.08em; text-transform:uppercase }}
    .context-brief dd {{ margin:0; font-size:14px; overflow-wrap:anywhere }}
    .context-brief ul {{ margin:0; padding-left:18px }}
    .exchange-window {{ margin-top:20px; padding:22px; border:1px solid var(--line); background:var(--paper) }}
    .exchange-window>span {{ color:var(--accent); font:700 10px var(--mono); letter-spacing:.08em; text-transform:uppercase }}
    .exchange-window p {{ margin:12px 0 0; font-size:16px; line-height:1.65; overflow-wrap:anywhere }}
    .exchange-question {{ border-left:4px solid var(--accent) }}
    .exchange-answer {{ border-left:4px solid var(--green) }}
    .exchange-action {{ border-left:4px solid var(--hot) }}
    .exchange-answer small {{ display:block; margin-top:10px; color:var(--muted); line-height:1.45 }}
    .observer-compact {{ padding:18px 0 26px; border:0; border-bottom:1px solid var(--line); background:transparent; margin-bottom:34px }}
    .observer-compact .observer-signal {{ justify-content:flex-start; flex-wrap:wrap; gap:12px }}
    .observer-compact [data-current-activity] {{ color:var(--ink); font-size:14px; font-weight:650 }}
    .quiet-footer {{ margin-top:34px; padding-top:18px; border-top:1px solid var(--line); color:var(--muted); font:11px/1.5 var(--mono) }}
    .technical-view {{ margin-top:42px; padding-top:28px; border-top:2px solid var(--accent) }}
    .technical-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:14px; margin-bottom:18px }}
    .technical-head h2 {{ margin-top:6px }}
    .technical-badge {{ padding:5px 8px; border:1px solid var(--accent); color:var(--accent); font:800 9px var(--mono); letter-spacing:.08em }}
    .technical-stats {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:1px; margin-bottom:28px; border:1px solid var(--line); background:var(--line) }}
    .technical-stats>div {{ padding:12px; background:var(--surface); min-width:0 }}
    .technical-stats span,.technical-provenance span {{ display:block; color:var(--muted); font:700 9px var(--mono); letter-spacing:.08em; text-transform:uppercase }}
    .technical-stats strong {{ display:block; margin-top:5px; font:700 13px var(--mono); overflow-wrap:anywhere }}
    .technical-provenance {{ display:grid; grid-template-columns:130px minmax(0,1fr); gap:8px 14px; margin-top:24px; padding:14px; border:1px solid var(--line); background:var(--surface) }}
    .technical-provenance code {{ overflow-wrap:anywhere }}
    @media(max-width:600px) {{
      .technical-stats {{ grid-template-columns:1fr 1fr }}
      .technical-provenance {{ grid-template-columns:1fr }}
      .provider-buttons {{ grid-template-columns:1fr 1fr }}
      main {{ padding:18px 16px 34px }}
      header {{ padding:40px 0 22px }}
      .observer-compact {{ margin-bottom:38px }}
      .exchange {{ padding:20px; margin-bottom:54px }}
      .exchange-head {{ gap:16px; margin-bottom:24px }}
      .exchange-window {{ margin-top:22px; padding:22px 20px }}
    }}
    .toolbar {{ display:flex; gap:10px; align-items:center; justify-content:space-between; margin:0 0 18px }}
    h2 {{ margin:0; font-size:23px; letter-spacing:-.03em }}
    .work-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px; margin-bottom:52px }}
    .work-card {{ min-width:0; background:var(--surface); border:1px solid var(--line); border-top:4px solid var(--green); padding:19px }}
    .quality-block {{ margin-top:18px; padding-top:14px; border-top:1px solid var(--line) }}
    .quality-head {{ display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:10px }}
    .quality-verdict {{ padding:3px 7px; border:1px solid var(--line); font:700 9px var(--mono); letter-spacing:.08em }}
    .quality-pass {{ color:var(--green) }} .quality-fail {{ color:var(--hot) }} .quality-uncertain {{ color:#e0af68 }}
    .quality-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1px; background:var(--line); border:1px solid var(--line) }}
    .quality-grid>div {{ min-width:0; display:flex; justify-content:space-between; gap:8px; padding:8px; background:var(--paper); font:10px var(--mono) }}
    .quality-grid span {{ color:var(--muted); overflow-wrap:anywhere }}
    .quality-grid strong {{ font-size:9px }}
    .quality-metrics {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px 12px; margin-top:10px; color:var(--muted); font:10px var(--mono) }}
    .quality-metrics b {{ color:var(--ink) }}
    .quality-provenance {{ margin-top:8px; color:var(--muted); font:9px var(--mono); overflow-wrap:anywhere }}
    .work-head {{ display:flex; justify-content:space-between; align-items:center; gap:10px }}
    .work-status {{ padding:4px 8px; background:var(--green); color:#172018; font:700 10px var(--mono); text-transform:uppercase }}
    .work-status.completed {{ background:var(--accent); color:var(--paper) }}
    .work-card h3 {{ margin:16px 0 6px; font-size:22px; line-height:1.15; letter-spacing:-.025em }}
    .work-meta {{ color:var(--muted); font:10px var(--mono); letter-spacing:.1em }}
    .work-section,.final-result {{ margin-top:18px; padding-top:14px; border-top:1px solid var(--line); font-size:14px }}
    .work-section b,.final-result b {{ color:var(--accent); font:700 10px var(--mono); letter-spacing:.08em; text-transform:uppercase }}
    .work-section ul,.work-section ol {{ margin:8px 0 0; padding-left:20px }} .work-section li+li {{ margin-top:6px }}
    /* Durable results legitimately contain hashes and provider identifiers with
       no natural break points. The card, not that untrusted text, owns width;
       force long tokens to wrap so a phone projection never clips evidence. */
    .work-section li,.final-result p,.work-head code {{ min-width:0; overflow-wrap:anywhere; word-break:break-word }}
    .final-result p {{ margin:8px 0 0 }}
    .empty {{ padding:28px; border:1px dashed var(--line); color:var(--muted); background:rgba(255,255,255,.28) }}
    .history {{ margin-top:8px; border-top:1px solid var(--line); padding-top:20px }}
    .history>summary {{ cursor:pointer; color:var(--muted); font:700 12px var(--mono); letter-spacing:.08em; text-transform:uppercase }}
    .history-tools {{ display:flex; gap:10px; margin:14px 0 }}
    input {{ width:100%; min-height:44px; border:1px solid var(--line); border-radius:0; background:var(--surface); color:var(--ink); padding:0 13px; font:16px var(--mono) }}
    .receipts {{ display:grid; gap:6px }}
    .receipt {{ appearance:none; width:100%; display:grid; grid-template-columns:46px 84px 1fr auto; gap:10px; align-items:center;
      padding:14px; border:1px solid var(--line); background:var(--surface); text-align:left; color:inherit; cursor:pointer }}
    .sequence,.revision,code {{ font:11px var(--mono); color:var(--muted) }}
    .status {{ padding:4px 7px; text-align:center; font:700 10px var(--mono); text-transform:uppercase; color:white }}
    .status.accepted {{ background:var(--green); color:#172018 }} .status.rejected {{ background:var(--hot); color:var(--paper) }}
    .receipt-summary {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap }}
    .receipt-detail {{ display:none; grid-column:2/-1; gap:6px; padding-top:8px; overflow-wrap:anywhere }}
    .receipt.open .receipt-detail {{ display:grid }}
    footer {{ margin-top:64px; padding-top:22px; border-top:1px solid var(--line); color:var(--muted); font:12px var(--mono) }}
    /* Keeping the switch in normal grid flow anchors it to the upper-right while
       retaining its full touch target and respecting the phone's content inset. */
    .theme-switch {{ display:inline-flex; align-items:center; justify-content:center; min-width:34px; min-height:30px; cursor:pointer; user-select:none }}
    .theme-switch input {{ position:absolute; width:1px; height:1px; margin:0; opacity:0; pointer-events:none }}
    /* The theme switch and operator light intentionally share WAKE's visual
       geometry while keeping separate interaction semantics. */
    .data-switch-track {{ width:34px; height:18px; box-sizing:border-box; flex:0 0 34px; padding:2px; border:1px solid var(--line); background:var(--surface); border-radius:20px; display:inline-flex; align-items:center; justify-content:flex-start }}
    .data-switch-track i {{ display:block; width:12px; height:12px; flex:0 0 12px; box-sizing:border-box; border-radius:50%; background:var(--muted); transition:transform .15s ease,background .15s ease }}
    .theme-switch input:checked + .data-switch-track i {{ transform:translateX(16px); background:var(--green) }}
    .theme-switch input:focus-visible + .data-switch-track {{ outline:2px solid var(--green); outline-offset:2px }}
    @media(max-width:600px) {{ header {{ column-gap:10px; row-gap:16px; padding:28px 0 22px }}
      .brand-block {{ gap:7px; min-width:0 }}
      .brand {{ font-size:clamp(34px,10.8vw,42px) }}
      .inspired {{ font-size:9px; line-height:1.15; letter-spacing:.07em }}
      .masthead-actions {{ gap:9px }}
      .theme-switch {{ min-width:44px; min-height:38px }}
      .data-switch-track {{ width:42px; height:24px; flex-basis:42px; padding:3px }}
      .data-switch-track i {{ width:16px; height:16px; flex-basis:16px }}
      .theme-switch input:checked + .data-switch-track i {{ transform:translateX(18px) }}
      .observer-head {{ gap:12px }} .observer-signal {{ align-items:flex-start }}
      .observer-state {{ max-width:112px; text-align:center }}
      .observer-grid {{ grid-template-columns:1fr 1fr }} .observer-cell.primary {{ grid-column:1/-1 }}
      .observer-detail {{ align-items:flex-start; flex-direction:column }}
      .context-brief>div {{ grid-template-columns:1fr; gap:5px }}
      .exchange-head {{ align-items:flex-start; flex-direction:column }}
      .toolbar {{ align-items:flex-end }}
      .receipt {{ grid-template-columns:38px 76px 1fr }} .revision {{ grid-column:3 }} .receipt-detail {{ grid-column:1/-1 }} }}
  </style>
</head>
<body><main data-published-run-id="{_escape(continuity_proof.get('artifact_run_id', ''))}">
  <header><div class="brand-block"><a class="brand" href="./" aria-label="sudofx home">sudo<i>fx</i></a>
    <a class="inspired" href="https://sudofx.github.io/wake/" target="_blank" rel="noopener noreferrer">Inspired by WAKE<b>✳︎</b></a></div>
    <div class="masthead-actions">
      <label class="theme-switch" title="Follow system theme"><input id="theme-toggle" type="checkbox" role="switch" aria-label="Use dark theme"><span class="data-switch-track" aria-hidden="true"><i></i></span></label>
      {actions_light_html}
    </div></header>
  {observer_console_html}
  {_exchange_panel(continuity_proof)}
  <section class="technical-view" aria-label="Public technical record">
    <div class="technical-head">
      <div><span class="eyebrow">Public record</span><h2>Technical view</h2></div>
      <span class="technical-badge">DERIVED VIEW</span>
    </div>
    <div class="technical-stats">
      <div><span>Record revision</span><strong data-record-revision>{context.revision}</strong></div>
      <div><span>Database</span><strong>{_format_bytes(health['database_bytes'])}</strong></div>
      <div><span>Replay</span><strong>{health['replay_ms']} ms</strong></div>
      <div><span>Receipts</span><strong>{total_receipts}</strong></div>
    </div>
    <div class="manual-test-panel" data-manual-test>
      <div class="quality-head"><b>Manual AI continuity test</b><span class="quality-verdict quality-pass">PUBLIC</span></div>
      <p class="manual-test-intro">Anyone can run this test. Choose an AI, send the generated bounded prompt, paste its JSON response back here, and sudofx will score packet grounding locally. Local scoring is evidence, not database authority.</p>
      <div class="provider-buttons" aria-label="Choose AI provider">
        <a data-manual-vendor="ChatGPT" href="com.openai.chat://" data-manual-fallback="https://chatgpt.com/">ChatGPT</a>
        <a data-manual-vendor="Claude" href="claude://" data-manual-fallback="https://claude.ai/new">Claude</a>
        <a data-manual-vendor="Gemini" href="googlegemini://" data-manual-fallback="https://gemini.google.com/app">Gemini</a>
        <a data-manual-vendor="DeepSeek" href="deepseek://" data-manual-fallback="https://chat.deepseek.com/">DeepSeek</a>
      </div>
      <label class="manual-field">Prompt to send<textarea data-manual-prompt readonly>{_escape(manual_prompt)}</textarea></label>
      <div class="manual-actions"><button type="button" data-manual-copy>Copy prompt</button></div>
      <label class="manual-field">Returned JSON<textarea data-manual-response spellcheck="false" autocapitalize="off" autocomplete="off" placeholder="Paste the complete JSON response here."></textarea></label>
      <div class="manual-actions">
        <button type="button" data-manual-analyze>Analyze response</button>
        <a data-manual-contribute hidden href="https://github.com/{_escape(repository)}/issues/new" target="_blank" rel="noopener noreferrer">Contribute result</a>
        <a data-manual-record href="https://github.com/{_escape(repository)}/actions/workflows/sudofx.yml" target="_blank" rel="noopener noreferrer">Record in Actions</a>
      </div>
      <div class="manual-local-score" data-manual-local-score hidden>
        <div class="quality-head"><b>Local grounding score</b><span class="quality-verdict" data-manual-local-total>—</span></div>
        <div class="quality-grid" data-manual-local-criteria></div>
      </div>
      <p class="manual-note" data-manual-status>{"Choose a provider to generate a fresh test ID and copy the prompt." if manual_prompt else "No handoff work item is available in this projection yet."}</p>
    </div>
    <div class="quality-block" data-manual-live>
      <div class="quality-head"><b>Live manual grounding evidence</b><span class="quality-verdict" data-manual-latest>—</span></div>
      <div class="quality-metrics">
        <span>Tests <b data-manual-total>—</b></span>
        <span>Comparable grounding batch <b data-manual-batch>—</b></span>
        <span>Vendors <b data-manual-vendors>—</b></span>
      </div>
      <div class="quality-provenance">Exact packet grounding only · semantic fidelity is reviewed separately.</div>
      <div class="quality-provenance" data-manual-recent>Waiting for live DB-derived evidence…</div>
    </div>
    <div class="quality-block" data-semantic-review-live>
      <div class="quality-head"><b>Semantic review queue</b><span class="quality-verdict quality-uncertain" data-semantic-review-status>{_escape(str(continuity_proof.get("semantic_review_status", "pending")).upper())}</span></div>
      <div class="quality-grid" data-semantic-review-criteria>{semantic_rows or '<div><span>No review criteria published yet</span><strong class="quality-uncertain">PENDING</strong></div>'}</div>
      <div class="quality-metrics">
        <span>You <b data-semantic-review-operator>{_escape(operator_review_status)}</b></span>
        <span>ChatGPT <b data-semantic-review-chatgpt>{_escape(chatgpt_review_status)}</b></span>
        <span>Run <b data-semantic-review-run>{_escape(semantic_run or "—")}</b></span>
        <span>Context digest <b data-semantic-review-digest>{_escape((semantic_digest[:12] + "…") if semantic_digest else "—")}</b></span>
      </div>
      <div class="quality-provenance">Human judgment is recorded separately from protocol success and is bound to this exact run + digest.</div>
    </div>
    <section>
      <div class="toolbar"><div><span class="eyebrow">{open_work} open</span><h2>Current work</h2></div></div>
      <div class="work-grid">{_work_cards(context.state)}</div>
    </section>
    <details class="history">
      <summary>Activity history · showing {len(history)} of {total_receipts} receipts</summary>
      <div class="history-tools"><input id="search" type="search" placeholder="Filter activity…" aria-label="Filter activity history"></div>
      <div class="receipts" id="receipts">{_receipt_rows(history)}</div>
    </details>
    <div class="technical-provenance">
      <span>Published run</span><code>{_escape(verification.get("run_id", "unknown"))}</code>
      <span>Commit</span><code>{_escape(verification.get("commit", "unknown"))}</code>
      <span>SQLite quick check</span><code>{_escape(health.get("quick_check", "unknown"))}</code>
      <span>Schema</span><code>{_escape(health.get("schema_version", "unknown"))}</code>
    </div>
  </section>
  <footer class="quiet-footer">This page is a derived public view. SQLite remains the authoritative record; operator actions live in GitHub Actions.</footer>
</main><script>
const observer=document.querySelector('.observer-console');
const observerState=document.querySelector('[data-observer-state]');
const statusLed=document.querySelector('[data-status-led]');
const currentActivity=document.querySelector('[data-current-activity]');
const currentStep=document.querySelector('[data-current-step]');
const latestRun=document.querySelector('[data-latest-run]');
const nextCheck=document.querySelector('[data-next-check]');
const observerDetail=document.querySelector('[data-observer-detail]');
const machineActivity=document.querySelector('[data-machine-activity]');
const machineText=document.querySelector('[data-machine-text]');
const exchangeStatus=document.querySelector('[data-exchange-status]');
const recordRevision=document.querySelector('[data-record-revision]');
const actionsLight=document.querySelector('.actions-light');
const setActionsLight=(state)=>{{if(actionsLight)actionsLight.dataset.lightState=state;}};
const actionsLightForVisualState=(state)=>state==='working'?'running':((state==='idle'||state==='failed')?'stopped':'unknown');
// The workflow owns a success-only successor chain. This field describes that
// lifecycle rather than estimating a wall-clock time that no longer exists.
const updateNextCheck=(state)=>{{
  if(!nextCheck)return;
  if(state==='working'){{nextCheck.textContent='In progress now';return;}}
  if(state==='continuous'){{nextCheck.textContent='Immediately after this cycle';return;}}
  nextCheck.textContent=state==='failed'?'Paused until repaired':'Not currently queued';
}};
const refreshObserver=async()=>{{
  if(!observer)return;
  const repo=observer.dataset.repository, workflow=observer.dataset.workflow, runner=observer.dataset.runner;
  try{{
    const [workflowResponse,response]=await Promise.all([
      fetch('https://api.github.com/repos/'+repo+'/actions/workflows/'+runner,{{cache:'no-store'}}),
      fetch('https://api.github.com/repos/'+repo+'/actions/workflows/'+workflow+'/runs?branch=sudofx-runtime&per_page=1',{{cache:'no-store'}})
    ]);
    if(!workflowResponse.ok||!response.ok)throw new Error('GitHub workflow status unavailable');
    const workflowMeta=await workflowResponse.json();
    const data=await response.json(), run=Array.isArray(data.workflow_runs)?data.workflow_runs[0]:null;
    if(!run)throw new Error('No workflow run');
    latestRun.textContent='#'+String(run.run_number||run.id);
    const enabled=workflowMeta.state==='active';
    const running=run.status!=='completed';
    const failed=enabled&&!running&&run.conclusion==='failure';
    const visualState=running?'working':(failed?'failed':(enabled?'continuous':'idle'));
    setActionsLight(actionsLightForVisualState(visualState));
    observer.className='observer-console '+visualState;
    observerState.className='observer-state '+visualState;
    observerState.textContent=running?'Live':(failed?'Paused':(enabled?'Running':'Stopped'));
    if(statusLed)statusLed.className='status-led '+visualState;
    currentActivity.textContent=running?'Gemini is answering now':(failed?'The last test stopped unexpectedly':(enabled?'Continuous runner enabled; next cycle is starting':'Continuous tests stopped'));
    updateNextCheck(visualState);
    if(exchangeStatus){{exchangeStatus.textContent=running?'Updating':'Latest';exchangeStatus.className='exchange-status '+(running?'working':'');}}
    const jobsResponse=await fetch(run.jobs_url,{{cache:'no-store'}});
    if(jobsResponse.ok){{
      const jobsData=await jobsResponse.json(), jobs=Array.isArray(jobsData.jobs)?jobsData.jobs:[];
      const steps=jobs.flatMap(job=>Array.isArray(job.steps)?job.steps:[]);
      const active=steps.find(step=>step.status==='in_progress')||steps.find(step=>step.status==='queued');
      currentStep.textContent=active?active.name:(run.status==='completed'?'Complete':'Starting');
      if(machineActivity){{machineActivity.hidden=true;machineActivity.classList.remove('working');}}
    }}
    observerDetail.textContent=running
      ? 'Started by GitHub · live status refreshes every 15 seconds'
      : {json.dumps(observer_static_detail)};
  }}catch(error){{
    // Loss of live telemetry must not erase the operator instruction preserved
    // in the published artifact. The prefix discloses staleness; the durable
    // explanation still tells the person whether action is actually required.
    observerDetail.textContent='Live status unavailable. '+observer.dataset.fallbackDetail;
    const fallbackVisualState=observer.dataset.fallbackState==='CONTINUOUS'?'continuous':'idle';
    observer.className='observer-console '+fallbackVisualState;
    observerState.className='observer-state '+fallbackVisualState;
    observerState.textContent=observer.dataset.fallbackState==='CONTINUOUS'?'Running':'Stopped';
    currentActivity.textContent=observer.dataset.fallbackActivity;
    currentStep.textContent='Live detail unavailable';
    updateNextCheck(fallbackVisualState);
    if(machineActivity)machineActivity.hidden=true;
    if(statusLed)statusLed.className='status-led '+fallbackVisualState;
  }}
}};
const exchange=document.querySelector('.exchange');
const updateList=(node,values,empty)=>{{
  if(!node)return;
  const items=Array.isArray(values)&&values.length?values:[empty];
  node.replaceChildren(...items.map(value=>{{const li=document.createElement('li');li.textContent=String(value);return li;}}));
}};
const publicAnswer=(proof)=>{{
  const raw=String(proof.candidate_result||'').trim();
  if(!raw)return 'No Gemini answer has been published yet.';
  if(raw.startsWith('Gemini understood:'))return raw;
  if(raw.startsWith('Reconstruction:')){{
    const label=raw.includes(' Chosen action:')?' Chosen action:'
      :(raw.includes(' Proposed next step:')?' Proposed next step:':'');
    if(label){{
      const pieces=raw.slice('Reconstruction:'.length).split(label);
      const understood=pieces.shift().trim();
      let suggestion=pieces.join(label);
      let verification='';
      if(suggestion.includes(' Verification:'))[suggestion,verification]=suggestion.split(' Verification:',2);
      if(suggestion.includes(' Target:'))suggestion=suggestion.split(' Target:',1)[0];
      return 'Gemini understood: '+understood+' Gemini suggests: '+suggestion.trim()
        +(verification.trim()?' We would know it worked if: '+verification.trim():'');
    }}
  }}
  return raw;
}};
const liveExchangeUrl='https://raw.githubusercontent.com/'+(observer?.dataset.repository||'sudofx/sudofx')+'/sudofx-live/live.json';
const liveHandoffUrl='https://raw.githubusercontent.com/'+(observer?.dataset.repository||'sudofx/sudofx')+'/sudofx-live/handoff-v1.json';
const liveManualUrl='https://raw.githubusercontent.com/'+(observer?.dataset.repository||'sudofx/sudofx')+'/sudofx-live/manual-evaluations.json';
const manualPrompt=document.querySelector('[data-manual-prompt]');
const manualResponse=document.querySelector('[data-manual-response]');
const manualStatus=document.querySelector('[data-manual-status]');
const manualAnalyze=document.querySelector('[data-manual-analyze]');
const manualCopy=document.querySelector('[data-manual-copy]');
const manualContribute=document.querySelector('[data-manual-contribute]');
const manualRecord=document.querySelector('[data-manual-record]');
const manualLocalScore=document.querySelector('[data-manual-local-score]');
const manualLocalTotal=document.querySelector('[data-manual-local-total]');
const manualLocalCriteria=document.querySelector('[data-manual-local-criteria]');
const manualBasePrompt=manualPrompt?.value||'';
const manualDimensions=['objective_fidelity','authority_fidelity','history_fidelity','constraint_fidelity','frontier_fidelity','epistemic_discipline','transfer_usability'];
const freshManualId=()=>{{
  const values=new Uint32Array(1);
  crypto.getRandomValues(values);
  return 'UUID-'+String(values[0]%1000000).padStart(6,'0');
}};
const manualPacketText=()=>{{
  const packetMarker='COMPLETE JSON PACKET\n';
  const source=manualPrompt?.value||manualBasePrompt;
  const index=source.indexOf(packetMarker);
  return index>=0?source.slice(index+packetMarker.length).trim():'';
}};
const setManualStatus=(message)=>{{if(manualStatus)manualStatus.textContent=message;}};
// Keep copying and app launching as separate browser primitives. iOS is most
// reliable when the provider control is a real link that the OS can hand to the
// installed app. Copy remains best-effort on the same tap and is always
// available as an explicit second tap if WebKit denies clipboard access.
const copyManualFromField=()=>{{
  if(!manualPrompt?.value)return false;
  try{{
    // iOS Safari is unreliable when copying from readonly controls. Copy from
    // a short-lived editable textarea instead, keeping the whole operation
    // synchronous so provider deep-links can still use the same physical tap.
    const helper=document.createElement('textarea');
    helper.value=manualPrompt.value;
    helper.setAttribute('aria-hidden','true');
    helper.style.position='fixed';
    helper.style.top='0';
    helper.style.left='-9999px';
    helper.style.opacity='0';
    helper.style.fontSize='16px';
    document.body.appendChild(helper);
    helper.focus();
    helper.select();
    helper.setSelectionRange(0,helper.value.length);
    const copied=Boolean(document.execCommand('copy'));
    helper.remove();
    return copied;
  }}catch{{return false;}}
}};
const copyManual=async(value)=>{{
  if(!value)return false;
  try{{
    if(navigator.clipboard?.writeText){{
      await navigator.clipboard.writeText(value);
      return true;
    }}
  }}catch{{}}
  return copyManualFromField();
}};
const prepareManualProvider=(link)=>{{
  if(!manualPrompt||!manualBasePrompt){{setManualStatus('No manual packet is available yet.');return false;}}
  const vendor=link.dataset.manualVendor||'';
  const testId=freshManualId();
  const nonce='HANDOFF-'+testId;
  manualPrompt.value=manualBasePrompt
    .replaceAll('__SUDOFX_VENDOR__',vendor)
    .replaceAll('__SUDOFX_TEST_ID__',testId)
    .replaceAll('__SUDOFX_NONCE__',nonce);
  document.querySelectorAll('[data-manual-vendor]').forEach(node=>node.setAttribute('aria-pressed',String(node===link)));
  // Start the modern clipboard write without awaiting it so the anchor's native
  // navigation keeps the original user gesture. The explicit Copy button below
  // remains the deterministic fallback.
  let copyStarted=false;
  try{{
    if(navigator.clipboard?.writeText){{
      navigator.clipboard.writeText(manualPrompt.value).catch(()=>{{}});
      copyStarted=true;
    }}
  }}catch{{}}
  if(!copyStarted)copyStarted=copyManualFromField();
  setManualStatus((copyStarted?'Prompt copied. ':'Prompt ready. ')+'Opening '+vendor+'. If paste is empty, return and tap Copy prompt once.');
  const fallback=link.dataset.manualFallback||'';
  if(fallback){{
    setTimeout(()=>{{if(!document.hidden)location.href=fallback;}},1200);
  }}
  return true;
}};
document.querySelectorAll('[data-manual-vendor]').forEach(link=>link.addEventListener('click',()=>prepareManualProvider(link)));
if(manualCopy)manualCopy.addEventListener('click',async()=>{{
  const copied=await copyManual(manualPrompt?.value||'');
  setManualStatus(copied?'Prompt copied. You can now open any provider and paste it.':'Copy was blocked by the browser; press and hold the prompt, then choose Copy.');
}});
const parseManualResponse=(raw)=>{{
  let candidate=String(raw||'').trim();
  if(candidate.startsWith('&#96;&#96;&#96;')&&candidate.endsWith('&#96;&#96;&#96;')){{
    const lines=candidate.split(/\r?\n/);
    candidate=lines.slice(1,-1).join('\n').trim();
  }}
  if(candidate.startsWith(String.fromCharCode(96,96,96))&&candidate.endsWith(String.fromCharCode(96,96,96))){{
    const lines=candidate.split(/\r?\n/);
    candidate=lines.slice(1,-1).join('\n').trim();
  }}
  candidate=candidate.replaceAll('“','"').replaceAll('”','"');
  const response=JSON.parse(candidate);
  if(!response||Array.isArray(response)||typeof response!=='object')throw new Error('Response must be one JSON object.');
  return response;
}};
const analyzeManual=()=>{{
  if(!manualResponse||!manualPrompt)throw new Error('Manual test panel is unavailable.');
  const response=parseManualResponse(manualResponse.value);
  const packetText=manualPacketText();
  if(!packetText)throw new Error('The visible prompt does not contain a packet.');
  const packet=JSON.parse(packetText);
  const required=['test_id','nonce','vendor','work_id','packet_digest','answers'];
  if(required.some(key=>!(key in response)))throw new Error('Response is missing transport metadata.');
  if(response.packet_digest!==packet.packet_digest)throw new Error('Response belongs to a different packet.');
  if(response.work_id!==packet.work_id)throw new Error('Response belongs to a different work item.');
  if(typeof response.test_id!=='string'||!/^UUID-[0-9]{{6}}$/.test(response.test_id))throw new Error('test_id must use UUID-NNNNNN.');
  if(typeof response.nonce!=='string'||!/^HANDOFF-UUID-[0-9]{{6}}$/.test(response.nonce))throw new Error('nonce must use HANDOFF-UUID-NNNNNN.');
  if(typeof response.vendor!=='string'||!response.vendor.trim())throw new Error('vendor is required.');
  if(!response.answers||Array.isArray(response.answers)||typeof response.answers!=='object')throw new Error('answers must be an object.');
  const results=manualDimensions.map(dimension=>{{
    const answer=response.answers[dimension];
    const answerText=answer&&typeof answer.answer==='string'?answer.answer.trim():'';
    const evidence=answer&&typeof answer.evidence==='string'?answer.evidence.trim():'';
    return {{dimension,passed:Boolean(answerText)&&evidence.length>=8&&packetText.includes(evidence)}};
  }});
  const score=results.filter(item=>item.passed).length;
  if(manualLocalCriteria){{
    manualLocalCriteria.replaceChildren(...results.map(item=>{{
      const row=document.createElement('div');
      const label=document.createElement('span');
      label.textContent=item.dimension.replaceAll('_',' ');
      const value=document.createElement('strong');
      value.textContent=item.passed?'PASS':'FAIL';
      value.className=item.passed?'quality-pass':'quality-fail';
      row.append(label,value);
      return row;
    }}));
  }}
  if(manualLocalTotal){{
    manualLocalTotal.textContent=score+'/7';
    manualLocalTotal.className='quality-verdict '+(score===7?'quality-pass':'quality-uncertain');
  }}
  if(manualLocalScore)manualLocalScore.hidden=false;
  if(manualContribute){{
    const title='Manual handoff result · '+String(response.vendor).trim()+' · '+String(response.test_id);
    manualContribute.href='https://github.com/'+(observer?.dataset.repository||'sudofx/sudofx')+'/issues/new?title='+encodeURIComponent(title);
    manualContribute.hidden=false;
  }}
  setManualStatus('Local scorer v2: '+score+'/7 packet-grounding checks passed. This browser result is not yet authoritative.');
  return score;
}};
if(manualAnalyze)manualAnalyze.addEventListener('click',()=>{{
  try{{analyzeManual();}}catch(error){{if(manualLocalScore)manualLocalScore.hidden=true;setManualStatus('Could not score: '+error.message);}}
}});
if(manualContribute)manualContribute.addEventListener('click',async()=>{{
  await copyManual(manualResponse?.value||'');
  setManualStatus('Response copied. Paste it into the GitHub issue so the contribution is preserved for review.');
}});
if(manualRecord)manualRecord.addEventListener('click',async()=>{{
  await copyManual(manualResponse?.value||'');
  setManualStatus('Response copied. Use handoff-evaluate in GitHub Actions to record it into governed SQLite state.');
}});
const refreshManualEvidence=async()=>{{
  try{{
    const response=await fetch(liveManualUrl+'?ts='+Date.now(),{{cache:'no-store'}});
    if(!response.ok)throw new Error('manual evidence unavailable');
    const view=await response.json();
    const total=document.querySelector('[data-manual-total]');
    const batch=document.querySelector('[data-manual-batch]');
    const vendors=document.querySelector('[data-manual-vendors]');
    const latest=document.querySelector('[data-manual-latest]');
    const recent=document.querySelector('[data-manual-recent]');
    const comparable=view.comparable_batch||{{}};
    if(total)total.textContent=String(view.total_tests??0);
    if(batch)batch.textContent=String(comparable.tests??0)+' tests · '+String(comparable.score??0)+'/'+String(comparable.max_score??0);
    if(vendors)vendors.textContent=Array.isArray(comparable.vendors)&&comparable.vendors.length?comparable.vendors.join(', '):'—';
    if(latest){{
      const item=view.latest||{{}};
      latest.textContent=item.test_id?String(item.score??0)+'/7':'—';
      latest.className='quality-verdict '+((item.score===7)?'quality-pass':'quality-uncertain');
    }}
    if(recent){{
      const items=Array.isArray(view.recent)?view.recent.slice().reverse():[];
      recent.textContent=items.length
        ?items.map(item=>String(item.vendor||'')+' '+String(item.score??0)+'/7 · '+String(item.test_id||'')).join(' | ')
        :'No manual evaluations recorded yet.';
    }}
    if(recordRevision&&Number.isInteger(view.record_revision))recordRevision.textContent=String(view.record_revision);
  }}catch(error){{/* Static DB-derived evidence remains visible if the live view is briefly unavailable. */}}
}};
const refreshExchange=async()=>{{
  if(!exchange)return;
  try{{
    const response=await fetch(liveExchangeUrl+'?ts='+Date.now(),{{cache:'no-store'}});
    if(!response.ok)throw new Error('proof unavailable');
    const proof=await response.json();
    if(recordRevision){{
      try{{
        const handoffResponse=await fetch(liveHandoffUrl+'?ts='+Date.now(),{{cache:'no-store'}});
        if(handoffResponse.ok){{
          const handoff=await handoffResponse.json();
          if(Number.isInteger(handoff.record_revision))recordRevision.textContent=String(handoff.record_revision);
        }}
      }}catch{{}}
    }}
    const runId=String(proof.artifact_run_id||'');
    if(!runId)return;
    exchange.dataset.artifactRunId=runId;
    const trial=proof.overnight_trial||{{}};
    const task=String(trial.task||'Read what was left from the earlier run, explain where the experiment stands, and suggest what should happen next without making up missing information.');
    document.querySelector('[data-exchange-question]').textContent=task;
    document.querySelector('[data-exchange-response]').textContent=publicAnswer(proof);
    const overnight=proof.kind==='evolving overnight Gemini continuity observation';
    document.querySelector('[data-exchange-action]').textContent=overnight
      ?"Gemini read the information left from the earlier run and suggested what should happen next. sudofx saved the exchange so a brand-new Gemini can pick up from it next time. Gemini did not get to change the project's facts by itself."
      :(proof.assessment_status==='semantic_review_pending'
        ?"Gemini read what it was given and suggested a next step. The system checked the answer without letting Gemini change the project's recorded facts."
        :'No completed Gemini exchange is available yet.');
    if(exchangeStatus){{
      exchangeStatus.textContent=trial.cycle?'TEST '+trial.cycle:'LATEST';
      exchangeStatus.className='exchange-status';
    }}
    const matrix=document.querySelector('[data-exchange-matrix]');
    if(matrix){{
      const current=Number(trial.matrix_cycle),size=Number(trial.matrix_size);
      if(Number.isInteger(current)&&Number.isInteger(size)&&current>0&&size>0){{
        const pass=Math.floor((current-1)/size)+1;
        const position=((current-1)%size)+1;
        matrix.textContent='pass '+pass+' · '+position+'/'+size+' ('+(position/size*100).toFixed(1)+'%)';
      }}else matrix.textContent='—';
    }}
    const coordinate=document.querySelector('[data-exchange-coordinate]');
    if(coordinate){{
      const point=trial.coordinate||{{}};
      coordinate.textContent=[point.semantic_lens,point.exposure,point.pressure].filter(Boolean).join(' · ')||'—';
    }}
    const protocol=document.querySelector('[data-exchange-protocol]');
    if(protocol){{
      const protocolPassed=typeof proof.protocol_gate_passed==='boolean'
        ?proof.protocol_gate_passed
        :proof.passed===true;
      protocol.textContent=protocolPassed?'PASS':'NOT PASSED';
    }}
    const semantic=document.querySelector('[data-exchange-semantic]');
    if(semantic)semantic.textContent=String(
      proof.semantic_review_status
      ||(proof.assessment_status==='semantic_review_pending'?'pending':proof.assessment_status)
      ||'unknown'
    ).toUpperCase();
    const semanticReviewStatus=document.querySelector('[data-semantic-review-status]');
    if(semanticReviewStatus){{
      const value=String(proof.semantic_review_status||(proof.assessment_status==='semantic_review_pending'?'pending':proof.assessment_status)||'unknown').toUpperCase();
      semanticReviewStatus.textContent=value;
      semanticReviewStatus.className='quality-verdict '+(value==='PASS'?'quality-pass':value==='FAIL'?'quality-fail':'quality-uncertain');
    }}
    const reviewerStates=(proof.semantic_review&&proof.semantic_review.reviewers)||{{}};
    const operatorState=String((reviewerStates.operator&&reviewerStates.operator.status)||'pending').toUpperCase();
    const chatgptState=String((reviewerStates.chatgpt&&reviewerStates.chatgpt.status)||'pending').toUpperCase();
    const operatorNode=document.querySelector('[data-semantic-review-operator]');
    const chatgptNode=document.querySelector('[data-semantic-review-chatgpt]');
    if(operatorNode)operatorNode.textContent=operatorState;
    if(chatgptNode)chatgptNode.textContent=chatgptState;
    const semanticReviewRun=document.querySelector('[data-semantic-review-run]');
    const reviewRunId=String(proof.artifact_run_id||'');
    if(semanticReviewRun)semanticReviewRun.textContent=reviewRunId||'—';
    const semanticReviewDigest=document.querySelector('[data-semantic-review-digest]');
    const reviewDigest=String(proof.context_digest||'');
    if(semanticReviewDigest)semanticReviewDigest.textContent=reviewDigest?reviewDigest.slice(0,12)+'…':'—';
    const semanticReviewCriteria=document.querySelector('[data-semantic-review-criteria]');
    if(semanticReviewCriteria){{
      const review=proof.semantic_review||{{}};
      const criteria=Array.isArray(review.criteria)?review.criteria:[];
      const rows=criteria.length?criteria:[{{id:'No review criteria published yet',status:'pending'}}];
      semanticReviewCriteria.replaceChildren(...rows.map(item=>{{
        const row=document.createElement('div');
        const label=document.createElement('span');
        label.textContent=String(item.id||'').replaceAll('_',' ');
        const value=document.createElement('strong');
        const status=String(item.status||'pending').toUpperCase();
        value.textContent=status;
        value.className=status==='PASS'?'quality-pass':status==='FAIL'?'quality-fail':'quality-uncertain';
        row.append(label,value);
        return row;
      }}));
    }}
    return proof;
  }}catch(error){{/* Keep the last known exchange visible if the disposable live view is briefly unavailable. */}}
  return null;
}};
refreshObserver();
refreshExchange();
refreshManualEvidence();
setInterval(refreshObserver,15000);
setInterval(refreshExchange,15000);
setInterval(refreshManualEvidence,15000);
const search=document.querySelector('#search');
if(search)search.addEventListener('input',()=>{{const q=search.value.toLowerCase();document.querySelectorAll('.receipt').forEach(r=>r.hidden=!r.dataset.search.toLowerCase().includes(q))}});
document.querySelectorAll('.receipt').forEach(r=>r.addEventListener('click',()=>r.setAttribute('aria-expanded',r.classList.contains('open'))));
const toggle=document.querySelector('#theme-toggle');
const saved=()=>{{try{{return localStorage.getItem('wake-theme')}}catch{{return null}}}};
const sync=()=>{{const dark=document.documentElement.dataset.theme==='dark',manual=Boolean(saved());toggle.checked=dark;toggle.setAttribute('aria-label',dark?'Use light theme':'Use dark theme');toggle.closest('.theme-switch').title=manual?`Manual ${{dark?'dark':'light'}} theme`:`Following system ${{dark?'dark':'light'}} theme`}};
sync();toggle.addEventListener('change',()=>{{const dark=toggle.checked;if(dark)document.documentElement.dataset.theme='dark';else delete document.documentElement.dataset.theme;try{{localStorage.setItem('wake-theme',dark?'dark':'light')}}catch{{}}sync()}});
try{{const media=matchMedia('(prefers-color-scheme:dark)');media.addEventListener('change',event=>{{if(saved())return;if(event.matches)document.documentElement.dataset.theme='dark';else delete document.documentElement.dataset.theme;sync()}})}}catch{{}}
</script></body></html>"""


def export_site(
    kernel: Kernel,
    directory: str | Path,
    *,
    repository: str = "sudofx/sudofx",
    verification: dict[str, str] | None = None,
    continuity_proof: dict[str, object] | None = None,
) -> Path:
    """
    Write the derived Pages artifact and disable Jekyll processing.

    Callers choose the destination. The function never touches the database and
    never claims that a successful file write publishes or checkpoints state.
    """
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    index = destination / "index.html"
    index.write_text(
        render(
            kernel,
            repository=repository,
            verification=verification,
            continuity_proof=continuity_proof,
        ),
        encoding="utf-8",
    )
    if continuity_proof is not None:
        # This JSON is a derived proof artifact for inspection. It contains only
        # synthetic continuity-fixture evidence and is never read back as state.
        (destination / "continuity-proof.json").write_text(
            json.dumps(continuity_proof, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    # Health is a replaceable, content-free projection. It reveals growth and
    # integrity signals without exposing proposal payloads or becoming an input
    # to restore, governance, or maintenance decisions.
    (destination / "database-health.json").write_text(
        json.dumps(kernel.record.health(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    try:
        # The Shortcut fetches this replaceable, public-safe projection. The
        # packet is never read back as authority; submission is checked against
        # a freshly reconstructed packet before SQLite accepts the evidence.
        export_handoff_packet(kernel, destination, HANDOFF_WORK_ID)
    except ValueError:
        pass
    (destination / ".nojekyll").write_text("", encoding="utf-8")
    # The local operator loop must make its continuation decision from the same
    # verified artifact the human sees, never from workflow success alone. A
    # green workflow proves execution; it does not prove that more work is safe.
    # Keeping this as a derived file also prevents runner coordination from
    # becoming a second authority beside the SQLite record.
    proof = continuity_proof or {}
    assessment_status = proof.get("assessment_status")
    if assessment_status == "semantic_review_pending":
        disposition = "CONTINUE"
        reason = "The verified cycle is complete and continuous testing is authorized."
    elif assessment_status == "safe_work_available":
        disposition = "CONTINUE"
        reason = "The verified observer artifact identifies another safe bounded cycle."
    elif proof.get("passed") is True:
        disposition = "NO MORE SAFE WORK"
        reason = "The verified cycle completed without identifying another safe operation."
    else:
        disposition = "FAILED"
        reason = "The observer artifact did not establish a successful governed cycle."
    (destination / "runner-state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "disposition": disposition,
                "reason": reason,
                "artifact_run_id": proof.get("artifact_run_id", ""),
                "artifact_commit": proof.get("artifact_commit", ""),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return index
