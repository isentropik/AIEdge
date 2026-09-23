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
await build({entryPoints:[path.join(here,'entry.mjs')],outfile:path.join(output,'esp-web-tools-aiedge.js'),bundle:true,format:'esm',target:'es2022',minify:true,legalComments:'eof',banner:{js:'/* ESP Web Tools 10.4.0, ESPHome / Open Home Foundation, Apache-2.0. AIEdge setup and USB speed changes; see NOTICES.txt. */'},plugins:[{name:'aiedge-discovery',setup(b){
 b.onLoad({filter:/esp-web-tools[\\/]dist[\\/]flash\.js$/},async args=>{
  let s=await fs.readFile(args.path,'utf8');
  s="import {flashWithSpeedFallback} from "+JSON.stringify(path.join(here,'flash-speed.mjs'))+";\n"+s;
  s=replaceOnce(s,'export const flash = async (onEvent, port, manifestPath, manifest, eraseFirst) => {',
    'const flashOnce = async (onEvent, port, manifestPath, manifest, eraseFirst, baudrate) => {');
  s=replaceOnce(s,'baudrate: 115200,','baudrate,');
  s+='\nexport const flash = (onEvent, port, manifestPath, manifest, eraseFirst) => flashWithSpeedFallback((events, baud, erase) => flashOnce(events, port, manifestPath, manifest, erase, baud), onEvent, eraseFirst);\n';
  return {contents:s,loader:'js',resolveDir:path.dirname(args.path)};
 });
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
  s=replaceOnce(s,'this._renderProgress("Preparing installation")','this._renderProgress(this._installState?.message || "Preparing installation")');
  s=replaceOnce(s,'undeterminateLabel = "Wrapping up";','undeterminateLabel = this._aiedgeStatus || "Detecting Wi-Fi setup";');
  s=replaceOnce(s,'label="Installation complete!"','.label=${supportsImprov ? "Loader installed. Wi-Fi setup is ready." : "Loader installed, but Wi-Fi setup did not respond after one automatic restart. Open Logs & Console to diagnose."}');
  s=replaceOnce(s,'supportsImprov && this._installErase','supportsImprov');
  // Wording only: retain upstream erase-and-reinstall behavior and confirmation.
  s=replaceOnce(s,'case 254 /* ImprovSerialErrorState.TIMEOUT */:',
    'case 255: error = "Device is busy or the Wi-Fi request failed. Go back and reopen Wi-Fi setup to retry."; break;\n                case 254 /* ImprovSerialErrorState.TIMEOUT */:');
  if(s.split('Erase User Data').length!==4) throw new Error('Upstream erase label count changed');
  s=s.replaceAll('Erase User Data','Erase user data / reinstall');
  // An accessible eye button in the field toggles visibility without submitting.
  s=replaceOnce(s,`                ></ew-filled-text-field>
              \x60
                : ""}
        </div>`, `                >
                  <ew-icon-button slot="trailing-icon" type="button" aria-label="Show password" title="Show password"
                    @click=\x24{(event) => {
                      const field = this.shadowRoot.querySelector('ew-filled-text-field[name="password"]');
                      if (!field) return;
                      const show = field.type === "password";
                      field.type = show ? "text" : "password";
                      const button = event.currentTarget;
                      const label = show ? "Hide password" : "Show password";
                      button.setAttribute("aria-label", label); button.title = label;
                      button.querySelector(".eye-slash").style.display = show ? "" : "none";
                    }}>
                    <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
                      <path d="M2 12Q6 5 12 5Q18 5 22 12Q18 19 12 19Q6 19 2 12Z"></path><circle cx="12" cy="12" r="3"></circle>
                      <path class="eye-slash" style="display:none" d="M3 3L21 21"></path>
                    </svg>
                  </ew-icon-button>
                </ew-filled-text-field>
              \x60
                : ""}
        </div>`);
  return {contents:s,loader:'js',resolveDir:path.dirname(args.path)};
 });
}}]});
// Retain upstream and bundled dependency licenses, not just minifier comments.
let notices='AIEdge bundles ESP Web Tools 10.4.0 with faster USB flashing and one slow fallback, USB discovery recovery, erase-label wording, readable Wi-Fi request errors and a password visibility eye button in tools/build.mjs.\nUpstream: https://github.com/esphome/esp-web-tools\nBrowser flashing remains upstream work. AIEdge does not claim authorship of bundled dependencies.\n\n';
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
