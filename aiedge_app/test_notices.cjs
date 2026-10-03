const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'notices.js'),'utf8');
function fixture(){
 const elements=new Map(),get=id=>{
  if(!elements.has(id))elements.set(id,{id,textContent:'',dataset:{},hidden:true,parentElement:{hidden:false,closest(){return this.hidden?this:null;}}});
  return elements.get(id);
 };
 const window={},location={hash:'#setup/image'};vm.runInContext(source,vm.createContext({window,location,document:{getElementById:get,querySelectorAll:selector=>[...elements.values()].filter(e=>selector==='[data-notice-scope]'?!!e.dataset.noticeScope:e.dataset.noticeKind==='connection')}}));
 return {get,notices:window.AIEdgeNotices,location};
}
test('a visible form owns one outage message and route changes restore the global message',()=>{
 const f=fixture();f.notices.show('error','Connection lost',true,true);f.notices.show('setup-status','Setup unavailable',true,true);
 f.notices.show('format-status','Format unavailable',true,true);
 assert.equal(f.get('error').hidden,true);assert.equal(f.get('setup-status').hidden,true);assert.equal(f.get('format-status').hidden,false);
 f.get('format-status').parentElement.hidden=true;f.notices.sync();
 assert.equal(f.get('format-status').hidden,true);assert.equal(f.get('setup-status').hidden,false);
 f.get('setup-status').parentElement.hidden=true;f.notices.sync();assert.equal(f.get('error').hidden,false);
 f.get('format-status').parentElement.hidden=false;f.notices.sync();assert.equal(f.get('error').hidden,true);assert.equal(f.get('format-status').hidden,false);
});
test('clearing a specific error restores the wizard connection error without resurrecting cleared notices',()=>{
 const f=fixture();f.notices.show('error','Offline',true,true);f.notices.show('setup-status','Setup offline',true,true);f.notices.show('meter-status','Meter offline',true,true);
 f.notices.show('meter-status','');assert.equal(f.get('meter-status').hidden,true);assert.equal(f.get('setup-status').hidden,false);
 f.notices.show('setup-status','');assert.equal(f.get('error').hidden,false);f.notices.show('error','');f.notices.sync();
 assert.equal(f.get('meter-status').hidden,true);assert.equal(f.get('setup-status').hidden,true);assert.equal(f.get('error').hidden,true);
});
test('local connection notices recover even after a global status request succeeds',()=>{
 const f=fixture();f.notices.show('error','Offline',true,true);f.notices.show('setup-status','Offline setup',true,true);f.notices.show('format-status','Offline format',true,true);
 f.notices.show('error','');f.notices.show('format-status','');assert.equal(f.get('setup-status').hidden,false);
});
test('an unrelated storage or configuration error is never suppressed by an outage notice',()=>{
 const f=fixture();f.notices.show('error','Local storage full',true);f.notices.show('meter-status','Offline',true,true);
 assert.equal(f.get('error').hidden,false);assert.equal(f.get('meter-status').hidden,false);
});
test('timeout and transport failures are distinguished from logic errors and rejected access',()=>{
 const f=fixture();assert.equal(f.notices.connection({name:'TimeoutError'}),true);assert.equal(f.notices.connection({status:503}),true);
 assert.equal(f.notices.connection({name:'TypeError',message:'Failed to fetch'}),true);
 assert.equal(f.notices.connection({name:'TypeError',message:'undefined is not a function'}),false);
 assert.equal(f.notices.connection({status:403}),false);assert.match(f.notices.message({status:403}),/Home Assistant/);
 assert.match(f.notices.message({name:'TimeoutError'}),/did not respond in time/);
 assert.match(f.notices.message({name:'TypeError',message:'Failed to fetch'}),/Could not reach AIEdge/);
 assert.equal(f.notices.message({message:'Calibration changed'}),'Calibration changed');
});
test('a late calibration error stays on image/alignment/dials instead of appearing on Meter or Data',()=>{
 const f=fixture();f.location.hash='#setup/meter';f.notices.show('setup-status','Calibration unavailable',true,true,'editor');
 assert.equal(f.get('setup-status').hidden,true);f.location.hash='#setup/alignment';f.notices.sync();assert.equal(f.get('setup-status').hidden,false);
 f.location.hash='#setup/data';f.notices.sync();assert.equal(f.get('setup-status').hidden,true);
});
test('an action validation stays with its setup step while navigation preserves other drafts',()=>{
 const f=fixture();f.notices.show('setup-status','Take a picture first',true,false,'#setup/image');
 assert.equal(f.get('setup-status').hidden,false);f.location.hash='#setup/lighting';f.notices.sync();assert.equal(f.get('setup-status').hidden,true);
 f.location.hash='#setup/image';f.notices.sync();assert.equal(f.get('setup-status').hidden,false);
});
