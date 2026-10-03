const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'reading-format.js'),'utf8');
const pipeline='a'.repeat(64);
const dials=[{index:0,name:'Register',direction:'ccw'},{index:1,name:'Wheel',direction:'cw'}];
const savedFormat={version:1,pipeline_id:pipeline,unit:'ft3',dials:[
 {index:0,value_per_revolution:1000,position_error:0},
 {index:1,value_per_revolution:5,position_error:.2}
]};
class Element {
 constructor(tag,registry){this.tag=tag;this.registry=registry;this.children=[];this.listeners={};this.attributes={};this.dataset={};this.disabled=false;this.hidden=false;this.open=false;this._value='';this.textContent='';}
 set id(value){this._id=value;this.registry.set(value,this);}get id(){return this._id;}
 set value(value){this._value=String(value);}get value(){return this._value;}
 setAttribute(name,value){this.attributes[name]=value;}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=children;}
 addEventListener(name,fn){this.listeners[name]=fn;}
 fire(name,target=this){this.listeners[name]?.({target});}
 contains(target){return this===target||this.children.some(child=>child.contains(target));}
 querySelectorAll(selector){const tags=selector.split(',');return this.children.flatMap(child=>[...(tags.includes(child.tag)?[child]:[]),...child.querySelectorAll(selector)]);}
 checkValidity(){if(this.disabled)return true;if(this.required&&this.value==='')return false;if(this.type!=='number'||this.value==='')return true;const n=Number(this.value);return Number.isFinite(n)&&(this.min===undefined||n>=Number(this.min))&&(this.max===undefined||n<=Number(this.max));}
 reportValidity(){return this.querySelectorAll('input,select').every(field=>field.checkValidity());}
 focus(){this.focused=true;}
 focus(){this.focused=true;}
 getContext(){return {};}
}
const reply=body=>({ok:true,json:async()=>body});
function fixture(format=savedFormat,meter=null){
 const elements=new Map(),get=id=>{if(!elements.has(id)){const e=new Element('div',elements);e.id=id;}return elements.get(id);};
 const field=(id,tag)=>{const e=new Element(tag,elements);e.id=id;return e;};
 const unit=field('format-unit','select');unit.required=true;
 const rate=field('format-max-rate','input');rate.type='number';rate.min='0';
 get('reading-form').append(unit,rate,get('format-dials'));
 const posts=[],events={};
 const window={addEventListener(name,fn){events[name]=fn;},dispatchEvent(){}};
 const fetch=async(url,options={})=>{
  if(options.method==='POST'){posts.push(JSON.parse(options.body));return reply({revision:'saved'});}
  if(url==='api/setup')return reply({token:'test-token',calibration:{dials:[]},meter});
  return reply({pipeline_id:pipeline,revision:'original',format,dials});
 };
 vm.runInContext(source,vm.createContext({document:{getElementById:get,createElement:tag=>new Element(tag,elements)},window,fetch,AbortSignal,Event}));
 return {get,window,posts,events};
}
const submit=app=>app.get('reading-form').onsubmit({preventDefault(){}});
function change(app,id,value){app.get(id).value=value;app.get(id).fire('input');}

test('missing revolution values have one inline error and focus the field without a native popup',async()=>{
 const app=fixture();await app.window.openReadingFormat();change(app,'format-value-1','');
 assert.equal(app.get('reading-form').noValidate,true);
 app.get('reading-form').reportValidity=()=>{throw Error('Native popup must not run');};
 assert.equal(await submit(app),false);assert.equal(app.posts.length,0);
 assert.equal(app.get('format-value-1').focused,true);assert.equal(app.get('format-status').textContent,'Enter a value per revolution for Wheel.');
});

test('reopening a loaded number format preserves unsaved scales and performs no write',async()=>{
 const app=fixture();await app.window.openReadingFormat();change(app,'format-value-0','1234');
 await app.window.openReadingFormat();assert.equal(app.get('format-value-0').value,'1234');assert.equal(app.posts.length,0);
});

test('changed meter units cannot silently reuse saved physical scales or rate',async()=>{
 const app=fixture({...savedFormat,maximum_rate_per_second:1},{profile:{type:'gas',unit:'m3'}});
 await app.window.openReadingFormat();
 assert.equal(app.get('format-unit').value,'m3');assert.equal(app.get('format-unit').disabled,true);
 assert.equal(app.get('format-unit-select').hidden,true);assert.equal(app.get('format-unit-summary').hidden,false);
 assert.equal(app.get('format-value-0').value,'');assert.equal(app.get('format-value-1').value,'');assert.equal(app.get('format-max-rate').value,'');
 assert.match(app.get('format-status').textContent,/Units changed from ft³ to m³/);
 await submit(app);assert.equal(app.posts.length,0);
 change(app,'format-value-0',1000);change(app,'format-value-1',5);await submit(app);
 assert.equal(app.posts.length,1);assert.equal(app.posts[0].format.unit,'m3');
 assert.deepEqual(app.posts[0].format.dials.map(d=>d.position_error),[0,.2]);
});

test('matching meter units preserve existing values and allow unchanged Next',async()=>{
 const app=fixture(savedFormat,{profile:{type:'gas',unit:'ft3'}});await app.window.openReadingFormat();
 assert.equal(app.get('format-value-0').value,'1000');assert.equal(app.get('format-value-1').value,'5');
 assert.equal(await submit(app),true);assert.equal(app.posts.length,0);
});

test('a meter change invalidates the open form before it can submit old values',async()=>{
 const app=fixture();await app.window.openReadingFormat();app.events['aiedge-meter-saved']();
 change(app,'format-value-0',10000);assert.equal(await submit(app),false);assert.equal(app.posts.length,0);
 assert.equal(app.get('save-format').disabled,true);
});

test('new formats save without choosing provisional errors; ordinary rows contain only values',async()=>{
 const app=fixture(null);await app.window.openReadingFormat();
 assert.equal(app.get('format-dials').querySelectorAll('input').length,2);
 app.get('format-unit').value='ft3';app.get('format-unit').fire('change');
 change(app,'format-value-0',1000);change(app,'format-value-1',5);
 await submit(app);
 assert.equal(app.posts.length,1);
 assert.deepEqual(app.posts[0].format.dials,[{index:0,value_per_revolution:1000,position_error:.1},{index:1,value_per_revolution:5,position_error:.1}]);
});

test('editing a scale preserves saved zero and custom internal error bounds',async()=>{
 const app=fixture();await app.window.openReadingFormat();
 change(app,'format-value-0',10000);await submit(app);
 assert.deepEqual(app.posts[0].format.dials,[{index:0,value_per_revolution:10000,position_error:0},{index:1,value_per_revolution:5,position_error:.2}]);
});

test('a changed pipeline never inherits old dial scales or custom error bounds',async()=>{
 const app=fixture({...savedFormat,pipeline_id:'b'.repeat(64)});await app.window.openReadingFormat();
 assert.equal(app.get('format-value-0').value,'');assert.equal(app.get('format-value-1').value,'');
 assert.match(app.get('format-status').textContent,/Calibration or the model changed/);
 await submit(app);assert.equal(app.posts.length,0);
});

test('the optional rate preserves reader assumptions and the existing API contract',async()=>{
 const app=fixture();await app.window.openReadingFormat();
 change(app,'format-max-rate',30);await submit(app);
 assert.equal(app.posts[0].format.maximum_rate_per_second,.5);
 assert.deepEqual(app.posts[0].format.dials.map(d=>d.position_error),[0,.2]);
 assert.equal(app.posts[0].revision,'original');assert.equal(app.posts[0].format.pipeline_id,pipeline);
});
