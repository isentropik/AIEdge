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
 finish(response(page));await tick();assert.equal(app.get('refresh').disabled,false);
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
 const document = {getElementById:get, createElement:()=>new Element(),createElementNS:()=>new Element()};
 const window = {addEventListener(){}};
 const context={document,window,location:{hash:''},Intl,Date:date};
 if(trend){
  for(const id of ['day-curve','hour-curve']){
   get(id).clientWidth=500;
   get(id).addEventListener=(name,fn)=>{get(id)['on'+name]=fn;};
  }
  Object.assign(context,{ResizeObserver:class {observe(){}},fetch:trend,AbortSignal});
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'gas-charts.js'),'utf8'),context);
 }
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'integration.js'),'utf8'),context);
 return {get,render:usage=>window.AIEdgeIntegration.render({mqtt:{usage}})};
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
 key('Home');assert.match(label(),/0?1\.00–3\.00 ft³ used/);
 key('ArrowRight');assert.match(label(),/1:00 AM PDT.*1:00 AM PST.*2\.00–7\.00 ft³ used/);
 const paths=chart.children[0].children;
 const ribbon=paths.filter(n=>n.attributes.class==='plot-band');assert.equal(ribbon.length,1);
 assert.equal(paths.filter(n=>n.attributes.class==='plot-estimate').length,3);
 // From 2.01 to 4.1 h the possible total spans the earlier 6 and later 14.
 // Both ends of that unmeasured interval must include its entire envelope.
 const verts=[...ribbon[0].attributes.d.matchAll(/[ML]([\d.]+) ([\d.]+)/g)].map(m=>m.slice(1).map(Number));
 const y=v=>293-281*v/20,x=h=>36+(500-48)*h/4.5;
 for(const t of [2.01,4.1])for(const v of [6,14]){
   assert(verts.some(([px,py])=>Math.abs(px-x(t))<.02&&Math.abs(py-y(v))<.02));
 }
 key('ArrowRight');key('ArrowRight');assert.match(label(),/Hourly range unavailable/);
 assert.match(chart.attributes['aria-valuetext'],/No meter reading/);
 key('End');assert.match(label(),/1\.00–10\.00 ft³ used/);assert.equal(chart.dataset.endEvent,'9');
 assert.match(chart.attributes['aria-valuetext'],/15\.50 ft³ estimated/);
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
 const lengths=()=>paths('plot-estimate').map(p=>p.attributes.d.split(' L').length);
 const assertEnd=id=>{
  assert.equal(chart.dataset.endEvent,String(id));assert.equal(chart.dataset.endTime,source(id).captured_at);
  assert.equal(ui.get('usage-estimate').dataset.eventId,String(id));
 };
 ui.render({daily:range(8),daily_nominal:nominal(7,4)});assertEnd(8);assert.deepEqual(lengths(),[1]);
 answer();await tick();assertEnd(8);assert.deepEqual(lengths(),[1,2,1]);
 ui.render({daily:range(8),daily_nominal:nominal(9,5)});assertEnd(9);
 assert.match(chart.attributes['aria-valuetext'],/5.00 ft³ estimated/);assert.equal(reads,1);
 // The independent nominal is a separate point until its own daily range is linked.
 assert.equal(paths('plot-band').length,2);
 const partial={...nominal(10,7),method:'observed_increments',status:'partial_coverage',lower_ft3:null,upper_ft3:null};
 ui.render({daily:range(8),daily_nominal:partial});assertEnd(10);assert.deepEqual(lengths(),[1,2,1]);
 assert.match(chart.attributes['aria-valuetext'],/7.00 ft³ estimated.*Partial coverage$/);
 assert.equal(paths('plot-band').length,1);
 // Earlier bounded readings share a ribbon; the isolated partial estimate remains outside it.
 const ribbonX=paths('plot-band')[0].attributes.d.match(/(?:M|L)([\d.]+)/g).map(v=>Number(v.slice(1)));
 const partialX=Number(paths('plot-estimate').at(-1).attributes.d.slice(1).split(' ')[0]);
 assert(Math.max(...ribbonX)<partialX);
 data=history(8);now+=125000;
 ui.render({daily:{...range(8),status:'stale',checked_through:source(15)},daily_nominal:nominal(6,4)});
 answer();await tick();assertEnd(8);assert.deepEqual(lengths(),[1,2]);
 assert.match(chart.attributes['aria-valuetext'],/Stale$/);
 // Same millisecond and event number are insufficient to join a different source.
 data={...data,last_captured_at:data.last_captured_at.replace('.000Z','.000001Z')};now+=125000;
 ui.render({daily:range(8)});answer();await tick();assert.deepEqual(lengths(),[1,1,1]);
 data={...history(8),last_digest:source(4).source_sha256};now+=125000;
 ui.render({daily:range(8)});answer();await tick();assert.deepEqual(lengths(),[1,1,1]);
 data=history(12);now+=125000;
 ui.render({daily:range(8)});answer();await tick();assertEnd(8);assert.deepEqual(lengths(),[1,1,1]);
 ui.render({daily_nominal:{...partial,value_ft3:0}});assertEnd(10);assert.deepEqual(lengths(),[1]);
 assert.match(chart.attributes['aria-valuetext'],/0.00 ft³ estimated.*Partial coverage/);
 ui.render({daily_nominal:{day,timezone,status:'opening_balance',value_ft3:'0.00'}});
 assert.equal(chart.dataset.endEvent,undefined);assert.equal(chart.hidden,true);
 assert.match(ui.get('usage-time').textContent,/Awaiting the first measurement/);
 ui.render({});assert.equal(chart.dataset.endTime,undefined);
});

