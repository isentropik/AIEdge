"use strict";
(function(root){
  const numeric=v=>((typeof v==='number')||(typeof v==='string'&&v.trim()!==''))&&Number.isFinite(Number(v))?Number(v):null;
  function box(r){
    if(!r)return null;
    let x=numeric(r.x),y=numeric(r.y),w=numeric(r.dx),h=numeric(r.dy);
    if([x,y,w,h].some(v=>v===null)||w===0||h===0)return null;
    if(w<0){x+=w;w=-w;}if(h<0){y+=h;h=-h;}
    return {x,y,w,h};
  }
  function evaluate(markers,width,height){
    width=numeric(width);height=numeric(height);
    if(!(width>0&&height>0))return {state:'waiting',text:'Load the reference image to check marker placement.'};
    if(!Array.isArray(markers)||markers.length!==2)return {state:'incomplete',text:'Choose both alignment markers to check their spacing.'};
    const boxes=markers.map(box);
    if(boxes.some(b=>!b))return {state:'incomplete',text:'Give both markers a position and a nonzero width and height.'};
    if(boxes.some(b=>b.x<0||b.y<0||b.x+b.w>width||b.y+b.h>height))return {state:'outside',text:'Keep both marker rectangles entirely inside the reference image.'};
    const [a,b]=boxes;
    const overlap=Math.min(a.x+a.w,b.x+b.w)>Math.max(a.x,b.x)&&Math.min(a.y+a.h,b.y+b.h)>Math.max(a.y,b.y);
    if(overlap)return {state:'overlap',text:'The marker rectangles overlap. Choose two separate, distinctive fixed markings.'};
    const fraction=Math.hypot(a.x+a.w/2-b.x-b.w/2,a.y+a.h/2-b.y-b.h/2)/Math.hypot(width,height);
    const close=fraction<.25;
    return {state:close?'close':'separated',fraction,text:'Marker centers are '+Math.round(fraction*100)+'% of the image diagonal apart. '+
      (close?'Try moving them farther apart. ':'Spacing looks reasonable. ')+
      'About 25% or more is a placement guideline, not a validation threshold. Both patches still need clear, fixed features.'};
  }
  const api={evaluate};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.AIEdgeMarkerSpacing=api;
})(typeof window!=='undefined'?window:globalThis);
