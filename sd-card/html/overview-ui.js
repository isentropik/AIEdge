/* Read-only overview. No forced captures or streams; five-minute refresh. */
(()=>{const el=id=>document.getElementById(id);let running=false;const preview=location.hostname==='127.0.0.1'&&location.port==='8878';
function parse(text){return text.trim().split(/[\r\n]+/).filter(Boolean).map(row=>{const p=row.split('\t');return {name:p.length>1?p.shift():'Meter',value:p.join('\t')||row};});}
function registerDisplay(name,value,raw){
 // Display-only: retain the leading places present in the raw main register.
 if(name.toLowerCase()!=='main'||!/^\d+(?:\.\d+)?$/.test(value)||!/^0\d+(?:\.\d+)?$/.test(raw||''))return value;
 const parts=value.split('.');parts[0]=parts[0].padStart(raw.split('.')[0].length,'0');return parts.join('.');
}
async function read(path){const r=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(7000)});if(!r.ok)throw Error('Device response unavailable');return r.text();}
function message(text,state){el('connection').textContent=text;el('connection').dataset.state=state;}
function cards(rows){const list=el('readings');list.replaceChildren();for(const row of rows){const card=document.createElement('article');card.className='ae-reading';const name=document.createElement('p');name.className='ae-eyebrow';name.textContent=row.name+(preview?' · EXAMPLE VALUE':' · CURRENT READING');const value=document.createElement('div');value.className='ae-reading-value';value.textContent=row.value||'—';const note=document.createElement('p');note.textContent=preview?'Example only · not read from the image':'As reported by the device';card.append(name,value,note);list.append(card);}}
async function refresh(){if(running)return;running=true;el('refresh').disabled=true;let failed=0;let rows=[];let details={};
try{const data=JSON.parse(await read('/sysinfo'));const info=Array.isArray(data)?data[0]:data;
 if(info.camera_available===false){
  cards([{name:'Meter reading',value:'Unavailable'}]);
  document.querySelector('#readings article p:last-child').textContent='Camera unavailable';
  message('Camera unavailable. Connect the camera with power off, then restart. Settings and maintenance remain accessible.','error');
  el('process').textContent='Paused — camera unavailable';
  el('temperature').textContent=info.cputemp?info.cputemp+' °C':'Unavailable';
  for(const [id,path,suffix] of [['signal','/rssi',' dBm'],['uptime','/uptime','']]){try{el(id).textContent=(await read(path)).trim()+suffix;}catch(e){el(id).textContent='Unavailable';}}
  el('capture').hidden=true;el('image-empty').hidden=false;
  document.querySelector('#image-empty strong').textContent='Camera unavailable';
  document.querySelector('#image-empty span').textContent='Image capture and recognition are paused.';
  el('reading-details').replaceChildren();
  el('checked').textContent='Device connected. Last checked '+new Date().toLocaleTimeString();
  el('refresh').disabled=false;running=false;return;
 }
}catch(e){/* Older firmware may not expose camera capability; retain existing read-only handling. */}
try{rows=parse(await read('/value?all=true&type=value'));if(!rows.length)throw Error();cards(rows);}catch(e){failed++;message('Could not read the device. Displayed values may be stale.','error');}
for(const [id,path,suffix] of [['process','/statusflow',''],['signal','/rssi',' dBm'],['temperature','/cpu_temperature',' °C'],['uptime','/uptime','']]){try{el(id).textContent=(await read(path)).trim()+suffix;}catch(e){el(id).textContent='Unavailable';failed++;}}
for(const kind of ['prevalue','raw','error']){try{details[kind]=Object.fromEntries(parse(await read('/value?all=true&type='+kind)).map(x=>[x.name,x.value]));}catch(e){details[kind]={};failed++;}}
if(rows.length){cards(rows.map(row=>({...row,value:registerDisplay(row.name,row.value,details.raw[row.name])})));el('reading-details').replaceChildren();for(const row of rows){const tr=document.createElement('tr');for(const value of [row.name,registerDisplay(row.name,details.prevalue[row.name]||'—',details.raw[row.name]),details.raw[row.name]||'—',details.error[row.name]||'Unavailable']){const td=document.createElement('td');td.textContent=value;tr.append(td);}el('reading-details').append(tr);}}
if(!failed)message(preview?'Design preview · example values do not correspond to the archived image':'Readings received · refreshes every 5 minutes','ok');else if(rows.length)message('Some device details are unavailable.','error');
el('checked').textContent='Last checked '+new Date().toLocaleTimeString()+'. This is the retrieval time, not the image capture time.';
const img=el('capture');img.onload=()=>{img.hidden=false;el('image-empty').hidden=true;};img.onerror=()=>{img.hidden=true;el('image-empty').hidden=false;};img.src='/img_tmp/alg_roi.jpg?timestamp='+Date.now();el('refresh').disabled=false;running=false;}
if(preview){document.querySelector('.ae-camera-panel h2').textContent='Archived meter image';document.querySelector('.ae-camera-panel .ae-chip').textContent='Not live';document.querySelector('.ae-panel-foot span').textContent='This archived image is not the source of the example values above.';}
el('refresh').onclick=refresh;refresh();setInterval(()=>{if(!document.hidden)refresh();},300000);
})();
