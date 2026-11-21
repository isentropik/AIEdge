/* Guided setup over the same validated calibration and number-format stores. */
(() => {
'use strict';
const $=id=>document.getElementById(id);
const steps=['meter','lighting','image','alignment','dials','format','data','finish'];
const headings={meter:'Meter and units',lighting:'Lighting',image:'Image',alignment:'Alignment markers',dials:'Analog dials',format:'Number format',data:'Data',finish:'Finish setup'};
const form=$('reading-form'),formatHome=$('page-format');
const redoing=location.hash==='#setup/redo';
let lastRoute=null,visitedSetup=false;
let step='image',active=false,busy=false,navigating=false,loadingStep=false,camera=null,polling=false,viewGeneration=0,routeGeneration=0,statusSnapshot=null;
const messages={camera_not_configured:'Set the camera address in AIEdge app configuration, or choose a saved image.',camera_not_ready:'The camera is not ready. Check its connection and saved settings.',camera_setup_busy:'A camera request is already running. Wait for it to finish.',camera_authentication_failed:'Camera login was rejected. Check its credentials in app configuration.',camera_api_unavailable:'This firmware does not support remote capture.',camera_connection_failed:'Could not reach the camera. Check its power and network connection.',camera_timeout:'The camera did not respond in time.',camera_setup_failed:'The picture could not be verified. Your current reference has been kept.',camera_certificate_invalid:'The camera certificate could not be verified.',reference_must_be_640x480:'Choose a 640 × 480 reference image.'};
Object.assign(messages,{camera_busy:'The camera is busy. Wait for the current request to finish.',camera_lighting_unsupported:'This camera does not support app lighting controls.',camera_lighting_config_unsupported:'The saved lighting configuration is unsupported or ambiguous. Check it on the camera.',camera_lighting_pin_unavailable:'That pin is unavailable. Choose a free lighting pin.',camera_lighting_conflict:'Lighting changed on the camera. Review the current values and edit again.',camera_lighting_choice_invalid:'Check the light source, pin, LED count and channel values.',camera_lighting_unverified:'Lighting activation is unverified. Load and activate the saved lighting before taking a picture.',camera_lighting_connection_failed:'The camera connection failed. Load the saved settings to check the result; the request was not retried.',camera_lighting_activation_unverified:'Settings were saved, but activation is unverified. Load and activate the saved lighting before taking a picture.',camera_lighting_save_unverified:'The lighting save is unverified. Load the current settings before continuing.',camera_lighting_rejected:'The camera rejected the lighting request. Load the current settings before continuing.',camera_lighting_response_invalid:'The camera returned an invalid lighting response. Load the current settings before continuing.',camera_lighting_storage_unavailable:'The app could not save its lighting operation record. No further camera changes can be made until storage is repaired.'});
Object.assign(messages,{camera_image_unsupported:'This camera firmware does not support app image controls.',camera_image_config_unsupported:'The saved image settings are incomplete or ambiguous. Check them on the camera.',camera_image_conflict:'Image settings changed on the camera. Review the current values and edit again.',camera_image_unverified:'Image settings could not be verified. Load and activate the saved settings before taking a picture.',camera_image_reference_required:'Take a picture in the new orientation and save its calibration before resuming scheduled capture.',camera_image_orientation_unverified:'The picture orientation could not be verified. Your saved calibration has been kept.',camera_image_choice_invalid:'Check the exposure and gain values.',camera_image_storage_unavailable:'The app could not save the image-settings operation. Repair app storage before changing the camera.',camera_image_activation_unverified:'Image settings were saved, but activation could not be verified. Load and activate the saved settings.',camera_image_save_unverified:'The image settings save could not be verified. Load the settings before continuing.',camera_image_connection_failed:'Could not reach the camera. The image-settings request was not retried.',camera_image_response_invalid:'The camera returned an invalid image-settings response.',camera_image_rejected:'The camera rejected the image settings.'});
Object.assign(messages,{auto_contract_unsupported:'Auto setup is unavailable on this camera firmware. Choose manual controls.',auto_restore_unverified:'The last camera trial could not be verified. Restore the saved settings before taking another picture.',auto_receipt_unverified:'The camera trial receipt could not be verified. Restore the saved settings before taking another picture.',auto_config_conflict:'Camera settings changed. Load the current settings before continuing.',auto_no_usable_image:'Auto could not find a usable picture. Check the camera position and light, or choose manual controls.',auto_cancelled:'Auto setup stopped.',auto_deadline:'Auto setup reached its time limit. Check the saved settings before trying again.',auto_storage_full:'Auto trial storage is full. Free app storage before taking more trial pictures.',auto_storage_unavailable:'The app could not save its Auto operation record. Repair app storage before continuing.',auto_save_unverified:'The selected settings save could not be verified. Restore the saved settings before continuing.',auto_activation_unverified:'The selected settings activation could not be verified. Restore the saved settings before continuing.',auto_recovery_unavailable:'The pending camera operation cannot be recovered automatically. Check app storage and the camera address.',auto_probe_failed:'The camera trial failed. Check its saved settings before taking another picture.',auto_response_invalid:'The camera returned an invalid trial response. Restore the saved settings before taking another picture.',auto_connection_failed:'The camera connection failed. Check its saved settings before taking another picture.'});
function note(message,error=false,target='setup-status',connection=false){
 if(window.AIEdgeNotices){window.AIEdgeNotices.show(target,message,error,connection,target==='setup-status'?'#setup/'+step:null);return;}
 const element=$(target);element.textContent=message;element.hidden=!message;element.dataset.error=String(error);
}
messages.auto_reference_unusable='The saved settings did not produce a usable reference picture. Your current reference has been kept. Check the light or choose manual controls.';
async function json(path,options={}){
 const response=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(10000),...options});
 const result=await response.json().catch(()=>({error:'The app returned an unreadable response.'}));
 if(!response.ok){const error=Error(messages[result.error]||result.error||'The app did not respond.');error.status=response.status;throw error;}
 return result;
}
function editor(){return window.AIEdgeCalibration?.status()||{};}
function controls(){
 const state=editor(),index=steps.indexOf(step);
 window.AIEdgeImageEditor?.setBusy(busy||navigating||!!state.busy);
 $('setup-back').disabled=busy||navigating||loadingStep||index===0;$('setup-next').disabled=busy||navigating||loadingStep||!!state.busy;
 $('setup-next').hidden=step==='finish';$('setup-next').textContent=busy?'Applying…':'Next';
 $('setup-next').setAttribute('aria-busy',String(busy));
 $('step-count').textContent=`Step ${index+1} of ${steps.length}`;
 $('setup-progress').textContent=step==='alignment'?'3 fixed markers':step==='dials'?(state.dial_count||0)+' dials':'';
 for(const button of document.querySelectorAll('.setup-steps button')){
  const current=button.dataset.step===step;button.setAttribute('aria-current',current?'step':'false');
  button.disabled=busy||navigating||loadingStep||!!state.busy;button.dataset.completed=String(steps.indexOf(button.dataset.step)<index);
 }
 const selected=document.querySelector?.('.setup-steps button[aria-current="step"]'),nav=document.querySelector?.('.setup-steps');
 if(selected&&nav&&nav.scrollWidth>nav.clientWidth)nav.scrollTo({left:Math.max(0,selected.offsetLeft-nav.offsetLeft-(nav.clientWidth-selected.offsetWidth)/2),behavior:'auto'});
 const image=!!state.has_image;
 $('take-reference').classList.toggle('primary',!image);
 $('take-reference').textContent=image?'Take another picture':'Take picture';
 $('take-reference').disabled=busy||!!state.busy||!camera?.configured;
 $('take-reference').hidden=true;
 $('check-camera').disabled=busy||!camera?.configured;
 const stale=!!window.AIEdgeCameraControls?.requiresPicture()||!!window.AIEdgeImageControls?.requiresPicture();
 $('reference-stage').classList.toggle('reference-stale',image&&stale);
 $('image-take-picture').hidden=(image&&!stale)||!camera?.configured||step!=='image';$('image-take-picture').disabled=busy;
 $('image-choose-file').hidden=!!camera?.configured;
 $('retake-reference').hidden=!image||stale||step!=='image';$('retake-reference').disabled=busy||!camera?.configured;
 $('use-latest').disabled=busy||!!state.busy;
 for(const id of ['reference-grid','reference-zoom-in','reference-zoom-out','reference-fit'])$(id).disabled=!image;
 for(const id of ['image-mirror','image-flip'])$(id).disabled=busy||navigating||!!state.busy||!image;
}
function moveFormat(inWizard){
 const host=inWizard?$('setup-format-host'):formatHome;
 if(form.parentElement!==host)host.append(form);
 $('save-format').hidden=inWizard;
 $('reload-format').hidden=inWizard;
}
async function show(next,updateHash=false){
 if(!steps.includes(next))next='meter';
 const generation=++viewGeneration;
 active=true;step=next;window.showAppPage('setup');
 if(updateHash&&location.hash!=='#setup/'+step){location.hash='setup/'+step;return;}
 loadingStep=true;
 $('setup-heading').textContent=headings[step];
 $('restart-setup').hidden=true;
 $('setup-meter').hidden=step!=='meter';
 $('setup-lighting').hidden=step!=='lighting';
 $('setup-editor').hidden=!['image','alignment','dials'].includes(step);
 $('image-controls').hidden=step!=='image';$('placement-controls').hidden=step==='image';
 window.AIEdgeImageControls?.setStep(step);
 $('selected-label').firstChild.textContent=step==='alignment'?'Marker':'Dial';
 for(const id of ['format','data','finish'])$('setup-'+(id==='format'?'format-host':id)).hidden=step!==id;
 moveFormat(step==='format');
 window.AIEdgeNotices?.sync();
 controls();
 if(['image','alignment','dials'].includes(step)){
  await window.openCalibration();
  if(!active||generation!==viewGeneration)return;
  window.AIEdgeCalibration?.setMode(next==='alignment'?'markers':next==='dials'?'dials':'image');
 }
 if(next==='meter'){
  const loaded=await window.AIEdgeMeter.load();
  if(active&&generation===viewGeneration)$('restart-setup').hidden=redoing||!loaded||!window.AIEdgeMeter.status().hasSaved;
 }
 if(next==='format')await window.openReadingFormat();
 if(next==='data')await window.AIEdgeArchive.load();
 if(next==='finish')await summary(generation);
 if(active&&generation===viewGeneration){loadingStep=false;controls();}
}
function fail(message){note(message,true);return false;}
async function leave(){
 const state=editor();
 if(['image','alignment','dials'].includes(step)&&state.loaded===false)return false;
 if(step==='meter')return await window.AIEdgeMeter.save();
 if(step==='lighting'){
  const lighting=window.AIEdgeCameraControls?.status?.();
  if(lighting?.needs_activation&&!lighting.dirty)return fail('Review the pending lighting activation before continuing.');
  return true;
 }
 if(step==='image'){
  if(window.AIEdgeCameraControls?.status?.().dirty||window.AIEdgeImageControls?.status?.().dirty)return fail('Apply your control changes before continuing.');
  if(!(state.has_image&&!window.AIEdgeCameraControls?.requiresPicture()&&!window.AIEdgeImageControls?.requiresPicture()))return fail(state.has_image?'Take a picture with the changed camera settings before continuing.':'Take a picture or choose an image before continuing.');
  return window.AIEdgeImageEditor?await window.AIEdgeImageEditor.save():true;
 }
 if(step==='alignment')return state.markers_complete||fail('Place all three markers on fixed markings.');
 if(step==='dials')return await window.AIEdgeCalibration.save();
 if(step==='format')return await window.AIEdgeFormat.save();
 if(step==='data')return await window.AIEdgeArchive.save();
 return true;
}
async function go(target){
 if(busy||navigating||loadingStep||editor().busy||!steps.includes(target))return;
 const generation=routeGeneration;
 const index=steps.indexOf(step),to=steps.indexOf(target);
 if(to<=index){note('');await show(target,true);return;}
 navigating=true;busy=true;controls();
 try{
  for(let i=index;i<to;i++){
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
function paintCamera(value,completedHere=false){
 camera=value;
 window.AIEdgeCameraControls?.configure(value.configured,value.camera_url);
 window.AIEdgeImageControls?.configure(value.configured,value.camera_url);
 window.AIEdgeImageControls?.receiveAuto?.(value.auto_settings);
 const saved=value.saved_controls;
 // An explicit Apply found overlapping edits. Show the values it read for review.
 if(completedHere&&value.state==='error'&&value.error==='camera_lighting_conflict'&&value.settings)window.AIEdgeCameraControls?.receive(value);
 if(completedHere&&value.state==='error'&&value.error==='camera_image_conflict'&&value.image_settings)window.AIEdgeImageControls?.receive(value);
 if(saved?.settings&&!(completedHere&&value.settings))window.AIEdgeCameraControls?.receive({cached:true,settings:saved.settings});
 if(saved?.image_settings&&!(completedHere&&value.image_settings))window.AIEdgeImageControls?.receive({cached:true,image_settings:{...saved.image_settings,requires_reference:!!value.image_requires_reference}});
 if((completedHere||!saved)&&value.state==='ready'&&(value.action?.startsWith('lighting-')||value.action==='auto-picture'||value.action==='auto-recover'))window.AIEdgeCameraControls?.receive(value);
 if((completedHere||!saved)&&value.state==='ready'&&(value.action?.startsWith('image-')||value.action==='auto-picture'||value.action==='auto-recover'))window.AIEdgeImageControls?.receive(value);
 if('image_requires_reference' in value)window.AIEdgeImageControls?.setReferenceRequired?.(value.image_requires_reference);
 window.AIEdgeImageControls?.markAttention(!!value.image_needs_attention);
 if(value.lighting_needs_attention||saved)window.AIEdgeCameraControls?.markAttention?.(!!value.lighting_needs_attention);
 if(value.controls_save_failed)note('These controls are available for this session. AIEdge could not save them to storage.',true);
 if(value.state==='error'&&value.error==='camera_image_unsupported')window.AIEdgeImageControls?.unavailable();
 if(value.state==='error'&&(value.action?.startsWith('auto-')||value.action?.startsWith('image-')))window.AIEdgeImageControls?.markReload?.(value.action!=='image-load'&&value.error!=='camera_busy'&&value.error!=='camera_setup_busy');
 const imageState=window.AIEdgeImageControls?.status?.()||{};
 $('settings-device-note').textContent=!value.configured?'Configure a camera or choose a saved image in Setup.':value.error==='camera_image_unsupported'?'This firmware requires the camera website for exposure and gain settings.':imageState.auto_attention||imageState.needs_activation?'Restore saved camera settings in Setup → Image before taking pictures.':imageState.loaded?'Exposure and gain controls are available in Setup → Image.':'Load camera controls in Setup to check available settings.';
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
 $('camera-setup-note').hidden=!!value.configured;
 controls();
}
async function loadCamera(){
 try{paintCamera(await json('api/camera-setup'));}
 catch(error){note(window.AIEdgeNotices?.message(error)||error.message,true,active?'setup-status':'camera-action-status',window.AIEdgeNotices?.connection(error));$('camera-setup-note').textContent='Camera configuration unavailable.';}
}
async function cameraAction(action,details={}){
 if(polling||busy)return false;
 if(action==='picture'){
  try{
   if(window.AIEdgeCameraControls?.status?.().dirty||window.AIEdgeImageControls?.status?.().dirty)return fail('Apply your control changes before taking a picture.');
   if(window.AIEdgeImageControls?.status?.().automatic){
    action='auto-picture';details=window.AIEdgeImageControls.autoDetails();
   }else if(window.AIEdgeCameraControls?.status?.().needs_activation||window.AIEdgeImageControls?.status?.().needs_activation||window.AIEdgeImageControls?.status?.().auto_attention)return fail('Apply the pending settings before taking a picture.');
  }
  catch(error){note(error.message,true);return false;}
 }
 polling=true;busy=true;controls();
 window.AIEdgeCameraControls?.setBusy(true);
 window.AIEdgeImageControls?.setBusy(true);
 const target=active?'setup-status':'camera-action-status';note('',false,target);
 const takingPicture=action==='picture'||action==='auto-picture';
 $('reference-working').hidden=!takingPicture;$('reference-working-text').textContent=action==='auto-picture'?'Adjusting light and exposure…':'Taking picture…';$('check-camera').disabled=true;
 try{
  const setup=await json('api/setup');
  let result=await json('api/camera-setup',{method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Setup':setup.token},body:JSON.stringify({action,...details})});
  const job=result.job,deadline=Date.now()+(action==='auto-picture'?180000:30000);
  while(['queued','working'].includes(result.state)){
   if(Date.now()>=deadline)throw Error('The camera request is still pending. Check its status before taking another picture.');
   await new Promise(resolve=>setTimeout(resolve,500));result=await json('api/camera-setup');
   if(result.job!==job)throw Error('The camera request changed in another session. Check the current reference.');
   if(action==='auto-picture'&&result.progress){
    const progress=result.progress;
    $('reference-working-text').textContent=progress.stage==='saving'?'Saving selected settings…':progress.stage==='reference'?'Taking reference picture…':`Adjusting light and exposure · ${progress.shots} picture${progress.shots===1?'':'s'}`;
   }
  }
  paintCamera(result,true);
  if(result.state==='error')throw Error(messages[result.error]||'The camera request failed. Your current reference has been kept.');
  if(takingPicture){await window.AIEdgeCalibration.useReference(result.reference_sha256);window.AIEdgeCameraControls?.pictureTaken();window.AIEdgeImageControls?.pictureTaken(result.image_orientation);}
  else if(action==='lighting-apply')note(result.settings?.active_verified?'Lighting applied.': 'Lighting settings are unchanged.',false,target);
  else if(action==='image-apply')note(result.image_settings?.active_verified?'Image settings applied.':'Image settings are unchanged.',false,target);
  else if(action==='check')note('Camera: '+(result.readiness?.state||'unknown').replaceAll('_',' '),result.readiness?.state!=='ready',target);
  return true;
 }catch(error){note(window.AIEdgeNotices?.message(error)||error.message,true,target,window.AIEdgeNotices?.connection(error));return false;}
 finally{polling=false;busy=false;window.AIEdgeCameraControls?.setBusy(false);window.AIEdgeImageControls?.setBusy(false);$('reference-working').hidden=true;$('check-camera').disabled=false;controls();}
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
async function summary(generation){
 try{
  const [calibration,format,archive]=await Promise.all([json('api/setup'),json('api/reading-format'),json('api/archive').catch(()=>null)]);
  if(!active||generation!==viewGeneration)return;
  const ready=!!calibration.calibration&&!calibration.recovery;
  const profile=window.AIEdgeMeter.selectedProfile?.(calibration,format)??calibration.meter?.profile;
  const bound=!!format.format&&!!format.pipeline_id&&!format.recovery&&!calibration.meter?.recovery&&format.format.pipeline_id===format.pipeline_id&&(!profile||format.format.unit===profile.unit);
  const mqtt=statusSnapshot?.mqtt?.state;
  const types={gas:'Gas',water:'Water',electric:'Electric'};
  const units={ft3:'ft³',m3:'m³',L:'L',gal_us:'US gal',kWh:'kWh'};
  const unit=units[profile?.unit||format.format?.unit];
  const rows=[['Meter',profile&&!calibration.meter?.recovery?types[profile.type]:'Needs review'],['Units',unit||'Needs review'],
   ['Reference and dials',ready&&calibration.calibration.dials?calibration.calibration.dials.length+' dials · '+calibration.calibration.markers.length+' markers':ready?'Saved':'Incomplete'],['Number format',bound?'Saved':'Needs review']];
  const scales=[];
  if(ready&&bound)for(const scale of format.format.dials||[]){
   const dial=calibration.calibration.dials?.[scale.index];
   if(dial)scales.push([dial.name,scale.value_per_revolution.toLocaleString(undefined,{maximumSignificantDigits:15})+' '+unit+'/revolution · '+(dial.direction==='ccw'?'counterclockwise':'clockwise')]);
  }
  if(bound&&format.format.maximum_rate_per_second!=null)
   rows.push(['Maximum rate',(format.format.maximum_rate_per_second*60).toLocaleString(undefined,{maximumSignificantDigits:5})+' '+unit+'/min']);
  const light=camera?.settings?.lighting;
  if(light)rows.push(['Last loaded lighting',(light.source==='builtin'?'Built-in flash':light.type+' strip')+' · '+light.intensity+'%']);
  if(typeof camera?.auto_settings?.automatic==='boolean')rows.push(['Image setup',camera.auto_settings.automatic?'Automatic':'Manual']);
  rows.push(['Capture',camera?(camera.capture_enabled?'On':'Off'):'Unknown']);
  if(camera?.capture_enabled)rows.push(['Capture interval',camera.interval_seconds+' seconds']);
  if(archive?.config)rows.push(['Archive',archive.config.enabled?archive.config.directory:'Off']);
  rows.push(['MQTT',mqtt?(mqtt==='disabled'?'Off':mqtt.replaceAll('_',' ')):'Unknown']);
  function list(id,items){
   const host=$(id);host.replaceChildren();
   for(const [name,value] of items){const row=document.createElement('div'),key=document.createElement('dt'),text=document.createElement('dd');if(name==='MQTT')text.id='setup-summary-mqtt';key.textContent=name;text.textContent=value;row.append(key,text);host.append(row);}
  }
  list('setup-summary',rows);list('setup-scales',scales);$('setup-dial-details').hidden=!scales.length;
 }catch(error){if(active&&generation===viewGeneration)note(error.message,true);}
}
function route(hash){
 if(active&&hash===lastRoute&&hash.startsWith('#setup'))return true;
 // A new visit opens the saved wizard, even if the last visit left an unsubmitted draft.
 if(hash==='#setup'&&visitedSetup&&lastRoute!==hash){location.reload();return true;}
 const enteringSetup=!active;
 lastRoute=hash;
 if(hash==='#calibration'||hash==='#setup'||hash.startsWith('#setup/'))visitedSetup=true;
 routeGeneration++;viewGeneration++;
 if(redoing&&!hash.startsWith('#setup/')&&hash!=='#calibration'){location.reload();return true;}
 if(hash==='#settings'){active=false;moveFormat(false);window.showAppPage('settings');loadCamera();return true;}
 if(hash==='#calibration'||hash==='#setup'||hash.startsWith('#setup/')){if(enteringSetup)loadCamera();show(hash==='#calibration'?'image':hash==='#setup'?'meter':hash.split('/')[1]||'meter');return true;}
 if(active){active=false;moveFormat(false);}
 return false;
}
$('setup-next').onclick=()=>go(steps[Math.min(steps.length-1,steps.indexOf(step)+1)]);
$('setup-back').onclick=()=>go(steps[Math.max(0,steps.indexOf(step)-1)]);
$('restart-setup').onclick=()=>{location.hash='setup/redo';location.reload();};
for(const button of document.querySelectorAll('.setup-steps button'))button.onclick=()=>go(button.dataset.step);
$('image-take-picture').onclick=()=>cameraAction('picture');$('take-reference').onclick=()=>cameraAction('picture');$('retake-reference').onclick=()=>cameraAction('picture');
$('check-camera').onclick=()=>cameraAction('check');$('use-latest').onclick=latest;
$('reference-grid').onclick=()=>{const value=$('reference-grid').getAttribute('aria-pressed')!=='true';$('reference-grid').setAttribute('aria-pressed',String(value));window.AIEdgeCalibration?.setGrid(value);};
let zoom=1;
function setZoom(value){zoom=Math.max(1,Math.min(3,value));$('reference-stage').dataset.zoomed=String(zoom>1);$('calibration-canvas').style.width=(zoom*100)+'%';$('reference-fit').textContent=zoom===1?'Fit':Math.round(zoom*100)+'%';window.AIEdgeCalibration?.draw();}
$('reference-fit').onclick=()=>setZoom(1);$('reference-zoom-in').onclick=()=>setZoom(zoom+.5);$('reference-zoom-out').onclick=()=>setZoom(zoom-.5);
window.updateSetupFlow=controls;
window.AIEdgeFlow={route,renderStatus,statusUnavailable(){statusSnapshot=null;for(const id of ['settings-storage','setup-local-storage','settings-mqtt'])$(id).textContent='Unknown';$('setup-mqtt-note').textContent='MQTT status unavailable.';const mqtt=$('setup-summary-mqtt');if(mqtt)mqtt.textContent='Unknown';for(const id of ['settings-free-space','setup-free-space'])$(id).textContent='—';}};
window.addEventListener('aiedge-calibration-saved',()=>{if(active)controls();});
window.addEventListener('resize',()=>{if(active)controls();});
window.AIEdgeCameraControls?.connect(cameraAction);
window.AIEdgeImageControls?.connect(cameraAction);
route(location.hash);
})();
