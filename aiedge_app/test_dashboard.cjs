const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'dashboard.js'),'utf8');
class Element {
 constructor(){this.textContent='';this.hidden=false;this.disabled=false;this.value='system';this.dataset={};this.style={};this.children=[];this.attributes={};this.queries=new Map();this.classList={add(){}};}
 setAttribute(name,value){this.attributes[name]=value;}
 removeAttribute(name){delete this.attributes[name];}
 querySelector(name){if(!this.queries.has(name))this.queries.set(name,new Element());return this.queries.get(name);}
 replaceChildren(...children){this.children=children;}
 get firstChild(){return this.children[0]??null;}
 insertBefore(child,reference){this.children.splice(reference===null?this.children.length:this.children.indexOf(reference),0,child);}
 append(...children){this.children.push(...children);}
 addEventListener(){}
 getContext(){return {};}
 querySelectorAll(){return [];}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function showCaptures(app){
 app.location.hash='#captures';app.listeners.hashchange();
}
const response=value=>({ok:true,status:200,json:async()=>value});
const state={captures:1,unique_images:1,failures:0,capture_enabled:true,interval_seconds:30,missed_slots:0,
 latest:null,recognition:{state:'estimated',dial_positions:[]},reading:{state:'estimated',value:123},
 camera:{state:'ready'},storage:{state:'ready',free_bytes:1024**3},mqtt:{state:'connected'}};
const page={items:[],next_before:null};
test('page containers cannot trigger browser fragment scrolling for app routes',()=>{
 const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
 for(const route of ['overview','captures','setup','format','settings']){
  assert.ok(html.includes('id="page-'+route+'"'));assert.equal(html.includes('id="'+route+'"'),false);
 }
});
function fixture(fetch,physical=false,modules={}){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const document={getElementById:get,createElement:()=>new Element(),documentElement:{dataset:{}},hidden:true,readyState:'loading',addEventListener(){}};
 const listeners={};
 const window={...modules,addEventListener(name,fn){listeners[name]=fn;},dispatchEvent(){},renderPhysicalReading(reading){get('meter-value').textContent=reading.value===null?'—':String(reading.value);}};
 const context=vm.createContext({document,window,fetch,location:{hash:'#overview'},localStorage:{getItem(){return null;},setItem(){}},AbortSignal,setTimeout,clearTimeout,Date,console,CustomEvent:class{}});
 vm.runInContext(source,context);
 if(physical)vm.runInContext(fs.readFileSync(path.join(__dirname,'reading-format.js'),'utf8'),context);
 return {get,window,location:context.location,listeners};
}

test('leaving a capture cancels its pending review before setup handles the route',async()=>{
 const calls=[];const app=fixture(async url=>response(url==='api/status'?state:page),false,{
  AIEdgeReview:{close:()=>calls.push('close'),open:id=>calls.push('open '+id)},
  AIEdgeFlow:{renderStatus(){},statusUnavailable(){},route:hash=>{calls.push(hash);return hash.startsWith('#setup');}}
 });
 await tick();app.location.hash='#captures/9';app.listeners.hashchange();
 assert.deepEqual(calls,['#captures/9','open 9']);calls.length=0;
 app.location.hash='#setup/image';app.listeners.hashchange();assert.deepEqual(calls,['close','#setup/image']);
});

test('Setup navigation uses the guided route instead of the legacy calibration alias',async()=>{
 const app=fixture(async url=>response(url.includes('capture-history')?page:state));await tick();app.get('setup-tab').onclick();
 assert.equal(app.location.hash,'setup');
});
test('a changed page starts at the top but re-rendering the same route does not disturb scrolling',async()=>{
 const scrolls=[];const app=fixture(async url=>response(url==='api/status'?state:page),false,{scrollTo:(x,y)=>scrolls.push([x,y]),AIEdgeFlow:{renderStatus(){},statusUnavailable(){},route:()=>true}});
 await tick();app.location.hash='#setup/image';app.listeners.hashchange();assert.deepEqual(scrolls,[[0,0]]);
 app.listeners.hashchange();assert.equal(scrolls.length,1);
 app.location.hash='#setup/alignment';app.listeners.hashchange();assert.equal(scrolls.length,2);
});
test('deferred scroll reset cannot jump a later page when an older route finishes rendering',async()=>{
 const callbacks=[],scrolls=[];const app=fixture(async url=>response(url==='api/status'?state:page),false,{requestAnimationFrame:fn=>callbacks.push(fn),scrollTo:(x,y)=>scrolls.push([x,y]),AIEdgeFlow:{renderStatus(){},statusUnavailable(){},route:()=>true}});
 await tick();app.location.hash='#setup/image';app.listeners.hashchange();app.location.hash='#settings';app.listeners.hashchange();
 callbacks.shift()();assert.equal(scrolls.length,0);callbacks.shift()();assert.deepEqual(scrolls,[[0,0]]);
});
test('a transfer context hold explains the gap and clears after capture resumes',async()=>{
 let held=true,statusCalls=0;
 const current=()=>({...state,last_error:held?{error:'transfer_context_changed'}:null});
 const app=fixture(async url=>{
   if(url==='api/overview')return response({mqtt:{state:'connected',overview_meter:'gas'},
     capture_error:held?'transfer_context_changed':null});
   if(url==='api/status'){statusCalls++;return response(current());}
   return response(page);
 },false,{AIEdgeIntegration:{render(){}}});
 await tick();
 assert.equal(app.get('error').hidden,false);
 assert.equal(app.get('error').textContent,'Capture paused. Recovery settings or software changed after a photo transfer was interrupted. Review the gap to resume capture.');
 held=false;
 await app.get('refresh').onclick();await tick();
 assert.equal(app.get('error').hidden,true);
 assert.equal(app.get('error').textContent,'');
 app.get('refresh').onclick();await tick();
 assert.equal(statusCalls,2);
});
test('failed history does not clear a successful current reading',async()=>{
 const app=fixture(async url=>{if(url.includes('capture-history'))throw new TypeError('network');return response(state);});
 showCaptures(app);
 await tick();
 assert.equal(app.get('meter-value').textContent,'123');
 assert.equal(app.get('camera-status').textContent,'Camera ready');
 assert.equal(app.get('error').hidden,true);
 assert.equal(app.get('history-error').hidden,false);
 assert.equal(app.get('history-summary').textContent,'History unavailable');
 assert.equal(app.get('empty-gallery').hidden,true);
});
test('stalled history does not hold back status rendering',async()=>{
 let finish;
 const app=fixture(url=>url.includes('capture-history')?new Promise(resolve=>finish=resolve):Promise.resolve(response(state)));
 showCaptures(app);
 await tick();assert.equal(app.get('meter-value').textContent,'123');
 assert.equal(app.get('camera-status').textContent,'Camera ready');
 assert.equal(app.get('history-summary').textContent,'Loading captures…');
 assert.equal(app.get('empty-gallery').hidden,true);
 finish(response(page));await tick();assert.equal(app.get('refresh').disabled,false);
 assert.equal(app.get('history-summary').textContent,'No stored captures');
 assert.equal(app.get('empty-gallery').hidden,false);
});
test('status failure clears the current value while successful history remains available',async()=>{
 const app=fixture(async url=>{if(url==='api/status')throw new TypeError('offline');return response(page);});
 showCaptures(app);
 await tick();assert.equal(app.get('meter-value').textContent,'—');
 assert.equal(app.get('camera-status').textContent,'Connection lost');
 assert.equal(app.get('history-error').hidden,true);
 assert.equal(app.get('empty-gallery').textContent,'No stored captures yet.');
});
test('history recovery clears only its own error',async()=>{
 let fail=true;
 const app=fixture(async url=>{if(url.includes('capture-history')){if(fail)throw new Error('history');return response(page);}return response(state);});
 showCaptures(app);
 await tick();assert.equal(app.get('history-error').hidden,false);
 fail=false;app.get('refresh').onclick();await tick();
 assert.equal(app.get('history-error').hidden,true);
 assert.equal(app.get('history-summary').textContent,'No stored captures');
 assert.equal(app.get('meter-value').textContent,'123');
});
test('failed older page preserves cards and restores cursor controls',async()=>{
 let calls=0;
 const row={sha256:'a'.repeat(64),bytes:100,frame_id:'a',captured_at:'2026-01-01T00:00:00Z',received_at:'2026-01-01T00:00:01Z'};
 const app=fixture(async url=>{if(url.includes('capture-history')){calls++;if(url.includes('before='))throw new Error('page unavailable');return response({items:[row],next_before:9});}return response(state);});
 showCaptures(app);
 await tick();const original=app.get('gallery').children[0];
 await app.get('history-older').onclick();
 assert.equal(app.get('gallery').children[0],original);
 assert.equal(app.get('history-newer').disabled,true);
 assert.equal(app.get('history-older').disabled,false);
 assert.equal(app.get('history-error').hidden,false);
 assert.equal(app.get('error').hidden,true);assert.equal(calls,2);
});

test('number format prompt does not hide missing calibration or pending recognition',async()=>{
 for(const [recognition,message] of [['not_configured','Recognition is not configured.'],['waiting_for_image','Waiting for an image.'],['pending','Processing the latest image.'],['rejected','Image rejected. No total available.'],['estimated','Set the number format to calculate a reading.']]){
  const app=fixture(async url=>response(url==='api/status'?{...state,recognition:{state:recognition},reading:{state:'not_configured',value:null}}:page),true);
  await tick();assert.equal(app.get('reading-status').textContent,message,recognition);
 }
});

test('ambiguous ranges remain separate and do not render a guessed total',async()=>{
 const reading={state:'ambiguous',value:null,unit:'ft3',bounds:{state:'bounded',ranges:[
  {lower_text:'0255798.00',upper_text:'0255798.11'},
  {lower_text:'0255803.00',upper_text:'0255803.11'}],wraps_register:false}};
 const app=fixture(async url=>response(url==='api/status'?{...state,reading}:page),true);
 await tick();
 assert.equal(app.get('meter-value').textContent,'—');
 assert.equal(app.get('reading-status').textContent,'Reading unresolved. No total published.');
 assert.equal(app.get('reading-bounds').hidden,false);
 assert.equal(app.get('reading-bounds-label').textContent,'2 possible ranges');
 assert.deepEqual(app.get('reading-ranges').children.map(row=>row.textContent),[
  '0255798.00 – 0255798.11 ft³','0255803.00 – 0255803.11 ft³']);
 assert.match(app.get('reading-bounds-note').textContent,/accuracy is unverified/);
});

test('range display clears on a status outage or resolved reading',async()=>{
 let mode='ambiguous';
 const reading={state:'ambiguous',value:null,unit:'ft3',bounds:{state:'bounded',ranges:[{lower_text:'099.0',upper_text:'100.0'}],wraps_register:true}};
 const app=fixture(async url=>{
  if(url!=='api/status')return response(page);
  if(mode==='offline')throw new TypeError('network');
  return response({...state,reading:mode==='ambiguous'?reading:{state:'estimated',value:100,text:'100.0',unit:'ft3'}});
 },true);
 await tick();assert.equal(app.get('reading-bounds').hidden,false);
 assert.match(app.get('reading-bounds-note').textContent,/rollover/);
 mode='resolved';app.get('refresh').onclick();await tick();
 assert.equal(app.get('reading-bounds').hidden,true);assert.equal(app.get('reading-ranges').children.length,0);
 assert.equal(app.get('meter-value').textContent,'100.0');
 mode='ambiguous';app.get('refresh').onclick();await tick();
 mode='offline';app.get('refresh').onclick();await tick();
 assert.equal(app.get('reading-bounds').hidden,true);assert.equal(app.get('meter-value').textContent,'—');
});

test('unresolved fine digits retain only the prefix shared by the current ranges',async()=>{
 let prefix='02558';
 const app=fixture(async url=>response(url==='api/status'?{...state,reading:{state:'ambiguous',value:null,unit:'ft3',bounds:{
  state:'bounded',common_integer_prefix:prefix,wraps_register:false,
  ranges:[{lower_text:'0255803.00',upper_text:'0255803.11'},{lower_text:'0255808.00',upper_text:'0255808.11'}]
 }}}:page),true);
 await tick();assert.equal(app.get('meter-value').textContent,'02558…');assert.equal(app.get('meter-unit').textContent,'ft³');
 assert.equal(app.get('reading-status').textContent,'Fine reading unresolved. No total published.');
 prefix='02559';app.get('refresh').onclick();await tick();
 assert.equal(app.get('meter-value').textContent,'02559…');
 prefix='';app.get('refresh').onclick();await tick();assert.equal(app.get('meter-value').textContent,'—');
});

test('inconsistent dial group has a specific explanation and never a total',async()=>{
 let indices=[1,2,3,4];
 const app=fixture(async url=>response(url==='api/status'?{...state,reading:{state:'inconsistent',value:null,
  consistency:{dial_indices:indices,individual_cause_identified:false}}}:page),true);
 await tick();assert.equal(app.get('meter-value').textContent,'—');
 assert.equal(app.get('reading-bounds').hidden,true);
 assert.equal(app.get('reading-status').textContent,'Dials 2, 3, 4, 5 disagree within the reading tolerances. No total published.');
 indices=[-1,99];app.get('refresh').onclick();await tick();
 assert.equal(app.get('reading-status').textContent,'Dial positions disagree. No reading published.');
 assert.equal(app.get('meter-value').textContent,'—');
});

test('range resource limit and contradictory positions never render partial bounds',async()=>{
 for(const reading of [
  {state:'ambiguous',value:null,bounds:{state:'unavailable',reason:'range_limit'}},
  {state:'inconsistent',value:null,bounds:{state:'inconsistent',reason:'dial_bounds_disagree'}}]){
  const app=fixture(async url=>response(url==='api/status'?{...state,reading}:page),true);
  await tick();assert.equal(app.get('meter-value').textContent,'—');
  assert.equal(app.get('reading-bounds').hidden,true);assert.equal(app.get('reading-ranges').children.length,0);
 }
});

test('rejected recognition offers the relevant calibration action',async()=>{
 for(const [error,message] of [['alignment_rejected','Alignment failed. Check the reference image and markers.'],['one_or_more_dials_rejected','A dial could not be read. Check its crop and visibility.'],['image_does_not_match_calibration','Image dimensions changed. Review the calibration.']]){
  const app=fixture(async url=>response(url==='api/status'?{...state,recognition:{state:'rejected',error},reading:{state:'unavailable',reason:'image_unavailable',value:null}}:page),true);
  await tick();assert.equal(app.get('reading-status').textContent,message,error);
  assert.equal(app.get('meter-value').textContent,'—');
 }
});

test('an overloaded app is not mislabeled as a storage or network failure',async()=>{
 const app=fixture(async url=>url==='api/status'?{ok:false,status:503,json:async()=>({code:'http_busy'})}:response(page));
 await tick();assert.equal(app.get('camera-status').textContent,'App busy');
 assert.equal(app.get('error').textContent,'The app is busy. Retrying automatically.');
 assert.equal(app.get('meter-value').textContent,'—');
});

test('unknown 503 and explicit storage errors keep distinct explanations',async()=>{
 for(const [code,label,message] of [[undefined,'App unavailable','The app is temporarily unavailable. Retrying automatically.'],['storage_unavailable','Storage unavailable','Local storage is unavailable. Saved images have not been replaced.']]){
  const app=fixture(async url=>url==='api/status'?{ok:false,status:503,json:async()=>({code})}:response(page));
  await tick();assert.equal(app.get('camera-status').textContent,label);
  assert.equal(app.get('error').textContent,message);
 }
});


test('rejected capture metadata has readable messages',async()=>{
 for(const [error,message] of [['duplicate_camera_header','Camera returned repeated capture metadata. The image was rejected.'],['invalid_camera_header','Camera returned invalid capture metadata. The image was rejected.'],['invalid_image_length','Camera returned an invalid image length or transfer format. The image was rejected.']]){
  const app=fixture(async url=>response(url==='api/status'?{...state,last_error:{error}}:page));
  await tick();assert.equal(app.get('error').hidden,false);assert.equal(app.get('error').textContent,message);
 }
});

const consumption={state:'estimated',value:4.5,text:'4.50',unit:'ft3',average_rate_per_minute_text:'0.09',anchor_captured_at:'2026-09-29T00:00:00Z'};
test('relative consumption and average rate use explicit server formatting',async()=>{
 const app=fixture(async url=>response(url==='api/status'?{...state,consumption}:page));
 await tick();assert.equal(app.get('consumption-value').textContent,'4.50 ft\u00b3');
 assert.equal(app.get('consumption-rate').textContent,'0.09 ft\u00b3/min');
 assert.equal(app.get('consumption-anchor').hidden,false);
});
test('ambiguous or pending consumption clears both previous numeric values',async()=>{
 let current=consumption;
 const app=fixture(async url=>response(url==='api/status'?{...state,consumption:current}:page));
 await tick();assert.equal(app.get('consumption-value').textContent,'4.50 ft\u00b3');
 for(const unavailable of ['ambiguous','pending','within_noise']){
  current={...consumption,state:unavailable,value:null};app.get('refresh').onclick();await tick();
  assert.equal(app.get('consumption-value').textContent,'\u2014');assert.equal(app.get('consumption-rate').textContent,'\u2014');
 }
});
test('status outage never leaves a previous consumption or rate looking current',async()=>{
 let unavailable=false;
 const app=fixture(async url=>{if(url==='api/status'&&unavailable)throw TypeError('offline');return response(url==='api/status'?{...state,consumption}:page);});
 await tick();unavailable=true;app.get('refresh').onclick();await tick();
 assert.equal(app.get('consumption-value').textContent,'\u2014');assert.equal(app.get('consumption-rate').textContent,'\u2014');
 assert.equal(app.get('consumption-anchor').hidden,true);assert.equal(app.get('consumption-status').textContent,'Status unavailable.');
});

test('camera admission states distinguish readiness from an enabled schedule',async()=>{
 for(const [camera,label] of [[{state:'busy'},'Camera busy'],[{state:'settings_unavailable'},'Camera settings unavailable'],[{state:'startup_recovery'},'Camera startup recovery'],[{state:'clock_unsynchronized'},'Waiting for camera clock'],[{state:'unavailable'},'Camera unreachable'],[{state:'not_checked'},'Waiting for camera check']]){
  const app=fixture(async url=>response(url.includes('capture-history')?page:{...state,camera}));
  await tick();assert.equal(app.get('camera-status').textContent,label);
  assert.equal(app.get('schedule').textContent,'Every 30 seconds');
 }
 const disabled=fixture(async url=>response(url.includes('capture-history')?page:{...state,capture_enabled:false,camera:{state:'ready'}}));
 await tick();assert.equal(disabled.get('camera-status').textContent,'Capture disabled');
});

test('Overview reports disabled MQTT as Off rather than a Home Assistant disconnection',async()=>{
 const app=fixture(async url=>response(url==='api/status'?{...state,mqtt:{state:'disabled'}}:page));await tick();
 assert.equal(app.get('mqtt-state').textContent,'Off');
 const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
 assert.ok(html.includes('<dt>MQTT output</dt><dd id="mqtt-state">'));
});

test('overview retries independently of a stalled diagnostic request and loads history only on Captures',async()=>{
 const urls=[],renders=[];let finish,event=41;
 const app=fixture(url=>{
   urls.push(url);
   if(url==='api/overview')return Promise.resolve(response({mqtt:{state:'publishing',overview_meter:'gas',usage:{daily_nominal:{event_id:event}}}}));
   if(url==='api/status')return new Promise(resolve=>finish=resolve);
   return Promise.resolve(response(page));
 },false,{AIEdgeIntegration:{render:s=>renders.push(s.mqtt.usage.daily_nominal.event_id)}});
 await tick();assert.deepEqual(renders,[41]);event=42;
 app.get('refresh').onclick();await tick();
 assert.deepEqual(renders,[41,42]);assert.deepEqual(urls,['api/overview','api/status','api/overview']);
 showCaptures(app);await tick();assert.equal(urls.filter(url=>url.startsWith('api/capture-history')).length,1);
 finish(response(state));await tick();assert.equal(app.get('count').textContent,1);
});

test('a transport failure retains a sourced measurement until recovery, and authoritative empty data clears it',async()=>{
 let mode='cold',event=70;const renders=[];
 const app=fixture(async url=>{
   if(url!=='api/overview')return response(state);
   if(mode==='cold'||mode==='offline')throw TypeError('network');
   const usage=mode==='empty'?{}:{daily_nominal:{value_ft3:'14.00',event_id:event,measured_at:'2025-04-01T12:00:00Z'}};
   return response({mqtt:{state:'connected',overview_meter:'gas',usage}});
 },false,{AIEdgeIntegration:{render:s=>renders.push(s?.mqtt.usage.daily_nominal||null)}});
 async function refresh(as){mode=as;app.get('refresh').onclick();await tick();}
 await tick();assert.equal(renders.at(-1),null);assert.match(app.get('usage-connection').textContent,/could not be loaded/);
 await refresh('ok');const first=renders.at(-1);await refresh('offline');
 assert.deepEqual(renders.at(-1),first);assert.match(app.get('usage-connection').textContent,/Stale/);
 assert.equal(app.get('usage-connection').hidden,false);
 event++;await refresh('ok');assert.equal(renders.at(-1).event_id,event);assert.equal(app.get('usage-connection').hidden,true);
 await refresh('empty');await refresh('offline');assert.equal(renders.at(-1),null);assert.doesNotMatch(app.get('usage-connection').textContent,/Stale/);
});

test('other meters use full status and a switch back to gas re-enables overview polling',async()=>{
 const calls=[];let meter='other';
 const app=fixture(async url=>{
   calls.push(url);
   return response({...state,mqtt:{state:'connected',overview_meter:meter,usage:{}}});
 },false,{AIEdgeIntegration:{render(){}}});
 await tick();assert.deepEqual(calls,['api/overview','api/status']);
 calls.length=0;meter='gas';app.get('refresh').onclick();await tick();
 assert.deepEqual(calls,['api/status']);
 calls.length=0;app.get('refresh').onclick();await tick();
 assert.deepEqual(calls,['api/overview']);
});

function gasOverview(trend, date=Date) {
 const elements = new Map();
 const get = id => {
   if (!elements.has(id)) elements.set(id, new Element());
   return elements.get(id);
 };
 get('usage-period').value='today';
 const document = {getElementById:get, createElement:()=>new Element(),createElementNS:()=>new Element()};
 const window = {addEventListener(){}};
 const context={document,window,location:{hash:''},Intl,Date:date};
 if(trend){
  for(const id of ['day-curve','usage-period','gas-previous']){
   get(id).clientWidth=500;
   get(id).addEventListener=(name,fn)=>{get(id)['on'+name]=fn;};
  }
  Object.assign(context,{ResizeObserver:class {observe(){}},fetch:trend,AbortSignal,AbortController,
    requestAnimationFrame:fn=>queueMicrotask(fn),setTimeout:fn=>queueMicrotask(fn)});
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'gas-charts.js'),'utf8'),context);
 }
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'integration.js'),'utf8'),context);
 return {get,charts:window.AIEdgeCharts,render:(usage,metadata={})=>window.AIEdgeIntegration.render({mqtt:{usage,...metadata}})};
}

