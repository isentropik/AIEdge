(function(root){
'use strict';
const units={ft3:'Cubic feet (ft³)',m3:'Cubic metres (m³)',L:'Litres (L)',US_gal:'US gallons',imp_gal:'Imperial gallons',Wh:'Watt-hours (Wh)',kWh:'Kilowatt-hours (kWh)'};
const choices={gas:['ft3','m3'],water:['L','m3','US_gal','imp_gal','ft3'],electricity:['Wh','kWh']};
function validateProfile(p){
 if(!p||p.version!==1||!choices[p.kind]||!choices[p.kind].includes(p.source_unit)||!choices[p.kind].includes(p.display_unit)||
 !Number.isFinite(p.units_per_count)||p.units_per_count<=0||typeof p.has_secondary!=='boolean'||!Number.isFinite(p.secondary_units_per_revolution)||
 (p.has_secondary?p.secondary_units_per_revolution<=0:p.secondary_units_per_revolution!==0)||p.confirmed!==true)throw Error('Check the meter type, units and positive scales.');return p;
}
function validateSaved(s){
 if(!s||typeof s.revision!=='string'||!/^[a-f0-9]{64}$/.test(s.revision)||typeof s.model_compatible!=='boolean'||!['not_integrated','not_configured','calibration_required','pending','display_only'].includes(s.activation))throw Error('Unsupported settings response');
 if(s.profile!==null)validateProfile(s.profile);return s;
}
function mount(doc,fetcher){
 const n=id=>doc.getElementById(id);let revision=null,busy=false,locked=false;
 const say=text=>{n('profile-message').textContent=text;};
 function controls(){n('profile-load').disabled=busy;n('profile-save').disabled=busy||!revision;n('profile-fields').disabled=busy||!revision;}
 function setUnits(id,kind,selected){const node=n(id);node.replaceChildren();for(const key of ['',...(choices[kind]||[])]){const option=doc.createElement('option');option.value=key;option.textContent=key?units[key]:'Choose a unit';node.append(option);}node.value=selected||'';}
 function secondary(){n('secondary-fields').hidden=!n('meter-secondary').checked;n('meter-revolution').required=n('meter-secondary').checked;}
 function lock(value){locked=value;for(const id of ['meter-kind','meter-source','meter-multiplier','meter-secondary','meter-revolution'])n(id).disabled=value;n('scale-lock').hidden=!value;}
 async function request(options){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
 try{const r=await fetcher('/meter_profile',{cache:'no-store',credentials:'same-origin',redirect:'error',...options,signal:controller.signal});const body=await r.json();if(!r.ok){const e=Error(body.error||'Request failed');e.status=r.status;throw e;}return body;}finally{clearTimeout(timer);}}
 async function load(){if(busy)return;busy=true;revision=null;controls();say('Reading saved settings…');
 try{const s=validateSaved(await request({method:'GET'})),p=s.profile;revision=s.revision;lock(!!p);
 n('meter-kind').value=p?p.kind:'';setUnits('meter-source',p?p.kind:'',p?p.source_unit:'');setUnits('meter-display',p?p.kind:'',p?p.display_unit:'');n('meter-multiplier').value=p?String(p.units_per_count):'';n('meter-secondary').checked=p?p.has_secondary:false;n('meter-revolution').value=p&&p.has_secondary?String(p.secondary_units_per_revolution):'';n('meter-confirm').checked=false;secondary();
 say(s.activation==='display_only'?'Display units are active for consumption diagnostics and accounting status. Stored quantities and legacy readings keep their original units.':(p?'Saved details need a matching calibration before they can be applied.':'Choose the meter type and check its printed units. Nothing has been saved.'));
 }catch(_){say('Could not load meter settings. Reload when the device is available. Your form has not been submitted.');}finally{busy=false;controls();}}
 async function save(event){if(event)event.preventDefault();if(busy||!revision)return;
 let profile;try{profile=validateProfile({version:1,kind:n('meter-kind').value,source_unit:n('meter-source').value,display_unit:n('meter-display').value,units_per_count:Number(n('meter-multiplier').value),has_secondary:n('meter-secondary').checked,secondary_units_per_revolution:n('meter-secondary').checked?Number(n('meter-revolution').value):0,confirmed:n('meter-confirm').checked});}catch(e){say(e.message);return;}
 busy=true;controls();say('Saving meter details…');
 try{const s=await request({method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Revision':revision},body:JSON.stringify(profile)});if(!((s.status==='saved_not_active'&&s.active_changed===false)||(s.status==='saved_display_only'&&s.active_changed===true)))throw Error('Unexpected save response');say(s.status==='saved_display_only'?'Saved. Display units apply now to consumption diagnostics and accounting status. Stored quantities and legacy readings are unchanged.':'Saved, but not active. This meter needs a matching calibration.');}
 catch(e){say(e.status===409?'The saved settings changed, the device is busy, or the physical scale is locked. Reload before trying again.':'Save could not be confirmed. Reload to check what was saved before trying again.');}
 finally{revision=null;busy=false;controls();}}
 n('meter-kind').addEventListener('change',()=>{if(locked)return;setUnits('meter-source',n('meter-kind').value,'');setUnits('meter-display',n('meter-kind').value,'');n('meter-confirm').checked=false;});
 n('meter-secondary').addEventListener('change',secondary);n('profile-form').addEventListener('input',()=>{n('meter-confirm').checked=false;});
 // A checkbox's own input event must retain its newly selected state.
 n('meter-confirm').addEventListener('input',e=>e.stopPropagation());
 n('profile-load').addEventListener('click',load);n('profile-form').addEventListener('submit',save);controls();return {load,save};
}
const api={choices,validateProfile,validateSaved,mount};if(typeof module!=='undefined')module.exports=api;
if(typeof document!=='undefined')mount(document,root.fetch.bind(root)).load();
})(typeof window!=='undefined'?window:globalThis);
