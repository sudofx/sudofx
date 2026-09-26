"""Generate the static, phone-friendly view of a verified record."""

from __future__ import annotations

import html
import json
from pathlib import Path

from .kernel import Kernel


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _state_cards(state: dict[str, object]) -> str:
    if not state:
        return '<div class="empty">No accepted state yet. Run the first operation to begin.</div>'
    return "".join(
        f"""
        <article class="state-card">
          <div class="state-key">{_escape(key)}</div>
          <pre>{_escape(json.dumps(value, indent=2, ensure_ascii=False))}</pre>
        </article>
        """
        for key, value in sorted(state.items())
    )


def _receipt_rows(history: tuple[dict[str, object], ...]) -> str:
    if not history:
        return '<div class="empty">Receipts will appear here after the first proposal.</div>'
    rows: list[str] = []
    for event in reversed(history):
        proposal = event["proposal"]
        assert isinstance(proposal, dict)
        operations = proposal.get("operations", [])
        summary = ", ".join(
            f"{operation.get('action')} {operation.get('key')}" for operation in operations
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


def render(kernel: Kernel, *, repository: str = "sudofx/sudofx") -> str:
    context = kernel.context(receipt_limit=0)
    history = kernel.record.history()
    accepted = sum(event["status"] == "accepted" for event in history)
    rejected = len(history) - accepted
    action_url = f"https://github.com/{repository}/actions/workflows/sudofx.yml"
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
    header {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-start; padding-bottom:44px }}
    .brand-block {{ display:inline-flex; flex-direction:column; align-items:flex-start; gap:8px }}
    .brand {{ color:var(--ink); text-decoration:none; font:900 clamp(34px,9vw,76px)/.85 var(--mono); letter-spacing:-.08em }}
    .brand i {{ color:var(--green); font-style:normal }}
    .inspired {{ color:var(--muted); text-decoration:none; font:700 9px/1 var(--mono); letter-spacing:.12em; text-transform:uppercase }}
    .inspired b {{ color:var(--green) }}
    .brand:hover,.inspired:hover {{ color:var(--hot) }}
    .tagline {{ max-width:360px; color:var(--muted); font-size:14px; text-align:right }}
    .eyebrow {{ font:700 11px/1 var(--mono); letter-spacing:.14em; text-transform:uppercase; color:var(--green) }}
    .hero {{ border-top:1px solid var(--line); padding:34px 0 46px }}
    h1 {{ margin:10px 0 0; max-width:760px; font-size:clamp(30px,6vw,58px); line-height:1; letter-spacing:-.045em }}
    .metrics {{ display:grid; grid-template-columns:repeat(3,1fr); gap:1px; background:var(--line); border:1px solid var(--line); margin:0 0 44px }}
    .metric {{ background:var(--surface); padding:20px }}
    .metric strong {{ display:block; font:700 clamp(28px,7vw,46px)/1 var(--mono); margin-top:9px }}
    .toolbar {{ display:flex; gap:10px; align-items:center; justify-content:space-between; margin:0 0 18px }}
    h2 {{ margin:0; font-size:23px; letter-spacing:-.03em }}
    .action {{ display:inline-flex; align-items:center; min-height:44px; padding:0 16px; color:var(--paper); background:var(--ink); text-decoration:none; font:700 13px var(--mono); border-radius:2px }}
    .action:hover {{ background:var(--hot) }}
    .state-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; margin-bottom:52px }}
    .state-card {{ min-width:0; background:var(--surface); border:1px solid var(--line); padding:17px }}
    .state-key {{ font:700 12px var(--mono); color:var(--accent); overflow-wrap:anywhere }}
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
    .theme-switch {{ display:flex; align-items:center; gap:8px; cursor:pointer; user-select:none }}
    .theme-switch input {{ position:absolute; opacity:0; pointer-events:none }}
    .theme-icon {{ width:18px; color:var(--accent); font:16px/1 var(--mono) }}
    .data-switch-track {{ width:42px; height:24px; padding:2px; border:1px solid var(--line); background:var(--surface); border-radius:20px }}
    .data-switch-track i {{ display:block; width:18px; height:18px; border-radius:50%; background:var(--muted); transition:transform .2s ease,background .2s ease }}
    .theme-switch input:checked + .theme-icon + .data-switch-track i {{ transform:translateX(17px); background:var(--accent) }}
    .theme-switch input:focus-visible + .theme-icon + .data-switch-track {{ outline:3px solid var(--hot); outline-offset:3px }}
    @media(max-width:600px) {{ header {{ display:block }} .tagline {{ text-align:left; margin-top:18px }}
      .metrics {{ grid-template-columns:1fr }} .toolbar {{ align-items:flex-end }}
      .receipt {{ grid-template-columns:38px 76px 1fr }} .revision {{ grid-column:3 }} .receipt-detail {{ grid-column:1/-1 }} }}
  </style>