function ribbonSides(d){
 const sides=[[],[]];let side=0,last;
 for(const m of d.matchAll(/([MLQC])([^MLQCZ]+)/g)){
   const v=m[2].trim().split(/\s+/).map(Number),coords=[];
   for(let i=0;i<v.length;i+=2)coords.push([v[i],v[i+1]]);
   if(m[1]==='L')side=1;
   if(m[1]==='Q'||m[1]==='C')sides[side].push([last,...coords]);
   last=coords.at(-1);
 }
 return sides;
}
function onCurve(edge,x){
 const [a,b]=[edge[0],edge.at(-1)];
 let lo=0,hi=1;
 const at=(t,k)=>{
   const s=1-t,p=edge.map(v=>v[k]);
   return p.length===3?s*s*p[0]+2*s*t*p[1]+t*t*p[2]:
     s**3*p[0]+3*s*s*t*p[1]+3*s*t*t*p[2]+t**3*p[3];
 };
 for(let i=0;i<27;i++){const t=(lo+hi)/2;if((at(t,0)<x)===(b[0]>a[0]))lo=t;else hi=t;}
 return at((lo+hi)/2,1);
}
function ribbonAt(side,x){
 const seg=side.find(e=>x>=Math.min(e[0][0],e.at(-1)[0])-.000001&&x<=Math.max(e[0][0],e.at(-1)[0])+.000001);
 assert(seg,'Source time is outside the ribbon');return onCurve(seg,x);
}

