'use strict';
const $ = (id) => document.getElementById(id);
const state = { overview: null, property: '', building: '', view: 'overview' };
const titles = { overview:'Operations overview', ask:'Ask Building Brain', documents:'Reference library', assets:'Equipment registry', notes:'Field knowledge', buildings:'Buildings & templates' };

async function api(url, opts={}) {
  const isForm=opts.body instanceof FormData;
  const headers = isForm ? {} : (opts.body ? {'Content-Type':'application/json'} : {});
  const response=await fetch(url,{...opts,headers:{...headers,...opts.headers}});
  if (!response.ok) {
    let msg=`Request failed (${response.status})`;
    try {const value=await response.json(); msg=typeof value.detail==='string'? value.detail:msg;} catch{}
    throw new Error(msg);
  }
  if(response.status===204)return null;
  return response.json();
}
function toast(message, error=false) {
  const area=$('toast'); area.textContent=message; area.className=error?'show error':'show';
  clearTimeout(toast.timeout); toast.timeout=setTimeout(()=>area.className='',5500);
}
function text(tag,contents,cls='') {
  const node=document.createElement(tag); if(cls)node.className=cls; node.textContent=String(contents ?? '');return node;
}
function empty(container,label) {container.replaceChildren(text('div',label,'empty'));}
function pill(value,cls=''){return text('span',value,`pill ${cls}`);}
function formatDate(iso){if(!iso)return '—';return String(iso).slice(0,10);}
function show(view) {
  state.view=view;
  for (const b of document.querySelectorAll('#nav button')) b.classList.toggle('active',b.dataset.view===view);
  for (const p of document.querySelectorAll('.view')) p.classList.toggle('active',p.dataset.panel===view);
  $('view-title').textContent=titles[view];
  window.scrollTo({top:0,behavior:'instant'});
  refreshView().catch(e=>toast(e.message,true));
}
function currentProperty(){return Number(state.property)||null;}
function currentBuilding(){return Number(state.building)||null;}
function buildingsForProperty(){return (state.overview?.buildings||[]).filter(b=>b.property_id===currentProperty());}
function labelBuilding(id){return state.overview?.buildings.find(b=>b.id===id)?.name || 'Unknown building';}
function fillSelect(select,values,first=null,preferred=null){
  const keep=preferred!==null?String(preferred):select.value;
  select.replaceChildren();
  if(first){const opt=new Option(first.label,first.value);select.add(opt);}
  for(const val of values){select.add(new Option(val.label,String(val.value)));}
  const has=Array.from(select.options).some(o=>o.value===keep);
  if(has)select.value=keep;
}
async function refreshOverview(){
  const previousProperty=state.property;
  const previousBuilding=state.building;
  state.overview=await api('/api/overview');
  const properties=state.overview.properties;
  fillSelect($('property-select'),properties.map(x=>({value:x.id,label:x.name})),properties.length?null:{value:'',label:'Create a property first'},previousProperty||null);
  state.property=$('property-select').value||'';
  const buildings=buildingsForProperty();
  fillSelect($('building-select'),buildings.map(b=>({value:b.id,label:b.name})),{value:'',label:'Entire property'},previousBuilding||'');
  state.building=$('building-select').value;
  fillScopeOptions();
  renderStats();
}
function fillScopeOptions(){
  const buildingOptions=buildingsForProperty().map(b=>({value:b.id,label:b.name}));
  fillSelect($('upload-scope'),buildingOptions,{value:'',label:'Entire property (shared)' });
  fillSelect($('building-template'),buildingOptions,{value:'',label:'None — reference building'});
  for(const id of ['asset-building','note-building','exception-building']){
    fillSelect($(id),buildingOptions,null,state.building||null);
  }
}
function renderStats(){
  const stats=state.overview.stats;
  const items=[['PROPERTIES',stats.properties,'▦'],['BUILDINGS',stats.buildings,'⌂'],['REFERENCE DOCUMENTS',stats.documents,'▤'],['PENDING REVIEWS',stats.pending_reviews,'✎']];
  $('stats').replaceChildren(...items.map(([label,value,icon])=>{
    const block=document.createElement('div');block.className='stat';
    block.append(text('span',icon,'stat-icon'),text('div',value,'stat-value'),text('div',label,'stat-label'));return block;
  }));
  $('stats-subtitle').textContent='Entire workspace';
  $('mode-badge').textContent=state.overview.ai_mode==='none'?'SOURCE SEARCH':`AI: ${state.overview.ai_mode.toUpperCase()}`;
}
async function refreshView(){
  if(state.view==='documents')await renderDocuments();
  if(state.view==='assets')await renderAssets();
  if(state.view==='notes')await renderReviewList('notes');
  if(state.view==='buildings'){renderBuildings();await renderReviewList('exceptions');}
}
async function renderDocuments(){
  const container=$('document-list');
  if(!currentProperty()){empty(container,'Create a property to start your reference library.');$('doc-count').textContent='0 DOCUMENTS';return;}
  const rows=await api(`/api/documents?property_id=${currentProperty()}${currentBuilding()?`&building_id=${currentBuilding()}`:''}`);
  $('doc-count').textContent=`${rows.length} DOCUMENTS`;
  if(!rows.length){empty(container,'No documents yet. Upload a text PDF, DOCX, TXT, MD or CSV.');return;}
  container.replaceChildren(...rows.map(row=>{
    const block=text('div','','record');const head=text('div','','record-head');
    const info=document.createElement('div');info.append(text('h4',row.filename),text('div',row.building_name||'Shared across property','record-meta'));
    head.append(info,pill(row.kind.replace('.','').toUpperCase()));block.append(head);
    block.append(text('div',`${row.pages||'—'} PDF pages · ${Math.ceil(row.size_bytes/1024)} KB · indexed ${formatDate(row.created_at)}`,'record-meta'));
    const ctr=text('div','','record-controls'); const link=text('a','Open original ↗');link.href=`/api/documents/${row.id}/file`;link.target='_blank';link.rel='noopener';ctr.append(link);
    const del=text('button','Remove','mini-button danger');del.type='button';del.addEventListener('click',async()=>{
      if(!confirm(`Delete ${row.filename} and its indexed passages?`))return;
      await action(async()=>{await api(`/api/documents/${row.id}`,{method:'DELETE'}); await refreshOverview();await renderDocuments();},'Document removed.');
    });ctr.append(del);block.append(ctr);return block;
  }));
}
async function renderAssets(){
  const container=$('asset-list');
  if(!currentProperty()){empty(container,'Create a property and building first.');$('asset-count').textContent='0 ASSETS';return;}
  const rows=await api(`/api/assets?property_id=${currentProperty()}${currentBuilding()?`&building_id=${currentBuilding()}`:''}`);
  $('asset-count').textContent=`${rows.length} ASSETS`;
  if(!rows.length){empty(container,'No equipment added for this scope.');return;}
  container.replaceChildren(...rows.map(row=>{
    const node=text('div','','record');const head=text('div','','record-head');head.append(text('h4',row.name),pill(row.inherited?'Template reference':row.system||'Asset',row.inherited?'inherited':''));node.append(head);
    node.append(text('div',`${row.building_name} · ${row.location||'Location not recorded'}`,'record-meta'));
    const details=[row.model&&`Model: ${row.model}`,row.serial&&`Serial: ${row.serial}`,row.warranty_until&&`Warranty: ${row.warranty_until}`].filter(Boolean);
    if(details.length)node.append(text('p',details.join(' · ')));
    if(row.notes)node.append(text('p',row.notes));return node;
  }));
}
async function renderReviewList(kind){
  const target=$(kind==='notes'?'note-list':'exception-list');
  if(!currentProperty()){empty(target,'Create a property before recording observations.');return;}
  const rows=await api(`/api/${kind}?property_id=${currentProperty()}${currentBuilding()?`&building_id=${currentBuilding()}`:''}`);
  if(!rows.length){empty(target,kind==='notes'?'No field notes yet.':'No building exceptions yet.');return;}
  target.replaceChildren(...rows.map(row=>{
    const node=text('div','','record');const head=text('div','','record-head');head.append(text('h4',row.title||row.label),pill(row.status,row.status));node.append(head);
    node.append(text('div',`${row.building_name} · ${row.author} · ${formatDate(row.created_at)}`,'record-meta'));
    node.append(text('p',row.body||row.details));
    if(row.status==='pending'){
      const ctr=text('div','','record-controls');
      for(const status of ['approved','rejected']){
        const btn=text('button',status==='approved'?'Approve & index':'Reject',status==='rejected'?'mini-button danger':'mini-button');btn.type='button';
        btn.addEventListener('click',()=>action(async()=>{await api(`/api/${kind}/${row.id}/review`,{method:'POST',body:JSON.stringify({status})});await refreshOverview();await renderReviewList(kind);},`Item ${status}.`));ctr.append(btn);
      }node.append(ctr);
    }
    return node;
  }));
}
function renderBuildings(){
  const target=$('building-list');const buildings=buildingsForProperty();
  if(!currentProperty()){empty(target,'Create your first property above.');return;}
  if(!buildings.length){empty(target,'No buildings yet. Add a reference building above.');return;}
  target.replaceChildren(...buildings.map(row=>{
    const node=text('div','','building-row');
    const left=text('div');left.append(text('b',row.name));left.append(text('div',row.template_id?`Inherits from ${labelBuilding(row.template_id)} — verify exceptions`:'Reference building · own records','record-meta'));
    node.append(left,pill(row.template_id?'Template-linked':'Reference'));return node;
  }));
}
async function action(task,success){
  try{await task();toast(success);}catch(e){toast(e.message,true);}
}
function bindForm(id,handler){$(id).addEventListener('submit',e=>{e.preventDefault(); action(handler,'Saved successfully.');});}
async function askQuestion(){
  if(!currentProperty())throw new Error('Create a property first.');
  const question=$('question').value.trim();if(!question)throw new Error('Enter your question.');
  const button=$('ask-submit');button.disabled=true;button.textContent='Searching references…';
  const output=$('ask-output');empty(output,'Searching indexed sources…');
  try{
    const data=await api('/api/ask',{method:'POST',body:JSON.stringify({property_id:currentProperty(),building_id:currentBuilding(),question})});
    output.replaceChildren();
    const answer=text('article','','panel answer-panel');
    answer.append(text('div',data.mode==='search'?'SOURCE RETRIEVAL · NO GENERATIVE AI':'AI SYNTHESIS · SOURCE GROUNDED','answer-meta'));
    answer.append(text('div',data.answer,'answer-copy'));
    if(data.ai_error)answer.append(text('div',data.ai_error,'warning'));
    answer.append(text('div',data.safety_note,'warning'));output.append(answer);
    const sources=text('article','','panel answer-panel');sources.append(text('h3',`References (${data.citations.length})`));
    const list=text('div','','citations');
    if(!data.citations.length)list.append(text('div','No references matched.','empty'));
    for(const cite of data.citations){
      const node=text('div','','cite');const title=text('div','','cite-title');title.append(text('span',`[${cite.reference}] ${cite.source_label}`));
      if(cite.document_id){const link=text('a','Open original ↗');link.href=`/api/documents/${cite.document_id}/file`;link.target='_blank';link.rel='noopener';title.append(link);}
      node.append(title);
      node.append(text('div',`${cite.scope}${cite.page_number?` · Page ${cite.page_number}`:''}${cite.building_name?` · ${cite.building_name}`:''}`,'cite-meta'));
      node.append(text('div',cite.excerpt,'cite-body'));list.append(node);
    }sources.append(list);output.append(sources);
  }finally{button.disabled=false;button.textContent='Search references ↗';}
}

