(() => {
  'use strict';
  const id = name => document.getElementById(name);
  const plot = id('register-plot');
  const svg = plot.querySelector('svg'), tip = id('register-tip'), status = id('register-status');
  const previous = id('register-previous'), next = id('register-next'), retry = id('register-retry');
  const scales = [...document.querySelectorAll('[data-register-days]')];
  const dayMs = 86400000;
  const number = new Intl.NumberFormat(undefined, {maximumFractionDigits: 2});
  const civilDate = new Intl.DateTimeFormat(undefined, {month:'short', day:'numeric', year:'numeric', timeZone:'UTC'});
  const shiftDay = (day, n) => new Date(Date.parse(day) + n * dayMs).toISOString().slice(0, 10);
  let days = 7, end = '', data, pending, visible = false, selected = -1, positions = [];

  function element(name, attrs, label) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (label !== undefined) node.textContent = label;
    return node;
  }

  function inspect(index) {
    selected = index;
    tip.hidden = index < 0;
    for (const dot of svg.querySelectorAll('circle')) dot.setAttribute('r', +dot.dataset.index === index ? 5 : 3);
    if (index < 0) return;
    const p = data.points[index];
    const when = p.kind === 'latest'
      ? new Date(p.at).toLocaleString(undefined,{timeZone:data.zone,month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})
      : civilDate.format(Date.parse(p.day)) + ' · Day close';
    tip.textContent = when + ' · ' + number.format(p.value) + ' ft³';
    tip.style.left = Math.max(0,Math.min(plot.clientWidth-tip.offsetWidth,positions[index]-tip.offsetWidth/2)) + 'px';
  }

  function draw() {
    if (!data) return;
    svg.replaceChildren();
    positions = [];
    const width = plot.clientWidth, height = width < 500 ? 205 : 235;
    if (!width || !data.points.length) { inspect(-1); return; }
    const values = data.points.map(p => p.value);
    const min = Math.min(...values), max = Math.max(...values);
    const raw = Math.max(max - min, 1) / 3;
    const power = 10 ** Math.floor(Math.log10(raw));
    const step = [1,2,2.5,5,10].find(v => v * power >= raw) * power;
    const low = Math.max(0,Math.floor(min/step)*step);
    const high = Math.max(low+step,Math.ceil(max/step)*step);
    const left = number.format(high).length * 8 + 12, right = width - 9, top = 16, bottom = height - 30;
    const first = Date.parse(data.startAt), last = Date.parse(data.endAt);
    const x = stamp => left + (Date.parse(stamp)-first) / (last-first) * (right-left);
    const y = value => bottom - (value-low) / (high-low) * (bottom-top);
    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    svg.style.height = height + 'px';
    for (let i = 0; i <= Math.round((high-low)/step); i++) {
      const value = low+i*step, yy = y(value);
      svg.append(element('line',{x1:left,x2:right,y1:yy,y2:yy,class:'plot-grid'}),
                 element('text',{x:left-8,y:yy+4,'text-anchor':'end'},number.format(value)));
    }
    const axisDate = new Intl.DateTimeFormat(undefined,{timeZone:data.zone,month:'short',day:'numeric'});
    const ticks = width < 500 ? 3 : 5;
    for (let i=0;i<ticks;i++) {
      const frac = i/(ticks-1);
      svg.append(element('text',{x:left+frac*(right-left),y:bottom+22,
        'text-anchor':i===0?'start':i===ticks-1?'end':'middle'},axisDate.format(first+frac*(last-first-1))));
    }
    const line = [];
    const dots = data.points.map((p,i) => {
      const px = x(p.at), py = y(p.value), prior = data.points[i-1];
      const join = prior && shiftDay(prior.day,1) === p.day && prior.value <= p.value;
      line.push((join?'L':'M')+px+' '+py);
      positions.push(px);
      return element('circle',{cx:px,cy:py,r:3,'data-index':i});
    });
    svg.append(element('path',{class:'register-line',d:line.join(' ')}), ...dots);
    inspect(selected < data.points.length ? selected : -1);
  }

  async function load() {
    pending?.abort();
    const request = new AbortController();
    pending = request;
    data = null;
    inspect(-1);
    svg.replaceChildren();
    previous.disabled = next.disabled = true;
    retry.hidden = true;
    plot.hidden = true;
    id('register-period').textContent = '';
    status.textContent = 'Loading meter history…';
    for (const b of scales) b.setAttribute('aria-pressed',String(+b.dataset.registerDays === days));
    try {
      const params = new URLSearchParams({days:String(days)});
      if (end) params.set('end',end);
      const response = await fetch('api/register-history?'+params,{signal:request.signal,priority:'low'});
      if (!response.ok) throw new Error();
      const result = await response.json();
      if (pending !== request) return;
      data = result;
      id('register-period').textContent = civilDate.formatRange(new Date(data.start),new Date(data.end));
      previous.disabled = false;
      next.disabled = data.end >= data.today;
      plot.hidden = !data.points.length;
      const lastPoint = data.points.at(-1);
      if (!lastPoint) {
        status.textContent = 'No recorded readings in this period.';
      } else {
        const detail = ['Daily closing readings'];
        if (data.points[0].day > data.start) detail.push('From ' + civilDate.format(Date.parse(data.points[0].day)));
        if (lastPoint.kind === 'latest') detail.push('Latest at ' + new Date(lastPoint.at).toLocaleTimeString(undefined,
          {timeZone:data.zone,hour:'numeric',minute:'2-digit',timeZoneName:'short'}));
        status.textContent = detail.join(' · ');
      }
      draw();
    } catch (error) {
      if (pending !== request || error.name === 'AbortError') return;
      status.textContent = 'Meter history could not be loaded.';
      retry.hidden = false;
      next.disabled = !end;
    }
  }

  scales.forEach(b => b.addEventListener('click',() => {
    days = +b.dataset.registerDays;
    end = '';
    load();
  }));
  previous.onclick = () => { end = shiftDay(data.start,-1); load(); };
  next.onclick = () => {
    const following = data && shiftDay(data.end,days);
    end = data && following < data.today ? following : '';
    load();
  };
  retry.onclick = load;
  function pointAt(event) {
    if (!positions.length || !data) return;
    const x = event.clientX - svg.getBoundingClientRect().left;
    let best = 0;
    for (let i=1;i<positions.length;i++) if (Math.abs(positions[i]-x)<Math.abs(positions[best]-x)) best=i;
    inspect(Math.abs(positions[best]-x)<=22 ? best : -1);
  }
  plot.addEventListener('pointermove',event => { if (event.pointerType==='mouse') pointAt(event); });
  plot.addEventListener('click',pointAt);
  plot.addEventListener('pointerleave',event => { if (event.pointerType==='mouse') inspect(-1); });
  plot.addEventListener('blur',() => inspect(-1));
  plot.addEventListener('keydown',event => {
    if (!data?.points.length) return;
    const last=data.points.length-1;
    const keys={Escape:-1,Home:0,End:last,ArrowRight:Math.min(last,selected+1),ArrowLeft:selected<0?last:Math.max(0,selected-1)};
    if (Object.hasOwn(keys,event.key)) { event.preventDefault(); inspect(keys[event.key]); }
  });
  new ResizeObserver(draw).observe(plot);
  new IntersectionObserver(entries => {
    visible=entries[0].isIntersecting;
    if (visible && !pending) load();
  }).observe(id('register-history-title'));
  id('refresh').addEventListener('click',() => { if (visible) load(); else pending=null; });
})();