test('hour stops keep unknown hours empty, bound usage conservatively and distinguish both 1 AM hours',async()=>{
 const day='2026-11-01',timezone='America/Los_Angeles',midnight=Date.parse(day+'T00:00:00-07:00'),hour=3600000;
 const src=(id,t)=>({event_id:id,source_sha256:id.toString(16).padStart(64,'0'),camera:'meter',format_id:'format',captured_at:new Date(t).toISOString()});
 const before=src(1,midnight-1000),after=src(2,midnight+1000),through=src(9,midnight+4.5*hour);
 const daily={day,timezone,before,after,through,lower:15,upper:16,label:'15–16 ft³',nominal_estimate:{method:'range_midpoint_v1',value_ft3:15.5}};
 class Clock extends Date{constructor(...args){super(...(args.length?args:[Date.parse(through.captured_at)]));}static now(){return Date.parse(through.captured_at);}}
 const point=(i,h,lo,hi)=>[midnight+hour*h,(lo+hi)/2,lo,hi,i];
 const groups=[[point(2,.01,0,1),point(3,.99,1,2),point(4,1.01,2,3),point(5,1.95,5,6),point(6,2.01,6,8)],[point(7,4.1,12,14)]];
 const data={day,zone:timezone,midnight,groups,status:'ready',identity:[day,timezone,'meter','format',before.source_sha256,after.source_sha256,1,before.captured_at,2,after.captured_at]};
 const ui=gasOverview(async()=>response(data),Clock);
 ui.render({daily});await tick();
 const chart=ui.get('day-curve'),label=()=>chart.attributes['aria-valuetext'],key=k=>chart.onkeydown({key:k,preventDefault(){}});
 assert.equal(chart.attributes['aria-valuemax'],4);
 key('Home');assert.match(label(),/1\.00–3\.00/);
 key('ArrowRight');assert.match(label(),/1:00 AM PDT.*1:00 AM PST.*2\.00–7\.00/);
 const paths=chart.children[0].children;
 const bands=paths.filter(n=>n.attributes.class==='plot-band');assert.equal(bands.length,2);
 const dots=paths.filter(n=>n.attributes.class==='plot-estimate-dot');
 assert.deepEqual(dots.map(n=>n.attributes['data-event']),[2,3,5,6,9]);
 // No reading in the fourth hour. Its whole interval remains blank.
 const endX=Number(dots.at(-2).attributes.cx);
 assert(ribbonSides(bands[0].attributes.d)[0].every(e=>e.at(-1)[0]<=endX+.01));
 assert.deepEqual(ribbonSides(bands[1].attributes.d),[[],[]]);
 key('ArrowRight');key('ArrowRight');assert.match(label(),/Interval unavailable/);
 assert.match(chart.attributes['aria-valuetext'],/Total unavailable/);
 key('End');assert.match(label(),/2\.00–20\.00 ft³\/h/);assert.equal(chart.dataset.endEvent,'9');
 assert.match(chart.attributes['aria-valuetext'],/Total 15\.50 ft³/);
});

