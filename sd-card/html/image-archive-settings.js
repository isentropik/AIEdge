(function(root){
'use strict';
function validateSaved(s){
 if(!s||s.version!==1||typeof s.revision!=='string'||! /^[a-f0-9]{64}$/.test(s.revision)||
 ['enabled','has_token','has_certificate'].some(k=>typeof s[k]!=='boolean')||
 ['host','device_id'].some(k=>typeof s[k]!=='string')||!Number.isInteger(s.port)||s.port<1||s.port>65535||
 !Number.isInteger(s.timeout_ms)||s.timeout_ms<1000||s.timeout_ms>30000)throw Error('Invalid settings response');
 return s;
}
function mount(doc,fetcher){
 const n=id=>doc.getElementById(id);let revision=null,busy=false;
 const say=text=>{n('settings-message').textContent=text;};
 const buttons=()=>{n('settings-load').disabled=busy;n('settings-save').disabled=busy||!revision;};
 async function request(options){const c=new AbortController(),t=setTimeout(()=>c.abort(),12000);
 try{const r=await fetcher('/image_archive_settings',{cache:'no-store',credentials:'same-origin',redirect:'error',...options,signal:c.signal});const body=await r.json();if(!r.ok){const e=Error(body.error||'Request failed');e.status=r.status;throw e;}return body;}finally{clearTimeout(t);}}
 async function load(){if(busy)return;busy=true;revision=null;buttons();say('Reading saved settings…');
 try{const s=validateSaved(await request({method:'GET'}));revision=s.revision;
 n('archive-enable').checked=s.enabled;n('archive-host').value=s.host;n('archive-port').value=String(s.port);n('archive-device').value=s.device_id;n('archive-timeout').value=String(s.timeout_ms/1000);
 n('archive-token').value='';n('archive-ca').value='';n('archive-token').placeholder=s.has_token?'Saved — leave blank to keep':'Enter the receiver access token';n('archive-ca').placeholder=s.has_certificate?'Saved — leave blank to keep':'Paste the receiver CA certificate';
 say('Saved settings loaded. The live status above shows whether archiving is running.');
 }catch(_){say('Could not read settings. The device may be busy, disconnected or need recovery. Your form has not been submitted.');}finally{busy=false;buttons();}}
 async function save(event){if(event)event.preventDefault();if(busy||!revision)return;
 const config={enabled:n('archive-enable').checked};
 const host=n('archive-host').value.trim(),device=n('archive-device').value.trim();if(host)config.host=host;if(device)config.device_id=device;
 config.port=Number(n('archive-port').value);config.timeout_ms=Number(n('archive-timeout').value)*1000;
 const body={version:1,config,token:n('archive-token').value||null,ca_pem:n('archive-ca').value||null};
 busy=true;buttons();say('Saving settings…');
 try{const s=await request({method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Revision':revision},body:JSON.stringify(body)});
 if(s.status!=='saved_restart_required'||s.active_changed!==false)throw Error('Unexpected save response');
 n('archive-token').value='';n('archive-ca').value='';say('Saved. Restart the device when ready to apply these settings. Active uploads have not changed.');
 }catch(e){say(e.status===409?'Settings changed or the device is busy. Reload saved settings before trying again.':'Save could not be confirmed. Do not repeat it yet; reload settings or check the device logs.');}
 finally{revision=null;busy=false;buttons();}}
 n('settings-load').addEventListener('click',load);n('settings-form').addEventListener('submit',save);
 n('archive-show-token').addEventListener('click',()=>{const show=n('archive-token').type==='password';n('archive-token').type=show?'text':'password';n('archive-show-token').setAttribute('aria-pressed',String(show));n('archive-show-token').setAttribute('aria-label',show?'Hide access token':'Show access token');});
 buttons();return {load,save};
}
const api={validateSaved,mount};if(typeof module!=='undefined')module.exports=api;
if(typeof document!=='undefined')mount(document,root.fetch.bind(root)).load();
})(typeof window!=='undefined'?window:globalThis);
