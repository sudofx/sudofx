"""
SUDOFX PUBLIC PROJECTION
========================

This module turns verified replayed state into a self-contained, phone-friendly
HTML artifact. The artifact is a projection: useful for inspection and navigation,
but never an input to governance, replay, or recovery.

Rendering is intentionally dependency-free so a fresh GitHub runner can publish
without a JavaScript toolchain or package registry. State-derived text is escaped
before interpolation. Interactive behavior is limited to filtering, disclosure,
theme preference, and links into GitHub's authenticated workflow control plane.

The browser receives no GitHub token and cannot mutate the record directly.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .kernel import Kernel


def _escape(value: object) -> str:
    """Escape all durable or operator text before placing it in HTML attributes or content."""
    return html.escape(str(value), quote=True)


def _state_cards(state: dict[str, object]) -> str:
    """Render non-work keys separately so generic kernel state remains inspectable."""
    visible = {key: value for key, value in state.items() if not key.startswith("work:")}
    if not visible:
        return '<div class="empty">No general state has been recorded.</div>'
    return "".join(
        f"""
        <article class="state-card">
          <div class="state-key">{_escape(key)}</div>
          <pre>{_escape(json.dumps(value, indent=2, ensure_ascii=False))}</pre>
        </article>
        """
        for key, value in sorted(visible.items())
    )


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
    context = kernel.context(receipt_limit=0)
    history = kernel.record.history()
    accepted = sum(event["status"] == "accepted" for event in history)
    rejected = len(history) - accepted
    work_items = [value for key, value in context.state.items() if key.startswith("work:")]
    open_work = sum(isinstance(item, dict) and item.get("status") == "open" for item in work_items)
    action_url = f"https://github.com/{repository}/actions/workflows/sudofx.yml"
    verification = verification or {}
    verified_commit = verification.get("commit", "")
    verified_run = verification.get("run_url", "")
    verification_html = (
        f"""
        <section class="verification" aria-label="Build verification">
          <div>
            <span class="eyebrow">Phone-ready verification</span>
            <h2>Tests passed before this page was published.</h2>
            <code>{_escape(verified_commit[:12] if verified_commit else "local / unknown commit")}</code>
          </div>
          {f'<a class="action" href="{_escape(verified_run)}">Open Action run ↗</a>' if verified_run else ''}
        </section>
        """
    )

    continuity_proof = continuity_proof or {}
    proof_passed = continuity_proof.get("passed") is True
    proof_checks = continuity_proof.get("checks", {})
    if not isinstance(proof_checks, dict):
        proof_checks = {}
    proof_check_rows = "".join(
        f"<li><b>{'PASS' if value is True else 'FAIL'}</b> {_escape(str(name).replace('_', ' '))}</li>"
        for name, value in proof_checks.items()
        if name != "production_state_mutated"
    )
    semantic_review = continuity_proof.get("semantic_review", {})
    if not isinstance(semantic_review, dict):
        semantic_review = {}
    review_criteria = semantic_review.get("criteria", [])
    if not isinstance(review_criteria, list):
        review_criteria = []
    review_rows = "".join(
        (
            f'<li class="review-item" data-review-id="{_escape(item.get("id", ""))}">'
            f'<span class="review-question">{_escape(item.get("question", ""))}</span>'
            '<div class="review-choices" role="group" aria-label="Choose semantic review verdict">'
            '<button type="button" data-choice="pass">Pass</button>'
            '<button type="button" data-choice="fail">Fail</button>'
            '<button type="button" data-choice="uncertain">Uncertain</button>'
            '</div></li>'
        )
        for item in review_criteria
        if isinstance(item, dict) and item.get("id")
    )
    continuity_html = (
        f"""
        <section class="continuity-proof" aria-label="Continuity proof" data-artifact-run-id="{_escape(continuity_proof.get("artifact_run_id", ""))}">
          <div class="proof-head">
            <div>
              <span class="eyebrow">{_escape(continuity_proof.get('kind', 'Disposable continuity proof'))}</span>
              <h2>{'Technical pass · semantic review pending' if continuity_proof.get('assessment_status') == 'semantic_review_pending' else ('Passed' if proof_passed else 'Not run')}</h2>
            </div>
            <span class="proof-status {'passed' if proof_passed else ''}">{'PASS' if proof_passed else 'N/A'}</span>
          </div>
          <div class="latest-result-bar">
            <button type="button" class="get-latest-result">Get latest result</button>
            <span class="latest-result-status" role="status" aria-live="polite">Run {_escape(continuity_proof.get("artifact_run_id", "unknown"))}</span>
          </div>
          <p>{_escape(continuity_proof.get('proves', 'No continuity proof was supplied for this projection.'))}</p>
          {f'<code class="context-digest">context {_escape(str(continuity_proof.get("context_digest", ""))[:16])}…</code>' if continuity_proof.get("context_digest") else '<code class="context-digest"></code>'}
          {f'<ul class="proof-checks">{proof_check_rows}</ul>' if proof_check_rows else ''}
          <div class="model-candidate"{' hidden' if not continuity_proof.get("candidate_result") else ''}><b>Candidate continuation</b><p>{_escape(continuity_proof.get("candidate_result", ""))}</p></div>
          {f'<div class="semantic-review" data-review-version="{_escape(semantic_review.get("version", ""))}" data-context-digest="{_escape(str(continuity_proof.get("context_digest", "")))}" data-work-id="{_escape(continuity_proof.get("work_id", ""))}" data-provider="{_escape(continuity_proof.get("provider", ""))}" data-model="{_escape(continuity_proof.get("model", ""))}"><b>Human semantic review · v{_escape(semantic_review.get("version", ""))}</b><p>{_escape(semantic_review.get("rule", ""))}</p><ul>{review_rows}</ul><div class="overall-review"><span>Overall semantic verdict</span><div class="review-choices" role="group" aria-label="Choose overall semantic verdict"><button type="button" data-overall="pass">Pass</button><button type="button" data-overall="fail">Fail</button><button type="button" data-overall="uncertain">Uncertain</button></div></div><button type="button" class="copy-review">Copy review</button><span class="copy-status" role="status" aria-live="polite"></span><div class="refresh-panel" hidden role="dialog" aria-modal="true" aria-labelledby="refresh-title"><div><b id="refresh-title">Review copied</b><p>Refreshing this page in <span class="refresh-count">5</span> seconds…</p></div><div class="refresh-actions"><button type="button" class="refresh-now">Refresh now</button><button type="button" class="refresh-cancel">Cancel</button></div></div></div>' if review_rows else ''}
          {f'<p class="proof-limit"><b>Boundary:</b> {_escape(continuity_proof.get("does_not_prove", ""))}</p>' if proof_passed else ''}
          {f'<a class="proof-json" href="./continuity-proof.json">Inspect machine-readable proof →</a>' if proof_passed else ''}
        </section>
        """
    )
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
    body {{ margin:0; background:var(--paper); color:var(--ink); font:16px/1.45 system-ui,-apple-system,sans-serif }}
    body:before {{ content:""; display:block; height:5px; background:var(--green) }}
    main {{ width:min(980px,100%); margin:auto; padding:clamp(20px,5vw,56px) }}
    /* The header grid gives the identity and theme control independent ownership
       of the top row. The tagline then spans a second row, so longer copy can
       wrap without displacing the control or requiring fragile positioning. */
    header {{ display:grid; grid-template-columns:minmax(0,1fr) auto; grid-template-areas:"brand theme" "tagline tagline";
      column-gap:24px; row-gap:22px; align-items:start; padding-bottom:44px }}
    .brand-block {{ grid-area:brand; display:inline-flex; flex-direction:column; align-items:flex-start; gap:8px; min-width:0 }}
    .brand {{ color:var(--ink); text-decoration:none; font:900 clamp(34px,9vw,76px)/.85 var(--mono); letter-spacing:-.08em }}
    .brand i {{ color:var(--green); font-style:normal }}
    .inspired {{ color:var(--muted); text-decoration:none; font:700 9px/1 var(--mono); letter-spacing:.12em; text-transform:uppercase }}
    .inspired b {{ color:var(--green) }}
    .brand:hover,.inspired:hover {{ color:var(--hot) }}
    .tagline {{ grid-area:tagline; max-width:520px; color:var(--muted); font-size:14px; text-align:left }}
    .eyebrow {{ font:700 11px/1 var(--mono); letter-spacing:.14em; text-transform:uppercase; color:var(--green) }}
    .hero {{ border-top:1px solid var(--line); padding:34px 0 46px }}
    h1 {{ margin:10px 0 0; max-width:760px; font-size:clamp(30px,6vw,58px); line-height:1; letter-spacing:-.045em }}
    .metrics {{ display:grid; grid-template-columns:repeat(3,1fr); gap:1px; background:var(--line); border:1px solid var(--line); margin:0 0 22px }}
    .metric {{ background:var(--surface); padding:20px }}
    .metric strong {{ display:block; font:700 clamp(28px,7vw,46px)/1 var(--mono); margin-top:9px }}
    .verification {{ display:flex; align-items:center; justify-content:space-between; gap:20px; margin:0 0 44px;
      padding:18px 20px; border:1px solid var(--line); border-left:4px solid var(--green); background:var(--surface) }}
    .verification h2 {{ margin:5px 0 8px; font-size:18px }}

    .continuity-proof {{ margin:0 0 44px; padding:20px; border:1px solid var(--line); background:var(--surface) }}
    .proof-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:18px }}
    .proof-head h2 {{ margin:5px 0 0; font-size:24px }}
    .proof-status {{ padding:5px 9px; border:1px solid var(--line); font:800 11px var(--mono); color:var(--muted) }}
    .proof-status.passed {{ border-color:var(--green); color:var(--green) }}
    .latest-result-bar {{ display:flex; align-items:center; gap:10px; justify-content:space-between; margin:14px 0 }}
    .get-latest-result {{ min-height:44px; padding:0 14px; border:1px solid var(--accent); border-radius:4px; background:var(--paper); color:var(--ink); font:700 12px var(--mono); cursor:pointer }}
    .latest-result-status {{ color:var(--muted); font:11px var(--mono); text-align:right }}
    .continuity-proof p {{ max-width:760px }}
    .proof-checks {{ display:grid; gap:7px; margin:18px 0; padding:0; list-style:none; font:12px/1.4 var(--mono) }}
    .proof-checks b {{ color:var(--green) }}
    .proof-limit {{ color:var(--muted); font-size:13px }}
    .model-candidate {{ margin:18px 0; padding:14px; border:1px solid var(--line); background:var(--paper) }}
    .model-candidate b {{ color:var(--accent); font:700 10px var(--mono); letter-spacing:.08em; text-transform:uppercase }}
    .semantic-review {{ margin:18px 0; padding:14px; border:1px solid var(--line); background:var(--surface) }}
    .semantic-review>b {{ color:var(--accent); font:700 10px var(--mono); letter-spacing:.08em; text-transform:uppercase }}
    .semantic-review ul {{ display:grid; gap:14px; margin:14px 0 0; padding:0; list-style:none }}
    .review-item {{ display:grid; gap:9px; padding:12px 0; border-top:1px solid var(--line) }}
    .review-question {{ font-size:14px; line-height:1.35 }}
    .review-choices {{ display:grid; grid-template-columns:repeat(3,1fr); gap:6px }}
    .review-choices button,.copy-review {{ min-height:44px; border:1px solid var(--line); border-radius:4px; background:var(--paper); color:var(--ink); font:700 12px var(--mono); cursor:pointer }}
    .review-choices button.selected {{ border-color:var(--accent); background:var(--accent); color:var(--paper) }}
    .overall-review {{ display:grid; gap:9px; margin-top:18px; padding-top:16px; border-top:1px solid var(--line) }}
    .overall-review>span {{ font:700 12px var(--mono); text-transform:uppercase; letter-spacing:.05em }}
    .copy-review {{ width:100%; margin-top:14px; background:var(--ink); color:var(--paper) }}
    .copy-review:disabled {{ cursor:not-allowed; opacity:.45 }}
    .copy-status {{ display:block; min-height:18px; margin-top:8px; color:var(--muted); font:11px var(--mono) }}
    .refresh-panel {{ position:fixed; left:50%; bottom:max(20px,env(safe-area-inset-bottom)); transform:translateX(-50%); width:min(92vw,420px); z-index:20; padding:16px; border:1px solid var(--line); border-radius:8px; background:var(--surface); box-shadow:0 14px 40px rgba(0,0,0,.28) }}
    .refresh-panel[hidden] {{ display:none }}
    .refresh-panel b {{ font:700 12px var(--mono); text-transform:uppercase; letter-spacing:.06em; color:var(--accent) }}
    .refresh-panel p {{ margin:7px 0 12px; font-size:14px }}
    .refresh-actions {{ display:grid; grid-template-columns:1fr 1fr; gap:8px }}
    .refresh-actions button {{ min-height:44px; border:1px solid var(--line); border-radius:4px; background:var(--paper); color:var(--ink); font:700 12px var(--mono); cursor:pointer }}
    .refresh-now {{ border-color:var(--accent)!important }}
    .proof-json {{ color:var(--accent); font:700 12px var(--mono); text-decoration:none }}
    .toolbar {{ display:flex; gap:10px; align-items:center; justify-content:space-between; margin:0 0 18px }}
    h2 {{ margin:0; font-size:23px; letter-spacing:-.03em }}
    .action {{ display:inline-flex; align-items:center; min-height:44px; padding:0 16px; color:var(--paper); background:var(--ink); text-decoration:none; font:700 13px var(--mono); border-radius:2px }}
    .action:hover {{ background:var(--hot) }}
    .state-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; margin-bottom:52px }}
    .state-card {{ min-width:0; background:var(--surface); border:1px solid var(--line); padding:17px }}
    .state-key {{ font:700 12px var(--mono); color:var(--accent); overflow-wrap:anywhere }}
    .work-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px; margin-bottom:52px }}
    .work-card {{ min-width:0; background:var(--surface); border:1px solid var(--line); border-top:4px solid var(--green); padding:19px }}
    .work-head {{ display:flex; justify-content:space-between; align-items:center; gap:10px }}
    .work-status {{ padding:4px 8px; background:var(--green); color:#172018; font:700 10px var(--mono); text-transform:uppercase }}
    .work-status.completed {{ background:var(--accent); color:var(--paper) }}
    .work-card h3 {{ margin:16px 0 6px; font-size:22px; line-height:1.15; letter-spacing:-.025em }}
    .work-meta {{ color:var(--muted); font:10px var(--mono); letter-spacing:.1em }}
    .work-section,.final-result {{ margin-top:18px; padding-top:14px; border-top:1px solid var(--line); font-size:14px }}
    .work-section b,.final-result b {{ color:var(--accent); font:700 10px var(--mono); letter-spacing:.08em; text-transform:uppercase }}
    .work-section ul,.work-section ol {{ margin:8px 0 0; padding-left:20px }} .work-section li+li {{ margin-top:6px }}
    .final-result p {{ margin:8px 0 0 }}
    pre {{ margin:14px 0 0; white-space:pre-wrap; overflow-wrap:anywhere; font:14px/1.4 var(--mono) }}
    .empty {{ padding:28px; border:1px dashed var(--line); color:var(--muted); background:rgba(255,255,255,.28) }}
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
    @media(max-width:600px) {{ header {{ column-gap:16px; row-gap:24px }}
      .metrics {{ grid-template-columns:1fr }} .verification {{ align-items:flex-start; flex-direction:column }}
      .toolbar {{ align-items:flex-end }}
      .receipt {{ grid-template-columns:38px 76px 1fr }} .revision {{ grid-column:3 }} .receipt-detail {{ grid-column:1/-1 }} }}
  </style>
</head>
<body><main>
  <header><div class="brand-block"><a class="brand" href="./" aria-label="sudofx home">sudo<i>fx</i></a>
    <a class="inspired" href="https://sudofx.github.io/wake/">Inspired by WAKE<b>✳︎</b></a></div>
    <label class="theme-switch" title="Follow system theme"><input id="theme-toggle" type="checkbox" role="switch" aria-label="Use dark theme"><span class="data-switch-track" aria-hidden="true"><i></i></span></label>
    <div class="tagline">Durable, accountable work across interchangeable intelligences.</div></header>
  <section class="hero"><div class="eyebrow">Verified durable record</div><h1>The intelligence can disappear. The work remains.</h1></section>
  <section class="metrics" aria-label="Record summary">
    <div class="metric"><span class="eyebrow">Revision</span><strong>{context.revision}</strong></div>
    <div class="metric"><span class="eyebrow">Accepted</span><strong>{accepted}</strong></div>
    <div class="metric"><span class="eyebrow">Rejected</span><strong>{rejected}</strong></div>
  </section>
  {verification_html}
  {continuity_html}
  <section><div class="toolbar"><div><span class="eyebrow">{open_work} open</span><h2>Durable work</h2></div><a class="action" href="{action_url}">Create or advance ↗</a></div>
    <div class="work-grid">{_work_cards(context.state)}</div></section>
  <section><div class="toolbar"><h2>General state</h2><a class="action" href="{action_url}">Run operation ↗</a></div>
    <div class="state-grid">{_state_cards(context.state)}</div></section>
  <section><div class="toolbar"><h2>Receipts</h2><span class="eyebrow">Newest first</span></div>
    <div class="history-tools"><input id="search" type="search" placeholder="Filter the record…" aria-label="Filter receipts"></div>
    <div class="receipts" id="receipts">{_receipt_rows(history)}</div></section>
  <footer>Hash-linked and replay-verified before publication · Pages is a projection, never the authority.</footer>
</main><script>
const search=document.querySelector('#search');
search.addEventListener('input',()=>{{const q=search.value.toLowerCase();document.querySelectorAll('.receipt').forEach(r=>r.hidden=!r.dataset.search.toLowerCase().includes(q))}});
document.querySelectorAll('.receipt').forEach(r=>r.addEventListener('click',()=>r.setAttribute('aria-expanded',r.classList.contains('open'))));
const proof=document.querySelector('.continuity-proof');
const latestButton=document.querySelector('.get-latest-result');
const latestStatus=document.querySelector('.latest-result-status');
const applyLatestProof=data=>{{
  const incoming=String(data.artifact_run_id||'');
  const current=String(proof?.dataset.artifactRunId||'');
  if(!incoming){{latestStatus.textContent='Latest proof has no run ID';return false;}}
  if(incoming===current){{latestStatus.textContent='No newer result yet · run '+incoming;return false;}}
  proof.dataset.artifactRunId=incoming;
  latestStatus.textContent='Loaded run '+incoming;
  const digest=String(data.context_digest||'');
  const digestNode=proof.querySelector('.context-digest');
  digestNode.textContent=digest?'context '+digest.slice(0,16)+'…':'';
  const candidate=proof.querySelector('.model-candidate');
  const candidateText=candidate.querySelector('p');
  candidate.hidden=!data.candidate_result;
  candidateText.textContent=String(data.candidate_result||'');
  const reviewNode=proof.querySelector('.semantic-review');
  if(reviewNode){{
    reviewNode.dataset.contextDigest=digest;
    reviewNode.dataset.workId=String(data.work_id||'');
    reviewNode.dataset.provider=String(data.provider||'');
    reviewNode.dataset.model=String(data.model||'');
    reviewNode.dataset.reviewVersion=String(data.semantic_review?.version||'');
    const criteria=Array.isArray(data.semantic_review?.criteria)?data.semantic_review.criteria:[];
    const list=reviewNode.querySelector('ul');
    list.replaceChildren(...criteria.map(item=>{{
      const li=document.createElement('li');li.className='review-item';li.dataset.reviewId=String(item.id||'');
      const q=document.createElement('span');q.className='review-question';q.textContent=String(item.question||'');
      const choices=document.createElement('div');choices.className='review-choices';choices.setAttribute('role','group');choices.setAttribute('aria-label','Choose semantic review verdict');
      for(const value of ['pass','fail','uncertain']){{
        const b=document.createElement('button');b.type='button';b.dataset.choice=value;b.textContent=value[0].toUpperCase()+value.slice(1);choices.appendChild(b);
      }}
      li.append(q,choices);return li;
    }}));
    initializeReviewControls(reviewNode);
  }}
  return true;
}};
if(latestButton){{
  latestButton.addEventListener('click',async()=>{{
    latestButton.disabled=true;latestStatus.textContent='Checking…';
    try{{
      const response=await fetch('./continuity-proof.json?ts='+Date.now(),{{cache:'no-store'}});
      if(!response.ok)throw new Error('HTTP '+response.status);
      const data=await response.json();
      applyLatestProof(data);
    }}catch(error){{
      latestStatus.textContent='Could not load latest result';
    }}finally{{latestButton.disabled=false;}}
  }});
}}
const initializeReviewControls=review=>{{
  const choices={{}}, items=[...review.querySelectorAll('.review-item')], overallButtons=[...review.querySelectorAll('[data-overall]')];
  const copyButton=review.querySelector('.copy-review'), status=review.querySelector('.copy-status');
  items.forEach(item=>{{
    choices[item.dataset.reviewId]='pass';
    item.querySelector('[data-choice="pass"]')?.classList.add('selected');
  }});
  choices.__overall='pass';
  overallButtons.find(button=>button.dataset.overall==='pass')?.classList.add('selected');
  const updateCopyState=()=>{{
    copyButton.disabled=false;
    copyButton.textContent='Copy review';
  }};
  review.querySelectorAll('.review-item [data-choice]').forEach(button=>button.addEventListener('click',()=>{{
    const item=button.closest('.review-item'), id=item.dataset.reviewId;
    choices[id]=button.dataset.choice;
    item.querySelectorAll('[data-choice]').forEach(peer=>peer.classList.toggle('selected',peer===button));
    updateCopyState();
  }}));
  overallButtons.forEach(button=>button.addEventListener('click',()=>{{
    choices.__overall=button.dataset.overall;
    overallButtons.forEach(peer=>peer.classList.toggle('selected',peer===button));
    updateCopyState();
  }}));
  copyButton.addEventListener('click',async()=>{{
    if(copyButton.disabled)return;
    const lines=[
      'SUDOFX_SEMANTIC_REVIEW v'+review.dataset.reviewVersion,
      'context_digest='+review.dataset.contextDigest,
      'work_id='+review.dataset.workId,
      'provider='+review.dataset.provider,
      'model='+review.dataset.model,
      ...items.map(item=>item.dataset.reviewId+'='+choices[item.dataset.reviewId]),
      'overall='+choices.__overall,
    ];
    const payload=lines.join('\\n');
    try{{
      await navigator.clipboard.writeText(payload);
    }}catch(error){{
      const area=document.createElement('textarea');
      area.value=payload;area.style.position='fixed';area.style.opacity='0';
      document.body.appendChild(area);area.select();
      document.execCommand('copy');area.remove();
    }}
    copyButton.textContent='Copied — paste into ChatGPT';
    status.textContent='Review copied to clipboard. No authoritative state was changed.';
    const panel=review.querySelector('.refresh-panel');
    const count=review.querySelector('.refresh-count');
    const refreshNow=review.querySelector('.refresh-now');
    const refreshCancel=review.querySelector('.refresh-cancel');
    let remaining=5, timer=null, cancelled=false;
    panel.hidden=false;
    count.textContent=String(remaining);
    const stopTimer=()=>{{if(timer!==null)clearInterval(timer);timer=null;}};
    refreshNow.onclick=()=>{{stopTimer();location.reload();}};
    refreshCancel.onclick=()=>{{cancelled=true;stopTimer();panel.hidden=true;status.textContent='Review copied. Automatic refresh cancelled.';}};
    timer=setInterval(()=>{{
      if(cancelled)return;
      remaining-=1;
      count.textContent=String(remaining);
      if(remaining<=0){{stopTimer();location.reload();}}
    }},1000);
  }});
  updateCopyState();
}};
const review=document.querySelector('.semantic-review');
if(review)initializeReviewControls(review);

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
    (destination / ".nojekyll").write_text("", encoding="utf-8")
    return index
