(() => {
  const LIVE_URL='https://raw.githubusercontent.com/sudofx/sudofx/sudofx-live/live.json';
  const fmtBytes=n=>{n=Number(n||0);if(!Number.isFinite(n)||n<=0)return '—';const u=['B','KB','MB','GB'];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return (n>=100||i===0?n.toFixed(0):n.toFixed(1))+' '+u[i]};
  const fmtMs=n=>{n=Number(n);return Number.isFinite(n)?(n<1?n.toFixed(2):n.toFixed(1))+' ms':'—'};
  const pct=n=>{n=Number(n);return Number.isFinite(n)?(n*100).toFixed(1)+'%':'—'};
  const q=(s)=>document.querySelector(s);
  const setCards=(root,values)=>{const el=q(root);if(!el)return;[...el.querySelectorAll('.metric-card')].forEach((card,i)=>{if(values[i]!==undefined){const strong=card.querySelector('strong');if(strong)strong.textContent=values[i]}})};
  const normalize=(raw)=>{
    const health=raw.health||raw.metrics?.health||raw.runtime_health||{};
    const continuity=raw.continuity||raw.continuity_proof||raw;
    const sem=continuity.semantic_review||{};
    const cm=continuity.metrics||{};
    return {
      generated:raw.generated||raw.generated_at||raw.projection_generated||'',
      revision:raw.record_revision??raw.revision??health.revision,
      health,
      continuity,
      cm,
      sem,
      applications:raw.applications||[]
    };
  };
  fetch(LIVE_URL+'?v='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('live projection unavailable');return r.json()}).then(raw=>{
    const d=normalize(raw);
    const summary=q('[data-live-summary] p');
    if(summary) summary.textContent=d.revision!==undefined&&d.revision!==null ? 'Authoritative record revision '+d.revision+' · browser data loaded from sudofx-live.' : 'Live public projection loaded from sudofx-live.';
    setCards('[data-technical-metrics]',[
      d.revision??'—',
      fmtBytes(d.health.database_bytes),
      fmtMs(d.health.replay_ms),
      d.applications.length||2
    ]);
    setCards('[data-runtime-metrics]',[
      d.revision??'—',
      d.health.event_count??'—',
      d.health.invocation_event_count??'—',
      fmtMs(d.health.replay_ms)
    ]);
    const context=d.cm.context_bytes??d.continuity.context_bytes;
    const full=d.cm.full_context_bytes??d.continuity.full_context_bytes;
    const ratio=d.cm.compression_ratio??d.continuity.compression_ratio;
    setCards('[data-continuity-metrics]',[
      context!==undefined?fmtBytes(context):'—',
      full!==undefined?fmtBytes(full):'—',
      ratio!==undefined?pct(ratio):'—',
      (d.sem.status||d.continuity.semantic_review_status||'—').toString().toUpperCase()
    ]);
    const fresh=q('[data-metrics-freshness]');
    if(fresh) fresh.textContent='Disposable live projection'+(d.generated?' generated '+new Date(d.generated).toLocaleString():'')+(d.revision!==undefined?' · source revision '+d.revision:'')+'. Metrics are read-only projections; SQLite remains authoritative.';
  }).catch(()=>{
    const summary=q('[data-live-summary] p');if(summary)summary.textContent='Live projection is temporarily unavailable. Static product information remains usable.';
    const fresh=q('[data-metrics-freshness]');if(fresh)fresh.textContent='Live metrics are temporarily unavailable. No authority is stored in this page.';
  });
})();