test('the daily chart follows the displayed publication through delayed history, gaps and stale readings',async()=>{
 const day='2025-01-05',timezone='UTC';
 const start=Date.parse(day+'T00:00:00Z');
 let now=start+3600000,reads=0;
 class Clock extends Date {constructor(...args){super(...(args.length?args:[now]));}static now(){return now;}}
 const source=id=>({camera:'meter',format_id:'profile',event_id:id,source_sha256:id.toString(16).padStart(64,'0'),
  captured_at:new Date(start+1000*id).toISOString()});
 const range=id=>({day,timezone,before:source(1),after:source(2),through:source(id),lower:'2.00',upper:'6.00',
  label:'2.00–6.00 ft³',nominal_estimate:{method:'range_midpoint_v1',value_ft3:'4.00'}});
 const nominal=(id,v)=>({day,timezone,event_id:id,source_sha256:source(id).source_sha256,measured_at:source(id).captured_at,
  method:'range_midpoint_v1',status:'daily_range',value_ft3:v,lower_ft3:2,upper_ft3:6});
 const point=id=>[start+id*1000,4,2,6,id];
 const history=end=>({day,zone:timezone,status:'ready',midnight:start,groups:[[point(3)],[point(6),point(end)]],
  identity:[day,timezone,'meter','profile',source(1).source_sha256,source(2).source_sha256,1,source(1).captured_at,2,source(2).captured_at],
  last_digest:source(end).source_sha256,last_captured_at:source(end).captured_at});
 let data=history(7),answer;
 const ui=gasOverview(()=>{reads++;return new Promise(resolve=>{answer=()=>resolve(response(data));});},Clock);
 const chart=ui.get('day-curve');
 const paths=cls=>chart.children[0].children.filter(n=>n.attributes.class===cls);
 const knots=()=>paths('plot-estimate-dot').map(n=>n.attributes['data-event']);
 const assertEnd=id=>{
  assert.equal(chart.dataset.endEvent,String(id));assert.equal(chart.dataset.endTime,source(id).captured_at);
  assert.equal(ui.get('usage-estimate').dataset.eventId,String(id));
 };
 ui.render({daily:range(8),daily_nominal:nominal(7,4)});assertEnd(8);assert.deepEqual(knots(),[8]);
 answer();await tick();assertEnd(8);assert.deepEqual(knots(),[3,8]);
 assert.deepEqual(paths('plot-history-gap').map(n=>[n.attributes['data-from'],n.attributes['data-to']]),[[point(3)[0],point(6)[0]]]);
 assert.equal(paths('plot-estimate').length,1);
 ui.render({daily:range(8),daily_nominal:nominal(9,5)});assertEnd(9);
 assert.match(chart.attributes['aria-valuetext'],/Total 5.00 ft³/);assert.equal(reads,1);
 // The independent nominal is a separate point until its own daily range is linked.
 assert.equal(paths('plot-band').length,2);
 const partial={...nominal(10,7),method:'observed_increments',status:'partial_coverage',lower_ft3:null,upper_ft3:null};
 ui.render({daily:range(8),daily_nominal:partial});assertEnd(10);assert.deepEqual(knots(),[3,10]);assert(paths('plot-estimate').every(n=>!n.attributes.d.includes(' C')));
 assert.match(chart.attributes['aria-valuetext'],/Total 7.00 ft³.*Partial coverage$/);
 assert.equal(paths('plot-band').length,1);
 // Earlier bounded readings share a ribbon; the isolated partial estimate remains outside it.
 const ribbonX=paths('plot-band')[0].attributes.d.match(/(?:M|L)([\d.]+)/g).map(v=>Number(v.slice(1)));
 const partialX=Number(paths('plot-estimate').at(-1).attributes.d.slice(1).split(' ')[0]);
 assert(Math.max(...ribbonX)<partialX);
 data=history(8);now+=125000;
 ui.render({daily:{...range(8),status:'stale',checked_through:source(15)},daily_nominal:nominal(6,4)});
 answer();await tick();assertEnd(8);assert.deepEqual(knots(),[3,8]);
 assert.match(chart.attributes['aria-valuetext'],/Stale$/);
 // Same millisecond and event number are insufficient to join a different source.
 data={...data,last_captured_at:data.last_captured_at.replace('.000Z','.000001Z')};now+=125000;
 ui.render({daily:range(8)});answer();await tick();assert.deepEqual(knots(),[3,8]);assert(paths('plot-estimate').every(n=>!n.attributes.d.includes(' C')));
 data={...history(8),last_digest:source(4).source_sha256};now+=125000;
 ui.render({daily:range(8)});answer();await tick();assert.deepEqual(knots(),[3,8]);assert(paths('plot-estimate').every(n=>!n.attributes.d.includes(' C')));
 data=history(12);now+=125000;
 ui.render({daily:range(8)});answer();await tick();assertEnd(8);assert.deepEqual(knots(),[3,8]);assert(paths('plot-estimate').every(n=>!n.attributes.d.includes(' C')));
 ui.render({daily_nominal:{...partial,value_ft3:0}});assertEnd(10);assert.deepEqual(knots(),[10]);
 assert.match(chart.attributes['aria-valuetext'],/Total 0.00 ft³.*Partial coverage/);
 ui.render({daily:range(8),daily_nominal:{...partial,method:'nominal_meter_movement_v1',coverage_started_at:source(3).captured_at}});
 assert.match(ui.get('usage-assumption').textContent,/Partial coverage · Fine dial since/);
 assert.match(ui.get('usage-bounds').textContent,/^Earlier daily range .*Meter event 8$/);
 assertEnd(10);
 ui.render({daily_nominal:{day,timezone,status:'opening_balance',value_ft3:'0.00'}});
 assert.equal(chart.dataset.endEvent,undefined);assert.equal(chart.hidden,true);
 assert.match(ui.get('usage-time').textContent,/Awaiting the first measurement/);
 ui.render({});assert.equal(chart.dataset.endTime,undefined);
});

test('contradictory daily bounds leave a break in both the line and its ribbon',async()=>{
 const day=new Date().toISOString().slice(0,10),timezone='UTC',midnight=Date.parse(day+'T00:00:00Z');
 const source=id=>({camera:'meter',format_id:'dial',event_id:id,source_sha256:id.toString(16).padStart(64,'0'),captured_at:new Date(midnight+id*60000).toISOString()});
 const before=source(1),after=source(2),through=source(9);
 const daily={day,timezone,before,after,through,lower:5,upper:7,label:'5–7 ft³',nominal_estimate:{method:'range_midpoint_v1',value_ft3:6}};
 const groups=[[[midnight+180000,12,10,14,3]],[[Date.parse(through.captured_at),6,5,7,9]]];
 const ui=gasOverview(async()=>response({day,zone:timezone,midnight,groups,status:'ready',last_digest:through.source_sha256,last_captured_at:through.captured_at,
   identity:[day,timezone,'meter','dial',before.source_sha256,after.source_sha256,1,before.captured_at,2,after.captured_at]}));
 ui.render({daily,daily_nominal:{...through,day,timezone,measured_at:through.captured_at,value_ft3:6,method:'range_midpoint_v1',lower_ft3:5,upper_ft3:7}});await tick();
 const paths=ui.get('day-curve').children[0].children;
 assert.equal(paths.filter(n=>n.attributes.class==='plot-estimate').length,2);
 const ribbons=paths.filter(n=>n.attributes.class==='plot-band');assert.equal(ribbons.length,2);
 for(const path of ribbons){
   const xs=[...path.attributes.d.matchAll(/[ML]([\d.]+)/g)].map(m=>+m[1]);
   assert.equal(new Set(xs).size,1);
 }
});

test('the daily clock axis aligns in a fractional-offset zone and inspection stays transient',async()=>{
 const zone='Asia/Kathmandu',day='2026-11-21',midnight=Date.parse(day+'T00:00:00+05:45');
 const source=(id,dt)=>({camera:'meter',format_id:'fmt',event_id:id,source_sha256:String(id).repeat(64),captured_at:new Date(midnight+dt).toISOString()});
 const before=source(1,-500),after=source(2,500),through=source(9,24000000);
 const Clock=class extends Date{constructor(...args){super(...(args.length?args:[through.captured_at]));}};
 const groups=[[[midnight,0,0,0,2],[midnight+18000000,4,1,7,6],[Date.parse(through.captured_at),5,2,8,9]]];
 const daily={day,timezone:zone,before,after,through,lower:2,upper:8,label:'2–8 ft³',nominal_estimate:{method:'range_midpoint_v1',value_ft3:5}};
 const ui=gasOverview(async()=>response({day,zone,midnight,groups,status:'ready',identity:[day,zone,'meter','fmt',before.source_sha256,after.source_sha256,1,before.captured_at,2,after.captured_at],last_digest:through.source_sha256,last_captured_at:through.captured_at}),Clock);
 const host=ui.get('day-curve');host.clientWidth=300;
 ui.render({daily});await tick();
 assert.deepEqual(host.children[0].children.filter(n=>n.attributes.class==='time-tick').map(n=>n.textContent),['12 AM','2 AM','4 AM','6 AM']);
 const tip=ui.get('day-tip');assert(tip.hidden);
 host.onfocus();assert.equal(tip.hidden,false);
 host.onkeydown({key:'End',preventDefault(){}});assert.match(host.attributes['aria-valuetext'],/Total 5.00 ft³/);
 host.onpointerleave({pointerType:'mouse'});assert(tip.hidden);
 host.onfocus();host.onpointercancel();assert(tip.hidden);
});

