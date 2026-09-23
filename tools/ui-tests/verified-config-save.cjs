const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const base=require('node:path').resolve(__dirname,'../../sd-card/html')+'/';
for(const file of ['readconfigcommon.js','readconfigparam.js']) {
 const source=fs.readFileSync(base+file,'utf8');
 const save=source.slice(source.indexOf('function SaveConfigToServer('),source.indexOf('\n}',source.indexOf('function SaveConfigToServer('))+2);
 const calls=[];let status=200,response='{"saved":true}';
 const context={config_loaded_bytes:'old\r\n',config_split:['new','',''],firework:{launch(){}},XMLHttpRequest:class{open(m,u){calls.push([m,u])}setRequestHeader(){}send(v){this.status=status;this.responseText=response;this.payload=v;calls.push(JSON.parse(v))}}};
 vm.createContext(context);vm.runInContext(save,context);
 assert.equal(context.SaveConfigToServer(''),true);assert.equal(context.config_loaded_bytes,'new\n');assert.deepEqual(calls[0],['POST','/config-save']);assert.deepEqual(calls[1],{before:'old\r\n',after:'new\n'});
 status=409;assert.equal(context.SaveConfigToServer(''),false);assert.equal(context.config_loaded_bytes,'new\n');
 status=200;response='bad';assert.equal(context.SaveConfigToServer(''),false);
 context.config_loaded_bytes=null;const count=calls.length;assert.equal(context.SaveConfigToServer(''),false);assert.equal(calls.length,count);
}
for(const name of fs.readdirSync(base).filter(n=>n.endsWith('.html'))) {
 const s=fs.readFileSync(base+name,'utf8');for(const line of s.split('\n').filter(x=>x.includes('SaveConfigToServer(domainname)')))assert.match(line,/if \(!SaveConfigToServer\(domainname\)\) return;/,name);
}
console.log('Verified saves: exact baseline, trimmed lines, conflict/failure handling, all callers gated.');
