import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {watchRelease} from '../release-watch.mjs';

// Run the page controller; replace only the USB component import, never use a port.
const source=fs.readFileSync(new URL('../installer.js',import.meta.url),'utf8')
 .replace("import {watchRelease} from './release-watch.mjs';",'')
 .replace(/await import\('\.\/vendor\/esp-web-tools-aiedge\.js\?[^']+'\);/,'');
const binary=new Uint8Array([1,2,3,4]);
const hash=Buffer.from(await webcrypto.subtle.digest('SHA-256',binary)).toString('hex');
let time=0,release='test-1',offline=false,click,manifestWrites=0,revokes=0;
const urls=new Map(),status={textContent:'',dataset:{}},version={textContent:''};
const button={hidden:true,setAttribute(k,v){assert.equal(k,'manifest');this.manifest=v;manifestWrites++;},addEventListener(kind,handler,capture){assert.equal(kind,'click');assert.equal(capture,true);click=handler;}};
const listeners={};
class TestURL extends URL {
 static createObjectURL(blob){const key='blob:test-'+urls.size;urls.set(key,blob);return key;}
 static revokeObjectURL(){revokes++;}
}
const manifest=()=>({name:'AIEdge Wi-Fi loader',version:release,builds:[{chipFamily:'ESP32',parts:[{path:'firmware.bin',offset:0}]}]});
const context={watchRelease:args=>watchRelease({...args,now:()=>time}),Blob,URL:TestURL,Uint8Array,crypto:webcrypto,AbortSignal,
 window:{isSecureContext:true,addEventListener:(name,fn)=>listeners[name]=fn},navigator:{serial:{}},
 location:{href:'https://example.test/',origin:'https://example.test'},customElements:{whenDefined:async()=>{}},
 document:{hidden:false,querySelector:s=>({'#status':status,'#install':button,'#verified-version':version}[s]),addEventListener:(name,fn)=>listeners[name]=fn},
 setInterval:fn=>listeners.interval=fn,
 fetch:async url=>{if(offline)throw Error('offline');const key=String(url);return {ok:true,json:async()=>key==='manifest.json'?manifest():{version:'test-1',files:{'firmware.bin':{bytes:4,sha256:hash}}},arrayBuffer:async()=>binary.buffer};}
};
vm.runInNewContext(source,context);
const settle=async()=>{for(let i=0;i<20;i++)await new Promise(r=>setImmediate(r));};
await settle();
assert.equal(button.hidden,false);assert.equal(version.textContent,'test-1');assert.equal(manifestWrites,1);
const originalManifest=button.manifest;
let prevented=0,stopped=0;
const event={preventDefault(){prevented++;},stopImmediatePropagation(){stopped++;}};
click(event);assert.equal(prevented,0);
time=60001;offline=true;click(event);await settle();
assert.equal(prevented,1);assert.equal(stopped,1);assert.match(status.textContent,/Could not check/);
offline=false;click(event);await settle();assert.match(status.textContent,/Ready to connect/);
const count=prevented;click(event);assert.equal(prevented,count);
time+=60001;release='test-2';listeners.interval();await settle();
assert.equal(button.hidden,true);assert.match(status.textContent,/Finish any active installation/);
assert.equal(button.manifest,originalManifest);assert.equal(manifestWrites,1);assert.equal(revokes,0);
const verifiedManifest=JSON.parse(await urls.get(originalManifest).text());
assert.equal(verifiedManifest.version,'test-1');
assert.deepEqual(new Uint8Array(await urls.get(verifiedManifest.builds[0].parts[0].path).arrayBuffer()),binary);
console.log('Installer integration: expired clicks blocked, offline retry works, newer release hides only new connection, verified blobs remain unchanged.');
