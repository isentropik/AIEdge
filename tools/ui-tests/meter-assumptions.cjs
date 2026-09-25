const fs=require('node:fs');const path=require('node:path');
for(const name of ['meter-profile.html','meter-assumptions.js']){
 const text=new TextDecoder('utf-8',{fatal:true}).decode(fs.readFileSync(path.join(__dirname,'../../sd-card/html',name)));
 if(/[\u00c2\u00c3\ufffd]/u.test(text))throw Error('Corrupt UTF-8 text: '+name);
}
const assert=require('node:assert/strict');
const api=require('../../sd-card/html/meter-assumptions.js');
const initial={revision:'a'.repeat(64),settings:{version:1,maximum_flow_ft3_hour:null},initialized:false,saved_active:false,active_maximum_flow_ft3_hour:null};
function doc(){const nodes={};for(const id of ['flow-form','flow-fields','flow-enabled','flow-maximum','flow-load','flow-save','flow-message'])nodes[id]={value:'',checked:false,disabled:false,events:{},addEventListener(k,v){this.events[k]=v;}};return {nodes,getElementById:id=>nodes[id]};}
(async()=>{
 for(const x of ['', ' ', '0', '-1','Infinity','bad','1e-999'])assert.throws(()=>api.limit(true,x));
 assert.equal(api.limit(false,'bad'),null);assert.equal(api.limit(true,'360'),360);
 for(const patch of [{settings:{}},{revision:'bad'},{saved_active:true},{active_maximum_flow_ft3_hour:360}])assert.throws(()=>api.validate({...initial,...patch}));
 const d=doc(),calls=[];let result=initial,status=200;
 const ui=api.mount(d,async(url,options)=>{calls.push([url,options]);return {ok:status===200,status,json:async()=>result};});
 assert(d.nodes['flow-save'].disabled);await ui.load();assert(!d.nodes['flow-save'].disabled&&d.nodes['flow-maximum'].disabled);
 assert.equal(calls.length,1);assert.equal(calls[0][1].method,'GET');
 d.nodes['flow-enabled'].checked=true;d.nodes['flow-enabled'].events.change();assert(!d.nodes['flow-maximum'].disabled);
 await ui.save();assert.equal(calls.length,1,'Blank enabled value never submits');
 d.nodes['flow-maximum'].value='360';result={status:'saved_and_active',active:true};await ui.save();
 assert.equal(calls.at(-1)[0],'/meter_assumptions');assert.equal(calls.at(-1)[1].redirect,'error');
 assert.deepEqual(JSON.parse(calls.at(-1)[1].body),{version:1,maximum_flow_ft3_hour:360});
 assert.equal(calls.at(-1)[1].headers['X-AIEdge-Revision'],initial.revision);
 assert.match(d.nodes['flow-message'].textContent,/Saved and active/);assert(d.nodes['flow-save'].disabled);
 await ui.save();assert.equal(calls.length,2,'No implicit repeated write');
 result={...initial,settings:{version:1,maximum_flow_ft3_hour:360},initialized:true,saved_active:true,active_maximum_flow_ft3_hour:360};
 await ui.load();assert(d.nodes['flow-enabled'].checked);assert.equal(d.nodes['flow-maximum'].value,'360');
 d.nodes['flow-enabled'].checked=false;result={status:'saved_not_active',active:false};await ui.save();
 assert.equal(JSON.parse(calls.at(-1)[1].body).maximum_flow_ft3_hour,null);
 assert.match(d.nodes['flow-message'].textContent,/not active/);
 result={...initial,initialized:true,active_maximum_flow_ft3_hour:360};await ui.load();assert.match(d.nodes['flow-message'].textContent,/current limit is 360/);
 status=409;result={error:'busy'};await ui.save();assert.match(d.nodes['flow-message'].textContent,/Reload/);assert(d.nodes['flow-save'].disabled);
 status=200;result=initial;await ui.load();result={status:'unexpected'};await ui.save();assert.match(d.nodes['flow-message'].textContent,/could not be confirmed/);
 console.log('PASS: optional flow form, input validation, saved/active feedback, disabling, conflict and no implicit retry');
})().catch(e=>{console.error(e);process.exitCode=1;});
