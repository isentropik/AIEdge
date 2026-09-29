(() => {
'use strict';
const $=id=>document.getElementById(id);
const date=value=>value?new Date(value).toLocaleString():'—';
const theme=$('theme');
try {theme.value=localStorage.getItem('aiedge-theme')||'system';} catch {}
function applyTheme(){
  document.documentElement.dataset.theme=theme.value;
  try {localStorage.setItem('aiedge-theme',theme.value);} catch {}
}
theme.onchange=applyTheme;applyTheme();
function page(name){
  for(const id of ['overview','captures','setup','format']){
    $(id).hidden=id!==name;$(id+'-tab').setAttribute('aria-current',id===name?'page':'false');
  }
  $('title').textContent={overview:'Overview',captures:'Captures',setup:'Calibration',format:'Number format'}[name];
}
$('overview-tab').onclick=()=>page('overview');
$('captures-tab').onclick=()=>page('captures');
$('setup-tab').onclick=()=>{page('setup');window.openCalibration();};
$('format-tab').onclick=()=>{page('format');window.openReadingFormat();};
let busy=false,timer=null,galleryKey=null,imageHash=null;
async function get(path){
  const response=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(8000)});
  if(!response.ok){
    let message='Could not load app status.';
    if(response.status===503)message='Local storage is unavailable. Saved images have not been replaced.';
    throw Error(message);
  }
  return response.json();
}
function renderRecognition(result){
  const r=typeof result==='object'&&result?result:{state:'not_configured'};
  const labels={not_configured:'Recognition is not configured.',waiting_for_image:'Waiting for an image.',pending:'Processing the latest image.',estimated:'Set the number format to calculate a reading.',rejected:'Image rejected. No total available.'};
  $('reading-status').textContent=labels[r.state]||'Recognition unavailable.';
  const list=$('dial-results');list.replaceChildren();list.hidden=!(r.dial_positions?.length);
  for(const [i,dial] of (r.dial_positions||[]).entries()){
    const row=document.createElement('div'),name=document.createElement('dt'),value=document.createElement('dd');
    name.textContent=dial.name||'Dial '+(i+1);
    value.textContent=dial.state==='estimated'&&Number.isFinite(dial.position)?dial.position.toFixed(2):'Rejected';
    row.append(name,value);list.append(row);
  }
}
function gallery(rows){
  const key=JSON.stringify(rows);
  if(key===galleryKey)return;
  galleryKey=key;$('gallery').replaceChildren();$('empty-gallery').hidden=rows.length>0;
  for(const row of rows){
    const card=document.createElement('a');card.className='panel capture';
    card.href='image/'+row.sha256;card.target='_blank';card.rel='noopener';
    const image=document.createElement('img');image.src=card.href;
    image.alt='Meter capture '+date(row.captured_at);image.loading='lazy';
    const body=document.createElement('div');body.className='body';
    const stamp=document.createElement('div');stamp.textContent=date(row.captured_at);
    const meta=document.createElement('small');meta.textContent=Math.round(row.bytes/1024)+' KB · Unlabeled';
    body.append(stamp,meta);card.append(image,body);$('gallery').append(card);
  }
}
function render(s,rows){
  renderRecognition(s.recognition);window.latestReading=s.reading;
  window.renderPhysicalReading?.(s.reading);
  $('mqtt-state').textContent=({disabled:'Not connected',starting:'Connecting',connected:'Connected',publishing:'Publishing',waiting_for_format:'Needs number format',waiting_for_reading:'Waiting for reading',disconnected:'Disconnected',error:'Connection failed'})[s.mqtt?.state]||'Not connected';
  $('count').textContent=s.captures;$('unique').textContent=s.unique_images;$('failures').textContent=s.failures;
  $('schedule').textContent=s.capture_enabled?'Every '+s.interval_seconds+' seconds':'Disabled';
  $('camera-status').textContent=s.capture_enabled?'Capture enabled':'Capture disabled';
  $('missed').textContent=s.missed_slots;$('received').textContent=date(s.latest?.received_at);
  $('storage-state').textContent=({ready:'Ready',low_space:'Low space',unavailable:'Unavailable'})[s.storage?.state]||'Unavailable';
  $('storage-free').textContent=Number.isFinite(s.storage?.free_bytes)?(s.storage.free_bytes/(1024**3)).toFixed(1)+' GiB':'—';
  $('capture-time').textContent=s.latest?'Captured '+date(s.latest.captured_at):'Waiting for the first image';
  $('empty-image').querySelector('p').textContent=s.capture_enabled?'Waiting for the camera to return an image.':'Camera capture is not enabled.';
  $('latest-image').hidden=!s.latest;$('empty-image').hidden=!!s.latest;
  if(s.latest?.sha256!==imageHash){
    imageHash=s.latest?.sha256||null;
    if(imageHash)$('latest-image').src='image/'+imageHash;
  }
  gallery(rows);
  const issue=s.recognition_error?'Recognition is waiting for local storage.':
    s.last_error?'Capture failed: '+s.last_error.error:
    s.capture_enabled&&s.storage?.state==='low_space'?'Capture paused: local storage is low on space. Existing images are kept.':'';
  $('error').hidden=!issue;$('error').textContent=issue;
  $('checked-at').textContent='Checked '+new Date().toLocaleTimeString();
}
async function refresh(){
  if(busy)return;
  clearTimeout(timer);busy=true;$('refresh').disabled=true;
  try {
    const [state,rows]=await Promise.all([get('api/status'),get('api/captures')]);
    render(state,rows);
  } catch(error){
    // Keep historical images visible, but do not leave an old value looking live.
    window.latestReading={state:'unavailable',value:null};
    window.renderPhysicalReading?.(window.latestReading);
    $('meter-value').textContent='—';$('reading-status').textContent='Status unavailable.';
    $('camera-status').textContent='Connection lost';$('mqtt-state').textContent='Unknown';
    $('storage-state').textContent='Unknown';$('storage-free').textContent='—';
    $('dial-results').hidden=true;$('error').hidden=false;
    $('error').textContent=error.name==='TimeoutError'?'The app did not respond. Retrying automatically.':error instanceof TypeError?'Connection to the app was lost. Retrying automatically.':error.message;
  } finally {
    busy=false;$('refresh').disabled=false;
    if(!document.hidden)timer=setTimeout(refresh,5000);
  }
}
$('refresh').onclick=refresh;
document.addEventListener('visibilitychange',()=>{
  clearTimeout(timer);if(!document.hidden)refresh();
});
refresh();
})();
