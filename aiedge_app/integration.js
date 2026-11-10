(() => {
'use strict';
const $=id=>document.getElementById(id);
const stamp=value=>value?new Date(value).toLocaleString():'Unknown time';
let revision=null;
const form=$('retention-form'),message=$('retention-message');
async function request(path, options={}) {
 const response=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(8000),...options});
 const value=await response.json();
 if(!response.ok)throw Error(value.error||'Request failed');
 return value;
}
async function load() {
 form.querySelector('button').disabled=true;
 try {
  const saved=await request('api/retention');revision=saved.revision;
  for(const [name,value] of Object.entries(saved.config))form.elements.namedItem(name).value=value;
  const e=saved.evidence;
  $('retention-coverage').textContent=e?
   `${e.protected_gap_images} protected gap photos (${(e.protected_gap_bytes/1048576).toFixed(1)} MiB). ${e.complete_pairs} complete gap pairs; ${e.missing_endpoint_pairs} pairs already missing photos; ${e.awaiting_right_endpoint} awaiting a right endpoint. Checked ${stamp(e.checked_at)}.`:
   'Photo coverage has not been checked yet.';
  message.textContent=saved.error?'Cleanup needs attention; eligible photos have not all been removed.':'Saved settings loaded.';
  form.querySelector('button').disabled=false;
 } catch(error) {revision=null;message.textContent='Could not load retention settings. Reload before editing.';}
}
form.addEventListener('submit',async event=>{
 event.preventDefault();if(revision===null||!form.reportValidity())return;
 form.querySelector('button').disabled=true;
 const config=Object.fromEntries(['recent_events','older_images','older_megabytes'].map(name=>[name,Number(form.elements.namedItem(name).value)]));
 try {
  const setup=await request('api/setup');
  const saved=await request('api/retention',{method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Setup':setup.token},body:JSON.stringify({config,revision})});
  revision=saved.revision;message.textContent='Saved. Limits apply at the next cleanup; protected evidence is kept.';
  form.querySelector('button').disabled=false;
 } catch(error) {
  revision=null;message.textContent='Save was not confirmed. Reload saved settings before retrying.';
 }
});
$('retention-reload').onclick=load;
window.addEventListener('hashchange',()=>{if(location.hash==='#settings'&&revision===null)load();});
function render(state) {
 const usage=state?.mqtt?.usage||{},daily=usage.daily,recent=usage.recent;
 const estimate=daily?.low_use_estimate;
 $('usage-estimate').textContent=estimate?.method==='lower_bound_assumption_v1'?'Low-use estimate: '+estimate.label:'Estimate unavailable';
 $('usage-bounds').textContent=daily?'Unresolved bounds: '+daily.label:'Daily range unavailable';
 $('usage-assumption').textContent=estimate?.assumption||'';
 $('usage-time').textContent=daily?`${daily.day} (${daily.timezone}) · Measured ${stamp(daily.through.captured_at)} · Event ${daily.through.event_id}`:'';
 $('usage-hour').textContent=recent?`${recent.label} · ${stamp(recent.hour.start.captured_at)} to ${stamp(recent.through.captured_at)}`:'Last hour unavailable';
 const list=$('usage-quarters');list.replaceChildren();
 for(const q of recent?.quarters||[]) {
  const item=document.createElement('li');item.textContent=`${q.lower}–${q.upper} ft³ · ${stamp(q.start.captured_at)} to ${stamp(q.through.captured_at)}`;list.append(item);
 }
}
window.AIEdgeIntegration={render};
if(location.hash==='#settings')load();
})();
