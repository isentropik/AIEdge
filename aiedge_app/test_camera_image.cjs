const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const logic=require('./camera-image.js'),source=fs.readFileSync(path.join(__dirname,'camera-image.js'),'utf8');
const controls={auto_exposure:false,dsp_exposure:false,exposure:600,compensation:0,auto_gain:false,gain:0,gain_limit:1,mirror:false,flip:false};
class Element{
 constructor(){this.value='';this.checked=false;this.hidden=false;this.disabled=false;this.textContent='';this.style={};this.attributes={};}
 setAttribute(name,value){this.attributes[name]=value;}getAttribute(name){return this.attributes[name];}
}
function fixture(){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},calls=[],automatic=[];
 const window={updateSetupFlow(){},AIEdgeCameraControls:{setAutomatic(value){automatic.push(value);}}};
 vm.runInContext(source,vm.createContext({window,document:{getElementById:get,querySelectorAll:()=>[]}}));
 const image=window.AIEdgeImageControls;
 image.connect(async(action,details)=>{calls.push({action,details});return true;});image.configure(true);image.setStep('image');
 const result={action:'image-load',job:'initial',image_settings:{revision:'a'.repeat(64),controls:{...controls},capabilities:{model:'OV2640',compensation_limit:2},needs_activation:false,requires_reference:false}};
 image.receive(result);return {image,get,calls,result,automatic};
}
test('sensor ranges reject invalid types, unknown sensors and unknown fields',()=>{
 assert.equal(logic.validate(controls,'OV2640'),true);
 for(const patch of [{exposure:1201},{gain:31},{gain:true},{gain_limit:7},{compensation:3},{flip:1},{extra:3}])assert.equal(logic.validate({...controls,...patch},'OV2640'),false);
 assert.equal(logic.validate({...controls,compensation:5},'OV5640'),true);assert.equal(logic.validate(controls,'unknown'),false);
});
test('automatic exposure and gain collapse manual settings while retaining camera type',()=>{
 const {image,get,calls,automatic}=fixture();get('image-auto').checked=true;get('image-auto').onchange();
 assert.equal(get('image-manual-controls').hidden,true);assert.equal(get('image-sensor').textContent,'OV2640');
 assert.equal(image.status().automatic,true);assert.equal(automatic.at(-1),true);assert.deepEqual(calls,[]);
 get('image-auto').checked=false;get('image-auto').onchange();assert.equal(get('image-manual-controls').hidden,false);
});
test('manual and automatic modes show only applicable exposure and gain inputs',()=>{
 const {get}=fixture();assert.equal(get('image-exposure-row').hidden,false);assert.equal(get('image-compensation-row').hidden,true);
 get('image-auto-exposure').checked=true;get('image-auto-exposure').onchange();
 assert.equal(get('image-exposure-row').hidden,true);assert.equal(get('image-compensation-row').hidden,false);
 assert.equal(get('image-gain-row').hidden,false);get('image-auto-gain').checked=true;get('image-auto-gain').onchange();
 assert.equal(get('image-gain-row').hidden,true);assert.equal(get('image-gain-limit-row').hidden,false);
});
test('slider edits and reversions do not write or force an unnecessary new photo',()=>{
 const {image,get,calls}=fixture();get('image-exposure').value='750';get('image-exposure').oninput();
 assert.equal(image.requiresPicture(),true);assert.deepEqual(calls,[]);get('image-exposure').value='600';get('image-exposure').oninput();
 assert.equal(image.requiresPicture(),false);
});
test('unchanged settings cause no save or activation on picture',async()=>{
 const {image,calls}=fixture();assert.equal(await image.apply(),true);assert.deepEqual(calls,[]);
});
test('flips preview immediately relative to a verified photo and clear only after another photo',()=>{
 const {image,get,result}=fixture();image.pictureTaken(0);get('image-mirror').onclick();
 assert.equal(get('calibration-canvas').style.transform,'scale(-1,1)');assert.equal(image.requiresPicture(),true);
 image.receive({...result,job:'apply',action:'image-apply',image_settings:{...result.image_settings,changed:true,controls:{...controls,mirror:true}}});
 assert.equal(get('calibration-canvas').style.transform,'scale(-1,1)');assert.equal(image.requiresPicture(),true);
 image.pictureTaken(1);assert.equal(get('calibration-canvas').style.transform,'scale(1,1)');assert.equal(image.requiresPicture(),false);
 image.setStep('alignment');assert.equal(get('image-mirror').hidden,true);assert.equal(get('calibration-canvas').style.transform,'');
});
test('polling the same completed job preserves unsaved controls',()=>{
 const {image,get,result}=fixture();get('image-gain').value='4';get('image-gain').oninput();image.receive(result);
 assert.equal(get('image-gain').value,'4');assert.equal(image.status().dirty,true);
});
test('invalid choices are rejected locally without a request',async()=>{
 const {image,get,calls}=fixture();get('image-exposure').value='1201';get('image-exposure').oninput();
 await assert.rejects(image.apply(),/exposure and gain/);assert.deepEqual(calls,[]);
});
test('uncertain activation requires explicit action and cannot be cleared by loading',async()=>{
 const {image,get,calls,result}=fixture();image.markAttention();assert.equal(get('apply-saved-image-controls').hidden,false);
 await image.apply();assert.equal(calls[0].action,'image-apply');
 image.receive({...result,job:'reload',image_settings:{...result.image_settings,needs_activation:true}});assert.equal(image.requiresPicture(),true);
});
test('busy controls cannot change the draft and unsupported firmware is clearly unavailable',()=>{
 const {image,get,calls}=fixture();image.setBusy(true);get('image-mirror').onclick();
 assert.equal(image.status().dirty,false);assert.equal(get('load-image-controls').disabled,true);assert.deepEqual(calls,[]);
});
test('reloaded pending orientation requires a verified photo and cannot use a legacy orientation guess',()=>{
 const {image,get,result}=fixture();image.receive({...result,job:'pending',image_settings:{...result.image_settings,requires_reference:true}});
 assert.equal(image.requiresPicture(),true);image.pictureTaken();assert.equal(image.requiresPicture(),true);
 image.pictureTaken(0);assert.equal(image.requiresPicture(),false);image.referenceChanged();assert.equal(image.requiresPicture(),true);
 assert.equal(get('calibration-canvas').style.transform,'');
});
test('choosing a different reference clears its old orientation preview baseline',()=>{
 const {image,get}=fixture();image.pictureTaken(0);image.referenceChanged();get('image-mirror').onclick();
 assert.equal(get('calibration-canvas').style.transform,'');assert.equal(image.requiresPicture(),true);
});
