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
// Rolling labels name real interval closes, including a partial final interval.
function intervalTicks(stops,start,end,width,zone){
  const format=timeFormat(zone,'minute');
  const ticks=stops.map(({to})=>({time:to,label:format.format(to)}));
  const labels=new Map();
  for(const t of ticks)labels.set(t.label,(labels.get(t.label)||0)+1);
  const selected=[];
  let right=-Infinity;
  for(const t of ticks){
    if(labels.get(t.label)>1)t.label+=' '+zonePart(timeFormat(zone,'range'),t.time);
    const x=width*(t.time-start)/Math.max(1,end-start);
    const half=t.label.length*3.6;
    if(x-half<right+10)continue;
    selected.push(t);
    right=x+half;
  }
  return selected;
}
// Bound consumption at a clock boundary from the saved daily totals on either side.
// Each completed hour selects its last actual measurement; the final hour uses the headline.
function dayHours(points, midnight, recent, hourly) {
  const last=points.at(-1), hour=3600000;
  if(midnight==null)return [{point:last,from:null,to:last[0]}];
  const stops=[];
  const suffix=Array(points.length+1).fill(Infinity);
  const eligible=p=>p[2]!=null&&p[3]!=null&&(p[5]!=='Partial coverage'||p[6]===true);
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
    const measured=hourly?.get(from);
    if(measured&&range&&measured.end===to){
      const lo=Math.max(range[0],measured.range[0]),hi=Math.min(range[1],measured.range[1]);
      range=lo<=hi?[lo,hi]:null;
    }
    stops.push({point,from,to,range});
    if(final)break;
    left=right;
  }
  return stops;
}
// Drawing and inspection share the same hourly measurements. Separate runs
// prevent interpolation across missing hours or incompatible readings.
function hourlyRuns(groups,stops){
  const first=groups[0][0],slots=new Map();
  for(const [slot,s] of stops.entries())if(s.point)slots.set(s.point,slot);
  if(!slots.has(first))slots.set(first,Math.max(0,stops.findIndex(s=>s.to>first[0])));
  const runs=[];
  let last=null,run=null,previousSlot=-1;
  for(const group of groups){
    for(const p of group){
      if(last&&(p[0]<=last[0]||p[2]==null||p[3]==null||last[2]==null||last[3]==null||
         last[2]>p[3]||p[1]==null||last[1]==null||p===group[0]&&p[6]===false))run=null;
      last=p;
      if(!slots.has(p))continue;
      const slot=slots.get(p);
      if(!run||slot>previousSlot+1){run=[];runs.push(run);}
      run.push(p);
      previousSlot=slot;
    }
  }
  return runs;
}

// A shared, slope-limited tangent keeps the line and both edges smooth through
// each actual point. Every cubic stays between its two endpoint values and the
// nominal stays inside the ribbon, even where a bound levels off or changes sign.
function trendPaths(run,x,y,band=true,line=true){
  const point=(px,v)=>px.toFixed(2)+' '+y(v).toFixed(2);
  const xx=run.map(p=>x(p[0]));
  const slope=run.map((p,i)=>{
    let low=Infinity,high=-Infinity;
    for(const j of [i-1,i+1]){
      if(j<0||j>=run.length)continue;
      const width=xx[j]-xx[i];
      if(!width)return 0;
      for(let k=1;k<=3;k++){
        const rate=(run[j][k]-p[k])/width;
        low=Math.min(low,rate);high=Math.max(high,rate);
      }
    }
    return low===Infinity?0:low>0?low:high<0?high:0;
  });
  function segment(i,j,k){
    const dx=(xx[j]-xx[i])/3,a=run[i][k],b=run[j][k];
    return ' C'+point(xx[i]+dx,a+dx*slope[i])+' '+point(xx[j]-dx,b-dx*slope[j])+' '+point(xx[j],b);
  }
  const lines=[],bands=[];
  const first=run[0],end=run.length-1;
  if(band&&first[2]!=null&&first[3]!=null){
    let area='M'+point(xx[0],first[3]);
    for(let i=1;i<=end;i++)area+=segment(i-1,i,3);
    area+=' L'+point(xx[end],run[end][2]);
    for(let i=end;i>0;i--)area+=segment(i,i-1,2);
    bands.push(svg('path',{class:'plot-band',d:area+' Z'}));
  }
  if(line&&first[1]!=null){
    let path='M'+point(xx[0],first[1]);
    for(let i=1;i<=end;i++)path+=segment(i-1,i,1);
    lines.push(svg('path',{class:'plot-estimate',d:path}));
  }
  return {lines,bands};
}

