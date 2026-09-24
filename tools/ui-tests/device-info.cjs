const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../sd-card/html/device-info.js'),'utf8');
async function render(info){
 const list={items:[],replaceChildren(){this.items=[];},append(...items){this.items.push(...items);}};
 const nodes={refresh:{disabled:false},status:{textContent:''},'device-info':list};
 const context={document:{getElementById:id=>nodes[id],createElement:()=>({textContent:''})},fetch:async()=>({ok:true,json:async()=>[info]}),AbortSignal:{timeout:()=>undefined},Date};
 vm.runInNewContext(source,context);await new Promise(resolve=>setImmediate(resolve));
 assert.equal(nodes.refresh.disabled,false);
 const values={};for(let i=0;i<list.items.length;i+=2)values[list.items[i].textContent]=list.items[i+1].textContent;
 return values;
}
(async()=>{
 for(const [available,error,shown] of [[false,'Failed (0x105)','No'],[true,'Success','Yes'],[false,'Not attempted','No']]){
  const values=await render({camera_available:available,camera_initialization:error});
  assert.equal(values['Camera detected'],shown);assert.equal(values['Camera initialization'],error);
 }
 assert.equal((await render({}))['Camera initialization'],'Unavailable');
 assert.equal((await render({camera_initialization:'<script>bad</script>'}))['Camera initialization'],'<script>bad</script>');
 console.log('Device information: camera initialization result, missing fields and text rendering passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
