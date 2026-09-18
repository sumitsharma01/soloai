/* Operator review only. No email-delivery or generated-HTML rendering. */
function mountEmailReview(state) {
  if (!state.email_workflows) return;
  const nav = document.querySelector('.nav');
  const button = document.createElement('button');
  button.textContent = '✉ Email review';
  button.onclick = showEmailReview;
  nav.append(button);
  const gmailButton = document.createElement('button');
  gmailButton.textContent = 'Connect Gmail';
  gmailButton.onclick = showGmailConnection;
  nav.append(gmailButton);
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
    if (!state.available) { target.append(document.createTextNode('Google OAuth must be configured on the server.')); return; }
    if (!state.connected) {
      const input = document.createElement('input'); input.type = 'email'; input.placeholder = 'Your Gmail address'; input.setAttribute('aria-label','Gmail address');
      const connect = document.createElement('button'); connect.textContent = 'Connect with Google';
      connect.onclick = async () => {
        connect.disabled = true;
        try { const result = await api('integrations/gmail/connect','POST',{email:input.value.trim().toLowerCase()}); window.location.assign(result.url); }
        catch (error) { toast(error.message); connect.disabled = false; }
      };
      target.append(input,connect);
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
    list.textContent = result.executions.length ? '' : 'No forwarded emails yet. Send an email.received event with a unique id to /api/events.';
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
