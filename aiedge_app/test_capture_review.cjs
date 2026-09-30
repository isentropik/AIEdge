const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'capture-review.js'),'utf8');
class Element {
 constructor(tag='div'){this.tag=tag;this.children=[];this.hidden=false;this.disabled=false;this.value='';this.textContent='';this.dataset={};this.attributes={};this.src='';}
 setAttribute(name,value){this.attributes[name]=value;}
 removeAttribute(name){delete this.attributes[name];}
 replaceChildren(...children){this.children=children;}
 append(...children){this.children.push(...children);}
 querySelectorAll(selector){return this.children.flatMap(child=>[...(child.tag===selector?[child]:[]),...child.querySelectorAll(selector)]);}
 reportValidity(){return true;}
 getContext(){return {clearRect(){},drawImage(){},strokeRect(){},fillRect(){},fillText(){}};}
}
const reply=(body,status=200)=>({ok:status<300,status,json:async()=>body});
const context={id:'c'.repeat(64),dials:[{name:'Dial 1'},{name:'Dial 2'}],calibration:{reference_sha256:'b'.repeat(64),dials:[{crop:[1,2,20,20]},{crop:[21,2,20,20]}]}};
const state={capture:{event_id:1,sha256:'a'.repeat(64),captured_at:'2026-01-01T00:00:00Z',matching_captures:2},context,review:null,other_context_reviews:0};
function fixture(custom){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const requests=[],events={};let saved=null;
 const window={addEventListener(name,callback){events[name]=callback;},AIEdgeReferenceImage:{load:async()=>({})}};
 const fetch=async(url,options={})=>{requests.push({url,options});if(custom){const result=await custom(url,options);if(result)return result;}
  if(url==='api/setup')return reply({token:'test-token'});
  if(options.method==='POST'){saved={...JSON.parse(options.body),revision:'d'.repeat(64)};return reply(saved);}
  return reply({...state,review:saved});};
 const sandbox=vm.createContext({document:{getElementById:get,createElement:tag=>new Element(tag)},window,fetch,location:{hash:'#captures/1'},AbortSignal,setTimeout,clearTimeout,Date,console});
 vm.runInContext(source,sandbox);return {get,window,requests,events,inputs:()=>get('review-dials').querySelectorAll('input')};
}
async function ready(app){await app.window.AIEdgeReview.open(1);app.get('review-image').onload();}
const submit=app=>app.get('review-form').onsubmit({preventDefault(){}});
test('model estimates never prefill labels; image load gates saving and unknown remains usable',async()=>{
 const app=fixture();try{
  await app.window.AIEdgeReview.open(1);assert.equal(app.get('review-save').disabled,true);
  assert.equal(app.inputs()[0].value,'');assert.equal(app.inputs()[1].value,'');
  app.get('review-image').onload();assert.equal(app.get('review-save').disabled,false);
  await submit(app);const post=app.requests.find(r=>r.options.method==='POST');
  assert.deepEqual(JSON.parse(post.options.body).positions,[null,null]);assert.equal(post.options.headers['X-AIEdge-Setup'],'test-token');
  assert.equal(app.get('review-status').textContent,'Review saved · 0 of 2 dials');
 }finally{app.window.AIEdgeReview.close();}
});
test('partial manual review keeps zero and unknown distinct and does not alter the image URL',async()=>{
 const app=fixture();try{await ready(app);app.inputs()[0].value='0';app.inputs()[0].oninput();await submit(app);
  assert.deepEqual(JSON.parse(app.requests.find(r=>r.options.method==='POST').options.body).positions,[0,null]);
  assert.equal(app.get('review-image').src,'image/'+'a'.repeat(64));assert.equal(app.get('review-repeat').hidden,false);
  assert.equal(app.get('review-save').disabled,true);
 }finally{app.window.AIEdgeReview.close();}
});
test('lost or conflicting save requires readback instead of an automatic retry',async()=>{
 const app=fixture((url,options)=>options.method==='POST'?reply({error:'Calibration changed.'},409):null);
 try{await ready(app);app.inputs()[0].value='5.1';app.inputs()[0].oninput();await submit(app);
  assert.equal(app.get('review-save').disabled,true);assert.equal(app.get('review-reload').hidden,false);
  assert.match(app.get('review-status').textContent,/Reload the review before retrying/);
  await submit(app);assert.equal(app.requests.filter(r=>r.options.method==='POST').length,1);
 }finally{app.window.AIEdgeReview.close();}
});
test('navigation retains an unsaved draft only for its unchanged image and revision',async()=>{
 const app=fixture();try{await ready(app);app.inputs()[1].value='7.3';app.inputs()[1].oninput();app.window.AIEdgeReview.close();
  await ready(app);assert.equal(app.inputs()[1].value,'7.3');assert.equal(app.get('review-status').textContent,'Unsaved review.');
 }finally{app.window.AIEdgeReview.close();}
});
test('leaving review before a slow response cannot replace another page',async()=>{
 let resolve;const waiting=new Promise(r=>resolve=r);const app=fixture(url=>url.startsWith('api/reviews/')?waiting:null);
 const work=app.window.AIEdgeReview.open(1);app.window.AIEdgeReview.close();resolve(reply(state));await work;
 assert.equal(app.get('capture-detail').hidden,true);assert.equal(app.inputs().length,0);
});
test('dial map is labeled as reference and original image can be restored',async()=>{
 const app=fixture();try{await ready(app);await app.get('review-map-view').onclick();
  assert.equal(app.get('review-caption').textContent,'Calibration reference · dial locations');
  assert.equal(app.get('review-map').hidden,false);assert.equal(app.get('review-image').hidden,true);
  app.get('review-capture-view').onclick();assert.equal(app.get('review-map').hidden,true);assert.equal(app.get('review-image').hidden,false);
  assert.equal(app.get('review-caption').textContent,'Original capture');
 }finally{app.window.AIEdgeReview.close();}
});
test('failed original image disables admission even after editing a value',async()=>{
 const app=fixture();try{await ready(app);app.get('review-image').onerror();app.inputs()[0].value='3';app.inputs()[0].oninput();
  assert.equal(app.get('review-save').disabled,true);assert.equal(app.get('review-reload').hidden,false);
  await submit(app);assert.equal(app.requests.filter(r=>r.options.method==='POST').length,0);
 }finally{app.window.AIEdgeReview.close();}
});
test('edits during a save remain visibly unsaved after the earlier payload commits',async()=>{
 let finish;const waiting=new Promise(resolve=>finish=resolve);const app=fixture((url,options)=>options.method==='POST'?waiting:null);
 try{await ready(app);app.inputs()[0].value='2';app.inputs()[0].oninput();const work=submit(app);
  app.inputs()[0].value='3';app.inputs()[0].oninput();finish(reply({positions:[2,null],revision:'d'.repeat(64)}));await work;
  assert.equal(app.inputs()[0].value,'3');assert.equal(app.get('review-save').disabled,false);assert.equal(app.get('review-status').textContent,'Unsaved review.');
 }finally{app.window.AIEdgeReview.close();}
});
