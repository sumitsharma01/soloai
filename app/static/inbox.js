/* Support Inbox: compact rows, explicit review and no generated HTML rendering. */
let inboxState, inboxSearch='', inboxFilter='all', inboxLabel='all';
const inboxDate = value => new Date(value*1000).toLocaleString();
const inboxStatus = row => row.delivery ? row.delivery.status : row.needs_human && row.status==='WAITING_FOR_REVIEW' ? 'NEEDS HUMAN' : row.status;
const labelOptions = (chosen=[], all=false) => (all?'<option value="">All emails</option>':'') + inboxState.labels.map(l=>`<option value="${esc(l.id)}" ${chosen.includes(l.id)?'selected':''}>${esc(l.name)}</option>`).join('');

async function showEmailReview() {
  const page=document.querySelector('#page');
  document.querySelector('.content').classList.add('inbox-mode');
  const notice=document.querySelector('.content > .notice');if(notice)notice.hidden=true;
  document.querySelector('header > span').textContent='Workspace / Support Inbox';
  document.querySelectorAll('.nav button').forEach(b=>b.classList.toggle('active',b.textContent.includes('Support Inbox')));
  page.innerHTML='<section class="panel"><h2>Support Inbox</h2><p role="status">Loading emails…</p></section>';
  try {
    inboxState=await api('inbox');
    if (!page.isConnected) return;
    document.querySelector('.heading h1').textContent='Support Inbox';
    document.querySelector('.heading p').textContent='Review the exceptions. Keep every reply accountable.';
    page.innerHTML=`<section class="panel inbox-toolbar"><div><h2>Email Support</h2><p>Automatic sending: <strong>${inboxState.rules.automatic?'On':'Off'}</strong> · Gmail sending: ${inboxState.send_authorized?'Authorized':'Not authorized'}</p></div><div class="actions"><button id="inbox-rules">Automation rules</button>${inboxState.rules.automatic?'<button class="danger" id="inbox-pause">Pause automatic sending</button>':''}<button id="inbox-labels">Labels</button><button id="inbox-instructions">Business instructions</button><button id="inbox-refresh">Refresh</button></div></section>
      <section class="panel inbox-list"><div class="inbox-filters"><label>Search<input id="inbox-search" placeholder="Sender or subject" value="${esc(inboxSearch)}"></label><label>Status<select id="inbox-filter">${['all','review','processing','sent','failed'].map(v=>`<option value="${v}" ${v===inboxFilter?'selected':''}>${({all:'All emails',review:'Needs review',processing:'Processing',sent:'Sent',failed:'Failed / uncertain'})[v]}</option>`).join('')}</select></label><label>Label<select id="inbox-label"><option value="all">All labels</option>${labelOptions([inboxLabel])}</select></label></div><p>Latest 100 emails. Labels are suggested using editable keywords; they do not grant permissions.</p><div id="inbox-rows"></div></section>`;
    document.querySelector('#inbox-search').oninput=e=>{inboxSearch=e.target.value;renderInboxRows()};
    document.querySelector('#inbox-filter').onchange=e=>{inboxFilter=e.target.value;renderInboxRows()};
    document.querySelector('#inbox-label').onchange=e=>{inboxLabel=e.target.value;renderInboxRows()};
    document.querySelector('#inbox-refresh').onclick=showEmailReview;
    document.querySelector('#inbox-rules').onclick=showInboxRules;
    document.querySelector('#inbox-labels').onclick=showInboxLabels;
    document.querySelector('#inbox-instructions').onclick=()=>showInboxInstructions();
    if(document.querySelector('#inbox-pause')) document.querySelector('#inbox-pause').onclick=async()=>{try{await api('inbox/rules','PUT',{...rulePayload(),automatic:false});await showEmailReview()}catch(e){toast(e.message)}};
    renderInboxRows();
  } catch(error) {page.textContent=error.message;}
}
function renderInboxRows(){
  const rows=inboxState.emails.filter(r=>{
    const status=inboxStatus(r);
    return (r.sender+' '+r.subject).toLowerCase().includes(inboxSearch.toLowerCase()) && (inboxLabel==='all'||r.labels.includes(inboxLabel)) &&
      (inboxFilter==='all'||inboxFilter==='review'&&['WAITING_FOR_REVIEW','NEEDS HUMAN','APPROVED'].includes(status)||inboxFilter==='processing'&&['QUEUED','RUNNING','DISPATCHING'].includes(status)||inboxFilter==='sent'&&status==='SENT'||inboxFilter==='failed'&&['FAILED','UNKNOWN'].includes(status));
  });
  const target=document.querySelector('#inbox-rows');
  target.innerHTML=rows.length?`<div class="tablewrap"><table><thead><tr><th>Sender / subject</th><th>Labels</th><th>Status</th><th>Received</th></tr></thead><tbody>${rows.map(r=>`<tr><td><button class="ticket-open" data-ticket="${esc(r.id)}"><strong>${esc(r.subject)}</strong><small>${esc(r.sender)}</small></button></td><td>${r.labels.map(id=>`<span class="chip">${esc(inboxState.labels.find(l=>l.id===id)?.name||id)}</span>`).join(' ')}</td><td><span class="chip">${esc(inboxStatus(r).replaceAll('_',' '))}</span></td><td>${inboxDate(r.created)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="empty">No emails match this view. Connect Gmail in Integrations to receive new messages.</p>';
  target.querySelectorAll('[data-ticket]').forEach(b=>b.onclick=()=>openInboxEmail(b.dataset.ticket));
}
function inboxDialog(title){
  const dialog=document.createElement('dialog');dialog.className='inbox-dialog';
  dialog.innerHTML=`<div class="inbox-dialog-head"><h2>${esc(title)}</h2><div><button data-expand>Expand</button><button data-close>Close</button></div></div><div class="inbox-dialog-body"></div>`;
  document.body.append(dialog);dialog.showModal();
  dialog.querySelector('[data-expand]').onclick=()=>{dialog.classList.toggle('expanded');dialog.querySelector('[data-expand]').textContent=dialog.classList.contains('expanded')?'Restore':'Expand'};
  dialog.querySelector('[data-close]').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>dialog.remove());
  return dialog;
}
async function refreshInboxData(){inboxState=await api('inbox');if(document.querySelector('#inbox-rows'))renderInboxRows()}
async function openInboxEmail(id){
  const dialog=inboxDialog('Email details'),body=dialog.querySelector('.inbox-dialog-body');body.textContent='Loading…';
  try {
    const r=await api('inbox/emails/'+encodeURIComponent(id));if(!dialog.isConnected)return;
    let dirty=false;
    const protect=e=>{if(dirty&&!confirm('Discard unsaved reply edits?'))e.preventDefault()};
    dialog.addEventListener('cancel',protect);
    dialog.querySelector('[data-close]').onclick=()=>{if(!dirty||confirm('Discard unsaved reply edits?'))dialog.close()};
    const locked=r.delivery&&['SENT','DISPATCHING','UNKNOWN'].includes(r.delivery.status);
    const editable=!locked&&r.content&&['WAITING_FOR_REVIEW','APPROVED','FAILED'].includes(r.status);
    body.innerHTML=`<p><strong>${esc(r.original_subject||r.subject||'Support email')}</strong></p><p>Reply to: ${esc(r.recipient||'Unavailable for this event')}<br>Status: ${esc(r.delivery?.status||r.status)} · ${inboxDate(r.created_at)}</p>
      ${r.delivery?`<p class="notice">Delivery: ${esc(r.delivery.status)} · ${r.delivery.actor==='agent'?'Agent':'Workspace owner'} · ${inboxDate(r.delivery.updated)}${r.delivery.status==='UNKNOWN'?' · Check Gmail Sent before taking any further action. SoloAI will not retry this delivery.':''}</p>`:''}
      <details open><summary>Customer email</summary><div class="inbox-message">${esc(r.content||'Content expired')}</div></details>
      <details><summary>Context and checks</summary><p>${r.needs_human?'The agent requested human assistance. Verify the facts and customer identity before replying.':'Review the reply against the customer request and your policy.'}</p><p>${esc(r.error||'No execution error recorded.')}</p><p>Tools: ${esc(r.tools.map(t=>t.tool_name+': '+t.status).join(', ')||'None')}</p><p>Tool result content is not retained. The email above is the ingested message, not a fetched full Gmail thread.</p><p>${r.tokens} tokens · ${r.latency} ms · Content expires ${inboxDate(r.expires_at)}</p></details>
      <form id="ticket-form"><label>Reply<textarea name="draft" maxlength="12000" required ${editable?'':'disabled'}>${esc(r.draft||'')}</textarea></label>
      <label>Labels<select name="labels" multiple ${editable?'':'disabled'}>${labelOptions(r.labels)}</select></label>
      <label>Guidance for this email only<textarea name="local_guidance" maxlength="1000" ${editable?'':'disabled'} placeholder="Add context, save, then regenerate the draft.">${esc(r.local_guidance)}</textarea></label>
      <div class="actions"><button type="submit" ${editable?'':'disabled'}>Save draft</button><button type="button" id="ticket-regenerate" ${editable?'':'disabled'}>Regenerate draft</button><button type="button" class="primary" id="ticket-send" ${editable&&r.recipient&&r.send_authorized?'':'disabled'}>Send reply</button><button type="button" id="ticket-reject" ${r.status==='WAITING_FOR_REVIEW'&&!locked?'':'disabled'}>Reject draft</button></div></form>
      ${!r.send_authorized?'<p>Sending needs separate Google authorization. Use Automation rules → Authorize Gmail sending.</p>':''}
      <button id="ticket-future">Save guidance for future emails</button><p id="ticket-result" role="status"></p>`;
    const form=body.querySelector('form'),result=body.querySelector('#ticket-result');
    form.oninput=()=>{dirty=true};form.onchange=()=>{dirty=true};
    const save=async()=>{
      const response=await api('inbox/emails/'+id,'PUT',{draft:form.elements.draft.value,local_guidance:form.elements.local_guidance.value,labels:Array.from(form.elements.labels.selectedOptions,o=>o.value),revision:r.revision});
      r.revision=response.revision;dirty=false;result.textContent='Draft saved.';
    };
    const action=async task=>{const buttons=Array.from(body.querySelectorAll('button'),b=>[b,b.disabled]);buttons.forEach(([b])=>b.disabled=true);try{await task()}catch(e){result.textContent=e.message}finally{buttons.forEach(([b,disabled])=>b.disabled=disabled)}};
    form.onsubmit=e=>{e.preventDefault();action(save)};
    body.querySelector('#ticket-regenerate').onclick=()=>action(async()=>{await save();await api('inbox/emails/'+id+'/regenerate','POST',{revision:r.revision});dialog.close();await refreshInboxData();toast('Queued for a new draft. Refresh the inbox when processing finishes.')});
    body.querySelector('#ticket-send').onclick=()=>action(async()=>{
      if(!confirm('Send this reply to '+r.recipient+'?'))return;
      await save();const sent=await api('inbox/emails/'+id+'/send','POST',{revision:r.revision});dialog.close();await refreshInboxData();toast(sent.sent?'Reply sent.':sent.status==='UNKNOWN'?'Delivery is uncertain. Check Gmail Sent; do not resend.':'Gmail rejected delivery. Your draft is saved.');
    });
    body.querySelector('#ticket-reject').onclick=()=>action(async()=>{await api('executions/'+id+'/reject','POST');dirty=false;dialog.close();await refreshInboxData()});
    body.querySelector('#ticket-future').onclick=()=>showInboxInstructions(form.elements.local_guidance.value);
  }catch(e){body.textContent=e.message}
}
function rulePayload(){const r=inboxState.rules;return {automatic:r.automatic,allowed_labels:r.allowed_labels,daily_limit:r.daily_limit,revision:r.revision}}
function showInboxRules(){
  const dialog=inboxDialog('Automation rules'),body=dialog.querySelector('.inbox-dialog-body'),r=inboxState.rules;
  body.innerHTML=`<p>Classification, permitted lookups and draft preparation run automatically. Sending is a separate permission.</p><p class="notice">Automatic sending applies only to new emails received after you save these rules. Refunds, cancellations, booking/account details, failed lookups, edited drafts and requests for human help stay in review. Keyword rules are conservative checks, not a guarantee of reply accuracy.</p>
    ${!inboxState.send_authorized?'<button id="authorize-send">Authorize Gmail sending</button><p>Google will ask for read and send permissions. This does not turn on automatic sending.</p>':'<p>Gmail read and send permissions are authorized.</p>'}
    <form><label class="inbox-toggle"><input name="automatic" type="checkbox" ${r.automatic?'checked':''} ${inboxState.send_authorized?'':'disabled'}> Allow automatic replies</label><label>Eligible labels<select name="allowed" multiple>${labelOptions(r.allowed_labels)}</select></label><label>Daily send limit (manual and automatic, UTC)<input type="number" name="limit" min="1" max="200" value="${r.daily_limit}" required></label><p>Pausing stops new dispatches. A reply already being sent cannot be recalled.</p><button class="primary">Save rules</button><p role="status"></p></form>`;
  if(body.querySelector('#authorize-send'))body.querySelector('#authorize-send').onclick=async()=>{try{const response=await api('integrations/gmail/connect','POST',{allow_send:true});location.assign(response.url)}catch(e){toast(e.message)}};
  const form=body.querySelector('form');form.onsubmit=async e=>{e.preventDefault();try{await api('inbox/rules','PUT',{automatic:form.elements.automatic.checked,allowed_labels:Array.from(form.elements.allowed.selectedOptions,o=>o.value),daily_limit:Number(form.elements.limit.value),revision:r.revision});dialog.close();await showEmailReview()}catch(error){form.querySelector('[role="status"]').textContent=error.message}};
}
function showInboxLabels(){
  const dialog=inboxDialog('Labels'),body=dialog.querySelector('.inbox-dialog-body');
  body.innerHTML=`<p>Keywords suggest labels on new messages. Existing messages keep their labels. Editing or deleting a label pauses automatic sending so you can review the rules.</p><div id="label-list">${inboxState.labels.map(l=>`<form data-id="${esc(l.id)}"><label>Name<input name="name" maxlength="60" required value="${esc(l.name)}"></label><label>Keywords, separated by commas<input name="keywords" maxlength="500" value="${esc(l.keywords)}"></label><div class="actions"><button>Save label</button><button type="button" data-remove="${esc(l.id)}">Remove label</button></div></form>`).join('')}</div><h3>Create a label</h3><form id="label-new"><label>Name<input name="name" maxlength="60" required></label><label>Keywords<input name="keywords" maxlength="500" placeholder="delivery, shipment"></label><button>Create label</button></form>`;
  body.querySelectorAll('form').forEach(form=>form.onsubmit=async e=>{e.preventDefault();try{await api('inbox/labels'+(form.dataset.id?'/'+form.dataset.id:''),form.dataset.id?'PUT':'POST',Object.fromEntries(new FormData(form)));dialog.close();await showEmailReview();showInboxLabels()}catch(error){toast(error.message)}});
  body.querySelectorAll('[data-remove]').forEach(button=>button.onclick=async()=>{if(!confirm('Remove this label? Emails stay intact. Scoped instructions will be disabled and automatic sending paused.'))return;try{await api('inbox/labels/'+button.dataset.remove,'DELETE');dialog.close();await showEmailReview();showInboxLabels()}catch(error){toast(error.message)}});
}
function showInboxInstructions(prefill=''){
  const dialog=inboxDialog('Business instructions'),body=dialog.querySelector('.inbox-dialog-body');
  body.innerHTML=`<p>These are approved business rules supplied to future agent executions, not model retraining. They never grant tool permissions. Existing drafts stay unchanged until regenerated.</p><div>${inboxState.instructions.map(r=>`<form data-id="${esc(r.id)}" data-revision="${r.revision}"><label>Instruction<textarea name="content" maxlength="1000" required>${esc(r.content)}</textarea></label><label>Applies to<select name="label_id">${labelOptions(r.label_id?[r.label_id]:[],true)}</select></label><label class="inbox-toggle"><input type="checkbox" name="active" ${r.active?'checked':''}> Active</label><div class="actions"><button>Save changes</button><button type="button" data-delete="${esc(r.id)}">Delete instruction</button></div></form>`).join('')}</div><h3>New instruction</h3><form><label>Instruction<textarea name="content" maxlength="1000" required placeholder="For late cancellation requests, explain our cancellation policy without promising a refund.">${esc(prefill)}</textarea></label><label>Applies to<select name="label_id">${labelOptions([],true)}</select></label><label class="inbox-toggle"><input type="checkbox" name="active" checked> Use for future emails</label><button class="primary">Save business instruction</button></form>`;
  body.querySelectorAll('form').forEach(form=>form.onsubmit=async e=>{e.preventDefault();try{await api('inbox/instructions'+(form.dataset.id?'/'+form.dataset.id:''),form.dataset.id?'PUT':'POST',{content:form.elements.content.value,label_id:form.elements.label_id.value||null,active:form.elements.active.checked,revision:Number(form.dataset.revision||0)});await refreshInboxData();dialog.close();toast('Business instruction saved. Existing drafts are unchanged.')}catch(error){toast(error.message)}});
  body.querySelectorAll('[data-delete]').forEach(button=>button.onclick=async()=>{if(!confirm('Delete this instruction for future runs?'))return;try{await api('inbox/instructions/'+button.dataset.delete,'DELETE');await refreshInboxData();dialog.close();toast('Instruction deleted.')}catch(error){toast(error.message)}});
}