test('hourly curves use real readings, preserve plateaus and never overshoot their sampled bounds',async()=>{
 const day='2026-11-21',zone='UTC',midnight=Date.parse(day+'T00:00:00Z'),hour=3600000;
 const source=(id,t)=>({camera:'meter',format_id:'fmt',event_id:id,source_sha256:id.toString(16).padStart(64,'0'),captured_at:new Date(midnight+t*hour).toISOString()});
 const before=source(1,-.01),after=source(2,0),through=source(10,3.5);
 class Clock extends Date{constructor(...args){super(...(args.length?args:[through.captured_at]));}}
 const rows=[[0,0,0],[.4,1,5],[.9,2,6],[1.1,2,7],[1.9,2,6],[2.4,3,8],[2.95,5,14],[3.2,8,16],[3.5,9,19]];
 const group=rows.map(([t,l,h],i)=>[midnight+t*hour,(l+h)/2,l,h,i+2]);
 const daily={day,timezone:zone,before,after,through,lower:9,upper:19,label:'9–19 ft³',nominal_estimate:{method:'range_midpoint_v1',value_ft3:14}};
 const nominal={...through,day,timezone:zone,measured_at:through.captured_at,method:'range_midpoint_v1',status:'daily_range',value_ft3:14,lower_ft3:9,upper_ft3:19};
 const identity=[day,zone,'meter','fmt',before.source_sha256,after.source_sha256,1,before.captured_at,2,after.captured_at];
 const ui=gasOverview(async()=>response({day,zone,midnight,identity,status:'ready',groups:[group.slice(0,6),group.slice(6)],last_digest:through.source_sha256,last_captured_at:through.captured_at}),Clock);
 ui.render({daily,daily_nominal:nominal});await tick();
 const paths=ui.get('day-curve').children[0].children;
 const dots=paths.filter(n=>n.attributes.class==='plot-estimate-dot');
 assert.deepEqual(dots.map(n=>n.attributes['data-event']),[2,4,6,8,10]);
 const host=ui.get('day-curve'),cursor=paths.find(n=>n.attributes.class==='plot-cursor');
 host.onkeydown({key:'Home',preventDefault(){}});
 const green=paths.find(n=>n.attributes.class==='plot-usage-dot');
 assert.equal(cursor.attributes.transform,'translate('+green.attributes.cx+' 0)');
 // The selected daily sample is earlier than the clock boundary and keeps its own timestamp.
 assert.equal(green.attributes.cx+cursor.children[1].attributes.cx,dots[1].attributes.cx);
 const [upper,lower]=ribbonSides(paths.find(n=>n.attributes.class==='plot-band').attributes.d);
 const traces=paths.filter(n=>n.attributes.class==='plot-estimate');
 assert.equal(traces.length,1);
 const marks=paths.filter(n=>n.attributes.class==='plot-history-gap');
 assert.deepEqual(marks.map(n=>[n.attributes['data-from'],n.attributes['data-to']]),[[group[5][0],group[6][0]]]);
 assert(!ui.get('day-gap-key').hidden);
 const line=traces.flatMap(p=>ribbonSides(p.attributes.d)[0]);
 assert.equal(line.length,dots.length-1);
 const y=v=>293-281*v/20;
 for(const [i,e] of line.entries()){
   const a=dots[i],b=dots[i+1],ra=group[a.attributes['data-event']-2],rb=group[b.attributes['data-event']-2];
   for(const f of [0,.1,.5,.9,1]){
     const x=e[0][0]+f*(e.at(-1)[0]-e[0][0]),v=onCurve(e,x);
     assert(v>=Math.min(y(ra[1]),y(rb[1]))-.02&&v<=Math.max(y(ra[1]),y(rb[1]))+.02);
     assert(v>=ribbonAt(upper,x)-.02&&v<=ribbonAt(lower,x)+.02);
   }
   assert(Math.abs(e.at(-1)[1]-y(rb[1]))<.02);
   assert(Math.abs(ribbonAt(upper,e.at(-1)[0])-y(rb[3]))<.02);
   assert(Math.abs(ribbonAt(lower,e.at(-1)[0])-y(rb[2]))<.02);
 }
});

test('absolute presentation rounds decimal text and preserves the exact source',()=>{
 const ui = gasOverview();
 const absolute_nominal = {event_id:31, measured_at:'2025-03-03T12:00:00Z',source_sha256:'1'.repeat(64),
   value_ft3:'9999999999999999.95', bands_ft3:[['1.001','1.009']],status:'partial_coverage'};
 ui.render({absolute_nominal});
 assert.equal(ui.get('absolute-value').textContent,'10,000,000,000,000,000.0 ft³');
 assert.match(ui.get('absolute-value').dataset.fullValue,/9999999999999999\.95/);
 assert.match(ui.get('absolute-value').dataset.eventId,/31/);
 assert.equal(ui.get('absolute-value').dataset.measuredAt,absolute_nominal.measured_at);
 assert.match(ui.get('absolute-status').textContent,/Partial/);
 ui.render({});
 assert.equal(ui.get('absolute-value').dataset.eventId,undefined);
 assert.equal(ui.get('absolute-value').dataset.fullValue,undefined);
});

test('photo-anchored absolute estimate keeps its own bounds, event and held time',()=>{
 const ui=gasOverview();
 const absolute_nominal={event_id:48, measured_at:'2025-03-03T12:01:03Z', source_sha256:'b'.repeat(64),
   value_ft3:'20139.723',lower_ft3:'20129.6',upper_ft3:'20154.8',method:'photo_anchored_fine_dial',status:'estimated'};
 ui.render({absolute_nominal});
 assert.equal(ui.get('absolute-value').textContent,'20,139.7 ft³');
 assert.equal(ui.get('absolute-bounds').textContent,'Absolute bounds · 20,129.6–20,154.8 ft³');
 ui.render({absolute_nominal:{...absolute_nominal,status:'held_at_last_reading'}});
 assert.match(ui.get('absolute-status').textContent,/Last supported estimate/);
 assert.equal(ui.get('absolute-value').dataset.measuredAt,absolute_nominal.measured_at);
 ui.render({});
 assert.equal(ui.get('absolute-bounds').hidden,true);
});

test('photo register shows its hundred resolution and original time after a hold',()=>{
 const ui=gasOverview();
 const absolute_nominal={event_id:48, measured_at:'2025-03-03T12:01:03Z', source_sha256:'b'.repeat(64),
   value_ft3:'20400', resolution_ft3:100, method:'photo_register_hundreds', status:'photo_register'};
 ui.render({absolute_nominal});
 assert.equal(ui.get('absolute-value').textContent,'20,400 ft³');
 assert.equal(ui.get('absolute-status').textContent,'100 ft³ resolution');
 assert.equal(ui.get('absolute-value').dataset.eventId,'48');
 ui.render({absolute_nominal:{...absolute_nominal,status:'held_at_last_reading'}});
 assert.match(ui.get('absolute-status').textContent,/Last photo reading/);
 assert.equal(ui.get('absolute-value').dataset.measuredAt,absolute_nominal.measured_at);
});

test('historical segment precision is a display choice with the original measurement available',()=>{
 const ui = gasOverview();
 const historical = {value:0.123456789,event_id:8,captured_at:'2025-03-03T12:00:00Z',source_sha256:'2'.repeat(64),segment_started_at:'2025-03-03T09:00:00Z'};
 ui.render({historical});
 assert.equal(ui.get('segment-value').textContent,'0.12 ft³');
 assert.equal(ui.get('segment-value').dataset.fullValue,'0.123456789');
 ui.render({});
 assert.equal(ui.get('segment-value').dataset.eventId,undefined);
});

test('one plot switches windows immediately, keeps real zero whiskers and rejects a conflicting source',async()=>{
 const t=Date.UTC(2026,10,1,8);
 const src=i=>({event_id:i+10,source_sha256:i.toString(16).padStart(64,'0'),camera:'meter',format_id:'fmt',clock_id:'clock',captured_at:new Date(t+i*900000).toISOString()});
 const span=(a,b,lo,hi)=>({start:src(a),through:src(b),lower:lo,upper:hi});
 const recent={hour:span(0,4,'1.00','2.00'),through:src(4),timezone:'America/Los_Angeles',label:'1.00–2.00 ft³',
   quarters:[span(0,1,0,0),span(1,2,0,1),span(2,3,0,1),span(3,4,0,1)]};
 const bin=(a,b,l,h,lo,hi)=>({start:src(a).captured_at,end:src(b).captured_at,lower:l,upper:h,total_lower:lo,total_upper:hi});
 const data={start:src(0).captured_at,end:src(4).captured_at,minutes:15,bins:[bin(0,1,0,0,0,0),bin(1,2,0,1,0,1),bin(2,3,null,null,null,null),bin(3,4,0,1,1,2)]};
 const result={...recent,status:'ready',history_available:true,periods:{'1':data,'6':{...data,minutes:30}}};
 let answer,reads=0;
 const ui=gasOverview(()=>{reads++;return new Promise(resolve=>{answer=resolve;});});
 ui.render({recent});assert.equal(reads,0);
 const filter=ui.get('usage-period'),chart=ui.get('day-curve');
 filter.value='1';filter.onchange();assert.equal(reads,1);
 const marks=()=>chart.children[0].children.filter(n=>n.attributes.class==='plot-usage-dot');
 assert.equal(marks().length,4);  // Native quarters paint before the recorder returns.
 const x=i=>36+(chart.clientWidth-72)*i/4;
 const closeChecks=(indices)=>{
   const nodes=chart.children[0].children,stems=nodes.filter(n=>n.attributes.class==='plot-whisker');
   const left=nodes.filter(n=>n.attributes.class==='total-tick'),right=nodes.filter(n=>n.attributes.class==='use-tick');
   const grid=nodes.filter(n=>n.attributes.class==='plot-grid');
   assert.equal(grid.length,5);
   const positions=grid.map(n=>n.attributes.y1);
   assert.deepEqual(left.map(n=>n.attributes.y-4),positions);
   assert.deepEqual(right.map(n=>n.attributes.y-4),positions);
   assert(positions.slice(1).every((v,i)=>v-positions[i]===positions[1]-positions[0]));
   assert.equal(+right.at(-1).textContent,4);assert(+left.at(-1).textContent<=2);
   assert.equal(+right[0].textContent,0);
   const y=v=>+right[0].attributes.y-4+(right.at(-1).attributes.y-right[0].attributes.y)*v/Number(right.at(-1).textContent);
   assert.equal(marks()[0].attributes.cy,y(0));
   assert(Math.abs(+marks()[1].attributes.cy-y(2))<.01);
   assert.deepEqual(marks().map(n=>n.attributes.cx),indices.map(x));
   assert.deepEqual(stems.map(n=>Number(/ M([^ ]+) /.exec(n.attributes.d)[1])),indices.filter(i=>i!==1).map(x));
   const ticks=nodes.filter(n=>n.attributes.class==='time-tick');
   assert(ticks.length>0&&ticks.every(n=>[1,2,3,4].map(x).includes(n.attributes.x)));
 };
 closeChecks([1,2,3,4]);
 chart.getBoundingClientRect=()=>({left:23});
 for(const index of [3,1,0,2]){
   const pos=x(index+1);
   chart.onpointerdown({clientX:pos+23});
   assert.equal(chart.attributes['aria-valuenow'],index);
   const cursor=chart.children[0].children.find(n=>n.attributes.class==='plot-cursor');
   assert.equal(cursor.attributes.transform,'translate('+pos+' 0)');
   assert.equal(cursor.children[1].attributes.cx,0);
 }
 answer(response(result));await tick();closeChecks([1,2,4]);
 chart.onkeydown({key:'Home',preventDefault(){}});
 assert.match(chart.attributes['aria-valuetext'],/Total 0.00 ft³.*Rate 0.00 ft³\/h/);
 filter.value='6';filter.onchange();assert.equal(marks().length,3);
 const next={...recent,through:src(5),hour:span(1,5,2,3),quarters:[span(1,2,0,1),span(2,3,0,1),span(3,4,0,1),span(4,5,0,1)]};
 ui.render({recent:next});assert.equal(marks().length,3);
 assert.equal(chart.dataset.endTime,src(4).captured_at);assert.match(ui.get('day-history-status').textContent,/Last saved/);
 answer(response({...result,through:{...src(5),source_sha256:'f'.repeat(64)}}));await tick();
 assert.equal(chart.dataset.endTime,src(4).captured_at);
 filter.value='today';filter.onchange();assert.equal(chart.hidden,true);
});