test('contradictory daily bounds leave a break in both the line and its ribbon',async()=>{
 const day='2026-11-20',timezone='UTC',midnight=Date.parse(day+'T00:00:00Z');
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
 host.onkeydown({key:'End',preventDefault(){}});assert.match(host.attributes['aria-valuetext'],/5.00 ft³ estimated/);
 host.onpointerleave({pointerType:'mouse'});assert(tip.hidden);
 host.onfocus();host.onpointercancel();assert(tip.hidden);
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

test('historical segment precision is a display choice with the original measurement available',()=>{
 const ui = gasOverview();
 const historical = {value:0.123456789,event_id:8,captured_at:'2025-03-03T12:00:00Z',source_sha256:'2'.repeat(64),segment_started_at:'2025-03-03T09:00:00Z'};
 ui.render({historical});
 assert.equal(ui.get('segment-value').textContent,'0.12 ft³');
 assert.equal(ui.get('segment-value').dataset.fullValue,'0.123456789');
 ui.render({});
 assert.equal(ui.get('segment-value').dataset.eventId,undefined);
});

test('clock buckets display a real zero, preserve missing amounts and reject a mismatched endpoint',async()=>{
 const points=Array.from({length:5},(_,i)=>({event_id:i+10,source_sha256:'c'.repeat(64),captured_at:new Date(Date.UTC(2026,10,1,8,i*15)).toISOString()}));
 const recent={hour:{start:points[0],through:points[4]},through:points[4],timezone:'America/Los_Angeles',label:'1.00–2.00 ft³',
  quarters:points.slice(1).map((p,i)=>({start:points[i],through:p,lower:'0.00',upper:'1.00'}))};
 const bins=recent.quarters.map((q,i)=>({start:q.start.captured_at,end:q.through.captured_at,lower:i===2?null:'0.00',upper:i===2?null:'0.00'}));
 let result={status:'ready',timezone:recent.timezone,through:recent.through,history_available:true,periods:{'1':{start:bins[0].start,end:bins[3].end,minutes:15,bins,lower:'1.00',upper:'2.00'}}};
 const ui=gasOverview(async()=>response(result));ui.get('usage-period').value='1';
 ui.render({recent});await tick();
 assert.equal(ui.get('quarter-plot').hidden,false);
 assert.equal(ui.get('usage-hour').textContent,'1.50 ft³');
 assert.equal(ui.get('recent-bounds').textContent,'Bounds · 1.00–2.00 ft³');
 assert.equal(ui.get('recent-metric-label').textContent,'Nominal use');
 const chart=ui.get('hour-curve'),fig=chart.children[0].children;
 assert.equal(fig.filter(n=>n.attributes.class==='plot-estimate').length,2);
 assert.equal(fig.filter(n=>n.attributes.class==='plot-band').length,2);
 assert.equal(fig.filter(n=>n.attributes.class==='plot-upper').length,0);
 const key=k=>chart.onkeydown({key:k,preventDefault(){}});
 key('Home');assert.match(chart.attributes['aria-valuetext'],/0\.00 ft³ nominal · Bounds 0\.00–0\.00 ft³/);
 key('ArrowRight');key('ArrowRight');assert.match(chart.attributes['aria-valuetext'],/Range unavailable/);
 assert.equal(ui.get('hour-tip').hidden,false);
 key('Escape');assert.equal(ui.get('hour-tip').hidden,true);
 assert.equal(fig.filter(n=>n.attributes.class==='time-tick').length>1,true);
 result.periods['1'].lower='58.18';result.periods['1'].upper='66.31';
 ui.get('usage-period').value='1';ui.render({recent});
 assert.equal(ui.get('usage-hour').textContent,'62.25 ft³');
 result.periods['1'].upper=null;ui.render({recent});
 assert.equal(ui.get('usage-hour').textContent,'At least 58.18 ft³ · partial coverage');
 assert.equal(ui.get('recent-bounds').hidden,true);
 ui.render({recent:{...recent,quarters:recent.quarters.slice(1)}});assert.equal(ui.get('quarter-plot').hidden,true);
 result={...result,through:{...recent.through,source_sha256:'e'.repeat(64)}};
 ui.render({recent});await tick();assert.equal(ui.get('quarter-plot').hidden,true);
});
