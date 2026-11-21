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
// Bound consumption at a clock boundary from the saved daily totals on either side.
// The line keeps every measurement. Only its inspection targets are grouped.
function dayHours(points, midnight, recent) {
  const last=points.at(-1), hour=3600000;
  if(midnight==null)return [{point:last,from:null,to:last[0]}];
  const stops=[];
  const suffix=Array(points.length+1).fill(Infinity);
  const eligible=p=>p[2]!=null&&p[3]!=null&&p[5]!=='Partial coverage';
  for(let i=points.length-1;i>=0;i--)
    suffix[i]=eligible(points[i])?Math.min(points[i][3],suffix[i+1]):suffix[i+1];
  let i=0, priorLow=0, left=[0,0];
  for(let from=midnight;from<last[0]||!stops.length;from+=hour){
    const to=Math.min(from+hour,last[0]), first=i;
    // Historical times are truncated to milliseconds. A point stamped at an
    // hour boundary can safely bound it from above, even with sub-ms precision.
    while(i<points.length&&points[i][0]<to){
      if(eligible(points[i]))priorLow=Math.max(priorLow,points[i][2]);
      i++;
    }
    const final=to===last[0];
    const right=final&&eligible(last)?[Math.max(priorLow,last[2]),last[3]]:[priorLow,suffix[i]];
    const point=final?last:i>first?points[i-1]:null;
    let range=null;
    if(point&&(!final||eligible(last))&&left[0]<=left[1]&&right[0]<=right[1]&&left[0]<=right[1]&&Number.isFinite(right[1])){
      // Recorder bounds are published in hundredths. Round their difference
      // outwards for any source that supplies finer precision.
      const cents=(v,mode)=>Math.round(100*Number(v.toLocaleString('en-US',{useGrouping:false,maximumFractionDigits:2,roundingMode:mode})));
      range=[Math.max(0,cents(right[0],'floor')-cents(left[1],'ceil'))/100,
             (cents(right[1],'ceil')-cents(left[0],'floor'))/100];
      if(recent){
        // The published hour and its four adjacent quarters are separate
        // constraints. Only add quarters that lie entirely inside this slot.
        const inside=part=>part.start>=from&&part.end<=to;
        const covers=part=>part.start<=from&&part.end>=to;
        const contained=recent.slice(1).filter(inside).reduce((sum,q)=>sum+cents(q.low,'floor'),0);
        const lower=Math.max(range[0],contained/100,inside(recent[0])?recent[0].low:0);
        const upper=Math.min(range[1],...recent.filter(covers).map(q=>q.high));
        range=lower<=upper?[lower,upper]:null;
      }
    }
    stops.push({point,from,to,range});
    if(final)break;
    left=right;
  }
  return stops;
}
function chart(kind) {
  const host = $(kind+'-curve'), readout = $(kind+'-readout'), isDay = kind === 'day';
  const graphic = svg('svg',{'aria-hidden':'true'});
  host.append(graphic);
  let model, chosen, atX, atY;
  function pick(index) {
    if (!model?.points.length) return;
    const i = Math.max(0,Math.min(index,model.stops.length-1)), stop=model.stops[i], p=stop.point;
    chosen = stop.from??stop.to;
    const cursor=graphic.querySelector('.plot-cursor');
    if(isDay){
      const format=new Intl.DateTimeFormat(undefined,{timeZone:model.zone,hour:'numeric',minute:'2-digit',timeZoneName:'short'});
      let span='';
      if(stop.from!=null){
        const offset=t=>format.formatToParts(t).find(part=>part.type==='timeZoneName').value;
        span=(offset(stop.from)===offset(stop.to)?format.formatRange(stop.from,stop.to):format.format(stop.from)+' – '+format.format(stop.to))+' · ';
      }
      $('day-hour-readout').textContent=span+(stop.range?number.format(stop.range[0])+'–'+number.format(stop.range[1])+' ft³ used':'Hourly range unavailable');
    }
    host.setAttribute('aria-valuenow',i);
    if(!p){
      readout.textContent='No meter reading in this hour.';
      host.setAttribute('aria-valuetext',$('day-hour-readout').textContent+' · '+readout.textContent);
      if(cursor)cursor.setAttribute('visibility','hidden');
      return;
    }
    const amounts = p[2]==null ? '' : number.format(p[2])+'–'+number.format(p[3])+' ft³';
    const time = isDay ? clock(p[0],model.zone,true) : clock(p[5],model.zone)+' – '+clock(p[0],model.zone,true);
    const estimate = p[1]==null ? '' : number.format(p[1])+' ft³ estimated';
    const value = isDay ? [estimate,amounts,p[5]].filter(Boolean).join(' · ') : amounts;
    readout.textContent = (isDay?'Day total at ':'')+time+' · '+value;
    host.setAttribute('aria-valuetext',(isDay?$('day-hour-readout').textContent+' · ':'')+readout.textContent);
    if(cursor) {
      cursor.setAttribute('visibility','visible');
      cursor.setAttribute('transform','translate('+atX(p[0])+' 0)');
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
    const i=model.stops.findIndex(s=>(s.from??s.to)===chosen);
    pick(i<0 ? model.stops.length-1 : i);
  }
  function locate(e) {
    if(!model || !atX)return;
    const px=e.clientX-host.getBoundingClientRect().left;
    if(isDay){
      const i=model.stops.findIndex(s=>px<atX(s.to));
      pick(i<0?model.stops.length-1:i);return;
    }
    let best=0;
    model.points.forEach((p,i)=>{if(Math.abs(atX(p[0])-px)<Math.abs(atX(model.points[best][0])-px))best=i;});
    pick(best);
  }
  host.addEventListener('pointerdown',locate);
  host.addEventListener('pointermove',e=>{if(e.pointerType==='mouse'||e.buttons)locate(e);});
  host.addEventListener('keydown',e=>{
    if(!model)return;
    const i=model.stops.findIndex(s=>(s.from??s.to)===chosen);
    const next={ArrowLeft:i-1,ArrowRight:i+1,Home:0,End:model.stops.length-1}[e.key];
    if(next!==undefined){e.preventDefault();pick(next);}
  });
  new ResizeObserver(draw).observe(host);
  return function update(groups, start, zone, key, empty, midnight, recent) {
    if(!groups?.length){
      model=null; chosen=null; graphic.replaceChildren(); host.hidden=true;
      if(isDay)$('day-hour-readout').textContent='';
      readout.textContent=empty||''; return;
    }
    if(model?.key===key)return;
    const previous=model?.stops.at(-1);
    if(!previous || chosen===(previous.from??previous.to))chosen=null;
    const points=groups.flat();
    const stops=isDay?dayHours(points,midnight,recent):points.map(p=>({to:p[0],point:p}));
    model={groups,points,stops,start,zone,key};
    host.hidden=false; host.tabIndex=0;
    host.setAttribute('role','slider');
    host.setAttribute('aria-label',isDay?'Inspect gas use by hour':'Inspect 15-minute usage by interval end');
    host.setAttribute('aria-valuemin','0');host.setAttribute('aria-valuemax',stops.length-1);
    draw();
  };
}
const drawDay=chart('day'), drawHour=chart('hour');
let identity='', saved=null, generation=0, due=0, pending=false, latest=null, recentWindow=null;
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
  drawDay(visible,history?.midnight??stamp,zone,JSON.stringify([identity,history?.revision,latest,recentWindow]),null,history?.midnight,recentWindow);
}
async function day(daily,headline,recent){
  const key=headline?.source&&daily?.before&&daily.after&&daily.through&&daily.day===headline.day&&daily.timezone===headline.zone ? JSON.stringify([daily.day,daily.timezone,daily.through.camera,daily.through.format_id,
    daily.before.source_sha256,daily.after.source_sha256,daily.before.event_id,daily.before.captured_at,daily.after.event_id,daily.after.captured_at]) : '';
  if(key!==identity){identity=key;generation++;saved=null;pending=false;due=0;$('day-history-status').textContent='';}
  latest=headline;
  recentWindow=null;
  // Accept the other published range only when its final source is also the
  // headline's exact event. Preserve microsecond ordering at slot boundaries.
  if(headline?.source&&recent?.through?.event_id===headline.source.event_id&&recent.through.source_sha256===headline.source.source_sha256&&
     recent.through.captured_at===headline.source.captured_at&&recent.timezone===headline.zone&&
     recent.hour?.through?.event_id===recent.through.event_id&&recent.hour.through.source_sha256===recent.through.source_sha256&&
     recent.hour.through.captured_at===recent.through.captured_at&&recent.hour.lower!=null&&recent.hour.upper!=null&&
     String(recent.hour.lower).trim()&&String(recent.hour.upper).trim()){
    const ms=s=>Date.parse(s)+Number((/\.(\d+)/.exec(s)?.[1]||'').padEnd(6,'0').slice(3,6))/1000;
    const fields=[recent.hour,...recent.quarters].map(q=>({start:ms(q.start.captured_at),end:ms(q.through.captured_at),low:Number(q.lower),high:Number(q.upper)}));
    if(fields.every(q=>Number.isFinite(q.low)&&Number.isFinite(q.high)&&q.low>=0&&q.low<=q.high&&q.start<q.end)){
      // The chart endpoint represents the same measured instant, including its
      // fractional millisecond. Use its plotted coordinate for this comparison.
      for(const q of fields)if(q.end===fields[0].end)q.end=Date.parse(headline.source.captured_at);
      recentWindow=fields;
    }
  }
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