test('Today fills earlier hours only from an archive paired to the movement checkpoint',async()=>{
 const day='2026-11-21',timezone='UTC',midnight=Date.parse(day+'T00:00:00Z'),hour=3600000;
 const src=(id,ms)=>({event_id:id,source_sha256:String(id).padStart(64,'0'),captured_at:new Date(midnight+ms).toISOString(),camera:'meter',format_id:'f'});
 const before=src(1,-3000),after=src(2,1000),end=src(9,3*hour);
 const daily={day,timezone,before,after,through:end,lower:10,upper:18,label:'10–18 ft³',nominal_estimate:{method:'range_midpoint_v1',value_ft3:14}};
 const identity=[day,timezone,'meter','f',before.source_sha256,after.source_sha256,1,before.captured_at,2,after.captured_at];
 const start=[midnight+2*hour,12,7,1],points=[start,[midnight+3*hour,13,9,2]];
 const meter_prefix={points:[[midnight+1000,0,2,'h1'],[midnight+hour-1000,2,3,'h1']],anchor:start.slice(0,3),offset:4};
 const nominal={...end,measured_at:end.captured_at,day,timezone,value_ft3:'13',method:'nominal_meter_movement_v1',status:'partial_coverage'};
 class Clock extends Date{constructor(...args){super(...(args.length?args:[midnight+3*hour]));}static now(){return midnight+3*hour;}}
 for(const match of [true,false]){
  const ui=gasOverview(async()=>response({status:'ready',identity,day,zone:timezone,midnight,
   groups:[[[midnight+hour-1000,7,5,9,3]]],meter_prefix:{...meter_prefix,anchor:match?meter_prefix.anchor:[start[0],11,7]}}),Clock);
  ui.render({daily,daily_nominal:nominal,movement_history:{midnight,points}});await tick();
  const host=ui.get('day-curve');host.onkeydown({key:'Home',preventDefault(){}});
  assert.equal(ui.get('day-tip-amount').textContent,match?'2.00 ft³':'—');
  if(match){
   assert(host.attributes['aria-valuetext'].includes('5.00–9.00'));
   host.onkeydown({key:'ArrowRight',preventDefault(){}});
   assert.equal(ui.get('day-tip-amount').textContent,'—');
  }
 }
});

test('hourly meter curve uses real closes, clips ledger gaps and ignores missing MQTT publications',async()=>{
 const day='2026-11-21',timezone='UTC',midnight=Date.parse(day+'T00:00:00Z'),hour=3600000;
 const src=(id,ms)=>({event_id:id,source_sha256:String(id).padStart(64,'0'),captured_at:new Date(midnight+ms).toISOString(),camera:'meter',format_id:'f'});
 const before=src(1,-3000),after=src(2,1000),end=src(80,3*hour+2000);
 const identity=[day,timezone,'meter','f',before.source_sha256,after.source_sha256,1,before.captured_at,2,after.captured_at];
 const daily={day,timezone,before,after,through:end,lower:10,upper:18,label:'10–18 ft³',nominal_estimate:{method:'range_midpoint_v1',value_ft3:14}};
 const points=[[midnight+1000,0,2,1],[midnight+4000,1,3,2],[midnight+hour-1000,2,20,3],
   [midnight+2*hour-1000,7,43,11],[midnight+3*hour-1000,11,70,39],[midnight+3*hour+2000,13,80,40]];
 const nominal={...end,measured_at:end.captured_at,day,timezone,value_ft3:'13',method:'nominal_meter_movement_v1',status:'partial_coverage'};
 const gap=[midnight+hour+1000,midnight+hour+50000];
 const capture_coverage={first:[2,midnight+1000],through:[80,midnight+3*hour+2000],gaps:[gap]};
 const groups=[[[midnight+hour-1000,2,1,3,20]],[[midnight+3*hour-1000,11,9,13,70]]];
 class Clock extends Date{constructor(...args){super(...(args.length?args:[midnight+3*hour+2000]));}static now(){return midnight+3*hour+2000;}}
 const ui=gasOverview(async()=>response({status:'ready',identity,day,zone:timezone,midnight,groups,capture_coverage}),Clock);
 ui.render({daily,daily_nominal:nominal,movement_history:{midnight,points}});await tick();
 const host=ui.get('day-curve'),nodes=host.children[0].children;
 const paths=nodes.filter(n=>n.attributes.class==='plot-estimate');
 assert.equal(paths.length,1);assert.equal(paths[0].attributes.d.split(' C').length-1,4);
 assert.equal(paths[0].attributes['clip-path'],'url(#meter-capture-coverage)');
 assert.deepEqual(nodes.filter(n=>n.attributes.class==='plot-estimate-dot').map(n=>n.attributes['data-event']),[2,20,43,70,80]);
 assert.deepEqual(nodes.filter(n=>n.attributes.class==='plot-history-gap').map(n=>[n.attributes['data-from'],n.attributes['data-to']]),[gap]);
 const dialGap=[midnight+2*hour+1200,midnight+2*hour+4200];
 const delayed={...capture_coverage,through:[43,points[3][0]]};
 const resumed=gasOverview(async()=>response({status:'ready',identity,day,zone:timezone,midnight,groups,capture_coverage:delayed}),Clock);
 resumed.render({daily,daily_nominal:nominal,movement_history:{midnight,points,dial_from:[20,points[2][0]],dial_gaps:[gap,dialGap]}});await tick();
 const drawn=resumed.get('day-curve').children[0].children;
 assert.deepEqual(drawn.filter(n=>n.attributes.class==='plot-history-gap').map(n=>[n.attributes['data-from'],n.attributes['data-to']]),[gap,dialGap]);
 const clips=drawn.find(n=>n.tagName==='defs'||n.children?.[0]?.attributes?.id==='meter-capture-coverage').children[0].children;
 const lastDot=drawn.filter(n=>n.attributes.class==='plot-estimate-dot').at(-1);
 assert(Math.abs(Number(clips.at(-1).attributes.x)+Number(clips.at(-1).attributes.width)-Number(lastDot.attributes.cx))<0.0001);
});

test('partial day plots anchored meter readings, clips each gap, and rejects expired rolling ranges',async()=>{
 const day='2026-02-03',midnight=Date.parse(day+'T00:00Z'),minute=60000;
 const points=[[610,0,10,0],[659,2,22,0],[719,4.1,43,1],[748,5.4,65,1]]
   .map(([m,...rest])=>[midnight+m*minute,...rest]);
 const first=points[0],tail=points.at(-1),gap=[midnight+680*minute,midnight+681*minute];
 const from=[first[2],first[0]],prior={event_id:3,captured_at:new Date(midnight-3600000).toISOString(),
   source_sha256:'3'.repeat(64),camera:'meter',format_id:'fmt',clock_id:'clock'};
 const end=prior.captured_at,start=new Date(Date.parse(end)-3600000).toISOString();
 const expired={start,end,minutes:15,bins:[{start,end,lower:1,upper:3,total_lower:1,total_upper:3}]};
 const ref={timezone:'UTC',through:prior};
 const result={...ref,status:'ready',history_available:true,periods:{'1':expired,'24':expired}};
 const nominal={day,timezone:'UTC',value_ft3:'5.40',event_id:65,source_sha256:'9'.repeat(64),
   measured_at:new Date(tail[0]).toISOString(),method:'nominal_meter_movement_v1',status:'partial_coverage'};
 class Clock extends Date{constructor(...args){super(...(args.length?args:[tail[0]]));}static now(){return tail[0];}}
 const ui=gasOverview(async()=>response(result),Clock),host=ui.get('day-curve'),filter=ui.get('usage-period');
 const render=gaps=>ui.render({daily_nominal:nominal,chart_period_reference:ref,
   movement_history:{midnight,points,dial_from:from,dial_gaps:gaps}});
 const nodes=cls=>host.children[0].children.filter(n=>n.attributes.class===cls);
 const select=async value=>{filter.value=value;filter.onchange();await tick();};
 render([[midnight,first[0]],gap]);
 assert.equal(nodes('plot-estimate').filter(p=>p.attributes.d.includes(' C')).length,1);
 assert.deepEqual(nodes('plot-history-gap').map(p=>[p.attributes['data-from'],p.attributes['data-to']]),[gap]);
 assert.equal(nodes('plot-estimate-dot')[0].attributes.cx,36);
 assert.deepEqual(nodes('plot-estimate-dot').map(p=>p.attributes['data-event']),[10,22,43,65]);
 assert.equal(ui.get('interval-key').textContent,'Rate (ft³/h)');
 assert.deepEqual(nodes('plot-usage-dot').map(n=>n.attributes['data-through-event']),[22,43,65]);
 assert.equal(nodes('plot-whisker').length,0);
 for(const [window,delta] of [['1','1.30'],['24','5.40']]){
   await select(window);
   assert.equal(host.dataset.endEvent,'65');
   assert.equal(host.dataset.endTime,nominal.measured_at);
   assert(ui.get('day-history-status').textContent.includes(delta+' ft³ tracked'));
   assert.equal(nodes('plot-usage-dot').length,window==='1'?1:3);
   assert.equal(nodes('plot-whisker').length,0);
   assert.equal(nodes('plot-band').length,0);
 }
 await select('today');
 render([[midnight,first[0]]]); // A missing interruption cannot authorize a connecting curve.
 assert(!nodes('plot-estimate').some(p=>p.attributes['clip-path']));
 assert(nodes('plot-estimate').length>=2);
});

