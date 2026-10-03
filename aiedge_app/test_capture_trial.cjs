const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'capture-trial.js'),'utf8');
const ID='a'.repeat(32),JOB='b'.repeat(32);
const ok=data=>({ok:true,status:200,json:async()=>data}),bad=error=>({ok:false,status:400,json:async()=>({error})});
const queued=(extra={})=>({request_id:ID,job:JOB,state:'queued',attempts:0,max_attempts:3,unique_images:0,duplicate_images:0,counts_complete:true,...extra});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(fetch,{hash='#captures',stored=null,storageFailed=false,hidden=false}={}){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,{textContent:'',hidden:false,disabled:false,dataset:{}});return elements.get(id);};
 const listeners={},timers=new Map(),posts=[],saved=new Map(stored?[['aiedge-capture-trial:/',stored]]:[]);
 let timerId=0;
 const document={getElementById:get,hidden,readyState:'complete',addEventListener(name,fn){listeners[name]=fn;}};
 const location={hash,pathname:'/'};
 const window={addEventListener(name,fn){listeners[name]=fn;}};
 const sessionStorage={getItem:key=>saved.get(key)||null,setItem(key,value){if(storageFailed)throw Error('storage disabled');saved.set(key,value);}};
 vm.runInContext(source,vm.createContext({document,location,window,sessionStorage,AbortSignal,Uint8Array,
  crypto:{getRandomValues(array){array.fill(170);return array;}},fetch:async(url,options={})=>{if(options.method==='POST')posts.push({url,options,body:JSON.parse(options.body)});return fetch(url,options);},
  setTimeout(fn){timers.set(++timerId,fn);return timerId;},clearTimeout(id){timers.delete(id);}}));
 return {get,location,document,listeners,timers,posts,saved,async poll(){const next=[...timers.entries()][0];assert.ok(next,'Expected status poll');timers.delete(next[0]);await next[1]();}};
}
test('opening captures reads status only and leaves idle polling stopped',async()=>{
 const urls=[];const app=fixture(async url=>{urls.push(url);return ok({state:'idle',can_start:true});});await tick();
 assert.deepEqual(urls,['api/capture-trial']);assert.equal(app.posts.length,0);assert.equal(app.get('trial-start').disabled,false);assert.equal(app.timers.size,0);
});
test('overview and hidden tabs do not poll trials or request photos',async()=>{
 for(const options of [{hash:'#overview'},{hidden:true}]){let count=0;const app=fixture(async()=>{count++;return ok({});},options);await tick();assert.equal(count,0);assert.equal(app.timers.size,0);}
});
test('double start uses one journal ID and the existing setup token',async()=>{
 let finish,app;app=fixture(async(url,options)=>url==='api/setup'?ok({token:'fixture-only'}):options.method==='POST'?new Promise(resolve=>finish=resolve):ok(app?.posts.length?queued({can_start:false}):{state:'idle',can_start:true}));
 await tick();const first=app.get('trial-start').onclick();app.get('trial-start').onclick();await tick();assert.equal(app.posts.length,1);
 assert.deepEqual(app.posts[0].body,{action:'start',request_id:ID,max_attempts:3,duration_seconds:90,interval_seconds:30});
 assert.equal(app.posts[0].options.headers['X-AIEdge-Setup'],'fixture-only');finish(ok(queued()));await first;
 assert.equal(app.get('trial-stop').hidden,false);assert.equal(app.get('trial-start').disabled,true);
});
test('a lost start reply reads its existing job without issuing another POST',async()=>{
 let app;app=fixture(async(url,options)=>url==='api/setup'?ok({token:'fixture'}):options.method==='POST'?Promise.reject(new TypeError('lost')):ok(app?.posts.length?queued({state:'working',attempts:1,can_start:false}):{state:'idle',can_start:true}));
 await tick();await app.get('trial-start').onclick();assert.equal(app.posts.length,1);assert.equal(app.get('trial-state').textContent,'Capturing…');assert.equal(app.get('trial-stop').hidden,false);assert.equal(app.get('trial-check').hidden,true);
});
test('unconfirmed admission is retried only explicitly and with the same ID',async()=>{
 let admitted=false,app;app=fixture(async(url,options)=>{
  if(url==='api/setup')return ok({token:'fixture'});
  if(options.method==='POST'){if(!admitted)throw new TypeError('lost');return ok(queued());}
  return ok(app?.posts.length?(admitted?queued({can_start:false}):{state:'not_found',request_id:ID,can_start:true}):{state:'idle',can_start:true});
 });await tick();await app.get('trial-start').onclick();assert.equal(app.posts.length,1);assert.equal(app.get('trial-start').textContent,'Retry start');
 await app.poll();assert.equal(app.posts.length,1);admitted=true;await app.get('trial-start').onclick();assert.equal(app.posts.length,2);assert.equal(app.posts[0].body.request_id,app.posts[1].body.request_id);
});
test('reload recovers a saved request without automatically starting or resuming',async()=>{
 const urls=[];const app=fixture(async url=>{urls.push(url);return ok(queued({state:'interrupted',error:'trial_interrupted',counts_complete:false,capture_outcome_uncertain:true,can_start:true}));},{stored:ID});await tick();
 assert.deepEqual(urls,['api/capture-trial?request_id='+ID]);assert.equal(app.posts.length,0);assert.match(app.get('trial-notice').textContent,/will not resume/);assert.match(app.get('trial-notice').textContent,/unknown outcome/);assert.equal(app.timers.size,0);
});
test('Stop requests cancellation once and keeps the in-flight state visible',async()=>{
 let stopped=false;const app=fixture(async(url,options)=>url==='api/setup'?ok({token:'fixture'}):options.method==='POST'?(stopped=true,ok(queued({state:'cancelling'}))):ok(queued({state:stopped?'cancelling':'working',can_start:false})));await tick();
 const stop=app.get('trial-stop').onclick();app.get('trial-stop').onclick();await stop;assert.equal(app.posts.length,1);assert.deepEqual(app.posts[0].body,{action:'cancel',request_id:ID});assert.equal(app.get('trial-state').textContent,'Stopping…');assert.equal(app.get('trial-stop').disabled,true);
});
test('completed duplicate captures show separate attempts and unique counts',async()=>{
 const app=fixture(async()=>ok(queued({state:'completed',attempts:3,unique_images:1,duplicate_images:2,can_start:true})));await tick();
 assert.equal(app.get('trial-counts').textContent,'3 / 3 attempts · 1 unique · 2 repeated');assert.equal(app.get('trial-progress').value,3);assert.equal(app.timers.size,0);assert.equal(app.get('trial-start').disabled,false);
});
test('unavailable journal blocks start and shows one actionable error',async()=>{
 const app=fixture(async()=>ok({state:'unavailable',can_start:false,error:'trial_journal_invalid',block_reason:'trial_journal_invalid',counts_complete:false}));await tick();
 assert.equal(app.get('trial-start').disabled,true);assert.match(app.get('trial-notice').textContent,/saved trial record/);assert.match(app.get('trial-notice').textContent,/incomplete/);assert.equal(app.posts.length,0);
});
test('missing tab storage refuses to start a request it cannot track',async()=>{
 const app=fixture(async()=>ok({state:'idle',can_start:true}),{storageFailed:true});await tick();await app.get('trial-start').onclick();assert.equal(app.posts.length,0);assert.equal(app.get('trial-start').disabled,true);assert.match(app.get('trial-notice').textContent,/Browser storage/);
});
test('an inaccessible app leaves Start disabled and polls only while visible',async()=>{
 const app=fixture(async()=>{throw new TypeError('lost');});await tick();assert.equal(app.get('trial-start').disabled,true);assert.equal(app.timers.size,1);
 app.document.hidden=true;app.listeners.visibilitychange();assert.equal(app.timers.size,0);assert.equal(app.posts.length,0);
});
test('blocked admission never changes app options or offers automatic capture',async()=>{
 const app=fixture(async()=>ok({state:'idle',can_start:false,block_reason:'trial_not_allowed'}));await tick();assert.equal(app.get('trial-start').disabled,true);assert.match(app.get('trial-notice').textContent,/Pause automatic capture/);assert.equal(app.posts.length,0);
});
test('trial controls are packaged with accessible progress and compact responsive styles',()=>{
 const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8'),css=fs.readFileSync(path.join(__dirname,'parity.css'),'utf8'),docker=fs.readFileSync(path.join(__dirname,'Dockerfile'),'utf8');
 for(const id of ['trial-start','trial-stop','trial-check','trial-state','trial-progress','trial-notice'])assert.equal((html.match(new RegExp('id="'+id+'"','g'))||[]).length,1);
 assert.ok(html.includes('src="capture-trial.js"'));assert.ok(html.includes('aria-label="Capture attempts"'));assert.match(css,/\.trial-body\{align-items:flex-start;flex-direction:column/);assert.ok(docker.includes('COPY capture_trial.py capture-trial.js ./'));
});
