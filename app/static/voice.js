/* Voice settings and browser tests. No provider keys are accepted in the browser. */
let voiceCleanup=null;
function mountVoice(){
  const group=document.createElement('div');group.className='voice-nav-group';
  group.innerHTML='<button class="agent-nav-link" id="voice-nav-toggle" aria-expanded="false" aria-controls="voice-nav-children">▸ Voice Receptionist</button><div id="voice-nav-children" hidden><button data-voice-page="overview">Overview</button><button data-voice-page="configuration">Configuration & test</button></div>';
  document.querySelector('.agent-nav')?.append(group);
  group.querySelector('#voice-nav-toggle').onclick=()=>{const expanded=group.querySelector('#voice-nav-children').hidden;if(expanded)showVoiceOverview();else{group.querySelector('#voice-nav-children').hidden=true;group.querySelector('#voice-nav-toggle').setAttribute('aria-expanded','false');group.querySelector('#voice-nav-toggle').textContent='▸ Voice Receptionist';}};
  group.querySelector('[data-voice-page="overview"]').onclick=showVoiceOverview;
  group.querySelector('[data-voice-page="configuration"]').onclick=showVoice;
  if(!['agents','marketplace'].includes(view))return;
  const card=document.createElement('article');card.className='card';
  const icon='<div class="icon voice-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/></svg></div>';
  card.innerHTML=view==='marketplace'?`${icon}<h2>Voice Receptionist</h2><p>A welcoming voice for business questions, callbacks and browser test calls.</p><span class="chip">Preview · Browser calls</span><div class="actions"><button>Configure agent →</button></div>`:`<div class="cardtop">${icon}<div><h3>Voice Receptionist</h3><p>Your conversational front desk</p></div><span class="badge off">Preview</span></div><p>A welcoming voice for business questions and permitted actions.</p><div class="permissions"><span class="chip">Browser calls</span><span class="chip">Confirmed actions</span></div><div class="cardfoot"><span>Telephone calls not connected</span><button>Manage agent →</button></div>`;
  card.querySelector('button').onclick=showVoiceOverview;document.querySelector('#page .agents')?.append(card);
  if(!card.isConnected)document.querySelector('#page')?.append(card);
}
function activateVoicePage(name){
  document.querySelector('.content')?.classList.remove('inbox-mode');
  const tree=document.querySelector('#voice-nav-children');if(tree)tree.hidden=false;
  const toggle=document.querySelector('#voice-nav-toggle');if(toggle){toggle.setAttribute('aria-expanded','true');toggle.textContent='▾ Voice Receptionist';}
  document.querySelectorAll('.nav button').forEach(b=>{b.classList.remove('active');b.removeAttribute('aria-current');});
  const selected=document.querySelector(`[data-voice-page="${name}"]`);if(selected){selected.classList.add('active');selected.setAttribute('aria-current','page');}
  const notice=document.querySelector('.content > .notice');if(notice)notice.hidden=true;
}
async function showVoiceOverview(){
  if(voiceCleanup)voiceCleanup();activateVoicePage('overview');
  const page=document.querySelector('#page');page.innerHTML='<section class="panel" role="status">Loading voice overview…</section>';
  document.querySelector('.main header span').textContent='My agents / Voice Receptionist / Overview';
  document.querySelector('.heading h1').textContent='Voice Receptionist';
  document.querySelector('.heading p').textContent='Your sessions, model usage and service health in one place.';
  try{
    const o=await api('voice/overview');if(!page.isConnected||document.querySelector('[aria-current="page"]')?.dataset.voicePage!=='overview')return;
    const number=n=>Number(n).toLocaleString(),metric=(label,value,detail)=>`<div class="stat"><small>${label}</small><strong>${value}</strong><footer>${detail}</footer></div>`;
    const max=Math.max(1,...o.daily.map(d=>d.sessions));
    page.innerHTML=`<section class="panel voice-overview-header"><div><span class="chip">Browser preview</span><h2>${esc(o.name)}</h2><p>Agent ID <code>${esc(o.agent_id)}</code></p><p>Model <strong>${esc(o.model||'Not configured')}</strong> · Azure region <strong>${esc(o.region||'Not configured')}</strong></p></div><div class="actions"><button id="voice-overview-refresh">Refresh</button><button class="primary" id="voice-overview-configure">Configure & test →</button></div></section>
      <div class="stats voice-stats">${metric('Concurrent sessions',number(o.counts.active),'Active reservations that have not expired')}${metric('Total sessions',number(o.counts.total),'All recorded attempts in this workspace')}${metric('Completed sessions',number(o.counts.completed),'Completed status, not a task-success score')}${metric('Avg model tokens / session',o.average_tokens===null?'No sessions':number(o.average_tokens),'Ended sessions; includes reported audio and text tokens')}</div>
      <div class="voice-overview-grid"><section class="panel"><h2>Sessions served</h2><p>Last seven UTC calendar days · ${number(o.daily.reduce((a,d)=>a+d.sessions,0))} session starts</p><div class="voice-chart" role="img" aria-label="Daily session starts over the last seven days">${o.daily.map(d=>`<div class="voice-bar-column"><span>${d.sessions}</span><div class="voice-bar-track"><div class="voice-bar" style="height:${d.sessions/max*100}%"></div></div><small>${esc(d.date.slice(5))}</small></div>`).join('')}</div><details><summary>View daily data</summary><table class="voice-data"><thead><tr><th>Date (UTC)</th><th>Sessions</th><th>Reported tokens</th></tr></thead><tbody>${o.daily.map(d=>`<tr><td>${esc(d.date)}</td><td>${number(d.sessions)}</td><td>${number(d.tokens)}</td></tr>`).join('')}</tbody></table></details></section>
      <section class="panel"><h2>Model performance</h2><div class="check">Reported tokens, ended sessions <b>${number(o.counts.tokens)}</b></div><div class="check">Failed sessions <b>${number(o.counts.failed)}</b></div><p>Usage comes from Azure response events. Missing provider usage is not estimated. These are combined model tokens, not a text-only LLM count.</p><h3>Conversation flow</h3><div class="check">Turns <b>Not instrumented</b></div><div class="check">Interruption rate <b>Not instrumented</b></div><p>A disconnected call is not counted as a conversational interruption.</p></section>
      <section class="panel"><h2>Reply latency</h2><p>Response latency over time, stage breakdowns and P95/P99 are not measured yet. No timing estimates are shown.</p><div class="voice-empty">Waiting for turn-level timing instrumentation</div></section>
      <section class="panel"><h2>Deployment health</h2><div class="check">Connection latency / agent join <b>Not measured</b></div><div class="check">Inbound telephone calls <b>Not connected</b></div><div class="check">Agent uptime / average load <b>Not measured</b></div><p>Model configuration does not prove endpoint health. This page reports workspace call metadata, not Azure infrastructure availability.</p></section></div><p class="muted">Updated ${esc(new Date(o.updated*1000).toLocaleString())}. Use Refresh for a new snapshot.</p>`;
    document.querySelector('#voice-overview-refresh').onclick=showVoiceOverview;document.querySelector('#voice-overview-configure').onclick=showVoice;
  }catch(e){page.textContent=e.message;}
}