test('tracked bounds use their own event pair and never bridge an empty hour',async()=>{
 const midnight=Date.parse('2026-02-03T00:00Z'),hour=3600000,source_sha256='c'.repeat(64);
 const points=[[1,0,11,0],[1.5,1,20,0],[4,1,40,1],[4.5,2,50,1]].map(([h,...rest])=>[midnight+h*hour,...rest]);
 const first=points[0],last=points.at(-1),gap=[points[1][0],points[2][0]];
 const anchor=[11,first[0]],measured_at=new Date(last[0]).toISOString();
 const movement_history={midnight,format:'fmt',points,dial_from:anchor,dial_gaps:[[midnight,first[0]],gap]};
 const daily_nominal={day:'2026-02-03',timezone:'UTC',value_ft3:'2',event_id:50,source_sha256,measured_at,
   method:'nominal_meter_movement_v1',status:'partial_coverage',coverage_started_at:new Date(first[0]).toISOString()};
 const edge=(a,b,use,total)=>({start:[a[2],a[0]],end:[b[2],b[0]],use,total});
 const data={format:'fmt',midnight,anchor,event:50,measured_at,digest:source_sha256,joins:[],edges:[
   edge(first,points[1],[90,125],[90,125]),edge(points[1],points[2],[0,0],[90,125]),
   edge(points[2],last,[85,130],[175,255])]};
 class Clock extends Date{constructor(...args){super(...(args.length?args:[last[0]]));}static now(){return last[0];}}
 for(const [digest,expected] of [[source_sha256,[20,50]],['d'.repeat(64),[]]]){
   const ui=gasOverview(async()=>response({...data,digest}),Clock),host=ui.get('day-curve');
   ui.render({daily_nominal,movement_history});await tick();
   const nodes=cls=>host.children[0].children.filter(n=>n.attributes.class===cls);
   assert.deepEqual(nodes('plot-whisker').map(n=>n.attributes['data-through-event']),expected);
   assert.equal(nodes('plot-band').length,expected.length?2:0);
   assert.equal(nodes('plot-history-gap').length,1);
   assert(!nodes('plot-usage-dot').some(n=>n.attributes['data-through-event']===40));
   assert.equal(host.dataset.endEvent,'50');
 }
});

test('movement headline and chart stay on their meter event when range-only publications change',async()=>{
 const day='2026-11-21',timezone='UTC',midnight=Date.parse(day+'T00:00:00Z');
 const src=id=>({camera:'meter',format_id:'profile',event_id:id,source_sha256:id.toString(16).padStart(64,'0'),
   captured_at:new Date(midnight+id*3600000).toISOString()});
 class Clock extends Date{constructor(...args){super(...(args.length?args:[midnight+8*3600000]));}static now(){return midnight+8*3600000;}}
 const range=(id,lower,upper)=>({day,timezone,through:src(id),before:src(1),after:src(2),lower,upper,
   label:lower+'–'+upper+' ft³',nominal_estimate:{method:'range_midpoint_v1',value_ft3:(lower+upper)/2}});
 const ui=gasOverview(async()=>response({status:'unavailable'}),Clock),through=src(5);
 const nominal={...through,day,timezone,measured_at:through.captured_at,value_ft3:'17.15',method:'nominal_meter_movement_v1',
   status:'partial_coverage',lower_ft3:8,upper_ft3:12,bounds_event_id:4,bounds_measured_at:src(4).captured_at,bounds_source_sha256:src(4).source_sha256};
 const movement_history={midnight,points:[[Date.parse(src(3).captured_at),16.02,3,0],[Date.parse(through.captured_at),17.15,5,1]]};
 ui.render({daily:range(6,9,11),daily_nominal:nominal,movement_history});await tick();
 const host=ui.get('day-curve'),nodes=()=>host.children[0].children;
 assert.equal(ui.get('usage-estimate').textContent,'17.15 ft³');
 assert.equal(host.dataset.endTime,through.captured_at);
 assert.match(ui.get('usage-bounds').textContent,/9–11.*Meter event 6/);
 assert.deepEqual(nodes().filter(n=>n.attributes.class==='plot-estimate-dot').map(n=>n.attributes['data-event']),[3,5]);
 assert(nodes().filter(n=>n.attributes.class==='plot-estimate').every(n=>!n.attributes.d.includes(' C')));
 assert.equal(nodes().filter(n=>n.attributes.class==='plot-band').length,0);
 ui.render({daily:range(5,8,12),daily_nominal:nominal,movement_history});
 assert.equal(host.dataset.endEvent,'5');assert.equal(ui.get('usage-estimate').textContent,'17.15 ft³');
 assert(nodes().some(n=>n.attributes.class==='plot-band'));
 host.onkeydown({key:'End',preventDefault(){}});
 assert.match(host.attributes['aria-valuetext'],/17.15.*8.00–12.00/);
 ui.render({daily:range(6,9,11)},{overview_daily_method:'nominal_meter_movement_v1'});
 assert(!ui.get('usage-estimate').textContent.includes('10.00'));
 assert.match(ui.get('usage-bounds').textContent,/9–11.*Meter event 6/);
 assert.equal(host.dataset.endEvent,undefined);
});

test('a 24-hour view shows each real hour across the fall clock change and omits only a missing rate',async()=>{
  const midnight=Date.parse('2026-11-01T00:00:00-07:00'),hour=3600000;
  const zone='America/Los_Angeles',end=midnight+6*hour+15000;
  const hours=Array.from({length:6},(_,i)=>({start:midnight+i*hour,end:midnight+(i+1)*hour,use:i+2}));
  for(const missing of [false,true]){
    const rows=missing?hours.filter((_,i)=>i!==2):hours;
    const ui=gasOverview(async()=>response({zone,end,midnight,minutes:60,hours:rows,groups:[],resets:[midnight]}));
    ui.get('total-key-label').parentElement={};
    ui.charts.setCalendar(zone,new Date(end).toISOString());
    ui.charts.period('24',null);
    await tick();
    const marks=ui.get('day-curve').children[0].children.filter(n=>n.attributes.class==='plot-usage-dot');
    const rates=marks.map(n=>n.attributes['data-rate']);
    assert.deepEqual(rates,missing?[2,3,5,6,7]:[2,3,4,5,6,7]);
    assert.deepEqual(marks.map(n=>n.attributes['data-hour-end']),rows.map(q=>q.end));
    for(const mark of marks)assert.equal(mark.attributes['data-hour-end']-mark.attributes['data-start'],hour);
  }
});

test('six-hour chart renders tracked partial rates, prefers complete rates and leaves unsupported hours open',async()=>{
  const midnight=Date.parse('2026-11-23T00:00Z'),hour=3600000,at=i=>midnight+i*hour,end=at(6)+1000;
  const hours=[{start:at(0),end:at(1),use:7,bounds:[6,8]}];
  const partialHours=[{start:at(0),end:at(1),use:1},{start:at(1),end:at(2),use:3,bounds:[2,5]},
    {start:at(2),end:at(3),use:2},{start:at(4),end:at(5),use:4}];
  const trackedLevels=[0,7,10,12,13,17].map((value,i)=>[at(i),value,'day']);
  const ui=gasOverview(async()=>response({zone:'UTC',end,midnight,minutes:60,hours,partialHours,trackedLevels,
    dailyHours:trackedLevels.map(([t,value])=>[t,value,null,null]),groups:[],resets:[midnight]}));
  ui.get('total-key-label').parentElement={};
  ui.charts.setCalendar('UTC',new Date(end).toISOString());
  ui.charts.period('6',null);
  await tick();
  const marks=ui.get('day-curve').children[0].children;
  const ofClass=name=>marks.filter(n=>n.attributes.class===name).map(n=>n.attributes);
  assert.deepEqual(ofClass('plot-usage-dot').map(n=>n['data-rate']),[7,3,2,4]);
  assert.deepEqual(ofClass('plot-whisker').map(n=>n['data-hour-end']),[at(1),at(2)]);
  assert(!marks.some(n=>n.attributes['data-day-series']!=null &&
    n.attributes['data-start']<=at(3)&&n.attributes['data-end']>=at(4)));
  assert.match(ui.get('day-history-status').textContent,/Includes partial rates/);
});

test('a closing daily reading supports earlier totals only through measured hours',async()=>{
  const midnight=Date.parse('2026-11-23T00:00Z'),hour=3600000,end=midnight+6*hour+1000;
  const hours=[2,3,5].map(i=>({start:midnight+i*hour,end:midnight+(i+1)*hour,use:2,bounds:[1,3]}));
  const dailyHours=[[midnight+4*hour,12,10,14],[midnight+6*hour,20,17,22]];
  const ui=gasOverview(async()=>response({zone:'UTC',end,midnight,minutes:60,hours,dailyHours,groups:[],resets:[midnight]}));
  ui.get('total-key-label').parentElement={};
  ui.charts.setCalendar('UTC',new Date(end).toISOString());
  ui.charts.period('6',null);
  await tick();
  const points=ui.get('day-curve').children[0].children.filter(n=>n.attributes.class==='plot-estimate-dot');
  const at=i=>points.find(p=>+p.attributes['data-time']===midnight+i*hour)?.attributes;
  assert.equal(at(2)['data-total'],8);
  assert.equal(at(2)['data-low'],4);
  assert.equal(at(2)['data-high'],12);
  assert.equal(at(1),undefined);
  assert.equal(at(5)['data-total'],18);
});

