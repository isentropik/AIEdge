(() => {
'use strict';
const $=id=>document.getElementById(id),form=$('reading-form'),canvas=$('format-canvas'),ctx=canvas.getContext('2d');
const units={ft3:'ft³',m3:'m³',L:'L',gal_us:'US gal',kWh:'kWh'};
// Provisional until held-out calibration/model error has been measured.
const defaultPositionError=.1;
let loaded=false,busy=false,dirty=false,revision=null,pipeline=null,token=null,dials=[],geometry=[],picture=null,selected=0,imageGeneration=0,referenceDigest=null,positionErrors=new Map(),framing=null,meterUnit=null;
const messages={invalid_maximum_rate:'Enter a maximum rate of zero or greater, or leave it empty.',reading_scale_too_small:'That revolution value is too small to represent in the selected units.',reading_pipeline_changed:'Calibration or the model changed. Reload the format and check each dial.',reading_format_changed_reload:'The format was changed in another session. Reload saved values before trying again.',reading_dial_mapping_mismatch:'The dial list changed. Reload the format.',reading_scales_must_be_nested:'Dial values must have whole-number revolution ratios, such as 1000 and 5.',invalid_reading_scale_or_error:'The dial values or saved reader configuration are invalid. Reload the format.'};
function status(message,error=false){$('format-status').textContent=message;$('format-status').dataset.error=String(error);$('format-status').hidden=!message;}
function controls(){
 for(const input of form.querySelectorAll('input,select'))input.disabled=busy||!pipeline;
 if(meterUnit)$('format-unit').disabled=true;
 $('save-format').disabled=busy||!pipeline||!dials.length||!dirty;
 $('reload-format').disabled=busy;
}
function changed(){dirty=true;status('Unsaved changes');controls();}
function highlight(index){selected=index;draw();}
function draw(){
 if(!picture)return;
 ctx.clearRect(0,0,640,480);const frame=window.AIEdgeImageFraming?.drawImage(ctx,picture,framing||window.AIEdgeImageFraming.identity());if(!frame)ctx.drawImage(picture,0,0,640,480);
 ctx.save();if(frame)ctx.transform(frame.m[0],frame.m[3],frame.m[1],frame.m[4],frame.m[2],frame.m[5]);
 geometry.forEach((dial,i)=>{const b=dial.crop;if(!b)return;ctx.strokeStyle=i===selected?'#d6bdff':'#67d6cf';ctx.lineWidth=i===selected?3:1;ctx.strokeRect(...b);
 const text=dials[i]?.name||'Dial '+(i+1);ctx.font='12px system-ui';const width=ctx.measureText(text).width+10,x=Math.min(b[0],640-width),y=Math.max(0,b[1]-21);ctx.fillStyle='#101115e8';ctx.fillRect(x,y,width,20);ctx.fillStyle='#fff';ctx.fillText(text,x+5,y+14);});
 ctx.restore();$('format-selected').textContent=dials[selected]?.name||'Reference image';
}
function labelUnits(){const unit=units[$('format-unit').value];$('format-scale-label').textContent=unit?`Value (${unit}/rev)`:'Value per revolution';$('format-rate-unit').textContent=(unit||'units')+'/min';}
async function request(path,options={}){
 const response=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(10000),...options});
 const body=await response.json().catch(()=>({error:'Could not read the device response.'}));
 if(!response.ok)throw Error(messages[body.error]||body.error||'Could not save the format.');
 return body;
}
function input(id,label,value,min,max){
 const field=document.createElement('input');field.id=id;field.type='number';field.step='any';field.min=String(min);if(max!==null)field.max=String(max);field.required=true;field.inputMode='decimal';field.setAttribute('aria-label',label);field.value=value??'';field.addEventListener('input',changed);return field;
}
async function loadPreview(digest){
 const generation=++imageGeneration;picture=null;canvas.hidden=true;$('format-image-empty').hidden=false;
 $('format-image-empty').textContent=digest?'Loading reference image…':'Save a calibration first.';
 if(!digest)return;
 try{const image=await window.AIEdgeReferenceImage.load('reference/'+digest);
  if(generation!==imageGeneration)return;
  picture=image;canvas.hidden=false;$('format-image-empty').hidden=true;draw();
 }catch(e){if(generation===imageGeneration)$('format-image-empty').textContent=e.message;}
}
async function load(force=false){
 if(busy||loaded&&!force)return;
 busy=true;controls();status('Loading dial format…');
 try{
  const [saved,setup]=await Promise.all([request('api/reading-format'),request('api/setup')]);
  revision=saved.revision;pipeline=saved.pipeline_id;token=setup.token;dials=saved.dials||[];
  geometry=setup.calibration?.dials||[];picture=null;canvas.hidden=true;$('format-image-empty').hidden=false;
  const stale=!!saved.format&&saved.format.pipeline_id!==pipeline;
  meterUnit=setup.meter?.profile?.unit||null;
  if(setup.meter?.recovery)throw Error('Review Meter and units before editing the number format.');
  const unitsChanged=!!meterUnit&&!!saved.format&&saved.format.unit!==meterUnit;
  $('format-unit-select').hidden=!!meterUnit;$('format-unit-summary').hidden=!meterUnit;
  $('format-unit-text').textContent=units[meterUnit]||'';
  // Never silently transfer physical scales to a changed calibration by array index.
  const mapping=new Map(!stale?(saved.format?.dials||[]).map(d=>[d.index,d]):[]);
  $('format-unit').value=meterUnit||saved.format?.unit||'';$('format-max-rate').value=!stale&&!unitsChanged&&saved.format?.maximum_rate_per_second!=null?saved.format.maximum_rate_per_second*60:'';labelUnits();$('format-dials').replaceChildren();positionErrors=new Map();
  for(const dial of dials){
   const row=document.createElement('div');row.className='format-row';const name=document.createElement('div');name.className='format-name';name.textContent=dial.name;
   const direction=document.createElement('small');direction.textContent=dial.direction==='ccw'?'CCW':'CW';name.append(direction);
   const savedDial=mapping.get(dial.index);
   const scale=input('format-value-'+dial.index,dial.name+' value per revolution',unitsChanged?null:savedDial?.value_per_revolution,0,null);
   positionErrors.set(dial.index,savedDial?.position_error??defaultPositionError);
   scale.addEventListener('focus',()=>highlight(dial.index));
   row.append(name,scale);$('format-dials').append(row);
  }
  dirty=unitsChanged;loaded=true;
  if(!pipeline||!dials.length)status('Save the dial calibration before setting the number format.');
  else if(saved.recovery)status('The saved number format could not be loaded. Enter replacement values; the original file will be kept.',true);
  else if(stale)status('Calibration or the model changed. Enter the values for the current dials.',true);
  else if(unitsChanged)status(`Units changed from ${units[saved.format.unit]} to ${units[meterUnit]}. Enter each dial's value in ${units[meterUnit]} before applying the new format.`,true);
  else status('');
  selected=0;referenceDigest=setup.calibration?.reference_sha256;
  framing=referenceDigest&&setup.image_editor?.image_edit?.reference_sha256===referenceDigest?setup.image_editor.image_edit.edit:null;loadPreview(referenceDigest);
 }catch(e){status(e.message,true);loaded=false;pipeline=null;}
 finally{busy=false;controls();}
}
$('format-max-rate').addEventListener('input',changed);
$('format-unit').addEventListener('change',()=>{labelUnits();changed();});
$('reload-format').onclick=()=>load(true);
async function saveFormat(event){
 event?.preventDefault();if(busy||!loaded||!pipeline){status('Load the current dial format before saving.',true);return false;}if(!form.reportValidity())return false;
 if(!dirty&&revision)return true;
 const values=dials.map(d=>({index:d.index,value_per_revolution:Number($('format-value-'+d.index).value),position_error:positionErrors.get(d.index)})).sort((a,b)=>b.value_per_revolution-a.value_per_revolution);
 if(values.some(d=>!Number.isFinite(d.value_per_revolution)||d.value_per_revolution<=0)){status('Enter positive values per revolution.',true);return false;}
 if(values.some(d=>!Number.isFinite(d.position_error)||d.position_error<0||d.position_error>=.5)){status('Saved reader uncertainty is invalid. Reload the format.',true);return false;}
 const rateText=$('format-max-rate').value;const rate=rateText===''?null:Number(rateText)/60;
 if(rate!==null&&(!Number.isFinite(rate)||rate<0)){status(messages.invalid_maximum_rate,true);return false;}
 const candidate={version:1,pipeline_id:pipeline,unit:$('format-unit').value,dials:values};
 if(rate!==null)candidate.maximum_rate_per_second=rate;
 busy=true;controls();status('Saving…');
 try{const saved=await request('api/reading-format',{method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Setup':token},body:JSON.stringify({revision,format:candidate})});revision=saved.revision;dirty=false;status('');window.dispatchEvent(new Event('aiedge-reading-format-saved'));return true;}
 catch(e){status(e.message,true);return false;}
 finally{busy=false;controls();}
}
form.onsubmit=saveFormat;window.AIEdgeFormat={save:saveFormat};
window.addEventListener('aiedge-calibration-saved',()=>{pipeline=null;loaded=false;controls();status('Calibration changed. Reopen Number format to check the current dials.',true);});
window.addEventListener('aiedge-meter-saved',()=>{loaded=false;pipeline=null;controls();});
window.addEventListener('aiedge-image-edit-saved',event=>{if(event.detail?.reference_sha256===referenceDigest){framing=event.detail.edit;draw();}});
window.openReadingFormat=()=>load();
window.addEventListener('aiedge-refresh-images',event=>{if(event.detail==='format'&&!picture&&!busy&&loaded)loadPreview(referenceDigest);});
window.renderPhysicalReading=(reading,recognition)=>{
 $('meter-value').textContent='—';$('meter-unit').textContent='';
 $('reading-bounds').hidden=true;$('reading-ranges').replaceChildren();
 if(!reading)return;
 if(reading.state==='not_configured'&&recognition&&recognition.state!=='estimated')return;
 const messages={not_configured:'Set the number format to calculate a reading.',inconsistent:'Dial positions disagree. No reading published.',ambiguous:'More than one reading is possible.',invalid:'The number format is invalid.',unavailable:'No reading available.'};
 if(reading.state==='estimated'&&typeof reading.text==='string'){
  $('meter-value').textContent=reading.text;$('meter-unit').textContent=units[reading.unit]||reading.unit;
  $('reading-status').textContent='Estimate · accuracy not yet verified';return;
 }
 if(reading.state==='inconsistent'&&Array.isArray(reading.consistency?.dial_indices)){
  const indices=reading.consistency.dial_indices;
  if(indices.length>1&&indices.length<=16&&indices.every(i=>Number.isInteger(i)&&i>=0&&i<32)){
   $('reading-status').textContent='Dials '+indices.map(i=>i+1).join(', ')+' disagree within the reading tolerances. No total published.';
   return;
  }
 }
 const bounds=reading.bounds;
 if(reading.state==='ambiguous'&&bounds?.state==='bounded'&&Array.isArray(bounds.ranges)&&bounds.ranges.length){
  const unit=units[reading.unit]||reading.unit;
  $('reading-status').textContent='Reading unresolved. No total published.';
  if(typeof bounds.common_integer_prefix==='string'&&/^\d+$/.test(bounds.common_integer_prefix)){
   $('meter-value').textContent=bounds.common_integer_prefix+'…';$('meter-unit').textContent=unit;
   $('reading-status').textContent='Fine reading unresolved. No total published.';
  }
  $('reading-bounds-label').textContent=bounds.ranges.length===1?'Possible range':bounds.ranges.length+' possible ranges';
  for(const range of bounds.ranges){
   const row=document.createElement('li');
   row.textContent=range.lower_text+' – '+range.upper_text+' '+unit;
   $('reading-ranges').append(row);
  }
  $('reading-bounds-note').textContent=bounds.wraps_register?'The ranges cross the register rollover. They depend on the configured dial tolerances.':'These ranges depend on the configured dial tolerances; accuracy is unverified.';
  $('reading-bounds').hidden=false;return;
 }
 if(reading.reason==='reading_pipeline_changed')$('reading-status').textContent='Review the number format after the calibration change.';
 else if(reading.state!=='unavailable'||!['image_unavailable','reading_pipeline_changed'].includes(reading.reason))$('reading-status').textContent=messages[reading.state]||'No reading available.';
};
window.renderPhysicalReading(window.latestReading,window.latestRecognition);
})();
