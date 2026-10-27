/* Gmail connection controls. Support Inbox lives in inbox.js. */
function mountEmailReview(state) {
  if (!state.email_workflows) return;
  const nav = document.querySelector('[data-agent-group="email-support"]');
  if (!nav) return;
  const parent=nav.querySelector('.agent-nav-link');
  parent.textContent='▸ Email Support';parent.setAttribute('aria-expanded','false');parent.setAttribute('aria-controls','email-nav-children');
  const children=document.createElement('div');children.id='email-nav-children';children.hidden=true;
  children.innerHTML='<button data-email-page="overview">Overview</button><button class="inbox-nav-link" data-email-page="inbox">Support Inbox</button><button data-email-page="configuration">Configuration</button>';
  nav.append(children);
  parent.onclick=()=>{if(children.hidden)showEmailOverview();else{children.hidden=true;parent.setAttribute('aria-expanded','false');parent.textContent='▸ Email Support';}};
  children.querySelector('[data-email-page="overview"]').onclick=showEmailOverview;
  children.querySelector('[data-email-page="inbox"]').onclick=showEmailReview;
  children.querySelector('[data-email-page="configuration"]').onclick=()=>{selected='email-support';view='detail';render();activateEmailPage('configuration');};
  if(view==='detail'&&selected==='email-support')activateEmailPage('configuration');
  // Existing transient /api/try remains available. Explain the explicitly enabled
  // durable inbox separately so legacy privacy badges are not misleading.
  document.querySelectorAll('.chip').forEach(chip => {
    if (chip.textContent === 'No content storage') chip.textContent = 'Manual tests are transient';
  });
  document.querySelectorAll('.check').forEach(check => {
    if (check.textContent.includes('Customer content stored') || check.textContent.includes('Store message content')) {
      check.textContent = 'Queued emails and drafts: temporary review storage enabled';
    }
  });
  const notice = document.createElement('p');
  notice.className = 'notice';
  notice.textContent = 'Email review is enabled. Forwarded emails and drafts are stored temporarily for review. Manual tests stay transient. Sending requires separate Gmail authorization. Automatic sending is off until you enable it in Support Inbox.';
  document.querySelector('.content').prepend(notice);
}

async function showGmailConnection() {
  const page = document.querySelector('#page');
  page.innerHTML = '<section class="panel"><h2>Gmail connection</h2><p>New inbox messages are sent to your Azure Foundry email agent and stored temporarily for your review. Sending requires separate authorization; SoloAI never deletes mail. Existing inbox contents are not imported.</p><div id="gmail-status" aria-live="polite">Loading…</div></section>';
  const target = document.querySelector('#gmail-status');
  try {
    const state = await api('integrations/gmail');
    target.replaceChildren();
    const summary = document.createElement('p');
    summary.textContent = state.connected ? `Connected: ${state.email}. Last sync: ${state.last_sync ? new Date(state.last_sync*1000).toLocaleString() : 'Waiting for first sync'}. Status: ${state.error || 'Ready'}. Sending: ${state.send_authorized ? 'authorized' : 'not authorized'}` : 'No mailbox connected.';
    target.append(summary);
    if (!state.available) { target.append(document.createTextNode('Gmail is not set up on this SoloAI installation yet. Ask the person running SoloAI to complete the Gmail setup guide. You can still try an agent from My agents.')); return; }
    if (!state.connected) {
      const connect = document.createElement('button'); connect.textContent = 'Connect with Google';
      connect.onclick = () => beginGmailConnection(connect);
      target.append(connect);
    } else {
      const disconnect = document.createElement('button'); disconnect.textContent = 'Disconnect Gmail';
      disconnect.onclick = async () => { try { await api('integrations/gmail/disconnect','POST'); await showGmailConnection(); } catch(error) { toast(error.message); } };
      const note = document.createElement('p'); note.textContent = 'Disconnect stops future syncing and deletes saved tokens. Already queued drafts remain subject to retention. You can also revoke access in your Google Account. Sync runs approximately every 60 seconds while the worker is running.';
      const reconnect=document.createElement('button');reconnect.textContent='Reconnect with Google';
      reconnect.onclick=async()=>{try{const r=await api('integrations/gmail/connect','POST',{allow_send:!!state.send_authorized});location.assign(r.url)}catch(e){toast(e.message)}};
      target.append(reconnect,disconnect,note);
      if(state.error==='gmail_history_expired'){const reset=document.createElement('button');reset.textContent='Restart sync from now';reset.onclick=async()=>{if(!confirm('The missed period will not be imported. Review it manually in Gmail. Automatic replies will be paused. Restart from now?'))return;try{await api('integrations/gmail/reset-sync','POST');await showGmailConnection()}catch(e){toast(e.message)}};target.append(reset)}
    }
    const refresh = document.createElement('button'); refresh.textContent = 'Refresh connection status'; refresh.onclick = showGmailConnection; target.append(refresh);
  } catch(error) { target.textContent = error.message; }
}

