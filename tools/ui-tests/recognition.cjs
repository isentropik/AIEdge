const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../sd-card/html/recognition.js'),'utf8');
function node(){return {items:[],textContent:'',append(...items){this.items.push(...items);},replaceChildren(){this.items=[];}};}
async function render(responses){
 const nodes={refresh:node(),connection:node(),'recognition-results':node()},requests=[];
 const context={document:{getElementById:id=>nodes[id],createElement:node},Date,
  AbortSignal:{timeout:()=>undefined},fetch:async url=>{requests.push(url);const kind=url.split('type=')[1];const body=responses[kind];return {ok:body!==null,text:async()=>body||''};}};
 vm.runInNewContext(source,context);await new Promise(resolve=>setImmediate(resolve));
 assert.equal(nodes.refresh.disabled,false);assert.equal(requests.length,4);
 const cards={};for(const card of nodes['recognition-results'].items){const [title,list]=card.items;const values={};for(let i=0;i<list.items.length;i+=2)values[list.items[i].textContent]=list.items[i+1].textContent;cards[title.textContent]=values;}
 return {nodes,cards};
}
(async()=>{
 let r=await render({value:'Main\t',raw:'Main\t',prevalue:'Main\t',error:'Main\t'});
 assert.deepEqual(Object.keys(r.cards),['Main']);assert.equal(r.cards.Main.Reading,'Unavailable');
 r=await render({value:'Main\t0255310\r\nSecondary\t0',raw:'Main\t0255310\r\nSecondary\t',prevalue:null,error:'Main\tno error\r\nSecondary\t<script>example</script>'});
 assert.equal(r.cards.Main.Reading,'0255310');assert.equal(r.cards.Secondary.Reading,'0');
 assert.equal(r.cards.Secondary['Raw recognition'],'Unavailable');
 assert.equal(r.cards.Secondary.Validation,'<script>example</script>');
 assert.match(r.nodes.connection.textContent,/Some readings are unavailable/);
 r=await render({value:'invalid response',raw:'Main\t3',prevalue:'',error:''});
 assert.deepEqual(Object.keys(r.cards),['Main']);assert.equal(r.cards.Main.Reading,'Unavailable');
 assert.match(r.nodes.connection.textContent,/Some readings are unavailable/);
 r=await render({});assert.equal(Object.keys(r.cards).length,0);assert.match(r.nodes.connection.textContent,/No recognition output/);
 console.log('Recognition output: empty named rows, leading zeros, zero readings, partial failures, malformed rows and text-only rendering passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