async function start(){
  document.querySelectorAll('nav button').forEach(b=>b.addEventListener('click',()=>show(b.dataset.view)));
  document.querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>show(b.dataset.go)));
  document.querySelectorAll('[data-question]').forEach(b=>b.addEventListener('click',()=>{$('question').value=b.dataset.question;$('question').focus();}));
  $('property-select').addEventListener('change',()=>{state.property=$('property-select').value;state.building=''; const bs=buildingsForProperty();fillSelect($('building-select'),bs.map(x=>({value:x.id,label:x.name})),{value:'',label:'Entire property'},'');fillScopeOptions();refreshView().catch(e=>toast(e.message,true));});
  $('building-select').addEventListener('change',()=>{state.building=$('building-select').value;fillScopeOptions();refreshView().catch(e=>toast(e.message,true));});
  bindForm('property-form',async()=>{
    const result=await api('/api/properties',{method:'POST',body:JSON.stringify({name:$('property-name').value,description:$('property-description').value})});
    state.property=String(result.id);state.building=''; $('property-form').reset();await refreshOverview();renderBuildings();await renderReviewList('exceptions');
  });
  bindForm('building-form',async()=>{
    if(!currentProperty())throw new Error('Create a property first.');
    const result=await api('/api/buildings',{method:'POST',body:JSON.stringify({property_id:currentProperty(),name:$('building-name').value,template_id:Number($('building-template').value)||null})});
    state.building=String(result.id);$('building-form').reset();await refreshOverview();renderBuildings();await renderReviewList('exceptions');
  });
  bindForm('upload-form',async()=>{
    if(!currentProperty())throw new Error('Create a property first.');
    const file=$('upload-file').files[0];if(!file)throw new Error('Select a reference file.');
    const data=new FormData();data.append('file',file);data.append('property_id',currentProperty());data.append('building_id',$('upload-scope').value);
    const result=await api('/api/documents/upload',{method:'POST',body:data});
    $('upload-form').reset();await refreshOverview();await renderDocuments();toast(`${result.chunks} searchable passages indexed from ${result.filename}.`);
  });
  bindForm('asset-form',async()=>{
    if(!currentProperty())throw new Error('Create a property first.');
    const body={property_id:currentProperty(),building_id:Number($('asset-building').value),name:$('asset-name').value,system:$('asset-system').value,model:$('asset-model').value,serial:$('asset-serial').value,location:$('asset-location').value,notes:$('asset-notes').value,warranty_until:$('asset-warranty').value};
    await api('/api/assets',{method:'POST',body:JSON.stringify(body)});$('asset-form').reset();await refreshOverview();await renderAssets();
  });
  bindForm('note-form',async()=>{
    if(!currentProperty())throw new Error('Create a property first.');
    await api('/api/notes',{method:'POST',body:JSON.stringify({property_id:currentProperty(),building_id:Number($('note-building').value),title:$('note-title').value,body:$('note-body').value,author:$('note-author').value})});$('note-form').reset();await refreshOverview();await renderReviewList('notes');
  });
  bindForm('exception-form',async()=>{
    if(!currentProperty())throw new Error('Create a property first.');
    await api('/api/exceptions',{method:'POST',body:JSON.stringify({property_id:currentProperty(),building_id:Number($('exception-building').value),label:$('exception-label').value,details:$('exception-details').value,author:$('exception-author').value})});$('exception-form').reset();await refreshOverview();await renderReviewList('exceptions');
  });
  $('ask-form').addEventListener('submit',e=>{e.preventDefault();action(askQuestion,'Search complete.');});
  await refreshOverview();renderBuildings();
}
start().catch(e=>toast(e.message,true));
