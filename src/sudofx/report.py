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

from .kernel import Kernel
from .models import Context


def _escape(value: object) -> str:
    """Escape all durable or operator text before placing it in HTML attributes or content."""
    return html.escape(str(value), quote=True)


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
    Translate the provider boundary into the conversation an operator cares about.

    The complete proof remains available as a derived JSON artifact. This view
    deliberately omits transport metadata and test mechanics: it shows the
    bounded meaning sent to Gemini, Gemini's semantic answer, and the system's
    governed treatment of that answer without promoting any of those projections
    into authority.
    """
    review = proof.get("semantic_review", {})
    evidence = review.get("evidence", {}) if isinstance(review, dict) else {}
    if not isinstance(evidence, dict):
        evidence = {}
    objective = evidence.get("objective", "No current objective was supplied.")
    accepted = evidence.get("accepted_results", [])
    obligations = evidence.get("open_obligations", [])
    constraints = evidence.get("constraints", [])
    response = proof.get("candidate_result", "No Gemini response has been published yet.")
    rationale = proof.get("candidate_rationale", "")
    action = (
        "Governance accepted the proposal on an isolated verification snapshot. "
        "The durable record was not changed; the next test cycle starts automatically."
        if proof.get("assessment_status") == "semantic_review_pending"
        else "No governed Gemini proposal has been published yet."
    )
    def items(value: object, empty: str) -> str:
        values = value if isinstance(value, list) else []
        return "".join(f"<li>{_escape(item)}</li>" for item in values) or f"<li>{empty}</li>"

    return f"""
      <section class="exchange" aria-label="Gemini exchange" data-artifact-run-id="{_escape(proof.get('artifact_run_id', ''))}">
        <div class="exchange-head">
          <div><span class="eyebrow">Intelligence exchange</span><h2>What Gemini was asked</h2></div>
          <span class="exchange-status" data-exchange-status>LAST EXCHANGE</span>
        </div>
        <p class="question">Using only the durable context below, reconstruct this work and propose one concrete next step.</p>
        <dl class="context-brief">
          <div><dt>Objective</dt><dd data-exchange-objective>{_escape(objective)}</dd></div>
          <div><dt>Accepted progress</dt><dd><ul data-exchange-accepted>{items(accepted, 'None yet')}</ul></dd></div>
          <div><dt>Current frontier</dt><dd><ul data-exchange-frontier>{items(obligations, 'No open obligation recorded')}</ul></dd></div>
          <div><dt>Constraints</dt><dd><ul data-exchange-constraints>{items(constraints, 'No additional constraints')}</ul></dd></div>
        </dl>
        <div class="exchange-answer"><span>Gemini responded</span><p data-exchange-response>{_escape(response)}</p>
          <small data-exchange-rationale{' hidden' if not rationale else ''}>{f'Why: {_escape(rationale)}' if rationale else ''}</small></div>
        <div class="exchange-action"><span>What sudofx did</span><p data-exchange-action>{_escape(action)}</p></div>
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
    observer_continuous = continuity_proof.get("assessment_status") == "semantic_review_pending"
    # A semantic review result remains evidence rather than authoritative state,
    # but continuous test authorization means it no longer pauses the observer.
    # The presentation therefore describes execution truth without pretending
    # that Gemini's proposal was applied to the durable work item.
    observer_static_state = "CONTINUOUS" if observer_continuous else "IDLE"
    observer_static_activity = (
        "Latest Gemini cycle complete; next cycle starts automatically"
        if observer_continuous
        else "No bounded operation currently running"
    )
    observer_static_detail = (
        "Continuous mode is active. Every successful published cycle immediately starts another bounded Gemini test."
        if observer_continuous
        else "No continuous cycle is active. Start the continuation workflow to resume."
    )
    observer_console_html = f"""
        <section class="observer-console checking" aria-label="Development status"
                 data-repository="{_escape(repository)}" data-workflow="prove-model.yml"
                 data-fallback-state="{observer_static_state}"
                 data-fallback-activity="{_escape(observer_static_activity)}"
                 data-fallback-detail="{_escape(observer_static_detail)}">
          <div class="observer-head">
            <div>
              <span class="eyebrow">Live development</span>
              <h1>What sudofx is doing</h1>
            </div>
            <div class="observer-signal" aria-live="polite">
              <span class="status-led checking" data-status-led aria-hidden="true"></span>
              <span class="observer-state checking" data-observer-state>CHECKING…</span>
            </div>
          </div>
          <div class="observer-grid">
            <div class="observer-cell primary"><span>Current activity</span><strong data-current-activity>Loading live workflow status…</strong></div>
            <div class="observer-cell"><span>Current step</span><strong data-current-step>Checking GitHub…</strong></div>
            <div class="observer-cell"><span>Latest run</span><strong data-latest-run>{_escape(verification.get("run_id", "unknown"))}</strong></div>
            <div class="observer-cell"><span>Next cycle</span><strong data-next-check>Checking chain…</strong></div>
          </div>
          <div class="machine-activity" data-machine-activity hidden aria-live="polite">
            <div class="machine-lights" aria-hidden="true">
              <i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i>
            </div>
            <div class="machine-track" aria-hidden="true"><span data-machine-text>PROCESSING VERIFIED WORK</span></div>
          </div>
          <div class="observer-detail">
            <span data-observer-detail>Connecting to GitHub…</span>
            <a href="https://github.com/{_escape(repository)}/actions/workflows/prove-model.yml">Open workflow ↗</a>
          </div>
          {f'''<div class="owner-access" data-owner-access>
            <a class="owner-login" data-owner-login href="{_escape(control_url)}/auth/login">Owner sign in</a>
            <div class="owner-controls" data-owner-controls hidden aria-live="polite">
              <span data-owner-identity></span>
              <span data-owner-control-status>Checking controls…</span>
              <div><button type="button" data-owner-start>Start</button><button type="button" data-owner-stop>Stop</button><button type="button" data-owner-backup hidden>Backup</button></div>
            </div>
          </div>''' if control_url else ''}
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
    header {{ display:grid; grid-template-columns:minmax(0,1fr) auto; grid-template-areas:"brand theme" "tagline tagline";
      column-gap:20px; row-gap:8px; align-items:start; padding-bottom:16px }}
    .brand-block {{ grid-area:brand; display:inline-flex; align-items:baseline; gap:12px; min-width:0 }}
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
    .status-led {{ width:12px; height:12px; border-radius:50%; flex:0 0 12px; animation:led-blink 1.1s ease-in-out infinite }}
    .status-led.checking {{ background:var(--accent); box-shadow:0 0 9px var(--accent) }}
    .status-led.idle,.status-led.waiting {{ background:#e0af68; box-shadow:0 0 8px #e0af68 }}
    .status-led.continuous {{ background:var(--green); box-shadow:0 0 10px var(--green) }}
    .status-led.working {{ background:var(--green); box-shadow:0 0 10px var(--green) }}
    .status-led.failed {{ background:#f7768e; box-shadow:0 0 10px #f7768e }}
    @keyframes led-blink {{ 0%,100% {{ opacity:.25 }} 50% {{ opacity:1 }} }}
    .observer-state {{ padding:6px 9px; border:1px solid var(--line); font:800 11px var(--mono); letter-spacing:.04em }}
    .observer-state.working {{ color:var(--green); border-color:var(--green) }}
    .observer-state.failed {{ color:var(--hot); border-color:var(--hot) }}
    .observer-state.waiting {{ color:var(--accent); border-color:var(--accent) }}
    .observer-state.continuous {{ color:var(--green); border-color:var(--green) }}
    .observer-state.checking {{ color:var(--accent); border-color:var(--accent) }}
    .observer-grid {{ display:grid; grid-template-columns:2fr 1fr 1fr; gap:1px; background:var(--line); border:1px solid var(--line) }}
    .observer-cell {{ min-width:0; padding:14px; background:var(--paper) }}
    .observer-cell span {{ display:block; color:var(--muted); font:700 9px var(--mono); letter-spacing:.08em; text-transform:uppercase }}
    .observer-cell strong {{ display:block; margin-top:7px; font-size:13px; line-height:1.25; overflow-wrap:anywhere }}
    .observer-detail {{ display:flex; justify-content:space-between; gap:14px; margin-top:12px; color:var(--muted); font:11px var(--mono) }}
    .observer-detail a {{ color:var(--accent); text-decoration:none; white-space:nowrap }}
    .owner-access {{ margin-top:14px; padding-top:14px; border-top:1px solid var(--line); font:11px var(--mono) }}
    .owner-login {{ color:var(--muted); text-decoration:none }}
    .owner-controls {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px 14px; align-items:center }}
    .owner-controls>* {{ min-width:0 }}
    .owner-controls>[data-owner-control-status] {{ overflow-wrap:anywhere }}
    .owner-controls[hidden] {{ display:none }}
    .owner-controls>[data-owner-control-status] {{ color:var(--muted) }}
    .owner-controls>div {{ grid-column:1/-1; display:grid; grid-template-columns:repeat(3,1fr); gap:8px }}
    .owner-controls button {{ min-height:44px; border:1px solid var(--line); background:var(--paper); color:var(--ink); font:800 12px var(--mono); cursor:pointer }}
    .owner-controls [data-owner-start] {{ border-color:var(--green); color:var(--green) }}
    .owner-controls [data-owner-stop] {{ border-color:#f7768e; color:#f7768e }}
    .owner-controls button:disabled {{ opacity:.45; cursor:wait }}
    .owner-controls button[hidden] {{ display:none }}
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
    .exchange {{ margin:0 0 38px; padding:18px; border:1px solid var(--line); background:var(--surface) }}
    .exchange-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px }}
    .exchange-head h2 {{ margin-top:6px }}
    .exchange-status {{ padding:5px 8px; border:1px solid var(--line); color:var(--muted); font:800 10px var(--mono); letter-spacing:.04em; white-space:nowrap }}
    .exchange-status.working {{ color:var(--green); border-color:var(--green) }}
    .question {{ margin:18px 0; padding:14px; border-left:4px solid var(--accent); background:var(--paper); font-size:16px; font-weight:650 }}
    .context-brief {{ display:grid; gap:1px; margin:0; background:var(--line); border:1px solid var(--line) }}
    .context-brief>div {{ display:grid; grid-template-columns:140px 1fr; gap:14px; padding:12px; background:var(--paper) }}
    .context-brief dt,.exchange-answer>span,.exchange-action>span {{ color:var(--accent); font:700 10px var(--mono); letter-spacing:.08em; text-transform:uppercase }}
    .context-brief dd {{ margin:0; font-size:14px; overflow-wrap:anywhere }}
    .context-brief ul {{ margin:0; padding-left:18px }}
    .exchange-answer,.exchange-action {{ margin-top:16px; padding-top:14px; border-top:1px solid var(--line) }}
    .exchange-answer p,.exchange-action p {{ margin:7px 0 0; font-size:15px; overflow-wrap:anywhere }}
    .exchange-answer small {{ display:block; margin-top:8px; color:var(--muted) }}
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
    .theme-switch {{ grid-area:theme; justify-self:end; display:flex; align-items:center; gap:8px; cursor:pointer; user-select:none }}
    .theme-switch input {{ position:absolute; width:1px; height:1px; margin:0; opacity:0; pointer-events:none }}
    /* The track is the complete visual control. A second theme glyph repeated
       the same meaning and introduced an unnecessary alignment relationship. */
    .data-switch-track {{ width:42px; height:24px; padding:2px; border:1px solid var(--line); background:var(--surface); border-radius:20px }}
    .data-switch-track i {{ display:block; width:18px; height:18px; border-radius:50%; background:var(--muted); transition:transform .2s ease,background .2s ease }}
    .theme-switch input:checked + .data-switch-track i {{ transform:translateX(17px); background:var(--green) }}
    .theme-switch input:focus-visible + .data-switch-track {{ outline:3px solid var(--green); outline-offset:3px }}
    @media(max-width:600px) {{ header {{ column-gap:16px }}
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
    <label class="theme-switch" title="Follow system theme"><input id="theme-toggle" type="checkbox" role="switch" aria-label="Use dark theme"><span class="data-switch-track" aria-hidden="true"><i></i></span></label>
    <div class="tagline">Durable, accountable work across interchangeable intelligences.</div></header>
  {observer_console_html}
  {_exchange_panel(continuity_proof)}
  <section><div class="toolbar"><div><span class="eyebrow">{open_work} open</span><h2>Current work</h2></div></div>
    <div class="work-grid">{_work_cards(context.state)}</div></section>
  <details class="history"><summary>Activity history · showing {len(history)} of {total_receipts} receipts</summary>
    <div class="history-tools"><input id="search" type="search" placeholder="Filter activity…" aria-label="Filter activity history"></div>
    <div class="receipts" id="receipts">{_receipt_rows(history)}</div></details>
  <footer>Verified durable record · revision {context.revision} · {int(health['database_bytes'])} database bytes · {health['replay_ms']} ms replay · Pages is a read-only view.</footer>
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
const controlUrl={json.dumps(control_url)};
const ownerLogin=document.querySelector('[data-owner-login]');
const ownerControls=document.querySelector('[data-owner-controls]');
const ownerIdentity=document.querySelector('[data-owner-identity]');
const ownerControlStatus=document.querySelector('[data-owner-control-status]');
const ownerStart=document.querySelector('[data-owner-start]');
const ownerStop=document.querySelector('[data-owner-stop]');
const ownerBackup=document.querySelector('[data-owner-backup]');
const ownerSessionKey='sudofx-owner-session';
const ownerFragment='#sudofx-control=';
// OAuth returns encrypted session ciphertext in the fragment. Fragments never
// reach Pages or referrer headers; move it to sessionStorage and immediately
// remove it from the address bar before making an authenticated request.
if(controlUrl && location.hash.startsWith(ownerFragment)){{
  try{{
    sessionStorage.setItem(ownerSessionKey,decodeURIComponent(location.hash.slice(ownerFragment.length)));
    history.replaceState(null,'',location.pathname+location.search);
  }}catch{{}}
}}
const ownerSession=()=>{{try{{return sessionStorage.getItem(ownerSessionKey)||''}}catch{{return ''}}}};
const ownerRequest=async(path,method='GET')=>{{
  const response=await fetch(controlUrl+path,{{method,headers:{{Authorization:'Bearer '+ownerSession()}}}});
  const body=await response.json().catch(()=>({{}}));
  if(!response.ok)throw new Error(body.error||'Owner control request failed');
  return body;
}};
const applyOwnerWorkflowState=(state)=>{{
  // The authenticated control service reads the workflow's enabled flag and
  // active runs with the owner's GitHub token. When available, that evidence
  // outranks both anonymous API telemetry and the last published HTML snapshot.
  const running=state.enabled&&state.activeRuns.length>0;
  const visualState=running?'working':(state.enabled?'continuous':'idle');
  observer.className='observer-console '+visualState;
  observerState.className='observer-state '+visualState;
  observerState.textContent=running?'WORKING':(state.enabled?'CONTINUOUS':'STOPPED');
  currentActivity.textContent=running
    ?'Waiting for Gemini and governing its response'
    :(state.enabled?'Continuous runner enabled; next cycle is starting':'Continuous tests stopped by owner');
  currentStep.textContent=running?'GitHub Actions cycle in progress':(state.enabled?'Starting next cycle':'No Gemini request in progress');
  updateNextCheck(visualState);
  observerDetail.textContent=state.enabled
    ?'Authenticated owner control confirms continuous operation is enabled.'
    :'Authenticated owner control confirms the workflow is disabled and no new cycle can start.';
  if(statusLed)statusLed.className='status-led '+visualState;
  if(machineActivity){{machineActivity.hidden=!running;machineActivity.classList.toggle('working',running);}}
  if(exchangeStatus){{exchangeStatus.textContent=running?'WAITING ON GEMINI':'LAST EXCHANGE';exchangeStatus.className='exchange-status '+(running?'working':'');}}
}};
const refreshOwnerControls=async()=>{{
  if(!controlUrl||!ownerControls||!ownerSession())return null;
  try{{
    const state=await ownerRequest('/api/session');
    ownerLogin.hidden=true;
    ownerControls.hidden=false;
    ownerIdentity.textContent='Signed in as '+state.login;
    const maintenance=state.maintenance||{{}};
    const databaseSize=Number(maintenance.databaseBytes||0);
    const storageRisk=maintenance.repositoryVisibility==='public'?'public state':maintenance.repositoryVisibility||'unknown visibility';
    const protection=maintenance.stateBranchProtected?'protected':'unprotected';
    const workflowLabel=state.enabled?(state.activeRuns.length?'Running now':'Enabled · next cycle starting'):'Stopped';
    ownerControlStatus.textContent=workflowLabel+' · DB '+databaseSize+' bytes · '+storageRisk+' · '+protection;
    ownerStart.disabled=state.enabled;
    ownerStop.disabled=!state.enabled;
    if(ownerBackup){{ownerBackup.hidden=!Array.isArray(state.capabilities)||!state.capabilities.includes('backup');ownerBackup.disabled=false;}}
    applyOwnerWorkflowState(state);
    return state;
  }}catch{{
    try{{sessionStorage.removeItem(ownerSessionKey)}}catch{{}}
    ownerControls.hidden=true;
    ownerLogin.hidden=false;
    return null;
  }}
}};
const operateOwnerControl=async(path)=>{{
  ownerStart.disabled=true;ownerStop.disabled=true;if(ownerBackup)ownerBackup.disabled=true;ownerControlStatus.textContent='Updating…';
  try{{const result=await ownerRequest(path,'POST');ownerControlStatus.textContent=result.message;await refreshOwnerControls();}}
  catch(error){{ownerControlStatus.textContent=error.message;ownerStart.disabled=false;ownerStop.disabled=false;if(ownerBackup)ownerBackup.disabled=false;}}
}};
if(ownerStart)ownerStart.addEventListener('click',()=>operateOwnerControl('/api/start'));
if(ownerStop)ownerStop.addEventListener('click',()=>operateOwnerControl('/api/stop'));
if(ownerBackup)ownerBackup.addEventListener('click',()=>operateOwnerControl('/api/backup'));
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
    const response=await fetch('https://api.github.com/repos/'+repo+'/actions/workflows/'+workflow+'/runs?per_page=1',{{cache:'no-store'}});
    if(!response.ok)throw new Error('HTTP '+response.status);
    const data=await response.json(), run=Array.isArray(data.workflow_runs)?data.workflow_runs[0]:null;
    if(!run)throw new Error('No workflow run');
    latestRun.textContent='#'+String(run.run_number||run.id);
    const running=run.status!=='completed';
    const visualState=running?'working':(run.conclusion==='failure'?'failed':({json.dumps(observer_static_state)}==='CONTINUOUS'?'continuous':'idle'));
    observer.className='observer-console '+visualState;
    observerState.className='observer-state '+visualState;
    observerState.textContent=running?'WORKING':(run.conclusion==='failure'?'FAILED':{json.dumps(observer_static_state)});
    if(statusLed)statusLed.className='status-led '+visualState;
    currentActivity.textContent=running?'Waiting for Gemini and governing its response':(run.conclusion==='failure'?'Workflow needs inspection':{json.dumps(observer_static_activity)});
    updateNextCheck(visualState);
    if(exchangeStatus){{exchangeStatus.textContent=running?'WAITING ON GEMINI':'LAST EXCHANGE';exchangeStatus.className='exchange-status '+(running?'working':'');}}
    const jobsResponse=await fetch(run.jobs_url,{{cache:'no-store'}});
    if(jobsResponse.ok){{
      const jobsData=await jobsResponse.json(), jobs=Array.isArray(jobsData.jobs)?jobsData.jobs:[];
      const steps=jobs.flatMap(job=>Array.isArray(job.steps)?job.steps:[]);
      const active=steps.find(step=>step.status==='in_progress')||steps.find(step=>step.status==='queued');
      currentStep.textContent=active?active.name:(run.status==='completed'?'Complete':'Starting');
      if(machineActivity){{
        machineActivity.hidden=!running;
        machineActivity.classList.toggle('working',running);
      }}
      if(machineText && running){{
        const stepName=active?active.name:'Starting bounded development cycle';
        machineText.textContent='ACTIVE · '+stepName+' · RUN '+String(run.run_number||run.id)+' · VERIFIED TELEMETRY';
      }}
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
    observerState.textContent=observer.dataset.fallbackState;
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
const refreshExchange=async()=>{{
  if(!exchange)return;
  try{{
    const response=await fetch('./continuity-proof.json?ts='+Date.now(),{{cache:'no-store'}});
    if(!response.ok)throw new Error('proof unavailable');
    const proof=await response.json();
    const runId=String(proof.artifact_run_id||'');
    if(!runId||runId===exchange.dataset.artifactRunId)return;
    exchange.dataset.artifactRunId=runId;
    const evidence=proof.semantic_review?.evidence||{{}};
    document.querySelector('[data-exchange-objective]').textContent=String(evidence.objective||'No current objective was supplied.');
    updateList(document.querySelector('[data-exchange-accepted]'),evidence.accepted_results,'None yet');
    updateList(document.querySelector('[data-exchange-frontier]'),evidence.open_obligations,'No open obligation recorded');
    updateList(document.querySelector('[data-exchange-constraints]'),evidence.constraints,'No additional constraints');
    document.querySelector('[data-exchange-response]').textContent=String(proof.candidate_result||'No Gemini response was published.');
    const rationale=document.querySelector('[data-exchange-rationale]');
    rationale.textContent=proof.candidate_rationale?'Why: '+String(proof.candidate_rationale):'';
    rationale.hidden=!proof.candidate_rationale;
    document.querySelector('[data-exchange-action]').textContent=proof.assessment_status==='semantic_review_pending'
      ?'Governance accepted the proposal on an isolated verification snapshot. The durable record was not changed; the next test cycle starts automatically.'
      :'No governed Gemini proposal was published.';
    if(exchangeStatus){{exchangeStatus.textContent='UPDATED · RUN '+runId;exchangeStatus.className='exchange-status';}}
  }}catch(error){{/* Keep the last published exchange visible while Pages catches up. */}}
}};
refreshObserver();
refreshExchange();
setInterval(refreshObserver,15000);
setInterval(refreshExchange,15000);
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
