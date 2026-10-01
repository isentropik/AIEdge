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
const response=value=>({ok:true,status:200,json:async()=>value});
const state={captures:1,unique_images:1,failures:0,capture_enabled:true,interval_seconds:30,missed_slots:0,
 latest:null,recognition:{state:'estimated',dial_positions:[]},reading:{state:'estimated',value:123},
 camera:{state:'ready'},storage:{state:'ready',free_bytes:1024**3},mqtt:{state:'connected'}};
const page={items:[],next_before:null};
function fixture(fetch,physical=false){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const document={getElementById:get,createElement:()=>new Element(),documentElement:{dataset:{}},hidden:true,readyState:'loading',addEventListener(){}};
 const window={addEventListener(){},dispatchEvent(){},renderPhysicalReading(reading){get('meter-value').textContent=reading.value===null?'—':String(reading.value);}};
 const context=vm.createContext({document,window,fetch,location:{hash:'#overview'},localStorage:{getItem(){return null;},setItem(){}},AbortSignal,setTimeout,clearTimeout,Date,console,CustomEvent:class{}});
 vm.runInContext(source,context);
 if(physical)vm.runInContext(fs.readFileSync(path.join(__dirname,'reading-format.js'),'utf8'),context);
 return {get,window};
}
test('failed history does not clear a successful current reading',async()=>{
 const app=fixture(async url=>{if(url.includes('capture-history'))throw new TypeError('network');return response(state);});
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
 await tick();assert.equal(app.get('meter-value').textContent,'123');
 assert.equal(app.get('camera-status').textContent,'Camera ready');
 finish(response(page));await tick();assert.equal(app.get('refresh').disabled,false);
});
test('status failure clears the current value while successful history remains available',async()=>{
 const app=fixture(async url=>{if(url==='api/status')throw new TypeError('offline');return response(page);});
 await tick();assert.equal(app.get('meter-value').textContent,'—');
 assert.equal(app.get('camera-status').textContent,'Connection lost');
 assert.equal(app.get('history-error').hidden,true);
 assert.equal(app.get('empty-gallery').textContent,'No stored captures yet.');
});
test('history recovery clears only its own error',async()=>{
 let fail=true;
 const app=fixture(async url=>{if(url.includes('capture-history')){if(fail)throw new Error('history');return response(page);}return response(state);});
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