test('a recovered increase remains in later cumulative runs across an unsupported hour',async()=>{
  const midnight=Date.parse('2026-11-23T00:00Z'),hour=3600000,end=midnight+6*hour+1000;
  const at=i=>midnight+i*hour;
  const hours=[{start:at(0),end:at(1),use:12,bounds:[11,13]},
    {start:at(3),end:at(4),use:1,bounds:[0,2]}];
  const trackedLevels=[[at(1),9,'same-day'],[at(3),10,'same-day'],[at(4),11,'same-day']];
  const dailyHours=[[at(3),10,8,12],[at(4),11,9,13]];
  const ui=gasOverview(async()=>response({zone:'UTC',end,midnight,minutes:60,hours,dailyHours,trackedLevels,
    flowCeiling:.01,groups:[],resets:[midnight]}));
  ui.get('total-key-label').parentElement={};
  ui.charts.setCalendar('UTC',new Date(end).toISOString());
  ui.charts.period('6',null);
  await tick();
  const nodes=ui.get('day-curve').children[0].children.map(n=>n.attributes);
  const point=i=>nodes.find(n=>n.class==='plot-estimate-dot'&&n['data-time']===at(i));
  assert.equal(point(3)['data-total'],13);
  assert.equal(point(4)['data-total'],14);
  assert.equal(point(3)['data-low'],11);
  assert.equal(point(2),undefined);
  assert(!nodes.some(n=>n.class==='plot-usage-dot'&&n['data-hour-end']===at(3)));
});

test('optical changes drive the dot and its single measurement whisker',async()=>{
  const midnight=Date.parse('2026-11-25T00:00:00Z'), step=600000;
  const start=midnight+step,end=start+step;
  const registerProfile={points:[[midnight,100,94,107,1],[start,100,94,107,1],[end,100.531,94,107,1]],
    openings:{[midnight]:[100,94,107,1]},gaps:[],conflicts:[],modeled:[],fineBounds:[],reconciled:true,
    rateIntervals:[[start,end,{use:.00235,bands:[[0,.0934]]}]]};
  const ui=gasOverview(async()=>response({zone:'UTC',end,midnight,minutes:60,hours:[],groups:[],resets:[midnight],registerProfile}));
  ui.get('total-key-label').parentElement={};
  ui.charts.setCalendar('UTC',new Date(end).toISOString());
  ui.charts.period('1',null);
  await tick();
  const nodes=ui.get('day-curve').children[0].children.map(n=>n.attributes).filter(a=>a['data-hour-end']===end);
  const dots=nodes.filter(n=>n.class==='plot-usage-dot');
  assert.equal(dots.length,1);
  assert.equal(dots[0]['data-use'],.00235);
  assert.equal(dots[0]['data-rate'],.00235*6);
  assert.deepEqual(nodes.filter(n=>n.class==='plot-whisker').map(n=>[n['data-lower'],n['data-upper']]),
    [[0,.0934*6]]);
});

test('browsing a previous hour requests its missing optical rates before drawing fallback dots',async()=>{
  const midnight=Date.UTC(2026,10,25),step=600000,end=midnight+36*step,previous=end-6*step;
  const points=Array.from({length:37},(_,i)=>[midnight+i*step,100+i/2,99+i/2,110+i/2,1]);
  const profile={points,openings:{[midnight]:[100,99,110,1]},gaps:[],conflicts:[],modeled:[],
    fineBounds:[],reconciled:true,rateIntervals:[]};
  const data={midnight,zone:'UTC',hours:[],groups:[],dailyHours:[[midnight,0]],resets:[midnight]};
  const calls=[];
  let release;
  const ui=gasOverview(async url=>{
    if(url.includes('minutes=10')){
      calls.push(url);
      await new Promise(done=>{release=done});
      return response({...data,minutes:10,end:previous,rateIntervals:[
        [previous-step,previous,{use:.01,bands:[[0,.1]]}]]});
    }
    return response({...data,minutes:60,end,registerProfile:profile});
  });
  ui.get('total-key-label').parentElement={};
  ui.charts.setCalendar('UTC',new Date(end).toISOString());
  ui.charts.period('1',null);
  await tick();
  ui.get('gas-previous').onclick();
  const marks=()=>ui.get('day-curve').children[0].children.map(n=>n.attributes)
    .filter(n=>n['data-hour-end']===previous);
  assert.deepEqual(calls,['api/chart-hours?end='+previous+'&minutes=10']);
  assert.equal(marks().length,0);
  release();
  await tick();
  assert.equal(marks().find(n=>n.class==='plot-usage-dot')['data-rate'],.06);
  assert.equal(marks().filter(n=>n.class==='plot-whisker').length,1);
});

test('an outage at the hour keeps measured subintervals and midnight has separate closing and opening strokes',async()=>{
  const midnight=Date.UTC(2026,10,26),step=600000,at=i=>midnight+i*step,end=at(15);
  const points=Array.from({length:176},(_,i)=>[at(i-160),300+i,299+i,301+i,0]);
  const opening=i=>points.find(p=>p[0]===at(i)).slice(1);
  const proof={use:1,bands:[[.8,1.2]]};
  const gap=[at(6)-20000,at(6)+5000];
  const profile={points,openings:{[at(-144)]:opening(-144),[midnight]:opening(0)},gaps:[gap],unknownGaps:[gap],
    modeled:[],conflicts:[],fineBounds:[],reconciled:true,
    rateIntervals:[1,2,3,4,5,6,7,8,9,10,11,12].map(i=>[at(i-1),at(i),proof])};
  const ui=gasOverview(async()=>response({zone:'UTC',end,midnight,minutes:60,hours:[],groups:[],registerProfile:profile}));
  ui.get('total-key-label').parentElement={};
  ui.charts.setCalendar('UTC',new Date(end).toISOString());
  ui.charts.period('24',null);
  await tick();
  const nodes=ui.get('day-curve').children[0].children;
  const strokes=nodes.filter(n=>n.attributes['data-day-series']!=null).map(n=>n.attributes);
  assert(strokes.some(n=>n['data-end']===midnight && n['data-start']<midnight));
  assert(nodes.some(n=>n.attributes.class==='plot-reset' && n.attributes['data-midnight']===midnight));
  assert(!nodes.some(n=>n.attributes.class==='plot-estimate' && n.attributes.x1!=null));
  assert(!strokes.some(n=>n['data-start']<gap[1]&&gap[0]<n['data-end']));
  assert(strokes.some(n=>n['data-start']===at(0) && n['data-end']===at(5)));
  assert(strokes.some(n=>n['data-start']===at(7) && n['data-end']===at(12)));
  assert(!nodes.some(n=>n.attributes['data-hour-end']===at(6)||n.attributes['data-hour-end']===at(12)));
  assert(!nodes.some(n=>n.attributes.class==='plot-estimate-dot' && n.attributes['data-time']===at(5)));
});

test('Day follows the absolute reading while daily is held and extends a warm ten-minute window',async()=>{
  const midnight=Date.UTC(2026,10,26), hour=3600000, first=midnight+18*hour+31*60000;
  const next=first+7*60000;
  class Clock extends Date{constructor(...args){super(...(args.length?args:[next]));}static now(){return next;}}
  const points=Array.from({length:26},(_,i)=>[midnight+(i-6)*hour,100+i,99+i,101+i,0]).filter(p=>p[0]<first);
  points.push([first,125,124,126,0]);
  const registerProfile={points,openings:{[midnight]:[106,105,107,0]},gaps:[],modeled:[],conflicts:[],fineBounds:[],
    registerHead:[first,125,51,'a'.repeat(64),125],reconciled:true};
  const requests=[];
  const ui=gasOverview(async url=>{requests.push(url);return response({zone:'UTC',end:first,midnight,minutes:60,hours:[],groups:[],resets:[midnight],registerProfile});},Clock);
  ui.get('total-key-label').parentElement={};
  const daily={day:'2026-11-26',timezone:'UTC',method:'nominal_meter_movement_v1',value_ft3:'1',
    source_sha256:'c'.repeat(64),event_id:29,measured_at:new Date(midnight+16*hour).toISOString(),status:'held_at_last_reading'};
  function render(t,v,id,digest){ui.render({daily_nominal:daily,absolute_nominal:{method:'photo_anchored_fine_dial',
    measured_at:new Date(t).toISOString(),source_sha256:digest.repeat(64),event_id:id,value_ft3:String(v),lower_ft3:v-1,upper_ft3:v+1}},
    {overview_meter:'gas',overview_daily_method:'nominal_meter_movement_v1'});}
  render(first,125,51,'a');await tick();
  assert.equal(ui.get('day-curve').dataset.endTime,new Date(first).toISOString());
  const count=requests.length;
  render(next,126,52,'b');await tick();
  assert.equal(ui.get('day-curve').dataset.endTime,new Date(next).toISOString(),JSON.stringify([requests,ui.get('day-curve').dataset,ui.get('day-history-status').textContent]));
  assert.equal(requests.length,count);
  const nodes=ui.get('day-curve').children[0].children.map(n=>n.attributes);
  assert.equal(nodes.find(n=>n.class==='plot-estimate-dot' && n['data-time']===next)['data-total'],20);
  assert(nodes.some(n=>n.class==='plot-usage-dot' && n['data-hour-end']===next));
  assert.match(ui.get('day-history-status').textContent,/partial hour/);
});
