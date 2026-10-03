const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'meter-profile.js'),'utf8');
test('page controls have unique IDs so setup cannot target the Overview unit label',()=>{
 const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
 const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
 assert.equal(new Set(ids).size,ids.length);assert.match(html,/<select id="profile-unit"/);
 assert.match(html,/<[^>]+id="meter-unit"/);
});
class Element {
 constructor(){this.value='';this.hidden=false;this.disabled=false;this.dataset={};this.children=[];this.listeners={};}
 append(child){this.children.push(child);}replaceChildren(){this.children=[];}
 addEventListener(name,fn){this.listeners[name]=fn;}focus(){this.focused=true;}
}
function fixture({profile=null,unit='ft3',loadFailure=false,saveFailure=false,unverified=false}={}){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const posts=[],events=[];let failed=loadFailure;
 const fetch=async(url,options={})=>{
  if(failed)return {ok:false,json:async()=>({error:'Load failed'})};
  if(options.method==='POST'){
   const value=JSON.parse(options.body);posts.push(value);
   return {ok:!saveFailure,json:async()=>saveFailure?{error:'meter_profile_changed_reload'}:{revision:'saved',profile:unverified?null:value.profile}};
  }
  return {ok:true,json:async()=>url==='api/setup'?{available:true,token:'fixture',meter:{profile,revision:profile?'original':null}}:{format:{unit}}};
 };
 const window={dispatchEvent:event=>events.push(event.type)};
 vm.runInContext(source,vm.createContext({document:{getElementById:get,createElement:()=>new Element()},window,fetch,AbortSignal,Event}));
 return {get,window,posts,events,setLoadFailure:value=>failed=value};
}
function choose(app,type,unit){app.get('meter-type').value=type;app.get('meter-type').listeners.change();if(unit)app.get('profile-unit').value=unit;}

test('old format units suggest a unit without inventing the meter type',async()=>{
 const app=fixture();await app.window.AIEdgeMeter.load();
 assert.equal(app.get('meter-type').value,'');assert.equal(app.get('profile-unit').disabled,true);
 assert.equal(await app.window.AIEdgeMeter.save(),false);assert.equal(app.posts.length,0);
 choose(app,'gas');assert.equal(app.get('profile-unit').value,'ft3');
 assert.deepEqual(app.get('profile-unit').children.map(e=>e.value),['','ft3','m3']);
 assert.equal(await app.window.AIEdgeMeter.save(),true);
 assert.deepEqual(app.posts[0],{revision:null,profile:{version:1,type:'gas',unit:'ft3'}});
 assert.deepEqual(app.events,['aiedge-meter-saved']);
});

test('unit choices follow meter type and unsupported previous units are cleared',async()=>{
 const app=fixture();await app.window.AIEdgeMeter.load();choose(app,'water','L');choose(app,'gas');
 assert.equal(app.get('profile-unit').value,'');choose(app,'electric');assert.equal(app.get('profile-unit').value,'kWh');
 assert.deepEqual(app.get('profile-unit').children.map(e=>e.value),['','kWh']);
});

test('failed load disables choices and a retry can recover without saving',async()=>{
 const app=fixture({loadFailure:true});assert.equal(await app.window.AIEdgeMeter.load(),false);
 assert.equal(app.get('meter-type').disabled,true);assert.equal(app.get('meter-retry').hidden,false);
 app.setLoadFailure(false);await app.get('meter-retry').onclick();assert.equal(app.get('meter-type').disabled,false);
 assert.equal(app.get('meter-status').hidden,true);assert.equal(app.posts.length,0);
});

test('a save conflict cannot advance or claim success and offers a reload',async()=>{
 const app=fixture({profile:{version:1,type:'gas',unit:'ft3'},saveFailure:true});await app.window.AIEdgeMeter.load();
 choose(app,'gas','m3');assert.equal(await app.window.AIEdgeMeter.save(),false);
 assert.match(app.get('meter-status').textContent,/another session/);assert.equal(app.get('meter-retry').hidden,false);
 assert.deepEqual(app.events,[]);assert.equal(app.get('meter-type').disabled,true);
});

test('unverified readback never marks meter choices saved',async()=>{
 const app=fixture({unverified:true});await app.window.AIEdgeMeter.load();choose(app,'gas');
 assert.equal(await app.window.AIEdgeMeter.save(),false);assert.match(app.get('meter-status').textContent,/could not be verified/);
 assert.deepEqual(app.events,[]);
});

test('unchanged Next still checks the server revision without a new type assumption',async()=>{
 const app=fixture({profile:{version:1,type:'water',unit:'ft3'}});await app.window.AIEdgeMeter.load();
 assert.equal(await app.window.AIEdgeMeter.save(),true);assert.equal(app.posts[0].revision,'original');
 assert.equal(app.posts[0].profile.type,'water');
 assert.deepEqual(app.events,[]);
});
