'use strict';
// Draft capture only; this page never publishes knowledge to Ask Brain.
(function(){
  tabNames.twin='Building Map';
  const systems=['Plumbing','Electrical','HVAC','Fire protection','Structural','Building automation','Appliances','General'];
  const relations=['feeds','serves','controls','drains_to','connects_to','located_in','monitors','part_of'];
  const option=(value,label)=>'<option value="'+esc(value)+'">'+esc(label)+'</option>';
  const select=(name,label,opts)=>'<label>'+esc(label)+'<select name="'+name+'">'+opts.join('')+'</select></label>';
  const input=(name,label,required=false,type='text')=>'<label>'+esc(label)+'<input name="'+name+'" type="'+type+'" '+(required?'required':'')+'></label>';
  const area=(name,label,required=false)=>'<label>'+esc(label)+'<textarea name="'+name+'" '+(required?'required':'')+'></textarea></label>';
  const optId=v=>v?Number(v):null;
  function evidence(data,pid){
    return select('source_kind','Evidence type',[option('field','Technician observation'),option('schematic','Existing schematic')])+
      area('source_reference','Source / observation details, who observed it and when',true)+
      select('drawing_id','Schematic (only for schematic evidence)',[option('','None'),...data.drawings.map(d=>option(d.id,d.name))])+
      input('page','Drawing page (optional)',false,'number')+
      select('note_id','Existing field note / photo (field evidence only)',[option('','None'),...state.notes.filter(n=>n.property_id===pid).map(n=>option(n.id,'#'+n.id+' '+String(n.text||'Photo').slice(0,70)))]);
  }
  function bindEvidence(form){
    const sync=()=>{const schematic=form.elements.source_kind.value==='schematic';
      for(const k of ['drawing_id','page']){form.elements[k].disabled=!schematic;if(!schematic)form.elements[k].value=''}
      form.elements.drawing_id.required=schematic;
      form.elements.note_id.disabled=schematic;if(schematic)form.elements.note_id.value='';
    };form.elements.source_kind.onchange=sync;sync();
  }
  function evidenceValues(v){return {source_kind:v.source_kind,source_reference:v.source_reference,drawing_id:optId(v.drawing_id),page:optId(v.page),note_id:optId(v.note_id)}}
  async function load(root,pid){
    const current=()=>root.isConnected&&state.property===pid&&state.tab==='twin';
    try{
      const data=await api('/twin?property_id='+pid);if(!current())return;
      const names=new Map(data.components.map(c=>[c.id,c.name]));
      const components=data.components.map(c=>'<article class="item-card"><div><h3>'+esc(c.name)+'</h3><p>'+esc(c.system+' · '+c.component_type+' · '+c.location)+'</p><p>'+esc(c.source_reference)+'</p></div><span class="tag">Draft</span></article>').join('');
      const links=data.links.map(l=>'<article class="item-card"><div><h3>'+esc(names.get(l.from_id)||'?')+' → '+esc(names.get(l.to_id)||'?')+'</h3><p>'+esc(l.relation+' · '+l.source_reference)+'</p></div><span class="tag">Draft</span></article>').join('');
      root.innerHTML='<section class="panel"><h2>Upload an existing schematic</h2><form id="twin-upload"><input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg" required><button class="btn primary">Save source drawing</button></form><div class="row-list">'+data.drawings.map(d=>'<a href="/api/twin/drawings/'+d.id+'?property_id='+pid+'">'+esc(d.name)+'</a>').join('')+'</div></section>'+
        '<section class="panel"><h2>Teach Brain — record a component</h2><form id="twin-component" class="form-grid">'+input('name','Component name',true)+select('system','Building system',systems.map(s=>option(s,s)))+input('component_type','Type (valve, panel, room, pump…)',true)+input('location','Exact location')+area('description','Observed details')+select('asset_id','Related equipment',[option('','None'),...state.assets.filter(a=>a.property_id===pid).map(a=>option(a.id,a.name))])+evidence(data,pid)+'<button class="btn primary">Save draft component</button></form></section>'+
        '<section class="panel"><h2>Teach Brain — record a connection</h2><form id="twin-link" class="form-grid">'+select('from_id','From component',[option('','Select'),...data.components.map(c=>option(c.id,c.name))])+select('relation','Relationship',relations.map(r=>option(r,r)))+select('to_id','To component',[option('','Select'),...data.components.map(c=>option(c.id,c.name))])+area('description','Connection details')+evidence(data,pid)+'<button class="btn primary" '+(data.components.length<2?'disabled':'')+'>Save draft connection</button></form></section>'+
        '<section class="panel"><h2>Draft components ('+data.components.length+')</h2><div class="row-list">'+(components||'<p>No components recorded.</p>')+'</div></section><section class="panel"><h2>Draft connections ('+data.links.length+')</h2><div class="row-list">'+(links||'<p>No connections recorded.</p>')+'</div></section>';
      const bind=(id,fn)=>{const f=root.querySelector('#'+id);f.onsubmit=async e=>{e.preventDefault();const b=f.querySelector('button');b.disabled=true;try{await fn(new FormData(f));toast('Draft saved');if(current())await load(root,pid)}catch(err){toast(err.message)}finally{b.disabled=false}};return f};
      bind('twin-upload',fd=>{fd.append('property_id',pid);return api('/twin/drawings',{method:'POST',body:fd})});
      bindEvidence(bind('twin-component',fd=>{const v=Object.fromEntries(fd);return api('/twin/components?property_id='+pid,json('POST',{...evidenceValues(v),name:v.name,system:v.system,component_type:v.component_type,location:v.location,description:v.description,asset_id:optId(v.asset_id)}))}));
      bindEvidence(bind('twin-link',fd=>{const v=Object.fromEntries(fd);if(!v.from_id||!v.to_id)throw Error('Choose both components');return api('/twin/links?property_id='+pid,json('POST',{...evidenceValues(v),from_id:Number(v.from_id),to_id:Number(v.to_id),relation:v.relation,description:v.description}))}));
    }catch(e){if(current())root.textContent=e.message}
  }
  views.twin=()=>{const pid=state.property;queueMicrotask(()=>{const root=document.querySelector('#twin-root');if(root&&state.property===pid&&state.tab==='twin')load(root,pid)});return '<div class="section-heading"><div><h2>Living Building Map</h2><p>Capture schematics and technician observations.</p></div></div><p class="hint">Draft workspace. Nothing entered here is approved or used by Ask Brain. Technical review and individual permissions are required before publication.</p><div id="twin-root">Loading building map…</div>'};
})();
