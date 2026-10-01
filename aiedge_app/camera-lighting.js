/* Lighting choices are saved on the camera; brightness belongs beside the photo. */
(function(root){
'use strict';
const clone=value=>JSON.parse(JSON.stringify(value));
function mode(light){return light.type==='SK6812_RGBW'&&light.channels[3]>0?(light.channels.slice(0,3).some(Boolean)?'custom':'white'):'rgb';}
function chooseMode(light,value){
 const next=clone(light);
 if(value==='white'&&next.type==='SK6812_RGBW')next.channels=[0,0,0,255];
 else if(value==='rgb'){next.channels=next.channels.slice(0,3).concat(0);if(!next.channels.some(Boolean))next.channels=[255,255,255,0];}
 else if(value!=='custom')throw Error('Unsupported lighting mode.');
 return next;
}
function equal(a,b){return !!a&&!!b&&['source','pin','type','count','intensity'].every(key=>a[key]===b[key])&&a.channels.every((value,index)=>value===b.channels[index]);}
const api={mode,chooseMode,equal};
if(typeof module!=='undefined'){module.exports=api;return;}
const $=id=>document.getElementById(id);
let saved=null,draft=null,revision=null,capabilities=null,needsActivation=false,stale=false,working=false,runner=null,configured=false,selectedMode='rgb',automatic=false,lastJob=null;
function update(){
 const strip=draft?.source==='strip',white=draft?.type==='SK6812_RGBW',selected=selectedMode;
 $('lighting-fields').hidden=!draft;$('lighting-strip-fields').hidden=!strip;
 $('lighting-mode-label').hidden=!strip||!white;$('lighting-color-label').hidden=!strip||selected!=='rgb';
 $('lighting-custom').hidden=!strip||selected!=='custom';$('lighting-white-channel').hidden=!white;
 $('image-brightness').hidden=!draft||automatic;
 for(const input of document.querySelectorAll('#lighting-fields input, #lighting-fields select, #image-brightness input'))input.disabled=working;
 $('load-lighting').disabled=working||!configured;$('apply-saved-lighting').hidden=!draft||!needsActivation;$('apply-saved-lighting').disabled=working;
 $('lighting-connection-note').hidden=!!draft;
 if(draft){
  $('lighting-source').value=draft.source;$('lighting-type').value=draft.type;$('lighting-count').value=draft.count;
  $('lighting-mode').value=selected;
  $('lighting-color').value='#'+draft.channels.slice(0,3).map(v=>Math.max(0,Math.min(255,v||0)).toString(16).padStart(2,'0')).join('');
  for(let index=0;index<4;index++)$('lighting-channel-'+index).value=draft.channels[index];
  $('lighting-intensity').value=draft.intensity;$('lighting-percent').textContent=draft.intensity+'%';
 }
 window.updateSetupFlow?.();
}
function change(){
 if(!draft||working)return;
 const light=clone(draft);light.source=$('lighting-source').value;light.type=$('lighting-type').value;
 light.pin=light.source==='builtin'?capabilities.builtin_pin:Number($('lighting-pin').value);
 light.count=Number($('lighting-count').value);light.intensity=Number($('lighting-intensity').value);
 if(light.type!=='SK6812_RGBW')light.channels[3]=0;
 if(light.type!==draft.type){if(light.type==='SK6812_RGBW')light.channels=[0,0,0,255];selectedMode=mode(light);}
 draft=light;update();
}
function receive(result){
 const settings=result.settings;if(!settings?.lighting||!settings.capabilities)return;
 if(result.job&&result.job===lastJob)return;
 if(result.job)lastJob=result.job;
 const before=revision;
 saved=clone(settings.lighting);draft=clone(saved);selectedMode=mode(draft);revision=settings.revision;capabilities=settings.capabilities;needsActivation=!!settings.needs_activation;
 if(result.action==='lighting-apply'&&settings.active_verified===true&&!needsActivation)root.AIEdgeImageControls?.rebaseRevision(before,revision);
 const select=$('lighting-pin');select.replaceChildren();
 for(const pin of capabilities.pins){const option=document.createElement('option');option.value=String(pin.pin);option.textContent='GPIO '+pin.pin+(pin.available?'':' · unavailable');option.disabled=!pin.available;select.append(option);}
 select.value=String(draft.pin);
 if(settings.sensor)$('image-sensor').textContent=settings.sensor;
 if(result.action==='lighting-apply'&&settings.changed)stale=true;
 update();
}
async function apply(){
 if(!draft||(!needsActivation&&equal(saved,draft)))return true;
 if(![draft.count,draft.pin,draft.intensity,...draft.channels].every(Number.isInteger)||draft.count<1||draft.count>100000||draft.intensity<0||draft.intensity>100||draft.channels.some(v=>v<0||v>255))throw Error('Check the LED count, brightness and channel values.');
 return runner('lighting-apply',{revision,lighting:clone(draft)});
}
for(const id of ['lighting-source','lighting-type','lighting-pin','lighting-count','lighting-intensity'])$(id).oninput=change;
$('lighting-mode').onchange=()=>{if(!draft||working)return;selectedMode=$('lighting-mode').value;draft=chooseMode(draft,selectedMode);update();};
$('lighting-color').oninput=()=>{if(!draft||working)return;const color=$('lighting-color').value;if(!/^#[0-9a-f]{6}$/i.test(color))return;selectedMode='rgb';draft.channels=[1,3,5].map(at=>parseInt(color.slice(at,at+2),16)).concat(0);update();};
for(let index=0;index<4;index++)$('lighting-channel-'+index).oninput=()=>{if(!draft||working)return;draft.channels[index]=Number($('lighting-channel-'+index).value);update();};
$('load-lighting').onclick=()=>runner?.('lighting-load');
$('apply-saved-lighting').onclick=()=>apply();
root.AIEdgeCameraControls={receive,apply,connect(fn){runner=fn;},setBusy(value){working=value;update();},configure(value){configured=!!value;update();},markAttention(){needsActivation=true;update();},
 setAutomatic(value){if(automatic===!!value)return;automatic=!!value;update();},
 // A peer can advance the revision only from this exact verified baseline;
 // a stale or independently changed configuration still fails server checks.
 rebaseRevision(before,after){if(revision===before&&typeof after==='string'&&/^[a-f0-9]{64}$/.test(after))revision=after;},
 requiresPicture(){return stale||needsActivation||!!draft&&!equal(saved,draft);},pictureTaken(){stale=false;update();},needsAttention(){return needsActivation;},
 status(){return {loaded:!!draft,dirty:!!draft&&!equal(saved,draft),needs_activation:needsActivation,revision};}};
update();
})(typeof window!=='undefined'?window:globalThis);
