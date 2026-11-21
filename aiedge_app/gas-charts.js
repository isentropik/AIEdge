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
    const amounts = p[2]==null ? '' : number.format(p[2])+'–'+number.format(p[3])+' ft³';
    const time = isDay ? clock(p[0],model.zone,true) : clock(p[5],model.zone)+' – '+clock(p[0],model.zone,true);
    const estimate = p[1]==null ? '' : number.format(p[1])+' ft³ estimated';
    const value = isDay ? [estimate,amounts,p[5]].filter(Boolean).join(' · ') : amounts;
    readout.textContent = time+' · '+value;
    host.setAttribute('aria-valuenow',i);
    host.setAttribute('aria-valuetext',readout.textContent);
    const cursor=graphic.querySelector('.plot-cursor');
    if(cursor) {
      cursor.setAttribute('transform','translate('+atX(chosen)+' 0)');
      cursor.querySelectorAll('circle').forEach((dot,j)=>dot.setAttribute('cy',atY(isDay ? p[1]??p[2] : p[j+2])));
    }
  }
  function draw() {
    if (!model?.points.length || !host.clientWidth) return;
    const {groups,points,start,zone} = model;
    const w=host.clientWidth, h=isDay ? (w<440?175:205) : (w<440?144:156);
    const left=36,right=w-12,top=12,bottom=h-27;
    const peak=Math.max(0,...points.map(p=>p[3]??p[1]));
    const raw=(peak||1)/3, unit=10**Math.floor(Math.log10(raw));
    const step=([1,2,2.5,5,10].find(v=>v*unit>=raw)||10)*unit;
    const ceiling=Math.max(step,Math.ceil(peak/step)*step);
    const end=points.at(-1)[0], span=Math.max(1,end-start);
    const x=t=>end===start?(left+right)/2:left+(right-left)*(t-start)/span, y=v=>bottom-(bottom-top)*v/ceiling;
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
      if(g[0][2]!=null)nodes.push(svg('path',{d:line(g,3)+' L'+[...g].reverse().map(p=>coords(p,2)).join(' L')+' Z',class:'plot-band'}));
      for(const [k,cls] of isDay?[[1,'plot-estimate']]:[[2,'plot-estimate'],[3,'plot-upper']]){
        if(g[0][k]==null)continue;
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
      nodes.push(svg('text',{x:x(t),y:h-6,'text-anchor':ticks.length===1?'middle':i===0?'start':i===ticks.length-1?'end':'middle'},label));
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
  const host=$('day-curve');
  const source=latest?.source;
  if(!source){
    delete host.dataset.endEvent;delete host.dataset.endTime;
    $('day-history-status').textContent='';
    drawDay(null,null,null,null,'Waiting for a supported measurement');return;
  }
  const {value,lower,upper,day,zone,status,method}=latest;
  const stamp=Date.parse(source.captured_at), event=source.event_id;
  const numeric=v=>(typeof v==='number'||typeof v==='string'&&v.trim()!=='')&&Number.isFinite(Number(v))&&Number(v)>=0;
  const estimate=numeric(value)?Number(value):null;
  const bounds=numeric(lower)&&numeric(upper)&&Number(lower)<=Number(upper)&&
    (estimate==null||Number(lower)<=estimate&&estimate<=Number(upper));
  if(estimate==null&&!bounds){
    delete host.dataset.endEvent;delete host.dataset.endTime;
    $('day-history-status').textContent='';
    drawDay(null,null,null,null,'No supported amount for this measurement');return;
  }
  const label=status==='stale'?'Stale':method==='observed_increments'||status==='partial_coverage'?'Partial coverage':
    method==='lower_bound_assumption_v1'?'Lower-bound assumption':'';
  const point=[stamp,estimate,bounds?Number(lower):null,bounds?Number(upper):null,event,label];
  const history=saved?.day===day&&saved.zone===zone?saved:null;
  const groups=history?.groups || [], last=groups.at(-1)?.at(-1);
  const recorded=last && method==='range_midpoint_v1' && history.last_digest===source.source_sha256 && history.last_captured_at===source.captured_at &&
    last.every((v,i)=>v===point[i]);
  // Only recorder segments establish continuity. A newer published total supplies a point, never a connecting interval.
  const visible=recorded ? [...groups.slice(0,-1),[...groups.at(-1).slice(0,-1),point]] :
    [...groups.map(g=>g.filter(p=>p[0]<stamp&&p[4]<event)).filter(g=>g.length),[point]];
  host.dataset.endEvent=String(event);host.dataset.endTime=source.captured_at;
  $('day-history-status').textContent=saved?.status==='unavailable'?'History refresh delayed':
    !recorded&&visible.length>1?'Showing the latest measurement as a separate point.':'';
  drawDay(visible,history?.midnight??stamp,zone,JSON.stringify([identity,history?.revision,latest]));
}
async function day(daily,headline){
  const key=headline?.source&&daily?.before&&daily.after&&daily.through&&daily.day===headline.day&&daily.timezone===headline.zone ? JSON.stringify([daily.day,daily.timezone,daily.through.camera,daily.through.format_id,
    daily.before.source_sha256,daily.after.source_sha256,daily.before.event_id,daily.before.captured_at,daily.after.event_id,daily.after.captured_at]) : '';
  if(key!==identity){identity=key;generation++;saved=null;pending=false;due=0;$('day-history-status').textContent='';}
  latest=headline;
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
