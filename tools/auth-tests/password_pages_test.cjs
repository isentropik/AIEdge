const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');
function fixture(file,reply){
 const text=fs.readFileSync(path.join(root,'shared',file),'utf8');
 const script=text.match(/<script>([\s\S]*?)<\/script>/)[1];
 const elements={};for(const id of ['theme','password','confirm','current','token','show','save','status','form','continue'])elements[id]={value:'',type:'password',hidden:false,disabled:false,attrs:{},setAttribute(k,v){this.attrs[k]=v}};
 elements.continue.hidden=true;const calls=[];
 const context={document:{getElementById:id=>elements[id],documentElement:{dataset:{}}},localStorage:{getItem(){return null},setItem(){}},TextEncoder,btoa:s=>Buffer.from(s,'binary').toString('base64'),fetch:async(url,options)=>{calls.push({url,options});if(reply instanceof Error)throw reply;return reply||{ok:true,text:async()=> 'Saved'}}};
 vm.runInNewContext(script,context);return {elements,calls,submit:()=>elements.form.onsubmit({preventDefault(){}})};
}
(async()=>{
 for(const [file,change] of [['WebsiteSetupPage.h',false],['WebsitePasswordPage.h',true]]){
  const f=fixture(file);const e=f.elements;e.password.value='new-long-password';e.confirm.value='different';e.current.value='old-pąssword-long';e.token.value='ab'.repeat(32);
  await f.submit();assert.equal(f.calls.length,0);assert.match(e.status.textContent,/do not match/);
  e.password.value=e.confirm.value='😀'.repeat(33);await f.submit();assert.equal(f.calls.length,0);assert.match(e.status.textContent,/128 UTF-8/);
  e.password.value=e.confirm.value='new-long-password';e.show.onclick();assert.equal(e.password.type,'text');assert.equal(e.confirm.type,'text');if(change)assert.equal(e.current.type,'text');e.show.onclick();assert.equal(e.password.type,'password');
  await f.submit();assert.equal(f.calls.length,1);const call=f.calls[0];assert.equal(call.url,change?'/auth/password':'/auth/setup');assert.equal(call.options.method,'POST');assert.equal(call.options.body,'new-long-password');
  if(change){assert.equal(call.options.headers.Authorization,'Basic '+Buffer.from('admin:old-pąssword-long','utf8').toString('base64'));assert.equal(call.options.headers['X-AIEdge-Password-Change'],'confirm')}else assert.equal(call.options.headers['X-AIEdge-Setup'],'ab'.repeat(32));
  assert.equal(e.form.hidden,true);assert.equal(e.continue.hidden,false);assert.equal(e.password.value,'');assert.equal(e.confirm.value,'');assert.equal(e.save.disabled,false);assert.equal(change?e.current.value:e.token.value,'');
  for(const reply of [{ok:false,text:async()=> 'Rejected'},new Error('network')]){
   const bad=fixture(file,reply);bad.elements.password.value=bad.elements.confirm.value='new-long-password';bad.elements.current.value='old-long-password';bad.elements.token.value='ab'.repeat(32);
   await bad.submit();assert.equal(bad.calls.length,1);assert.equal(bad.elements.form.hidden,false);assert.equal(bad.elements.password.value,'new-long-password');assert.equal(bad.elements.save.disabled,false);assert.equal(bad.elements.continue.hidden,true);
  }
 }
 console.log('PASS: embedded password-page JavaScript validation, UTF-8 credentials, eye toggle, successful save and failure behavior (no visual rendering)');
})().catch(e=>{console.error(e);process.exitCode=1});
