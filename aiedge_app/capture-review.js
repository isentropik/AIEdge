(() => {
'use strict';
const $=id=>document.getElementById(id);
const drafts=new Map();let current=null,token=null,request=0,saving=false,conflicted=false,imageReady=false,referencePicture=null,mapMode=false,selected=0,imageTimer=null;
const time=value=>new Date(value).toLocaleString();
function notice(message,error=false){$('review-status').textContent=message;$('review-status').dataset.error=String(error);}
function values(){return [...$('review-dials').querySelectorAll('input')].map(input=>input.value.trim()===''?null:Number(input.value));}
function key(){return current?current.capture.sha256+':'+current.context?.id:null;}
function remembered(){
 if(!current?.context)return;
 const entries=values(),saved=current.review?.positions||current.context.dials.map(()=>null);
 if(JSON.stringify(entries)===JSON.stringify(saved)){drafts.delete(key());return;}
 drafts.set(key(),{revision:current.review?.revision||null,values:entries});
 if(drafts.size>100)drafts.delete(drafts.keys().next().value);
}
function changed(showNotice=true){
 remembered();const edited=JSON.stringify(values())!==JSON.stringify(current?.review?.positions||current?.context?.dials.map(()=>null));
 $('review-save').disabled=saving||conflicted||!imageReady||!current?.context||!!current.review&&!edited;
 if(!conflicted&&showNotice)notice(edited?'Unsaved review.':'');
}
async function json(path,options={}){
 const response=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(8000),...options});
 let result;try{result=await response.json();}catch{throw Error('The app did not return a valid review response.');}
 if(!response.ok){const error=Error(result.error||'Review could not be loaded.');error.status=response.status;throw error;}
 return result;
}
function clear(){
 clearTimeout(imageTimer); imageReady=false;referencePicture=null;mapMode=false;selected=0;$('review-map').hidden=true;$('review-map-view').hidden=true;$('review-capture-view').setAttribute('aria-pressed','true');$('review-map-view').setAttribute('aria-pressed','false');$('review-caption').textContent='Original capture';$('review-dials').replaceChildren();$('review-save').disabled=true;$('review-image').hidden=true;
 $('review-empty').hidden=false;$('review-empty').textContent='Loading image…';
 $('review-original').hidden=true;$('review-reference-link').hidden=true;$('review-reload').hidden=true;
 $('review-meta').textContent='';$('review-repeat').hidden=true;notice('');
}
async function open(eventId,reload=false){
 remembered();const serial=++request;current=null;conflicted=false;saving=false;
 $('capture-list').hidden=true;$('capture-detail').hidden=false;clear();
 try{
  const [result,setup]=await Promise.all([json('api/reviews/'+eventId),json('api/setup')]);
  if(serial!==request)return;
  current=result;token=setup.token;
  const capture=result.capture,context=result.context,review=result.review;
  $('review-meta').textContent='Captured '+time(capture.captured_at);
  imageTimer=setTimeout(()=>{if(serial===request&&!imageReady){$('review-image').removeAttribute('src');$('review-image').onerror();}},10000);
  $('review-image').src='image/'+capture.sha256;
  $('review-original').href='image/'+capture.sha256;$('review-original').hidden=false;
  const repeat=capture.matching_captures>1;
  $('review-repeat').hidden=!repeat;
  $('review-repeat').textContent=repeat?'Same image in '+capture.matching_captures+' captures. One review applies to all.':'';
  if(!context){notice('Save a calibration before entering dial readings.',true);return;}
  let entries=review?.positions||context.dials.map(()=>null);
  const draft=drafts.get(key());
  if(!reload&&draft&&draft.revision===(review?.revision||null))entries=draft.values;
  else drafts.delete(key());
  for(const [i,dial] of context.dials.entries()){
   const row=document.createElement('label');row.className='review-row';
   const name=document.createElement('span');name.className='review-name';
   const number=document.createElement('span');number.className='review-number';number.textContent=i+1;
   const text=document.createElement('span');text.textContent=dial.name;
   name.append(number,text);
   const input=document.createElement('input');input.type='number';input.min='0';input.max='9.999999999';input.step='any';input.inputMode='decimal';
   input.placeholder='Unknown';input.value=entries[i]===null?'':String(entries[i]);input.setAttribute('aria-label',dial.name+' position from 0 up to 10');
   input.oninput=changed;input.onfocus=()=>{selected=i;drawMap();};row.append(name,input);$('review-dials').append(row);
  }
  if(context.calibration?.reference_sha256){
   $('review-map-view').hidden=false;
  }
  changed();
  if(review&&JSON.stringify(entries)===JSON.stringify(review.positions))notice('Review saved · '+review.positions.filter(v=>v!==null).length+' of '+context.dials.length+' dials');
  else if(result.other_context_reviews)notice('Earlier reviews used a different calibration or model. Enter a new review for this setup.');
 }catch(error){if(serial!==request)return;notice(error.message||'Review could not be loaded.',true);$('review-empty').textContent='Image unavailable';$('review-reload').hidden=false;}
}
function close(){clearTimeout(imageTimer);remembered();++request;current=null;$('capture-list').hidden=false;$('capture-detail').hidden=true;}
$('review-image').onload=()=>{clearTimeout(imageTimer);imageReady=true;$('review-image').hidden=mapMode;if(!mapMode)$('review-empty').hidden=true;if(current?.context)changed(false);};
$('review-image').onerror=()=>{clearTimeout(imageTimer);imageReady=false;$('review-image').hidden=true;$('review-empty').hidden=false;$('review-empty').textContent='Image unavailable';$('review-save').disabled=true;notice('The original image could not be loaded. Reload before saving.',true);conflicted=true;$('review-reload').hidden=false;};
$('review-back').onclick=()=>{location.hash='captures';};
$('review-reload').onclick=()=>{const id=current?.capture.event_id||Number(location.hash.split('/')[1]);open(id,true);};
$('review-form').onsubmit=async event=>{
 event.preventDefault();if(!current?.context||saving||conflicted||$('review-save').disabled)return;
 if(!$('review-form').reportValidity())return;
 const snapshot=current,serial=request;saving=true;$('review-save').disabled=true;
 $('review-save').textContent='Saving…';notice('Saving review…');
 const payload={event_id:snapshot.capture.event_id,context_id:snapshot.context.id,revision:snapshot.review?.revision||null,positions:values()};
 try{
  const result=await json('api/reviews',{method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Setup':token},body:JSON.stringify(payload)});
  if(serial!==request)return;
  current.review=result;drafts.delete(key());
  if(JSON.stringify(values())!==JSON.stringify(result.positions))changed();
  else notice('Review saved · '+result.positions.filter(v=>v!==null).length+' of '+snapshot.context.dials.length+' dials');
 }catch(error){
  if(serial!==request)return;
  // A lost response may follow a successful write. Read saved state before another save.
  conflicted=true;$('review-reload').hidden=false;
  notice((error.message||'Save could not be verified.')+' Reload the review before retrying.',true);
 }finally{
  if(serial===request){saving=false;$('review-save').textContent='Save review';const edited=JSON.stringify(values())!==JSON.stringify(current?.review?.positions||[]);$('review-save').disabled=conflicted||!imageReady||!!current?.review&&!edited;}
 }
};
function drawMap(){
 if(!referencePicture||!current?.context)return;
 const canvas=$('review-map'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,640,480);ctx.drawImage(referencePicture,0,0,640,480);
 for(const [i,dial] of current.context.calibration.dials.entries()){
  const box=dial.crop;ctx.strokeStyle=i===selected?'#e1ccff':'#67d6cf';ctx.lineWidth=i===selected?3:1;ctx.strokeRect(...box);
  const x=Math.min(617,Math.max(0,box[0])),y=Math.max(0,box[1]-23);ctx.fillStyle=i===selected?'#6652c8':'#18262b';ctx.fillRect(x,y,23,22);
  ctx.font='bold 13px system-ui';ctx.fillStyle='#fff';ctx.textAlign='center';ctx.fillText(String(i+1),x+11.5,y+16);
 }
}
$('review-capture-view').onclick=()=>{
 mapMode=false;$('review-map').hidden=true;$('review-image').hidden=!imageReady;$('review-empty').hidden=imageReady;
 $('review-caption').textContent='Original capture';$('review-capture-view').setAttribute('aria-pressed','true');$('review-map-view').setAttribute('aria-pressed','false');
};
$('review-map-view').onclick=async()=>{
 if(!current?.context?.calibration)return;
 const serial=request;mapMode=true;$('review-image').hidden=true;$('review-empty').hidden=false;$('review-empty').textContent='Loading dial map…';
 $('review-caption').textContent='Calibration reference · dial locations';$('review-capture-view').setAttribute('aria-pressed','false');$('review-map-view').setAttribute('aria-pressed','true');
 try{
  if(!referencePicture)referencePicture=await window.AIEdgeReferenceImage.load('reference/'+current.context.calibration.reference_sha256);
  if(serial!==request||!mapMode)return;drawMap();$('review-map').hidden=false;$('review-empty').hidden=true;
 }catch(error){if(serial===request&&mapMode){$('review-map').hidden=true;$('review-empty').textContent='Dial map unavailable';notice(error.message,true);}}
};
window.addEventListener('aiedge-refresh-images',event=>{const match=/^#captures\/([1-9][0-9]*)$/.exec(location.hash);if(event.detail==='captures'&&match&&!saving)open(Number(match[1]));});
window.AIEdgeReview={open,close};
})();
