// Modified ESP Web Tools 10.4.0 build for AIEdge. Upstream: Apache-2.0.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
const here=path.dirname(fileURLToPath(import.meta.url));
const deps=path.join(here,'node_modules');
const output=path.resolve(here,'../vendor');
await fs.mkdir(output,{recursive:true});
function replaceOnce(text,from,to) {
 if(text.split(from).length!==2) throw new Error('Upstream patch anchor changed: '+from.slice(0,80));
 return text.replace(from,to);
}
await build({entryPoints:[path.join(here,'entry.mjs')],outfile:path.join(output,'esp-web-tools-aiedge.js'),bundle:true,format:'esm',target:'es2022',minify:true,legalComments:'eof',banner:{js:'/* ESP Web Tools 10.4.0, ESPHome / Open Home Foundation, Apache-2.0. Modified by AIEdge for bounded USB discovery recovery. See NOTICES.txt. */'},plugins:[{name:'aiedge-discovery',setup(b){
 b.onLoad({filter:/esp-web-tools[\\/]dist[\\/]install-dialog\.js$/},async args=>{
  let s=await fs.readFile(args.path,'utf8');
  s="import {Transport, HardReset} from 'esptool-js';\nimport {discoverWithRecovery} from "+JSON.stringify(path.join(here,'discovery.mjs'))+";\n"+s;
  s=replaceOnce(s,'const client = new ImprovSerial(this.port, this.logger);','let client = new ImprovSerial(this.port, this.logger);');
  s=replaceOnce(s,'this._info = await client.initialize(timeout);',`this._info = await discoverWithRecovery({
    initialTimeout: timeout,
    connect: async wait => {
      client = new ImprovSerial(this.port, this.logger);
      const info = await client.initialize(wait);
      client.addEventListener('state-changed', () => this.requestUpdate());
      client.addEventListener('error-changed', () => this.requestUpdate());
      return info;
    },
    reset: async () => {
      const transport = new Transport(this.port);
      await transport.setDTR(false);
      await transport.setRTS(true);
      await sleep(100);
      await new HardReset(transport).reset();
    },
    pause: sleep,
    status: message => {this._aiedgeStatus=message;this.requestUpdate();},
    isPortBusy: error => error instanceof PortNotReady
  });
  this._aiedgeStatus=undefined;`);
  s=replaceOnce(s,'this._renderProgress("Connecting")','this._renderProgress(this._aiedgeStatus || "Connecting")');
  s=replaceOnce(s,'undeterminateLabel = "Wrapping up";','undeterminateLabel = this._aiedgeStatus || "Detecting Wi-Fi setup";');
  s=replaceOnce(s,'label="Installation complete!"','.label=${supportsImprov ? "Loader installed. Wi-Fi setup is ready." : "Loader installed, but Wi-Fi setup did not respond after one automatic restart. Open Logs & Console to diagnose."}');
  s=replaceOnce(s,'supportsImprov && this._installErase','supportsImprov');
  // Wording only: retain upstream erase-and-reinstall behavior and confirmation.
  if(s.split('Erase User Data').length!==4) throw new Error('Upstream erase label count changed');
  s=s.replaceAll('Erase User Data','Erase user data / reinstall');
  return {contents:s,loader:'js',resolveDir:path.dirname(args.path)};
 });
}}]});
// Retain upstream and bundled dependency licenses, not just minifier comments.
let notices='AIEdge bundles ESP Web Tools 10.4.0 with the discovery modification in tools/build.mjs.\nUpstream: https://github.com/esphome/esp-web-tools\nBrowser flashing remains upstream work. AIEdge does not claim authorship of bundled dependencies.\n\n';
async function visit(dir){for(const ent of await fs.readdir(dir,{withFileTypes:true})){
 if(!ent.isDirectory()||ent.name==='.bin'||ent.name==='@esbuild'||ent.name==='esbuild')continue;
 const sub=path.join(dir,ent.name);
 if(ent.name.startsWith('@')){await visit(sub);continue;}
 try {const pkg=JSON.parse(await fs.readFile(path.join(sub,'package.json'),'utf8'));
 notices+='\n=== '+pkg.name+' '+pkg.version+' ('+(pkg.license||'see license')+') ===\n';
 for(const file of await fs.readdir(sub)){if(/^(license|licence|copying|notice)([.\-]|$)/i.test(file))notices+=file+'\n'+await fs.readFile(path.join(sub,file),'utf8')+'\n';}
 }catch(error){throw new Error('Could not preserve license for '+sub+': '+error.message);}
}}
await visit(deps);await fs.writeFile(path.join(output,'NOTICES.txt'),notices);
console.log('Built pinned installer with one reset-and-discovery retry.');
