(function(root){
'use strict';
const fields={pending:'pending',blocked:'blocked',cleanup:'acknowledged_awaiting_cleanup',stored:'stored',uploaded:'upload_acknowledgments',failures:'upload_failures',notqueued:'binding_rejected',notsaved:'enqueue_rejected'};
function failureDetail(s){
 const code=s.last_upload_error;
 if(!code||code==='none'||code==='not_started')return '';
 if(s.last_http_status===401||s.last_http_status===403)return 'The storage server rejected the credentials. Check the archive token. Queued images are retained.';
 if(s.last_http_status>=400)return 'The storage server returned HTTP '+s.last_http_status+'. Queued images are retained.';
 if(['connection_failed','settings_connection_failed'].includes(code))return 'Could not connect securely to the storage server. Check its address, connection and certificate. Queued images are retained.';
 if(code.includes('timeout'))return 'The storage request timed out. Queued images are retained.';
 if(code.includes('receipt'))return 'The storage receipt could not be verified. Queued images are retained.';
 if(code.startsWith('spool_')||code==='settings_file_invalid_or_missing')return 'A saved image or its settings could not be read or verified. Check the SD card. Existing files are retained.';
 return 'The last upload did not complete. Queued images are retained; check the device logs.';
}
function describe(s){
 if(!s||s.version!==1||['worker_started','engine_ready','capture_enabled'].some(k=>typeof s[k]!=='boolean')||[...Object.values(fields),'handoff_rejected'].some(k=>!Number.isSafeInteger(s[k])||s[k]<0)||!s.resources||!Number.isSafeInteger(s.resources.sampled_us)||s.resources.sampled_us<0)throw Error('Invalid archive status');
 if(s.last_http_status!==undefined&&(!Number.isInteger(s.last_http_status)||s.last_http_status<0||s.last_http_status>599))throw Error('Invalid upload status');
 if(s.last_upload_error!==undefined&&(typeof s.last_upload_error!=='string'||s.last_upload_error.length>64))throw Error('Invalid upload error');
 const failure=failureDetail(s);
 if(!s.worker_started)return ['Not running','Archiving may be disabled or still initializing. Check logs if you expected it to start.'];
 // The worker publishes its first resource sample after queue initialization.
 if(!s.engine_ready)return s.resources.sampled_us>0
  ? ['Storage unavailable','The saved image queue could not be opened or updated. New images cannot be saved or uploaded. Check the SD card and device logs.']
  : ['Starting','The saved queue is not ready. No delivery is confirmed by this state.'];
 if(s.blocked)return ['Needs attention',failure||'Some queued images require attention. Check the device logs.'];
 if(s.binding_rejected||s.handoff_rejected||s.enqueue_rejected)return [s.capture_enabled?'Some captures were not archived':'Finishing queued uploads','Some captures could not be queued or saved during this restart. Check the counts below and device logs; these counts do not confirm a saved copy.'];
 if(s.pending&&failure)return ['Retrying upload',failure];
 return [s.capture_enabled?'Running':'Finishing queued uploads',s.capture_enabled?'New images can be queued when a reading captures a photo.':'New captures are not being queued. Existing uploads may continue.'];
}
function mount(doc,fetcher){let busy=false;
 const node=id=>doc.getElementById(id);
 async function refresh(){
  if(busy)return;busy=true;node('refresh').disabled=true;node('notice').textContent='Reading archive statusâ€¦';
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
