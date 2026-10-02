(() => {
  const root=document.querySelector('[data-conversation-app]');
  if(!root)return;

  const state=root.querySelector('[data-conversation-state]');
  const dot=root.querySelector('[data-conversation-dot]');
  const messages=root.querySelector('[data-conversation-messages]');
  const intro=root.querySelector('[data-conversation-intro]');
  const form=root.querySelector('[data-conversation-form]');
  const input=root.querySelector('[data-conversation-input]');
  const send=root.querySelector('[data-conversation-send]');
  const help=root.querySelector('[data-conversation-help]');
  const clear=root.querySelector('[data-conversation-clear]');
  const auth=root.querySelector('[data-conversation-auth]');
  const login=root.querySelector('[data-conversation-login]');
  let gateway='';
  let busy=false;

  const setState=(label,kind='idle')=>{
    state.textContent=label;
    dot.dataset.state=kind;
  };
  const setEnabled=enabled=>{
    input.disabled=!enabled;
    send.disabled=!enabled;
    if(enabled)input.focus();
  };
  const bubble=(role,text)=>{
    if(intro)intro.hidden=true;
    const article=document.createElement('article');
    article.className='conversation-bubble '+(role==='human'?'human':'assistant');
    const meta=document.createElement('span');
    meta.textContent=role==='human'?'You':'Assistant';
    const body=document.createElement('p');
    body.textContent=text;
    article.append(meta,body);
    messages.append(article);
    messages.scrollTop=messages.scrollHeight;
  };
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));

  const poll=async requestId=>{
    for(let attempt=0;attempt<80;attempt++){
      const response=await fetch(gateway+'/api/conversation/result?request_id='+encodeURIComponent(requestId),{
        credentials:'include',
        cache:'no-store'
      });
      if(response.status===202||response.status===404){
        await sleep(1500);
        continue;
      }
      if(!response.ok)throw new Error((await response.text())||'Conversation reply failed.');
      const data=await response.json();
      if(!data||typeof data.content!=='string')throw new Error('Conversation gateway returned an invalid reply.');
      return data.content;
    }
    throw new Error('Conversation reply did not arrive before the polling window closed.');
  };

  const checkSession=async()=>{
    const configResponse=await fetch('conversation-config.json?v='+Date.now(),{cache:'no-store'});
    if(!configResponse.ok)throw new Error('Conversation gateway configuration is unavailable.');
    const config=await configResponse.json();
    gateway=String(config.gateway_url||'').replace(/\/$/,'');
    if(!gateway){
      setState('Private gateway not connected','offline');
      help.textContent='The chat UI is ready, but the authenticated gateway URL has not been configured.';
      setEnabled(false);
      return;
    }

    const response=await fetch(gateway+'/api/conversation/session',{credentials:'include',cache:'no-store'});
    if(response.status===401){
      setState('Operator sign in required','offline');
      auth.hidden=false;
      login.href=gateway+'/login?return_to='+encodeURIComponent(location.href);
      help.textContent='Sign in through GitHub OAuth to use Conversation.';
      setEnabled(false);
      return;
    }
    if(!response.ok)throw new Error('Conversation gateway is unavailable.');
    const session=await response.json();
    if(!session||session.authenticated!==true){
      setState('Operator sign in required','offline');
      auth.hidden=false;
      login.href=gateway+'/login?return_to='+encodeURIComponent(location.href);
      setEnabled(false);
      return;
    }
    auth.hidden=true;
    setState('Private gateway connected · provider remains stateless','ready');
    help.textContent='This visible transcript exists only in this page. Do not enter direct identifiers or secrets.';
    setEnabled(true);
  };

  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(busy)return;
    const message=input.value.trim();
    if(!message)return;
    busy=true;
    setEnabled(false);
    bubble('human',message);
    input.value='';
    setState('Governed turn in progress…','busy');
    help.textContent='Encrypting transport, reconstructing bounded context, and invoking a fresh provider.';
    try{
      const response=await fetch(gateway+'/api/conversation',{
        method:'POST',
        credentials:'include',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({message})
      });
      if(response.status===401){
        auth.hidden=false;
        login.href=gateway+'/login?return_to='+encodeURIComponent(location.href);
        throw new Error('Operator sign in expired.');
      }
      if(!response.ok){
        let detail='Conversation request failed.';
        try{const data=await response.json();if(data&&data.error)detail=data.error}catch{}
        throw new Error(detail);
      }
      const data=await response.json();
      if(!data||typeof data.request_id!=='string')throw new Error('Conversation gateway did not return a request ID.');
      const reply=await poll(data.request_id);
      bubble('assistant',reply);
      setState('Ready · next turn will use a fresh provider invocation','ready');
      help.textContent='Continuity is reconstructed from governed observations, not this screen.';
    }catch(error){
      bubble('assistant','Transport error: '+(error instanceof Error?error.message:'Conversation request failed.'));
      setState('Conversation transport needs attention','offline');
      help.textContent='No failed browser request is treated as durable success.';
    }finally{
      busy=false;
      setEnabled(Boolean(gateway)&&auth.hidden);
    }
  });

  clear.addEventListener('click',()=>{
    messages.querySelectorAll('.conversation-bubble').forEach(node=>node.remove());
    if(intro)intro.hidden=false;
    setState(gateway?'Screen cleared · governed continuity remains':'Private gateway not connected',gateway?'ready':'offline');
    help.textContent=gateway?'The browser transcript is gone. sudofx observations were not reset.':'The chat UI is ready, but the authenticated gateway URL has not been configured.';
  });

  checkSession().catch(error=>{
    setState('Private gateway unavailable','offline');
    help.textContent=error instanceof Error?error.message:'Conversation gateway unavailable.';
    setEnabled(false);
  });
})();