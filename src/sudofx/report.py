"""
SUDOFX PUBLIC PROJECTION
========================

This module turns verified replayed state into a self-contained, phone-friendly
HTML artifact. The artifact is a projection: useful for inspection and navigation,
but never an input to governance, replay, or recovery.

Rendering is intentionally dependency-free so a fresh GitHub runner can publish
without a JavaScript toolchain or package registry. State-derived text is escaped
before interpolation. Interactive behavior is limited to live observer telemetry,
history filtering, disclosure, and theme preference.

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

    The authenticated technical view still exposes exact durable work and receipt
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
          <div><span class="eyebrow">One AI to the next</span><h2>Latest exchange</h2></div>
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
    control_url: str = "",
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
    # The control service URL is public configuration, not a credential. An
    # absent URL removes the authentication affordance entirely so local exports
    # and partially configured deployments never imply controls are available.
    control_url = control_url.rstrip("/")
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
    # The public page embeds only public-safe technical projection data. The
    # operator session controls visibility, not confidentiality: hidden HTML is
    # not a security boundary. Sensitive state must remain behind the authenticated
    # service rather than being rendered into Pages at all.
    # The manual exchange is a derived, provider-neutral view of the same
    # compressed handoff used for automated continuity tests. It is embedded in
    # the current public-safe projection but stays inaccessible through normal
    # UI interaction until the confidential service authenticates the owner.
    # Private persistence will require moving delivery behind that service too;
    # presentation gating alone is deliberately not claimed as confidentiality.
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
        # authenticated workbench simply stays unavailable instead of inventing
        # a prompt from unrelated state.
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
    # Authentication remains a presentation-layer gateway to the separate
    # control service; moving it into the masthead must not make Pages an
    # authority or expose authenticated actions before session verification.
    # This structure intentionally matches WAKE's compact operator popover so
    # both related tools keep the same location and interaction vocabulary.
    owner_access_html = (
        f'''<div class="owner-access" data-owner-access>
      <a class="owner-login" data-owner-login href="{_escape(control_url)}/auth/login" aria-label="Open Settings" title="Settings">
        <span class="settings-glyph" aria-hidden="true">⚙︎</span><span class="sr-only">Settings</span>
      </a>
      <button class="owner-menu-toggle" data-owner-menu-toggle type="button" aria-label="Open Settings" title="Settings" aria-expanded="false" aria-haspopup="true" hidden>
        <span class="settings-glyph" aria-hidden="true">⚙︎</span><span class="sr-only" data-owner-menu-label>Settings</span>
      </button>
      <div class="owner-controls" data-owner-controls hidden aria-live="polite">
        <div class="owner-control-heading"><strong>Settings</strong><span data-owner-identity></span><span data-owner-control-status>Checking controls…</span></div>
        <div class="owner-control-actions"><button type="button" data-owner-start>Start</button><button type="button" data-owner-stop>Stop</button><button type="button" data-owner-backup hidden>Backup</button></div>
        <button class="owner-handoff" type="button" data-owner-handoff {'disabled' if not manual_prompt else ''}>Manual AI handoff</button>
        <button class="owner-signout" type="button" data-owner-signout>Sign out</button>
      </div>
    </div>'''
        if control_url
        else ""
    )
    observer_console_html = f"""
        <section class="observer-console checking observer-compact" aria-label="Live status"
                 data-repository="{_escape(repository)}" data-workflow="prove-model.yml"
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
    header {{ position:relative; display:grid; grid-template-columns:minmax(0,1fr) auto; grid-template-areas:"brand actions" "tagline tagline";
      column-gap:18px; row-gap:14px; align-items:center; padding:30px 0 20px }}
    .brand-block {{ grid-area:brand; display:flex; align-items:baseline; gap:12px; min-width:0; white-space:nowrap }}
    .masthead-actions {{ grid-area:actions; display:flex; align-items:center; justify-content:flex-end; gap:12px; min-width:max-content }}
    .brand {{ color:var(--ink); text-decoration:none; font:900 clamp(30px,8vw,48px)/.85 var(--mono); letter-spacing:-.08em }}
    .brand i {{ color:var(--green); font-style:normal }}
    .inspired {{ color:var(--muted); text-decoration:none; font:700 9px/1 var(--mono); letter-spacing:.12em; text-transform:uppercase }}
    .inspired b {{ color:var(--green) }}
    .brand:hover,.inspired:hover {{ color:var(--hot) }}
    .tagline {{ grid-area:tagline; max-width:520px; color:var(--muted); font-size:12px; text-align:left }}
    .eyebrow {{ font:700 11px/1 var(--mono); letter-spacing:.14em; text-transform:uppercase; color:var(--green) }}
    .observer-console {{ margin:0 0 32px; padding:18px; border:1px solid var(--line); border-top:4px solid var(--accent); background:var(--surface) }}
    .observer-console.working {{ border-top-color:var(--green) }}
    .observer-console.failed {{ border-top-color:#f7768e }}
    .observer-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:18px }}
    .observer-head h1 {{ margin:6px 0 16px; font-size:clamp(24px,6vw,34px); line-height:1; letter-spacing:-.04em }}
    .observer-signal {{ display:flex; align-items:center; gap:9px }}
    .status-led {{ width:9px; height:9px; border-radius:50%; flex:0 0 9px; animation:none }}
    .status-led.checking {{ background:var(--accent); box-shadow:none }}
    .status-led.idle {{ background:#f7768e; box-shadow:0 0 10px #f7768e }}\n    .status-led.waiting {{ background:#e0af68; box-shadow:0 0 8px #e0af68 }}
    .status-led.continuous {{ background:var(--green); box-shadow:none }}
    .status-led.working {{ background:var(--green); box-shadow:none }}
    .status-led.failed {{ background:#f7768e; box-shadow:0 0 10px #f7768e }}
    @keyframes led-blink {{ 0%,100% {{ opacity:.25 }} 50% {{ opacity:1 }} }}
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
    /* Operator access is a masthead popover, not durable report content. Its
       elevated layer and mobile fixed panel mirror WAKE while keeping every
       authenticated action hidden until the control service accepts a session. */
    .sr-only {{ position:absolute!important; width:1px!important; height:1px!important; padding:0!important; margin:-1px!important; overflow:hidden!important; clip:rect(0,0,0,0)!important; white-space:nowrap!important; border:0!important }}
    .owner-access {{ position:relative; z-index:2000; font:10px var(--mono) }}
    .owner-login,.owner-menu-toggle {{ width:26px; height:26px; display:inline-grid; place-items:center; position:relative; color:var(--muted); padding:0; border:0; border-radius:50%; background:transparent; text-decoration:none; cursor:pointer }}
    .settings-glyph {{ display:block; font:26px/1 system-ui,-apple-system,sans-serif; line-height:26px; transform:none }}
    .owner-menu-toggle:hover,.owner-menu-toggle:focus-visible,.owner-login:hover,.owner-login:focus-visible {{ color:var(--ink); background:color-mix(in srgb,var(--surface) 70%,transparent) }}
    .owner-controls {{ position:absolute; top:calc(100% + 8px); right:0; width:250px; padding:14px; background:var(--surface); border:1px solid var(--line); box-shadow:0 14px 36px #0003; display:grid; gap:12px }}
    .owner-controls[hidden],.owner-menu-toggle[hidden],.owner-login[hidden] {{ display:none!important }}
    .owner-control-heading {{ display:grid; gap:3px; padding-bottom:10px; border-bottom:1px solid var(--line) }}
    .owner-control-heading strong {{ font:800 10px var(--mono); letter-spacing:.6px; text-transform:uppercase }}
    .owner-control-heading span {{ min-width:0; color:var(--muted); white-space:normal; font:10px/1.45 var(--mono); overflow-wrap:anywhere }}
    .owner-control-actions {{ display:grid; grid-template-columns:repeat(3,1fr); gap:6px }}
    .owner-controls button {{ border:1px solid var(--line); border-radius:4px; background:var(--surface); color:var(--ink); padding:7px 8px; font:800 10px var(--mono); cursor:pointer }}
    .owner-controls [data-owner-start] {{ border-color:var(--green); color:var(--green) }}
    .owner-controls [data-owner-stop] {{ border-color:#f7768e; color:#f7768e }}
    .owner-controls button:disabled {{ opacity:.45; cursor:wait }}
    .owner-controls button[hidden] {{ display:none }}
    .owner-controls .owner-signout {{ width:100%; border-color:var(--line); color:var(--muted); background:transparent }}
    .owner-controls .owner-handoff {{ width:100%; border-color:var(--accent); color:var(--accent) }}
    .handoff-dialog {{ width:min(720px,calc(100vw - 24px)); max-height:calc(100vh - 24px); padding:0; border:1px solid var(--line); background:var(--surface); color:var(--ink); box-shadow:0 22px 70px #0007 }}
    .handoff-dialog::backdrop {{ background:#111a }}
    .handoff-shell {{ display:grid; gap:14px; padding:18px }}
    .handoff-head {{ display:flex; justify-content:space-between; align-items:start; gap:16px }}
    .handoff-head h2 {{ margin:4px 0 0 }}
    .handoff-head button,.handoff-actions button,.provider-buttons a {{ border:1px solid var(--line); border-radius:4px; background:var(--surface); color:var(--ink); padding:9px 11px; font:800 11px var(--mono); cursor:pointer }}
    .provider-buttons {{ display:grid; grid-template-columns:repeat(4,1fr); gap:7px }}
    .provider-buttons a {{ text-align:center; text-decoration:none }}
    .provider-buttons a[aria-pressed=true] {{ color:var(--green); border-color:var(--green) }}
    .handoff-field {{ display:grid; gap:6px; color:var(--muted); font:700 10px var(--mono); letter-spacing:.05em; text-transform:uppercase }}
    .handoff-field textarea {{ width:100%; min-height:170px; resize:vertical; border:1px solid var(--line); background:var(--paper); color:var(--ink); padding:12px; font:12px/1.45 var(--mono); text-transform:none; letter-spacing:normal }}
    .handoff-actions {{ display:flex; flex-wrap:wrap; gap:8px }}
    .handoff-actions [data-handoff-copy],.handoff-actions [data-handoff-analyze] {{ border-color:var(--accent); color:var(--accent) }}
    .handoff-note {{ min-height:1.5em; margin:0; color:var(--muted); font:11px/1.45 var(--mono) }}
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
    .exchange-head h2 {{ margin-top:6px }}
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
    .owner-technical[hidden] {{ display:none!important }}
    .owner-technical {{ margin-top:42px; padding-top:28px; border-top:2px solid var(--accent) }}
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
    .theme-switch {{ display:flex; align-items:center; height:26px; cursor:pointer; user-select:none }}
    .theme-switch input {{ position:absolute; width:1px; height:1px; margin:0; opacity:0; pointer-events:none }}
    /* The track is the complete visual control. A second theme glyph repeated
       the same meaning and introduced an unnecessary alignment relationship. */
    .data-switch-track {{ width:44px; height:26px; padding:2px; border:1px solid var(--line); background:var(--surface); border-radius:20px }}
    .data-switch-track i {{ display:block; width:20px; height:20px; border-radius:50%; background:var(--muted); transition:transform .2s ease,background .2s ease }}
    .theme-switch input:checked + .data-switch-track i {{ transform:translateX(17px); background:var(--green) }}
    .theme-switch input:focus-visible + .data-switch-track {{ outline:3px solid var(--green); outline-offset:3px }}
    @media(max-width:600px) {{ header {{ column-gap:12px; row-gap:16px; padding:26px 0 20px }}
      .brand-block {{ gap:7px; min-width:0 }}
      .brand {{ font-size:clamp(28px,9.5vw,36px); flex:0 0 auto }}
      .inspired {{ font-size:7px; letter-spacing:.08em; flex:0 1 auto; overflow:hidden; text-overflow:clip }}
      .masthead-actions {{ gap:7px }}
      .tagline {{ font-size:12px; line-height:1.45 }}
      .owner-controls {{ position:fixed; top:52px; right:16px; left:auto; width:min(320px,calc(100vw - 32px)); padding:16px; gap:10px; box-shadow:0 18px 46px #0005 }}
      .owner-control-actions {{ grid-template-columns:1fr 1fr; gap:8px }}
      .owner-control-actions [data-owner-backup] {{ grid-column:1/-1 }}
      .owner-controls button {{ min-height:42px }}
      .provider-buttons {{ grid-template-columns:1fr 1fr }}
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
      {owner_access_html}
    </div>
    <div class="tagline">Can a fresh AI pick up where the last one left off?</div></header>
  <dialog class="handoff-dialog" data-handoff-dialog>
    <div class="handoff-shell">
      <div class="handoff-head"><div><span class="eyebrow">Owner-only transport</span><h2>Manual AI handoff</h2></div><button type="button" data-handoff-close aria-label="Close manual handoff">Close</button></div>
      <div class="provider-buttons" aria-label="Choose destination">
        <a href="com.openai.chat://" data-handoff-provider="ChatGPT">ChatGPT</a><a href="claude://" data-handoff-provider="Claude">Claude</a><a href="https://gemini.google.com/app" target="_blank" rel="noopener noreferrer" data-handoff-provider="Gemini">Gemini</a><a href="deepseek://" data-handoff-provider="DeepSeek">DeepSeek</a>
      </div>
      <label class="handoff-field">Prompt to paste<textarea data-handoff-prompt readonly>{_escape(manual_prompt)}</textarea></label>
      <div class="handoff-actions"><button type="button" data-handoff-copy>Copy prompt</button></div>
      <label class="handoff-field">Returned JSON<textarea data-handoff-response spellcheck="false" autocapitalize="off" autocomplete="off" placeholder="Paste the complete response here. It remains only in this browser page."></textarea></label>
      <div class="handoff-actions"><button type="button" data-handoff-submit disabled>Paste &amp; submit result</button></div>
      <p class="handoff-note" data-handoff-status>Select a destination. The prompt will be copied automatically when the browser permits it.</p>
    </div>
  </dialog>
  {observer_console_html}
  {_exchange_panel(continuity_proof)}
  <section class="owner-technical" data-owner-technical hidden aria-label="Operator technical view">
    <div class="technical-head">
      <div><span class="eyebrow">Operator only</span><h2>Technical view</h2></div>
      <span class="technical-badge">AUTHENTICATED VIEW</span>
    </div>
    <div class="technical-stats">
      <div><span>Record revision</span><strong data-record-revision>{context.revision}</strong></div>
      <div><span>Database</span><strong>{_format_bytes(health['database_bytes'])}</strong></div>
      <div><span>Replay</span><strong>{health['replay_ms']} ms</strong></div>
      <div><span>Receipts</span><strong>{total_receipts}</strong></div>
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
      <div data-semantic-review-form data-run-id="{_escape(semantic_run)}" data-context-digest="{_escape(semantic_digest)}">
        <div class="quality-grid">
          <label><span>Objective fidelity</span><select data-review-criterion="objective_fidelity"><option value="pass" selected>PASS</option><option value="uncertain">UNCERTAIN</option><option value="fail">FAIL</option></select></label>
          <label><span>History fidelity</span><select data-review-criterion="history_fidelity"><option value="pass" selected>PASS</option><option value="uncertain">UNCERTAIN</option><option value="fail">FAIL</option></select></label>
          <label><span>Frontier fidelity</span><select data-review-criterion="frontier_fidelity"><option value="pass" selected>PASS</option><option value="uncertain">UNCERTAIN</option><option value="fail">FAIL</option></select></label>
          <label><span>Compression awareness</span><select data-review-criterion="compression_awareness"><option value="pass" selected>PASS</option><option value="uncertain">UNCERTAIN</option><option value="fail">FAIL</option></select></label>
          <label><span>Unsupported claims</span><select data-review-criterion="unsupported_claims"><option value="pass" selected>PASS</option><option value="uncertain">UNCERTAIN</option><option value="fail">FAIL</option></select></label>
          <label><span>Actionability</span><select data-review-criterion="actionability"><option value="pass" selected>PASS</option><option value="uncertain">UNCERTAIN</option><option value="fail">FAIL</option></select></label>
        </div>
        <div class="handoff-actions"><button type="button" data-semantic-review-submit>Record review</button></div>
        <div class="quality-provenance" data-semantic-review-message>Review writes only one bounded assessment event.</div>
      </div>
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
  <footer class="quiet-footer">Public view shows the experiment. Authenticated operator sessions unlock the technical record and controls.</footer>
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
const controlUrl={json.dumps(control_url)};
const ownerLogin=document.querySelector('[data-owner-login]');
const ownerMenuToggle=document.querySelector('[data-owner-menu-toggle]');
const ownerMenuLabel=document.querySelector('[data-owner-menu-label]');
const ownerControls=document.querySelector('[data-owner-controls]');
const ownerIdentity=document.querySelector('[data-owner-identity]');
const ownerControlStatus=document.querySelector('[data-owner-control-status]');
const ownerStart=document.querySelector('[data-owner-start]');
const ownerStop=document.querySelector('[data-owner-stop]');
const ownerBackup=document.querySelector('[data-owner-backup]');
const ownerHandoff=document.querySelector('[data-owner-handoff]');
const ownerSignout=document.querySelector('[data-owner-signout]');
const ownerTechnical=document.querySelector('[data-owner-technical]');
const handoffDialog=document.querySelector('[data-handoff-dialog]');
const handoffPrompt=document.querySelector('[data-handoff-prompt]');
const handoffResponse=document.querySelector('[data-handoff-response]');
const handoffStatus=document.querySelector('[data-handoff-status]');
const handoffSubmit=document.querySelector('[data-handoff-submit]');
const semanticReviewForm=document.querySelector('[data-semantic-review-form]');
const semanticReviewSubmit=document.querySelector('[data-semantic-review-submit]');
const semanticReviewMessage=document.querySelector('[data-semantic-review-message]');
const handoffBasePrompt=handoffPrompt?.value||'';
let handoffProvider='';
const ownerSessionKey='sudofx-owner-session';
const ownerFragment='#sudofx-control=';
const handoffReturnFragment='#handoff-evaluate';
const handoffReturnKey='sudofx-pending-handoff-evaluation';
try{{
  if(!localStorage.getItem(ownerSessionKey)){{
    const legacy=sessionStorage.getItem(ownerSessionKey);
    if(legacy)localStorage.setItem(ownerSessionKey,legacy);
  }}
  sessionStorage.removeItem(ownerSessionKey);
}}catch{{}}
// OAuth returns encrypted session ciphertext in the fragment. Fragments never
// reach Pages or referrer headers; move it to origin-persistent localStorage and immediately
// remove it from the address bar before making an authenticated request.
if(controlUrl && location.hash.startsWith(ownerFragment)){{
  try{{
    localStorage.setItem(ownerSessionKey,decodeURIComponent(location.hash.slice(ownerFragment.length)));
    history.replaceState(null,'',location.pathname+location.search);
  }}catch{{}}
}}
const ownerSession=()=>{{try{{return localStorage.getItem(ownerSessionKey)||''}}catch{{return ''}}}};
// The Shortcut transports no credential and no model response in its URL. Its
// fragment is only a same-browser intent marker; the response remains on the
// clipboard until an authenticated, user-initiated paste submits it.
if(location.hash===handoffReturnFragment){{
  try{{sessionStorage.setItem(handoffReturnKey,'1')}}catch{{}}
  history.replaceState(null,'',location.pathname+location.search);
}}
const pendingHandoffReturn=()=>{{try{{return sessionStorage.getItem(handoffReturnKey)==='1'}}catch{{return false}}}};
if(controlUrl&&pendingHandoffReturn()&&!ownerSession())location.assign(controlUrl+'/auth/login');
const formatBytes=(value)=>{{
  // This is the browser equivalent of the server renderer's presentation-only
  // formatter. The Worker still returns the exact integer byte count; no display
  // rounding becomes storage or governance truth.
  const units=['B','KB','MB','GB'];
  let amount=Math.max(0,Number(value)||0),unit=0;
  while(amount>=1024&&unit<units.length-1){{amount/=1024;unit+=1;}}
  if(unit===0)return Math.trunc(amount)+' B';
  const precision=amount>=100?0:1;
  return Number(amount.toFixed(precision))+' '+units[unit];
}};
const ownerRequest=async(path,method='GET',payload=null)=>{{
  const headers={{Authorization:'Bearer '+ownerSession()}};
  if(payload!==null)headers['Content-Type']='application/json';
  const response=await fetch(controlUrl+path,{{method,headers,body:payload===null?undefined:JSON.stringify(payload)}});
  const body=await response.json().catch(()=>({{}}));
  if(!response.ok)throw new Error(body.error||'Owner control request failed');
  return body;
}};
// The popover is presentational state only. Closing it never changes workflow
// authority, while signing out explicitly removes the origin-persistent session.
const setOwnerMenu=(open)=>{{
  if(!ownerMenuToggle||!ownerControls)return;
  ownerControls.hidden=!open;
  ownerMenuToggle.setAttribute('aria-expanded',String(open));
}};
const showOwnerSignedOut=()=>{{
  if(handoffDialog?.open)handoffDialog.close();
  if(handoffResponse)handoffResponse.value='';
  setOwnerMenu(false);
  if(ownerMenuToggle)ownerMenuToggle.hidden=true;
  if(ownerLogin)ownerLogin.hidden=false;
  if(ownerTechnical)ownerTechnical.hidden=true;
}};
const applyOwnerWorkflowState=(state)=>{{
  // The authenticated control service reads the workflow's enabled flag and
  // active runs with the owner's GitHub token. When available, that evidence
  // outranks both anonymous API telemetry and the last published HTML snapshot.
  const running=state.enabled&&state.activeRuns.length>0;
  const visualState=running?'working':(state.enabled?'continuous':'idle');
  observer.className='observer-console '+visualState;
  observerState.className='observer-state '+visualState;
  observerState.textContent=running?'Live':(state.enabled?'Running':'Stopped');
  currentActivity.textContent=running
    ?'Waiting for Gemini and governing its response'
    :(state.enabled?'Continuous runner enabled; next cycle is starting':'Continuous tests stopped by owner');
  currentStep.textContent=running?'GitHub Actions cycle in progress':(state.enabled?'Starting next cycle':'No Gemini request in progress');
  updateNextCheck(visualState);
  observerDetail.textContent=state.enabled
    ?'Authenticated owner control confirms continuous operation is enabled.'
    :'Authenticated owner control confirms the workflow is disabled and no new cycle can start.';
  if(statusLed)statusLed.className='status-led '+visualState;
  if(machineActivity){{machineActivity.hidden=true;machineActivity.classList.remove('working');}}
  if(exchangeStatus){{exchangeStatus.textContent=running?'WAITING ON GEMINI':'LAST EXCHANGE';exchangeStatus.className='exchange-status '+(running?'working':'');}}
}};
const refreshOwnerControls=async()=>{{
  if(!controlUrl||!ownerControls||!ownerSession())return null;
  try{{
    const state=await ownerRequest('/api/session');
    // Older deployed control workers may not yet include latestRun. Hydrate it
    // from the same public GitHub workflow feed used by signed-out observers so
    // authenticated and incognito views cannot disagree during rollout.
    if(!state.latestRun&&observer){{
      try{{
        const repo=observer.dataset.repository, workflow=observer.dataset.workflow;
        const latestResponse=await fetch('https://api.github.com/repos/'+repo+'/actions/workflows/'+workflow+'/runs?per_page=1',{{cache:'no-store'}});
        if(latestResponse.ok){{
          const latestData=await latestResponse.json();
          const latest=Array.isArray(latestData.workflow_runs)?latestData.workflow_runs[0]:null;
          if(latest)state.latestRun={{id:latest.id,status:latest.status,conclusion:latest.conclusion||null,url:latest.html_url}};
        }}
      }}catch{{}}
    }}
    ownerLogin.hidden=true;
    ownerMenuToggle.hidden=false;
    if(ownerTechnical)ownerTechnical.hidden=false;
    ownerIdentity.textContent='Signed in as '+state.login;
    const maintenance=state.maintenance||{{}};
    const databaseSize=Number(maintenance.databaseBytes||0);
    const storageRisk=maintenance.repositoryVisibility==='public'?'public state':maintenance.repositoryVisibility||'unknown visibility';
    const protection=maintenance.stateBranchProtected?'protected':'unprotected';
    const latest=state.latestRun||null;
    const failed=Boolean(state.enabled&&!state.activeRuns.length&&latest&&latest.status==='completed'&&latest.conclusion==='failure');
    const workflowLabel=state.enabled?(state.activeRuns.length?'Running now':(failed?'Paused · last cycle failed':'Enabled · next cycle starting')):'Stopped';
    ownerMenuLabel.textContent='Settings';
    ownerMenuToggle.classList.toggle('is-active',state.enabled);
    ownerControlStatus.textContent=workflowLabel+' · DB '+formatBytes(databaseSize)+' · '+storageRisk+' · '+protection;
    ownerStart.disabled=state.enabled;
    ownerStop.disabled=!state.enabled;
    if(ownerBackup){{ownerBackup.hidden=!Array.isArray(state.capabilities)||!state.capabilities.includes('backup');ownerBackup.disabled=false;}}
    const handoffEvaluateEnabled=Array.isArray(state.capabilities)&&state.capabilities.includes('handoff-evaluate');
    if(handoffSubmit)handoffSubmit.disabled=!handoffEvaluateEnabled;
    const semanticReviewEnabled=Array.isArray(state.capabilities)&&state.capabilities.includes('semantic-review');
    if(semanticReviewSubmit)semanticReviewSubmit.disabled=!semanticReviewEnabled;
    if(pendingHandoffReturn()&&handoffEvaluateEnabled&&handoffDialog){{
      try{{sessionStorage.removeItem(handoffReturnKey)}}catch{{}}
      if(!handoffDialog.open)handoffDialog.showModal();
      handoffStatus.textContent='Claude result ready. Tap Paste & submit result.';
    }}
    applyOwnerWorkflowState(state);
    return state;
  }}catch{{
    try{{localStorage.removeItem(ownerSessionKey)}}catch{{}}
    showOwnerSignedOut();
    // A Shortcut return may find an expired encrypted session. Preserve only
    // the intent marker and re-enter the same OAuth gateway; the clipboard text
    // never leaves the device until the replacement session is verified.
    if(pendingHandoffReturn()&&controlUrl)location.assign(controlUrl+'/auth/login');
    return null;
  }}
}};
const operateOwnerControl=async(path,event,refresh=true)=>{{
  // iOS may deliver the same tap through the document-level dismissal handler.
  // Keep the operator panel open until this request has a visible outcome; a
  // control action must never look like an unexplained navigation or dismissal.
  event?.stopPropagation();
  setOwnerMenu(true);
  const label=path==='/api/backup'?'backup':(path==='/api/start'?'start':'stop');
  const disabledBefore={{start:ownerStart.disabled,stop:ownerStop.disabled,backup:ownerBackup?.disabled||false}};
  ownerStart.disabled=true;ownerStop.disabled=true;if(ownerBackup)ownerBackup.disabled=true;
  ownerControlStatus.textContent='Requesting '+label+'…';
  try{{
    const result=await ownerRequest(path,'POST');
    // Backup does not change workflow state, so refreshing would only replace
    // its acceptance message with generic status. Start and Stop do refresh,
    // but their action result is restored afterward as the visible outcome.
    if(refresh)await refreshOwnerControls();
    setOwnerMenu(true);
    ownerControlStatus.textContent=result.message||'Request accepted.';
    if(!refresh){{
      ownerStart.disabled=disabledBefore.start;
      ownerStop.disabled=disabledBefore.stop;
      if(ownerBackup)ownerBackup.disabled=disabledBefore.backup;
    }}
  }}catch(error){{
    setOwnerMenu(true);
    ownerControlStatus.textContent='Request failed: '+error.message;
    ownerStart.disabled=disabledBefore.start;
    ownerStop.disabled=disabledBefore.stop;
    if(ownerBackup)ownerBackup.disabled=disabledBefore.backup;
  }}
}};
if(ownerStart)ownerStart.addEventListener('click',(event)=>operateOwnerControl('/api/start',event));
if(ownerStop)ownerStop.addEventListener('click',(event)=>operateOwnerControl('/api/stop',event));
if(ownerBackup)ownerBackup.addEventListener('click',(event)=>operateOwnerControl('/api/backup',event,false));
const copyText=async(value)=>{{
  await navigator.clipboard.writeText(value);
}};
const freshHandoffId=()=>{{
  const words=new Uint32Array(1);
  crypto.getRandomValues(words);
  return 'UUID-'+String(words[0]%1000000).padStart(6,'0');
}};
const selectHandoffProvider=(link)=>{{
  handoffProvider=link.dataset.handoffProvider||'';
  const testId=freshHandoffId();
  const nonce='HANDOFF-'+testId;
  const transportPrompt=handoffBasePrompt
    .replaceAll('__SUDOFX_VENDOR__',handoffProvider)
    .replaceAll('__SUDOFX_TEST_ID__',testId)
    .replaceAll('__SUDOFX_NONCE__',nonce);
  // Selecting a destination is a fresh authenticated operator action. Carry
  // that narrow authority with the human-transported packet so a prior durable
  // Stop still blocks automation but does not make this one requested response
  // look unauthorized to the receiving intelligence.
  handoffPrompt.value='CURRENT OPERATOR AUTHORIZATION\\nThe authenticated operator explicitly selected '+handoffProvider+' for exactly one manual response to this packet. This authorizes the response only; it does not authorize durable mutation, continuous execution, or another model invocation. A prior Stop in the durable packet remains authoritative for those other actions. Do not use this authorization paragraph as evidence; evidence must quote only the COMPLETE JSON PACKET.\\n\\n'+transportPrompt;
  // ChatGPT currently accepts an undocumented prompt parameter that can fill
  // the composer, but it does not submit the message. Keep clipboard transport
  // as the durable fallback and never infer equivalent parameters for vendors
  // that publish only bare app handlers.
  if(handoffProvider==='ChatGPT'){{
    link.href='com.openai.chat://chatgpt.com/?temporary-chat=true&prompt='+encodeURIComponent(handoffPrompt.value);
  }}
  document.querySelectorAll('[data-handoff-provider]').forEach(candidate=>candidate.setAttribute('aria-pressed',String(candidate===link)));
  // Start the clipboard write during the trusted tap that follows the app URI.
  // Awaiting it first can consume Safari's user activation and prevent iOS from
  // opening the destination. The visible prompt remains the manual fallback.
  copyText(handoffPrompt.value).catch(()=>{{handoffPrompt.focus();handoffPrompt.select();}});
  handoffStatus.textContent=handoffProvider==='ChatGPT'
    ?'ChatGPT opening with a draft when supported. Tap Send; if the draft is empty, paste the copied prompt.'
    :handoffProvider+' opening. Paste the copied prompt into a new chat and send it.';
}};
if(ownerHandoff)ownerHandoff.addEventListener('click',()=>{{
  setOwnerMenu(false);
  if(handoffDialog&&!ownerHandoff.disabled)handoffDialog.showModal();
}});
document.querySelectorAll('[data-handoff-provider]').forEach(link=>link.addEventListener('click',()=>selectHandoffProvider(link)));
document.querySelector('[data-handoff-copy]')?.addEventListener('click',async()=>{{
  try{{await copyText(handoffPrompt.value);handoffStatus.textContent='Prompt copied.';}}
  catch{{handoffPrompt.focus();handoffPrompt.select();handoffStatus.textContent='Clipboard access was blocked; the prompt is selected.';}}
}});
handoffSubmit?.addEventListener('click',async()=>{{
  // Clipboard reads require this trusted tap on iOS. The Shortcut therefore
  // carries only transient text and a page URL; the browser session remains the
  // sole authority that can ask the Worker to spend GitHub Actions permission.
  let response=handoffResponse.value.trim();
  if(!response){{
    try{{response=(await navigator.clipboard.readText()).trim();handoffResponse.value=response;}}
    catch{{handoffStatus.textContent='Clipboard access was blocked. Paste the returned JSON above, then tap submit again.';handoffResponse.focus();return;}}
  }}
  if(!response){{handoffStatus.textContent='The clipboard does not contain a handoff response.';return;}}
  handoffSubmit.disabled=true;
  handoffStatus.textContent='Submitting through the authenticated operator…';
  try{{
    const result=await ownerRequest('/api/operate','POST',{{action:'handoff-evaluate',response}});
    handoffResponse.value='';
    handoffStatus.textContent=result.message||'Handoff evaluation accepted for governed recording.';
  }}catch(error){{
    handoffStatus.textContent='Submission failed: '+error.message;
  }}finally{{handoffSubmit.disabled=false;}}
}});
if(semanticReviewSubmit)semanticReviewSubmit.addEventListener('click',async(event)=>{{
  event.stopPropagation();
  if(!semanticReviewForm)return;
  const criteria={{}};
  semanticReviewForm.querySelectorAll('[data-review-criterion]').forEach(select=>{{criteria[select.dataset.reviewCriterion]=select.value;}});
  const review={{
    artifact_run_id:String(semanticReviewForm.dataset.runId||''),
    context_digest:String(semanticReviewForm.dataset.contextDigest||''),
    criteria,
  }};
  semanticReviewSubmit.disabled=true;
  if(semanticReviewMessage)semanticReviewMessage.textContent='Binding review to authoritative SQLite evidence…';
  const originalLabel=semanticReviewSubmit.textContent;
  try{{
    await ownerRequest('/api/operate','POST',{{action:'semantic-review',review}});
    semanticReviewSubmit.textContent='Recording…';
    if(semanticReviewMessage)semanticReviewMessage.textContent='Request accepted. Waiting for SQLite confirmation…';
    let confirmed=false;
    for(let attempt=0;attempt<15;attempt+=1){{
      await new Promise(resolve=>setTimeout(resolve,2000));
      const proof=await refreshExchange();
      const operatorReview=proof&&proof.semantic_review&&proof.semantic_review.reviewers&&proof.semantic_review.reviewers.operator;
      if(operatorReview&&String(operatorReview.status||'pending')!=='pending'){{
        confirmed=true;
        break;
      }}
    }}
    if(confirmed){{
      semanticReviewSubmit.textContent='Recorded ✓';
      if(semanticReviewMessage)semanticReviewMessage.textContent='Recorded in authoritative SQLite.';
      setTimeout(()=>{{semanticReviewSubmit.textContent=originalLabel;semanticReviewSubmit.disabled=false;}},1200);
    }}else{{
      semanticReviewSubmit.textContent=originalLabel;
      semanticReviewSubmit.disabled=false;
      if(semanticReviewMessage)semanticReviewMessage.textContent='Submitted, but SQLite confirmation is still pending. Live status will keep refreshing.';
    }}
  }}catch(error){{
    if(semanticReviewMessage)semanticReviewMessage.textContent='Review failed: '+error.message;
    semanticReviewSubmit.textContent=originalLabel;
    semanticReviewSubmit.disabled=false;
  }}
}});
document.querySelector('[data-handoff-close]')?.addEventListener('click',()=>handoffDialog?.close());
if(ownerMenuToggle)ownerMenuToggle.addEventListener('click',(event)=>{{event.stopPropagation();setOwnerMenu(ownerControls.hidden);}});
if(ownerControls)ownerControls.addEventListener('click',(event)=>event.stopPropagation());
if(ownerSignout)ownerSignout.addEventListener('click',()=>{{try{{localStorage.removeItem(ownerSessionKey)}}catch{{}}showOwnerSignedOut();}});
document.addEventListener('click',()=>setOwnerMenu(false));
document.addEventListener('keydown',(event)=>{{if(event.key==='Escape')setOwnerMenu(false);}});
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
  // Signed-in owners already have a narrower, authenticated status source.
  // Avoid letting an anonymous rate limit or stale published artifact overwrite
  // a successful Stop with the opposite message.
  if(ownerSession()&&await refreshOwnerControls())return;
  const repo=observer.dataset.repository, workflow=observer.dataset.workflow;
  try{{
    const [workflowResponse,response]=await Promise.all([
      fetch('https://api.github.com/repos/'+repo+'/actions/workflows/'+workflow,{{cache:'no-store'}}),
      fetch('https://api.github.com/repos/'+repo+'/actions/workflows/'+workflow+'/runs?per_page=1',{{cache:'no-store'}})
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
    observer.className='observer-console '+visualState;
    observerState.className='observer-state '+visualState;
    observerState.textContent=running?'Live':(failed?'Paused':(enabled?'Running':'Stopped'));
    if(statusLed)statusLed.className='status-led '+visualState;
    currentActivity.textContent=running?'Gemini is answering now':(failed?'The last test stopped unexpectedly':(enabled?'Continuous runner enabled; next cycle is starting':'Continuous tests stopped by owner'));
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
    if(semanticReviewForm){{
      const targetChanged=semanticReviewForm.dataset.runId!==reviewRunId||semanticReviewForm.dataset.contextDigest!==reviewDigest;
      semanticReviewForm.dataset.runId=reviewRunId;
      semanticReviewForm.dataset.contextDigest=reviewDigest;
      if(targetChanged&&semanticReviewMessage)semanticReviewMessage.textContent='Review target updated. Submission is bound to this exact run + digest.';
    }}
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
    control_url: str = "",
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
            control_url=control_url,
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
