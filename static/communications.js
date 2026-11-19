'use strict';
const $=id=>document.getElementById(id);let token='',me=null,contacts=[],call=null,pc=null,stream=null,cursor=0,pending=[],timer=null,busy=false,starting=false,generation=0,facing='user';
const say=s=>$('status').textContent=s;
async function api(path,body,method='GET'){const r=await fetch('/api/connect'+path,{method,headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Request failed');return d}
const post=(p,b)=>api(p,b,'POST');
function closeMedia(){generation++;if(pc){pc.onicecandidate=null;pc.ontrack=null;pc.close()}pc=null;if(stream)stream.getTracks().forEach(t=>t.stop());stream=null;call=null;cursor=0;pending=[];starting=false;$('local').srcObject=null;$('remote').srcObject=null;$('call').hidden=true;$('mute').textContent='Mute';$('camera').textContent='Camera off';}
function display(c){$('call').hidden=false;const incoming=c.status==='ringing'&&c.callee===me.id;$('accept').hidden=!incoming;$('decline').hidden=!incoming;$('call-status').textContent=incoming?'Incoming '+c.kind+' call from '+(contacts.find(p=>p.id===c.caller)?.username||'colleague'):c.status==='ringing'?'Ringing…':'Connecting '+c.kind+' call…'}
async function refreshMessages(){const id=Number($('contact').value);if(!id)return;const rows=await api('/messages/'+id);if(Number($('contact').value)!==id)return;const box=$('messages');const text=rows.map(m=>(m.sender===me.id?'You':contacts.find(p=>p.id===m.sender)?.username||'Colleague')+': '+m.body).join('\n\n');if(box.textContent!==text){box.textContent=text;box.scrollTop=box.scrollHeight}}
async function startMedia(c){if(starting||pc)return;starting=true;const g=generation;try{if(!navigator.mediaDevices?.getUserMedia)throw Error('Camera and microphone require HTTPS or localhost');const cfg=await api('/ice-config');const media=await navigator.mediaDevices.getUserMedia({audio:true,video:c.kind==='video'?{facingMode:facing}:false});if(g!==generation){media.getTracks().forEach(t=>t.stop());return}stream=media;$('local').srcObject=stream;const conn=new RTCPeerConnection(cfg);pc=conn;stream.getTracks().forEach(t=>conn.addTrack(t,stream));conn.ontrack=e=>{$('remote').srcObject=e.streams[0]||new MediaStream([e.track]);};conn.onicecandidate=e=>{if(e.candidate&&g===generation)post('/calls/'+c.id+'/signals',{kind:'ice',payload:e.candidate.toJSON()}).catch(x=>say(x.message))};conn.onconnectionstatechange=()=>{if(g===generation)$('call-status').textContent='Call: '+conn.connectionState};if(c.caller===me.id){const offer=await conn.createOffer();await conn.setLocalDescription(offer);await post('/calls/'+c.id+'/signals',{kind:'offer',payload:{type:offer.type,sdp:offer.sdp}})}}catch(e){if(g===generation){say(e.message);try{await post('/calls/'+c.id+'/decision',{action:'end'})}catch{}closeMedia()}}finally{if(g===generation)starting=false}}
async function getSignals(c){const d=await api('/calls/'+c.id+'/signals?after='+cursor);if(!call||call.id!==c.id||!pc)return;if(d.status!=='accepted'){closeMedia();return}for(const s of d.signals){if(s.kind==='ice'){if(pc.remoteDescription)await pc.addIceCandidate(s.payload);else pending.push(s.payload)}else{await pc.setRemoteDescription(s.payload);for(const ice of pending)await pc.addIceCandidate(ice);pending=[];if(s.kind==='offer'){const a=await pc.createAnswer();await pc.setLocalDescription(a);await post('/calls/'+c.id+'/signals',{kind:'answer',payload:{type:a.type,sdp:a.sdp}})}}cursor=s.id}}
let knownOrders=null,orderSignature='';
async function refreshOrders(){
 const rows=await api('/orders');if(!token)return;
 const ids=new Set(rows.map(o=>o.id));
 if(knownOrders){const incoming=rows.filter(o=>!knownOrders.has(o.id));if(incoming.length)$('order-notice').textContent=incoming.length+' new work order(s) received.'}
 knownOrders=ids;
 const signature=JSON.stringify(rows);if(signature===orderSignature)return;
 orderSignature=signature;const root=$('my-orders');root.replaceChildren();
 for(const o of rows){
  const card=document.createElement('article');card.style.cssText='background:#1b2025;padding:14px;margin:8px 0;border-left:3px solid #ffb44e;border-radius:6px';
  const title=document.createElement('h3');title.textContent=o.title;card.append(title);
  const info=document.createElement('p');info.textContent='#'+o.id+' · '+o.priority+' · '+o.status+(o.due_date?' · Due '+o.due_date:'');card.append(info);
  const desc=document.createElement('p');desc.textContent=o.description;card.append(desc);
  if(o.status!=='Completed'){
   const start=document.createElement('button');start.textContent='Start';start.disabled=o.status==='In Progress';
   const finish=document.createElement('button');finish.textContent='Complete';finish.style.marginLeft='8px';
   const resolution=document.createElement('textarea');resolution.placeholder='Completion notes';resolution.maxLength=10000;resolution.style.cssText='display:block;width:95%;margin:10px 0;background:#252b31;color:white;padding:8px';
   resolution.value=o.resolution||'';
   async function update(status){try{if(status==='Completed'&&!resolution.value.trim())return say('Enter completion notes');start.disabled=finish.disabled=true;await api('/orders/'+o.id,{status,revision:o.revision,resolution:resolution.value},'PATCH');orderSignature='';await refreshOrders();say('Work order updated')}catch(e){say(e.message);start.disabled=o.status==='In Progress';finish.disabled=false}}
   start.onclick=()=>update('In Progress');finish.onclick=()=>update('Completed');card.append(resolution,start,finish)
  }else{const p=document.createElement('p');p.textContent=o.resolution||'';card.append(p)}
  root.append(card)
 }
 if(!rows.length)root.textContent='No assigned work orders.';
}
async function poll(){if(!token||busy)return;busy=true;try{const calls=await api('/calls');if(!token)return;const c=calls[0];if(!c){if(call){closeMedia();say('Call ended')}}else{if(call&&call.id!==c.id)closeMedia();if(!call){call=c;display(c)}else{const changed=call.status!==c.status;call=c;if(changed)display(c)}if(c.status==='accepted'){await startMedia(c);if(pc&&call?.id===c.id)await getSignals(c)}}await refreshOrders();await refreshMessages()}catch(e){say(e.message)}finally{busy=false}}
$('login').onsubmit=async e=>{e.preventDefault();try{const d=await post('/login',Object.fromEntries(new FormData(e.currentTarget)));token=d.token;const c=await api('/contacts');me=c.me;contacts=c.contacts;$('contact').replaceChildren(...contacts.map(p=>new Option(p.username,p.id)));$('identity').textContent='Signed in as '+me.username;$('login').reset();$('login').hidden=true;$('workspace').hidden=false;clearInterval(timer);timer=setInterval(poll,1200);poll()}catch(e){token='';say(e.message)}};
$('contact').onchange=()=>refreshMessages().catch(e=>say(e.message));
$('compose').onsubmit=async e=>{e.preventDefault();const id=Number($('contact').value);if(!id)return say('Choose a contact');try{await post('/messages',{recipient:id,body:e.currentTarget.elements.body.value});e.currentTarget.reset();await refreshMessages()}catch(e){say(e.message)}};
async function dial(kind){const id=Number($('contact').value);if(!id)return say('Choose a contact');try{await post('/calls',{recipient:id,kind});await poll()}catch(e){say(e.message)}}
$('voice').onclick=()=>dial('voice');$('video').onclick=()=>dial('video');
async function decision(action){if(!call)return;try{await post('/calls/'+call.id+'/decision',{action});if(action!=='accept')closeMedia();await poll()}catch(e){say(e.message)}}
$('accept').onclick=()=>decision('accept');$('decline').onclick=()=>decision('decline');$('hangup').onclick=()=>decision('end');
$('mute').onclick=()=>{const t=stream?.getAudioTracks()[0];if(t){t.enabled=!t.enabled;$('mute').textContent=t.enabled?'Mute':'Unmute'}};
$('camera').onclick=()=>{const t=stream?.getVideoTracks()[0];if(t){t.enabled=!t.enabled;$('camera').textContent=t.enabled?'Camera off':'Camera on'}};
$('flip').onclick=async()=>{const old=stream?.getVideoTracks()[0];if(!old||!pc)return;try{const g=generation;const next=facing==='user'?'environment':'user';const m=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:next}},audio:false});const track=m.getVideoTracks()[0];if(g!==generation){track.stop();return}const sender=pc.getSenders().find(s=>s.track===old);if(!sender){track.stop();return}await sender.replaceTrack(track);if(g!==generation){track.stop();return}stream.removeTrack(old);old.stop();stream.addTrack(track);facing=next;$('local').srcObject=stream}catch(e){say(e.message)}};
$('logout').onclick=async()=>{clearInterval(timer);if(call)try{await post('/calls/'+call.id+'/decision',{action:'end'})}catch{}try{await post('/logout',{})}catch{}closeMedia();token='';me=null;knownOrders=null;orderSignature='';$('my-orders').replaceChildren();$('order-notice').textContent='';$('workspace').hidden=true;$('login').hidden=false;$('messages').textContent='';say('Signed out')};
window.addEventListener('pagehide',()=>{clearInterval(timer);closeMedia()});
