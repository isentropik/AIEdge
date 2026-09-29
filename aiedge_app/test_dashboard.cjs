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
 storage:{state:'ready',free_bytes:1024**3},mqtt:{state:'connected'}};
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
 assert.equal(app.get('camera-status').textContent,'Capture enabled');
 assert.equal(app.get('error').hidden,true);
 assert.equal(app.get('history-error').hidden,false);
 assert.equal(app.get('history-summary').textContent,'History unavailable');
 assert.equal(app.get('empty-gallery').hidden,true);
});
test('stalled history does not hold back status rendering',async()=>{
 let finish;
 const app=fixture(url=>url.includes('capture-history')?new Promise(resolve=>finish=resolve):Promise.resolve(response(state)));
 await tick();assert.equal(app.get('meter-value').textContent,'123');
 assert.equal(app.get('camera-status').textContent,'Capture enabled');
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