// Connection status comes from the signed-in workspace, never a browser tenant ID.
async function showIntegrations() {
  const page = document.querySelector('#page');
  page.innerHTML = `<section class="panel"><h2>Your tools, in one place</h2><p>Your website can stay on Vercel, AWS or wherever you host it. Connect only the information your agent needs.</p><div class="steps"><span>1 Choose a tool</span><span>2 Review access</span><span>3 Connect</span></div></section>
  <div class="agents">
    <section class="card"><div class="icon email">✉</div><h2>Gmail</h2><p>Read customer emails and prepare replies. Sending needs separate Google authorization; deleting is never allowed.</p><p id="gmail-summary" role="status">Checking connection…</p><button class="primary" id="open-gmail">Connect with Google</button></section>
    <section class="card"><div class="icon">⌁</div><h2>Booking information</h2><p>Let the email agent look up a booking through an approved, read-only connection.</p><p id="booking-summary" role="status">Checking connection…</p><p>Use Supabase for a restricted live lookup. Legacy MCP and local snapshots are development-only.</p></section>
    <section class="card"><div class="icon">⌁</div><h2>Supabase</h2><p>Connect a restricted booking function in your Supabase project.</p><p>Read-only access. Customer verification required before lookup.</p><button class="primary" id="open-supabase">Set up Supabase</button></section>
  </div><details class="panel"><summary>More integrations</summary><div class="agents">
    <section class="card"><span class="chip">Pilot connector</span><h2>Outlook</h2><p>Connect Microsoft mail with delegated read access and optional sending.</p><button id="open-outlook">Connect Outlook</button></section>
  </div></details><section class="panel"><h2>Next: try your agent</h2><p>Open My agents, add your business guidance and turn on the agent. With Gmail and the email worker configured, new messages appear in Email review. Use Support Inbox to edit drafts, send reviewed replies and manage automatic sending.</p><details><summary>For developers: connect your own application</summary><p>Use the server API when you need to send events from your app. This is optional for Gmail.</p><button id="open-api">Application API setup</button></details></section>`;
  const connect = page.querySelector('#open-gmail');
  connect.onclick = () => beginGmailConnection(connect);
  page.querySelector('#open-api').onclick = showApplicationConnection;
  page.querySelector('#open-supabase').onclick = showBookingConnection;
  page.querySelector('#open-outlook').onclick = showOutlookConnection;
  const gmail = page.querySelector('#gmail-summary');
  const booking = page.querySelector('#booking-summary');
  await Promise.all([
    api('integrations/gmail').then(s => { if (s.connected) { connect.textContent = 'Manage Gmail'; connect.onclick = showGmailConnection; } gmail.textContent = s.connected ? `Connected: ${s.email}` : s.available ? 'Ready to connect with Google' : 'Setup needed by your SoloAI operator'; }).catch(e => { gmail.textContent = e.message; }),
    api('integrations/booking').then(s => { booking.textContent = `${s.mode}. ${s.note}`; }).catch(e => { booking.textContent = e.message; })
  ]);
}

// Authorization begins on the server so secrets and workspace binding stay there.
async function beginGmailConnection(button) {
  button.disabled = true;
  try {
    const state = await api('integrations/gmail');
    if (state.connected || !state.available) {
      await showGmailConnection();
      return;
    }
    const result = await api('integrations/gmail/connect', 'POST', {});
    window.location.assign(result.url);
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; }
}


