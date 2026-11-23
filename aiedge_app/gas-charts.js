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
function rateTicks(edges,start,end,width,zone){
  if(start===end)return [{time:end,label:clock(end,zone)}];
  const format=timeFormat(zone,'minute'),labels=edges.map(t=>format.format(t).replace(':00',''));
  const ticks=edges.map((time,i)=>({time,label:labels.indexOf(labels[i])===labels.lastIndexOf(labels[i])?
    labels[i]:labels[i]+' '+zonePart(timeFormat(zone,'range'),time)}));
  const stride=Math.max(1,Math.ceil((ticks.length-1)/Math.max(1,Math.floor(width/53))));
  const room=(end-start)*49/width;
  return ticks.filter((tick,i)=>i===0||i===ticks.length-1||(i%stride===0&&tick.time<=end-room));
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
function trendPaths(run,x,y,band=true,line=true,smooth=true){
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
    if(!smooth)return ' L'+point(xx[j],run[j][k]);
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
function meterRuns(points,midnight,verified,extra){
  const runs=[];
  let prev,run,bucket,firstInRun;
  for(const p of points){
    const hour=Math.floor((p[0]-midnight)/3600000);
    const reset=!prev || typeof prev[3]!==typeof p[3] || hour>bucket+1 ||
      p[0]<=prev[0] || p[2]<=prev[2] || p[1]<prev[1];
    if(reset){run=[];runs.push(run);firstInRun=true;}
    if(!reset && hour===bucket && !firstInRun&&!extra?.has(prev[2]))run.pop();
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
// The publisher pairs this archive with the exact nominal state. On days without
// a midnight bracket the range recorder has no coverage map. The fine-dial
// archive still records its own anchor and the endpoints of each interruption.
function dialCoverage(archive,event,stamp,estimate){
  const points=archive?.points, gaps=archive?.dial_gaps, from=archive?.dial_from;
  if(!points?.length||!Array.isArray(gaps)||!from)return null;
  const first=points[0],tail=points.at(-1);
  if(first[2]!==from[0]||first[0]!==from[1]||tail[2]!==event||tail[0]!==stamp||tail[1]!==estimate)return null;
  if(!Number.isSafeInteger(archive.midnight)||archive.midnight>first[0])return null;
  let lastEnd=archive.midnight;
  for(const gap of gaps){
    if(!Array.isArray(gap)||gap.length!==2||!gap.every(Number.isSafeInteger)||
       gap[0]<lastEnd||gap[1]<=gap[0]||gap[1]>stamp)return null;
    lastEnd=gap[1];
  }
  const internal=gaps.filter(gap=>gap[1]>from[1]);
  let next=0,prior=null;
  for(const point of points){
    const [time,value,id,group]=point;
    if(!Number.isSafeInteger(time)||!Number.isFinite(value)||value<0||
       !Number.isSafeInteger(id)||id<=0||!Number.isSafeInteger(group)||group<0)return null;
    if(prior){
      if(time<=prior[0]||value<prior[1]||id<=prior[2])return null;
      const begin=next;
      while(next<internal.length&&internal[next][1]<=time)next++;
      // If the archive cannot locate every break between two saved knots,
      // keep the original disconnected groups.
      if(next-begin!==group-prior[3]||(next>begin&&internal[begin][0]<prior[0]))return null;
    }
    prior=point;
  }
  return next===internal.length?{first:from,through:[event,stamp],gaps:internal,fromFineDial:true}:null;
}
// Evidence is optional and arrives after the nominal chart has painted.
let trackedReply=null,trackedRequest=null,trackedBusy=false;
function requestTracked(headline){
  const archive=headline?.movement, source=headline?.source;
  if(!source||!archive?.dial_from||!archive.points?.length)return;
  const key=JSON.stringify([archive.format,archive.midnight,archive.dial_from,source.event_id,source.captured_at,source.source_sha256]);
  if(trackedBusy||trackedRequest===key)return;
  trackedRequest=key;trackedBusy=true;
  fetch('api/tracked-bounds'+(calendar?'?end='+calendar.end:''),{cache:'no-store',signal:AbortSignal.timeout(30000)})
    .then(r=>r.ok?r.json():null).then(data=>{
      if(trackedRequest!==key||data?.format!==archive.format||data.midnight!==archive.midnight||
         data.event!==source.event_id||data.measured_at!==source.captured_at||data.digest!==source.source_sha256||
         JSON.stringify(data.anchor)!==JSON.stringify(archive.dial_from)||!Array.isArray(data.edges)||!Array.isArray(data.joins))return;
      trackedReply=data;showDay();
    }).catch(()=>{trackedRequest=null;}).finally(()=>{
      trackedBusy=false;
      if(latest?.source&&latest.source.event_id!==source.event_id)requestTracked(latest);
    });
}
function trackedRanges(movement,coverage){
  const totals=new Map(),uses=new Map(),edges=coverage?.edges;
  if(!edges||!movement?.length)return {totals,uses};
  const opening=movement[0][2]===coverage.first[0];
  let sum=[0,0];
  totals.set(movement[0][2],[0,0]);
  const valid=r=>Array.isArray(r)&&r.length===2&&r.every(Number.isSafeInteger)&&0<=r[0]&&r[0]<=r[1];
  for(let i=1;i<movement.length;i++){
    const [at,,id]=movement[i],a=movement[i-1];
    const edge=edges.find(e=>e.end?.[0]===id&&e.end[1]===at&&e.start?.[0]===a[2]&&e.start[1]===a[0]);
    if(!valid(edge?.use)){sum=null;continue;}
    uses.set(id,edge.use.map(v=>v/100));
    if(opening&&valid(edge.total))sum=edge.total;
    else if(sum)sum=sum.map((v,j)=>v+edge.use[j]);
    if(sum)totals.set(id,sum.map(v=>v/100));
  }
  return {totals,uses};
}
function intervalRate(s){
  const tracked=s.tracked,q=s.hour;
  const from=tracked?.from??q?.start??s.from,to=tracked?s.point[0]:s.to;
  const bounds=tracked?tracked.range:s.range;
  const volume=q?.use??tracked?.amount??(bounds?(bounds[0]+bounds[1])/2:null);
  if(from==null||to<=from||volume==null)return null;
  const factor=3600000/(to-from);
  return {value:volume*factor,bounds:bounds?.map(v=>v*factor),volume};
}
function rateRange(bounds){
  return bounds.map((v,i)=>number.format(cents(v,i?'ceil':'floor')/100)).join('–')+' ft³/h';
}
function chart(){
  const host=$('day-curve'),tip=$('day-tip');
  const title=$('day-tip-title'),amount=$('day-tip-amount'),note=$('day-tip-note');
  const graphic=svg('svg',{'aria-hidden':'true'});
  host.append(graphic);
  let model,chosen,atX,atY,usageY,cursor,dot,active=-1,inspecting=false,drawnWidth=0,plotBottom=0;
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
    const interval=stop.tracked?clockSpan(stop.tracked.from,p[0],model.zone):
      stop.from==null?'':clockSpan(stop.from,stop.to,model.zone);
    let used=stop.low>0?'At least '+number.format(stop.low)+' ft³ used':'Interval unavailable';
    if(stop.range){
      const [lo,hi]=stop.range;
      used=lo===0&&hi>0?'Up to '+number.format(hi)+' ft³ used':number.format((lo+hi)/2)+' ft³ used';
    }
    title.textContent=interval||clock(stop.to,model.zone,true);
    amount.textContent=p?.[1]!=null?(model.trackedWindow?'Tracked ':'Total ')+number.format(p[1])+' ft³':model.movement?
      (model.loadingHistory?'Loading saved total':'No verified total this hour'):'Total unavailable';
    if(stop.tracked){
      used=number.format(stop.tracked.amount)+' ft³ tracked'+(stop.tracked.partial?' · partial coverage':'');
      if(stop.tracked.range)used+=' ('+stop.tracked.range.map(v=>number.format(v)).join('–')+' ft³)';
      const totalRange=model.bounds.totals.get(p[4]);
      if(totalRange)amount.textContent='Tracked total '+number.format(p[1])+' ft³ ('+totalRange.map(v=>number.format(v)).join('–')+')';
    }
    note.textContent=stop.tracked?used+' · '+clock(p[0],model.zone,true):
      model.trackedWindow?'Since '+clock(model.movement[0][0],model.zone,true):model.movement && p ? used+' · '+clock(p[0],model.zone,true) : used;
    if(stop.tracked?.range&&model.trackedWindow&&stop.tracked.from===model.movement[0][0]){
      amount.textContent=number.format(stop.tracked.amount)+' ft³ tracked';
      note.textContent='Range '+stop.tracked.range.map(v=>number.format(v)).join('–')+' ft³'+(stop.tracked.partial?' · partial coverage':'');
    }
    if(!model.summary&&stop.rate)note.textContent+=' · Rate '+number.format(stop.rate.value)+' ft³/h';
    if(model.summary){
      title.textContent=new Intl.DateTimeFormat(undefined,{timeZone:model.zone,month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(stop.to);
      amount.textContent=stop.reset?'Daily total resets to 0 ft³':p?
        'Cumulative estimate '+number.format(p[1])+' ft³':'Gas rate';
      const details=[];
      if(!stop.hour&&p?.[2]!=null&&p[3]!=null)details.push('Range '+number.format(p[2])+'–'+number.format(p[3])+' ft³');
      if(stop.reset)details.push('Calendar opening balance');
      if(stop.hour){
        const q=stop.hour;
        title.textContent=clockSpan(q.start,q.end,model.zone);
        amount.textContent=number.format(stop.rate.value)+' ft³/h';
        details.push(number.format(q.use)+' ft³ used');
        if(q.basis==='register'||q.basis==='photo_replay'||q.basis==='carried_register'){
          const register=new Intl.NumberFormat(undefined,{minimumFractionDigits:5,maximumFractionDigits:5});
          details.push(register.format(q.closing)+' − '+register.format(q.opening)+' ft³');
          if(q.carry)details.push(clock(q.carry.start,model.zone)+' meter reading + '+number.format(q.carry.use)+' ft³');
        }
        if(stop.rate.bounds)details.push('Rate range '+rateRange(stop.rate.bounds));
        if(q.basis==='photo_replay')details.push('Reconstructed from saved frames');
        if(stop.cumulative){
          const c=stop.cumulative;
          const range=c[2]!=null&&c[3]!=null?' (range '+number.format(c[2])+'–'+number.format(c[3])+' ft³)':'';
          details.push('Cumulative estimate '+number.format(c[1])+' ft³'+range);
        }
      }
      if(stop.unknownHour){
        title.textContent=clockSpan(stop.unknownHour,stop.to,model.zone);
        amount.textContent='Rate unknown';
        details.length=0;
        details.push('Meter readings do not establish the difference');
      }
      note.textContent=details.join(' · ');
    }
    host.setAttribute('aria-valuenow',i);
    const rangeText=(lo,hi)=>lo!=null&&hi!=null?number.format(lo)+'–'+number.format(hi)+' ft³':'';
    host.setAttribute('aria-valuetext',[title.textContent,amount.textContent,rangeText(p?.[2],p?.[3]),model.summary||model.trackedWindow||stop.rate?note.textContent:used,
      stop.rate?.bounds&&rateRange(stop.rate.bounds),p?.[5]].filter(Boolean).join(' · '));
    tip.hidden=!show;
    const px=atX(stop.tracked?p[0]:stop.to),level=p?.[1]??p?.[2];
    const py=stop.hour?usageY(stop.rate.value):level==null?plotBottom/2:atY(level);
    tip.dataset.hour=String(!!stop.hour);
    if(show){
      const position=px<drawnWidth/2?(px+9)+'px':'calc('+(px-9)+'px - var(--tip-width))';
      tip.style.left='clamp(0px, '+position+', calc(100% - var(--tip-width)))';
      const height=tip.offsetHeight||0;
      const preferred=py>height+10?py-height-8:py+8;
      tip.style.top=Math.max(0,Math.min(preferred,plotBottom-height))+'px';
    }
    cursor.setAttribute('visibility',show?'visible':'hidden');
    cursor.setAttribute('transform','translate('+px+' 0)');
    dot.setAttribute('class',stop.hour?'plot-selected-use':'plot-estimate-dot');
    dot.setAttribute('visibility',show&&(stop.hour||p?.[1]!=null)?'visible':'hidden');
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
      return {max,y:v=>bottom-(bottom-top)*v/max};
    }
    const totalLabel=$('total-key-label');
    $('chart-legend').hidden=false;
    const total=scale(Math.max(0,...points.map(p=>Math.max(p[3]??0,p[1]??0)),...(model.summary?.extent||[]),...(model.movement||[]).map(p=>p[1]),
      ...Array.from(model.bounds.totals.values(),r=>r[1])));
    const intervals=model.stops.filter(s=>s.rate);
    const useKey=$('use-series-key'),tracked=intervals.some(s=>s.tracked);
    useKey.dataset.tracked=String(tracked&&!intervals.some(s=>s.tracked?.range||s.range));
    useKey.title='Average gas rate and supported range, right axis';
    $('interval-key').textContent='Rate (ft³/h)';
    useKey.hidden=!intervals.length;
    if(totalLabel)totalLabel.textContent=(model.trackedWindow||model.coverage?.edges?'Tracked total':model.movement?'Hourly total trend':'Total')+(intervals.length?' · left':'');
    if(model.summary){
      if(totalLabel){
        totalLabel.textContent='Cumulative'+(intervals.length?' · left':'');
        totalLabel.parentElement.title='Cumulative gas use in ft³. The solid line shows the meter estimate. Shading spans its lower and upper bounds.';
      }
      useKey.title='Meter change divided by elapsed time, in cubic feet per hour';
    }
    const usage=scale(Math.max(0,...intervals.map(s=>Math.max(s.rate.bounds?.[1]??0,s.rate.value))));
    const end=model.stops.at(-1).to, span=Math.max(1,end-start);
    const x=t=>end===start?(left+right)/2:left+(right-left)*(t-start)/span,y=total.y;
    atX=x; atY=y; usageY=usage.y; drawnWidth=w; plotBottom=bottom;
    graphic.setAttribute('viewBox','0 0 '+w+' '+h);
    graphic.style.height=h+'px';
    const nodes=[];
    const tickLabel=v=>Number(v.toPrecision(6)).toLocaleString(undefined,{maximumSignificantDigits:4,notation:v>=1000?'compact':'standard'});
    const gridIntervals=4;
    for(let i=0;i<=gridIntervals;i++){
      const fraction=i/gridIntervals,pos=bottom-(bottom-top)*fraction;
      nodes.push(svg('line',{x1:left,x2:right,y1:pos,y2:pos,class:'plot-grid'}),
        svg('text',{x:left-7,y:pos+4,'text-anchor':'end',class:'total-tick'},tickLabel(total.max*fraction)));
      if(intervals.length)nodes.push(svg('text',{x:right+7,y:pos+4,class:'use-tick'},tickLabel(usage.max*fraction)));
    }
    const runs=model.rolling?groups:hourlyRuns(groups,model.rangeStops);
    const lines=[];
    if(model.summary){
      const defs=svg('defs');
      for(const [i,series] of model.summary.series.entries()){
        const clip=svg('clipPath',{id:'daily-span-'+i,clipPathUnits:'userSpaceOnUse'});
        const from=Math.max(start,series.run[0][0]);
        const until=Math.min(end,series.run.at(-1)[0]);
        if(until>from)clip.append(svg('rect',{x:x(from),y:0,width:x(until)-x(from),height:h}));
        defs.append(clip);
        const clipped=svg('g',{'clip-path':'url(#daily-span-'+i+')','data-day-series':i});
        const run=series.run;
        clipped.append(...trendPaths(run,x,y,false,true,false).lines);
        let band=[];
        function shade(){
          if(band.length>1){
            const area=trendPaths(band,x,y,true,false,false).bands[0];
            clipped.insertBefore(area,clipped.firstChild);
            for(const k of [2,3]){
              const side=trendPaths(band.map(p=>[p[0],p[k],p[k],p[k]]),x,y,false,true,false).lines[0];
              side.setAttribute('class','plot-bound-edge');clipped.append(side);
            }
          }
          band=[];
        }
        for(const p of run){
          if(p[2]==null||p[3]==null)shade();
          if(p[2]!=null&&p[3]!=null)band.push(p);
        }
        shade();nodes.push(clipped);
        for(const p of run)if(start<=p[0]&&p[0]<=end){
          if(p[2]!=null&&p[3]>p[2]&&run.length===1)nodes.push(svg('line',{class:'plot-bound-edge',x1:x(p[0]),x2:x(p[0]),y1:y(p[2]),y2:y(p[3])}));
          lines.push(svg('circle',{cx:x(p[0]),cy:y(p[1]),r:2,class:'plot-estimate-dot','data-event':p[4],
            'data-time':p[0],'data-total':p[1],...(p[2]==null||p[3]==null?{}:{'data-low':p[2],'data-high':p[3]})}));
        }
      }
      nodes.push(defs);
      for(const t of model.summary.resets){
        const px=x(t);
        nodes.push(svg('line',{x1:px,x2:px,y1:top,y2:bottom,class:'plot-midnight'}));
        const close=model.summary.closes.get(t);
        if(close)lines.push(svg('line',{x1:px,x2:px,y1:y(close[1]),y2:y(0),class:'plot-estimate'}));
        lines.push(svg('circle',{cx:px,cy:y(0),r:3.5,class:'plot-reset','data-midnight':t}));
      }
    }
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
      for(const run of meterRuns(model.movement,model.midnight??start,!!model.coverage,model.coverage?.extra)){
        let band=[];
        for(const p of run){
          const range=model.bounds.totals.get(p[4]);
          if(!range||!model.bounds.uses.has(p[4])){
            if(band.length>1)drawRun(band,true,false);
            band=[];
          }
          if(range){[p[2],p[3]]=range;band.push(p);}
        }
        if(band.length>1)drawRun(band,true,false);
        drawRun(run,false,true);
      }
    }
    {
      const gapKey=$('day-gap-key');
      gapKey.hidden=!model.gaps.length;
      gapKey.title=model.summary||model.coverage?'Interruption in saved captures or meter tracking':'Break between published estimates';
      if(gapKey.lastChild?.nodeType===3)gapKey.lastChild.textContent=model.summary||model.coverage?'Reading gap':'History break';
      for(const [from,to] of model.gaps){
        nodes.push(svg('line',{class:'plot-history-gap',x1:x(from),x2:x(to),y1:bottom+2,y2:bottom+2,
          stroke:'var(--series)','stroke-width':3,'stroke-linecap':model.coverage?'butt':'round','data-from':from,'data-to':to}));
      }
    }
    nodes.push(...lines);
    for(const stop of model.stops){
      if(!stop.rate)continue;
      const measured=stop.tracked,range=stop.rate.bounds;
      const px=x(measured?stop.point[0]:stop.to),attrs=measured?{'data-through-event':stop.point[4]}:stop.hour?{'data-hour-end':stop.to,'data-start':stop.hour.start,'data-use':stop.hour.use,'data-rate':stop.rate.value}:{};
      if(range&&range[1]>range[0]){
        const [lo,hi]=range,cap=Math.min(4,Math.max(1,(px-x(measured?.from??stop.hour?.start??stop.from))/4));
        nodes.push(svg('path',{class:'plot-whisker',...attrs,d:'M'+(px-cap)+' '+usage.y(hi)+'h'+(cap*2)+' M'+px+' '+usage.y(hi)+'V'+usage.y(lo)+' M'+(px-cap)+' '+usage.y(lo)+'h'+(cap*2)}));
      }
      const py=usage.y(stop.rate.value);
      nodes.push(svg('circle',{class:'plot-usage-dot',...attrs,cx:px,cy:py,r:stop.hour?5:3.1}));
    }
    let ticks=model.summary?rateTicks(model.summary.edges,start,end,right-left,zone):
      model.rolling&&!model.trackedWindow?intervalTicks(model.stops,start,end,right-left,zone):axisTicks(start,end,right-left,zone);
    if(model.summary?.resets.length){
      ticks=ticks.filter(t=>model.summary.resets.every(r=>Math.abs(x(r)-x(t.time))>55));
      ticks.push(...model.summary.resets.map(time=>({time,label:'Midnight'})));
    }
    for(const tick of ticks){
      const px=x(tick.time);
      const halfLabel=tick.label.length*3.4;
      const anchor=px<halfLabel?'start':px>w-halfLabel?'end':'middle';
      nodes.push(svg('line',{x1:px,x2:px,y1:bottom,y2:bottom+4,class:'plot-tick'}),
        svg('text',{x:px,y:h-6,'text-anchor':anchor,class:'time-tick'},tick.label));
    }
    cursor=svg('g',{class:'plot-cursor',visibility:'hidden','pointer-events':'none'});
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
  return function update(groups, start, zone, key, empty, midnight, recent, clockBins, gaps=[], hourly=null, movement=null, coverage=null,summary=null) {
    if(!groups?.length&&!clockBins?.length){
      $('chart-legend').hidden=true;
      model=null; chosen=null; graphic.replaceChildren(); host.hidden=true;
      hide();active=-1;cursor=null;dot=null;drawnWidth=0;
      host.setAttribute('aria-valuetext','');
      $('day-history-status').textContent=empty||'';$('day-gap-key').hidden=true;
      return;
    }
    if(model?.key===key)return;
    const previous=model?.stops.at(-1);
    if(!previous || chosen===(previous.from??previous.to))chosen=null;
    const rangeStops=clockBins||dayHours(groups.flat(),midnight,recent,hourly)
      .filter(stop=>stop.to>start||stop.to===groups.at(-1).at(-1)[0]);
    const stops=movement&&!clockBins?rangeStops.map(stop=>{
      const p=movement.findLast(p=>(stop.from==null||p[0]>=stop.from)&&
        (p[0]<stop.to||stop.to===movement.at(-1)[0]&&p[0]===stop.to));
      const same=p&&p[2]===stop.point?.[4];
      return {...stop,point:p?[p[0],p[1],same?stop.point[2]:null,same?stop.point[3]:null,p[2]]:null};
    }):rangeStops;
    if(!clockBins&&coverage?.extra?.size){
      for(const [time,value,id] of movement){
        if(coverage.extra.has(id)&&!stops.some(s=>s.point?.[4]===id))
          stops.push({from:null,to:time,point:[time,value,null,null,id]});
      }
      stops.sort((a,b)=>a.to-b.to);
    }
    const bounds=trackedRanges(movement,coverage);
    if(coverage?.fromFineDial&&movement){
      const increments=new Map();
      for(let i=1;i<movement.length;i++){
        const a=movement[i-1],b=movement[i];
        if(a[2]<coverage.first[0]||a[0]<start||coverage.gaps.some(([l,r])=>l<=a[0]&&r>=b[0]))continue;
        const amount=(Math.round(b[1]*100)-Math.round(a[1]*100))/100;
        increments.set(b[2],{from:a[0],amount,range:bounds.uses.get(b[2]),
          partial:coverage.gaps.some(([l,r])=>l<b[0]&&r>a[0])});
      }
      for(const s of stops)if(!s.range||increments.get(s.point?.[4])?.range)s.tracked=increments.get(s.point?.[4]);
    }
    for(const s of stops)s.rate=intervalRate(s);
    const points=clockBins?stops.map(s=>s.point||[s.to,null,null,null]):groups.flat();
    model={groups,points,stops,rangeStops,movement,coverage,bounds,start,midnight,zone,key,summary,rolling:!!clockBins,trackedWindow:!!movement&&!!clockBins,gaps,loadingHistory:empty==='loading'};
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
let calendar=null,browsing=null;
function localOpening(end,zone){
  const fmt=new Intl.DateTimeFormat('sv-SE',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'});
  const day=fmt.format(end);
  let lo=end-36*3600000,hi=end;
  while(hi-lo>1){
    const mid=lo+Math.floor((hi-lo)/2);
    if(fmt.format(mid)===day)hi=mid;else lo=mid;
  }
  return hi;
}
const hourMs=3600000;
function rateMinutes(selection,elapsed){
  const span=selection==='today'?elapsed/hourMs:Number(selection);
  return span<=1?10:span<=6?60:span<=12?120:240;
}
function completedTick(stamp,zone,minutes){
  return stamp-(stamp+offsetAt(stamp,zone))%(minutes*60000);
}
function loadCalendar(stamp,zone,minutes){
  const current={end:stamp,zone,midnight:localOpening(stamp,zone),minutes,data:null,status:'loading'};
  fetch('api/chart-hours?end='+stamp+(minutes===60?'':'&minutes='+minutes),
    {cache:'no-store',signal:AbortSignal.timeout(45000)})
    .then(async r=>{
      if(!r.ok)throw Error();
      const data=await r.json();
      if(data.end!==stamp||data.zone!==zone||data.midnight!==current.midnight||
         (data.minutes??60)!==minutes||!Array.isArray(data.hours)||!Array.isArray(data.groups))throw Error();
      current.data=data;current.status='ready';
    }).catch(()=>{current.status='unavailable';}).finally(()=>{
      if(current===calendar||current===detail||current===browsing?.fine)showSummary(dayView);
    });
  return current;
}
let manualChartRefresh=false,detail=null,calendarStamp=0,visibleSummary=null;
window.addEventListener('aiedge-refresh-images',()=>{manualChartRefresh=true;});
function requestDetail(){
  if(browsing||!calendar||rateMinutes(selection,calendarStamp-calendar.midnight)!==10)return;
  if(detail?.zone===calendar.zone&&completedTick(detail.end,calendar.zone,10)===completedTick(calendarStamp,calendar.zone,10))return;
  detail=loadCalendar(calendarStamp,calendar.zone,10);
}
function setCalendar(zone,stamp){
  if(!zone || (calendar && calendar.zone!==zone)){
    browsing=null;calendar=null;detail=null;visibleSummary=null;
    $('gas-period-row').hidden=true;$('gas-latest').hidden=true;
    if(!zone)return;
  }
  calendarStamp=stamp?Date.parse(stamp):Date.now();
  const fresh=manualChartRefresh;
  manualChartRefresh=false;
  if(fresh||calendar?.zone!==zone||completedTick(calendarStamp,zone,60)!==completedTick(calendar.end,zone,60)||
     stamp&&!calendar.pinned){
    calendar=loadCalendar(calendarStamp,zone,60);
    calendar.pinned=!!stamp;
    detail=null;
  }
  requestDetail();
}
// Close a rate interval on the local clock. A clipped edge uses its actual elapsed time.
// A missing constituent reading leaves the entire average unknown.
function rateBuckets(rows,start,end,minutes,zone){
  if(start>=end)return [];
  const byStart=new Map(rows.map(q=>[q.start,q])),groups=[];
  let from=start;
  const width=minutes*60000,offset=offsetAt(start,zone),fixed=offset===offsetAt(end,zone);
  const firstCut=fixed?start+width-(start+offset)%width:start+60000;
  for(let t=Math.min(firstCut,end);;t=Math.min(t+(fixed?width:60000),end)){
    if(!fixed&&t!==end&&(t+offsetAt(t,zone))%width!==0)continue;
    let at=from,use=0,lo=0,hi=0,bounded=true,first=byStart.get(from);
    while(at<t){
      const q=byStart.get(at);
      if(!q||q.end<=at||q.end>t)break;
      use+=q.use;
      if(q.bounds){lo+=q.bounds[0];hi+=q.bounds[1];}else bounded=false;
      at=q.end;
    }
    groups.push(at!==t?{start:from,end:t}:first.end===t?first:
      {start:from,end:t,use,bounds:bounded?[lo,hi]:null,basis:'sum'});
    if(t===end)break;
    from=t;
  }
  return groups;
}
function showSummary(view){
  const hourly=browsing?.hourly??calendar;
  const {zone,midnight,data}=hourly;
  const stamp=browsing?.end??calendarStamp;
  const elapsed=browsing?browsing.end-browsing.start:stamp-midnight;
  const minutes=rateMinutes(selection,elapsed),fine=minutes===10;
  const short=browsing?browsing.fine:detail;
  const source=fine?short:hourly;
  const end=browsing?.end??completedTick(source?.end??stamp,zone,fine?10:60);
  const start=browsing?.start??(selection==='today'?midnight:end-Number(selection)*hourMs);
  if(browsing)view=browsing.view;
  updateNavigation(hourly,start,end);
  const status=hourly.status==='ready'?(source?.status??'loading'):hourly.status;
  if(!browsing&&status==='loading'&&visibleSummary?.selection===selection&&visibleSummary.zone===zone&&visibleSummary.midnight===midnight)return;
  visibleSummary=status==='ready'?{selection,zone,midnight}:null;
  const key=JSON.stringify(['rate',selection,minutes,start,end,status,hourly.end,source?.end,view?.key]);
  const host=$('day-curve'),stops=new Map(),series=[],extent=[];
  const stop=t=>{
    if(!stops.has(t))stops.set(t,{from:null,to:t,point:null});
    return stops.get(t);
  };
  const hours=data?.hours||[], byEnd=new Map(hours.map(q=>[q.end,q]));
  const resets=(data?.resets||[midnight]).filter(t=>start<=t&&t<=end);
  const knots=new Map(),closes=new Map();
  const dailySamples=[...(data?.dailyHours||[]),...(fine?short?.data?.dailyHours||[]:[])];
  const dailyTimes=new Set(dailySamples.map(p=>p[0]));
  const sample=(time,value,low,high,event=null)=>[time,value,low,high,event];
  for(const row of dailySamples)knots.set(row[0],sample(...row));
  const midnightTicks=new Set(data?.resets||[midnight]);
  for(const t of midnightTicks)knots.set(t,sample(t,0,0,0));
  if(view?.movement){
    const ranges=trackedRanges(view.movement,view.coverage).totals;
    const dailyRanges=new Map(view.visible.flat().filter(p=>p[2]!=null&&p[3]!=null&&p[6]!==false)
      .map(p=>[p[4],p.slice(2,4)]));
    const readings=new Map(view.movement.map(p=>[p[2],p]));
    for(const offset of [...(data?.offsets||[]),...(fine?short?.data?.offsets||[]:[])]){
      const source=readings.get(offset.event);
      if(!source||offset.time<midnight||midnightTicks.has(offset.time))continue;
      const range=ranges.get(offset.event)||dailyRanges.get(offset.event);
      knots.set(offset.time,sample(offset.time,source[1]+offset.use,
        range?range[0]+offset.bounds[0]:null,range?range[1]+offset.bounds[1]:null,offset.event));
    }
  }
  // Each completed hour contributes its measured change to the daily estimate.
  // Start with an independently established daily level after a missing hour.
  for(const q of hours){
    const before=knots.get(q.start);
    if(!before)continue;
    const direct=knots.get(q.end);
    // Previous-day recorder totals represent the entire day and stand on their own.
    if(q.end<midnight&&direct&&!midnightTicks.has(q.end))continue;
    const destination=midnightTicks.has(q.end)?closes:knots;
    destination.set(q.end,sample(q.end,before[1]+q.use,
      before[2]!=null&&q.bounds?before[2]+q.bounds[0]:null,
      before[3]!=null&&q.bounds?before[3]+q.bounds[1]:null,direct?.[4]));
  }
  const samples=source?.data?.hours||[];
  if(fine){
    for(const q of samples){
      byEnd.set(q.end,q);
      const before=knots.get(q.start);
      if(!before||knots.has(q.end)&&!midnightTicks.has(q.end))continue;
      const target=midnightTicks.has(q.end)?closes:knots;
      if(!target.has(q.end))target.set(q.end,sample(q.end,before[1]+q.use,
        before[2]!=null&&q.bounds?before[2]+q.bounds[0]:null,
        before[3]!=null&&q.bounds?before[3]+q.bounds[1]:null));
    }
  }
  const spacing=(fine?10:60)*60000;
  function add(run){
    if(!run.length||run.at(-1)[0]<start||run[0][0]>end)return;
    const first=run.findIndex(p=>p[0]>=start);
    const visible=run.slice(Math.max(0,first-1));
    series.push({run:visible});
    for(const p of visible){
      extent.push(Math.max(p[1],p[3]??0));
      if(start<=p[0]&&p[0]<=end)stop(p[0]).point=p;
    }
  }
  let run=[];
  for(const [t,p] of [...knots].sort((a,b)=>a[0]-b[0])){
    if(t>end)break;
    const previous=run.at(-1);
    if(previous&&(t-previous[0]!==spacing||fine&&byEnd.get(t)?.start!==previous[0]||midnightTicks.has(t)||p[1]<previous[1]||
       midnightTicks.has(previous[0])&&!byEnd.has(t)&&!dailyTimes.has(t))){
      if(closes.has(t)&&previous[0]===t-spacing&&(!fine||byEnd.get(t)?.start===previous[0]))run.push(closes.get(t));
      add(run);run=[];
    }
    run.push(p);
  }
  add(run);
  // A prior day can end with a single saved observation before the next hour.
  // Preserve it at its actual time when there is no clock reading in the window.
  for(const group of data?.groups||[]){
    const last=group.at(-1);
    if(last&&last[0]>=start&&last[0]<=end&&last[0]<midnight&&
       ![...knots.keys()].some(t=>t>=Math.max(group[0][0],start)&&t<=last[0])){
      add([last]);
    }
  }
  for(const t of resets)stop(t).reset=true;
  const buckets=rateBuckets(samples,start,end,minutes,zone),unknown=[];
  for(const q of buckets){
    const s=stop(q.end);
    if(q.use==null){
      s.unknownHour=q.start;unknown.push([q.start,q.end]);
    }else{
      s.hour=q;s.range=q.bounds;s.cumulative=s.reset?null:s.point;
    }
  }
  stop(end);
  const ordered=[...stops.values()].sort((a,b)=>a.to-b.to);
  if(view){
    if(browsing){delete host.dataset.endEvent;host.dataset.endTime=new Date(end).toISOString();}
    else{host.dataset.endEvent=String(view.event);host.dataset.endTime=latest.source.captured_at;}
  }else{delete host.dataset.endEvent;delete host.dataset.endTime;}
  const message=status==='loading'?'Loading meter readings…':status==='unavailable'?'Meter history unavailable':
    data?.missing?.includes('daily')&&start<midnight?'Previous daily totals unavailable':
    source?.data?.missing?.includes('register')&&!samples.length?'Meter history unavailable':
    !buckets.some(q=>q.use!=null)?'No supported rate in this window':'';
  const missingHour=status==='ready'&&unknown.length===1?'Rate unknown '+clockSpan(...unknown[0],zone):'';
  $('day-history-status').textContent=[minutes<60?minutes+'-min averages':minutes/60+'-hour averages',view?.partialCoverage||browsing&&start<hourly.end-25*hourMs?'Partial daily total':'',missingHour,message||'Through '+clock(end,zone)].filter(Boolean).join(' · ');
  drawDay([],start,zone,key,null,midnight,null,ordered,[],null,null,null,
    {series,extent,resets,closes,edges:[start,...buckets.map(q=>q.end)]});
}
let identity='', saved=null, lastRangeSource=null, generation=0, due=0, lastAttempt=0, pending=false, latest=null, recentWindow=null;
function showDay(){
  const host=$('day-curve');
  const source=latest?.source;
  if(!source){
    dayView=null;
    if(calendar){showSummary(null);return;}
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
  const loading=!history?.groups?.length && (pending || saved?.status==='loading');
  const reply=trackedReply?.event===event&&trackedReply?.measured_at===source.captured_at&&trackedReply.digest===source.source_sha256&&
    trackedReply.format===latest.movement?.format&&trackedReply.midnight===latest.movement?.midnight&&
    JSON.stringify(trackedReply.anchor)===JSON.stringify(latest.movement?.dial_from)?trackedReply:null;
  const key=JSON.stringify([identity,history?.revision,latest,recentWindow,periods?.key,loading,reply]);
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
  let coverage=tracksMeter?history?.capture_coverage:null;
  const partialCoverage=tracksMeter&&(!coverage||reply?.edges.length)?dialCoverage(latest.movement,event,stamp,estimate):null;
  if(partialCoverage&&reply){
    partialCoverage.edges=reply.edges;
    partialCoverage.gaps=partialCoverage.gaps.filter(([a,b])=>!reply.joins.some(j=>j[0]===a&&j[1]===b));
    // An independent recorder can also establish an interruption.
    for(const gap of coverage?.gaps||[])if(!partialCoverage.gaps.some(([a,b])=>a===gap[0]&&b===gap[1]))partialCoverage.gaps.push(gap);
    partialCoverage.gaps.sort((a,b)=>a[0]-b[0]);
  }
  const dialFrom=latest.movement?.dial_from, tail=latest.movement?.points?.at(-1);
  if(coverage&&dialFrom&&tail?.[2]===event&&tail[0]===stamp&&tail[1]===estimate&&
     dialFrom[0]<=coverage.through[0]&&dialFrom[1]<=coverage.through[1]&&
     coverage.through[0]<event&&coverage.through[1]<stamp){
    coverage={...coverage,through:[event,stamp]};
  }
  const dialGaps=tracksMeter?latest.movement?.dial_gaps:null;
  let evidenceGaps=coverage?.gaps||[];
  if(!partialCoverage&&Array.isArray(dialGaps)&&dialGaps.length&&dialGaps.every(g=>
    Array.isArray(g)&&g.length===2&&g.every(Number.isSafeInteger)&&g[0]<g[1])){
    const combined=[];
    for(const [start,end] of [...evidenceGaps,...dialGaps].sort((a,b)=>a[0]-b[0])){
      const prior=combined.at(-1);
      if(prior&&start<=prior[1])prior[1]=Math.max(prior[1],end);
      else combined.push([start,end]);
    }
    evidenceGaps=combined;
    if(coverage)coverage={...coverage,gaps:combined};
  }
  if(partialCoverage){
    coverage=partialCoverage;
    evidenceGaps=partialCoverage.gaps;
  }
  const gaps=tracksMeter?evidenceGaps.filter(([a,b])=>a<stamp&&b>a).map(([a,b])=>[a,Math.min(b,stamp)]):recordedGroups.slice(1).map((group,i)=>[recordedGroups[i].at(-1)[0],group[0][0]]);
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
  if(partialCoverage?.edges&&movement===latest.movement.points){
    const extra=[];
    for(const e of partialCoverage.edges){
      if(!Array.isArray(e.point)||e.point.length!==4)continue;
      const i=movement.findIndex(p=>p[2]===e.start[0]&&p[0]===e.start[1]),a=movement[i],b=movement[i+1];
      const [t,value,id,group]=e.point;
      if(a&&b&&b[2]===e.until?.[0]&&b[0]===e.until[1]&&t===e.end[1]&&id===e.end[0]&&
         a[0]<t&&t<b[0]&&a[2]<id&&id<b[2]&&a[1]<=value&&value<=b[1]&&Number.isSafeInteger(group))
        extra.push(e.point);
    }
    if(extra.length){
      const all=[...movement,...extra].sort((a,b)=>a[2]-b[2]);
      if(dialCoverage({...latest.movement,points:all},event,stamp,estimate)){
        movement=all;
        partialCoverage.extra=new Set(extra.map(p=>p[2]));
      }
    }
  }
  dayView={visible,midnight,stamp,event,zone,day,key,gaps,movement,coverage,partialCoverage,historyStatus:saved?.status};
  if(calendar){showSummary(dayView);return;}
  if(selection!=='today'){showRolling();return;}
  activeSelection='today';host.dataset.endEvent=String(event);host.dataset.endTime=source.captured_at;
  $('day-history-status').textContent=[handoff!=null?'Estimate basis changed at '+clock(handoff,zone):
    partialCoverage&&dialFrom[1]>midnight?'Coverage starts at '+clock(dialFrom[1],zone):'',
    latest.savedOnly?'Last saved · '+clock(stamp,zone):saved?.status==='unavailable'?'Saved history · refresh delayed':''].filter(Boolean).join(' · ');
  const hourly=new Map();
  const exactMs=t=>!/[1-9]/.test((/\.(\d+)/.exec(t)?.[1]||'').slice(3));
  for(const b of periods?.periods?.['24']?.bins||[]){
    const range=pair(b.lower,b.upper);
    // Clock bins start on exact local hours; the two outer partials may have microseconds.
    if(range&&exactMs(b.start)&&(b.end===source.captured_at||exactMs(b.end))){
      hourly.set(Date.parse(b.start),{end:Date.parse(b.end),range});
    }
  }
  const firstShown=partialCoverage?.first[1]??midnight??stamp;
  drawDay(visible,firstShown,zone,key,loading?'loading':null,midnight,recentWindow,null,gaps,hourly,movement,coverage);

}
async function day(daily,headline,recent){
  if(calendar?.pinned&&headline?.source&&Date.parse(headline.source.captured_at)!==calendar.end)return;
  const key=headline?.source&&daily?.before&&daily.after&&daily.through&&daily.day===headline.day&&daily.timezone===headline.zone ? JSON.stringify([daily.day,daily.timezone,daily.through.camera,daily.through.format_id,
    daily.before.source_sha256,daily.after.source_sha256,daily.before.event_id,daily.before.captured_at,daily.after.event_id,daily.after.captured_at]) : '';
  const sameSaved=!!headline?.source&&lastRangeSource?.day===headline.day&&lastRangeSource.zone===headline.zone&&
    lastRangeSource.event===headline.source.event_id&&lastRangeSource.time===headline.source.captured_at&&lastRangeSource.digest===headline.source.source_sha256;
  if((key&&key!==identity)||(!key&&!headline?.source)){
    identity=key;generation++;saved=null;pending=false;due=0;lastRangeSource=null;
    $('day-history-status').textContent='';
  }
  if(key)lastRangeSource={day:daily.day,zone:daily.timezone,event:daily.through.event_id,time:daily.through.captured_at,digest:daily.through.source_sha256};
  latest=headline && {...headline,savedOnly:daily?.historical_only===true,historyCompatible:Boolean(key)||sameSaved,sameDailyBounds:Boolean(key) && (headline.method==='nominal_meter_movement_v1' || headline.method==='range_midpoint_v1' && !['stale','partial_coverage'].includes(headline.status)) &&
    daily?.status!=='stale' && daily.through.event_id===headline.source.event_id && daily.through.source_sha256===headline.source.source_sha256 &&
    daily.through.captured_at===headline.source.captured_at};
  requestTracked(headline);
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
    }else saved={...saved,status:data.status==='loading'?'loading':'unavailable'};
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
// When bounded intervals predate this capture session, show only the change
// between real measurements inside the selected window. A partial first hour
// has no implied opening value at the window boundary.
function showTrackedWindow(view,hours,key){
  const end=view.stamp,start=end-hours*3600000;
  const points=view.movement.filter(p=>p[0]>=start);
  const host=$('day-curve');
  if(points.length<2){
    delete host.dataset.endTime;delete host.dataset.endEvent;
    drawDay(null,null,null,null,'Only one saved reading in this window');
    return;
  }
  const first=points[0],movement=points.map(([t,value,event,group])=>
    [t,(Math.round(value*100)-Math.round(first[1]*100))/100,event,group]);
  const stops=movement.map(([to,value,id])=>({from:null,to,point:[to,value,null,null,id]}));
  const gaps=view.coverage.gaps.filter(([a,b])=>a<end&&b>first[0]);
  host.dataset.endTime=latest.source.captured_at;host.dataset.endEvent=String(view.event);
  $('day-history-status').textContent=number.format(movement.at(-1)[1])+' ft³ tracked · '+clockSpan(first[0],end,view.zone);
  drawDay([],start,view.zone,key,null,view.midnight,null,stops,gaps,null,movement,view.coverage);
}
let rollingDrawKey='';
function showRolling(){
  if(calendar){showSummary(dayView);return;}
  const host=$('day-curve'),hours=Number(selection);
  const selected=rolling?.periods?.[selection];
  const newerDay=selected&&rolling.compatibleWithDay&&rolling.notice==='Last saved'&&dayView?.stamp>asTime(selected.end)&&
    dayView.midnight!=null&&dayView.stamp-hours*3600000>=dayView.midnight;
  const key=JSON.stringify([selection,selected?rolling.key:null,selected?rolling.notice:null,dayView?.key]);
  if(key===rollingDrawKey)return;
  rollingDrawKey=key;activeSelection=selection;
  const lastEnd=selected?asTime(selected.end):null;
  const staleWindow=dayView&&lastEnd!=null&&
    (lastEnd<=dayView.stamp-hours*3600000||lastEnd<dayView.coverage?.first[1]);
  let period=staleWindow?null:selected;
  let useSaved=!!period;
  if(!period||newerDay){
    const current=dayView&&dailyWindow(dayView,hours);
    if(current&&(!period||current.bins.every(b=>pair(b.total_lower,b.total_upper)))){
      period=current;
      useSaved=false;
      // Only interval amounts share a baseline across shifted windows. A prefix
      // measured from the previous window's start cannot constrain today's prefix.
      if(selected&&rolling.compatibleWithDay){
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
  if(dayView?.movement&&dayView.partialCoverage&&!useSaved&&!period?.bins.some(b=>pair(b.total_lower,b.total_upper)||pair(b.lower,b.upper))){
    showTrackedWindow(dayView,hours,key);return;
  }
  const zone=useSaved?rolling.zone:dayView?.zone;
  if(!period?.bins?.length){
    delete host.dataset.endEvent;delete host.dataset.endTime;
    drawDay(null,null,null,null,'No saved readings for this window');return;
  }
  const start=asTime(period.start),end=asTime(period.end);
  const event=useSaved?rolling.through:latest.source;
  host.dataset.endTime=event.captured_at;host.dataset.endEvent=event.event_id;
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
  if(changed && browsing){
    const windows=periodWindows(browsing.hourly,browsing.anchor,next);
    const window=windows.find(w=>w.start<browsing.end && browsing.end<=w.end) || windows.at(-1);
    selectWindow(window,windows,browsing.hourly,browsing.anchor,next);
  }
  selection=next;rolling=data;
  for(const button of $('gas-scales').querySelectorAll('[data-scale]'))
    button.setAttribute('aria-pressed',String(next===button.dataset.scale));
  if(changed)requestDetail();
  if(selection==='today'){
    if(changed||previousKey!==data?.key||wasCompatible!==data?.compatibleWithDay){rollingDrawKey='';showDay();}
  }else showRolling();
}
// The hourly snapshot contains up to 25 hours. Offer windows that actually
// intersect saved history. Pin the same snapshot while the reader browses.
function periodWindows(hourly,anchor,value){
  const {zone,midnight,data}=hourly;
  const minutes=rateMinutes(value,anchor-midnight);
  const close=completedTick(anchor,zone,minutes===10?10:60);
  const starts=[...(data?.hours||[]).map(q=>q.start),...(data?.dailyHours||[]).map(p=>p[0]),
    ...(data?.offsets||[]).map(p=>p.time),...(data?.groups||[]).filter(g=>g.length).map(g=>g[0][0])];
  const earliest=Math.min(close,...starts);
  if(value==='today'){
    const days=[{start:midnight,end:close}];
    for(let end=midnight;end>earliest;){
      const start=localOpening(end-1,zone);
      days.push({start,end});
      end=start;
    }
    return days;
  }
  const span=Number(value)*hourMs,windows=[];
  for(let end=close;end>=earliest;end-=span)windows.push({start:end-span,end});
  return windows;
}
function selectWindow(chosen,windows,hourly,anchor,value){
  const old=browsing;
  visibleSummary=null;
  browsing=null;
  if(!chosen || chosen.end===windows[0].end && chosen.start===windows[0].start)return;
  let fine=old?.fine??detail;
  if(rateMinutes(value,chosen.end-chosen.start)===10 &&
     (!fine || fine.zone!==hourly.zone || chosen.end>fine.end || chosen.start<completedTick(fine.end,fine.zone,10)-2*hourMs)){
    fine=loadCalendar(chosen.end,hourly.zone,10);
  }
  browsing={...chosen,hourly,anchor,fine,view:old?old.view:dayView};
}
let navWindows=[],navKey='',navZone='';
function movePeriod(index,returnFocus=false){
  const chosen=navWindows[index];
  if(!chosen)return;
  selectWindow(chosen,navWindows,browsing?.hourly??calendar,browsing?.anchor??calendarStamp,selection);
  closePicker(returnFocus);
  if(!browsing)requestDetail();
  showSummary(dayView);
}
function windowLabel(w){
  const fmt=new Intl.DateTimeFormat(undefined,{timeZone:navZone,month:'short',day:'numeric'});
  if(fmt.format(w.start)!==fmt.format(w.end))
    return fmt.format(w.start)+' '+clock(w.start,navZone)+' – '+fmt.format(w.end)+' '+clock(w.end,navZone);
  return clockSpan(w.start,w.end,navZone);
}
function dateLabel(t){
  return new Intl.DateTimeFormat(undefined,{timeZone:navZone,weekday:'long',month:'short',day:'numeric'}).format(t);
}
function updateNavigation(hourly,start,end){
  const anchor=browsing?.anchor??calendarStamp;
  const windows=periodWindows(hourly,anchor,selection);
  const key=JSON.stringify([selection,start,end,hourly.zone,windows]);
  if(key===navKey&&!$('gas-period-row').hidden)return;
  navKey=key;navZone=hourly.zone;navWindows=windows;
  $('gas-period-row').hidden=false;
  const index=periodIndex();
  $('gas-previous').disabled=index>=windows.length-1;
  $('gas-next').disabled=!browsing;
  $('gas-latest').hidden=!browsing;
  $('gas-period-day').textContent=dateLabel(selection==='today'?start:end);
  $('gas-period-time').textContent=windowLabel({start,end});
  if(!$('gas-period-picker').hidden)closePicker(false);
}
function periodIndex(){
  return browsing?navWindows.findIndex(w=>w.start===browsing.start&&w.end===browsing.end):0;
}
function closePicker(returnFocus) {
  $('gas-period-picker').hidden = true;
  $('gas-jump').setAttribute('aria-expanded','false');
  if(returnFocus) $('gas-jump').focus();
}
function openPicker() {
  const index=periodIndex();
  const options = navWindows.map((w,i) => {
    const button = document.createElement('button');
    button.type = 'button';
    const differentDates=dateLabel(navWindows[0].end)!==dateLabel(navWindows.at(-1).end);
    const periodLabel=windowLabel(w);
    button.textContent=selection==='today'?dateLabel(w.start):
      differentDates&&dateLabel(w.start)===dateLabel(w.end)?dateLabel(w.end)+' · '+periodLabel:periodLabel;
    if(index===i) {
      button.setAttribute('aria-current','true');
      const check = document.createElement('span');
      check.setAttribute('aria-hidden','true');
      check.textContent='✓';
      button.append(check);
    }
    button.addEventListener('click',()=>movePeriod(i,true));
    return button;
  });
  $('gas-period-options').replaceChildren(...options);
  $('gas-period-picker').hidden = false;
  $('gas-jump').setAttribute('aria-expanded','true');
  options[index].focus();
}
$('gas-scales').querySelectorAll('[data-scale]').forEach(button=>button.addEventListener('click',()=>{
  const select=$('usage-period');
  select.value=button.dataset.scale;
  select.dispatchEvent(new Event('change'));
}));
$('gas-previous').addEventListener('click',()=>movePeriod(periodIndex()+1));
$('gas-next').addEventListener('click',()=>movePeriod(periodIndex()-1));
$('gas-latest').addEventListener('click',()=>{movePeriod(0);$('gas-jump').focus();});
$('gas-jump').addEventListener('click',()=>$('gas-period-picker').hidden ? openPicker() : closePicker(true));
document.addEventListener?.('pointerdown',e=>{if(!e.target.closest('.jump')) closePicker(false);});
document.addEventListener?.('focusin',e=>{if(!e.target.closest('.jump')) closePicker(false);});
const row = $('gas-period-row');
row.addEventListener('keydown',e=>{
  if(e.key==='Escape' && !$('gas-period-picker').hidden) {e.preventDefault();closePicker(true);return;}
  const n = e.target.closest('#gas-period-options button');
  if(n && ['ArrowUp','ArrowDown'].includes(e.key)) {
    e.preventDefault();
    (e.key==='ArrowUp'?n.previousElementSibling:n.nextElementSibling)?.focus();
  } else if(!n && ['ArrowLeft','ArrowRight'].includes(e.key)) {
    e.preventDefault();
    movePeriod(periodIndex()+(e.key==='ArrowLeft'?1:-1));
    $('gas-jump').focus();
  }
});

// Swipe on the date strip. Touching the plot still inspects readings.
let gesture = null, suppressClick = false;
row.addEventListener('pointerdown',e=>{
  suppressClick = false;
  if(e.isPrimary && e.pointerType==='touch' && !e.target.closest('#gas-period-picker'))
    gesture={id:e.pointerId,x:e.clientX,y:e.clientY};
});
row.addEventListener('pointercancel',()=>{gesture=null;});
row.addEventListener('pointerup',e=>{
  if(!gesture || gesture.id!==e.pointerId) return;
  const dx=e.clientX-gesture.x,dy=e.clientY-gesture.y;
  gesture=null;
  if(Math.abs(dx)<45 || Math.abs(dx)<Math.abs(dy)*1.5) return;
  suppressClick=true;
  movePeriod(periodIndex()+(dx>0?1:-1));
});
row.addEventListener('click',e=>{
  if(suppressClick) {suppressClick=false;e.preventDefault();e.stopImmediatePropagation();}
},true);

window.AIEdgeCharts={day,period,setCalendar,get hourly(){return !!calendar;}};
})();
