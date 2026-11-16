'use strict';
function rankProperties(properties, latitude, longitude, accuracy) {
  if (!Number.isFinite(latitude) || Math.abs(latitude)>90 || !Number.isFinite(longitude) || Math.abs(longitude)>180 || !Number.isFinite(accuracy) || accuracy<0 || accuracy>250) return {status:'inaccurate',candidates:[]};
  const rad=x=>x*Math.PI/180;
  const candidates=properties.filter(p=>Number.isFinite(p.latitude)&&Number.isFinite(p.longitude)&&Number.isFinite(p.geofence_radius)&&p.geofence_radius>=25&&p.geofence_radius<=2000).map(p=>{
    const a=Math.sin(rad(p.latitude-latitude)/2)**2+Math.cos(rad(latitude))*Math.cos(rad(p.latitude))*Math.sin(rad(p.longitude-longitude)/2)**2;
    const distance=6371000*2*Math.asin(Math.sqrt(Math.min(1,Math.max(0,a))));
    return {id:p.id,name:p.name,distance,radius:p.geofence_radius,inside:distance+accuracy<=p.geofence_radius};
  }).filter(p=>p.distance<=p.radius+accuracy).sort((a,b)=>a.distance-b.distance);
  return {status:candidates.length===0?'outside':candidates.length===1&&candidates[0].inside?'confident':'ambiguous',candidates};
}
if(typeof module!=='undefined'&&module.exports)module.exports={rankProperties};
else globalThis.BBLocation={rankProperties};