async function showSupabaseSetup() {
  const page = document.querySelector('#page');
  page.innerHTML = `<section class="panel form"><button id="back-integrations">← Integrations</button>
    <h2>Connect your booking data</h2><p>Start with the details below. Your operator uses them to configure a restricted booking lookup.</p>
    <p class="notice">This step saves a setup request. It does not connect to Supabase or grant database access. Do not enter passwords, API keys or real customer records.</p>
    <form id="supabase-setup">
      <label>Project URL<input name="project_url" type="url" required maxlength="200" placeholder="https://your-project.supabase.co"></label>
      <label>Booking table<input name="table_name" required maxlength="63" placeholder="bookings"></label>
      <label>Booking reference column<input name="reference_column" required maxlength="63" placeholder="booking_reference"></label>
      <label>Customer identifier column<input name="customer_column" required maxlength="63" placeholder="customer_id"></label>
      <label>Fields the agent may read<input name="allowed_fields" required maxlength="1279" placeholder="status, arrival_date, departure_date"></label>
      <p>Separate column names with commas. Include only information needed to answer booking questions.</p>
      <label>Which bookings belong to this business?<textarea name="ownership_rule" required minlength="10" maxlength="1000" placeholder="For example: this project belongs only to our hotel, or records are restricted by business_id."></textarea></label>
      <label>How should a customer prove they may see a booking?<textarea name="verification_rule" required minlength="10" maxlength="1000" placeholder="For example: require a verified customer session. A booking reference alone is not proof of identity."></textarea></label>
      <div class="check">Allowed action <b>Read booking details only</b></div>
      <label><input type="checkbox" required> I understand that this saves requirements, and access must be configured and tested before the agent can use them.</label>
      <button class="primary" type="submit">Save and request setup</button>
    </form><p id="supabase-result" role="status">Loading saved details…</p></section>`;
  page.querySelector('#back-integrations').onclick = showIntegrations;
  const form = page.querySelector('#supabase-setup');
  const result = page.querySelector('#supabase-result');
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    const saved = await api('integrations/supabase');
    if (!form.isConnected) return;
    for (const [key,value] of Object.entries(saved.configuration || {})) {
      if (form.elements.namedItem(key)) form.elements.namedItem(key).value = Array.isArray(value) ? value.join(', ') : value;
    }
    result.textContent = saved.configuration ? 'Setup requested. Authorization pending. You can update the details below.' : 'No setup request saved yet.';
    submit.disabled = false;
  } catch (error) { result.textContent = error.message + ' Reload this page to try again.'; }
  form.onsubmit = async event => {
    event.preventDefault(); submit.disabled = true;
    const values = Object.fromEntries(new FormData(form));
    values.project_url = values.project_url.trim().replace(/\/$/, '');
    for (const key of ['table_name','reference_column','customer_column']) values[key] = values[key].trim();
    values.allowed_fields = [...new Set(values.allowed_fields.split(',').map(x => x.trim()).filter(Boolean))];
    try { const response = await api('integrations/supabase/setup','POST',values); result.textContent = response.message; }
    catch (error) { result.textContent = error.message; }
    finally { submit.disabled = false; }
  };
}

