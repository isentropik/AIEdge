const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const light={source:'strip',pin:12,type:'SK6812_RGBW',count:19,channels:[0,0,0,255],intensity:29};
const sensor={auto_exposure:false,dsp_exposure:false,exposure:600,compensation:0,auto_gain:false,gain:0,gain_limit:1,mirror:false,flip:false};
class Element{
 constructor(){this.value='';this.checked=false;this.hidden=false;this.disabled=false;this.textContent='';this.style={};this.attributes={};this.children=[];}
 setAttribute(k,v){this.attributes[k]=v;}replaceChildren(){this.children=[];}append(e){this.children.push(e);}
}
function fixture(imageRevision='a'.repeat(64)){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const window={updateSetupFlow(){}},context=vm.createContext({window,document:{getElementById:get,querySelectorAll:()=>[],createElement:()=>new Element()}}),calls=[];
 for(const name of ['camera-lighting.js','camera-image.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,name),'utf8'),context);
 const lighting=window.AIEdgeCameraControls,image=window.AIEdgeImageControls;
 const ls={lighting:light,revision:'a'.repeat(64),capabilities:{builtin_pin:4,pins:[]},needs_activation:false};
 const is={controls:sensor,revision:imageRevision,capabilities:{model:'OV2640',compensation_limit:2},needs_activation:false};
 lighting.receive({job:'light-load',action:'lighting-load',settings:ls});
 image.receive({job:'image-load',action:'image-load',image_settings:is});
 for(const controls of [lighting,image])controls.connect(async(action,details)=>{calls.push({action,details});return true;});
 return {lighting,image,get,calls,ls,is};
}
test('verified light then image updates keep drafts and share only the exact baseline',async()=>{
 const f=fixture();f.get('lighting-intensity').value='70';f.get('lighting-intensity').oninput();
 f.get('image-exposure').value='750';f.get('image-exposure').oninput();await f.lighting.apply();
 assert.equal(f.calls[0].details.revision,'a'.repeat(64));
 f.lighting.receive({job:'light-apply',action:'lighting-apply',settings:{...f.ls,revision:'b'.repeat(64),lighting:{...light,intensity:70},changed:true,active_verified:true}});
 assert.equal(f.image.status().dirty,true);await f.image.apply();
 assert.equal(f.calls[1].details.revision,'b'.repeat(64));assert.equal(f.calls[1].details.controls.exposure,750);
 f.image.receive({job:'image-apply',action:'image-apply',image_settings:{...f.is,revision:'c'.repeat(64),controls:{...sensor,exposure:750},changed:true,active_verified:true}});
 assert.equal(f.lighting.status().revision,'c'.repeat(64));assert.equal(f.lighting.requiresPicture(),true);
});
test('unverified peer updates never advance the other panel baseline',()=>{
 const f=fixture();f.lighting.receive({job:'uncertain',action:'lighting-apply',settings:{...f.ls,revision:'b'.repeat(64),active_verified:false}});
 assert.equal(f.image.status().revision,'a'.repeat(64));
 f.image.receive({job:'uncertain-image',action:'image-apply',image_settings:{...f.is,revision:'c'.repeat(64),active_verified:false}});
 assert.equal(f.lighting.status().revision,'b'.repeat(64));
});
test('independently changed image baseline cannot be rebased by lighting',()=>{
 const f=fixture('d'.repeat(64));f.lighting.receive({job:'verified',action:'lighting-apply',settings:{...f.ls,revision:'b'.repeat(64),active_verified:true}});
 assert.equal(f.image.status().revision,'d'.repeat(64));
 f.image.rebaseRevision('d'.repeat(64),'bad');assert.equal(f.image.status().revision,'d'.repeat(64));
});
test('repeated completed-lighting polls preserve a new brightness draft',()=>{
 const f=fixture();f.get('lighting-intensity').value='60';f.get('lighting-intensity').oninput();
 f.lighting.receive({job:'light-load',action:'lighting-load',settings:f.ls});
 assert.equal(f.get('lighting-intensity').value,60);assert.equal(f.lighting.status().dirty,true);
});
test('an applied brightness change stays stale when a later draft is reverted',()=>{
 const f=fixture();f.lighting.receive({job:'applied',action:'lighting-apply',settings:{...f.ls,lighting:{...light,intensity:70},changed:true,active_verified:true}});
 for(const value of [75,70]){f.get('lighting-intensity').value=String(value);f.get('lighting-intensity').oninput();}
 assert.equal(f.lighting.status().dirty,false);assert.equal(f.lighting.requiresPicture(),true);
 f.lighting.pictureTaken();assert.equal(f.lighting.requiresPicture(),false);
});
test('busy lighting fields cannot mutate their draft',()=>{
 const f=fixture();f.lighting.setBusy(true);f.get('lighting-intensity').value='90';f.get('lighting-intensity').oninput();
 assert.equal(f.lighting.status().dirty,false);assert.equal(f.lighting.requiresPicture(),false);
});
