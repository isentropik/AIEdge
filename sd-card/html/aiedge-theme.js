/* AIEdge theme preference. Local to this browser and device address. */
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
  const header=document.querySelector('.aiedge-header, .ae-tool-header')||document.querySelector('main');
  if(header)header.append(label);else document.body.prepend(label);
  select.addEventListener('change',()=>{mode=select.value;try{if(mode==='system')localStorage.removeItem(key);else localStorage.setItem(key,mode);}catch(e){}apply();document.querySelectorAll('iframe').forEach(frame=>{try{frame.contentWindow.dispatchEvent(new CustomEvent('aiedge-theme-change',{detail:mode}));}catch(e){}});});
 });
})();
