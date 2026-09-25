const assert=require('node:assert/strict');
const api=require('../../../sd-card/html/image-archive.js');
const good={version:1,worker_started:true,engine_ready:true,capture_enabled:true,pending:2,blocked:0,acknowledged_awaiting_cleanup:0,stored:1,upload_acknowledgments:3,upload_failures:4,handoff_rejected:0,binding_rejected:0,enqueue_rejected:0,resources:{sampled_us:1000}};
function doc(){const nodes={};for(const id of ['refresh','notice','state','detail','pending','blocked','cleanup','stored','uploaded','failures','notqueued','notsaved'])nodes[id]={textContent:'',disabled:false,addEventListener(){}};return {nodes,getElementById:id=>nodes[id]};}
(async()=>{
 assert.equal(api.describe(good)[0],'Running');
 assert.equal(api.describe({...good,last_http_status:0,last_upload_error:'settings_connection_failed'})[0],'Retrying upload');
 assert.match(api.describe({...good,last_http_status:0,last_upload_error:'settings_connection_failed'})[1],/connect securely/);
 assert.match(api.describe({...good,blocked:1,last_http_status:401,last_upload_error:'settings_rejected'})[1],/credentials/);
 assert.match(api.describe({...good,last_http_status:503,last_upload_error:'server_rejected'})[1],/HTTP 503/);
 assert.match(api.describe({...good,blocked:1,last_http_status:201,last_upload_error:'receipt_invalid'})[1],/receipt/);
 assert.equal(api.describe({...good,last_http_status:201,last_upload_error:'none'})[0],'Running');
 assert.equal(api.describe({...good,last_http_status:0,last_upload_error:'not_started'})[0],'Running');
 assert(!api.describe({...good,last_http_status:0,last_upload_error:'secret-server-token'})[1].includes('secret-server-token'));
 for(const extra of [{last_http_status:-1},{last_http_status:600},{last_http_status:'503'},{last_upload_error:null},{last_upload_error:'x'.repeat(65)}])assert.throws(()=>api.describe({...good,...extra}));

 assert.equal(api.describe({...good,handoff_rejected:1})[0],'Some captures were not archived');
 assert.equal(api.describe({...good,enqueue_rejected:1})[0],'Some captures were not archived');
 assert.equal(api.describe({...good,blocked:1,handoff_rejected:2})[0],'Needs attention');
 assert.equal(api.describe({...good,worker_started:false})[0],'Not running');
 assert.equal(api.describe({...good,engine_ready:false,resources:{sampled_us:0}})[0],'Starting');
 assert.equal(api.describe({...good,engine_ready:false})[0],'Storage unavailable');
 assert.equal(api.describe({...good,binding_rejected:1})[0],'Some captures were not archived');
 assert.equal(api.describe({...good,blocked:1})[0],'Needs attention');
 assert.equal(api.describe({...good,capture_enabled:false})[0],'Finishing queued uploads');
 for(const bad of [null,{},[],{...good,pending:-1},{...good,pending:'2'},{...good,pending:Number.MAX_SAFE_INTEGER+1},{...good,worker_started:'true'},{...good,resources:null},{...good,resources:{sampled_us:-1}},{...good,resources:{sampled_us:'1'}},{...good,binding_rejected:-1}])assert.throws(()=>api.describe(bad));
 const d=doc(),calls=[];let response=good;
 const ui=api.mount(d,async(path,options)=>{calls.push([path,options]);return {ok:true,json:async()=>response};});
 assert.equal(calls.length,0);await ui.refresh();assert.equal(calls.length,1);assert.equal(calls[0][0],'/image_archive_status');assert.equal(calls[0][1].method,'GET');assert.equal(calls[0][1].redirect,'error');assert.equal(calls[0][1].credentials,'same-origin');
 assert.equal(d.nodes.pending.textContent,'2');assert.equal(d.nodes.uploaded.textContent,'3');assert.equal(d.nodes.state.textContent,'Running');
 response={...good,binding_rejected:5,handoff_rejected:2,enqueue_rejected:3};await ui.refresh();assert.equal(d.nodes.notqueued.textContent,'5');assert.equal(d.nodes.notsaved.textContent,'3');
 response={};await ui.refresh();assert.equal(d.nodes.pending.textContent,'Unavailable');assert.equal(d.nodes.refresh.disabled,false);
 let release;const held=api.mount(d,()=>new Promise(r=>release=r));const task=held.refresh();await held.refresh();assert(d.nodes.refresh.disabled);release({ok:false});await task;assert.equal(d.nodes.refresh.disabled,false);
 console.log('Archive UI state, invalid data, stale-count clearing, fixed read-only request and duplicate-action tests passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