async function showVoice(){
  activateVoicePage('configuration');
  if(voiceCleanup)voiceCleanup();
  const page=document.querySelector('#page');page.innerHTML='<section class="panel">Loading your receptionist…</section>';
  try{
    const state=await api('voice');if(!page.isConnected)return;
    const s=state.settings;
    const notice=document.querySelector('.content > .notice');if(notice)notice.hidden=true;
    document.querySelector('.main header span').textContent='Workspace / Voice Receptionist';
    document.querySelector('.heading h1').textContent='Your Voice Receptionist';
    document.querySelector('.heading p').textContent='Tell it about your business, then try a conversation.';
    page.innerHTML=`<div class="voice-layout"><section class="panel"><form id="voice-settings" class="form">
      <h2>Conversation</h2><p>Save your changes before testing. Changes apply to the next call and pause the enabled setup.</p>
      <label>Business name<input name="company" required maxlength="100" value="${esc(s.company)}"></label>
      <label>Business information<textarea name="business_info" rows="4" maxlength="4000" placeholder="Opening hours, location and answers your receptionist can give.">${esc(s.business_info)}</textarea></label>
      <label>Instructions<textarea name="instructions" rows="8" maxlength="6000">${esc(s.instructions)}</textarea></label>
      <p>Use {Company} for your business name. Your instructions cannot grant access to tools or customer records.</p>
      <label>Welcome message<textarea name="greeting" rows="2" maxlength="400">${esc(s.greeting)}</textarea></label>
      <label>When a person needs to help<textarea name="follow_up" rows="2" maxlength="500" placeholder="For example: ask the caller to email help@example.com.">${esc(s.follow_up)}</textarea></label>
      <h2>Actions</h2><label><input type="checkbox" name="allow_callback_requests" ${s.allow_callback_requests?'checked':''}> Allow callback requests</label><p>The agent prepares a request. You review and confirm it here before it enters the staff review list. Contact details and the message expire after twenty-four hours and are removed on the next voice-page visit. No email is sent.</p>${state.demo_available?`<label><input type="checkbox" name="allow_demo_bookings" ${s.allow_demo_bookings?'checked':''}> Enable synthetic booking demo</label><p>Uses a separate local booking database. Your signed-in session represents one verified demo customer. New bookings and changes require a confirmation here. No real reservations or payments.</p>`:''}<h2>Model and voice</h2><label>Model<select name="model">${state.models.map(m=>`<option value="${esc(m.id)}">${esc(m.name)}</option>`).join('')}</select></label>
      <label>Voice<select name="voice">${['alloy','ash','sage','coral','echo','shimmer'].map(v=>`<option ${s.voice===v?'selected':''}>${v}</option>`).join('')}</select></label>
      <details><summary>Advanced call settings</summary><label>Language<input name="language" maxlength="40" value="${esc(s.language)}"></label><label>Maximum test length<select name="max_seconds">${[30,60,120,180].map(n=>`<option value="${n}" ${s.max_seconds===n?'selected':''}>${n} seconds</option>`).join('')}</select></label><label><input type="checkbox" name="allow_interruptions" ${s.allow_interruptions?'checked':''}> Let callers interrupt the reply</label></details>
      <div class="actions"><button class="primary" type="submit">Save settings</button><button type="button" id="voice-enable" ${state.tested?'':'disabled'}>${state.enabled?'Disable':'Enable'} receptionist</button></div><p id="voice-save-status" role="status">${state.enabled?'This tested setup is marked ready. Telephone calls are not connected.':state.tested?'Test completed. Enable marks this setup ready; test calls also work while disabled.':'Save and complete a test before enabling.'}</p></form></section>
      <section class="panel voice-preview"><div class="eyebrow">LIVE PREVIEW</div><h2>Try a conversation</h2><p>Use your microphone to speak with the receptionist. Azure processes the audio. SoloAI does not save recordings or transcripts.</p><p id="voice-call-status" role="status">${state.available?'Ready when you are.':'Your operator needs to connect the Azure voice model.'}</p><div class="actions"><button id="voice-start" class="primary" ${state.available&&s.revision?'':'disabled'}>Start test call</button><button id="voice-end" disabled>End call</button></div><p>Up to ${s.max_seconds} seconds per call. Your workspace has a ${state.daily_seconds/60}-minute daily test allowance. The full selected duration is reserved when a call starts.</p><div class="notice"><strong>What this version can do</strong><p>Answer from your business information and explain how to contact your team. Callback requests can be prepared when permitted and need your confirmation. Synthetic bookings are available in development when enabled. Real phone transfers, bookings, orders and payments are not connected.</p></div><details><summary>Recent tests</summary>${state.calls.map(c=>`<p>${esc(new Date(c.created*1000).toLocaleString())}: ${esc(c.status)} · ${c.tokens} reported tokens</p>`).join('')||'<p>No calls yet.</p>'}</details><h3>Callback requests</h3><div id="voice-requests"></div><h3>Synthetic bookings</h3><div id="voice-bookings"></div></section></div>`;
    renderVoiceRequests(state.requests||[]);renderVoiceBookings(state);
    const form=document.querySelector('#voice-settings'),note=document.querySelector('#voice-save-status');
    let dirty=false;
    form.oninput=()=>{dirty=true;document.querySelector('#voice-start').disabled=true;document.querySelector('#voice-enable').disabled=true;note.textContent='Unsaved changes. Save before testing.';};
    form.onsubmit=async e=>{e.preventDefault();if(voiceCleanup)voiceCleanup();try{const values=Object.fromEntries(new FormData(form));await api('voice','PUT',{...values,revision:s.revision,max_seconds:Number(values.max_seconds),allow_interruptions:form.elements.allow_interruptions.checked,allow_callback_requests:form.elements.allow_callback_requests.checked,allow_demo_bookings:form.elements.allow_demo_bookings?.checked||false});await showVoice();toast('Settings saved. Try a call when you are ready.')}catch(e){note.textContent=e.message}};
    document.querySelector('#voice-enable').onclick=async()=>{try{await api('voice/enable','POST',{enabled:!state.enabled,revision:s.revision});await showVoice()}catch(e){note.textContent=e.message}};
    document.querySelector('#voice-start').onclick=()=>{if(!dirty)startVoiceCall();};
  }catch(e){page.textContent=e.message;}
}
async function startVoiceCall(){
  const status=document.querySelector('#voice-call-status'),start=document.querySelector('#voice-start'),end=document.querySelector('#voice-end');
  start.disabled=true;end.disabled=false;status.textContent='Requesting microphone access…';
  let stream,context,socket,capture,source,stopped=false,next=0,sources=new Set();
  const stop=()=>{if(stopped)return;stopped=true;socket?.close();stream?.getTracks().forEach(t=>t.stop());capture?.disconnect();source?.disconnect();for(const node of sources){try{node.stop()}catch{}}context?.close();end.disabled=true;start.disabled=false;voiceCleanup=null;};
  voiceCleanup=stop;end.onclick=()=>{stop();status.textContent='Call ended. You can test again or refresh to enable this setup.';api('voice').then(s=>{if(s.tested&&document.querySelector('#voice-enable'))document.querySelector('#voice-enable').disabled=false;}).catch(()=>{});};
  try{
    stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,channelCount:1},video:false});
    if(stopped){stream.getTracks().forEach(t=>t.stop());return;}
    context=new AudioContext({sampleRate:24000});await context.resume();await context.audioWorklet.addModule('/static/voice-capture.js');
    if(stopped){await context.close();return;}
    if(context.sampleRate!==24000)throw Error('This browser does not support the required audio format.');
    socket=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/api/voice/call`);
    socket.onmessage=e=>{if(stopped)return;const msg=JSON.parse(e.data);
      if(msg.type==='action_pending'){api('voice').then(s=>{renderVoiceRequests(s.requests||[]);renderVoiceBookings(s);}).catch(()=>{});}
      if(msg.type==='ready'){status.textContent='Connected. You can speak now.';source=context.createMediaStreamSource(stream);capture=new AudioWorkletNode(context,'voice-capture');capture.port.onmessage=e=>{if(socket.readyState===WebSocket.OPEN&&socket.bufferedAmount<96000)socket.send(e.data)};source.connect(capture);capture.connect(context.destination);}
      if(msg.type==='audio'){const raw=atob(msg.audio),bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);const pcm=new Int16Array(bytes.buffer),buffer=context.createBuffer(1,pcm.length,24000),channel=buffer.getChannelData(0);for(let i=0;i<pcm.length;i++)channel[i]=pcm[i]/32768;const player=context.createBufferSource();player.buffer=buffer;player.connect(context.destination);next=Math.max(next,context.currentTime);player.start(next);next+=buffer.duration;sources.add(player);player.onended=()=>sources.delete(player);}
      if(msg.type==='interrupt'){for(const node of sources){try{node.stop()}catch{}}sources.clear();next=context.currentTime;}
      if(msg.type==='error'||msg.type==='ended'){status.textContent=msg.message;stop();}
    };
    socket.onerror=()=>{status.textContent='Could not connect. Please try again.';stop();};
    socket.onclose=()=>{if(!stopped){status.textContent='Call ended. Refresh this page to see the result.';stop();}};
  }catch(e){status.textContent=e.name==='NotAllowedError'?'Microphone access was not allowed. Enable it in your browser to test.':e.message;stop();}
}
document.addEventListener('click',e=>{if(voiceCleanup&&(e.target.closest('[data-nav]')||e.target.closest('[data-agent]')||e.target.closest('#logout')||e.target.closest('.agent-nav')))voiceCleanup();},true);
window.addEventListener('pagehide',()=>voiceCleanup?.());

function renderVoiceRequests(requests){
  const box=document.querySelector('#voice-requests');if(!box)return;
  box.innerHTML=requests.map(r=>{const p=JSON.parse(r.payload);return `<article class="card"><strong>${esc(p.name)}</strong><p>${esc(p.contact)}</p><p>${esc(p.reason)}</p><p>${r.status==='SAVED_FOR_REVIEW'?'Saved for staff review. No message has been sent.':'Awaiting your confirmation.'}</p>${r.status==='PENDING_CONFIRMATION'?`<button data-confirm-callback="${esc(r.id)}">Confirm callback request</button>`:''}</article>`}).join('')||'<p>No callback requests yet.</p>';
  box.querySelectorAll('[data-confirm-callback]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{await api('voice/requests/'+button.dataset.confirmCallback+'/confirm','POST',{});const s=await api('voice');renderVoiceRequests(s.requests||[]);toast('Saved for staff review.')}catch(e){toast(e.message);button.disabled=false;}});
}

function renderVoiceBookings(state){
 const box=document.querySelector('#voice-bookings');if(!box)return;
 box.innerHTML='<p>Demo only. One accommodation per workspace, up to eight guests. Confirmed stays cannot overlap.</p>'+(state.demo_bookings||[]).map(b=>`<p><strong>${esc(b.id)}</strong>: ${esc(b.arrival)} to ${esc(b.departure)}, ${b.guests} guests</p>`).join('')+(state.booking_proposals||[]).map(r=>{const p=JSON.parse(r.payload);return `<article class="card"><strong>${esc(p.operation)} demo booking</strong><p>${esc(p.booking_id)} ${esc(p.arrival)} to ${esc(p.departure)}, ${p.guests} guests</p><p>${esc(r.status)} ${esc(r.result_id||'')}</p>${r.status==='PENDING_CONFIRMATION'?`<button data-confirm-booking="${esc(r.id)}">Confirm demo booking</button>`:''}</article>`}).join('');
 box.querySelectorAll('[data-confirm-booking]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{await api('voice/bookings/'+button.dataset.confirmBooking+'/confirm','POST',{});renderVoiceBookings(await api('voice'));toast('Synthetic booking saved. No real reservation was made.')}catch(e){toast(e.message);button.disabled=false;}});
}
