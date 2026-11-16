import React, {useState} from 'react';
import {SafeAreaView, ScrollView, View, Text, TextInput, Pressable, StyleSheet, Alert} from 'react-native';
import {CameraView, useCameraPermissions} from 'expo-camera';

type RecordRow = {id:number; name?:string; title?:string; status?:string; description?:string; location?:string; model?:string; serial?:string; notes?:string; next_due?:string; building_id?:number; property_id?:number; role?:string};
type Session = {url:string; auth:string};
const fg='/api/mobile/properties/';
export default function App(){
 const [url,setUrl]=useState(''); const [user,setUser]=useState('admin'); const [password,setPassword]=useState('');
 const [session,setSession]=useState<Session|null>(null); const [properties,setProperties]=useState<RecordRow[]>([]);
 const [property,setProperty]=useState<RecordRow|null>(null); const [tab,setTab]=useState('Work orders');
 const [rows,setRows]=useState<RecordRow[]>([]); const [question,setQuestion]=useState(''); const [answer,setAnswer]=useState('');
 const [busy,setBusy]=useState(false); const [scan,setScan]=useState(false); const [permission,requestPermission]=useCameraPermissions();
 const [asset,setAsset]=useState<RecordRow|null>(null);
 async function api(s:Session,path:string,method='GET',body?:unknown){
  const response=await fetch(s.url+path,{method,headers:{Authorization:s.auth,Accept:'application/json',...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});
  if(!response.ok)throw new Error('Server returned HTTP '+response.status);
  return response.json();
 }
 async function run(fn:()=>Promise<void>){if(busy)return;setBusy(true);try{await fn()}catch(e){Alert.alert('Building Brain',e instanceof Error?e.message:'Request failed')}finally{setBusy(false)}}
 async function login(){await run(async()=>{const origin=url.trim().replace(/\/+$/,'');if(!/^https:\/\/[a-zA-Z0-9.-]+(?::[0-9]+)?$/.test(origin))throw new Error('Enter an HTTPS server origin without a path.');if(!user||!password||user.includes(':')||/[^\x20-\x7E]/.test(user+password))throw new Error('Use nonempty ASCII credentials; username cannot contain a colon.');const auth=await api({url:origin,auth:''},'/api/mobile/login','POST',{username:user,password});const s={url:origin,auth:'Bearer '+auth.token};const data=await api(s,'/api/mobile/properties');setProperties(data);setSession(s);setPassword('');});}
 async function load(p:RecordRow,t:string){if(!session)return;await run(async()=>{const paths:Record<string,string>={'Work orders':'work-orders','Equipment':'assets','PM':'pm-plans','Inspections':'inspections'};const data=paths[t]?await api(session,fg+p.id+'/'+paths[t]):[];setProperty(p);setTab(t);setRows(data);setAsset(null);setAnswer('');});}
 async function update(id:number,status:string){if(!session||!property)return;await run(async()=>{const current=rows.find(r=>r.id===id);if(!current)throw new Error('Refresh work orders');await api(session,fg+property.id+'/work-orders/'+id,'PATCH',{status,expected_status:current.status});setRows(await api(session,fg+property.id+'/work-orders'));});}
 async function ask(){if(!session||!property)return;await run(async()=>{const data=await api(session,'/api/ask','POST',{property_id:property.id,question});setAnswer(data.answer+'\n\n'+(data.citations||[]).map((c:any)=>c.source_label+': '+c.excerpt).join('\n\n')+'\n\n'+(data.safety_note||''));});}
 async function scanned(value:string){setScan(false);if(!session||!property)return;await run(async()=>{const match=/^buildingbrain:asset:([1-9][0-9]*)$/.exec(value);if(!match)throw new Error('Unrecognized equipment label');const items:RecordRow[]=await api(session,fg+property.id+'/assets');const found=items.find(a=>a.id===Number(match[1]));if(!found)throw new Error('Asset not found in selected property');setAsset(found);setTab('Equipment');setRows(items);});}
 const button=(label:string,action:()=>void)=><Pressable disabled={busy} style={styles.button} onPress={action}><Text style={styles.buttonText}>{label}</Text></Pressable>;
 const input=(value:string,change:(v:string)=>void,placeholder:string,secure=false)=><TextInput style={styles.input} value={value} onChangeText={change} placeholder={placeholder} placeholderTextColor="#94a3b8" autoCapitalize="none" secureTextEntry={secure}/>;
 if(scan)return <SafeAreaView style={styles.root}><CameraView style={{flex:1}} barcodeScannerSettings={{barcodeTypes:['qr']}} onBarcodeScanned={({data})=>{if(scan&&!busy)void scanned(data)}}/>{button('Cancel',()=>setScan(false))}</SafeAreaView>;
 return <SafeAreaView style={styles.root}><ScrollView contentContainerStyle={{padding:20,gap:12}}><Text style={styles.heading}>Building Brain</Text><Text style={styles.muted}>FIELD OPERATIONS</Text>{busy&&<Text style={styles.muted}>Working…</Text>}
 {!session?<>{input(url,setUrl,'https://your-server.example')}{input(user,setUser,'Username')}{input(password,setPassword,'Password',true)}{button('Connect',()=>void login())}<Text style={styles.muted}>Private beta • assigned properties only • HTTPS required</Text></>:<>
 {button('Sign out',()=>{void api(session,'/api/mobile/logout','POST').catch(()=>{});setSession(null);setProperty(null);setRows([]);setAsset(null);setAnswer('');setProperties([])})}
 {!property?<><Text style={styles.heading}>Select property</Text>{properties.map(p=><View key={p.id}>{button(p.name||String(p.id),()=>void load(p,'Work orders'))}</View>)}</>:<>
 <Text style={styles.heading}>{property.name}</Text>{button('Change property',()=>{setProperty(null);setRows([]);setAsset(null);setAnswer('')})}
 <View style={{flexDirection:'row',flexWrap:'wrap',gap:8}}>{['Work orders','Equipment','PM','Inspections'].map(t=><View key={t}>{button(t,()=>void load(property,t))}</View>)}</View>
 {button('Refresh '+tab,()=>void load(property,tab))}
 {button('Scan equipment QR',()=>void run(async()=>{const p=permission?.granted?permission:await requestPermission();if(!p.granted)throw new Error('Camera permission required');setScan(true)}))}
 <Text style={styles.heading}>{tab}</Text>
 {tab==='AI'?<>{input(question,setQuestion,'Ask about this property')}{button('Ask',()=>void ask())}<Text style={styles.text}>{answer}</Text></>:<>
 {asset&&<View style={styles.card}><Text style={styles.heading}>{asset.name}</Text><Text style={styles.text}>{[asset.location,asset.model,asset.serial,asset.notes].filter(Boolean).join('\n')}</Text>{button('Close asset',()=>setAsset(null))}</View>}
 {!rows.length&&<Text style={styles.muted}>No records found.</Text>}
 {rows.map(r=><View key={r.id} style={styles.card}><Text style={styles.text}>{r.title||r.name}</Text><Text style={styles.muted}>{[r.status,r.description,r.location,r.next_due].filter(Boolean).join(' • ')}</Text>
 {tab==='Work orders'&&property.role==='technician'&&r.status!=='completed'&&r.status!=='cancelled'&&<>{button('Start work',()=>void update(r.id,'in_progress'))}{button('Complete',()=>Alert.alert('Complete work order?','Confirm work is finished.',[{text:'Cancel'},{text:'Complete',onPress:()=>void update(r.id,'completed')}]))}</>}
 {tab==='Equipment'&&button('Details',()=>setAsset(r))}</View>)}</>}
 </>}</>}
 </ScrollView></SafeAreaView>;
}
const styles=StyleSheet.create({root:{flex:1,backgroundColor:'#0b1220'},heading:{color:'#f8fafc',fontSize:24,fontWeight:'700'},muted:{color:'#94a3b8',fontSize:14},text:{color:'#e2e8f0',fontSize:16},input:{backgroundColor:'#172337',color:'#fff',padding:14,borderRadius:10},button:{backgroundColor:'#2459a6',padding:12,borderRadius:9},buttonText:{color:'#fff',fontWeight:'600'},card:{backgroundColor:'#172337',padding:16,borderRadius:12,gap:10}});
