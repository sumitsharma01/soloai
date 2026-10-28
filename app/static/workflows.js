/* A bounded block editor. Saved drafts never rewrite published definitions. */
let flowEditor=null;
const flowKinds={trigger:'Manual trigger',ai_task:'AI task',tool:'Approved tool',condition:'Condition',approval:'Approval',handoff:'Human handoff'};
function mountWorkflows(){
 const button=document.createElement('button');button.textContent='◇ Custom flows · Preview';button.onclick=showWorkflows;document.querySelector('.nav').append(button);
 const preview=document.querySelector('.flow-preview');if(preview){preview.innerHTML='<div class="eyebrow">CUSTOM FLOWS · PREVIEW</div><h2>Build a small automation</h2><p>Combine tasks, rules and approvals. Test a draft before publishing and enabling it.</p><button class="primary" id="open-flow-builder">Open workflow builder →</button><p>Manual triggers and internal review tasks. No external writes or scheduled runs.</p>';document.querySelector('#open-flow-builder').onclick=showWorkflows;}
}
function flowPage(title){
 if(typeof voiceCleanup==='function')voiceCleanup();
 document.querySelector('.content').classList.remove('inbox-mode');const notice=document.querySelector('.content > .notice');if(notice)notice.hidden=true;
 document.querySelector('.heading h1').textContent=title;document.querySelector('.heading p').textContent='Test → Publish → Enable. Your rules, one step at a time.';
 document.querySelector('.main header span').textContent='Workspace / Custom flows';
 const page=document.querySelector('#page');page.innerHTML='<section class="panel" role="status">Loading…</section>';return page;
}
async function showWorkflows(){
 const page=flowPage('Custom flows');
 try{const state=await api('workflows');if(!page.isConnected)return;
 page.innerHTML=`<section class="panel"><h2>A small workflow, built around your task</h2><p>This preview supports manual starts, AI text tasks, internal review tasks, text conditions, approvals and human handoffs. Maximum twelve steps and three AI tasks. AI tests use your Azure token allowance.</p><p>Run inputs, AI outputs and review tasks are stored until removed by the operator. Use synthetic data for this preview.</p><button class="primary" id="flow-new">Create from template</button>${!state.ai_available?'<p class="notice">AI tasks need the operator’s direct Azure chat-model connection. Other blocks can still be tested.</p>':''}</section><div class="agents">${state.flows.map(f=>`<article class="card"><h2>${esc(JSON.parse(f.draft).name)}</h2><p>Draft ${f.revision} · Published ${f.published||'none'}</p><span class="chip">${f.enabled?'Enabled':'Disabled'}</span><div class="actions"><button data-edit-flow="${esc(f.id)}">Open workflow →</button></div></article>`).join('')}</div><section class="panel"><h2>Internal review tasks</h2>${state.tasks.map(t=>`<details><summary>${esc(t.title)}</summary><p>${esc(t.content)}</p><small>Run ${esc(t.run)}</small></details>`).join('')||'<p>No live tasks created yet. Test runs never create these tasks.</p>'}</section>`;
 document.querySelector('#flow-new').onclick=async()=>{try{const r=await api('workflows','POST',state.template);await openWorkflow(r.id)}catch(e){toast(e.message)}};
 page.querySelectorAll('[data-edit-flow]').forEach(b=>b.onclick=()=>openWorkflow(b.dataset.editFlow));
 }catch(e){page.textContent=e.message;}
}
async function openWorkflow(id){
 const page=flowPage('Workflow builder');
 try{const state=await api('workflows');const row=state.flows.find(f=>f.id===id);if(!row)throw Error('Workflow not found.');
 flowEditor={...row,definition:JSON.parse(row.draft),dirty:false};drawFlow();
 }catch(e){page.textContent=e.message;}
}
function drawFlow(){
 const f=flowEditor,page=document.querySelector('#page');
 page.innerHTML=`<section class="panel"><button id="flow-back">← All workflows</button><label>Workflow name<input id="flow-name" maxlength="100" value="${esc(f.definition.name)}"></label><p>Draft ${f.revision} · Published ${f.published||'none'} · ${f.enabled?'Enabled':'Disabled'}</p><div class="actions"><button id="flow-save">Save draft</button><button id="flow-publish" ${f.tested===f.revision&&!f.dirty?'':'disabled'}>Publish tested draft</button><button id="flow-enable" ${f.published?'':'disabled'}>${f.enabled?'Disable':'Enable'} published version</button></div><p id="flow-draft-status" role="status">${f.dirty?'Unsaved changes. Save before testing.':'Editing this draft does not change published runs.'}</p></section>
 <section class="panel"><h2>Your workflow</h2><p>Steps run top to bottom. A condition continues only if the current text contains its match phrase; otherwise the run ends. Approvals and handoffs wait for a decision in SoloAI.</p><div class="workflow-blocks">${f.definition.blocks.map((b,i)=>`<article class="workflow-block"><div class="sectionhead"><strong>${i+1}. ${flowKinds[b.kind]}</strong>${i?`<div><button data-flow-up="${i}" ${i===1?'disabled':''} aria-label="Move step ${i+1} up">↑</button><button data-flow-remove="${i}" aria-label="Remove step ${i+1}">Remove</button></div>`:''}</div><label>Label<input data-flow-label="${i}" maxlength="80" value="${esc(b.label)}"></label>${['ai_task','condition'].includes(b.kind)?`<label>${b.kind==='condition'?'Text to match (case insensitive)':'Task instructions'}<textarea data-flow-instruction="${i}" maxlength="2000" rows="3">${esc(b.instruction||'')}</textarea></label>`:''}${b.kind==='tool'?'<p>Approved capability: create an internal review task using the current text. No email, booking or external-system write.</p>':''}${b.kind==='trigger'?'<p>Started manually by a signed-in workspace owner.</p>':''}</article>`).join('<div class="workflow-arrow" aria-hidden="true">↓</div>')}</div><div class="actions"><select id="flow-add-kind" aria-label="Block type">${Object.entries(flowKinds).filter(([k])=>k!=='trigger').map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select><button id="flow-add" ${f.definition.blocks.length>=12?'disabled':''}>Add block</button></div></section>
 <section class="panel"><h2>Run and inspect</h2><label>Input<textarea id="flow-input" maxlength="2000" rows="3" placeholder="Use a sample business request"></textarea></label><p>Tests call the real AI model but simulate the internal task write. Approval and handoff decisions are still required.</p><div class="actions"><button id="flow-test" ${f.dirty?'disabled':''}>Test saved draft</button><button id="flow-live" ${f.enabled?'':'disabled'}>Run published version</button><button id="flow-history">Refresh run history</button></div><div id="flow-runs"></div><div id="flow-run-detail"></div></section>`;
 document.querySelector('#flow-back').onclick=showWorkflows;
 const dirty=()=>{f.dirty=true;document.querySelector('#flow-test').disabled=true;document.querySelector('#flow-publish').disabled=true;document.querySelector('#flow-draft-status').textContent='Unsaved changes. Save before testing.';};
 document.querySelector('#flow-name').oninput=e=>{f.definition.name=e.target.value;dirty()};
 page.querySelectorAll('[data-flow-label]').forEach(e=>e.oninput=()=>{f.definition.blocks[Number(e.dataset.flowLabel)].label=e.value;dirty()});
 page.querySelectorAll('[data-flow-instruction]').forEach(e=>e.oninput=()=>{f.definition.blocks[Number(e.dataset.flowInstruction)].instruction=e.value;dirty()});
 page.querySelectorAll('[data-flow-remove]').forEach(e=>e.onclick=()=>{f.definition.blocks.splice(Number(e.dataset.flowRemove),1);f.dirty=true;drawFlow()});
 page.querySelectorAll('[data-flow-up]').forEach(e=>e.onclick=()=>{const i=Number(e.dataset.flowUp);[f.definition.blocks[i-1],f.definition.blocks[i]]=[f.definition.blocks[i],f.definition.blocks[i-1]];f.dirty=true;drawFlow()});
 document.querySelector('#flow-add').onclick=()=>{const kind=document.querySelector('#flow-add-kind').value;f.definition.blocks.push({kind,label:flowKinds[kind],instruction:''});f.dirty=true;drawFlow()};
 document.querySelector('#flow-save').onclick=async()=>{try{await api('workflows/'+f.id,'PUT',{...f.definition,revision:f.revision});await openWorkflow(f.id);toast('Draft saved. Test it before publishing.')}catch(e){toast(e.message)}};
 document.querySelector('#flow-publish').onclick=async()=>{try{await api('workflows/'+f.id+'/publish','POST',{revision:f.revision});await openWorkflow(f.id);toast('Published. Enable this version when ready.')}catch(e){toast(e.message)}};
 document.querySelector('#flow-enable').onclick=async()=>{try{await api('workflows/'+f.id+'/enable','POST',{enabled:!f.enabled,version:f.published});await openWorkflow(f.id)}catch(e){toast(e.message)}};
 const run=async(test)=>{const content=document.querySelector('#flow-input').value;if(!content.trim()){toast('Enter sample input first.');return;}const button=document.querySelector(test?'#flow-test':'#flow-live');button.disabled=true;
 try{const r=await api('workflows/'+f.id+'/runs','POST',{key:crypto.randomUUID(),content,test});await showFlowRun(r.id);await flowHistory()}catch(e){toast(e.message);await flowHistory()}finally{button.disabled=false;}};
 document.querySelector('#flow-test').onclick=()=>run(true);document.querySelector('#flow-live').onclick=()=>run(false);document.querySelector('#flow-history').onclick=flowHistory;flowHistory();
}
async function flowHistory(){
 const target=document.querySelector('#flow-runs');if(!target)return;
 try{const rows=await api('workflows/'+flowEditor.id+'/runs');if(!target.isConnected)return;target.innerHTML='<h3>Recent runs</h3>'+rows.map(r=>`<p><button data-flow-run="${esc(r.id)}">${r.test?'Test':'Live'} v${r.version} · ${esc(r.status)} · ${esc(new Date(r.created*1000).toLocaleString())}</button></p>`).join('');target.querySelectorAll('[data-flow-run]').forEach(b=>b.onclick=()=>showFlowRun(b.dataset.flowRun));}catch(e){toast(e.message)}
}
async function showFlowRun(id){
 const target=document.querySelector('#flow-run-detail');if(!target)return;
 try{const r=await api('workflows/runs/'+id);if(!target.isConnected)return;
 target.innerHTML=`<h3>${r.test?'Test':'Live'} run · ${esc(r.status)}</h3><p>Version ${r.version} · ${esc(r.id)}</p>${r.steps.map(s=>`<details open><summary>Step ${s.position+1} · ${esc(s.status)}</summary><pre class="workflow-output">${esc(s.output)}</pre></details>`).join('')}<div class="actions">${['WAITING_APPROVAL','NEEDS_HUMAN'].includes(r.status)?'<button id="flow-approve">Approve / complete handoff</button><button id="flow-reject">Reject and stop</button>':''}${['READY','RUNNING'].includes(r.status)?'<button id="flow-resume">Resume / check interrupted run</button>':''}<button id="flow-run-refresh">Refresh result</button></div>`;
 document.querySelector('#flow-run-refresh').onclick=()=>showFlowRun(id);
 for(const [selector,approved] of [['#flow-approve',true],['#flow-reject',false]]){const button=document.querySelector(selector);if(button)button.onclick=async()=>{button.disabled=true;try{await api('workflows/runs/'+id+'/decision','POST',{approved});await showFlowRun(id);await flowHistory()}catch(e){toast(e.message);button.disabled=false;}};}
 const resume=document.querySelector('#flow-resume');if(resume)resume.onclick=async()=>{try{await api('workflows/runs/'+id+'/resume','POST',{});await showFlowRun(id)}catch(e){toast(e.message)}};
 if(r.test&&r.status==='COMPLETED'&&r.version===flowEditor.revision&&!flowEditor.dirty){flowEditor.tested=r.version;document.querySelector('#flow-publish').disabled=false;}
 }catch(e){toast(e.message)}
}
