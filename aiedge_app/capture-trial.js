(() => {
'use strict';
const $=id=>document.getElementById(id),active=new Set(['queued','working','cancelling']);
const key='aiedge-capture-trial:'+location.pathname;
let requested=null,current=null,pending=false,loading=false,timer=null,serial=0,uncertain=false,storageError=false;
const messages={trial_not_allowed:'Pause automatic capture, MQTT and archiving, and finish calibration and number format.',
 trial_not_ready:'Trial capture is not ready yet.',trial_unavailable:'Trial capture is unavailable.',
 trial_journal_invalid:'The saved trial record could not be verified. It has been kept. Check app diagnostics.',
 trial_storage_unavailable:'Trial storage is unavailable. Check app diagnostics.',trial_busy:'Another trial is running.',
 trial_browser_storage_unavailable:'Browser storage is unavailable. Enable it and reload before starting a trial.',
 trial_context_changed:'Calibration or number format changed. The trial stopped.',
 trial_interrupted:'The app restarted. This trial will not resume.',
 camera_timeout:'The camera timed out. This trial will not retry.',
 camera_lighting_unverified:'Open Setup → Lighting and activate the saved lighting before capturing.',
 storage_low_space:'Local storage is low on space. Existing images are kept.',
 trial_clock_unverified:'Capture timing is missing. Images were kept; the trial stopped.',
 trial_frame_not_fresh:'Capture timing changed. Images were kept; the trial stopped.'};
try{const saved=sessionStorage.getItem(key);if(/^[a-f0-9]{32}$/.test(saved||''))requested=saved;}catch{storageError=true;}
const visible=()=>!document.hidden&&location.hash==='#captures';
function notice(message='',error=false){$('trial-notice').textContent=message;$('trial-notice').hidden=!message;$('trial-notice').dataset.error=String(error);}
function render(){
 const running=active.has(current?.state),missing=current?.state==='not_found';
 const states={idle:'Ready',queued:'Starting…',working:'Capturing…',cancelling:'Stopping…',completed:'Finished',cancelled:'Stopped',expired:'Time limit reached',failed:'Stopped after an error',interrupted:'Interrupted',unavailable:'Unavailable',not_found:'Start not confirmed'};
 $('trial-state').textContent=pending?'Sending request…':states[current?.state]||'Checking…';
 $('trial-start').textContent=requested&&(uncertain||missing)?'Retry start':'Start trial';
 $('trial-start').disabled=storageError||pending||loading||running||!current?.can_start;
 $('trial-stop').hidden=!running;$('trial-stop').disabled=pending||loading||current?.state==='cancelling';
 $('trial-check').hidden=!uncertain;$('trial-check').disabled=pending||loading;
 $('trial-progress').hidden=!current?.max_attempts;
 if(current?.max_attempts){
  $('trial-progress').max=current.max_attempts;$('trial-progress').value=current.attempts;
  $('trial-counts').textContent=current.attempts+' / '+current.max_attempts+' attempts · '+current.unique_images+' unique · '+current.duplicate_images+' repeated';
 }else $('trial-counts').textContent='3 attempts · 30 seconds apart · 90-second request budget';
 if(!pending&&!uncertain){
  const reason=current?.error||(!running?current?.block_reason:null);
  notice(reason?messages[reason]||'The trial stopped. Check app diagnostics before trying again.':'',!!current?.error);
  if(current?.counts_complete===false)notice((messages[current.error]||'Trial stopped.')+' Counts may be incomplete'+(current.capture_outcome_uncertain?'; a requested photo may have an unknown outcome.':'.'),true);
 }
 if(storageError)notice(messages.trial_browser_storage_unavailable,true);
}
async function json(url,options={}){
 const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(8000),...options});
 let data;try{data=await response.json();}catch{throw Error('invalid_response');}
 if(!response.ok){const error=Error(data.error||'trial_unavailable');error.status=response.status;throw error;}
 return data;
}
function schedule(){clearTimeout(timer);if(visible()&&(active.has(current?.state)||uncertain))timer=setTimeout(refresh,2000);}
async function refresh(){
 if(loading||pending||!visible())return;
 loading=true;const generation=++serial;render();
 try{
  const result=await json('api/capture-trial'+(requested?'?request_id='+requested:''));
  if(generation!==serial)return;
  current=result;
  // A status read, never another POST, resolves a lost start/cancel reply.
  uncertain=result.state==='not_found'&&!!requested;
  if(active.has(result.state)&&result.request_id){requested=result.request_id;try{sessionStorage.setItem(key,requested);}catch{}}
  if(uncertain)notice('Start was not confirmed. Retry start uses the same request; it cannot create a second trial.',true);
 }catch{uncertain=true;if(current)current.can_start=false;notice('Connection lost. Checking the saved request; no extra pictures will be requested automatically.',true);}
 finally{loading=false;render();schedule();}
}
async function action(kind){
 if(pending||loading||kind==='start'&&$('trial-start').disabled||kind==='cancel'&&$('trial-stop').disabled)return;
 clearTimeout(timer);pending=true;render();
 let id=requested;
 try{
  if(kind==='start'&&!(requested&&(uncertain||current?.state==='not_found'))){
   id=Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('');
   try{sessionStorage.setItem(key,id);}catch{storageError=true;throw Error('trial_browser_storage_unavailable');}requested=id;
  }
  const setup=await json('api/setup');if(!setup.token)throw Error('trial_not_ready');
  const body=kind==='start'?{action:'start',request_id:id,max_attempts:3,duration_seconds:90,interval_seconds:30}:{action:'cancel',request_id:id};
  const result=await json('api/capture-trial',{method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Setup':setup.token},body:JSON.stringify(body)});
  current=result;uncertain=false;notice();
 }catch(error){
  // Never silently repeat a start or cancel. Keep its ID for readback/retry.
  uncertain=true;if(current)current.can_start=false;
  notice(messages[error.message]||'Request could not be confirmed. Check status before starting another trial.',true);
 }finally{pending=false;render();await refresh();schedule();}
}
$('trial-start').onclick=()=>action('start');$('trial-stop').onclick=()=>action('cancel');$('trial-check').onclick=refresh;
function route(){clearTimeout(timer);if(visible())refresh();}
window.addEventListener('hashchange',route);document.addEventListener('visibilitychange',route);
window.addEventListener('aiedge-refresh-images',event=>{if(event.detail==='captures')refresh();});
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',route,{once:true});else route();
})();
