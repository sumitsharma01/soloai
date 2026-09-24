/* Operator review only. No email-delivery or generated-HTML rendering. */
function mountEmailReview(state) {
  if (!state.email_workflows) return;
  const nav = document.querySelector('.nav');
  const button = document.createElement('button');
  button.textContent = '✉ Email review';
  button.onclick = showEmailReview;
  nav.append(button);
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
  notice.textContent = 'Email review is enabled. Forwarded emails and drafts are stored temporarily for review. Manual tests stay transient. Approval records your decision and does not send mail.';
  document.querySelector('.content').prepend(notice);
}

async function showGmailConnection() {
  const page = document.querySelector('#page');
  page.innerHTML = '<section class="panel"><h2>Gmail connection</h2><p>Read-only access. New inbox messages are sent to your Azure Foundry email agent and stored temporarily for your review. SoloAI does not send or delete mail. Existing inbox contents are not imported.</p><div id="gmail-status" aria-live="polite">Loading…</div></section>';
  const target = document.querySelector('#gmail-status');
  try {
    const state = await api('integrations/gmail');
    target.replaceChildren();
    const summary = document.createElement('p');
    summary.textContent = state.connected ? `Connected: ${state.email}. Last sync: ${state.last_sync ? new Date(state.last_sync*1000).toLocaleString() : 'Waiting for first sync'}. Status: ${state.error || 'Ready'}` : 'No mailbox connected.';
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
      target.append(disconnect,note);
    }
    const refresh = document.createElement('button'); refresh.textContent = 'Refresh connection status'; refresh.onclick = showGmailConnection; target.append(refresh);
  } catch(error) { target.textContent = error.message; }
}

async function showEmailReview() {
  const page = document.querySelector('#page');
  if (!page) return;
  page.innerHTML = '<section class="panel"><h2>Email review</h2><p>Incoming emails, drafts and processing status. Approval does not send an email.</p><button id="email-refresh">Refresh</button><div id="email-list" aria-live="polite">Loading…</div><div id="email-detail"></div></section>';
  document.querySelector('#email-refresh').onclick = showEmailReview;
  const list = document.querySelector('#email-list');
  try {
    const result = await api('email/executions');
    if (!list.isConnected) return;
    list.textContent = result.executions.length ? '' : 'No emails yet. Connect Gmail in Integrations, then send a new message to that inbox.';
    for (const execution of result.executions) {
      const row = document.createElement('p');
      const open = document.createElement('button');
      open.textContent = `${execution.status} · ${new Date(execution.created_at * 1000).toLocaleString()}`;
      open.onclick = () => showEmailExecution(execution.execution_id);
      row.append(open);
      list.append(row);
    }
  } catch (error) { list.textContent = error.message; }
}

async function showEmailExecution(id) {
  const target = document.querySelector('#email-detail');
  target.textContent = 'Loading execution…';
  try {
    const execution = await api(`executions/${encodeURIComponent(id)}`);
    if (!target.isConnected) return;
    target.replaceChildren();
    const heading = document.createElement('h3');
    heading.textContent = execution.subject || 'Email execution';
    target.append(heading);
    for (const [label, value] of [
      ['Status', execution.status], ['Error', execution.error || 'None'],
      ['Tokens', `${execution.tokens} (${execution.usage_kind}; uncertain: ${execution.uncertain_tokens})`], ['Latency', `${execution.latency} ms`],
      ['Provider latency', `${execution.provider_latency} ms`],
      ['Needs human help', execution.needs_human == null ? 'Pending' : String(execution.needs_human)],
      ['Model / agent version', `${execution.model} / ${execution.agent_version}`],
      ['Content expiry', new Date(execution.expires_at * 1000).toLocaleString()]
    ]) {
      const p = document.createElement('p'); p.textContent = `${label}: ${value}`; target.append(p);
    }
    for (const [label, value] of [['Incoming message', execution.content], ['Draft', execution.draft]]) {
      const h = document.createElement('h3'); h.textContent = label;
      const body = document.createElement('pre'); body.textContent = value || 'Not available or expired.';
      target.append(h, body);
    }
    const tools = document.createElement('p');
    tools.textContent = 'Tools: ' + (execution.tools.map(t => `${t.tool_name}: ${t.status} (${t.duration} ms)`).join(', ') || 'None');
    target.append(tools);
    if (execution.status === 'WAITING_FOR_REVIEW') {
      for (const action of ['approve', 'reject']) {
        const button = document.createElement('button');
        button.textContent = action === 'approve' ? 'Approve draft (no sending)' : 'Reject draft';
        button.onclick = async () => {
          target.querySelectorAll('button').forEach(b => { b.disabled = true; });
          try { await api(`executions/${encodeURIComponent(id)}/${action}`, 'POST'); await showEmailExecution(id); }
          catch (error) { toast(error.message); await showEmailExecution(id); }
        };
        target.append(button);
      }
    }
  } catch (error) { target.textContent = error.message; }
}

// Connection status comes from the signed-in workspace, never a browser tenant ID.
async function showIntegrations() {
  const page = document.querySelector('#page');
  page.innerHTML = `<section class="panel"><h2>Your tools, in one place</h2><p>Your website can stay on Vercel, AWS or wherever you host it. Connect only the information your agent needs.</p><div class="steps"><span>1 Choose a tool</span><span>2 Review access</span><span>3 Connect</span></div></section>
  <div class="agents">
    <section class="card"><div class="icon email">✉</div><h2>Gmail</h2><p>Read new customer emails and prepare drafts for your review. No sending or deleting.</p><p id="gmail-summary" role="status">Checking connection…</p><button class="primary" id="open-gmail">Connect with Google</button></section>
    <section class="card"><div class="icon">⌁</div><h2>Booking information</h2><p>Let the email agent look up a booking through an approved, read-only connection.</p><p id="booking-summary" role="status">Checking connection…</p><p>Your SoloAI operator sets up this connection for your workspace. Self-service setup is not available yet.</p></section>
    <section class="card"><div class="icon">⌁</div><h2>Supabase</h2><p>Tell us where your booking data lives and what the email agent may read.</p><p>Guided setup. Authorization requires operator configuration.</p><button class="primary" id="open-supabase">Set up Supabase</button></section>
  </div><details class="panel"><summary>Planned integrations</summary><div class="agents">
    <section class="card"><span class="chip">Planned</span><h2>More tools</h2><p>Outlook and other services will appear here as their connectors become available.</p><button disabled>Coming soon</button></section>
  </div></details><section class="panel"><h2>Next: try your agent</h2><p>Open My agents, add your business guidance and turn on the agent. With Gmail and the email worker configured, new messages appear in Email review. Approval records your decision; it does not send the reply.</p><details><summary>For developers: connect your own application</summary><p>Use the server API when you need to send events from your app. This is optional for Gmail.</p><button id="open-api">Application API setup</button></details></section>`;
  const connect = page.querySelector('#open-gmail');
  connect.onclick = () => beginGmailConnection(connect);
  page.querySelector('#open-api').onclick = showApplicationConnection;
  page.querySelector('#open-supabase').onclick = showSupabaseSetup;
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
