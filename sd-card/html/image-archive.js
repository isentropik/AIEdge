(function(root){
'use strict';
const fields={pending:'pending',blocked:'blocked',cleanup:'acknowledged_awaiting_cleanup',stored:'stored',uploaded:'upload_acknowledgments',failures:'upload_failures'};
function describe(s){
 if(!s||s.version!==1||['worker_started','engine_ready','capture_enabled'].some(k=>typeof s[k]!=='boolean')||Object.values(fields).some(k=>!Number.isSafeInteger(s[k])||s[k]<0))throw Error('Invalid archive status');
 if(!s.worker_started)return ['Not running','Archiving may be disabled or still initializing. Check logs if you expected it to start.'];
 if(!s.engine_ready)return ['Starting','The saved queue is not ready. No delivery is confirmed by this state.'];
 if(s.blocked)return ['Needs attention','Some queued images require attention. Check the device logs.'];
 return [s.capture_enabled?'Running':'Finishing queued uploads',s.capture_enabled?'New images can be queued when a reading captures a photo.':'New captures are not being queued. Existing uploads may continue.'];
}
function mount(doc,fetcher){let busy=false;
 const node=id=>doc.getElementById(id);
 async function refresh(){
  if(busy)return;busy=true;node('refresh').disabled=true;node('notice').textContent='Reading archive status…';
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
  try{
   const response=await fetcher('/image_archive_status',{method:'GET',cache:'no-store',credentials:'same-origin',redirect:'error',signal:controller.signal});
   if(!response.ok)throw Error('Status unavailable');const s=await response.json(),text=describe(s);
   node('state').textContent=text[0];node('detail').textContent=text[1];
   for(const [id,key] of Object.entries(fields))node(id).textContent=String(s[key]);
   node('notice').textContent='Last checked '+new Date().toLocaleTimeString()+'. Refresh to update.';
  }catch(_){node('state').textContent='Unavailable';node('detail').textContent='Could not read current archive status. Check the connection and try again.';for(const id of Object.keys(fields))node(id).textContent='Unavailable';node('notice').textContent='Status could not be refreshed.';}
  finally{clearTimeout(timer);busy=false;node('refresh').disabled=false;}
 }
 node('refresh').addEventListener('click',refresh);return {refresh};
}
const api={describe,mount};if(typeof module!=='undefined')module.exports=api;
if(typeof document!=='undefined')mount(document,root.fetch.bind(root)).refresh();
})(typeof window!=='undefined'?window:globalThis);
