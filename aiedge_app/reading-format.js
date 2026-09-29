(() => {
'use strict';
const $=id=>document.getElementById(id),form=$('reading-form'),canvas=$('format-canvas'),ctx=canvas.getContext('2d');
const units={ft3:'ft³',m3:'m³',L:'L',gal_us:'US gal',kWh:'kWh'};
let loaded=false,busy=false,dirty=false,revision=null,pipeline=null,token=null,dials=[],geometry=[],picture=null,selected=0;
const messages={reading_scale_too_small:'That revolution value is too small to represent in the selected units.',reading_pipeline_changed:'Calibration or the model changed. Reload the format and check each dial.',reading_format_changed_reload:'The format was changed in another session. Reload saved values before trying again.',reading_dial_mapping_mismatch:'The dial list changed. Reload the format.',reading_scales_must_be_nested:'Dial values must have whole-number revolution ratios, such as 1000 and 5.',invalid_reading_scale_or_error:'Enter positive revolution values and tolerances from 0 to less than 0.5.'};
function status(message,error=false){$('format-status').textContent=message;$('format-status').dataset.error=String(error);}
function controls(){
 for(const input of form.querySelectorAll('input,select'))input.disabled=busy||!pipeline;
 $('save-format').disabled=busy||!pipeline||!dials.length||!dirty;
 $('reload-format').disabled=busy;
}
function changed(){dirty=true;status('Unsaved changes');controls();}
function highlight(index){selected=index;draw();}
function draw(){
 if(!picture)return;
 ctx.clearRect(0,0,640,480);ctx.drawImage(picture,0,0,640,480);
 geometry.forEach((dial,i)=>{const b=dial.crop;if(!b)return;ctx.strokeStyle=i===selected?'#d6bdff':'#67d6cf';ctx.lineWidth=i===selected?3:1;ctx.strokeRect(...b);
 const text=dials[i]?.name||'Dial '+(i+1);ctx.font='12px system-ui';const width=ctx.measureText(text).width+10,x=Math.min(b[0],640-width),y=Math.max(0,b[1]-21);ctx.fillStyle='#101115e8';ctx.fillRect(x,y,width,20);ctx.fillStyle='#fff';ctx.fillText(text,x+5,y+14);});
 $('format-selected').textContent=dials[selected]?.name||'Reference image';
}
function labelUnits(){const unit=units[$('format-unit').value];$('format-scale-label').textContent=unit?`Value (${unit}/rev)`:'Value per revolution';}
async function request(path,options={}){
 const response=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(10000),...options});
 const body=await response.json().catch(()=>({error:'Could not read the device response.'}));
 if(!response.ok)throw Error(messages[body.error]||body.error||'Could not save the format.');
 return body;
}
function input(id,label,value,min,max){
 const field=document.createElement('input');field.id=id;field.type='number';field.step='any';field.min=String(min);if(max!==null)field.max=String(max);field.required=true;field.inputMode='decimal';field.setAttribute('aria-label',label);field.value=value??'';field.addEventListener('input',changed);return field;
}
async function load(force=false){
 if(busy||loaded&&!force)return;
 busy=true;controls();status('Loading dial format…');
 try{
  const [saved,setup]=await Promise.all([request('api/reading-format'),request('api/setup')]);
  revision=saved.revision;pipeline=saved.pipeline_id;token=setup.token;dials=saved.dials||[];
  geometry=setup.calibration?.dials||[];picture=null;canvas.hidden=true;$('format-image-empty').hidden=false;
  const stale=!!saved.format&&saved.format.pipeline_id!==pipeline;
  // Never silently transfer physical scales to a changed calibration by array index.
  const mapping=new Map(!stale?(saved.format?.dials||[]).map(d=>[d.index,d]):[]);
  $('format-unit').value=saved.format?.unit||'';labelUnits();$('format-dials').replaceChildren();
  for(const dial of dials){
   const row=document.createElement('div');row.className='format-row';const name=document.createElement('div');name.className='format-name';name.textContent=dial.name;
   const direction=document.createElement('small');direction.textContent=dial.direction==='ccw'?'CCW':'CW';name.append(direction);
   const savedDial=mapping.get(dial.index);
   const scale=input('format-value-'+dial.index,dial.name+' value per revolution',savedDial?.value_per_revolution,0,null);
   const error=input('format-error-'+dial.index,dial.name+' tolerance',savedDial?.position_error,0,.499999);
   for(const field of [scale,error])field.addEventListener('focus',()=>highlight(dial.index));
   row.append(name,scale,error);$('format-dials').append(row);
  }
  dirty=false;loaded=true;
  if(!pipeline||!dials.length)status('Save the dial calibration before setting the number format.');
  else if(saved.recovery)status('The saved number format could not be loaded. Enter replacement values; the original file will be kept.',true);
  else if(stale)status('Calibration or the model changed. Enter the values for the current dials.',true);
  else status('');
  if(setup.calibration?.reference_sha256){
   const image=new Image();image.src='reference/'+setup.calibration.reference_sha256;
   try{await image.decode();picture=image;canvas.hidden=false;$('format-image-empty').hidden=true;selected=0;draw();}
   catch{$('format-image-empty').textContent='Reference image could not be loaded.';}
  }
 }catch(e){status(e.message,true);loaded=false;}
 finally{busy=false;controls();}
}
$('format-unit').addEventListener('change',()=>{labelUnits();changed();});
$('reload-format').onclick=()=>load(true);
form.onsubmit=async event=>{
 event.preventDefault();if(busy||!pipeline||!form.reportValidity())return;
 const values=dials.map(d=>({index:d.index,value_per_revolution:Number($('format-value-'+d.index).value),position_error:Number($('format-error-'+d.index).value)})).sort((a,b)=>b.value_per_revolution-a.value_per_revolution);
 if(values.some(d=>!Number.isFinite(d.value_per_revolution)||d.value_per_revolution<=0||!Number.isFinite(d.position_error)||d.position_error<0||d.position_error>=.5)){status(messages.invalid_reading_scale_or_error,true);return;}
 busy=true;controls();status('Saving…');
 try{const saved=await request('api/reading-format',{method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Setup':token},body:JSON.stringify({revision,format:{version:1,pipeline_id:pipeline,unit:$('format-unit').value,dials:values}})});revision=saved.revision;dirty=false;status('Format saved');window.dispatchEvent(new Event('aiedge-reading-format-saved'));}
 catch(e){status(e.message,true);}
 finally{busy=false;controls();}
};
window.addEventListener('aiedge-calibration-saved',()=>{pipeline=null;loaded=false;controls();status('Calibration changed. Reopen Number format to check the current dials.',true);});
window.openReadingFormat=()=>load();
window.renderPhysicalReading=reading=>{
 $('meter-value').textContent='—';$('meter-unit').textContent='';
 if(!reading)return;
 const messages={not_configured:'Set the number format to calculate a reading.',inconsistent:'Dial positions disagree. No reading published.',ambiguous:'More than one reading is possible.',invalid:'The number format is invalid.',unavailable:'No reading available.'};
 if(reading.state==='estimated'&&typeof reading.text==='string'){
  $('meter-value').textContent=reading.text;$('meter-unit').textContent=units[reading.unit]||reading.unit;
  $('reading-status').textContent='Estimate · accuracy not yet verified';return;
 }
 if(reading.reason==='reading_pipeline_changed')$('reading-status').textContent='Review the number format after the calibration change.';
 else if(reading.state!=='unavailable'||!['image_unavailable','reading_pipeline_changed'].includes(reading.reason))$('reading-status').textContent=messages[reading.state]||'No reading available.';
};
window.renderPhysicalReading(window.latestReading);
})();