</head>
<body><main>
  <header><div class="brand-block"><a class="brand" href="/" aria-label="sudofx home">sudo<i>fx</i></a>
    <a class="inspired" href="https://sudofx.github.io/wake/">Inspired by WAKE<b>✳︎</b></a></div><div><div class="tagline">Durable, accountable work across interchangeable intelligences.</div>
    <label class="theme-switch" title="Follow system theme"><input id="theme-toggle" type="checkbox" role="switch" aria-label="Use dark theme"><b class="theme-icon" aria-hidden="true">◐</b><span class="data-switch-track" aria-hidden="true"><i></i></span></label></div></header>
  <section class="hero"><div class="eyebrow">Verified durable record</div><h1>The intelligence can disappear. The work remains.</h1></section>
  <section class="metrics" aria-label="Record summary">
    <div class="metric"><span class="eyebrow">Revision</span><strong>{context.revision}</strong></div>
    <div class="metric"><span class="eyebrow">Accepted</span><strong>{accepted}</strong></div>
    <div class="metric"><span class="eyebrow">Rejected</span><strong>{rejected}</strong></div>
  </section>
  <section><div class="toolbar"><h2>Current state</h2><a class="action" href="{action_url}">Run operation ↗</a></div>
    <div class="state-grid">{_state_cards(context.state)}</div></section>
  <section><div class="toolbar"><h2>Receipts</h2><span class="eyebrow">Newest first</span></div>
    <div class="history-tools"><input id="search" type="search" placeholder="Filter the record…" aria-label="Filter receipts"></div>
    <div class="receipts" id="receipts">{_receipt_rows(history)}</div></section>
  <footer>Hash-linked and replay-verified before publication · Pages is a projection, never the authority.</footer>
</main><script>
const search=document.querySelector('#search');
search.addEventListener('input',()=>{{const q=search.value.toLowerCase();document.querySelectorAll('.receipt').forEach(r=>r.hidden=!r.dataset.search.toLowerCase().includes(q))}});
document.querySelectorAll('.receipt').forEach(r=>r.addEventListener('click',()=>r.setAttribute('aria-expanded',r.classList.contains('open'))));
const toggle=document.querySelector('#theme-toggle'),icon=document.querySelector('.theme-icon');
const saved=()=>{{try{{return localStorage.getItem('wake-theme')}}catch{{return null}}}};
const sync=()=>{{const dark=document.documentElement.dataset.theme==='dark',manual=Boolean(saved());toggle.checked=dark;toggle.setAttribute('aria-label',dark?'Use light theme':'Use dark theme');icon.textContent=manual?(dark?'◑':'☼'):'◐';toggle.closest('.theme-switch').title=manual?`Manual ${{dark?'dark':'light'}} theme`:`Following system ${{dark?'dark':'light'}} theme`}};
sync();toggle.addEventListener('change',()=>{{const dark=toggle.checked;if(dark)document.documentElement.dataset.theme='dark';else delete document.documentElement.dataset.theme;try{{localStorage.setItem('wake-theme',dark?'dark':'light')}}catch{{}}sync()}});
try{{const media=matchMedia('(prefers-color-scheme:dark)');media.addEventListener('change',event=>{{if(saved())return;if(event.matches)document.documentElement.dataset.theme='dark';else delete document.documentElement.dataset.theme;sync()}})}}catch{{}}
</script></body></html>"""


def export_site(kernel: Kernel, directory: str | Path, *, repository: str = "sudofx/sudofx") -> Path:
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    index = destination / "index.html"
    index.write_text(render(kernel, repository=repository), encoding="utf-8")
    (destination / ".nojekyll").write_text("", encoding="utf-8")
    return index
