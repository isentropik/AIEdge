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
const centsFormats=Object.fromEntries(['floor','ceil'].map(mode=>[mode,new Intl.NumberFormat('en-US',{
  useGrouping:false,maximumFractionDigits:2,roundingMode:mode
})]));
const cents=(value,mode)=>Math.round(100*Number(centsFormats[mode].format(value)));
const formats=new Map();
function timeFormat(zone,style) {
  const key=zone+'|'+style;
  if(!formats.has(key)){
    const options={timeZone:zone,hour:'numeric',minute:'2-digit'};
    if(style==='seconds'||style==='exact')options.second='2-digit';
    if(style==='range'||style==='exact')options.timeZoneName='short';
    if(style==='offset')options.timeZoneName='longOffset';
    formats.set(key,new Intl.DateTimeFormat(style==='offset'?'en-US':undefined,options));
  }
  return formats.get(key);
}
function clock(t,zone,exact=false) {
  return timeFormat(zone,exact?'exact':'minute').format(t);
}
function zonePart(format,t) {
  return format.formatToParts(t).find(p=>p.type==='timeZoneName').value;
}
function clockSpan(from,to,zone) {
  const format=timeFormat(zone,'range');
  return zonePart(format,from)===zonePart(format,to)?format.formatRange(from,to):format.format(from)+' – '+format.format(to);
}
function offsetAt(t,zone) {
  const match=/([+-])(\d\d):(\d\d)/.exec(zonePart(timeFormat(zone,'offset'),t));
  return match?(match[1]==='-'?-1:1)*(Number(match[2])*60+Number(match[3]))*60000:0;
}
// Align to local wall time even for fractional-hour offsets and clock changes.
function axisTicks(start,end,width,zone) {
  const span=end-start;
  if(span<=0)return [{time:start,label:clock(start,zone)}];
  const labelWidth=span<120000?88:50;
  const slots=Math.max(1,Math.min(7,Math.floor(width/labelWidth)));
  const minStep=span/slots;
  const step=([1,2,5,10,15,30,60,120,300,600,900,1800,3600,7200,10800,14400,21600,43200,86400]
    .map(seconds=>seconds*1000).find(ms=>ms>=minStep)||86400000);
  const labelFormat=timeFormat(zone,step<60000?'seconds':'minute');
  const ticks=[];
  const add=(from,to,offset)=>{
    for(let t=Math.ceil((from+offset)/step)*step-offset;t<=to;t+=step){
      const label=labelFormat.format(t);
      ticks.push({time:t,label:step>=3600000?label.replace(':00',''):label});
    }
  };
  const first=offsetAt(start,zone),last=offsetAt(end,zone);
  if(first===last)add(start,end,first);
  else{
    let lo=start,hi=end;
    while(hi-lo>1){
      const mid=Math.floor((lo+hi)/2);
      if(offsetAt(mid,zone)===first)lo=mid;else hi=mid;
    }
    add(start,lo,first);add(hi,end,last);
    const seen=new Set(),repeated=new Set();
    for(const t of ticks){if(seen.has(t.label))repeated.add(t.label);seen.add(t.label);}
    for(const t of ticks)if(repeated.has(t.label))t.label+=' '+zonePart(timeFormat(zone,'range'),t.time);
  }
  return ticks;
}
// Fit the outer edge in screen space. Interior display anchors may move one
// pixel outward so a staircase can become a gentle slope. Pin every gap corner.
function bandPath(points,k,x,y,move) {
  const side=k===3?-1:1,baseline=y(0);
  const levels=points.map(p=>side*y(p[k]));
  const coord=(t,v)=>x(t).toFixed(2)+' '+(side*v).toFixed(2);
  const vertex=(i,v=levels[i])=>coord(points[i][0],v);
  const path=[move+vertex(0)];
  function fit(a,b,left,right){
    if(b<=a)return;
    const t0=points[a][0],dt=points[b][0]-t0,rise=right-left;
    let bow=0,pivot=0;
    for(let i=a+1;i<b;i++){
      const u=(points[i][0]-t0)/dt;
      const required=(levels[i]-left-rise*u)/(4*u*(1-u));
      if(required>bow){bow=required;pivot=i;}
    }
    // A quadratic minus a linear input edge is concave in the outward
    // direction. Its maximum is at an endpoint or where the slopes agree.
    let split=bow>Math.abs(rise)/4?pivot:0;
    for(let i=a+1;!split&&i<=b;i++){
      const u=(points[i-1][0]-t0)/dt,v=(points[i][0]-t0)/dt;
      const slope=(levels[i]-levels[i-1])/(v-u);
      const at=bow?Math.max(u,Math.min(v,(rise+4*bow-slope)/(8*bow))):rise>slope?v:u;
      const slack=left+rise*at+4*bow*at*(1-at)-levels[i-1]-slope*(at-u);
      if(slack>2&&b>a+1)split=pivot||Math.min(b-1,Math.max(a+1,at-u<v-at?i-1:i));
    }
    if(split){
      // Stay inside the endpoint levels on a monotone stretch whenever
      // possible and never draw a lower gas bound below zero.
      const adjusted=Math.max(levels[split],Math.min(levels[split]+1,Math.max(left,right),side===1?baseline:Infinity));
      fit(a,split,left,adjusted);fit(split,b,adjusted,right);return;
    }
    path.push(bow>.000001?'Q'+coord(t0+dt/2,left+rise/2+2*bow)+' '+vertex(b,right):'L'+vertex(b,right));
  }
  let start=0;
  for(let i=1;i<points.length;i++){
    if(points[i][0]===points[i-1][0]||Math.abs(levels[i]-levels[i-1])>8){
      fit(start,i-1,levels[start],levels[i-1]);path.push('L'+vertex(i));start=i;
    }else if(i-start===64){
      // Bound the work per sample even for a long day of dense readings.
      fit(start,i,levels[start],levels[i]);start=i;
    }
  }
  fit(start,points.length-1,levels[start],levels.at(-1));
  return path.join(' ');
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
// Skip subpixel steps only when a straight stroke stays within one pixel and
// within every intervening published bound. Each recorder segment is independent.
function dailyStroke(group,y) {
  if(group.length<3)return group;
  const result=[group[0]];
  let start=0, minSlope=-Infinity, maxSlope=Infinity;
  for(let i=1;i<group.length;i++){
    const p=group[i],origin=group[start],dt=p[0]-origin[0];
    const base=y(origin[1]),level=y(p[1]),slope=(level-base)/dt;
    if(i>start+1 && (dt<=0 || slope<minSlope || slope>maxSlope)){
      result.push(group[i-1]);start=i-1;minSlope=-Infinity;maxSlope=Infinity;
      i--;continue;
    }
    const top=p[3]==null?level-1:Math.max(level-1,y(p[3]));
    const bottom=p[2]==null?level+1:Math.min(level+1,y(p[2]));
    minSlope=Math.max(minSlope,(top-base)/dt);
    maxSlope=Math.min(maxSlope,(bottom-base)/dt);
  }
  result.push(group.at(-1));
  return result;
}
// Recorder breaks interrupt the estimate. A nondecreasing daily total can still
// be bounded throughout a gap by its earlier lower and later upper limit.
function dailyRibbons(groups) {
  const ribbons=[];
  let ribbon=null;
  for(const group of groups){
    for(let i=0;i<group.length;i++){
      const p=group[i];
      if(p[2]==null||p[3]==null){ribbon=null;continue;}
      if(i===0 && ribbon){
        const prev=ribbon.at(-1);
        // Recorder points share the day's anchor. A separately published headline must qualify too.
        if(p[6]===false || prev[0]>=p[0] || prev[2]>p[3])ribbon=null;
        else ribbon.push([prev[0],null,prev[2],p[3]],[p[0],null,prev[2],p[3]]);
      }
      if(!ribbon){ribbon=[];ribbons.push(ribbon);}
      ribbon.push(p);
    }
  }
  return ribbons;
}
// Bucket totals sit at their interval centers. End caps cover the partial
// first and last buckets without extending any series across a missing bucket.
const center=p=>p[5]+(p[0]-p[5])/2;
function bucketStroke(group) {
  const first=group[0],last=group.at(-1);
  return [[first[5],...first.slice(1)],...group.map(p=>[center(p),...p.slice(1)]),last];
}
function chart(kind) {
  const host=$(kind+'-curve'),tip=$(kind+'-tip'),isDay=kind==='day';
  const title=$(kind+'-tip-title'),amount=$(kind+'-tip-amount'),bounds=$(kind+'-tip-bounds'),note=$(kind+'-tip-note');
  const graphic=svg('svg',{'aria-hidden':'true'});
  host.append(graphic);
  let model,chosen,atX,atY,cursor,dot,active=-1,inspecting=false,drawnWidth=0,plotBottom=0;
  function hide(){
    inspecting=false;tip.hidden=true;
    if(cursor)cursor.setAttribute('visibility','hidden');
    if(dot)dot.setAttribute('visibility','hidden');
  }
  function pick(index,show=true){
    if(!model?.points.length)return;
    const i=Math.max(0,Math.min(index,model.stops.length-1)),stop=model.stops[i],p=stop.point;
    if(i===active&&show===inspecting)return;
    active=i;inspecting=show;chosen=stop.from??stop.to;
    if(isDay){
      const interval=stop.from==null?'':clockSpan(stop.from,stop.to,model.zone);
      const used=stop.range?number.format(stop.range[0])+'–'+number.format(stop.range[1])+' ft³ used':'Hourly range unavailable';
      title.textContent=p?clock(p[0],model.zone,true):interval;
      amount.textContent=p?.[1]!=null?number.format(p[1])+' ft³ estimated':p?'':'No meter reading in this hour.';
      bounds.textContent=p?.[2]!=null&&p[3]!=null?'Bounds '+number.format(p[2])+'–'+number.format(p[3])+' ft³':'';
      note.textContent=[p&&interval,interval&&used,p?.[5]].filter(Boolean).join(' · ');
    }else{
      title.textContent=clockSpan(p[5],p[0],model.zone);
      amount.textContent=p[1]!=null?number.format(p[1])+' ft³ nominal':p[2]>0?'At least '+number.format(p[2])+' ft³ · partial coverage':'Range unavailable';
      bounds.textContent=p[3]!=null?'Bounds '+number.format(p[2])+'–'+number.format(p[3])+' ft³':'';
      note.textContent=p[0]%60000?'Through '+clock(p[0],model.zone,true):'';
    }
    host.setAttribute('aria-valuenow',i);
    host.setAttribute('aria-valuetext',[title,amount,bounds,note].map(el=>el.textContent).filter(Boolean).join(' · '));
    tip.hidden=!show;
    const px=atX(isDay?p?.[0]??stop.to:center(p)),level=p?.[1]??p?.[2];
    const py=level==null?plotBottom/2:atY(level);
    if(show){
      const position=px<drawnWidth/2?(px+9)+'px':'calc('+(px-9)+'px - var(--tip-width))';
      tip.style.left='clamp(0px, '+position+', calc(100% - var(--tip-width)))';
      const height=tip.offsetHeight||0;
      const preferred=py>height+10?py-height-8:py+8;
      tip.style.top=Math.max(0,Math.min(preferred,plotBottom-height))+'px';
    }
    cursor.setAttribute('visibility',show?'visible':'hidden');
    cursor.setAttribute('transform','translate('+px+' 0)');
    dot.setAttribute('visibility',show&&p?.[1]!=null?'visible':'hidden');
    dot.setAttribute('cy',py);
  }
  function draw() {
    if (!model?.points.length || !host.clientWidth) return;
    const {groups,points,start,zone} = model;
    const w=host.clientWidth, h=isDay ? (w<440?226:320) : (w<440?204:256);
    const left=36,right=w-12,top=12,bottom=h-27;
    const peak=Math.max(0,...points.map(p=>p[3]??p[1]));
    const raw=(peak||1)/3, unit=10**Math.floor(Math.log10(raw));
    const step=([1,2,2.5,5,10].find(v=>v*unit>=raw)||10)*unit;
    const ceiling=Math.max(step,Math.ceil(peak/step)*step);
    const end=points.at(-1)[0], span=Math.max(1,end-start);
    const x=t=>end===start?(left+right)/2:left+(right-left)*(t-start)/span, y=v=>bottom-(bottom-top)*v/ceiling;
    atX=x; atY=y; drawnWidth=w; plotBottom=bottom;
    graphic.setAttribute('viewBox','0 0 '+w+' '+h);
    graphic.style.height=h+'px';
    const nodes=[];
    for(let i=0;i<=Math.round(ceiling/step);i++){
      const v=i*step, pos=y(v);
      nodes.push(svg('line',{x1:left,x2:right,y1:pos,y2:pos,class:'plot-grid'}),svg('text',{x:left-8,y:pos+4,'text-anchor':'end'},Number(v.toPrecision(6)).toLocaleString()));
    }
    const coords=(p,k)=>x(p[0]).toFixed(2)+' '+y(p[k]).toFixed(2);
    const line=(g,k)=>'M'+g.map(p=>coords(p,k)).join(' L');
    const strokes=isDay?groups:groups.map(bucketStroke);
    const ribbons=isDay?dailyRibbons(groups):strokes;
    for(const g of ribbons){
      const back=[...g].reverse();
      const d=isDay?bandPath(g,3,x,y,'M')+' '+bandPath(back,2,x,y,'L'):line(g,3)+' L'+back.map(p=>coords(p,2)).join(' L');
      nodes.push(svg('path',{d:d+' Z',class:'plot-band'}));
    }
    for(const g of strokes){
      if(g[0][1]==null)continue;
      nodes.push(svg('path',{d:line(isDay?dailyStroke(g,y):g,1),class:'plot-estimate'}));
      if(isDay && (g.length===1||g.at(-1)===points.at(-1))){
        const p=g.at(-1);
        nodes.push(svg('circle',{cx:x(p[0]),cy:y(p[1]),r:1.9,class:'plot-estimate-dot'}));
      }
    }
    for(const tick of axisTicks(start,end,right-left,zone)){
      const px=x(tick.time);
      const halfLabel=tick.label.length*3.4;
      const anchor=px<halfLabel?'start':px>w-halfLabel?'end':'middle';
      nodes.push(svg('line',{x1:px,x2:px,y1:bottom,y2:bottom+4,class:'plot-tick'}),
        svg('text',{x:px,y:h-6,'text-anchor':anchor,class:'time-tick'},tick.label));
    }
    cursor=svg('g',{class:'plot-cursor',visibility:'hidden'});
    dot=svg('circle',{cx:0,r:4.3,class:'plot-estimate-dot'});
    cursor.append(svg('line',{x1:0,x2:0,y1:top,y2:bottom}),dot);
    nodes.push(cursor);
    graphic.replaceChildren(...nodes);
    const i=model.stops.findIndex(s=>(s.from??s.to)===chosen);
    active=-1;pick(i<0 ? model.stops.length-1 : i,inspecting);
  }
  function locate(e) {
    if(!model || !atX)return;
    const px=e.clientX-host.getBoundingClientRect().left;
    const i=model.stops.findIndex(s=>px<atX(s.to));
    pick(i<0?model.stops.length-1:i);
  }
  host.addEventListener('pointerdown',locate);
  host.addEventListener('pointermove',e=>{if(e.pointerType==='mouse'||e.buttons)locate(e);});
  host.addEventListener('pointerleave',e=>{if(e.pointerType==='mouse')hide();});
  host.addEventListener('pointercancel',hide);
  host.addEventListener('blur',hide);
  host.addEventListener('focus',()=>{if(!inspecting)pick(active<0?0:active);});
  document.addEventListener?.('pointerdown',e=>{if(inspecting&&!host.contains(e.target))hide();});
  host.addEventListener('keydown',e=>{
    if(e.key==='Escape'){hide();return;}
    if(!model)return;
    const i=model.stops.findIndex(s=>(s.from??s.to)===chosen);
    const next={ArrowLeft:i-1,ArrowRight:i+1,Home:0,End:model.stops.length-1}[e.key];
    if(next!==undefined){e.preventDefault();pick(next);}
  });
  new ResizeObserver(()=>{if(host.clientWidth!==drawnWidth)draw();}).observe(host);
  return function update(groups, start, zone, key, empty, midnight, recent, clockBins) {
    if(!groups?.length&&!clockBins?.length){
      model=null; chosen=null; graphic.replaceChildren(); host.hidden=true;
      hide();active=-1;cursor=null;dot=null;drawnWidth=0;
      host.setAttribute('aria-valuetext','');
      if(isDay)$('day-history-status').textContent=empty||'';
      return;
    }
    if(model?.key===key)return;
    const previous=model?.stops.at(-1);
    if(!previous || chosen===(previous.from??previous.to))chosen=null;
    const points=clockBins||groups.flat();
    const stops=isDay?dayHours(points,midnight,recent):points.map(p=>({to:p[0],point:p}));
    model={groups,points,stops,start,zone,key,clockBins};
    host.hidden=false; host.tabIndex=0;
    host.setAttribute('role','slider');
    host.setAttribute('aria-label',isDay?'Inspect gas use by hour':'Inspect gas use by interval');
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
  const point=[stamp,estimate,bounds?Number(lower):null,bounds?Number(upper):null,event,label,latest.sameDailyBounds];
  const history=saved?.day===day&&saved.zone===zone?saved:null;
  const groups=history?.groups || [], last=groups.at(-1)?.at(-1);
  const recorded=last && method==='range_midpoint_v1' && history.last_digest===source.source_sha256 && history.last_captured_at===source.captured_at &&
    last.every((v,i)=>v===point[i]);
  // Only recorder segments establish continuity. A newer published total supplies a point, never a connecting interval.
  const visible=recorded ? [...groups.slice(0,-1),[...groups.at(-1).slice(0,-1),point]] :
    [...groups.map(g=>g.filter(p=>p[0]<stamp&&p[4]<event)).filter(g=>g.length),[point]];
  host.dataset.endEvent=String(event);host.dataset.endTime=source.captured_at;
  $('day-history-status').textContent=saved?.status==='unavailable'?'History refresh delayed':'';
  drawDay(visible,history?.midnight??stamp,zone,JSON.stringify([identity,history?.revision,latest,recentWindow]),null,history?.midnight,recentWindow);
}
async function day(daily,headline,recent){
  const key=headline?.source&&daily?.before&&daily.after&&daily.through&&daily.day===headline.day&&daily.timezone===headline.zone ? JSON.stringify([daily.day,daily.timezone,daily.through.camera,daily.through.format_id,
    daily.before.source_sha256,daily.after.source_sha256,daily.before.event_id,daily.before.captured_at,daily.after.event_id,daily.after.captured_at]) : '';
  if(key!==identity){identity=key;generation++;saved=null;pending=false;due=0;$('day-history-status').textContent='';}
  latest=headline && {...headline,sameDailyBounds:Boolean(key) && headline.method==='range_midpoint_v1' && !['stale','partial_coverage'].includes(headline.status) &&
    daily?.status!=='stale' && daily.through.event_id===headline.source.event_id && daily.through.source_sha256===headline.source.source_sha256 &&
    daily.through.captured_at===headline.source.captured_at};
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
function hour(period,zone,midpoint){
  if(!period?.bins?.length){drawHour(null);return;}
  const groups=[],points=[];
  let group=null;
  for(const bin of period.bins){
    const point=[Date.parse(bin.end),midpoint(bin),bin.lower==null?null:Number(bin.lower),bin.upper==null?null:Number(bin.upper),null,Date.parse(bin.start)];
    points.push(point);
    if(point[1]==null){group=null;continue;}
    if(!group || group.at(-1)[0]!==point[5]){group=[];groups.push(group);}
    group.push(point);
  }
  drawHour(groups,Date.parse(period.start),zone,JSON.stringify([zone,points]),null,null,null,points);
}
window.AIEdgeCharts={day,hour};
})();
