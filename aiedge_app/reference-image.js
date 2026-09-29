/* Load a reference without leaving an editor waiting indefinitely. */
(function(root){
 'use strict';
 function load(url,{timeout=10000,ImageType=root.Image}={}){
  return new Promise((resolve,reject)=>{
   const image=new ImageType();let settled=false;
   const finish=(error)=>{
    if(settled)return;settled=true;clearTimeout(timer);
    image.onload=null;image.onerror=null;
    if(error){image.removeAttribute('src');reject(error);}else resolve(image);
   };
   const timer=setTimeout(()=>finish(Error('Reference image timed out. Use Refresh to try again.')),timeout);
   image.onload=()=>finish();
   image.onerror=()=>finish(Error('Reference image could not be loaded. Use Refresh to try again.'));
   image.src=url;
  });
 }
 if(typeof module==='object'&&module.exports)module.exports={load};
 else root.AIEdgeReferenceImage=Object.freeze({load});
})(typeof window==='object'?window:globalThis);
