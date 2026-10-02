(() => {
  const LIVE_URL='https://raw.githubusercontent.com/sudofx/sudofx/sudofx-live/live.json';
  const q=s=>document.querySelector(s);
  const fmtBytes=n=>{n=Number(n);if(!Number.isFinite(n)||n<0)return '—';if(n===0)return '0 B';const u=['B','KB','MB','GB'];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return (n>=100||i===0?n.toFixed(0):n.toFixed(1))+' '+u[i]};
  const fmtMs=n=>{n=Number(n);return Number.isFinite(n)?(n<1?n.toFixed(2):n.toFixed(1))+' ms':'—'};
  const pct=n=>{n=Number(n);return Number.isFinite(n)?(n*100).toFixed(1)+'%':'—'};
  const pretty=v=>String(v??'—').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
  const shortSha=v=>{v=String(v||'');return v?v.slice(0,10):'—'};
  const setText=(selector,value)=>{const el=q(selector);if(el)el.textContent=value};
  const setCards=(root,values)=>{const el=q(root);if(!el)return;[...el.querySelectorAll('.metric-card')].forEach((card,i)=>{if(values[i]!==undefined){const strong=card.querySelector('strong');if(strong)strong.textContent=values[i]}})};
  const normalize=raw=>{
    const health=raw.health||raw.metrics?.health||raw.runtime_health||{};
    const continuity=raw.continuity||raw.continuity_proof||raw;
    const sem=continuity.semantic_review||raw.semantic_review||{};
    const cm=continuity.metrics||continuity.compression||raw.compression||{};
    return {
      raw,
      generated:raw.generated||raw.generated_at||raw.projection_generated||'',
      revision:raw.record_revision??raw.revision??health.revision,
      health,
      summary:raw.summary||{},
      continuity,
      cm,
      sem,
      experiment:continuity.overnight_trial||raw.overnight_trial||{},
      applications:(raw.application_observability&&Array.isArray(raw.application_observability.applications))?raw.application_observability.applications:(raw.applications||[]),
      verification:raw.verification||{},
      projectionKind:raw.projection_kind||'',
      projectionSchema:raw.projection_schema
    };
  };

  fetch(LIVE_URL+'?v='+Date.now(),{cache:'no-store'})
    .then(r=>{if(!r.ok)throw new Error('live projection unavailable');return r.json()})
    .then(raw=>{
      const d=normalize(raw);
      const summary=q('[data-live-summary] p');
      if(summary){
        const events=d.health.event_count!==undefined?' · '+d.health.event_count+' governed events':'';
        const replay=d.health.replay_ms!==undefined?' · replay '+fmtMs(d.health.replay_ms):'';
        summary.textContent=(d.revision!==undefined?'Record revision '+d.revision:'Live projection loaded')+events+replay+'.';
      }

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
      setText('[data-db-size]',fmtBytes(d.health.database_bytes));
      setText('[data-quick-check]',String(d.health.quick_check||'—').toUpperCase());
      setText('[data-schema-version]',d.health.schema_version??'—');
      setText('[data-free-bytes]',fmtBytes(d.health.free_bytes));

      setCards('[data-operational-metrics]',[
        d.summary.work_items??'—',
        d.summary.open_work_items??'—',
        d.summary.accepted_results??'—',
        d.summary.conversation_turns??'—'
      ]);

      const appView=q('[data-application-observability]');
      if(appView){
        appView.replaceChildren();
        if(!d.applications.length){
          const empty=document.createElement('article');empty.className='panel';
          empty.innerHTML='<div class="tag">Applications</div><h3>No governed application evidence yet.</h3><p>Applications appear automatically when generic sudofx evidence identifies them.</p>';
          appView.append(empty);
        } else d.applications.forEach(app=>{
          const actions=app.actions||{},inv=app.invocations||{};
          const card=document.createElement('article');card.className='panel';
          const tag=document.createElement('div');tag.className='tag';tag.textContent='Application · '+String(app.id||'unknown');
          const title=document.createElement('h3');title.textContent=String(app.id||'unknown')+' uses sudofx';
          const detail=document.createElement('p');
          detail.textContent=(actions.accepted??0)+' accepted / '+(actions.rejected??0)+' rejected governed actions · '+(inv.total??0)+' invocations · '+(inv.completed??0)+' completed · '+(inv.failed??0)+' failed.';
          const context=document.createElement('p');context.className='muted';
          const recent=Array.isArray(inv.recent)?inv.recent:[],last=recent.at(-1),ctx=last&&last.context||{};
          context.textContent=last?'Latest: '+pretty(last.latest_stage||'unknown')+' · context '+fmtBytes(ctx.payload_bytes)+' · '+(Array.isArray(ctx.included_categories)?ctx.included_categories.join(', '):''):'No scoped invocation evidence recorded.';
          card.append(tag,title,detail,context);appView.append(card);
        });
      }

      const context=d.cm.context_bytes??d.cm.compressed_context_bytes??d.continuity.context_bytes;
      const full=d.cm.full_context_bytes??d.continuity.full_context_bytes;
      const ratio=d.cm.compression_ratio??d.cm.reduction_ratio??d.continuity.compression_ratio;
      setCards('[data-continuity-metrics]',[
        context!==undefined&&context!==null?fmtBytes(context):'NOT RECORDED',
        full!==undefined&&full!==null?fmtBytes(full):'NOT RECORDED',
        ratio!==undefined&&ratio!==null?pct(ratio):'NOT RECORDED',
        (d.sem.status||d.continuity.semantic_review_status||'—').toString().toUpperCase()
      ]);

      const bar=q('[data-compression-bar]');
      const label=q('[data-compression-label]');
      const note=q('[data-compression-note]');
      const contextN=Number(context),fullN=Number(full);
      if(bar&&label&&note&&Number.isFinite(contextN)&&Number.isFinite(fullN)&&fullN>0){
        const retained=Math.max(0,Math.min(100,(contextN/fullN)*100));
        bar.style.width=retained+'%';
        label.textContent=retained.toFixed(1)+'% retained';
        note.textContent=fmtBytes(contextN)+' delivered from '+fmtBytes(fullN)+' available · '+pct(1-(contextN/fullN))+' removed before provider delivery.';
      } else if(bar&&label&&note){
        bar.style.width='0%';
        label.textContent='Not recorded for this durable observation';
        note.textContent='This observation predates durable aggregate compression evidence. New overnight cycles preserve only safe byte/count aggregates in SQLite.';
      }

      const criteria=q('[data-semantic-criteria]');
      if(criteria){
        criteria.replaceChildren();
        const items=Array.isArray(d.sem.criteria)?d.sem.criteria:[];
        items.forEach(item=>{
          const card=document.createElement('div');
          card.className='criterion';
          const name=document.createElement('span');
          name.textContent=pretty(item.id||'criterion');
          const status=document.createElement('strong');
          const s=String(item.status||'pending').toLowerCase();
          status.className='quality-'+s;
          status.textContent=s.toUpperCase();
          card.append(name,status);
          criteria.append(card);
        });
      }

      const coord=d.experiment.coordinate||{};
      setCards('[data-experiment-metrics]',[
        d.experiment.cycle??'—',
        pretty(coord.semantic_lens||d.experiment.phase||'—'),
        pretty(coord.exposure||'—'),
        pretty(coord.pressure||'—')
      ]);
      const expNote=q('[data-experiment-note]');
      if(expNote){
        expNote.textContent='Google Gemini · '+(d.continuity.model||'model unknown')+' · 343-condition continuity matrix · current durable observation remains evidence, not project authority.';
      }

      setText('[data-projection-kind]',pretty(d.projectionKind||'—'));
      setText('[data-projection-schema]',d.projectionSchema??'—');
      setText('[data-source-revision]',d.revision??'—');
      setText('[data-source-integrity]',String(d.health.quick_check||'—').toUpperCase());
      setText('[data-generated-at]',d.generated?new Date(d.generated).toLocaleString():'—');
      setText('[data-source-commit]',shortSha(d.verification.commit||d.continuity.projection_commit));
      setText('[data-source-run]',d.verification.run_id||d.continuity.projection_run_id||'—');

      const fresh=q('[data-metrics-freshness]');
      if(fresh) fresh.textContent='Disposable live projection'+(d.generated?' generated '+new Date(d.generated).toLocaleString():'')+(d.revision!==undefined?' · source revision '+d.revision:'')+'. Metrics are read-only projections; SQLite remains authoritative.';
    })
    .catch(()=>{
      const summary=q('[data-live-summary] p');if(summary)summary.textContent='Live projection is temporarily unavailable. Static product information remains usable.';
      const fresh=q('[data-metrics-freshness]');if(fresh)fresh.textContent='Live metrics are temporarily unavailable. No authority is stored in this page.';
      setText('[data-experiment-note]','Live experiment telemetry is temporarily unavailable.');
    });
})();