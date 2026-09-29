(() => {
'use strict';
const geometry=window.AIEdgeGeometry;
const $=id=>document.getElementById(id),canvas=$('calibration-canvas'),ctx=canvas.getContext('2d');
let state={markers:[null,null,null],dials:[]},revision=null,reference=null,token=null,available=false,loaded=false,mode='markers',selected=0,picture=null,pendingReference=null,drag=null,busy=false,dirty=false;
const errorText={reference_image_not_found:'The reference image is missing. Choose the image again before saving.',reference_image_unreadable:'This image could not be opened. Choose a complete JPEG or PNG file.',reference_must_be_640x480:'Choose a 640 × 480 JPEG or PNG image.',invalid_landmark:'Keep each landmark inside the image.',invalid_dial_geometry:'Check the dial geometry.',setup_changed_reload_before_saving:'Calibration changed in another session. Reload before saving.',reference_recognition_rejected:'The reference did not pass alignment or needle visibility. Check the markers and dial landmarks.',three_markers_required:'Place all three markers.',invalid_dial_count:'Use between 1 and 16 dials.'};
const recoveryText={saved_calibration_invalid:'Saved calibration could not be read. Rebuild it here; the original file will be kept.',calibration_file_unavailable:'The calibration file is not readable. Check app storage and restart before saving.',saved_reference_unavailable:'The saved reference is missing or damaged. Choose a replacement image before saving.',recognition_runtime_unavailable:'The recognition engine could not load this calibration. Check the installed model and runtime files.'};
function status(message,error=false){$('setup-status').textContent=message;$('setup-status').dataset.error=String(error);}
function changed(message='Unsaved changes'){dirty=true;status(message);controls();}
function currentBox(){return mode==='markers'?state.markers[selected]:state.dials[selected]?.crop;}
function setBox(b){if(mode==='markers')state.markers[selected]=b;else if(state.dials[selected])state.dials[selected].crop=b;}
function option(value,text){const e=document.createElement('option');e.value=value;e.textContent=text;return e;}
function controls(){
 for(const control of document.querySelectorAll('.editor-controls input,.editor-controls select,.editor-controls button'))control.disabled=busy;
 $('reference-file').disabled=!available||busy;
 $('edit-markers').setAttribute('aria-pressed',String(mode==='markers'));$('edit-dials').setAttribute('aria-pressed',String(mode==='dials'));
 $('dial-controls').hidden=mode!=='dials';$('selected-item').replaceChildren();
 const names=mode==='markers'?['Marker 1','Marker 2','Marker 3']:state.dials.map(d=>d.name);
 names.forEach((name,i)=>$('selected-item').append(option(String(i),name)));$('selected-item').value=String(selected);
 const d=state.dials[selected];$('dial-name').value=mode==='dials'&&d?d.name:'';if(mode==='dials'&&d){$('dial-direction').value=d.direction;$('dial-model').value=d.model;}
 $('remove-dial').disabled=mode!=='dials'||!d||busy;$('add-dial').disabled=!picture||state.dials.length>=16||busy;
 const b=currentBox();['x','y','w','h'].forEach((k,i)=>{$('box-'+k).value=b?b[i]:'';$('box-'+k).disabled=!picture||busy||(mode==='dials'&&!d);});
 $('save-calibration').disabled=!available||!reference||busy||!dirty;
 $('editor-hint').textContent=!picture?'Choose a 640 × 480 image to begin.':mode==='markers'?'Draw three separated boxes around fixed markings, away from needles. Drag a corner to resize. Maximum 128 × 128 px.':!d?'Add a dial, then draw its crop.':'Draw a crop up to 148 × 148 px. Place four rim points clockwise from zero, then the needle pivot. The pivot is separate from the dial center.';
 draw();
}
function draw(){if(!picture)return;ctx.clearRect(0,0,640,480);ctx.drawImage(picture,0,0,640,480);
 const boxes=mode==='markers'?state.markers:state.dials.map(d=>d.crop);
 boxes.forEach((b,i)=>{if(!b)return;ctx.strokeStyle=i===selected?'#d6bdff':'#67d6cf';ctx.lineWidth=i===selected?2:1;ctx.strokeRect(...b);ctx.font='12px system-ui';ctx.fillStyle='#111c';ctx.fillRect(b[0],Math.max(0,b[1]-20),72,19);ctx.fillStyle='#fff';ctx.fillText((mode==='markers'?'Marker ':'Dial ')+(i+1),b[0]+4,Math.max(13,b[1]-6));
 if(i===selected){ctx.fillStyle='#e5d9ff';for(const [x,y] of corners(b))ctx.fillRect(x-3,y-3,6,6);}});
 if(mode==='dials'&&state.dials[selected]){const d=state.dials[selected];[...d.rim_points,d.needle_pivot].forEach((p,i)=>{if(!p)return;ctx.strokeStyle=i===4?'#70e1fc':'#fff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(p[0],p[1],4,0,Math.PI*2);ctx.stroke();ctx.fillStyle='#111';ctx.fillRect(p[0]+5,p[1]-15,30,17);ctx.fillStyle='#fff';ctx.fillText(['0','¼','½','¾','P'][i],p[0]+8,p[1]-2);});}
}
const corners=geometry.corners;
function location(e){const r=canvas.getBoundingClientRect();const scale=Math.min(r.width/640,r.height/480),ox=(r.width-640*scale)/2,oy=(r.height-480*scale)/2;return [(e.clientX-r.left-ox)/scale,(e.clientY-r.top-oy)/scale,scale];}
function hit(p,b){return geometry.nearestCorner(p,b,p[2]);}
function within(p,b){return b&&p[0]>=b[0]&&p[0]<=b[0]+b[2]&&p[1]>=b[1]&&p[1]<=b[1]+b[3];}
canvas.onpointerdown=e=>{if(!picture||busy)return;const p=location(e);if(p[0]<0||p[1]<0||p[0]>640||p[1]>480)return;
 const d=state.dials[selected],tool=$('edit-tool').value;if(mode==='dials'&&!d)return;
 if(mode==='dials'&&tool!=='crop'){const point=p.slice(0,2).map(v=>Math.round(v*10)/10);if(tool==='pivot')d.needle_pivot=point;else d.rim_points[Number(tool)]=point;changed();return;}
 const b=currentBox(),corner=hit(p,b);drag={start:p,box:b?.slice(),corner,move:corner<0&&within(p,b),ratio:$('lock-proportions').checked?(corner>=0?b[2]/b[3]:1):null};canvas.setPointerCapture(e.pointerId);e.preventDefault();};
canvas.onpointermove=e=>{if(!picture)return;const p=location(e),b=currentBox(),h=hit(p,b);canvas.style.cursor=mode==='dials'&&$('edit-tool').value!=='crop'?'crosshair':h>=0?(h%2?'nesw-resize':'nwse-resize'):within(p,b)?'move':'crosshair';if(!drag)return;
 const box=geometry.resizeBox(drag,p,mode==='markers'?128:148);
 if(box){setBox(box);controls();}};
canvas.onpointerup=e=>{if(drag){const modified=JSON.stringify(currentBox())!==JSON.stringify(drag.box||null);drag=null;if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);if(modified)changed();}};canvas.onpointercancel=()=>{if(drag){setBox(drag.box||null);drag=null;controls();}};
async function request(path,body,raw=false){const response=await fetch(path,{method:'POST',headers:{'X-AIEdge-Setup':token,'Content-Type':raw?'application/octet-stream':'application/json'},body:raw?body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});let data;try{data=await response.json();}catch{throw Error('The server did not return a valid response. Reload before retrying.');}if(!response.ok){const key=String(data.error).split(':')[0];throw Error(errorText[key]||String(data.error).replaceAll('_',' '));}return data;}
async function showReference(digest,newState){const img=await window.AIEdgeReferenceImage.load('reference/'+digest);picture=img;reference=digest;pendingReference=digest;if(newState){state=newState;selected=0;mode='markers';}canvas.hidden=false;$('reference-empty').hidden=true;$('reference-size').textContent='640 × 480';controls();}
window.addEventListener('aiedge-refresh-images',async event=>{
 if(event.detail!=='setup'||picture||busy)return;
 if(!loaded){window.openCalibration();return;}
 if(!pendingReference)return;
 busy=true;controls();status('Loading reference…');
 try{await showReference(pendingReference);status(dirty?'Unsaved changes':'');}
 catch(e){status(e.message,true);}
 finally{busy=false;controls();}
});
window.openCalibration=async()=>{
 if(loaded||busy)return;busy=true;controls();status('Loading calibration…');
 try{
  const r=await fetch('api/setup',{cache:'no-store',signal:AbortSignal.timeout(10000)});
  if(!r.ok)throw Error('Could not load calibration.');
  const s=await r.json();let referenceError=null;token=s.token;available=s.available;revision=s.revision;
  if(s.calibration){
   const c=s.calibration;
   state={markers:c.markers.map(m=>m.box),dials:c.dials.map(d=>({name:d.name,model:d.model,direction:d.direction,crop:d.crop,rim_points:d.landmarks?.rim_points||[null,null,null,null],needle_pivot:d.landmarks?.needle_pivot||null}))};
   pendingReference=c.reference_sha256;try{await showReference(pendingReference);}catch(e){referenceError=e.message;}
  }
  loaded=true;dirty=!!s.recovery;
  status(s.recovery?(recoveryText[s.recovery.code]||'Saved calibration needs recovery.'):referenceError||(available?'':'Calibration runtime is not configured.'),!!s.recovery||!!referenceError||!available);
 }catch(e){status(e.message,true);}
 finally{busy=false;controls();}
};
$('reference-file').onchange=async()=>{const file=$('reference-file').files[0];if(!file)return;if(file.size>4*1024*1024){status('Choose an image smaller than 4 MB.',true);return;}busy=true;controls();status('Loading reference…');try{const r=await request('api/setup/reference',await file.arrayBuffer(),true);await showReference(r.reference_sha256,{markers:[null,null,null],dials:[]});changed('Place three markers on fixed markings.');}catch(e){status(e.message,true);}finally{busy=false;controls();$('reference-file').value='';}};
$('save-calibration').onclick=async()=>{if(busy)return;if(state.markers.some(x=>!x)){status('Place all three markers.',true);return;}if(!state.dials.length||state.dials.some(d=>d.rim_points.some(p=>!p)||!d.needle_pivot)){status('Place four rim points and the needle pivot for every dial.',true);return;}busy=true;controls();status('Validating calibration…');try{const s=await request('api/setup/save',{reference_sha256:reference,design:state,revision});revision=s.revision;dirty=false;status('Calibration applied.');window.dispatchEvent(new Event('aiedge-calibration-saved'));}catch(e){status(e.message,true);}finally{busy=false;controls();}};
$('edit-markers').onclick=()=>{mode='markers';selected=0;controls();};$('edit-dials').onclick=()=>{mode='dials';selected=0;controls();};$('selected-item').onchange=()=>{selected=Number($('selected-item').value);controls();};
$('add-dial').onclick=()=>{let n=state.dials.length+1;while(state.dials.some(d=>d.name==='Dial '+n))n++;state.dials.push({name:'Dial '+n,model:'main',direction:'cw',crop:[0,0,140,140],rim_points:[null,null,null,null],needle_pivot:null});selected=state.dials.length-1;changed('Draw a crop around the dial.');};$('remove-dial').onclick=()=>{state.dials.splice(selected,1);selected=Math.max(0,selected-1);changed();};
for(const [id,key] of [['dial-name','name'],['dial-direction','direction'],['dial-model','model']])$(id).onchange=()=>{if(state.dials[selected]){state.dials[selected][key]=$(id).value;changed();}};
for(const [i,k] of ['x','y','w','h'].entries())$('box-'+k).onchange=()=>{
 const raw=$('box-'+k).value;
 const b=raw.trim()?geometry.resizeDimension(currentBox(),i,Number(raw),mode==='markers'?128:148,$('lock-proportions').checked):null;
 if(!b){status('Keep the box inside the image and supported size.',true);controls();return;}
 if(JSON.stringify(b)!==JSON.stringify(currentBox())){setBox(b);changed();}
};
controls();
})();
