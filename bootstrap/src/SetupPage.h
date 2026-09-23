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

.password-field{position:relative}.password-field input{padding-right:56px}.password-field #show{position:absolute;right:2px;top:10px;width:44px;height:44px;margin:0;padding:10px;border:0;background:transparent;color:var(--ae-ink);display:grid;place-items:center}.password-field #show:focus-visible{outline:2px solid var(--ae-accent)}main{background:var(--ae-surface)}.hint{color:var(--ae-muted)}.aiedge-theme-picker{justify-content:flex-end}#detail{overflow-wrap:anywhere}
body{max-width:560px;margin:32px auto;padding:16px;line-height:1.5}
main{padding:28px;border-radius:16px}
p{margin:0}p:empty{display:none}
.aiedge-header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:24px}
h1{margin:0;font-size:30px;line-height:1.2;letter-spacing:-.5px}
.aiedge-header .aiedge-theme-picker{margin:0;gap:8px;font-size:13px}
.connection{margin-bottom:24px}.connection #intro{font-weight:600}.connection #connection{margin-top:4px}
.download-status{margin-top:24px}#state{font-weight:600}#detail:not(:empty){margin-top:6px;color:var(--ae-muted)}
progress{display:block;width:100%;height:10px;margin:14px 0 10px;accent-color:var(--ae-accent)}
.download-details{display:grid;gap:4px;font-variant-numeric:tabular-nums}
#retry,#refresh{margin:16px 0 0}
.setup-footer{border-top:1px solid var(--ae-line);margin-top:24px;padding-top:16px;display:grid;gap:4px}
#device-address{white-space:nowrap}
@media(max-width:440px){body{margin:8px auto;padding:12px}main{padding:20px}.aiedge-header{gap:10px;flex-wrap:nowrap}h1{font-size:26px}.aiedge-header .aiedge-theme-picker{margin:0;font-size:12px}.aiedge-theme-picker select{max-width:100px}}
</style></head>
<body><main><header class="aiedge-header"><h1>AIEdge</h1></header><section class="connection"><p id="intro">Checking installation status…</p>
<p id="connection" class="hint"></p></section><form id="wifi" hidden><fieldset id="fields" style="border:0;padding:0;margin:0"><label for="networks">Wi-Fi network</label><select id="networks"><option value="">Select a network</option><option value="manual">Hidden network / enter manually</option></select>
<button class="secondary" id="scan" type="button">Rescan networks</button><p id="scan-status" class="hint" role="status">Looking for nearby 2.4 GHz networks…</p>
<div id="manual" hidden><label for="ssid">Wi-Fi name</label><input id="ssid" maxlength="31" autocomplete="off" autocapitalize="none" spellcheck="false"></div>
<label for="password">Password</label><div class="password-field"><input id="password" type="password" maxlength="63" autocomplete="new-password" autocapitalize="none" spellcheck="false"><button id="show" type="button" aria-label="Show password" title="Show password"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M2 12Q6 5 12 5Q18 5 22 12Q18 19 12 19Q6 19 2 12Z"></path><circle cx="12" cy="12" r="3"></circle><path id="eye-slash" style="display:none" d="M3 3L21 21"></path></svg></button></div>
<button id="go" type="submit">Connect to Wi-Fi</button></fieldset></form>
<section class="download-status"><p id="state" role="status">Checking device…</p><p id="detail" class="hint"></p><progress id="progress" max="100" value="0" aria-label="Package download"></progress>
<div class="download-details"><p id="transfer" class="hint"></p><p id="speed" class="hint"></p></div><button id="retry" hidden>Retry download to device and install</button>
<button id="refresh" type="button" class="secondary" hidden>Refresh device page</button></section>
<footer class="setup-footer"><p class="hint">Keep AIEdge powered during installation.</p><p class="hint">Device address: <a id="device-address" hidden></a><span id="address-pending">waiting for network details</span></p><p class="hint"><a href="/debug-log" download="aiedge-loader-debug.txt">Download debug log</a> · Current boot only. If the device stops responding, use USB Logs &amp; Console.</p></footer></main>
<script>
const $=id=>document.getElementById(id), state=$('state'), fields=$('fields'), networks=$('networks'), password=$('password');
let busy=true, scanning=false, started=false, choices=[], expectedHostname='', openingApplication=false;
// DOWNLOAD_FORMAT_BEGIN: shared with the host-side formatting checks.
function sizeText(bytes){return bytes>=1000000?(bytes/1000000).toFixed(2)+' MB':bytes>=1000?(bytes/1000).toFixed(1)+' kB':Math.round(bytes)+' B';}
function timeText(seconds){const n=Math.ceil(seconds);return n>=3600?Math.floor(n/3600)+' hr '+Math.ceil(n%3600/60)+' min':n>=60?Math.floor(n/60)+' min '+n%60+' sec':n+' sec';}
function transferText(s){
 const bytes=Number(s.downloaded_bytes),total=Number(s.total_bytes);
 if(!Number.isFinite(bytes)||!Number.isFinite(total)||total<=0)return {bytes:'',speed:''};
 const count=Math.max(0,Math.min(bytes,total));
 const progress=count===total?100:Math.min(99,Math.round(100*count/total));
 const amount=sizeText(count)+' / '+sizeText(total)+' ('+progress+'%)';
 if(s.phase!==2)return {bytes:count?amount:'',speed:''};
 const rate=Number(s.average_bytes_per_second);
 let speed=rate>0&&Number(s.elapsed_seconds)>=3?'Average speed: '+sizeText(rate)+'/s':'Calculating download speed…';
 if(s.waiting_for_data)speed+=' · Waiting for data; time remaining unavailable';
 else if(Number.isFinite(s.remaining_seconds)&&s.remaining_seconds>=0&&count<total)speed+=' · About '+timeText(s.remaining_seconds)+' remaining';
 if(count===total)speed='Download received. Checking package…';
 return {bytes:amount,speed};
}
// DOWNLOAD_FORMAT_END
async function deviceFetch(url,options={}){const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),8000);try{const r=await fetch(url,{...options,signal:controller.signal});const body=await r.arrayBuffer();return new Response(body,{status:r.status,statusText:r.statusText,headers:r.headers});}finally{clearTimeout(timer);}}
$('refresh').onclick=()=>location.reload();
async function openApplicationIfReady(){
 try{
  const response=await deviceFetch('/sysinfo',{cache:'no-store'});
  if(!response.ok)return false;
  const data=await response.json(),info=Array.isArray(data)&&data[0];
  if(!info||!/^aiedge-[0-9a-f]{6}$/.test(info.hostname||'')||
     (expectedHostname&&info.hostname!==expectedHostname)||
     typeof info.gitrevision!=='string'||!info.gitrevision||typeof info.html!=='string')return false;
  openingApplication=true;state.textContent='Installation complete. Opening AIEdge…';
  location.replace('/?installed='+Date.now());return true;
 }catch(e){return false;}
}
function controls(){fields.disabled=busy;$('scan').disabled=busy||scanning;$('go').disabled=busy||scanning;}
function selection(){const manual=networks.value==='manual';$('manual').hidden=!manual;$('ssid').required=manual;const ap=choices[Number(networks.value)];const open=!manual&&networks.value!==''&&ap&&ap.open;password.disabled=!!open;$('show').disabled=!!open;password.required=!open;password.minLength=open?0:8;if(open)password.value='';}
$('show').onclick=()=>{const show=password.type==='password';password.type=show?'text':'password';const label=show?'Hide password':'Show password';$('show').setAttribute('aria-label',label);$('show').title=label;$('eye-slash').style.display=show?'':'none';};networks.onchange=selection;
async function scan(){if(busy||scanning)return;scanning=true;controls();$('scan-status').textContent='Scanning nearby 2.4 GHz networks…';try{const r=await deviceFetch('/scan',{method:'POST'});if(!r.ok)throw Error(await r.text());}catch(e){scanning=false;controls();$('scan-status').textContent='Could not scan. Try Rescan or enter the network manually.';}}
$('scan').onclick=scan;
function renderNetworks(items){const previous=choices[Number(networks.value)]?.ssid, manual=networks.value==='manual';const seen=new Set();choices=items.sort((a,b)=>b.rssi-a.rssi).filter(n=>{if(seen.has(n.ssid))return false;seen.add(n.ssid);return true;});networks.replaceChildren(new Option('Select a network',''));
choices.forEach((n,i)=>{const strength=n.rssi>=-60?'Strong':n.rssi>=-75?'Good':'Weak';const supported=n.supported&&new TextEncoder().encode(n.ssid).length<=31&&!/["\r\n]/.test(n.ssid);const option=new Option(`${n.ssid} · ${strength}${n.open?' · Open':''}${supported?'':' · Not supported'}`,String(i));option.disabled=!supported;networks.add(option);if(n.ssid===previous&&supported)networks.value=String(i);});networks.add(new Option('Hidden network / enter manually','manual'));if(manual)networks.value='manual';selection();$('scan-status').textContent=choices.length?`${choices.length} networks found. 2.4 GHz Wi-Fi only.`:'No networks found. Rescan or enter the name manually.';}
$('wifi').onsubmit=async e=>{e.preventDefault();if(busy||scanning)return;const manual=networks.value==='manual';const ap=choices[Number(networks.value)];const name=manual?$('ssid').value:(networks.value!==''&&ap?ap.ssid:'');if(!name){state.textContent='Choose a Wi-Fi network first.';return;}if(new TextEncoder().encode(name).length>31||/["\r\n]/.test(name)||/["\r\n]/.test(password.value)){state.textContent='This build supports names up to 31 bytes, without quotes or line breaks.';return;}busy=true;controls();state.textContent='Connecting to Wi-Fi…';try{const r=await deviceFetch('/wifi',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:name,password:password.disabled?'':password.value})});if(!r.ok){state.textContent=await r.text();busy=false;controls();}}catch(e){state.textContent='Connection interrupted. Checking device status…';}};
$('retry').onclick=async()=>{busy=true;controls();$('retry').disabled=true;try{const r=await deviceFetch('/install',{method:'POST'});if(!r.ok)state.textContent=await r.text();}catch(e){state.textContent='Connection interrupted. Checking device…';}};
async function poll(){try{const r=await deviceFetch('/status',{cache:'no-store'});if(!r.ok)throw Error();const s=await r.json();if(/^aiedge-[0-9a-f]{6}$/.test(s.hostname||'')){expectedHostname=s.hostname;const address=$('device-address');address.textContent=s.hostname+'.local';address.href='http://'+s.hostname+'.local';address.hidden=false;$('address-pending').hidden=true;}busy=s.phase>0&&s.phase!==7;state.textContent=s.message;$('progress').value=s.progress;const transfer=transferText(s);$('transfer').textContent=transfer.bytes;$('speed').textContent=transfer.speed;$('refresh').hidden=true;controls();
$('wifi').hidden=busy||s.wifi_connected;
$('intro').textContent=s.wifi_connected?'Wi-Fi connected':busy?'Reconnecting and continuing installation…':'Choose your home Wi-Fi. You can start the download once connected.';
$('connection').textContent=s.wifi_saved?'Settings saved. AIEdge will reconnect automatically.':'';
$('detail').textContent=s.detail||'';
$('retry').hidden=!s.can_install;$('retry').disabled=busy;$('retry').textContent=s.phase===7?'Download to device and install ('+sizeText(s.total_bytes)+')':'Retry download to device and install';$('progress').hidden=s.phase===7||s.phase===0||s.phase===1||s.phase===6;
if(!started&&!busy&&!s.wifi_connected){started=true;await scan();}if(scanning){const n=await deviceFetch('/networks',{cache:'no-store'});if(!n.ok)throw Error();const result=await n.json();if(result.state!==1){scanning=false;controls();if(result.state===2)renderNetworks(result.networks);else $('scan-status').textContent='Scan failed. Rescan or enter the network manually.';}}}catch(e){if(await openApplicationIfReady())return;state.textContent='Device not responding. Retrying automatically. Keep it powered and stay on its network.';$('speed').textContent='Connection lost — speed and time remaining unavailable.';$('refresh').hidden=false;}finally{if(!openingApplication)setTimeout(poll,2000);}}
controls();poll();
</script></body></html>)HTML";
