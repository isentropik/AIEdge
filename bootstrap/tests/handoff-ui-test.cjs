const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../src/SetupPage.h'),'utf8');
const code=[...source.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
async function check(mode,expected){
 const elements=new Map(),requests=[],navigations=[];let schedule=0;
 const element=id=>{if(!elements.has(id))elements.set(id,{hidden:false,disabled:false,textContent:'',value:'',style:{},setAttribute(){}});return elements.get(id);};
 const ctx=vm.createContext({console,Response,AbortController,TextEncoder,document:{getElementById:element},setTimeout(){schedule++;return 1;},clearTimeout(){},location:{replace(url){navigations.push(url);},reload(){}},fetch:async(url)=>{
  requests.push(url);
  if(url==='/status')return new Response('Not found',{status:404});
  if(url==='/?installed=check')return new Response('<h1>AIEdge</h1>',{status:mode==='missing-page'?404:200});
  assert.equal(url,'/info?type=Hostname');
  if(mode==='offline')throw Error('offline');
  if(mode==='html')return new Response('<html>Not ready</html>');
  return new Response(mode==='wrong-device'?'other-device':'aiedge-744b20');
 }});
 vm.runInContext(code,ctx);await new Promise(setImmediate);await new Promise(setImmediate);
 assert.equal(navigations.length,expected);assert.deepEqual(requests,['/status','/info?type=Hostname',...(['ready','missing-page'].includes(mode)?['/?installed=check']:[])]);
 if(expected){assert.match(navigations[0],/^\/\?installed=\d+$/);assert.match(element('state').textContent,/Opening AIEdge/);assert.equal(schedule,3);}
 else {assert.match(element('state').textContent,/not responding/);assert.equal(schedule,mode==='missing-page'?4:3);}
}
(async()=>{for(const mode of ['ready','offline','html','wrong-device','missing-page'])await check(mode,mode==='ready'?1:0);console.log('PASS: application handoff, offline retry, invalid response, wrong-device rejection, homepage readiness; no installation requests.');})().catch(e=>{console.error(e);process.exitCode=1;});
