/* Every mutation follows an explicit user action. No reboot or automatic retry. */
(function(root){
"use strict";
const archivePath="/firmware/managed-bundle.zip";
const descriptions={boot_selected_reboot_required:"Firmware selected for the next boot. It is not running yet. Restart separately when ready.",install_failed_or_uncertain:"Installation failed or its result is uncertain. Flash or boot metadata may have changed. Inspect the device before another attempt.",idle:"No verification has started.",queued_or_running:"Verifying the uploaded bundle…",staged:"Bundle verified and staged. Firmware has not been installed.",already_staged:"This bundle is already verified and staged. Firmware has not been installed.",rejected:"Bundle rejected. Check that the ZIP and bundle ID match a managed build.",storage_error:"Storage error. Failed staging files were preserved for inspection.",busy_or_staging_conflict:"The device is busy, or a previous staging attempt needs inspection.",task_creation_failed:"The verification worker could not start. Check available device memory."};
function validate(file,id){if(!file||!file.name.toLowerCase().endsWith(".zip")||file.size<=0||file.size>8192000)throw Error("Choose a ZIP file no larger than 8,192,000 bytes.");if(!/^[0-9a-f]{64}$/.test(id))throw Error("Enter the exact 64-character lowercase bundle ID.");}
function client(request){
 async function status(){const value=JSON.parse(await request("GET","/bundle_status"));if(typeof value.active!=="boolean"||typeof value.status!=="string"||typeof value.bundle_id!=="string")throw Error("Unexpected status response.");return value;}
 async function stage(file,id,onProgress){validate(file,id);const current=await status();if(current.active||current.boot_selected)throw Error("An update is active or already selected for boot. Check its status first.");
  await request("POST","/delete"+archivePath);
  await request("POST","/upload"+archivePath,file,{},onProgress);
  await request("POST","/bundle_stage",id,{"X-Meter-Bundle-Action":"stage","Content-Type":"text/plain"});
 }
 async function install(id){
  if(!/^[0-9a-f]{64}$/.test(id))throw Error("Enter the exact 64-character lowercase bundle ID.");
  const current=await status();
  if(current.active||current.boot_selected||current.bundle_id!==id||!["staged","already_staged"].includes(current.status))throw Error("Verify this exact bundle before installing it.");
  await request("POST","/bundle_install",id,{"X-Meter-Bundle-Action":"install","Content-Type":"text/plain"});
 }
 return {status,stage,install};
}
function request(method,url,body,headers,onProgress){return new Promise((resolve,reject)=>{
 const xhr=new XMLHttpRequest();xhr.open(method,url);xhr.timeout=120000;
 Object.entries(headers||{}).forEach(([k,v])=>xhr.setRequestHeader(k,v));
 if(onProgress)xhr.upload.onprogress=e=>{if(e.lengthComputable)onProgress(Math.round(e.loaded*100/e.total));};
 xhr.onload=()=>{if(xhr.status>=200&&xhr.status<300)resolve(xhr.responseText);else reject(Error("Request failed (HTTP "+xhr.status+"). "+xhr.responseText.slice(0,200)));};
 xhr.onerror=()=>reject(Error("Connection failed. Check status before retrying; the last request may have completed."));
 xhr.ontimeout=()=>reject(Error("Request timed out. Check status before retrying; the last request may have completed."));
 xhr.send(body===undefined?null:body);
});}
root.MeterStaging={client,validate,descriptions};
if(typeof document==="undefined")return;
const api=client(request),form=document.getElementById("stage-form"),button=document.getElementById("stage"),refresh=document.getElementById("refresh"),output=document.getElementById("status"),progress=document.getElementById("progress");
const installButton=document.getElementById("install");
let timer=null,checking=false,mutating=false;
function stop(){if(timer!==null){clearTimeout(timer);timer=null;}}
async function check(){if(checking)return;checking=true;stop();try{const s=await api.status();installButton.disabled=mutating||s.active||s.boot_selected||!["staged","already_staged"].includes(s.status)||s.bundle_id!==document.getElementById("bundle-id").value.trim();output.textContent=(descriptions[s.status]||("Status: "+s.status))+(s.bundle_id?"\nBundle: "+s.bundle_id:"");if(s.active)timer=setTimeout(check,3000);}catch(e){installButton.disabled=true;output.textContent=e.message;}finally{checking=false;}}
form.addEventListener("submit",async e=>{e.preventDefault();if(checking||mutating){output.textContent="Wait for the current status check to finish.";return;}stop();mutating=true;installButton.disabled=true;button.disabled=true;refresh.disabled=true;progress.hidden=false;progress.value=0;output.textContent="Uploading bundle…";try{await api.stage(document.getElementById("archive").files[0],document.getElementById("bundle-id").value.trim(),n=>{progress.value=n;});output.textContent="Verification requested.";mutating=false;await check();}catch(error){output.textContent=error.message;}finally{mutating=false;button.disabled=false;refresh.disabled=false;progress.hidden=true;}});
installButton.addEventListener("click",async()=>{
 if(checking||mutating)return;
 stop();mutating=true;button.disabled=refresh.disabled=installButton.disabled=true;
 output.textContent="Installing verified firmware. Do not remove power.";
 try{await api.install(document.getElementById("bundle-id").value.trim());mutating=false;await check();}
 catch(error){output.textContent=error.message;}
 finally{mutating=false;button.disabled=refresh.disabled=false;}
});
document.getElementById("bundle-id").addEventListener("input",()=>{installButton.disabled=true;});
refresh.addEventListener("click",check);window.addEventListener("pagehide",stop);
})(typeof window!=="undefined"?window:globalThis);
