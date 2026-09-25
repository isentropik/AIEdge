(function(root){
'use strict';
function limit(enabled,text){
 if(!enabled)return null;
 const value=Number(text);
 if(!String(text).trim()||!Number.isFinite(value)||value<=0||value/3600===0)throw Error('Enter a positive maximum flow, or turn the limit off.');
 return value;
}
function validate(s){
 if(!s||!/^[a-f0-9]{64}$/.test(s.revision)||!s.settings||s.settings.version!==1||
 typeof s.initialized!=='boolean'||typeof s.saved_active!=='boolean'||(s.saved_active&&!s.initialized))throw Error('Unsupported flow settings response');
 const x=s.settings.maximum_flow_ft3_hour,y=s.active_maximum_flow_ft3_hour;
 for(const v of [x,y])if(v!==null&&(typeof v!=='number'||!Number.isFinite(v)||v<=0||v/3600===0))throw Error('Invalid flow limit');
 if(!s.initialized&&y!==null)throw Error('Invalid active state');
 return s;
}
function mount(doc,fetcher){
 const n=id=>doc.getElementById(id);let revision=null,busy=false;
 const say=x=>{n('flow-message').textContent=x;};
 function controls(){n('flow-load').disabled=busy;n('flow-save').disabled=busy||!revision;n('flow-fields').disabled=busy||!revision;n('flow-maximum').disabled=busy||!revision||!n('flow-enabled').checked;}
 async function request(options){const c=new AbortController(),t=setTimeout(()=>c.abort(),12000);
 try{const r=await fetcher('/meter_assumptions',{cache:'no-store',credentials:'same-origin',redirect:'error',...options,signal:c.signal});const data=await r.json();if(!r.ok){const e=Error(data.error||'Request failed');e.status=r.status;throw e;}return data;}finally{clearTimeout(t);}}
 async function load(){if(busy)return;busy=true;revision=null;controls();say('Reading flow settings…');
 try{const s=validate(await request({method:'GET'}));revision=s.revision;const v=s.settings.maximum_flow_ft3_hour;n('flow-enabled').checked=v!==null;n('flow-maximum').value=v===null?'':String(v);
 const active=s.active_maximum_flow_ft3_hour===null?'off':s.active_maximum_flow_ft3_hour+' ft³/hour';
 say(s.saved_active?'Saved limit is active: '+active+'.':s.initialized?'Saved limit is not active. The current limit is '+active+'.':'Saved settings will apply when accounting starts.');
 }catch(_){say('Could not load flow settings. Reload when the device is available.');}finally{busy=false;controls();}}
 async function save(event){if(event)event.preventDefault();if(busy||!revision)return;
 let value;try{value=limit(n('flow-enabled').checked,n('flow-maximum').value);}catch(e){say(e.message);return;}
 busy=true;controls();say('Saving flow limit…');
 try{const s=await request({method:'POST',headers:{'Content-Type':'application/json','X-AIEdge-Revision':revision},body:JSON.stringify({version:1,maximum_flow_ft3_hour:value})});
 if(s.status==='saved_and_active'&&s.active===true)say('Saved and active. Accounting uses this limit now. Earlier records are kept.');
 else if(s.status==='saved_not_active'&&s.active===false)say('Saved, but not active. Reload to check the current limit; accounting history needs attention.');
 else throw Error('Unexpected save response');
 }catch(e){say(e.status===409?'The device is busy or the settings changed. Reload before trying again.':'Save could not be confirmed. Reload to check what was saved before trying again.');}
 finally{revision=null;busy=false;controls();}}
 n('flow-enabled').addEventListener('change',controls);n('flow-load').addEventListener('click',load);n('flow-form').addEventListener('submit',save);controls();return {load,save};
}
const api={limit,validate,mount};if(typeof module!=='undefined')module.exports=api;
if(typeof document!=='undefined')mount(document,root.fetch.bind(root)).load();
})(typeof window!=='undefined'?window:globalThis);
