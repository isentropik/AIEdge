/* Archive controls never contact the NAS. The app owns the isolated copy worker. */
(() => {
'use strict';
const $=id=>document.getElementById(id);
const messages={archive_config_changed:'Archive settings changed in another session. Load the saved settings before continuing.',archive_choices_invalid:'Enter a network-storage folder below /media.',archive_request_invalid:'Enter a network-storage folder below /media.',archive_unavailable:'Archive storage is unavailable. Local captures are kept.',archive_mount_unavailable:'Network storage is unavailable. Copies will retry automatically.',archive_unsupported:'Network copies require Home Assistant OS on Linux.',archive_conflict:'An archive file differs from this capture. Check the destination before retrying.',archive_source_invalid:'A local capture could not be verified. Check app storage before retrying.',archive_io_failed:'The network copy failed. Copies will retry automatically.',archive_worker_busy:'A previous copy is still stopping. Copies will retry automatically.',archive_worker_failed:'The copy worker failed. Copies will retry automatically.',archive_timeout:'Network storage did not respond in time. Local captures are kept.',archive_busy:'A copy is still running. Wait for it to finish.',archive_local_storage_unavailable:'The archive ledger is unavailable. Local captures are kept.'};
let saved=null,dirty=false,busy=false,loading=null,active=false,timer=null,actionError=null,actionConnection=false;
function note(text,error=false,connection=false){if(window.AIEdgeNotices){window.AIEdgeNotices.show('archive-status',text,error,connection);return;}$('archive-status').textContent=text;$('archive-status').hidden=!text;$('archive-status').dataset.error=String(error);}
async function request(options){const response=await fetch('api/archive',{cache:'no-store',signal:AbortSignal.timeout(10000),...options});const result=await response.json();if(!response.ok){const error=Error(messages[result.error]||'Archive settings could not be verified.');error.status=response.status;throw error;}return result;}
function controls(){
 $('archive-enabled').disabled=busy||!saved;$('archive-directory').disabled=busy||!saved;
 $('archive-options').hidden=!$('archive-enabled').checked;
 $('archive-retry').disabled=busy||dirty;$('archive-reload').disabled=busy;
}
function paint(state,replace=false){
 if(!state.config||typeof state.revision!=='string')throw Error(messages.archive_unavailable);
 if(replace||!dirty){saved=state;$('archive-enabled').checked=state.config.enabled;$('archive-directory').value=state.config.directory;dirty=false;if(replace)actionError=null;}
 $('archive-counts').hidden=!state.config.enabled;$('archive-copied').textContent=state.copied_events;$('archive-pending').textContent=state.pending_events;
 $('archive-retry').hidden=!state.error||state.in_progress||!state.config.enabled;
 $('archive-reload').hidden=true;
 const text=state.state==='disabled'?(state.in_progress?'Off. The current copy may finish.':'Off. Images are stored in Home Assistant.'):
  state.state==='waiting_for_capture'?'No captures to copy yet.':
  state.state==='ready'?'All stored captures copied.':state.state==='copying'?'Copying a capture…':
  state.state==='waiting_for_worker'?'Waiting for the previous copy to stop.':state.error?(messages[state.error]||'The archive copy needs attention.'):'Captures are queued for copying.';
 note(actionError||(dirty?'Unsaved archive choices.':text),!!actionError||!!state.error&&!dirty,!!actionError&&actionConnection);
 $('settings-archive').textContent=state.state==='disabled'?'Off':state.error?'Needs attention':state.state==='ready'?'Up to date':state.state==='waiting_for_capture'?'No captures':'Copying';controls();
}
async function load(replace=false){
 if(loading)return loading;
 loading=(async()=>{try{paint(await request(),replace);return true;}catch(error){note(window.AIEdgeNotices?.message(error)||error.message||'Archive settings are unavailable.',true,window.AIEdgeNotices?.connection(error));$('archive-reload').hidden=false;$('settings-archive').textContent='Unavailable';return false;}finally{loading=null;controls();}})();return loading;
}
async function post(body){
 const setup=await fetch('api/setup',{cache:'no-store',signal:AbortSignal.timeout(10000)});if(!setup.ok){const error=Error('App access could not be verified.');error.status=setup.status;throw error;}const auth=await setup.json();
 return request({method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Setup':auth.token},body:JSON.stringify(body)});
}
async function save(){
 if(loading)await loading;if(!saved){if($('archive-status').dataset.error!=='true')note('Load archive settings before continuing.',true);return false;}
 if(!dirty)return true;
 busy=true;controls();
 try{const config={enabled:$('archive-enabled').checked,directory:$('archive-directory').value.trim()};paint(await post({action:'save',config,revision:saved.revision}),true);return true;}
 catch(error){actionError=window.AIEdgeNotices?.message(error)||error.message||'Archive choices could not be saved.';actionConnection=!!window.AIEdgeNotices?.connection(error);note(actionError,true,actionConnection);$('archive-reload').hidden=false;return false;}
 finally{busy=false;controls();}
}
function changed(){dirty=true;actionError=null;controls();note('Unsaved archive choices.');}
$('archive-enabled').onchange=changed;$('archive-directory').oninput=changed;
$('archive-reload').onclick=()=>load(true);
$('archive-retry').onclick=async()=>{if(busy||dirty||!saved)return;busy=true;controls();try{paint(await post({action:'retry',revision:saved.revision}));}catch(error){note(window.AIEdgeNotices?.message(error)||error.message,true,window.AIEdgeNotices?.connection(error));}finally{busy=false;controls();}};
function route(){active=['#setup/data','#settings'].includes(location.hash);if(timer){clearInterval(timer);timer=null;}if(active){load();timer=setInterval(()=>{if(!document.hidden&&!busy)load();},5000);}}
window.AIEdgeArchive={save,load};window.addEventListener('hashchange',route);route();
})();
