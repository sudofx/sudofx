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
  let codespacesUrl='';
  let localMode=false;
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

  const useLocalTransport=async()=>{
    const response=await fetch('/api/conversation/status',{cache:'no-store'});
    if(!response.ok)throw new Error('Private local Conversation transport is unavailable.');
    localMode=true;
    gateway='';
    auth.hidden=true;
    setState('Private local transport connected · provider remains stateless','ready');
    help.textContent='Visible transcript text exists only in this page and the active request.';
    setEnabled(true);
  };

  const checkSession=async()=>{
    const configResponse=await fetch('conversation-config.json?v='+Date.now(),{cache:'no-store'});
    if(!configResponse.ok)throw new Error('Conversation gateway configuration is unavailable.');
    const config=await configResponse.json();
    gateway=String(config.gateway_url||'').replace(/\/$/,'');
    codespacesUrl=String(config.codespaces_url||'');
    if(!gateway){
      try{
        await useLocalTransport();
        return;
      }catch{}
      if(codespacesUrl){
        setState('Private GitHub launch available','ready');
        auth.hidden=false;
        login.href=codespacesUrl;
        login.textContent='Launch private Conversation →';
        login.target='_blank';
        login.rel='noopener noreferrer';
        help.textContent='GitHub Codespaces will authenticate the private forwarded port. The public Pages site receives no token.';
      }else{
        setState('Private gateway not connected','offline');
        help.textContent='The chat UI is ready, but no authenticated private runtime is configured on this public deployment.';
      }
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

  const sendLocal=async message=>{
    const response=await fetch('/api/conversation',{
      method:'POST',
      credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      cache:'no-store',
      body:JSON.stringify({message})
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.error||'Conversation request failed.');
    if(!data||typeof data.content!=='string')throw new Error('Conversation transport returned an invalid reply.');
    return data.content;
  };

  const sendRemote=async message=>{
    const response=await fetch(gateway+'/api/conversation',{
      method:'POST',
      credentials:'include',
      headers:{'Content-Type':'application/json'},
      cache:'no-store',
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
    return poll(data.request_id);
  };

  input.addEventListener('keydown',event=>{
    if(event.key!=='Enter'||event.shiftKey||event.isComposing)return;
    event.preventDefault();
    if(!busy&&!input.disabled)form.requestSubmit();
  });

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
    help.textContent=localMode
      ?'Reconstructing bounded context and invoking a fresh provider.'
      :'Encrypting transport, reconstructing bounded context, and invoking a fresh provider.';
    try{
      const reply=localMode?await sendLocal(message):await sendRemote(message);
      bubble('assistant',reply);
      setState('Ready · next turn will use a fresh provider invocation','ready');
      help.textContent='Continuity is reconstructed from governed observations, not this screen.';
    }catch(error){
      bubble('assistant','Transport error: '+(error instanceof Error?error.message:'Conversation request failed.'));
      setState('Conversation transport needs attention','offline');
      help.textContent='No failed browser request is treated as durable success.';
    }finally{
      busy=false;
      setEnabled(localMode||(Boolean(gateway)&&auth.hidden));
    }
  });

  clear.addEventListener('click',()=>{
    messages.querySelectorAll('.conversation-bubble').forEach(node=>node.remove());
    if(intro)intro.hidden=false;
    const connected=localMode||Boolean(gateway);
    setState(connected?'Screen cleared · governed continuity remains':'Private gateway not connected',connected?'ready':'offline');
    help.textContent=connected?'The browser transcript is gone. sudofx observations were not reset.':'No private Conversation transport is configured.';
  });

  checkSession().catch(error=>{
    setState('Private transport unavailable','offline');
    help.textContent=error instanceof Error?error.message:'Conversation transport unavailable.';
    setEnabled(false);
  });
})();