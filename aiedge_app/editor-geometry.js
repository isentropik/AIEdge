/* Image-space geometry shared by pointer editing and its regression tests. */
(function(root){
 'use strict';
 const corners=b=>[[b[0],b[1]],[b[0]+b[2],b[1]],[b[0]+b[2],b[1]+b[3]],[b[0],b[1]+b[3]]];
 function nearestCorner(point,box,screenScale){
  if(!box||!(screenScale>0))return -1;
  const distances=corners(box).map(([x,y])=>Math.hypot(x-point[0],y-point[1]));
  const closest=Math.min(...distances);
  return closest<=14/screenScale?distances.indexOf(closest):-1;
 }
 function resizeBox(drag,point,maximum){
  if(drag.move){
   const [x,y,w,h]=drag.box;
   return [Math.max(0,Math.min(640-w,Math.round(x+point[0]-drag.start[0]))),
           Math.max(0,Math.min(480-h,Math.round(y+point[1]-drag.start[1]))),w,h];
  }
  const anchor=drag.corner>=0?corners(drag.box)[(drag.corner+2)%4]:drag.start;
  const ax=Math.round(anchor[0]),ay=Math.round(anchor[1]);
  const dx=point[0]-ax,dy=point[1]-ay,sx=dx<0?-1:1,sy=dy<0?-1:1;
  const maxW=Math.min(maximum,sx<0?ax:640-ax),maxH=Math.min(maximum,sy<0?ay:480-ay);
  if(maxW<8||maxH<8)return null;
  let w,h;
  if(drag.ratio){
   const minW=Math.max(8,8*drag.ratio),limit=Math.min(maxW,maxH*drag.ratio);
   if(limit<minW)return null;
   w=Math.max(minW,Math.min(limit,Math.max(Math.abs(dx),Math.abs(dy)*drag.ratio)));
   h=w/drag.ratio;
  }else{
   w=Math.max(8,Math.min(maxW,Math.abs(dx)));
   h=Math.max(8,Math.min(maxH,Math.abs(dy)));
  }
  w=Math.round(w);h=Math.round(h);
  return [sx<0?ax-w:ax,sy<0?ay-h:ay,w,h];
 }
 function resizeDimension(box,index,value,maximum,locked){
  if(!box||!Number.isInteger(value))return null;
  const result=box.slice();result[index]=value;
  if(locked&&(index===2||index===3))result[index===2?3:2]=Math.round(value*(index===2?box[3]/box[2]:box[2]/box[3]));
  const [x,y,w,h]=result;
  if(result.some(v=>!Number.isInteger(v))||x<0||y<0||w<8||h<8||w>maximum||h>maximum||x+w>640||y+h>480)return null;
  return result;
 }
 const api={corners,nearestCorner,resizeBox,resizeDimension};
 if(typeof module==='object'&&module.exports)module.exports=api;
 else root.AIEdgeGeometry=Object.freeze(api);
})(typeof window==='object'?window:globalThis);
