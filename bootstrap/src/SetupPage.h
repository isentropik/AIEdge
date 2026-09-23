#pragma once
static const char page[]=R"HTML(<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AIEdge setup</title><script>/* AIEdge theme preference. Local to this browser and device address. */
(function(){
 const key='aiedge-device-theme';let mode='system';
 const system=window.matchMedia('(prefers-color-scheme: dark)');
 try{const saved=localStorage.getItem(key);if(['light','dark'].includes(saved))mode=saved;}catch(e){}
 function apply(){document.documentElement.dataset.aiedgeTheme=mode==='system'?(system.matches?'dark':'light'):mode;document.querySelectorAll('[data-aiedge-theme-select]').forEach(s=>s.value=mode);}
 apply();system.addEventListener('change',apply);
 window.addEventListener('storage',e=>{if(e.key===key){mode=['light','dark'].includes(e.newValue)?e.newValue:'system';apply();}});
 window.addEventListener('aiedge-theme-change',e=>{mode=e.detail;apply();});
 document.addEventListener('DOMContentLoaded',()=>{
  if(window.top!==window.self)return;
  const label=document.createElement('label');label.className='aiedge-theme-picker';label.textContent='Theme ';
  const select=document.createElement('select');select.dataset.aiedgeThemeSelect='';select.setAttribute('aria-label','Theme');
  for(const value of ['system','light','dark'])select.add(new Option(value[0].toUpperCase()+value.slice(1),value));
  select.value=mode;label.append(select);
  const header=document.querySelector('.aiedge-header')||document.querySelector('main');
  if(header)header.append(label);else document.body.prepend(label);
  select.addEventListener('change',()=>{mode=select.value;try{if(mode==='system')localStorage.removeItem(key);else localStorage.setItem(key,mode);}catch(e){}apply();document.querySelectorAll('iframe').forEach(frame=>{try{frame.contentWindow.dispatchEvent(new CustomEvent('aiedge-theme-change',{detail:mode}));}catch(e){}});});
 });
})();
</script>
<style>body{font:16px system-ui;background:#f3f7f8;color:#172a36;margin:24px auto;padding:16px;max-width:520px}main{background:white;padding:24px;border-radius:16px}input,select,button{box-sizing:border-box;width:100%;font:inherit;padding:12px;margin:8px 0 16px;border:1px solid #a5bac5;border-radius:8px}button{background:#006e69;color:white;cursor:pointer}button.secondary{background:white;color:#006e69}button:disabled{opacity:.5;cursor:wait}input[type=checkbox]{width:auto;margin-right:8px}.hint{font-size:.9rem;color:#4c626e}progress{width:100%}[hidden]{display:none!important}</style><style>/* AIEdge device themes; meter images and canvas pixels are not recolored. */
:root{color-scheme:light;--ae-ink:#172a36;--ae-muted:#526876;--ae-line:#a5bac5;--ae-accent:#006e69;--ae-surface:#fff;--ae-bg:#f3f7f8;--ae-hover:#e4f2ef;--ae-expert:#ffefef}
:root[data-aiedge-theme=dark]{color-scheme:dark;--ae-ink:#e8f0f4;--ae-muted:#b0c4ce;--ae-line:#526874;--ae-accent:#7cddd0;--ae-surface:#1b2931;--ae-bg:#101b22;--ae-hover:#29423f;--ae-expert:#422c35}
html,body{background:var(--ae-bg);color:var(--ae-ink)}
a{color:var(--ae-accent)}
.aiedge-theme-picker{display:flex;align-items:center;gap:8px;font:14px system-ui;color:var(--ae-ink);margin:8px 0}
.aiedge-header .aiedge-theme-picker{margin-left:auto;flex-shrink:0}
.aiedge-theme-picker select{width:auto!important;margin:0!important;min-height:36px;padding:5px 10px;border:1px solid var(--ae-line);border-radius:7px;background:var(--ae-surface);color:var(--ae-ink)}
:root[data-aiedge-theme=dark] input:not([type=range]):not([type=checkbox]):not([type=radio]),:root[data-aiedge-theme=dark] select,:root[data-aiedge-theme=dark] textarea,:root[data-aiedge-theme=dark] button{background-color:var(--ae-surface);color:var(--ae-ink);border-color:var(--ae-line)}
:root[data-aiedge-theme=dark] .expert{background-color:var(--ae-expert)}
:root[data-aiedge-theme=dark] input:invalid,:root[data-aiedge-theme=dark] input:out-of-range{background-color:#512c31;border-color:#ff8e89}
:root[data-aiedge-theme=dark] .aiedge-header,:root[data-aiedge-theme=dark] .aiedge-credit,:root[data-aiedge-theme=dark] .aiedge-shell #Version,:root[data-aiedge-theme=dark] .aiedge-shell .menu,:root[data-aiedge-theme=dark] .aiedge-shell .menu li a,:root[data-aiedge-theme=dark] .aiedge-shell .menu li ul,:root[data-aiedge-theme=dark] .aiedge-shell .menu li:hover li a{background:var(--ae-surface);color:var(--ae-ink)}
:root[data-aiedge-theme=dark] .aiedge-shell .menu li a:hover,:root[data-aiedge-theme=dark] .aiedge-shell .menu li:hover>a{background:var(--ae-hover);color:var(--ae-accent)}
:root[data-aiedge-theme=dark] .aiedge-mark{color:#102a26}
@media(max-width:600px){.aiedge-header{flex-wrap:wrap}.aiedge-header .aiedge-theme-picker{margin-left:0}}

main{background:var(--ae-surface)}.hint{color:var(--ae-muted)}.aiedge-theme-picker{justify-content:flex-end}#detail{overflow-wrap:anywhere}</style></head>
<body><main><h1>AIEdge</h1><p id="intro">Checking installation status…</p>
<p id="connection" class="hint"></p><button id="retry" hidden>Retry download and installation</button><form id="wifi" hidden><fieldset id="fields" style="border:0;padding:0;margin:0"><label for="networks">Wi-Fi network</label><select id="networks"><option value="">Select a network</option><option value="manual">Hidden network / enter manually</option></select>
<button class="secondary" id="scan" type="button">Rescan networks</button><p id="scan-status" class="hint" role="status">Looking for nearby 2.4 GHz networks…</p>
<div id="manual" hidden><label for="ssid">Wi-Fi name</label><input id="ssid" maxlength="31" autocomplete="off" autocapitalize="none" spellcheck="false"></div>
<label for="password">Password</label><input id="password" type="password" maxlength="63" autocomplete="new-password" autocapitalize="none" spellcheck="false"><label><input id="show" type="checkbox">Show password</label>
<button id="go" type="submit">Connect and install</button></fieldset></form>
<p id="detail" class="hint"></p><p id="state" role="status">Checking device…</p><progress id="progress" max="100" value="0" aria-label="Package download"></progress>
<p class="hint">Keep AIEdge powered during installation. Once installed, open <a href="http://aiedge.local">aiedge.local</a>.</p></main>
<script>
const $=id=>document.getElementById(id), state=$('state'), fields=$('fields'), networks=$('networks'), password=$('password');
let busy=true, scanning=false, started=false, choices=[];
function controls(){fields.disabled=busy;$('scan').disabled=busy||scanning;$('go').disabled=busy||scanning;}
function selection(){const manual=networks.value==='manual';$('manual').hidden=!manual;$('ssid').required=manual;const ap=choices[Number(networks.value)];const open=!manual&&networks.value!==''&&ap&&ap.open;password.disabled=!!open;password.required=!open;password.minLength=open?0:8;if(open)password.value='';}
$('show').onchange=()=>{password.type=$('show').checked?'text':'password';};networks.onchange=selection;
async function scan(){if(busy||scanning)return;scanning=true;controls();$('scan-status').textContent='Scanning nearby 2.4 GHz networks…';try{const r=await fetch('/scan',{method:'POST'});if(!r.ok)throw Error(await r.text());}catch(e){scanning=false;controls();$('scan-status').textContent='Could not scan. Try Rescan or enter the network manually.';}}
$('scan').onclick=scan;
function renderNetworks(items){const previous=choices[Number(networks.value)]?.ssid, manual=networks.value==='manual';const seen=new Set();choices=items.sort((a,b)=>b.rssi-a.rssi).filter(n=>{if(seen.has(n.ssid))return false;seen.add(n.ssid);return true;});networks.replaceChildren(new Option('Select a network',''));
choices.forEach((n,i)=>{const strength=n.rssi>=-60?'Strong':n.rssi>=-75?'Good':'Weak';const supported=n.supported&&new TextEncoder().encode(n.ssid).length<=31&&!/["\r\n]/.test(n.ssid);const option=new Option(`${n.ssid} · ${strength}${n.open?' · Open':''}${supported?'':' · Not supported'}`,String(i));option.disabled=!supported;networks.add(option);if(n.ssid===previous&&supported)networks.value=String(i);});networks.add(new Option('Hidden network / enter manually','manual'));if(manual)networks.value='manual';selection();$('scan-status').textContent=choices.length?`${choices.length} networks found. 2.4 GHz Wi-Fi only.`:'No networks found. Rescan or enter the name manually.';}
$('wifi').onsubmit=async e=>{e.preventDefault();if(busy||scanning)return;const manual=networks.value==='manual';const ap=choices[Number(networks.value)];const name=manual?$('ssid').value:(networks.value!==''&&ap?ap.ssid:'');if(!name){state.textContent='Choose a Wi-Fi network first.';return;}if(new TextEncoder().encode(name).length>31||/["\r\n]/.test(name)||/["\r\n]/.test(password.value)){state.textContent='This build supports names up to 31 bytes, without quotes or line breaks.';return;}busy=true;controls();state.textContent='Connecting to Wi-Fi…';try{const r=await fetch('/wifi',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:name,password:password.disabled?'':password.value})});if(!r.ok){state.textContent=await r.text();busy=false;controls();}}catch(e){state.textContent='Connection interrupted. Checking device status…';}};
$('retry').onclick=async()=>{busy=true;controls();$('retry').disabled=true;try{const r=await fetch('/retry',{method:'POST'});if(!r.ok)state.textContent=await r.text();}catch(e){state.textContent='Connection interrupted. Checking device…';}};
async function poll(){try{const r=await fetch('/status',{cache:'no-store'});if(!r.ok)throw Error();const s=await r.json();busy=s.phase>0;state.textContent=s.message;$('progress').value=s.progress;controls();
$('wifi').hidden=busy||s.wifi_connected;
$('intro').textContent=s.wifi_connected?'Wi-Fi is connected. Installation status is shown below.':busy?'Reconnecting and continuing installation…':'Choose your home Wi-Fi to download and install AIEdge.';
$('connection').textContent=s.wifi_saved?'Wi-Fi settings saved. The device will reconnect after a restart.':'';
$('detail').textContent=s.detail||'';
$('retry').hidden=!s.wifi_connected||busy||s.phase>=0||s.phase===-8;$('retry').disabled=busy;
if(!started&&!busy&&!s.wifi_connected){started=true;await scan();}if(scanning){const n=await fetch('/networks',{cache:'no-store'});if(!n.ok)throw Error();const result=await n.json();if(result.state!==1){scanning=false;controls();if(result.state===2)renderNetworks(result.networks);else $('scan-status').textContent='Scan failed. Rescan or enter the network manually.';}}}catch(e){state.textContent='Device not responding. Keep the device powered and stay on its network. It may be restarting after installation.';}finally{setTimeout(poll,2000);}}
controls();poll();
</script></body></html>)HTML";
