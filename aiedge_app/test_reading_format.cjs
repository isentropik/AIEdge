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
 getContext(){return {};}
}
const reply=body=>({ok:true,json:async()=>body});
function fixture(format=savedFormat){
 const elements=new Map(),get=id=>{if(!elements.has(id)){const e=new Element('div',elements);e.id=id;}return elements.get(id);};
 const field=(id,tag)=>{const e=new Element(tag,elements);e.id=id;return e;};
 const unit=field('format-unit','select');unit.required=true;
 const rate=field('format-max-rate','input');rate.type='number';rate.min='0';
 get('format-advanced').append(get('format-errors'));
 get('reading-form').append(unit,rate,get('format-dials'),get('format-advanced'));
 const posts=[],events={};
 const window={addEventListener(name,fn){events[name]=fn;},dispatchEvent(){}};
 const fetch=async(url,options={})=>{
  if(options.method==='POST'){posts.push(JSON.parse(options.body));return reply({revision:'saved'});}
  if(url==='api/setup')return reply({token:'test-token',calibration:{dials:[]}});
  return reply({pipeline_id:pipeline,revision:'original',format,dials});
 };
 vm.runInContext(source,vm.createContext({document:{getElementById:get,createElement:tag=>new Element(tag,elements)},window,fetch,AbortSignal,Event}));
 return {get,window,posts,events};
}
const submit=app=>app.get('reading-form').onsubmit({preventDefault(){}});
function change(app,id,value){app.get(id).value=value;app.get(id).fire('input');}

test('new formats save without choosing provisional errors; ordinary rows contain only values',async()=>{
 const app=fixture(null);await app.window.openReadingFormat();
 assert.equal(app.get('format-advanced').open,false);
 assert.equal(app.get('format-dials').querySelectorAll('input').length,2);
 assert.equal(app.get('format-errors').querySelectorAll('input').length,2);
 app.get('format-unit').value='ft3';app.get('format-unit').fire('change');
 change(app,'format-value-0',1000);change(app,'format-value-1',5);
 await submit(app);
 assert.equal(app.posts.length,1);
 assert.deepEqual(app.posts[0].format.dials,[{index:0,value_per_revolution:1000,position_error:.1},{index:1,value_per_revolution:5,position_error:.1}]);
 assert.equal(app.get('format-advanced').open,false);
});

test('editing a scale preserves saved zero and custom error bounds with Advanced closed',async()=>{
 const app=fixture();await app.window.openReadingFormat();
 assert.equal(app.get('format-error-0').value,'0');assert.equal(app.get('format-error-1').value,'0.2');
 change(app,'format-value-0',10000);await submit(app);
 assert.deepEqual(app.posts[0].format.dials,[{index:0,value_per_revolution:10000,position_error:0},{index:1,value_per_revolution:5,position_error:.2}]);
 assert.equal(app.get('format-advanced').open,false);
});

test('invalid collapsed overrides open Advanced and prevent a write',async()=>{
 for(const value of ['',-.01,.5,'NaN']){
  const app=fixture();await app.window.openReadingFormat();change(app,'format-error-1',value);
  app.get('format-advanced').open=false;await submit(app);
  assert.equal(app.get('format-advanced').open,true,value);assert.equal(app.posts.length,0,value);
 }
});

test('a changed pipeline never inherits old dial scales or custom error bounds',async()=>{
 const app=fixture({...savedFormat,pipeline_id:'b'.repeat(64)});await app.window.openReadingFormat();
 assert.equal(app.get('format-value-0').value,'');assert.equal(app.get('format-value-1').value,'');
 assert.equal(app.get('format-error-0').value,'0.1');assert.equal(app.get('format-error-1').value,'0.1');
 assert.match(app.get('format-status').textContent,/Calibration or the model changed/);
 await submit(app);assert.equal(app.posts.length,0);
});

test('native validation reveals a hidden invalid override before the submit event',async()=>{
 const app=fixture();await app.window.openReadingFormat();
 change(app,'format-error-1',.5);app.get('reading-form').fire('invalid',app.get('format-error-1'));
 assert.equal(app.get('format-advanced').open,true);assert.equal(app.posts.length,0);
 app.get('format-advanced').open=false;app.get('reading-form').fire('invalid',app.get('format-value-1'));
 assert.equal(app.get('format-advanced').open,false);
});

test('manual overrides and the optional rate retain the existing API contract',async()=>{
 const app=fixture();await app.window.openReadingFormat();
 change(app,'format-error-0',.15);change(app,'format-max-rate',30);await submit(app);
 assert.equal(app.posts[0].format.maximum_rate_per_second,.5);
 assert.deepEqual(app.posts[0].format.dials.map(d=>d.position_error),[.15,.2]);
 assert.equal(app.posts[0].revision,'original');assert.equal(app.posts[0].format.pipeline_id,pipeline);
});