function activateEmailPage(name){
  if(typeof voiceCleanup==='function')voiceCleanup();
  document.querySelector('.content')?.classList.remove('inbox-mode');
  const tree=document.querySelector('#email-nav-children');if(tree)tree.hidden=false;
  const parent=document.querySelector('[data-agent-group="email-support"] > button');if(parent){parent.textContent='▾ Email Support';parent.setAttribute('aria-expanded','true');}
  document.querySelectorAll('.nav button').forEach(b=>{b.classList.remove('active');b.removeAttribute('aria-current');});
  const selected=document.querySelector(`[data-email-page="${name}"]`);if(selected){selected.classList.add('active');selected.setAttribute('aria-current','page');}
  const notice=document.querySelector('.content > .notice');if(notice)notice.hidden=true;
}
async function showEmailOverview(){
  activateEmailPage('overview');
  const page=document.querySelector('#page');page.innerHTML='<section class="panel" role="status">Loading email overview…</section>';
  document.querySelector('.main header span').textContent='My agents / Email Support / Overview';
  document.querySelector('.heading h1').textContent='Email Support';document.querySelector('.heading p').textContent='Inbox workload, review progress and delivery outcomes.';
  try{
    const o=await api('inbox/overview');if(!page.isConnected||document.querySelector('[aria-current="page"]')?.dataset.emailPage!=='overview')return;
    const n=v=>Number(v||0).toLocaleString(),s=o.statuses,d=o.deliveries,total=Object.values(s).reduce((a,b)=>a+b,0);
    const metric=(label,value,detail)=>`<div class="stat"><small>${label}</small><strong>${value}</strong><footer>${detail}</footer></div>`;
    const max=Math.max(1,...o.daily.map(x=>x.received));
    page.innerHTML=`<section class="panel voice-overview-header"><div><span class="chip">Email operations</span><h2>Email Support</h2><p>Agent ID <code>${esc(o.agent_id)}</code></p><p>Automatic sending <strong>${o.automatic?'On':'Off'}</strong> · Daily automatic limit ${n(o.daily_limit)}</p></div><div class="actions"><button id="email-overview-refresh">Refresh</button><button class="primary" id="email-overview-inbox">Open Support Inbox →</button></div></section>
    <div class="stats voice-stats">${metric('Emails received',n(total),'All retained queued email records')}${metric('Awaiting review',n(s.WAITING_FOR_REVIEW),`${n(o.needs_human)} flagged for human assistance`)}${metric('In progress',n((s.QUEUED||0)+(s.RUNNING||0)),`${n(s.QUEUED)} queued · ${n(s.RUNNING)} running`)}${metric('Replies sent',n(d.SENT),`${n(o.auto_sent)} automatically sent`)}</div>
    <div class="voice-overview-grid"><section class="panel"><h2>Email volume</h2><p>New queued emails by UTC date, last seven days. Manual draft tests are excluded.</p><div class="voice-chart" role="img" aria-label="Queued emails by day">${o.daily.map(x=>`<div class="voice-bar-column"><span>${x.received}</span><div class="voice-bar-track"><div class="voice-bar" style="height:${x.received/max*100}%"></div></div><small>${esc(x.date.slice(5))}</small></div>`).join('')}</div><details><summary>View daily counts</summary><table class="voice-data"><thead><tr><th>Date (UTC)</th><th>Emails</th></tr></thead><tbody>${o.daily.map(x=>`<tr><td>${esc(x.date)}</td><td>${n(x.received)}</td></tr>`).join('')}</tbody></table></details></section>
    <section class="panel"><h2>Review and delivery</h2><div class="check">Human assistance required <b>${n(o.needs_human)}</b></div><div class="check">Processing failures <b>${n(s.FAILED)}</b></div><div class="check">Delivery failures <b>${n(d.FAILED)}</b></div><div class="check">Uncertain delivery <b>${n(d.UNKNOWN)}</b></div><p>Check uncertain deliveries in the mailbox before retrying. A prepared or approved draft is not a sent reply.</p><div class="check">Rejected drafts <b>${n(s.REJECTED)}</b></div></section>
    <section class="panel"><h2>Model usage</h2><div class="check">Accounted tokens <b>${n(o.usage.tokens)}</b></div><div class="check">Finished processing records <b>${n(o.usage.samples)}</b></div><div class="check">Average execution latency <b>${o.usage.latency===null?'No samples':n(Math.round(o.usage.latency))+' ms'}</b></div><p>Based on finished queued executions, including failed attempts. Token accounting can include conservative reservations after uncertain outcomes. Latency runs from queue arrival to processing completion, including queue time and retries. It is not time to customer delivery. P95 and reply-quality scores are not shown here.</p></section>
    <section class="panel"><h2>Sending controls</h2><div class="check">Gmail sending permission <b>${o.send_authorized.gmail?'Authorized':'Not authorized'}</b></div><div class="check">Outlook sending permission <b>${o.send_authorized.outlook?'Authorized':'Not authorized'}</b></div><p>Authorization does not prove mailbox connectivity. Sending also depends on the agent permissions, automation rules and review decisions.</p><button id="email-overview-health">View connector health</button></section></div><p class="muted">Counts cover retained workspace records. Updated ${esc(new Date(o.updated*1000).toLocaleString())}. Refresh for a new snapshot.</p>`;
    document.querySelector('#email-overview-refresh').onclick=showEmailOverview;document.querySelector('#email-overview-inbox').onclick=showEmailReview;document.querySelector('#email-overview-health').onclick=showSupportHealth;
  }catch(e){page.textContent=e.message;}
}