// A displayed knot is always an actual meter event. Keep the first and last
// event of each basis and the final observation of each elapsed clock hour.
function meterRuns(points,midnight,verified){
  const runs=[];
  let prev,run,bucket,firstInRun;
  for(const p of points){
    const hour=Math.floor((p[0]-midnight)/3600000);
    const reset=!prev || typeof prev[3]!==typeof p[3] || hour>bucket+1 ||
      p[0]<=prev[0] || p[2]<=prev[2] || p[1]<prev[1];
    if(reset){run=[];runs.push(run);firstInRun=true;}
    if(!reset && hour===bucket && !firstInRun)run.pop();
    run.push([p[0],p[1],p[1],p[1],p[2],p[3]]);
    firstInRun=reset;
    prev=p;bucket=hour;
  }
  if(verified)return runs;
  return runs.flatMap(run=>{
    const out=[];
    for(const p of run){
      if(!out.length||out.at(-1).at(-1)[5]!==p[5])out.push([]);
      out.at(-1).push(p);
    }
    return out;
  });
}
function chart(){
  const host=$('day-curve'),tip=$('day-tip');
  const title=$('day-tip-title'),amount=$('day-tip-amount'),note=$('day-tip-note');
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
    const interval=stop.from==null?'':clockSpan(stop.from,stop.to,model.zone);
    let used=stop.low>0?'At least '+number.format(stop.low)+' ft³ used':'Interval unavailable';
    if(stop.range){
      const [lo,hi]=stop.range;
      used=lo===0&&hi>0?'Up to '+number.format(hi)+' ft³ used':number.format((lo+hi)/2)+' ft³ used';
    }
    title.textContent=interval||clock(stop.to,model.zone,true);
    amount.textContent=p?.[1]!=null?'Total '+number.format(p[1])+' ft³':model.movement?
      (model.loadingHistory?'Loading saved total':'No verified total this hour'):'Total unavailable';
    note.textContent=model.movement && p ? used+' · '+clock(p[0],model.zone,true) : used;
    host.setAttribute('aria-valuenow',i);
    const rangeText=(lo,hi)=>lo!=null&&hi!=null?number.format(lo)+'–'+number.format(hi)+' ft³':'';
    host.setAttribute('aria-valuetext',[title.textContent,amount.textContent,rangeText(p?.[2],p?.[3]),used,
      stop.range&&rangeText(...stop.range),p?.[5]].filter(Boolean).join(' · '));
    tip.hidden=!show;
    const px=atX(stop.to),level=p?.[1]??p?.[2];
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
    // A daily sample can precede its hour close. Keep that reading at its measured time.
    dot.setAttribute('cx',p?atX(p[0])-px:0);
    dot.setAttribute('cy',py);
  }
  function draw() {
    if (!model?.points.length || !host.clientWidth) return;
    const {groups,points,start,zone} = model;
    const w=host.clientWidth,h=w<440?226:320;
    const left=36,right=w-36,top=12,bottom=h-27;
    function scale(peak){
      const raw=(peak||1)/3,unit=10**Math.floor(Math.log10(raw));
      const step=([1,2,2.5,5,10].find(v=>v*unit>=raw)||10)*unit;
      const max=Math.max(step,Math.ceil(peak/step)*step);
      return {step,max,y:v=>bottom-(bottom-top)*v/max};
    }
    const totalLabel=$('total-key-label');
    if(totalLabel)totalLabel.textContent=model.movement?'Hourly total trend · left':'Total · left';
    const total=scale(Math.max(0,...points.map(p=>p[3]??p[1]??0),...(model.movement||[]).map(p=>p[1])));
    const intervals=model.stops.filter(s=>s.range);
    const usage=scale(Math.max(0,...intervals.map(s=>s.range[1])));
    const end=model.stops.at(-1).to, span=Math.max(1,end-start);
    const x=t=>end===start?(left+right)/2:left+(right-left)*(t-start)/span,y=total.y;
    atX=x; atY=y; drawnWidth=w; plotBottom=bottom;
    graphic.setAttribute('viewBox','0 0 '+w+' '+h);
    graphic.style.height=h+'px';
    const nodes=[];
    const tickLabel=v=>Number(v.toPrecision(6)).toLocaleString(undefined,{maximumSignificantDigits:4,notation:v>=1000?'compact':'standard'});
    for(let i=0;i<=Math.round(total.max/total.step);i++){
      const v=i*total.step, pos=y(v);
      nodes.push(svg('line',{x1:left,x2:right,y1:pos,y2:pos,class:'plot-grid'}),svg('text',{x:left-7,y:pos+4,'text-anchor':'end',class:'total-tick'},tickLabel(v)));
    }
    if(intervals.length)for(let i=0;i<=Math.round(usage.max/usage.step);i++){
      const v=i*usage.step;
      nodes.push(svg('text',{x:right+7,y:usage.y(v)+4,class:'use-tick'},tickLabel(v)));
    }
    const runs=model.rolling?groups:hourlyRuns(groups,model.rangeStops);
    const lines=[];
    let coverageClip=null;
    if(model.coverage){
      // Clip the hourly guide at the exact stored capture times. A gap does
      // not change the shape on either side, or manufacture an extra knot.
      coverageClip=svg('clipPath',{id:'meter-capture-coverage',clipPathUnits:'userSpaceOnUse'});
      let from=Math.max(start,model.coverage.first[1]);
      const until=Math.min(end,model.coverage.through[1]);
      function span(to){
        if(to>from)coverageClip.append(svg('rect',{x:x(from),y:0,width:x(to)-x(from),height:h}));
      }
      for(const [a,b] of model.coverage.gaps){
        if(b<=from||a>=until)continue;
        span(Math.min(a,until));from=Math.max(from,b);
      }
      span(until);
      const defs=svg('defs');defs.append(coverageClip);nodes.push(defs);
    }
    function drawRun(run,band,line){
      const trend=trendPaths(run,x,y,band,line);
      if(coverageClip)for(const path of [...trend.lines,...trend.bands])path.setAttribute('clip-path','url(#meter-capture-coverage)');
      nodes.push(...trend.bands);lines.push(...trend.lines);
      if(line)for(const p of run)if(p[4]!=null&&p[1]!=null)lines.push(svg('circle',{
        cx:x(p[0]),cy:y(p[1]),r:p[0]===end?2.7:1.8,class:'plot-estimate-dot','data-event':p[4]
      }));
    }
    for(const run of runs)drawRun(run,true,!model.movement);
    if(model.movement){
      for(const run of meterRuns(model.movement,start,!!model.coverage))drawRun(run,false,true);
    }
    {
      const gapKey=$('day-gap-key');
      gapKey.hidden=!model.gaps.length;
      gapKey.title=model.coverage?'Interruption in saved captures or meter tracking':'Break between published estimates';
      if(gapKey.lastChild?.nodeType===3)gapKey.lastChild.textContent=model.coverage?'Reading gap':'History break';
      for(const [from,to] of model.gaps){
        nodes.push(svg('line',{class:'plot-history-gap',x1:x(from),x2:x(to),y1:bottom+2,y2:bottom+2,
          stroke:'var(--series)','stroke-width':3,'stroke-linecap':model.coverage?'butt':'round','data-from':from,'data-to':to}));
      }
    }
    nodes.push(...lines);
    for(const stop of model.stops){
      if(!stop.range||stop.from==null)continue;
      const [lo,hi]=stop.range,px=x(stop.to),cap=Math.min(4,Math.max(1,(x(stop.to)-x(stop.from))/4));
      if(hi>lo)nodes.push(svg('path',{class:'plot-whisker',d:'M'+(px-cap)+' '+usage.y(hi)+'h'+(cap*2)+' M'+px+' '+usage.y(hi)+'V'+usage.y(lo)+' M'+(px-cap)+' '+usage.y(lo)+'h'+(cap*2)}));
      nodes.push(svg('circle',{class:'plot-usage-dot',cx:px,cy:usage.y((lo+hi)/2),r:3.1}));
    }
    const ticks=model.rolling?intervalTicks(model.stops,start,end,right-left,zone):axisTicks(start,end,right-left,zone);
    for(const tick of ticks){
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
    const stops=model.stops;
    const i=stops.findIndex((s,j)=>j===stops.length-1||px<=(atX(s.to)+atX(stops[j+1].to))/2);
    pick(i);
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
  return function update(groups, start, zone, key, empty, midnight, recent, clockBins, gaps=[], hourly=null, movement=null, coverage=null) {
    if(!groups?.length&&!clockBins?.length){
      model=null; chosen=null; graphic.replaceChildren(); host.hidden=true;
      hide();active=-1;cursor=null;dot=null;drawnWidth=0;
      host.setAttribute('aria-valuetext','');
      $('day-history-status').textContent=empty||'';$('day-gap-key').hidden=true;
      return;
    }
    if(model?.key===key)return;
    const previous=model?.stops.at(-1);
    if(!previous || chosen===(previous.from??previous.to))chosen=null;
    const rangeStops=clockBins||dayHours(groups.flat(),midnight,recent,hourly);
    const stops=movement?rangeStops.map(stop=>{
      const p=movement.findLast(p=>(stop.from==null||p[0]>=stop.from)&&
        (p[0]<stop.to||stop.to===movement.at(-1)[0]&&p[0]===stop.to));
      const same=p&&p[2]===stop.point?.[4];
      return {...stop,point:p?[p[0],p[1],same?stop.point[2]:null,same?stop.point[3]:null,p[2]]:null};
    }):rangeStops;
    const points=clockBins?stops.map(s=>s.point||[s.to,null,null,null]):groups.flat();
    model={groups,points,stops,rangeStops,movement,coverage,start,zone,key,rolling:!!clockBins,gaps,loadingHistory:empty==='loading'};
    host.hidden=false; host.tabIndex=0;
    host.setAttribute('role','slider');
    host.setAttribute('aria-label','Inspect gas use by interval');
    host.setAttribute('aria-valuemin','0');host.setAttribute('aria-valuemax',stops.length-1);
    draw();
  };
}
const drawDay=chart();
let selection='today',rolling=null,activeSelection=null;
let dayView=null;
let identity='', saved=null, lastRangeSource=null, generation=0, due=0, lastAttempt=0, pending=false, latest=null, recentWindow=null;
function showDay(){
  const host=$('day-curve');
  const source=latest?.source;
  if(!source){
    dayView=null;
    if(selection!=='today'){showRolling();return;}
    delete host.dataset.endEvent;delete host.dataset.endTime;
    $('day-history-status').textContent='';
    drawDay(null,null,null,null,'Waiting for a supported measurement');return;
  }
  const {value,lower,upper,day,zone,status,method}=latest;
  const stamp=Date.parse(source.captured_at), event=source.event_id;
  const numeric=v=>(typeof v==='number'||typeof v==='string'&&v.trim()!=='')&&Number.isFinite(Number(v))&&Number(v)>=0;
  const estimate=numeric(value)?Number(value):null;
  const tracksMeter=method==='nominal_meter_movement_v1';
  const bounds=numeric(lower)&&numeric(upper)&&Number(lower)<=Number(upper)&&
    (tracksMeter||estimate==null||Number(lower)<=estimate&&estimate<=Number(upper));
  if(estimate==null&&!bounds){
    dayView=null;
    if(selection!=='today'){showRolling();return;}
    delete host.dataset.endEvent;delete host.dataset.endTime;
    $('day-history-status').textContent='';
    drawDay(null,null,null,null,'No supported amount for this measurement');return;
  }
  const label=status==='stale'?'Stale':method==='observed_increments'||status==='partial_coverage'?'Partial coverage':
    method==='lower_bound_assumption_v1'?'Lower-bound assumption':'';
  const point=[stamp,estimate,bounds?Number(lower):null,bounds?Number(upper):null,event,label,latest.sameDailyBounds];
  const history=latest.historyCompatible&&saved?.day===day&&saved.zone===zone?saved:null;
  const periods=rolling?.compatibleWithDay&&(latest.sameDailyBounds||tracksMeter&&history)&&rolling.zone===zone&&
    (rolling.through.event_id<event&&Date.parse(rolling.through.captured_at)<stamp||
     rolling.through.event_id===event&&rolling.through.captured_at===source.captured_at&&rolling.through.source_sha256===source.source_sha256)?rolling:null;
  const key=JSON.stringify([identity,history?.revision,latest,recentWindow,periods?.key]);
  if(dayView?.key===key&&dayView.historyStatus===saved?.status){
    if(selection!=='today'){showRolling();return;}
    if(host.dataset.endEvent===String(event)&&activeSelection==='today')return;
  }
  const groups=history?.groups || [], last=groups.at(-1)?.at(-1);
  const recorded=last && method==='range_midpoint_v1' && history.last_digest===source.source_sha256 && history.last_captured_at===source.captured_at &&
    last.every((v,i)=>v===point[i]);
  const recordedGroups=recorded?groups:groups.map(g=>g.filter(p=>p[0]<stamp&&p[4]<event)).filter(g=>g.length);
  // A newer headline can extend the hourly preview without creating a fictitious recorder break.
  // Conflicting or out-of-order publications remain isolated until the recorder confirms them.
  if(!recorded&&last&&(last[0]>=stamp||last[4]>=event||stamp-last[0]>=660000))point[6]=false;
  const visible=recorded ? [...groups.slice(0,-1),[...groups.at(-1).slice(0,-1),point]] : [...recordedGroups,[point]];
  const coverage=tracksMeter?history?.capture_coverage:null;
  const gaps=tracksMeter?(coverage?.gaps||[]).filter(([a,b])=>a<stamp&&b>a).map(([a,b])=>[a,Math.min(b,stamp)]):recordedGroups.slice(1).map((group,i)=>[recordedGroups[i].at(-1)[0],group[0][0]]);
  let movement=null, midnight=history?.midnight, handoff=null;
  if(tracksMeter){
    const archive=latest.movement, tail=archive?.points?.at(-1);
    if(tail?.[2]===event&&tail[0]===stamp&&tail[1]===estimate){
      const prefix=history?.meter_prefix, first=archive.points[0];
      if(prefix?.points?.length && prefix.anchor?.every((v,i)=>v===first[i]) && prefix.anchor.length===3 &&
          prefix.points.at(-1)[0]<first[0] && prefix.points.at(-1)[2]<first[2]){
        movement=prefix.points.concat(archive.points);
        if(prefix.offset)handoff=first[0];
      }else movement=archive.points;
      midnight=midnight??archive.midnight;
    }else movement=[[stamp,estimate,event,0]];
  }
  dayView={visible,midnight,stamp,event,zone,day,key,gaps,historyStatus:saved?.status};
  if(selection!=='today'){showRolling();return;}
  activeSelection='today';host.dataset.endEvent=String(event);host.dataset.endTime=source.captured_at;
  $('interval-key').textContent='Hourly use';
  $('day-history-status').textContent=[handoff!=null?'Estimate basis changed at '+clock(handoff,zone):'',
    saved?.status==='unavailable'?'Saved history · refresh delayed':''].filter(Boolean).join(' · ');
  const hourly=new Map();
  const exactMs=t=>!/[1-9]/.test((/\.(\d+)/.exec(t)?.[1]||'').slice(3));
  for(const b of periods?.periods?.['24']?.bins||[]){
    const range=pair(b.lower,b.upper);
    // Clock bins start on exact local hours; the two outer partials may have microseconds.
    if(range&&exactMs(b.start)&&(b.end===source.captured_at||exactMs(b.end))){
      hourly.set(Date.parse(b.start),{end:Date.parse(b.end),range});
    }
  }
  drawDay(visible,midnight??stamp,zone,key,!history||history.refreshing&&!history.meter_prefix?'loading':null,midnight,recentWindow,null,gaps,hourly,movement,coverage);

}
async function day(daily,headline,recent){
  const key=headline?.source&&daily?.before&&daily.after&&daily.through&&daily.day===headline.day&&daily.timezone===headline.zone ? JSON.stringify([daily.day,daily.timezone,daily.through.camera,daily.through.format_id,
    daily.before.source_sha256,daily.after.source_sha256,daily.before.event_id,daily.before.captured_at,daily.after.event_id,daily.after.captured_at]) : '';
  const sameSaved=!!headline?.source&&lastRangeSource?.day===headline.day&&lastRangeSource.zone===headline.zone&&
    lastRangeSource.event===headline.source.event_id&&lastRangeSource.time===headline.source.captured_at&&lastRangeSource.digest===headline.source.source_sha256;
  if((key&&key!==identity)||(!key&&!headline?.source)){
    identity=key;generation++;saved=null;pending=false;due=0;lastRangeSource=null;
    $('day-history-status').textContent='';
  }
  if(key)lastRangeSource={day:daily.day,zone:daily.timezone,event:daily.through.event_id,time:daily.through.captured_at,digest:daily.through.source_sha256};
  latest=headline && {...headline,historyCompatible:Boolean(key)||sameSaved,sameDailyBounds:Boolean(key) && (headline.method==='nominal_meter_movement_v1' || headline.method==='range_midpoint_v1' && !['stale','partial_coverage'].includes(headline.status)) &&
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
  const newerCoverage=selection==='today' && saved?.capture_coverage && saved.status==='ready' &&
    headline?.movement?.points?.at(-1)?.[2]>saved.capture_coverage.through[0] && Date.now()-lastAttempt>=30000;
  if(!key||pending||Date.now()<due&&!newerCoverage){showDay();return;}
  lastAttempt=Date.now();
  const current=generation;pending=true; showDay();
  try{
    const res=await fetch('api/gas-trend',{cache:'no-store',signal:AbortSignal.timeout(6000)});
    if(!res.ok)throw Error('history');
    const data=await res.json();
    if(current!==generation)return;
    if(JSON.stringify(data.identity)===key && Array.isArray(data.groups)&&(data.groups.length||!saved?.groups?.length)){
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

// Bound changes in the saved daily total at both edges of each rolling interval.
// An interval extending before this calendar day has no same-day baseline.
function dailyWindow(view,hours){
  const end=view.stamp,start=end-hours*3600000,minutes=hours===1?15:hours===6?30:60;
  const points=view.visible.flat().filter(p=>p[2]!=null&&p[3]!=null&&(p[5]!=='Partial coverage'||p[6]===true));
  if(!points.length||view.midnight==null)return null;
  const times=points.map(p=>p[0]),lower=[],upper=[];
  for(let i=0;i<points.length;i++)lower[i]=Math.max(i?lower[i-1]:0,points[i][2]);
  for(let i=points.length-1;i>=0;i--)upper[i]=Math.min(upper[i+1]??Infinity,points[i][3]);
  function boundary(t){
    if(t===view.midnight)return [0,0];
    if(t<view.midnight||t<times[0]||t>times.at(-1))return null;
    let l=0,r=times.length;
    while(l<r){const i=(l+r)>>1;if(times[i]<t)l=i+1;else r=i;}
    // Recorder timestamps are millisecond-truncated; only the final publication is exact.
    const low=t===end&&times[l]===t?lower[l]:lower[l-1]??0;
    return low<=upper[l]?[low,upper[l]]:null;
  }
  const delta=(a,b)=>a&&b&&a[0]<=b[1]?[Math.max(0,cents(b[0],'floor')-cents(a[1],'ceil'))/100,
    (cents(b[1],'ceil')-cents(a[0],'floor'))/100]:null;
  const cuts=[start],step=minutes*60000;
  // Local minute alignment also handles half-hour DST transitions.
  let t=start+(step-((start+offsetAt(start,view.zone))%step));
  while(t<end){
    const remainder=(t+offsetAt(t,view.zone))%step;
    if(!remainder)cuts.push(t);
    t+=step-remainder;
  }
  cuts.push(end);
  const origin=boundary(start),bins=[];
  let left=origin;
  for(let i=1;i<cuts.length;i++){
    const right=boundary(cuts[i]),use=delta(left,right),total=delta(origin,right);
    bins.push({start:cuts[i-1],end:cuts[i],lower:use?.[0],upper:use?.[1],total_lower:total?.[0],total_upper:total?.[1]});
    left=right;
  }
  return {start,end,minutes,bins};
}
const asTime=t=>typeof t==='number'?t:Date.parse(t);
const pair=(lo,hi)=>lo!=null&&hi!=null&&Number.isFinite(+lo)&&Number.isFinite(+hi)&&+lo>=0&&+lo<=+hi?[+lo,+hi]:null;
let rollingDrawKey='';
function showRolling(){
  const host=$('day-curve'),hours=Number(selection);
  const selected=rolling?.periods?.[selection];
  const newerDay=selected&&rolling.compatibleWithDay&&rolling.notice==='Last saved'&&dayView?.stamp>asTime(selected.end)&&
    dayView.midnight!=null&&dayView.stamp-hours*3600000>=dayView.midnight;
  const key=JSON.stringify([selection,selected?rolling.key:null,selected?rolling.notice:null,dayView?.key]);
  if(key===rollingDrawKey)return;
  rollingDrawKey=key;activeSelection=selection;
  let period=selected;
  let useSaved=!!selected;
  if(!selected||newerDay){
    const current=dayView&&dailyWindow(dayView,hours);
    if(current&&(!selected||current.bins.every(b=>pair(b.total_lower,b.total_upper)))){
      period=current;
      useSaved=false;
      // Only interval amounts share a baseline across shifted windows. A prefix
      // measured from the previous window's start cannot constrain today's prefix.
      if(selected){
        const matches=new Map(selected.bins.map(b=>[asTime(b.start),b]));
        for(const bin of period.bins){
          const other=matches.get(bin.start);
          if(!other||asTime(other.end)!==bin.end||!pair(other.lower,other.upper))continue;
          const lo=Math.max(bin.lower??0,+other.lower),hi=Math.min(bin.upper??Infinity,+other.upper);
          bin.lower=lo<=hi?lo:null;bin.upper=lo<=hi?hi:null;
        }
      }
    }
  }
  const zone=useSaved?rolling.zone:dayView?.zone;
  if(!period?.bins?.length){
    delete host.dataset.endEvent;delete host.dataset.endTime;
    drawDay(null,null,null,null,'No saved readings for this window');return;
  }
  const start=asTime(period.start),end=asTime(period.end);
  const event=useSaved?rolling.through:latest.source;
  host.dataset.endTime=event.captured_at;host.dataset.endEvent=event.event_id;
  $('interval-key').textContent=period.minutes===60?'Hourly use':period.minutes+'-min use';
  const lastSaved=useSaved&&rolling.notice==='Last saved';
  const status=useSaved?rolling.notice: start<dayView.midnight?'Partial':'';
  const date=lastSaved?new Intl.DateTimeFormat(undefined,{timeZone:zone,month:'short',day:'numeric'}).format(end):'';
  $('day-history-status').textContent=[status,date,clockSpan(start,end,zone)].filter(Boolean).join(' · ');
  const runs=[],stops=[];
  let run=null;
  for(const bin of period.bins){
    const from=asTime(bin.start),to=asTime(bin.end),range=pair(bin.lower,bin.upper),total=pair(bin.total_lower,bin.total_upper);
    const p=total?[to,(total[0]+total[1])/2,...total,to===end?event.event_id:null]:null;
    if(p){
      if(!run||!range){
        run=from===start&&range?[[start,0,0,0,null]]:[];
        runs.push(run);
      }
      run.push(p);
    }
    if(!p||!range)run=null;
    stops.push({from,to,point:p,range,low:bin.lower});
  }
  const gaps=dayView?.zone===zone?dayView.gaps.filter(([a,b])=>a<end&&b>start).map(([a,b])=>[Math.max(start,a),Math.min(end,b)]):[];
  drawDay(runs,start,zone,key,null,null,null,stops,gaps);
}
function period(selectionValue,data){
  const next=['1','6','12','24'].includes(selectionValue)?selectionValue:'today';
  const changed=selection!==next,previousKey=rolling?.key,wasCompatible=rolling?.compatibleWithDay;
  selection=next;rolling=data;
  if(selection==='today'){
    if(changed||previousKey!==data?.key||wasCompatible!==data?.compatibleWithDay){rollingDrawKey='';showDay();}
  }else showRolling();
}
window.AIEdgeCharts={day,period};
})();
