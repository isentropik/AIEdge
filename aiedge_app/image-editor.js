/* Source-coordinate framing; camera pixels and calibration are kept intact. */
(function(root){
'use strict';
const clone=x=>JSON.parse(JSON.stringify(x));
const identity=()=>({version:1,turns:0,angle:0,crop:[0,0,640,480]});
function point(m,p){return [m[0]*p[0]+m[1]*p[1]+m[2],m[3]*p[0]+m[4]*p[1]+m[5]];}
function inverse(m){const [a,b,c,d,e,f]=m,q=a*e-b*d;return [e/q,-b/q,(b*f-e*c)/q,-d/q,a/q,(d*c-a*f)/q];}
function map(value){
 if(!value||value.version!==1||!Number.isInteger(value.turns)||value.turns<0||value.turns>3||!Number.isFinite(value.angle)||Math.abs(value.angle)>15)throw Error('Invalid image framing.');
 const snap=v=>Math.abs(v)<1e-12?0:Math.abs(v-1)<1e-12?1:Math.abs(v+1)<1e-12?-1:v;
 const radians=(90*value.turns+value.angle)*Math.PI/180,co=snap(Math.cos(radians)),si=snap(Math.sin(radians));
 const extent=[Math.ceil(Math.abs(co)*640+Math.abs(si)*480),Math.ceil(Math.abs(si)*640+Math.abs(co)*480)];
 const oriented=[co,-si,extent[0]/2-co*320+si*240,si,co,extent[1]/2-si*320-co*240];
 const crop=value.crop===null?[0,0,...extent]:value.crop;
 if(!Array.isArray(crop)||crop.length!==4||!crop.every(Number.isInteger)||crop[0]<0||crop[1]<0||crop[2]<16||crop[3]<16||crop[0]+crop[2]>extent[0]||crop[1]+crop[3]>extent[1])throw Error('Keep the crop inside the image.');
 const [x,y,w,h]=crop,scale=Math.min(640/w,480/h),offset=[(640-w*scale)/2,(480-h*scale)/2];
 const m=oriented.map((v,i)=>i===2?(v-x)*scale+offset[0]:i===5?(v-y)*scale+offset[1]:v*scale);
 return {edit:{version:1,turns:value.turns,angle:value.angle,crop:[...crop]},extent,oriented,m,inverse:inverse(m),scale,offset};
}
function corners(b){return [[b[0],b[1]],[b[0]+b[2],b[1]],[b[0]+b[2],b[1]+b[3]],[b[0],b[1]+b[3]]];}
function visible(value,p){const m=map(value),q=point(m.oriented,p),[x,y,w,h]=m.edit.crop;return q[0]>=x-1e-8&&q[0]<=x+w+1e-8&&q[1]>=y-1e-8&&q[1]<=y+h+1e-8;}
function resizeCursor(matrix,box,corner){const center=[box[0]+box[2]/2,box[1]+box[3]/2],a=point(matrix,corners(box)[corner]),b=point(matrix,center);return (a[0]-b[0])*(a[1]-b[1])>=0?'nwse-resize':'nesw-resize';}
function rotate(value,turns,angle){
 const old=map(value),next=map({version:1,turns:((turns%4)+4)%4,angle,crop:null});
 if(JSON.stringify(old.edit.crop)===JSON.stringify([0,0,...old.extent]))return next.edit;
 const points=corners(old.edit.crop).map(p=>point(next.oriented,point(inverse(old.oriented),p)));
 const min=(axis)=>Math.max(0,Math.floor(Math.min(...points.map(p=>p[axis]))+1e-8));
 const max=(axis)=>Math.min(next.extent[axis],Math.ceil(Math.max(...points.map(p=>p[axis]))-1e-8));
 const x=min(0),y=min(1);next.edit.crop=[x,y,max(0)-x,max(1)-y];return map(next.edit).edit;
}
function cropDrag(drag,p,extent){
 const b=drag.box,[w,h]=extent;
 if(drag.move)return [Math.max(0,Math.min(w-b[2],Math.round(b[0]+p[0]-drag.start[0]))),Math.max(0,Math.min(h-b[3],Math.round(b[1]+p[1]-drag.start[1]))),b[2],b[3]];
 const vertex=corners(b)[drag.corner],opposite=corners(b)[(drag.corner+2)%4];
 const q=[vertex[0]+p[0]-drag.start[0],vertex[1]+p[1]-drag.start[1]];
 const left=drag.corner===0||drag.corner===3,top=drag.corner<2;
 const x=left?Math.max(0,Math.min(opposite[0]-16,Math.round(q[0]))):opposite[0];
 const y=top?Math.max(0,Math.min(opposite[1]-16,Math.round(q[1]))):opposite[1];
 return [x,y,left?opposite[0]-x:Math.min(w,Math.max(x+16,Math.round(q[0])))-x,
              top?opposite[1]-y:Math.min(h,Math.max(y+16,Math.round(q[1])))-y];
}
function drawImage(ctx,image,value){
 const m=map(value),[x,y]=m.offset,[w,h]=m.edit.crop.slice(2);
 ctx.fillStyle='#080a0c';ctx.fillRect(0,0,640,480);ctx.save();ctx.beginPath();ctx.rect(x,y,w*m.scale,h*m.scale);ctx.clip();
 ctx.transform(m.m[0],m.m[3],m.m[1],m.m[4],m.m[2],m.m[5]);ctx.drawImage(image,0,0,640,480);ctx.restore();return m;
}
const core={identity,map,point,inverse,corners,visible,resizeCursor,rotate,cropDrag,drawImage};
if(typeof module==='object'){module.exports=core;return;}
root.AIEdgeImageFraming=Object.freeze(core);
const $=id=>document.getElementById(id),canvas=$('calibration-canvas');
let edit=identity(),saved=identity(),revision=null,reference=null,working=false,externalBusy=false,cropping=false,drag=null,mode='image',bound=false,persisted=null;
const errors={image_crop_hides_marker:'The crop would hide an alignment marker. Keep all markers inside it.',
 image_crop_hides_dial:'The crop would hide part of a dial. Keep every dial inside it.',
 image_edit_changed_reload_before_saving:'Image framing changed in another session. Reload before saving.',
 image_crop_outside_frame:'Keep the crop inside the image.',image_edit_invalid:'The image framing is invalid.'};
function pendingOrientation(){return !!root.AIEdgeImageControls?.status().orientation_pending;}
function changed(){root.AIEdgeCalibration?.draw();update();root.updateSetupFlow?.();}
function update(){
 const visible=mode==='image',has=!!root.AIEdgeCalibration?.status().has_image;
 for(const id of ['image-rotate-left','image-rotate-right','image-crop','image-reset-crop','image-straighten']){
  $(id).hidden=!visible;$(id).disabled=!has||working||externalBusy||pendingOrientation();
 }
 $('image-reset-crop').hidden=!visible||!cropping;
 $('image-crop').setAttribute('aria-pressed',String(cropping));$('image-crop').setAttribute('aria-label',cropping?'Apply crop':'Crop image');
 $('image-crop').title=cropping?'Apply crop':'Crop image';
 document.querySelector?.('.image-toolbar')?.setAttribute('data-cropping',String(cropping));
 $('image-straighten-controls').hidden=!visible||$('image-straighten').getAttribute('aria-pressed')!=='true';
 $('image-straighten-angle').value=String(edit.angle);$('image-straighten-value').textContent=edit.angle.toFixed(1)+'°';
 $('image-straighten-angle').disabled=working||externalBusy||pendingOrientation();
}
function display(){return map(cropping?{...edit,crop:null}:edit);}
function cropCoordinates(p){const m=display();return [(p[0]-m.offset[0])/m.scale,(p[1]-m.offset[1])/m.scale,p[2]*m.scale];}
function hit(p,type){const distance=corners(edit.crop).map(q=>Math.hypot(q[0]-p[0],q[1]-p[1]));const minimum=Math.min(...distance);return minimum<=(type==='touch'?24:16)/p[2]?distance.indexOf(minimum):-1;}
function inside(p,b){return p[0]>=b[0]&&p[0]<=b[0]+b[2]&&p[1]>=b[1]&&p[1]<=b[1]+b[3];}
function toggleCrop(){if(working||externalBusy||pendingOrientation())return;cropping=!cropping;drag=null;changed();}
$('image-crop').onclick=toggleCrop;
$('image-reset-crop').onclick=()=>{edit=map({...edit,crop:null}).edit;changed();};
for(const [id,delta] of [['image-rotate-left',-1],['image-rotate-right',1]])$(id).onclick=()=>{
 if(working||externalBusy||pendingOrientation())return;edit=rotate(edit,edit.turns+delta,edit.angle);changed();
};
$('image-straighten').onclick=()=>{$('image-straighten').setAttribute('aria-pressed',String($('image-straighten').getAttribute('aria-pressed')!=='true'));update();};
$('image-straighten-angle').oninput=()=>{if(working||externalBusy||pendingOrientation())return;edit=rotate(edit,edit.turns,Number($('image-straighten-angle').value));changed();};
async function save(){
 if(!reference||working)return false;
 cropping=false;drag=null;changed();
 if(JSON.stringify(edit)===JSON.stringify(saved))return true;
 const expectedReference=reference;
 working=true;update();root.updateSetupFlow?.();
 try{
  const response=await fetch('api/setup/image-edit',{method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Setup':root.AIEdgeCalibration.token()},
   body:JSON.stringify({reference_sha256:reference,edit,revision}),signal:AbortSignal.timeout(10000)});
  const result=await response.json();if(!response.ok)throw Error(errors[result.error]||'Could not save image framing. Reload before retrying.');
  if(reference!==expectedReference||result.image_edit?.reference_sha256!==reference)throw Error('The reference changed while saving. Reload before continuing.');
  if(JSON.stringify(map(result.image_edit.edit).edit)!==JSON.stringify(edit)||typeof result.revision!=='string')throw Error('The saved framing could not be verified. Reload before continuing.');
  edit=map(result.image_edit.edit).edit;saved=clone(edit);revision=result.revision;persisted=clone(result.image_edit);
  root.dispatchEvent?.(new CustomEvent('aiedge-image-edit-saved',{detail:clone(result.image_edit)}));return true;
 }catch(error){root.AIEdgeCalibration.note(error.message,true);return false;}
 finally{working=false;changed();}
}
root.AIEdgeImageEditor={
 bind(digest,state){
  if(reference===digest&&bound)return;
  if(!bound){revision=state?.revision??null;persisted=state?.image_edit?clone(state.image_edit):null;}
  reference=digest;bound=true;
  edit=persisted?.reference_sha256===digest?map(persisted.edit).edit:identity();
  saved=clone(edit);cropping=false;drag=null;update();
  if(state?.recovery)root.AIEdgeCalibration?.note('Saved image framing could not be read. The original file has been kept.',true);
 },
 setMode(value){mode=value;if(value!=='image'){cropping=false;drag=null;}update();},
 refresh:update,setBusy(value){externalBusy=!!value;update();},save,display,status(){return {busy:working,dirty:JSON.stringify(edit)!==JSON.stringify(saved),edit:clone(edit),reference};},
 draw(ctx,image){return drawImage(ctx,image,display().edit);},
 overlay(ctx,screenScale){
  if(!cropping)return;
  const m=display(),[x,y,w,h]=edit.crop,b=[m.offset[0]+x*m.scale,m.offset[1]+y*m.scale,w*m.scale,h*m.scale];
  ctx.save();ctx.fillStyle='#080a0c99';ctx.beginPath();ctx.rect(0,0,640,480);ctx.rect(...b);ctx.fill('evenodd');
  ctx.strokeStyle='#f1f2f4';ctx.lineWidth=1.5/screenScale;ctx.strokeRect(...b);
  for(const [a,c] of corners(b)){
   const size=12/screenScale;ctx.fillStyle='#fff';ctx.fillRect(a-size/2,c-size/2,size,size);ctx.strokeStyle='#11151a';ctx.strokeRect(a-size/2,c-size/2,size,size);ctx.strokeStyle='#f1f2f4';
  }
  ctx.restore();
 },
 pointerDown(event,p){
  if(!cropping||working||externalBusy||pendingOrientation())return false;
  const q=cropCoordinates(p),corner=hit(q,event.pointerType);
  if(corner<0&&!inside(q,edit.crop))return true;
  drag={start:q,box:[...edit.crop],corner,move:corner<0};canvas.setPointerCapture(event.pointerId);event.preventDefault();return true;
 },
 pointerMove(event,p){
  if(!cropping)return false;
  if(working||externalBusy)return true;
  const q=cropCoordinates(p),corner=hit(q,event.pointerType);canvas.style.cursor=corner>=0?(corner%2?'nesw-resize':'nwse-resize'):inside(q,edit.crop)?'move':'default';
  if(drag){edit={...edit,crop:cropDrag(drag,q,display().extent)};root.AIEdgeCalibration?.draw();}
  return true;
 },
 pointerUp(event){if(!drag)return false;drag=null;if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);changed();return true;},
 cancel(){if(drag){edit={...edit,crop:drag.box};drag=null;changed();}}
};
update();
})(typeof window==='object'?window:globalThis);
