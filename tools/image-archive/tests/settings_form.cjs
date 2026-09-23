const assert=require('node:assert/strict');
const api=require('../../../sd-card/html/image-archive-settings.js');
const good={version:1,revision:'a'.repeat(64),enabled:true,host:'nas.local',device_id:'meter',port:8766,timeout_ms:15000,has_token:true,has_certificate:true};
function doc(){const nodes={};for(const id of ['settings-message','settings-load','settings-save','settings-form','archive-enable','archive-host','archive-port','archive-device','archive-timeout','archive-token','archive-ca','archive-show-token'])nodes[id]={value:'',checked:false,disabled:false,textContent:'',type:id==='archive-token'?'password':'text',events:{},addEventListener(k,v){this.events[k]=v;},setAttribute(k,v){this[k]=v;}};return {nodes,getElementById:id=>nodes[id]};}
(async()=>{
 for(const bad of [null,{}, {...good,revision:'bad'}, {...good,has_token:'true'}, {...good,port:0}, {...good,timeout_ms:30001}])assert.throws(()=>api.validateSaved(bad));
 const d=doc(),calls=[];let status=200,result=good;
 const ui=api.mount(d,async(url,options)=>{calls.push([url,options]);return {ok:status===200,status,json:async()=>result};});
 assert(d.nodes['settings-save'].disabled);await ui.load();assert(!d.nodes['settings-save'].disabled);assert.equal(d.nodes['archive-token'].value,'');assert.equal(d.nodes['archive-host'].value,'nas.local');
 result={status:'saved_restart_required',active_changed:false};await ui.save();
 const [url,request]=calls.at(-1);assert.equal(url,'/image_archive_settings');assert.equal(request.method,'POST');assert.equal(request.headers['X-AIEdge-Revision'],good.revision);assert.equal(request.redirect,'error');assert.equal(request.credentials,'same-origin');assert.equal(JSON.parse(request.body).token,null);assert.equal(JSON.parse(request.body).ca_pem,null);assert(d.nodes['settings-save'].disabled);assert.match(d.nodes['settings-message'].textContent,/Restart/);
 const count=calls.length;await ui.save();assert.equal(calls.length,count);
 result=good;await ui.load();d.nodes['archive-token'].value='b'.repeat(32);d.nodes['archive-show-token'].events.click();assert.equal(d.nodes['archive-token'].type,'text');assert.equal(d.nodes['archive-show-token']['aria-label'],'Hide access token');
 status=409;result={error:'changed'};await ui.save();assert.match(d.nodes['settings-message'].textContent,/Reload/);assert(d.nodes['settings-save'].disabled);
 status=200;result=good;await ui.load();status=503;result={error:'saved_but_recovery_required'};await ui.save();assert.match(d.nodes['settings-message'].textContent,/Do not repeat/);assert(d.nodes['settings-save'].disabled);
 console.log('Archive form tests passed: credential retention, revision checking, no retry after uncertain save, restart messaging and token visibility');
})().catch(e=>{console.error(e);process.exitCode=1;});
