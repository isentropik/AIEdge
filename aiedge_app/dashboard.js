(() => {
'use strict';
const $=id=>document.getElementById(id);
const captureErrors={
 duplicate_camera_header:'Camera returned repeated capture metadata. The image was rejected.',
 invalid_camera_header:'Camera returned invalid capture metadata. The image was rejected.',
 invalid_image_length:'Camera returned an invalid image length or transfer format. The image was rejected.',
 camera_authentication_failed:'Camera login was rejected. Check its credentials in app configuration.',
 camera_api_unavailable:'This camera firmware does not provide the remote capture API.',
 camera_busy:'Camera is busy. The next scheduled capture will try again.',
 camera_unavailable:'Camera is unavailable. Check the device and camera connection.',
 camera_clock_unsynchronized:'Camera is waiting for its clock to synchronize.',
 camera_clock_changed:'Camera time changed during capture. That image was rejected.',
 incomplete_capture_clock:'Camera returned incomplete timing metadata. That image was rejected.',
 duplicate_capture_clock_header:'Camera returned conflicting timing headers. That image was rejected.',
 invalid_capture_clock_id:'Camera returned an invalid clock identifier. That image was rejected.',
 invalid_capture_clock_tick:'Camera returned an invalid capture clock. That image was rejected.',
 camera_settings_unavailable:'Camera settings could not be applied. Check the device setup.',
 camera_startup_recovery:'Camera startup was interrupted or its recovery guard failed. Automatic initialization is paused; check device diagnostics.',
 camera_lighting_failed:'Camera lighting failed. The image was rejected.',
 camera_demo_mode:'The camera is in demo mode. Live capture is unavailable.',
 camera_worker_unavailable:'The camera could not start a capture. The next scheduled capture will try again.',
 camera_certificate_invalid:'Camera TLS certificate could not be verified.',
 camera_timeout:'Camera did not respond in time. The next scheduled capture will try again.',
 camera_name_unresolved:'Camera name could not be resolved. Check its address.',
 camera_connection_failed:'Could not connect to the camera. Check its power and network address.',
 camera_http_error:'Camera returned an unexpected response.',
 camera_status_invalid:'Camera returned invalid readiness information. No picture was requested.',
 camera_protocol_unsupported:'Camera firmware uses an unsupported capture protocol. No picture was requested.',
 stored_image_corrupt:'A saved image failed its integrity check. The original file has been kept.',
 stored_image_missing:'A saved image is missing from app storage.',
 storage_low_space:'Capture paused: local storage is low on space. Existing images are kept.',
 storage_unavailable:'Capture paused: local storage is unavailable.'
};
const date=value=>value?new Date(value).toLocaleString():'—';
const theme=$('theme');
try {theme.value=localStorage.getItem('aiedge-theme')||'system';} catch {}
function applyTheme(){
  document.documentElement.dataset.theme=theme.value;
  try {localStorage.setItem('aiedge-theme',theme.value);} catch {}
}
theme.onchange=applyTheme;applyTheme();
let activePage='overview';
function page(name){
  activePage=name;
  $('error').hidden=!$('error').textContent||$('error').dataset.owner===name;
  for(const id of ['overview','captures','setup','format','settings']){
    $(id).hidden=id!==name;$(id+'-tab').setAttribute('aria-current',id===name?'page':'false');
  }
  $('title').textContent={overview:'Overview',captures:'Captures',setup:'Setup',format:'Number format',settings:'Settings'}[name];
}
window.showAppPage=page;
const routes={setup:'setup',settings:'settings',overview:'overview',captures:'captures',calibration:'setup',format:'format'};
function route(){
 if(window.AIEdgeFlow?.route(location.hash))return;
 const review=/^#captures\/([1-9][0-9]*)$/.exec(location.hash);
 const name=review?'captures':routes[location.hash.slice(1)]||'overview';page(name);
 if(review){$('title').textContent='Review capture';window.AIEdgeReview?.open(Number(review[1]));}
 else window.AIEdgeReview?.close();
 if(name==='setup')window.openCalibration();
 if(name==='format')window.openReadingFormat();
}
for(const [hash,name] of Object.entries(routes).filter(([hash])=>hash!=='calibration'))$(name+'-tab').onclick=()=>{
 if(location.hash==='#'+hash)route();else location.hash=hash;
};
window.addEventListener('hashchange',route);
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',route,{once:true});
else route();
let busy=false,timer=null,galleryKey=null,imageHash=null,imageFailed=false;
let historyPage=null,historyCursors=[null],historyBusy=false,historyFailed=false;
function historyPath(){const before=historyCursors[historyCursors.length-1];return 'api/capture-history'+(before?'?before='+before:'');}
function historyControls(){
 $('history-newer').disabled=historyBusy||historyCursors.length===1;
 $('history-older').disabled=historyBusy||!historyPage?.next_before;
 $('history-summary').textContent=historyPage?.items.length?(historyCursors.length===1?'Latest captures':'Earlier captures')+' · '+historyPage.items.length:'No stored captures';
}
async function moveHistory(older){
 if(historyBusy||busy)return;
 const previous=[...historyCursors];
 if(older){if(!historyPage?.next_before)return;historyCursors.push(historyPage.next_before);}
 else{if(historyCursors.length===1)return;historyCursors.pop();}
 historyBusy=true;historyControls();
 try{historyPage=await get(historyPath());gallery(historyPage.items);historyError(null);}
 catch(error){historyCursors=previous;historyError(error);}
 finally{historyBusy=false;historyControls();}
}
function historyError(error){
 historyFailed=!!error;
 $('empty-gallery').hidden=historyFailed||!!historyPage?.items.length;
 $('history-error').hidden=!error;
 $('history-error').textContent=error?'Capture history could not be loaded. Use Refresh to try again.':'';
 $('empty-gallery').textContent=error?'Capture history unavailable.':'No stored captures yet.';
 if(error&&!historyPage)$('history-summary').textContent='History unavailable';
}
$('history-newer').onclick=()=>moveHistory(false);$('history-older').onclick=()=>moveHistory(true);
$('latest-image').onerror=()=>{imageFailed=true;$('latest-image').hidden=true;$('empty-image').hidden=false;$('empty-image').querySelector('strong').textContent='Image unavailable';$('empty-image').querySelector('p').textContent='The saved image could not be loaded. Use Refresh to try again.';};
$('latest-image').onload=()=>{imageFailed=false;$('latest-image').hidden=false;$('empty-image').hidden=true;};
async function get(path){
  const response=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(8000)});
  if(!response.ok){
    let message='Could not load app status.',code='status_unavailable';
    if(response.status===503){
      code='app_unavailable';message='The app is temporarily unavailable. Retrying automatically.';
      try{
        const reason=(await response.json()).code;
        if(reason==='storage_startup_failed'){code=reason;message='App storage could not be opened. Capture and MQTT are stopped. Check the data volume or restore a backup, then restart AIEdge.';}
        else if(reason==='storage_unavailable'){code=reason;message='Local storage is unavailable. Saved images have not been replaced.';}
        else if(reason==='http_busy'){code=reason;message='The app is busy. Retrying automatically.';}
      }catch{}
    }
    const error=Error(message);error.code=code;throw error;
  }
  return response.json();
}
function renderRecognition(result){
  const r=typeof result==='object'&&result?result:{state:'not_configured'};
  const labels={not_configured:'Recognition is not configured.',waiting_for_image:'Waiting for an image.',pending:'Processing the latest image.',estimated:'Set the number format to calculate a reading.',rejected:'Image rejected. No total available.'};
  const rejected={alignment_rejected:'Alignment failed. Check the reference image and markers.',
    one_or_more_dials_rejected:'A dial could not be read. Check its crop and visibility.',
    image_does_not_match_calibration:'Image dimensions changed. Review the calibration.',
    stored_image_corrupt:'The saved image failed its integrity check. No reading available.',
    stored_image_missing:'The saved image is missing. No reading available.'};
  $('reading-status').textContent=(r.state==='rejected'&&rejected[r.error])||labels[r.state]||'Recognition unavailable.';
  const list=$('dial-results');list.replaceChildren();list.hidden=!(r.dial_positions?.length);
  for(const [i,dial] of (r.dial_positions||[]).entries()){
    const row=document.createElement('div'),name=document.createElement('dt'),value=document.createElement('dd');
    name.textContent=dial.name||'Dial '+(i+1);
    value.textContent=dial.state==='estimated'&&Number.isFinite(dial.position)?dial.position.toFixed(2):'Rejected';
    row.append(name,value);list.append(row);
  }
}
function renderConsumption(c){
 const units={ft3:'ft³',m3:'m³',L:'L',gal_us:'US gal',kWh:'kWh'};
 $('consumption-value').textContent='—';$('consumption-rate').textContent='—';$('consumption-anchor').hidden=true;
 const states={not_configured:'Set the number format to track consumption.',waiting_for_image:'Waiting for an image.',recovering:'Restoring the saved capture sequence.',pending:'Waiting for the latest dial estimates.',anchored:'Waiting for another capture.',estimated:'Estimate · accuracy not yet verified',within_noise:'No change resolved within the reading tolerance.',bounded:'Only a range can be established.',ambiguous:'Complete turns cannot be determined for this interval.'};
 const reasons={capture_clock_missing:'Capture timing is missing. A new anchor is required.',capture_clock_invalid:'Capture timing is invalid. No consumption available.',reading_pipeline_changed:'Review the number format after the calibration change.',consumption_image_rejected:'The latest image could not be used for consumption.',consumption_positions_contradict_bounds:'Dial movement contradicts the configured bounds.',consumption_runtime_unavailable:'Consumption engine could not be loaded.',consumption_storage_unavailable:'Consumption is waiting for local storage.',consumption_saved_state_invalid:'Saved consumption could not be verified. Its records have been kept.'};
 $('consumption-status').textContent=c?(states[c.state]||reasons[c.reason]||'No consumption available.'):'Consumption is not configured.';
 if(c&&(c.state==='estimated'||c.state==='anchored')&&Number.isFinite(c.value)&&typeof c.text==='string'){
  const unit=units[c.unit]||c.unit;$('consumption-value').textContent=c.text+' '+unit;
  if(typeof c.average_rate_per_minute_text==='string')$('consumption-rate').textContent=c.average_rate_per_minute_text+' '+unit+'/min';
 }
 if(c?.anchor_captured_at){$('consumption-anchor').textContent='Anchor '+date(c.anchor_captured_at);$('consumption-anchor').hidden=false;}
}
function gallery(rows){
  const key=JSON.stringify(rows);
  if(key===galleryKey)return;
  galleryKey=key;$('gallery').replaceChildren();$('empty-gallery').hidden=rows.length>0||historyFailed;
  for(const row of rows){
    const card=document.createElement('button');card.type='button';card.className='panel capture';
    card.onclick=()=>{location.hash='captures/'+row.event_id;};
    card.setAttribute('aria-label','Review capture '+date(row.captured_at));
    const image=document.createElement('img');image.src='image/'+row.sha256;
    image.alt='Meter capture '+date(row.captured_at);image.loading='lazy';
    image.onerror=()=>{image.hidden=true;card.classList.add('image-unavailable');};
    const body=document.createElement('div');body.className='body';
    const stamp=document.createElement('div');stamp.textContent='Captured '+date(row.captured_at);
    const meta=document.createElement('small');meta.textContent=Math.round(row.bytes/1024)+' KB · '+(row.duplicate_image?'Repeated image · ':'')+(row.review_error?'Review unavailable':row.reviewed_dials===null||row.reviewed_dials===undefined?'Unlabeled':row.reviewed_dials+' of '+row.review_dials+' reviewed');
    const received=document.createElement('small');received.textContent='Received '+date(row.received_at);received.style.display='block';
    body.title='Frame '+row.frame_id;
    const action=document.createElement('div');action.className='capture-action';const label=document.createElement('span');label.textContent='Review image';action.append(label);
    body.append(stamp,received,meta,action);card.append(image,body);$('gallery').append(card);
  }
}
function render(s,rows){
  renderConsumption(s.consumption);
  renderRecognition(s.recognition);window.latestReading=s.reading;window.latestRecognition=s.recognition;
  window.renderPhysicalReading?.(s.reading,s.recognition);
  $('mqtt-state').textContent=({disabled:'Not connected',starting:'Connecting',connected:'Connected',publishing:'Publishing',waiting_for_format:'Needs number format',waiting_for_reading:'Waiting for reading',disconnected:'Disconnected',error:'Connection failed'})[s.mqtt?.state]||'Not connected';
  $('count').textContent=s.captures;$('unique').textContent=s.unique_images;$('failures').textContent=s.failures;
  $('schedule').textContent=s.capture_enabled?'Every '+s.interval_seconds+' seconds':'Disabled';
  const cameraLabels={not_checked:'Waiting for camera check',checking:'Checking camera',ready:'Camera ready',busy:'Camera busy',camera_unavailable:'Camera unavailable',settings_unavailable:'Camera settings unavailable',startup_recovery:'Camera startup recovery',clock_unsynchronized:'Waiting for camera clock',demo_mode:'Camera in demo mode',unavailable:'Camera unreachable'};
  $('camera-status').textContent=s.capture_enabled?(cameraLabels[s.camera?.state]||'Waiting for camera check'):'Capture disabled';
  $('missed').textContent=s.missed_slots;$('received').textContent=date(s.latest?.received_at);
  $('storage-state').textContent=({ready:'Ready',low_space:'Low space',unavailable:'Unavailable'})[s.storage?.state]||'Unavailable';
  $('storage-free').textContent=Number.isFinite(s.storage?.free_bytes)?(s.storage.free_bytes/(1024**3)).toFixed(1)+' GiB':'—';
  $('capture-time').textContent=s.latest?'Captured '+date(s.latest.captured_at):'Waiting for the first image';
  if(!imageFailed){
    $('empty-image').querySelector('strong').textContent='No captures yet';
    $('empty-image').querySelector('p').textContent=s.capture_enabled?'Waiting for the camera to return an image.':'Camera capture is not enabled.';
  }
  $('latest-image').hidden=!s.latest||imageFailed;$('empty-image').hidden=!!s.latest&&!imageFailed;
  if(s.latest?.sha256!==imageHash){
    imageHash=s.latest?.sha256||null;
    if(imageHash){imageFailed=false;$('latest-image').src='image/'+imageHash;}
  }
  gallery(rows);
  const configIssue=s.configuration?.state==='invalid';
  const issue=configIssue?(s.configuration.code==='setup_storage_unavailable'?'Setup storage could not be opened. Capture and MQTT are stopped. Check the data volume, then restart AIEdge.':s.configuration.code==='mqtt_identity_unavailable'?'The saved MQTT identity could not be loaded. Capture and MQTT are stopped. Restore the identity from backup, then restart AIEdge.':'App configuration could not be loaded. Capture and MQTT are stopped. Correct the app options and restart AIEdge.'):
    s.recognition?.error==='stored_result_invalid'?'The stored recognition result is damaged. Its image and original record have been kept.':
    s.setup_recovery?.code==='recognition_runtime_unavailable'?'Recognition engine could not load. Check the app runtime and model files.':
    s.setup_recovery?'Saved calibration could not be loaded. Open Calibration to recover it.':
    s.format_recovery?'Saved number format could not be loaded. Open Number format to replace it.':
    s.recognition_error?'Recognition is waiting for local storage.':
    s.last_error?(captureErrors[s.last_error.error]||'Capture failed: '+s.last_error.error):
    s.capture_enabled&&s.storage?.state==='low_space'?'Capture paused: local storage is low on space. Existing images are kept.':'';
  $('error').dataset.owner=configIssue?'':s.setup_recovery?'setup':s.format_recovery?'format':'';
  $('error').hidden=!issue||$('error').dataset.owner===activePage;$('error').textContent=issue;
  window.AIEdgeFlow?.renderStatus(s);
  $('checked-at').textContent='Checked '+new Date().toLocaleTimeString();
}
async function refresh(){
  if(busy)return;
  clearTimeout(timer);busy=true;$('refresh').disabled=true;
  const historyRequest=historyBusy?Promise.resolve():get(historyPath()).then(page=>{
    historyPage=page;historyControls();gallery(page.items);historyError(null);
  },error=>historyError(error));
  try {
    // History may time out independently. Render a successful status promptly.
    const state=await get('api/status');
    render(state,historyPage?.items||[]);
  } catch(error){
    // Keep historical images visible, but do not leave an old value looking live.
    window.AIEdgeFlow?.statusUnavailable();
    renderConsumption({state:'unavailable',value:null});
    $('consumption-status').textContent='Status unavailable.';
    window.latestReading={state:'unavailable',value:null};
    window.renderPhysicalReading?.(window.latestReading);
    $('meter-value').textContent='—';$('reading-status').textContent='Status unavailable.';
    const storageFailed=error.code==='storage_startup_failed',storageUnavailable=error.code==='storage_unavailable';
    $('camera-status').textContent=storageFailed?'Capture stopped':storageUnavailable?'Storage unavailable':error.code==='http_busy'?'App busy':error.code==='app_unavailable'?'App unavailable':'Connection lost';$('mqtt-state').textContent=storageFailed?'Stopped':'Unknown';
    $('storage-state').textContent=storageFailed||storageUnavailable?'Unavailable':'Unknown';$('storage-free').textContent='—';
    $('schedule').textContent=storageFailed?'Stopped':'Unavailable';
    for(const id of ['count','unique','failures','missed','received'])$(id).textContent='—';
    $('checked-at').textContent='Last check '+new Date().toLocaleTimeString();
    // History has its own result/error; a status outage must not discard it.
    if(!imageHash){$('empty-image').querySelector('strong').textContent='Image unavailable';$('empty-image').querySelector('p').textContent='Saved images could not be checked.';$('capture-time').textContent='Capture status unavailable';}
    $('dial-results').hidden=true;$('error').dataset.owner='';$('error').hidden=false;
    $('error').textContent=error.name==='TimeoutError'?'The app did not respond. Retrying automatically.':error instanceof TypeError?'Connection to the app was lost. Retrying automatically.':error.message;
  } finally {
    await historyRequest;
    busy=false;$('refresh').disabled=false;
    if(!document.hidden)timer=setTimeout(refresh,5000);
  }
}
$('refresh').onclick=()=>{if(imageFailed){imageHash=null;$('latest-image').removeAttribute('src');}galleryKey=null;window.dispatchEvent(new CustomEvent('aiedge-refresh-images',{detail:activePage}));refresh();};
window.addEventListener('aiedge-reading-format-saved',refresh);
window.addEventListener('aiedge-calibration-saved',refresh);
document.addEventListener('visibilitychange',()=>{
  clearTimeout(timer);if(!document.hidden)refresh();
});
refresh();
})();
