const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'setup.js'),'utf8');
class Element{
 constructor(){this.value='';this.hidden=false;this.disabled=false;this.textContent='';this.dataset={};this.style={};this.attributes={};this.children=[];}
 setAttribute(k,v){this.attributes[k]=v;}append(e){this.children.push(e);}replaceChildren(){this.children=[];}
 getBoundingClientRect(){return {width:640,height:480};}
 getContext(){return new Proxy({}, {get:()=>()=>{},set:()=>true});}
}
async function fixture(){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const posts=[],digest='a'.repeat(64),dial={name:'Dial 1',model:'main',direction:'cw',crop:[20,20,100,100],landmarks:{rim_points:[[70,20],[120,70],[70,120],[20,70]],needle_pivot:[70,70]}};
 const saved={token:'fixture',available:true,revision:'old',calibration:{reference_sha256:digest,markers:[{box:[0,0,16,16]},{box:[150,0,16,16]},{box:[0,150,16,16]}],dials:[dial,{...dial,name:'Dial 2'}]}};
 let rejectImage=false;
 const window={AIEdgeGeometry:require('./editor-geometry.js'),AIEdgeReferenceImage:{load:async()=>{if(rejectImage)throw Error('Image missing');return {};}},addEventListener(){},dispatchEvent(){}};
 const fetch=async(url,options={})=>{if(options.method==='POST')posts.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>options.method==='POST'?{revision:'new'}:saved};};
 vm.runInContext(source,vm.createContext({document:{getElementById:get,querySelectorAll:()=>[],createElement:()=>new Element()},window,fetch,AbortSignal,Event}));
 await window.openCalibration();return {get,window,posts,digest,rejectImage(){rejectImage=true;}};
}
test('selecting another dial survives duplicate route rendering',async()=>{
 const app=await fixture();app.window.AIEdgeCalibration.setMode('dials');app.get('selected-item').value='1';app.get('selected-item').onchange();
 app.window.AIEdgeCalibration.setMode('dials');assert.equal(app.get('selected-item').value,'1');assert.equal(app.get('dial-name').value,'Dial 2');
});
test('reusing the same reference keeps geometry and avoids a redundant save',async()=>{
 const app=await fixture();await app.window.AIEdgeCalibration.useReference(app.digest);
 const state=app.window.AIEdgeCalibration.status();assert.equal(state.dial_count,2);assert.equal(state.markers_complete,true);assert.equal(state.dirty,false);
 assert.equal(await app.window.AIEdgeCalibration.save(),true);assert.equal(app.posts.length,0);
});
test('a different reference clears old geometry and cannot be saved without new markers',async()=>{
 const app=await fixture();await app.window.AIEdgeCalibration.useReference('b'.repeat(64));
 const state=app.window.AIEdgeCalibration.status();assert.equal(state.reference,'b'.repeat(64));assert.equal(state.dial_count,0);assert.equal(state.markers_complete,false);
 assert.equal(await app.window.AIEdgeCalibration.save(),false);assert.equal(app.posts.length,0);assert.equal(app.get('setup-status').textContent,'Place all three markers.');
});
test('failed replacement image keeps the existing reference and geometry',async()=>{
 const app=await fixture();app.rejectImage();await assert.rejects(()=>app.window.AIEdgeCalibration.useReference('b'.repeat(64)),/Image missing/);
 const state=app.window.AIEdgeCalibration.status();assert.equal(state.reference,app.digest);assert.equal(state.dial_count,2);assert.equal(state.markers_complete,true);assert.equal(state.busy,false);
});
