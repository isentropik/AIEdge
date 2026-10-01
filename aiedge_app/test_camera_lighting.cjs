const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const logic=require('./camera-lighting.js'),source=fs.readFileSync(path.join(__dirname,'camera-lighting.js'),'utf8');
const white={source:'strip',pin:12,type:'SK6812_RGBW',count:19,channels:[0,0,0,255],intensity:25};
class Element{
 constructor(){this.value='';this.hidden=false;this.disabled=false;this.textContent='';this.children=[];}
 replaceChildren(){this.children=[];}append(child){this.children.push(child);}
}
function fixture(){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const calls=[],window={updateSetupFlow(){}};
 vm.runInContext(source,vm.createContext({window,document:{getElementById:get,querySelectorAll:()=>[],createElement:()=>new Element()}}));
 const controls=window.AIEdgeCameraControls;
 controls.connect(async(action,details)=>{calls.push({action,details});return true;});controls.configure(true);
 controls.receive({action:'lighting-load',settings:{revision:'a'.repeat(64),lighting:white,capabilities:{builtin_pin:4,pins:[0,1,3,4,12,13].map(pin=>({pin,available:pin!==0}))},sensor:'OV2640',needs_activation:false}});
 return {controls,get,calls};
}
test('W lighting has one brightness control and no RGB or W numeric duplicate',()=>{
 const {get}=fixture();assert.equal(get('lighting-mode').value,'white');assert.equal(get('lighting-color-label').hidden,true);
 assert.equal(get('lighting-custom').hidden,true);assert.equal(get('image-brightness').hidden,false);assert.equal(get('lighting-percent').textContent,'25%');
 assert.equal(get('image-sensor').textContent,'OV2640');
});
test('custom mix hides the color picker and shows only channel controls',()=>{
 const {get}=fixture();get('lighting-mode').value='custom';get('lighting-mode').onchange();
 assert.equal(get('lighting-custom').hidden,false);assert.equal(get('lighting-color-label').hidden,true);
});
test('RGB strips have no white-channel selection or W input',()=>{
 const {get}=fixture();get('lighting-type').value='WS2812B';get('lighting-type').oninput();
 assert.equal(get('lighting-mode-label').hidden,true);assert.equal(get('lighting-white-channel').hidden,true);
 assert.equal(get('lighting-color-label').hidden,false);
});
test('changing brightness marks a new photo as needed without capturing or writing automatically',()=>{
 const {controls,get,calls}=fixture();get('lighting-intensity').value='90';get('lighting-intensity').oninput();
 assert.equal(controls.requiresPicture(),true);assert.deepEqual(calls,[]);
 get('lighting-intensity').value='25';get('lighting-intensity').oninput();assert.equal(controls.requiresPicture(),false);
});
test('unchanged lighting advances without any save or activation request',async()=>{
 const {controls,calls}=fixture();assert.equal(await controls.apply(),true);assert.deepEqual(calls,[]);
});
test('white-mode brightness scales the dedicated W channel without changing it',async()=>{
 const {controls,get,calls}=fixture();get('lighting-intensity').value='100';get('lighting-intensity').oninput();await controls.apply();
 assert.equal(calls[0].action,'lighting-apply');assert.equal(calls[0].details.lighting.intensity,100);
 assert.deepEqual(JSON.parse(JSON.stringify(calls[0].details.lighting.channels)),[0,0,0,255]);
});
test('uncertain activation requires an explicit apply and remains stale until a verified photo',async()=>{
 const {controls,get,calls}=fixture();controls.markAttention();assert.equal(get('apply-saved-lighting').hidden,false);
 await controls.apply();assert.equal(calls.length,1);
 controls.receive({action:'lighting-apply',settings:{revision:'b'.repeat(64),lighting:{...white,intensity:80},capabilities:{builtin_pin:4,pins:[]},changed:true,needs_activation:false}});
 assert.equal(controls.requiresPicture(),true);controls.pictureTaken();assert.equal(controls.requiresPicture(),false);
});
test('pins are labelled without exposing firmware response text',()=>{
 const {get}=fixture();const options=get('lighting-pin').children;
 assert.equal(options[0].disabled,true);assert.equal(options[0].textContent,'GPIO 0 · unavailable');
 assert.equal(get('lighting-pin').value,'12');
});
test('invalid channels fail locally without a request',async()=>{
 const {controls,get,calls}=fixture();get('lighting-channel-3').value='256';get('lighting-channel-3').oninput();
 await assert.rejects(controls.apply(),/channel values/);assert.deepEqual(calls,[]);
});
test('switching RGB back to white restores white-only output',()=>{
 const rgb=logic.chooseMode(white,'rgb'),again=logic.chooseMode(rgb,'white');
 assert.equal(logic.mode(rgb),'rgb');assert.deepEqual(again.channels,[0,0,0,255]);assert.equal(logic.mode(again),'white');
});
