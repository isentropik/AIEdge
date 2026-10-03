/* Saved sensor controls. Editing a slider never takes a photo or writes to SD. */
(function(root){
'use strict';
const names=['auto_exposure','dsp_exposure','exposure','compensation','auto_gain','gain','gain_limit','mirror','flip'];
const boolean=new Set(['auto_exposure','dsp_exposure','auto_gain','mirror','flip']);
const clone=value=>JSON.parse(JSON.stringify(value));
function equal(a,b){return !!a&&!!b&&names.every(name=>a[name]===b[name]);}
function validate(value,model){
 if(!value||Object.keys(value).length!==names.length||!['OV2640','OV3660','OV5640'].includes(model))return false;
 const ranges={exposure:[0,1200],compensation:model==='OV2640'?[-2,2]:[-5,5],gain:[0,30],gain_limit:[0,6]};
 return names.every(name=>boolean.has(name)?typeof value[name]==='boolean':Number.isInteger(value[name])&&value[name]>=ranges[name][0]&&value[name]<=ranges[name][1]);
}
function automatic(value,on){return {...value,auto_exposure:!!on,auto_gain:!!on};}
if(typeof module==='object'){module.exports={equal,validate,automatic};return;}
const $=id=>document.getElementById(id);
let saved=null,draft=null,revision=null,caps=null,configured=false,working=false,runner=null,needsActivation=false,requiresReference=false,orientationReady=false,photoControls=null,photoStale=false,imageStep=false,lastJob=null;
let autoMode=null,autoAttention=false,autoSupported=null,reloadRequired=false;
function update(){
 const auto=autoMode===true;
 $('image-controls').setAttribute('data-automatic',String(auto&&autoSupported!==false&&!autoAttention));
 $('sensor-controls').hidden=!draft;$('image-manual-controls').hidden=auto;
 $('image-controls-note').hidden=!!draft;$('load-image-controls').hidden=!!draft&&!needsActivation&&!autoAttention&&!reloadRequired;
 $('load-image-controls').textContent=draft?'Reload saved settings':'Load camera controls';
 $('load-image-controls').disabled=working||!configured;
 $('apply-saved-image-controls').hidden=!draft||(!needsActivation&&!autoAttention);$('apply-saved-image-controls').disabled=working;
 $('apply-saved-image-controls').textContent=autoAttention?'Restore saved settings':'Activate saved settings';
 $('auto-capture-note').hidden=!auto||autoSupported!==false;
 $('auto-capture-note').textContent='Auto setup is unavailable on this camera firmware. Choose manual controls.';
 for(const input of document.querySelectorAll('#sensor-controls input,#sensor-controls select'))input.disabled=working;
 if(draft){
  $('image-auto').checked=auto;
  for(const [id,name] of [['image-auto-exposure','auto_exposure'],['image-dsp-exposure','dsp_exposure'],['image-auto-gain','auto_gain']])$(id).checked=draft[name];
  for(const [id,name] of [['exposure','exposure'],['compensation','compensation'],['gain','gain']]){$('image-'+id).value=String(draft[name]);$('image-'+id+'-value').textContent=String(draft[name]);}
  $('image-compensation').min=String(-caps.compensation_limit);$('image-compensation').max=String(caps.compensation_limit);
  $('image-gain-limit').value=String(draft.gain_limit);
  $('image-exposure-row').hidden=draft.auto_exposure;$('image-compensation-row').hidden=!draft.auto_exposure;
  $('image-gain-row').hidden=draft.auto_gain;$('image-gain-limit-row').hidden=!draft.auto_gain;
 }
 for(const [id,name] of [['image-mirror','mirror'],['image-flip','flip']]){
  $(id).hidden=!draft||!imageStep;$(id).disabled=working;$(id).setAttribute('aria-pressed',String(!!draft?.[name]));
 }
 const x=draft&&photoControls&&draft.mirror!==photoControls.mirror?-1:1,y=draft&&photoControls&&draft.flip!==photoControls.flip?-1:1;
 $('calibration-canvas').style.transform=imageStep&&draft&&photoControls?`scale(${x},${y})`:'';
 root.AIEdgeCameraControls?.setAutomatic?.(auto);
 root.updateSetupFlow?.();
}
function change(name,value){if(!draft||working)return;draft={...draft,[name]:value};update();}
function receive(result){
 const settings=result.image_settings;
 if(!settings?.controls||!settings.capabilities||!validate(settings.controls,settings.capabilities.model))return;
 if(result.job&&result.job===lastJob)return;
 if(result.job)lastJob=result.job;
 const wasChanged=['image-apply','auto-picture'].includes(result.action)&&settings.changed;
 const before=revision;
 saved=clone(settings.controls);draft=clone(saved);revision=settings.revision;caps=settings.capabilities;
 reloadRequired=false;
 needsActivation=!!settings.needs_activation;requiresReference=!!settings.requires_reference;
 if(['image-apply','auto-picture','auto-recover'].includes(result.action)&&settings.active_verified===true&&!needsActivation)root.AIEdgeCameraControls?.rebaseRevision(before,revision);
 if(wasChanged){photoStale=true;orientationReady=false;}
 $('image-sensor').textContent=caps.model;update();
}
async function apply(){
 if(autoAttention)return runner('auto-recover',{revision});
 if(!draft||(!needsActivation&&equal(saved,draft)))return true;
 if(!validate(draft,caps.model))throw Error('Check the exposure and gain values.');
 return runner('image-apply',{revision,controls:clone(draft)});
}
$('load-image-controls').onclick=()=>runner?.('image-load');
$('apply-saved-image-controls').onclick=()=>apply();
$('image-auto').onchange=async()=>{if(!draft||working)return;try{await runner('auto-mode',{automatic:$('image-auto').checked});}finally{update();}};
for(const [id,name] of [['image-auto-exposure','auto_exposure'],['image-dsp-exposure','dsp_exposure'],['image-auto-gain','auto_gain']])$(id).onchange=()=>change(name,$(id).checked);
for(const [id,name] of [['image-exposure','exposure'],['image-compensation','compensation'],['image-gain','gain'],['image-gain-limit','gain_limit']])$(id).oninput=()=>change(name,Number($(id).value));
for(const [id,name] of [['image-mirror','mirror'],['image-flip','flip']])$(id).onclick=()=>change(name,!draft[name]);
root.AIEdgeImageControls={receive,apply,receiveAuto(value){
 if(!value||typeof value.automatic!=='boolean')return;
 if(autoMode!==null&&autoMode!==value.automatic)photoStale=true;
 autoMode=value.automatic;autoAttention=!!value.needs_attention;autoSupported=value.supported;update();
 },autoDetails(){
 if(!draft||!revision)throw Error('Load the camera controls before taking a picture.');
 if(autoAttention)throw Error('Restore the saved settings before taking another picture.');
 if(autoSupported===false)throw Error('Auto setup is unavailable on this camera firmware. Choose manual controls.');
 return {revision,orientation:Number(draft.mirror)+2*Number(draft.flip)};
 },connect(fn){runner=fn;},setBusy(value){working=!!value;update();},configure(value){configured=!!value;update();},
 setStep(value){imageStep=value==='image';update();},markAttention(value=true){needsActivation=!!value;update();},
 markReload(){reloadRequired=true;photoStale=true;update();},
 unavailable(){if(!draft)$('image-controls-note').textContent='Image controls are unavailable on this camera firmware.';update();},
 rebaseRevision(before,after){if(revision===before&&typeof after==='string'&&/^[a-f0-9]{64}$/.test(after))revision=after;},
 requiresPicture(){return photoStale||requiresReference&&!orientationReady||!!draft&&(autoMode?draft.mirror!==saved.mirror||draft.flip!==saved.flip:!equal(saved,draft))||needsActivation||autoAttention;},
 referenceChanged(){photoControls=null;orientationReady=false;update();},
 pictureTaken(orientation=null){photoControls=Number.isInteger(orientation)&&orientation>=0&&orientation<=3?{mirror:!!(orientation&1),flip:!!(orientation&2)}:null;orientationReady=photoControls!==null;photoStale=false;update();},
 status(){return {loaded:!!draft,dirty:!!draft&&!equal(saved,draft),needs_activation:needsActivation,requires_reference:requiresReference,automatic:autoMode===true,auto_attention:autoAttention,revision};}
};
update();
})(typeof window==='object'?window:globalThis);
