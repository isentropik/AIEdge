// Never replace bytes or reload while a flashing dialog may be active.
export function watchRelease({version,fetchManifest,onCurrent,onStale,onUnavailable,now=Date.now}) {
 let checked=now(),pending=null,stale=false;
 async function check(force=false){
  if(stale)return false;
  if(pending)return pending;
  if(!force&&now()-checked<60000)return true;
  pending=(async()=>{try{
   const manifest=await fetchManifest();
   if(manifest.name!=='AIEdge Wi-Fi loader'||typeof manifest.version!=='string')throw Error('Invalid release manifest');
   if(manifest.version!==version){stale=true;onStale(manifest.version);return false;}
   checked=now();onCurrent();return true;
  }catch(e){onUnavailable();return false;}finally{pending=null;}})();
  return pending;
 }
 return {check,needsCheck:()=>stale||!!pending||now()-checked>=60000};
}
