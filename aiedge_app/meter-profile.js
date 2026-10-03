(() => {
'use strict';
const $=id=>document.getElementById(id),form=$('meter-form');
const units={ft3:'Cubic feet (ft³)',m3:'Cubic metres (m³)',L:'Litres (L)',gal_us:'US gallons',kWh:'Kilowatt-hours (kWh)'};
const supported={gas:['ft3','m3'],water:['ft3','m3','L','gal_us'],electric:['kWh']};
let loaded=false,busy=false,revision=null,token=null,profile=null,suggestedUnit='';
const errors={meter_profile_invalid:'Choose a meter type and its units.',meter_profile_changed_reload:'Meter choices changed in another session. Reload them before continuing.',saved_meter_profile_invalid:'The saved meter choices could not be read. Select replacement choices; the original file will be kept.'};
function note(message,error=false){$('meter-status').textContent=message;$('meter-status').hidden=!message;$('meter-status').dataset.error=String(error);}
function controls(){
 $('meter-type').disabled=busy||!loaded;$('profile-unit').disabled=busy||!loaded||!supported[$('meter-type').value];
 $('meter-retry').hidden=loaded||busy;$('meter-retry').disabled=busy;
}
function choices(){
 const selected=$('profile-unit').value||suggestedUnit,allowed=supported[$('meter-type').value]||[];
 $('profile-unit').replaceChildren();
 const empty=document.createElement('option');empty.value='';empty.textContent='Select units';$('profile-unit').append(empty);
 for(const key of allowed){const option=document.createElement('option');option.value=key;option.textContent=units[key];$('profile-unit').append(option);}
 $('profile-unit').value=allowed.includes(selected)?selected:allowed.length===1?allowed[0]:'';controls();
}
async function request(path,options={}){
 const response=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(10000),...options});
 const result=await response.json().catch(()=>({error:'The app returned an unreadable response.'}));
 if(!response.ok)throw Error(errors[result.error]||result.error||'The app did not respond.');
 return result;
}
async function load(force=false){
 if(busy||loaded&&!force)return loaded;
 busy=true;controls();note('Loading meter choices…');
 try{
  const [setup,format]=await Promise.all([request('api/setup'),request('api/reading-format')]);
  if(!setup.available||!setup.token||!setup.meter)throw Error('Meter setup is unavailable. Check the app and retry.');
  token=setup.token;revision=setup.meter.revision;profile=setup.meter.profile;
  suggestedUnit=profile?.unit||format.format?.unit||'';
  $('meter-type').value=profile?.type||'';$('profile-unit').value='';loaded=true;choices();
  note(setup.meter.recovery?'The saved meter choices could not be read. Select replacements; the original file will be kept.':'',!!setup.meter.recovery);
  return true;
 }catch(error){loaded=false;note(error.message,true);return false;}
 finally{busy=false;controls();}
}
async function save(event){
 event?.preventDefault();
 if(busy)return false;
 if(!loaded){note('Load meter choices before continuing.',true);return false;}
 const type=$('meter-type').value,unit=$('profile-unit').value;
 if(!supported[type]?.includes(unit)){note(errors.meter_profile_invalid,true);$('meter-type').value?$('profile-unit').focus():$('meter-type').focus();return false;}
 const unitChanged=profile?.unit!==unit;
 busy=true;controls();note('Saving…');
 try{
  const result=await request('api/setup/meter',{method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Setup':token},body:JSON.stringify({revision,profile:{version:1,type,unit}})});
  if(!result.revision||result.profile?.type!==type||result.profile?.unit!==unit)throw Error('The meter choices save could not be verified. Reload before trying again.');
  profile=result.profile;revision=result.revision;note('');if(unitChanged)window.dispatchEvent(new Event('aiedge-meter-saved'));return true;
 }catch(error){loaded=false;note(error.message,true);return false;}
 finally{busy=false;controls();}
}
$('meter-type').addEventListener('change',()=>{choices();note('');});$('profile-unit').addEventListener('change',()=>note(''));
$('meter-retry').onclick=()=>load(true);form.onsubmit=save;
window.AIEdgeMeter={load,save,status:()=>({loaded,busy,profile})};controls();
})();
