const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'setup-flow.js'),'utf8');
class Element{
 constructor(){this.hidden=false;this.disabled=false;this.textContent='';this.dataset={};this.attributes={};this.style={};this.children=[];this.firstChild={textContent:''};this.classList={toggle(){}};}
 setAttribute(k,v){this.attributes[k]=v;}getAttribute(k){return this.attributes[k]??null;}removeAttribute(k){delete this.attributes[k];}
 append(e){e.parentElement=this;this.children.push(e);}replaceChildren(){this.children=[];}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({hash='#setup/image',hasImage=true,markers=true,save=true,configured=false,openCalibration=async()=>{},saveCalibration=null}={}){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const buttons=['lighting','image','alignment','dials','format','data','finish'].map(step=>{const e=new Element();e.dataset.step=step;return e;});
 const editor={has_image:hasImage,markers_complete:markers,dial_count:6,busy:false},calls=[],posts=[];
 const location={hash};
 const window={showAppPage(name){calls.push('page:'+name);},openCalibration,openReadingFormat:async()=>{},
  AIEdgeCalibration:{status:()=>editor,setMode(mode){calls.push(mode);},save:async()=>{calls.push('save');return saveCalibration?await saveCalibration():save;},draw(){},setGrid(){}},
  AIEdgeFormat:{save:async()=>{calls.push('format-save');return save;}},addEventListener(){}};
 const fetch=async(url,options={})=>{if(options.method==='POST')posts.push({url,body:options.body});return {ok:true,json:async()=>url==='api/camera-setup'?{configured,state:'idle',capture_enabled:false,interval_seconds:30}:url==='api/setup'?{token:'fixture-only'}:{format:null}};};
 vm.runInContext(source,vm.createContext({document:{getElementById:get,querySelectorAll:()=>buttons,createElement:()=>new Element()},window,location,fetch,AbortSignal,URL,Date,setTimeout:fn=>setImmediate(fn)}));
 return {get,buttons,window,location,posts,calls,editor};
}
test('opening setup reads app metadata but never automatically requests a photo',async()=>{
 const app=fixture();await tick();assert.deepEqual(app.posts,[]);assert.equal(app.get('take-reference').disabled,true);
 assert.equal(app.get('step-count').textContent,'Step 2 of 7');
});
test('existing calibration bookmarks open the working image step',async()=>{
 const app=fixture({hash:'#calibration'});await tick();
 assert.equal(app.calls.includes('page:setup'),true);assert.equal(app.calls.includes('image'),true);
 assert.equal(app.get('setup-heading').textContent,'Image');
});
test('step tabs stay disabled while the saved reference is loading',async()=>{
 const app=fixture();app.editor.busy=true;app.window.updateSetupFlow();
 assert.equal(app.buttons.every(b=>b.disabled),true);await app.buttons[2].onclick();
 assert.equal(app.location.hash,'#setup/image');assert.equal(app.calls.includes('save'),false);
});
test('unchanged reference advances and returns without requiring another picture',async()=>{
 const app=fixture();await tick();await app.get('setup-next').onclick();await tick();
 assert.equal(app.location.hash,'setup/alignment');assert.equal(app.get('step-count').textContent,'Step 3 of 7');
 await app.get('setup-back').onclick();assert.equal(app.location.hash,'setup/image');assert.equal(app.posts.length,0);
});
test('missing image blocks both Next and a future step with one specific error',async()=>{
 const app=fixture({hasImage:false});await tick();await app.get('setup-next').onclick();
 assert.match(app.get('setup-status').textContent,/Take a picture/);assert.equal(app.location.hash,'#setup/image');
 await app.buttons[2].onclick();assert.match(app.get('setup-status').textContent,/Take a picture/);
 assert.equal(app.get('setup-status').hidden,false);assert.equal(app.calls.includes('save'),false);
});
test('alignment requires all three markers before advancing',async()=>{
 const app=fixture({hash:'#setup/alignment',markers:false});await tick();await app.get('setup-next').onclick();
 assert.equal(app.get('setup-status').textContent,'Place all three markers on fixed markings.');
 assert.equal(app.location.hash,'#setup/alignment');assert.equal(app.calls.includes('save'),false);
});
test('failed calibration save stays on dials instead of opening format',async()=>{
 const app=fixture({hash:'#setup/dials',save:false});await tick();await app.get('setup-next').onclick();
 assert.equal(app.calls.filter(c=>c==='save').length,1);assert.equal(app.location.hash,'#setup/dials');
 assert.equal(app.get('setup-next').disabled,false);
});
test('successful dial save opens format and updates the current step',async()=>{
 const app=fixture({hash:'#setup/dials'});await tick();await app.get('setup-next').onclick();
 assert.equal(app.calls.filter(c=>c==='save').length,1);assert.equal(app.location.hash,'setup/format');
 assert.equal(app.get('step-count').textContent,'Step 5 of 7');
});
test('data fields become unknown after status loss rather than retaining success',async()=>{
 const app=fixture();await tick();app.window.AIEdgeFlow.renderStatus({storage:{state:'ready',free_bytes:1024**3},mqtt:{state:'connected'}});
 assert.equal(app.get('settings-storage').textContent,'Available');app.window.AIEdgeFlow.statusUnavailable();
 assert.equal(app.get('settings-storage').textContent,'Unknown');assert.equal(app.get('settings-free-space').textContent,'—');
 assert.equal(app.get('settings-mqtt').textContent,'Unknown');
});
test('leaving during calibration load cannot restore the old editor or step',async()=>{
 let resolve;const loading=new Promise(r=>resolve=r),app=fixture({openCalibration:()=>loading});
 app.window.AIEdgeFlow.route('#settings');resolve();await tick();
 assert.equal(app.calls.at(-1),'page:settings');assert.equal(app.calls.includes('image'),false);
});
test('leaving during save cannot navigate back to the wizard after the save resolves',async()=>{
 let resolve;const saving=new Promise(r=>resolve=r),app=fixture({hash:'#setup/dials',saveCalibration:()=>saving});
 await tick();const next=app.get('setup-next').onclick();app.location.hash='#settings';app.window.AIEdgeFlow.route('#settings');
 resolve(true);await next;assert.equal(app.location.hash,'#settings');assert.equal(app.calls.at(-1),'page:settings');
});
