(() => {
  const LIVE_URL='https://raw.githubusercontent.com/sudofx/sudofx/sudofx-live/live.json';
  const APPLICATION_SOURCES='application-sources.json';
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
      access:raw.application_access||{},
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
  const themeToggle=q('[data-theme-toggle]');
  const systemDark=()=>matchMedia('(prefers-color-scheme:dark)').matches;
  const currentTheme=()=>document.documentElement.dataset.theme||localStorage.getItem('sudofx-theme')||(systemDark()?'dark':'light');
  const applyTheme=theme=>{document.documentElement.dataset.theme=theme;if(themeToggle)themeToggle.checked=theme==='dark'};
  applyTheme(currentTheme());
  if(themeToggle)themeToggle.addEventListener('change',()=>{const theme=themeToggle.checked?'dark':'light';localStorage.setItem('sudofx-theme',theme);applyTheme(theme)});
  const setRuntimeLight=(state,label)=>{const el=q('[data-runtime-light]');if(!el)return;el.dataset.state=state;el.title=label;el.setAttribute('aria-label',label)};
  setRuntimeLight('checking','sudofx status: checking current projection');
  const loadPrimaryProjection=async()=>{
    const local=await fetch(LOCAL_LIVE_URL+'?v='+Date.now(),{cache:'no-store'});
    if(local.status!==404){
      if(!local.ok)throw new Error('local live projection unavailable');
      return {raw:await local.json(),federate:false};
    }
    const remote=await fetch(PUBLIC_LIVE_URL+'?v='+Date.now(),{cache:'no-store'});
    if(!remote.ok)throw new Error('live projection unavailable');
    return {raw:await remote.json(),federate:true};
  };

  const loadFederatedApplications=()=>fetch(APPLICATION_SOURCES+'?v='+Date.now(),{cache:'no-store'})
    .then(r=>r.ok?r.json():{sources:[]})
    .then(config=>Promise.allSettled((Array.isArray(config.sources)?config.sources:[]).map(source=>
      fetch(source.projection_url+'?v='+Date.now(),{cache:'no-store'}).then(r=>{
        if(!r.ok)throw new Error('application projection unavailable');return r.json();
      }).then(raw=>{
        const observed=raw.application_observability;
        if(!observed||!Array.isArray(observed.applications))return [];
        return observed.applications.map(app=>({...app,projection_source:source.id||''}));
      })
    )))
    .then(results=>results.flatMap(result=>result.status==='fulfilled'?result.value:[]))
    .catch(()=>[]);

  let refreshInFlight=false;
  const refreshLive=()=>{
    if(refreshInFlight)return Promise.resolve();
    refreshInFlight=true;
    return loadPrimaryProjection()
    .then(async source=>{
      const raw=source.raw;
      const local=raw.application_observability?.applications||[];
      const external=source.federate?await loadFederatedApplications():[];
      raw.application_observability={...(raw.application_observability||{}),applications:[...local,...external]};
      return raw;
    })
    .then(raw=>{
      const d=normalize(raw);
      const quickCheck=String(d.health.quick_check||'').trim().toLowerCase();
      if(quickCheck==='ok')setRuntimeLight('running','sudofx status: authoritative database health check is OK');
      else if(quickCheck)setRuntimeLight('stopped','sudofx status: authoritative database health check is '+quickCheck);
      else setRuntimeLight('stale','sudofx status: live projection loaded, but database health is not reported');
      const accessBox=q('[data-application-access]');
      if(accessBox){
        const access=d.access||{};
        const dot=accessBox.querySelector('[data-access-dot]');
        const copy=accessBox.querySelector('[data-access-copy]');
        if(access.enabled===true){
          if(dot){dot.style.background='var(--accent)';dot.style.boxShadow='0 0 18px var(--accent)'}
          if(copy)copy.textContent='External application access is ENABLED · generation '+String(access.generation??'—')+'.';
        }else if(access.enabled===false){
          if(dot){dot.style.background='var(--danger)';dot.style.boxShadow='0 0 18px var(--danger)'}
          if(copy)copy.textContent='External application access is STOPPED · generation '+String(access.generation??'—')+'. sudofx remains online for operator access.';
        }else if(copy){
          copy.textContent='Application access state is not present in the current live projection.';
        }
      }

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
        d.applications.length
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

      const traffic=q('[data-traffic-window]');
      if(traffic){
        const openTraffic=new Set([...traffic.querySelectorAll('details[open][data-invocation-id]')].map(el=>el.dataset.invocationId).filter(Boolean));
        traffic.replaceChildren();
        const rows=d.applications.flatMap(app=>{
          const recent=Array.isArray(app.invocations?.recent)?app.invocations.recent:[];
          return recent.map(inv=>({app,inv}));
        }).sort((a,b)=>String(b.inv.updated_at||b.inv.started_at||'').localeCompare(String(a.inv.updated_at||a.inv.started_at||''))).slice(0,8);
        if(!rows.length){
          const empty=document.createElement('article');empty.className='panel';
          empty.innerHTML='<div class="tag">Traffic</div><h3>No application invocation evidence is visible yet.</h3><p>When an application completes a governed sudofx invocation, its safe lifecycle trace will appear here.</p>';
          traffic.append(empty);
        } else rows.forEach(({app,inv})=>{
          const card=document.createElement('details');card.className='panel traffic-item';
          const invocationId=String(inv.invocation_id||'');card.dataset.invocationId=invocationId;if(invocationId&&openTraffic.has(invocationId))card.open=true;
          const stages=Array.isArray(inv.stages)?inv.stages:[];
          const ctx=inv.context||{};
          const summary=document.createElement('summary');summary.className='traffic-summary';
          const summaryMain=document.createElement('span');summaryMain.className='traffic-summary-main';
          const appName=document.createElement('strong');appName.textContent=String(app.id||'application');
          const outcome=document.createElement('span');outcome.className='tag';outcome.textContent=pretty(inv.outcome||inv.latest_stage||'observed');
          summaryMain.append(appName,outcome);
          const summaryTime=document.createElement('time');summaryTime.className='muted';
          summaryTime.textContent=(inv.updated_at||inv.started_at)?new Date(String(inv.updated_at||inv.started_at).replace(' ','T')+'Z').toLocaleString():'Time unavailable';
          summary.append(summaryMain,summaryTime);
          const body=document.createElement('div');body.className='traffic-detail';
          const title=document.createElement('h3');title.textContent=String(app.id||'Application')+' → sudofx → provider → sudofx → '+String(app.id||'application');
          const flow=document.createElement('p');flow.textContent=stages.length?stages.map(pretty).join(' → '):pretty(inv.latest_stage||'Lifecycle recorded');
          const meta=document.createElement('p');meta.className='muted';
          const cats=Array.isArray(ctx.included_categories)?ctx.included_categories.length:0;
          meta.textContent='Invocation '+String(inv.invocation_id||'unknown').slice(0,8)+'… · bounded context '+fmtBytes(ctx.payload_bytes)+' · '+cats+' context categories · contents hidden';
          body.append(title,flow,meta);card.append(summary,body);traffic.append(card);
        });
      }

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
      setRuntimeLight('stopped','sudofx status: live projection unavailable');
      const summary=q('[data-live-summary] p');if(summary)summary.textContent='Live projection is temporarily unavailable. Static product information remains usable.';
      const fresh=q('[data-metrics-freshness]');if(fresh)fresh.textContent='Live metrics are temporarily unavailable. No authority is stored in this page.';
      setText('[data-experiment-note]','Live experiment telemetry is temporarily unavailable.');
    })
    .finally(()=>{refreshInFlight=false});
  };

  refreshLive();
  const LIVE_REFRESH_MS=5000;
  setInterval(refreshLive,LIVE_REFRESH_MS);
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')refreshLive()});
  window.addEventListener('focus',refreshLive);
})();