/* Guided setup over the same validated calibration and number-format stores. */
(() => {
'use strict';
const $=id=>document.getElementById(id);
const steps=['lighting','image','alignment','dials','format','data','finish'];
const headings={lighting:'Lighting',image:'Image',alignment:'Alignment markers',dials:'Analog dials',format:'Number format',data:'Data',finish:'Finish setup'};
const form=$('reading-form'),formatHome=$('format');
let step='image',active=false,busy=false,navigating=false,camera=null,polling=false,viewGeneration=0,routeGeneration=0,statusSnapshot=null;
const messages={camera_not_configured:'Set the camera address in AIEdge app configuration, or choose a saved image.',camera_not_ready:'The camera is not ready. Check its connection and saved settings.',camera_setup_busy:'A camera request is already running. Wait for it to finish.',camera_authentication_failed:'Camera login was rejected. Check its credentials in app configuration.',camera_api_unavailable:'This firmware does not support remote capture.',camera_connection_failed:'Could not reach the camera. Check its power and network connection.',camera_timeout:'The camera did not respond in time.',camera_setup_failed:'The picture could not be verified. Your current reference has been kept.',camera_certificate_invalid:'The camera certificate could not be verified.',reference_must_be_640x480:'Choose a 640 × 480 reference image.'};
Object.assign(messages,{camera_busy:'The camera is busy. Wait for the current request to finish.',camera_lighting_unsupported:'This camera does not support app lighting controls.',camera_lighting_config_unsupported:'The saved lighting configuration is unsupported or ambiguous. Check it on the camera.',camera_lighting_pin_unavailable:'That pin is unavailable. Choose a free lighting pin.',camera_lighting_conflict:'Camera settings changed. Load the current settings before applying your choices.',camera_lighting_choice_invalid:'Check the light source, pin, LED count and channel values.',camera_lighting_unverified:'Lighting activation is unverified. Load and activate the saved lighting before taking a picture.',camera_lighting_connection_failed:'The camera connection failed. Load the saved settings to check the result; the request was not retried.',camera_lighting_activation_unverified:'Settings were saved, but activation is unverified. Load and activate the saved lighting before taking a picture.',camera_lighting_save_unverified:'The lighting save is unverified. Load the current settings before continuing.',camera_lighting_rejected:'The camera rejected the lighting request. Load the current settings before continuing.',camera_lighting_response_invalid:'The camera returned an invalid lighting response. Load the current settings before continuing.',camera_lighting_storage_unavailable:'The app could not save its lighting operation record. No further camera changes can be made until storage is repaired.'});
function note(message,error=false,target='setup-status'){
 const element=$(target);element.textContent=message;element.hidden=!message;element.dataset.error=String(error);
}
async function json(path,options={}){
 const response=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(10000),...options});
 const result=await response.json().catch(()=>({error:'The app returned an unreadable response.'}));
 if(!response.ok)throw Error(messages[result.error]||result.error||'The app did not respond.');
 return result;
}
function editor(){return window.AIEdgeCalibration?.status()||{};}
function controls(){
 const state=editor(),index=steps.indexOf(step);
 $('setup-back').disabled=busy||navigating||index===0;$('setup-next').disabled=busy||navigating||!!state.busy;
 $('setup-next').hidden=step==='finish';$('setup-next').textContent=busy?'Applying…':'Next';
 $('setup-next').setAttribute('aria-busy',String(busy));
 $('step-count').textContent=`Step ${index+1} of ${steps.length}`;
 $('setup-progress').textContent=step==='alignment'?'3 fixed markers':step==='dials'?(state.dial_count||0)+' dials':'';
 for(const button of document.querySelectorAll('.setup-steps button')){
  const current=button.dataset.step===step;button.setAttribute('aria-current',current?'step':'false');
  button.disabled=busy||navigating||!!state.busy;button.dataset.completed=String(steps.indexOf(button.dataset.step)<index);
 }
 const selected=document.querySelector?.('.setup-steps button[aria-current="step"]'),nav=document.querySelector?.('.setup-steps');
 if(selected&&nav&&nav.scrollWidth>nav.clientWidth)nav.scrollTo({left:Math.max(0,selected.offsetLeft-nav.offsetLeft-(nav.clientWidth-selected.offsetWidth)/2),behavior:'auto'});
 const image=!!state.has_image;
 $('take-reference').classList.toggle('primary',!image);
 $('take-reference').textContent=image?'Take another picture':'Take picture';
 $('take-reference').disabled=busy||!!state.busy||!camera?.configured;
 $('take-reference').hidden=true;
 $('check-camera').disabled=busy||!camera?.configured;
 const stale=!!window.AIEdgeCameraControls?.requiresPicture();
 $('reference-stage').classList.toggle('reference-stale',image&&stale);
 $('image-take-picture').hidden=(image&&!stale)||!camera?.configured||step!=='image';$('image-take-picture').disabled=busy;
 $('image-choose-file').hidden=!!camera?.configured;
 $('retake-reference').hidden=!image||stale||step!=='image';$('retake-reference').disabled=busy||!camera?.configured;
 $('use-latest').disabled=busy||!!state.busy;
 for(const id of ['reference-grid','reference-zoom-in','reference-zoom-out','reference-fit'])$(id).disabled=!image;
}
function moveFormat(inWizard){
 const host=inWizard?$('setup-format-host'):formatHome;
 if(form.parentElement!==host)host.append(form);
 $('save-format').hidden=inWizard;
 $('reload-format').hidden=inWizard;
}
async function show(next,updateHash=false){
 if(!steps.includes(next))next='image';
 const generation=++viewGeneration;
 active=true;step=next;window.showAppPage('setup');
 if(updateHash&&location.hash!=='#setup/'+step){location.hash='setup/'+step;return;}
 $('setup-heading').textContent=headings[step];
 $('setup-lighting').hidden=step!=='lighting';
 $('setup-editor').hidden=!['image','alignment','dials'].includes(step);
 $('image-controls').hidden=step!=='image';$('placement-controls').hidden=step==='image';
 $('selected-label').firstChild.textContent=step==='alignment'?'Marker':'Dial';
 for(const id of ['format','data','finish'])$('setup-'+(id==='format'?'format-host':id)).hidden=step!==id;
 moveFormat(step==='format');
 controls();
 if(['image','alignment','dials'].includes(step)){
  await window.openCalibration();
  if(!active||generation!==viewGeneration)return;
  window.AIEdgeCalibration?.setMode(next==='alignment'?'markers':next==='dials'?'dials':'image');
 }
 if(next==='format')await window.openReadingFormat();
 if(next==='finish')await summary();
 if(active&&generation===viewGeneration)controls();
}
function fail(message){note(message,true);return false;}
async function leave(){
 const state=editor();
 if(step==='lighting')return await window.AIEdgeCameraControls?.apply()??true;
 if(step==='image')return (state.has_image&&!window.AIEdgeCameraControls?.requiresPicture())||fail(state.has_image?'Take a picture with the new lighting before continuing.':'Take a picture or choose an image before continuing.');
 if(step==='alignment')return state.markers_complete||fail('Place all three markers on fixed markings.');
 if(step==='dials')return await window.AIEdgeCalibration.save();
 if(step==='format')return await window.AIEdgeFormat.save();
 return true;
}
async function go(target){
 if(busy||navigating||editor().busy||!steps.includes(target))return;
 const generation=routeGeneration;
 const index=steps.indexOf(step),to=steps.indexOf(target);
 if(to<=index){note('');await show(target,true);return;}
 navigating=true;busy=true;controls();
 try{
  for(let i=index;i<to;i++){
   // Lighting jobs own busy/polling while the outer navigation stays guarded.
   if(step==='lighting')busy=false;
   if(!await leave())return;
   busy=true;
   if(!active||generation!==routeGeneration)return;
   await show(steps[i+1]);
   if(!active||generation!==routeGeneration)return;
  }
  location.hash='setup/'+target;
 }catch(error){note(error.message,true);}
 finally{busy=false;navigating=false;controls();}
}
function paintCamera(value){
 camera=value;
 window.AIEdgeCameraControls?.configure(value.configured);
 if(value.lighting_needs_attention)window.AIEdgeCameraControls?.markAttention();
 if(value.state==='ready'&&value.action?.startsWith('lighting-'))window.AIEdgeCameraControls?.receive(value);
 $('settings-camera-address').textContent=value.camera_url||'Not configured';
 $('settings-capture').textContent=value.capture_enabled?'On':'Off';
 $('settings-interval').textContent=Number.isInteger(value.interval_seconds)?value.interval_seconds+' seconds':'—';
 $('settings-camera-state').textContent=value.readiness?.state?.replaceAll('_',' ')||'Not checked';
 const link=$('device-settings');link.hidden=true;link.removeAttribute('href');
 try{
  const origin=new URL(value.camera_url);
  if(['http:','https:'].includes(origin.protocol)&&!origin.username&&!origin.password&&origin.pathname==='/'&&!origin.search&&!origin.hash){link.href=origin.href;link.hidden=false;}
 }catch{}
 $('camera-setup-note').textContent=value.configured?'Camera configured. Pictures are taken only when requested.':'No camera configured. You can use a saved 640 × 480 image.';
 controls();
}
async function loadCamera(){
 try{paintCamera(await json('api/camera-setup'));}
 catch(error){note(error.message,true,active?'setup-status':'camera-action-status');$('camera-setup-note').textContent='Camera configuration unavailable.';}
}
async function cameraAction(action,details={}){
 if(polling||busy)return false;
 if(action==='picture'){
  try{if(!await(window.AIEdgeCameraControls?.apply()??true))return false;}
  catch(error){note(error.message,true);return false;}
 }
 polling=true;busy=true;controls();
 window.AIEdgeCameraControls?.setBusy(true);
 const target=active?'setup-status':'camera-action-status';note('',false,target);
 $('reference-working').hidden=action!=='picture';$('check-camera').disabled=true;
 try{
  const setup=await json('api/setup');
  let result=await json('api/camera-setup',{method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Setup':setup.token},body:JSON.stringify({action,...details})});
  const job=result.job,deadline=Date.now()+30000;
  while(['queued','working'].includes(result.state)){
   if(Date.now()>=deadline)throw Error('The camera request is still pending. Check its status before taking another picture.');
   await new Promise(resolve=>setTimeout(resolve,500));result=await json('api/camera-setup');
   if(result.job!==job)throw Error('The camera request changed in another session. Check the current reference.');
  }
  paintCamera(result);
  if(result.state==='error')throw Error(messages[result.error]||'The camera request failed. Your current reference has been kept.');
  if(action==='picture'){await window.AIEdgeCalibration.useReference(result.reference_sha256);window.AIEdgeCameraControls?.pictureTaken();}
  else if(action==='lighting-apply')note(result.settings?.active_verified?'Lighting applied.': 'Lighting settings are unchanged.',false,target);
  else if(action==='check')note('Camera: '+(result.readiness?.state||'unknown').replaceAll('_',' '),result.readiness?.state!=='ready',target);
  return true;
 }catch(error){note(error.message,true,target);return false;}
 finally{polling=false;busy=false;window.AIEdgeCameraControls?.setBusy(false);$('reference-working').hidden=true;$('check-camera').disabled=false;controls();}
}
async function latest(){
 if(busy)return;busy=true;controls();note('Loading latest capture…');
 try{
  const [state,setup]=await Promise.all([json('api/status'),json('api/setup')]);
  if(!state.latest?.sha256)throw Error('No captured image is available. Choose a saved image or take a picture.');
  const response=await fetch('image/'+state.latest.sha256,{signal:AbortSignal.timeout(10000)});
  if(!response.ok)throw Error('The latest image could not be loaded.');
  const data=await response.arrayBuffer();
  if(data.byteLength>4*1024*1024)throw Error('The image is larger than 4 MB.');
  const reference=await json('api/setup/reference',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-AIEdge-Setup':setup.token},body:data});
  await window.AIEdgeCalibration.useReference(reference.reference_sha256);
 }catch(error){note(error.message,true);}
 finally{busy=false;controls();}
}
function renderStatus(s){
 statusSnapshot=s;
 const storage=s.storage||{},free=Number.isFinite(storage.free_bytes)?(storage.free_bytes/1024**3).toFixed(1)+' GB':'—';
 const storageText=storage.state==='ready'?'Available':storage.state==='low_space'?'Low space':'Unavailable';
 for(const id of ['setup-local-storage','settings-storage'])$(id).textContent=storageText;
 for(const id of ['setup-free-space','settings-free-space'])$(id).textContent=free;
 const mqtt=s.mqtt?.state||'disabled';$('settings-mqtt').textContent=mqtt==='disabled'?'Off':mqtt.replaceAll('_',' ');
 const summaryMqtt=$('setup-summary-mqtt');if(summaryMqtt)summaryMqtt.textContent=mqtt==='disabled'?'Off':mqtt.replaceAll('_',' ');
 $('setup-mqtt-note').textContent=mqtt==='disabled'?'MQTT output is off. No Home Assistant readings are published.':mqtt==='connected'?'MQTT output is connected.':'MQTT output: '+mqtt.replaceAll('_',' ');
}
async function summary(){
 try{
  const [calibration,format]=await Promise.all([json('api/setup'),json('api/reading-format')]);
  const ready=!!calibration.calibration&&!calibration.recovery;
  const bound=!!format.format&&!format.recovery&&format.format.pipeline_id===format.pipeline_id;
  const mqtt=statusSnapshot?.mqtt?.state;
  const rows=[['Reference and dials',ready?'Saved':'Incomplete'],['Number format',bound?'Saved':'Needs review'],['Capture',camera?(camera.capture_enabled?'On':'Off'):'Unknown'],['MQTT',mqtt?(mqtt==='disabled'?'Off':mqtt.replaceAll('_',' ')):'Unknown']];
  $('setup-summary').replaceChildren();
  for(const [name,value] of rows){const row=document.createElement('div'),key=document.createElement('dt'),text=document.createElement('dd');if(name==='MQTT')text.id='setup-summary-mqtt';key.textContent=name;text.textContent=value;row.append(key,text);$('setup-summary').append(row);}
 }catch(error){note(error.message,true);}
}
function route(hash){
 routeGeneration++;viewGeneration++;
 if(hash==='#settings'){active=false;moveFormat(false);window.showAppPage('settings');loadCamera();return true;}
 if(hash==='#calibration'||hash==='#setup'||hash.startsWith('#setup/')){show(hash==='#calibration'?'image':hash.split('/')[1]||'lighting');return true;}
 if(active){active=false;moveFormat(false);}
 return false;
}
$('setup-next').onclick=()=>go(steps[Math.min(steps.length-1,steps.indexOf(step)+1)]);
$('setup-back').onclick=()=>go(steps[Math.max(0,steps.indexOf(step)-1)]);
for(const button of document.querySelectorAll('.setup-steps button'))button.onclick=()=>go(button.dataset.step);
$('image-take-picture').onclick=()=>cameraAction('picture');$('take-reference').onclick=()=>cameraAction('picture');$('retake-reference').onclick=()=>cameraAction('picture');
$('check-camera').onclick=()=>cameraAction('check');$('use-latest').onclick=latest;
$('reference-grid').onclick=()=>{const value=$('reference-grid').getAttribute('aria-pressed')!=='true';$('reference-grid').setAttribute('aria-pressed',String(value));window.AIEdgeCalibration?.setGrid(value);};
let zoom=1;
function setZoom(value){zoom=Math.max(1,Math.min(3,value));$('reference-stage').dataset.zoomed=String(zoom>1);$('calibration-canvas').style.width=(zoom*100)+'%';$('reference-fit').textContent=zoom===1?'Fit':Math.round(zoom*100)+'%';window.AIEdgeCalibration?.draw();}
$('reference-fit').onclick=()=>setZoom(1);$('reference-zoom-in').onclick=()=>setZoom(zoom+.5);$('reference-zoom-out').onclick=()=>setZoom(zoom-.5);
window.updateSetupFlow=controls;
window.AIEdgeFlow={route,renderStatus,statusUnavailable(){statusSnapshot=null;for(const id of ['settings-storage','setup-local-storage','settings-mqtt'])$(id).textContent='Unknown';const mqtt=$('setup-summary-mqtt');if(mqtt)mqtt.textContent='Unknown';for(const id of ['settings-free-space','setup-free-space'])$(id).textContent='—';}};
window.addEventListener('aiedge-calibration-saved',()=>{if(active)controls();});
window.AIEdgeCameraControls?.connect(cameraAction);
route(location.hash);loadCamera();
})();
