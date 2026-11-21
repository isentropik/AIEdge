(() => {
'use strict';
const $ = id => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const number = new Intl.NumberFormat(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
function svg(tag, attrs = {}, text) {
  const node = document.createElementNS(svgNS,tag);
  for (const [k,v] of Object.entries(attrs)) node.setAttribute(k,v);
  if (text !== undefined) node.textContent = text;
  return node;
}
function clock(t, zone, exact=false) {
  return new Date(t).toLocaleTimeString(undefined,{timeZone:zone,hour:'numeric',minute:'2-digit',
    ...(exact ? {second:'2-digit',timeZoneName:'short'} : {})});
}
function chart(kind) {
  const host = $(kind+'-curve'), readout = $(kind+'-readout'), isDay = kind === 'day';
  const graphic = svg('svg',{'aria-hidden':'true'});
  host.append(graphic);
  let model, chosen, atX, atY;
  function pick(index) {
    if (!model?.points.length) return;
    const i = Math.max(0,Math.min(index,model.points.length-1)), p = model.points[i];
    chosen = p[0];
    const amounts = number.format(p[2])+'–'+number.format(p[3])+' ft³';
    const time = isDay ? clock(p[0],model.zone,true) : clock(p[5],model.zone)+' – '+clock(p[0],model.zone,true);
    const value = isDay ? number.format(p[1])+' ft³ estimated · '+amounts : amounts;
    readout.textContent = time+' · '+value;
    host.setAttribute('aria-valuenow',i);
    host.setAttribute('aria-valuetext',readout.textContent);
    const cursor=graphic.querySelector('.plot-cursor');
    if(cursor) {
      cursor.setAttribute('transform','translate('+atX(chosen)+' 0)');
      cursor.querySelectorAll('circle').forEach((dot,j)=>dot.setAttribute('cy',atY(p[isDay?1:j+2])));
    }
  }
  function draw() {
    if (!model?.points.length || !host.clientWidth) return;
    const {groups,points,start,zone} = model;
    const w=host.clientWidth, h=isDay ? (w<440?175:205) : (w<440?144:156);
    const left=36,right=w-12,top=12,bottom=h-27;
    const peak=Math.max(0,...points.map(p=>p[3]));
    const raw=(peak||1)/3, unit=10**Math.floor(Math.log10(raw));
    const step=([1,2,2.5,5,10].find(v=>v*unit>=raw)||10)*unit;
    const ceiling=Math.max(step,Math.ceil(peak/step)*step);
    const end=points.at(-1)[0], span=Math.max(1,end-start);
    const x=t=>left+(right-left)*(t-start)/span, y=v=>bottom-(bottom-top)*v/ceiling;
    atX=x; atY=y;
    graphic.setAttribute('viewBox','0 0 '+w+' '+h);
    graphic.style.height=h+'px';
    const nodes=[];
    for(let i=0;i<=Math.round(ceiling/step);i++){
      const v=i*step, pos=y(v);
      nodes.push(svg('line',{x1:left,x2:right,y1:pos,y2:pos,class:'plot-grid'}),svg('text',{x:left-8,y:pos+4,'text-anchor':'end'},Number(v.toPrecision(6)).toLocaleString()));
    }
    const coords=(p,k)=>x(p[0]).toFixed(2)+' '+y(p[k]).toFixed(2);
    const line=(g,k)=>'M'+g.map(p=>coords(p,k)).join(' L');
    for(const g of groups){
      nodes.push(svg('path',{d:line(g,3)+' L'+[...g].reverse().map(p=>coords(p,2)).join(' L')+' Z',class:'plot-band'}));
      for(const [k,cls] of isDay?[[1,'plot-estimate']]:[[2,'plot-estimate'],[3,'plot-upper']]){
        nodes.push(svg('path',{d:line(g,k),class:cls}));
        const dots=!isDay||g.length===1?g:[g.at(-1)];
        for(const p of dots) nodes.push(svg('circle',{cx:x(p[0]),cy:y(p[k]),r:isDay?2.6:4,class:cls+'-dot'}));
      }
    }
    const tickTimes=isDay?[start,...[.333,.667].map(f=>{
      const hour=3600000;
      return start+Math.round(span*f/hour)*hour;
    }).filter(t=>t>start+span*.12 && t<end-span*.12),end]:points.map(p=>p[0]);
    const ticks=[...new Set(tickTimes)];
    ticks.forEach((t,i)=>{
      let label=clock(t,zone);
      if(isDay && span<120000)label=new Date(t).toLocaleTimeString(undefined,{timeZone:zone,hour:'numeric',minute:'2-digit',second:'2-digit'});
      else if(isDay && w<440 && !i)label='Midnight';
      else if(isDay && w<440 && i<ticks.length-1)label=label.replace(':00','');
      nodes.push(svg('text',{x:x(t),y:h-6,'text-anchor':i===0?'start':i===ticks.length-1?'end':'middle'},label));
    });
    const cursor=svg('g',{class:'plot-cursor'});
    cursor.append(svg('line',{x1:0,x2:0,y1:top,y2:bottom}));
    for(const cls of isDay?['plot-estimate-dot']:['plot-estimate-dot','plot-upper-dot'])cursor.append(svg('circle',{cx:0,r:4.3,class:cls}));
    nodes.push(cursor);
    graphic.replaceChildren(...nodes);
    const i=chosen==null?-1:points.findIndex(p=>p[0]===chosen);
    pick(i<0 ? points.length-1 : i);
  }
  function locate(e) {
    if(!model || !atX)return;
    const px=e.clientX-host.getBoundingClientRect().left;
    let best=0;
    model.points.forEach((p,i)=>{if(Math.abs(atX(p[0])-px)<Math.abs(atX(model.points[best][0])-px))best=i;});
    pick(best);
  }
  host.addEventListener('pointerdown',locate);
  host.addEventListener('pointermove',e=>{if(e.pointerType==='mouse'||e.buttons)locate(e);});
  host.addEventListener('keydown',e=>{
    if(!model)return;
    const i=model.points.findIndex(p=>p[0]===chosen);
    const next={ArrowLeft:i-1,ArrowRight:i+1,Home:0,End:model.points.length-1}[e.key];
    if(next!==undefined){e.preventDefault();pick(next);}
  });
  new ResizeObserver(draw).observe(host);
  return function update(groups, start, zone, key, empty) {
    if(!groups?.length){
      model=null; chosen=null; graphic.replaceChildren(); host.hidden=true;
      readout.textContent=empty||''; return;
    }
    if(model?.key===key)return;
    if(!model || chosen===model.points.at(-1)[0])chosen=null;
    model={groups,points:groups.flat(),start,zone,key};
    host.hidden=false; host.tabIndex=0;
    host.setAttribute('role','slider');
    host.setAttribute('aria-label',isDay?'Inspect cumulative gas use by measurement time':'Inspect 15-minute usage by interval end');
    host.setAttribute('aria-valuemin','0');host.setAttribute('aria-valuemax',model.points.length-1);
    draw();
  };
}
const drawDay=chart('day'), drawHour=chart('hour');
let identity='', saved=null, generation=0, due=0, pending=false, latest=null;
function showDay(){
  const groups=saved?.groups?.filter(g=>g.length) || [];
  if(!groups.length){
    const message=!latest?'Waiting for a supported full-day reading':saved?.status==='unavailable'?'Daily history could not be loaded':saved?.status==='ready'?'No matching readings in Home Assistant history':'Loading today’s saved readings…';
    drawDay(null,null,null,null,message);return;
  }
  const cutoff=Date.parse(latest.through.captured_at);
  const visible=groups.map(g=>g.filter(p=>p[0]<=cutoff && p[4]<=latest.through.event_id)).filter(g=>g.length);
  if(!visible.length){drawDay(null,null,null,null,'Waiting for matching measurement times');return;}
  const last=visible.at(-1).at(-1);
  $('day-history-status').textContent=saved.status==='unavailable'?'History refresh delayed':'';
  drawDay(visible,saved.midnight,saved.zone,identity+'|'+last[4]+'|'+saved.revision);
}
async function day(daily){
  const key=daily?.before&&daily.after&&daily.through ? JSON.stringify([daily.day,daily.timezone,daily.through.camera,daily.through.format_id,
    daily.before.source_sha256,daily.after.source_sha256,daily.before.event_id,daily.before.captured_at,daily.after.event_id,daily.after.captured_at]) : '';
  if(key!==identity){identity=key;generation++;saved=null;pending=false;due=0;$('day-history-status').textContent='';}
  latest=daily;
  if(!key||pending||Date.now()<due){showDay();return;}
  const current=generation;pending=true; showDay();
  try{
    const res=await fetch('api/gas-trend',{cache:'no-store',signal:AbortSignal.timeout(6000)});
    if(!res.ok)throw Error('history');
    const data=await res.json();
    if(current!==generation)return;
    if(JSON.stringify(data.identity)===key && Array.isArray(data.groups)){
      saved={...data,revision:Date.now()};
    }else if(data.status==='unavailable')saved={...saved,status:'unavailable'};
    due=Date.now()+(data.refreshing||data.status==='loading'?3000:data.status==='ready'?120000:30000);
  }catch{
    if(current!==generation)return;
    saved={...saved,status:'unavailable'};due=Date.now()+30000;
  }finally{
    if(current===generation){pending=false;showDay();}
  }
}
function hour(recent){
  if(!recent){drawHour(null);return;}
  const points=recent.quarters.map(q=>[Date.parse(q.through.captured_at),null,Number(q.lower),Number(q.upper),q.through.event_id,Date.parse(q.start.captured_at)]);
  drawHour([points],points[0][0],recent.timezone,JSON.stringify([recent.timezone,points]));
}
window.AIEdgeCharts={day,hour};
})();
