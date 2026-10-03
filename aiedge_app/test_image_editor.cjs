const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const core=require('./image-editor.js'),source=fs.readFileSync(path.join(__dirname,'image-editor.js'),'utf8');
test('known clockwise quarter turn maps source corners and center correctly',()=>{
 const m=core.map({...core.identity(),turns:1,crop:null});
 assert.deepEqual(m.extent,[480,640]);assert.deepEqual(core.point(m.oriented,[0,0]),[480,0]);
 assert.deepEqual(core.point(m.oriented,[640,480]),[0,640]);assert.deepEqual(core.point(m.m,[320,240]),[320,240]);
});
test('arbitrary straightening and crops map pointer coordinates back to the source',()=>{
 for(const turns of [0,1,2,3])for(const angle of [-15,-.3,0,.3,15]){
  const full=core.map({...core.identity(),turns,angle,crop:null}),m=core.map({...full.edit,crop:[30,40,full.extent[0]-60,full.extent[1]-80]});
  for(const p of [[0,0],[640,480],[245.3,171.8]]){
   const restored=core.point(m.inverse,core.point(m.m,p));assert.ok(restored.every((v,i)=>Math.abs(v-p[i])<1e-8));
  }
 }
});
test('quarter turning an existing crop preserves the same source area',()=>{
 const initial={...core.identity(),crop:[100,120,240,200]};
 let value=initial;for(let i=0;i<4;i++)value=core.rotate(value,value.turns+1,value.angle);
 assert.deepEqual(value,initial);
});
test('corner grab offset does not jump the crop, move its anchor or resize on press',()=>{
 const box=[100,100,300,200],drag={box,corner:0,start:[104,107],move:false};
 assert.deepEqual(core.cropDrag(drag,drag.start,[640,480]),box);
 assert.deepEqual(core.cropDrag(drag,[124,127],[640,480]),[120,120,280,180]);
});
test('all four crop handles preserve their opposite corners and minimum size',()=>{
 const box=[100,100,300,200];
 for(let corner=0;corner<4;corner++){
  const drag={box,corner,start:core.corners(box)[corner],move:false};
  const result=core.cropDrag(drag,[320,220],[640,480]);
  assert.deepEqual(core.corners(result)[(corner+2)%4],core.corners(box)[(corner+2)%4]);
  assert.ok(result[2]>=16&&result[3]>=16);
 }
});
test('crop motion uses frozen image mapping and stays inside oriented bounds',()=>{
 const box=[20,30,200,150],drag={box,move:true,corner:-1,start:[60,60]};
 assert.deepEqual(core.cropDrag(drag,[-900,-900],[480,640]),[0,0,200,150]);
 assert.deepEqual(core.cropDrag(drag,[900,900],[480,640]),[280,490,200,150]);
 assert.deepEqual(core.cropDrag(drag,[80,80],[480,640]),[40,50,200,150]);
});
test('invalid transforms and crops do not become active',()=>{
 for(const value of [{...core.identity(),angle:NaN},{...core.identity(),turns:4},{...core.identity(),crop:[0,0,641,480]},{...core.identity(),crop:[0,0,5,5]}])assert.throws(()=>core.map(value));
});
test('cropped-away source points cannot receive new landmarks',()=>{
 const value={...core.identity(),crop:[100,100,300,200]};
 assert.equal(core.visible(value,[90,120]),false);assert.equal(core.visible(value,[200,200]),true);
});
test('resize cursor follows the displayed corner after rotation',()=>{
 const box=[100,100,140,140],plain=core.map(core.identity()),turned=core.map({...core.identity(),turns:1,crop:null});
 assert.equal(core.resizeCursor(plain.m,box,0),'nwse-resize');
 assert.equal(core.resizeCursor(turned.m,box,0),'nesw-resize');
});
function fixture({saved=null,reply=null,pending=false}={}){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,{hidden:false,disabled:false,value:'',textContent:'',title:'',attributes:{},style:{},setAttribute(k,v){this.attributes[k]=v;},getAttribute(k){return this.attributes[k]??null;},setPointerCapture(){},hasPointerCapture(){return false;}});return elements.get(id);};
 const posts=[],notes=[],ref='a'.repeat(64),window={AIEdgeCalibration:{status:()=>({has_image:true}),token:()=>'local-test',draw(){},note:(...args)=>notes.push(args)},AIEdgeImageControls:{status:()=>({orientation_pending:pending})},updateSetupFlow(){}};
 const fetch=async(url,options)=>{
  const body=JSON.parse(options.body);posts.push({url,body});
  return {ok:!reply?.error,json:async()=>reply??{revision:'next-revision',image_edit:{version:1,reference_sha256:body.reference_sha256,edit:body.edit}}};
 };
 vm.runInContext(source,vm.createContext({window,document:{getElementById:get},fetch,AbortSignal,console}));
 window.AIEdgeImageEditor.bind(ref,saved);
 return {get,posts,notes,ref,window,editor:window.AIEdgeImageEditor};
}
test('unchanged framing advances without save, capture or calibration write',async()=>{
 const app=fixture();assert.equal(await app.editor.save(),true);assert.deepEqual(app.posts,[]);
});
test('rotation is immediate and Next saves once to app framing only',async()=>{
 const app=fixture();app.get('image-rotate-right').onclick();
 assert.equal(app.editor.status().edit.turns,1);assert.equal(app.editor.status().dirty,true);
 assert.equal(await app.editor.save(),true);assert.equal(app.posts.length,1);
 assert.equal(app.posts[0].url,'api/setup/image-edit');assert.equal(await app.editor.save(),true);assert.equal(app.posts.length,1);
});
test('saved reference framing restores without requiring a new picture',()=>{
 const ref='a'.repeat(64),edit=core.rotate(core.identity(),3,0),app=fixture({saved:{revision:'existing',image_edit:{reference_sha256:ref,edit}}});
 assert.equal(app.editor.status().edit.turns,3);assert.equal(app.editor.status().dirty,false);
});
test('new reference starts clear but retains the latest global save revision',async()=>{
 const app=fixture();app.get('image-rotate-right').onclick();await app.editor.save();
 app.editor.bind('b'.repeat(64),{revision:null});assert.equal(app.editor.status().edit.turns,0);
 app.get('image-rotate-left').onclick();await app.editor.save();assert.equal(app.posts[1].body.revision,'next-revision');
});
test('crop mode uses the full frame while editing and stops when leaving Image',()=>{
 const ref='a'.repeat(64),app=fixture({saved:{revision:'existing',image_edit:{reference_sha256:ref,edit:{...core.identity(),crop:[100,100,300,200]}}}});
 app.get('image-crop').onclick();assert.deepEqual(JSON.parse(JSON.stringify(app.editor.display().edit.crop)),[0,0,640,480]);
 app.editor.setMode('markers');assert.deepEqual(JSON.parse(JSON.stringify(app.editor.display().edit.crop)),[100,100,300,200]);
 assert.equal(app.get('image-crop').hidden,true);
});
test('touch corner grab has a larger target and correct resize cursor',()=>{
 const ref='a'.repeat(64),app=fixture({saved:{image_edit:{reference_sha256:ref,edit:{...core.identity(),crop:[100,100,300,200]}}}});
 app.get('image-crop').onclick();app.editor.pointerMove({pointerType:'touch'},[119,120,1]);
 assert.equal(app.get('calibration-canvas').style.cursor,'move'); // Inside the crop, outside the handle radius.
 app.editor.pointerMove({pointerType:'touch'},[116,116,1]);assert.equal(app.get('calibration-canvas').style.cursor,'nwse-resize');
});
test('pending physical orientation disables framing until a verified picture',()=>{
 const app=fixture({pending:true});assert.equal(app.get('image-crop').disabled,true);
 app.get('image-rotate-right').onclick();assert.equal(app.editor.status().edit.turns,0);
});
test('crop rejection keeps unsaved changes and shows one actionable error',async()=>{
 const app=fixture({reply:{error:'image_crop_hides_marker'}});app.get('image-rotate-right').onclick();
 assert.equal(await app.editor.save(),false);assert.equal(app.editor.status().dirty,true);
 assert.equal(app.notes.length,1);assert.match(app.notes[0][0],/alignment marker/);
});
test('mismatched save receipt cannot advance or clear the draft',async()=>{
 const app=fixture({reply:{revision:'changed',image_edit:{reference_sha256:'a'.repeat(64),edit:core.identity()}}});
 app.get('image-rotate-right').onclick();assert.equal(await app.editor.save(),false);
 assert.equal(app.editor.status().dirty,true);assert.equal(app.notes.length,1);assert.match(app.notes[0][0],/could not be verified/);
});
