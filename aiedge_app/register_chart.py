"""One display-only register history for every gas chart time scale."""
from bisect import bisect_left
from datetime import datetime, time, timedelta
from heapq import heappop, heappush
from math import ceil, floor, inf, isfinite

from meter_history import millis
from daily_constraints import InconsistentConstraints


def measured_change_bounds(points, openings, legs, conflicts=()):
    """Combine bounds on meter levels and measured changes without treating a preferred turn as evidence."""
    if not points:
        return []
    scale = 1_000_000
    index = {p[0]:i for i,p in enumerate(points)}
    origin = len(points)
    centers = [round(p[1]*scale) for p in points] + [0]
    graph = [[] for _ in centers]
    def constraint(i,j,upper):
        # A bound on Xj-Xi is an edge. Subtracting the displayed centers gives
        # nonnegative weights for shortest paths; it does not constrain the readings.
        slack = ceil(upper*scale) - (centers[j]-centers[i])
        if slack >= -2:
            graph[i].append((j,max(0,slack)))

    runs=[]
    for j,(_,_,lo,hi,epoch) in enumerate(points):
        runs.append(runs[-1] if j and points[j-1][4]==epoch else j)
        if lo is not None:
            constraint(j,origin,-lo)
        if hi is not None:
            constraint(origin,j,hi)
        if j and points[j-1][4]==epoch:
            constraint(j,j-1,0)  # The same meter can only move forward.
    rejected = {tuple(row) for row in conflicts}
    for a,b,lo,hi in legs:
        i,j=index.get(a),index.get(b)
        if i is None or j is None or runs[i]!=runs[j] or (a,b,lo,hi) in rejected:
            continue
        delta=centers[j]-centers[i]
        if floor(lo*scale)-2<=delta<=ceil(hi*scale)+2:
            constraint(i,j,hi)
            constraint(j,i,-lo)

    # Only the preceding ten minutes, preceding hour and actual daily opening
    # are displayed. Keep the full calculation on the server and send those pairs.
    pairs=set()
    days=sorted(int(day) for day in openings)
    for j,p in enumerate(points):
        t=p[0]
        starts=[t-600000,t-3600000]
        day=bisect_left(days,t)-1
        if day>=0:
            a=days[day]
            base=openings.get(a,openings.get(str(a)))
            if base and not base[4]:
                starts.append(a)
        for a in starts:
            i=index.get(a)
            if i is not None and runs[i]==runs[j]:
                pairs.add((i,j))
    # Each shortest path is a sum of compatible inequalities. Shared absolute
    # offsets cancel, and overlapping hour and ten-minute evidence is counted once.
    needed={}
    for i,j in pairs:
        needed.setdefault(i,set()).add(j)
        needed.setdefault(j,set()).add(i)
    distances={}
    for start,targets in needed.items():
        best={start:0}
        queue=[(0,start)]
        left=len(targets)
        while queue and left:
            cost,i=heappop(queue)
            if cost!=best[i]:
                continue
            if i in targets:
                distances[start,i]=cost
                left-=1
            for j,weight in graph[i]:
                candidate=cost+weight
                if candidate<best.get(j,inf):
                    best[j]=candidate
                    heappush(queue,(candidate,j))
    out=[]
    for i,j in sorted(pairs):
        upper=distances.get((i,j),inf)
        if not isfinite(upper):
            continue
        delta=centers[j]-centers[i]
        lo=max(0,delta-distances.get((j,i),inf))/scale
        hi=(delta+upper)/scale
        left,right=points[i],points[j]
        endpoint_lo=max(0,right[2]-left[3]) if right[2] is not None and left[3] is not None else 0
        endpoint_hi=right[3]-left[2] if right[3] is not None and left[2] is not None else inf
        if lo>endpoint_lo+.000002 or hi<endpoint_hi-.000002:
            out.append([left[0],right[0],lo,hi])
    return out


def reconcile(points, legs, bands_at, gaps, near_register, ceiling, tracked_changes):
    """Find a forward path satisfying the optical changes and register envelopes.

    Work in millionths of a cubic foot so overlapping clock intervals cannot
    cycle on float rounding. Bounds and preferred centers are separate passes.
    """
    import math
    scale = 1_000_000
    index = {p[0]:i for i,p in enumerate(points)}
    domains = []
    for t,v,lo,hi,_ in points:
        bands = bands_at.get(t) or [(lo if lo is not None else v, hi if hi is not None else v)]
        domains.append([(math.floor(l*scale),math.ceil(h*scale)) for l,h in bands])
    # D[i][j] is the largest allowed difference X[j] - X[i]. The final
    # vertex is the fixed origin. Each added arc updates a closed matrix in
    # one pass, detecting incompatible cycles before making any changes.
    origin=len(points)
    low=[d[0][0] for d in domains]+[0]
    high=[d[-1][1] for d in domains]+[0]
    dist=[[hi-lo for hi in high] for lo in low]
    for i,row in enumerate(dist):
        row[i]=0
    conflicts=[]
    undo=None

    def upper(i,j,limit):
        if dist[i][j]<=limit:
            return
        through=[(k,limit+w) for k,w in enumerate(dist[j]) if limit+w<dist[i][k]]
        for row in dist:
            base=row[i]
            if base+limit>=row[j]:
                continue
            for k,extra in through:
                candidate=base+extra
                if candidate<row[k]:
                    if undo is not None:
                        undo.append((row,k,row[k]))
                    row[k]=candidate

    def add(i,j,lo,hi):
        if lo>hi or lo>dist[i][j] or hi < -dist[j][i]:
            return False
        upper(i,j,hi)
        upper(j,i,-lo)
        return True

    for i in range(1,len(points)):
        a,b=points[i-1:i+1]
        if a[4]!=b[4]:
            continue
        limit=math.ceil(ceiling*(b[0]-a[0])*scale/1000) if ceiling else max(0,domains[i][-1][1]-domains[i-1][0][0])
        if not add(i-1,i,0,limit):
            raise InconsistentConstraints(f'incompatible adjacent register bounds at {b[0]}')
    accepted=[]
    for q in sorted(legs,key=lambda q:q['end']-q['start']):
        i,j=index.get(q['start']),index.get(q['end'])
        if i is None or j is None or points[i][4]!=points[j][4] or not q.get('bounds'):
            continue
        lo,hi=q['bounds']
        if add(i,j,math.floor(lo*scale),math.ceil(hi*scale)):
            accepted.append((i,j,q))
        else:
            conflicts.append([q['start'],q['end'],lo,hi])
    outer=[(-dist[i][origin]/scale,dist[origin][i]/scale) for i in range(origin)]
    # Nominal changes are preferences inside the independent measurement
    # bounds. Preserve verified whole-hour totals first, then finer legs.
    bounded=[row.copy() for row in dist]
    for i,j,q in sorted(accepted,key=lambda row:row[2]['start']-row[2]['end']):
        if q['end']-q['start']==3600000 and q.get('basis') in ('fine_dial','carried_register','photo_replay') and q.get('use') is not None:
            use=round(q['use']*scale)
            add(i,j,max(0,use-1),use+1)
    # Choose a physically possible turn while all independently bounded
    # optical changes are still enforced. A preference cannot displace them.
    attempts=0
    def choose_turns(remaining):
        nonlocal attempts
        if not remaining:
            return True
        proposals=[]
        for i in remaining:
            choices=[(max(lo,-dist[i][origin]),min(hi,dist[origin][i])) for lo,hi in domains[i]
                     if lo<=dist[origin][i] and hi>=-dist[i][origin]]
            if not choices:
                return False
            proposals.append((len(choices),i,choices))
        _,i,choices=min(proposals,key=lambda r:(r[0],-points[r[1]][0]))
        nominal=points[i][1]*scale
        choices.sort(key=lambda band:max(band[0]-nominal,nominal-band[1],0))
        rest=remaining-{i}
        for lo,hi in choices:
            attempts+=1
            if attempts>1200:
                return False
            mark=len(undo)
            if add(origin,i,lo,hi) and choose_turns(rest):
                return True
            while len(undo)>mark:
                row,k,old=undo.pop()
                row[k]=old
        return False

    turns={i for i,d in enumerate(domains) if len(d)>1}
    undo=[]
    if not choose_turns(turns):
        dist=bounded
        undo=[]
        attempts=0
        if not choose_turns(turns):
            raise InconsistentConstraints('incompatible optical turns')
    undo=None
    for i,j,q in sorted(accepted,key=lambda row:row[2]['start']-row[2]['end']):
        if q.get('use') is not None:
            use=round(q['use']*scale)
            add(i,j,max(0,use-1),use+1)
    for i in range(1,len(points)):
        a,b=points[i-1:i+1]
        if a[4]==b[4] and a[0] in near_register and b[0] in near_register:
            use=round((b[1]-a[1])*scale)
            if use>=0:
                add(i-1,i,max(0,use-1),use+1)
    for a,b,delta in tracked_changes:
        use=round(delta*scale)
        add(index[a],index[b],max(0,use-1),use+1)

    def pin(i,preferred):
        candidate=max(-dist[i][origin],min(dist[origin][i],round(preferred*scale)))
        add(origin,i,candidate,candidate)

    # Prefer the published register where it exists. At an outage, pin the
    # feasible endpoints before placing any intermediate tick on the line.
    for t in sorted(near_register,reverse=True):
        pin(index[t],points[index[t]][1])
    for t in sorted(bands_at):
        if t in index:
            pin(index[t],points[index[t]][1])
    bridges=[(a,b) for a,b in gaps if a in index and b in index]
    for a,b in bridges:
        for t in (a,b):
            pin(index[t],points[index[t]][1])
    for i,(t,v,*_) in enumerate(points):
        for a,b in bridges:
            if a<t<b:
                left,right=dist[origin][index[a]],dist[origin][index[b]]
                v=(left+(right-left)*(t-a)/(b-a))/scale
                break
        pin(i,v)
    values=dist[origin][:-1]
    for i,p in enumerate(points):
        p[1]=values[i]/scale
        if p[2] is not None:
            p[2]=outer[i][0]
        if p[3] is not None:
            p[3]=outer[i][1]
    return conflicts


def sample(times, levels, t):
    i = bisect_left(times, t)
    if i < len(times) and times[i] == t:
        return levels[i]
    if not 0 < i < len(times):
        return None
    a, b = levels[i-1:i+1]
    if a[3] != b[3]:
        return None
    fraction = (t-times[i-1]) / (times[i]-times[i-1])
    return (a[0] + fraction*(b[0]-a[0]), a[1], b[2], a[3])


def register_profile(stamp, zone, registers, daily, hours, gaps, cuts, photos, ceiling, fine_legs=(), dial=None):
    """Use absolute anchors and independently measured travel. Never edit an observation."""
    raw = [p for p in registers if p[5][1] == 'photo_anchored_fine_dial']
    anchors = {}
    identities = {}
    for t, value, bounds, _, _, identity, _ in raw:
        key = (identity[0], *identity[2:])
        epoch = identities.setdefault(key, len(identities))
        anchors[t] = (float(value), *(map(float, bounds) if bounds else (None, None)), epoch)
    raw_times = sorted(anchors)
    def epoch_at(t):
        if not raw_times:
            return 0
        i = bisect_left(raw_times, t)
        if 0 < i < len(raw_times) and t != raw_times[i] and anchors[raw_times[i-1]][3] != anchors[raw_times[i]][3]:
            return None
        return anchors[raw_times[min(i, len(raw_times)-1)]][3]

    # An optically recovered hour can establish the absolute turn for adjacent
    # fine-dial changes even when the MQTT register was held for those hours.
    clock = {}
    for q in hours:
        for t, name in ((q['start'], 'opening'), (q['end'], 'closing')):
            if name in q and q[name] is not None and epoch_at(t) is not None:
                clock[t] = q[name]
    for rows, backward in ((reversed(hours), True), (hours, False)):
        for q in rows:
            a, b = q['start'], q['end']
            if q['basis'] != 'fine_dial' or epoch_at(a) != epoch_at(b) or epoch_at(a) is None:
                continue
            if backward and b in clock:
                clock.setdefault(a, clock[b]-q['use'])
            elif not backward and a in clock:
                clock.setdefault(b, clock[a]+q['use'])

    raw_levels = [anchors[t] for t in raw_times]
    for t, value in clock.items():
        interp = sample(raw_times, raw_levels, t)
        lo, hi = (interp[1:3] if interp and interp[1] is not None and interp[2] is not None
                  and interp[1] <= value <= interp[2] else (None, None))
        anchors[t] = (value, lo, hi, epoch_at(t))

    # An agreeing full-dial observation just before an outage may still have
    # several possible turns. Keep the same minimum-forward nominal policy as
    # the meter publisher and preserve the outer envelope for the whiskers.
    anchor_times = sorted(anchors)
    for t, bands in sorted(photos.items()):
        j = bisect_left(anchor_times, t)
        if not 0 < j < len(anchor_times) or anchor_times[j] == t:
            continue
        before, after = anchors[anchor_times[j-1]], anchors[anchor_times[j]]
        if before[3] != after[3]:
            continue
        possible = [(max(before[0], lo), min(after[0], hi)) for lo, hi in bands]
        possible = [(lo, hi) for lo, hi in possible if lo <= hi]
        if possible:
            anchors[t] = (possible[0][0], bands[0][0], bands[-1][1], before[3])
            anchor_times.insert(j, t)

    for leg in sorted(fine_legs,key=lambda q:q['start']):
        if leg.get('basis') not in ('photo_replay','carried_register'):
            continue
        for t,name in ((leg['start'],'opening'),(leg['end'],'closing')):
            j = bisect_left(anchor_times,t)
            if t in anchors or not 0<j<len(anchor_times):
                continue
            left,right = (anchors[x] for x in anchor_times[j-1:j+1])
            if left[3]!=right[3] or not left[0]<=leg[name]<=right[0]:
                continue
            anchors[t]=(leg[name],left[1],right[2],left[3])
            anchor_times.insert(j,t)
    # Raw samples can refer to another possible optical turn between two
    # independently reconstructed clock readings. Give the recovered boundary
    # precedence over conflicting raw centers without creating a backward step.
    fixed = sorted(clock)
    ordered = []
    for t in sorted(anchors):
        p = anchors[t]
        j = bisect_left(fixed, t)
        if t not in clock and ((j and anchors[fixed[j-1]][3] == p[3] and p[0] < clock[fixed[j-1]])
                               or (j < len(fixed) and anchors[fixed[j]][3] == p[3] and p[0] > clock[fixed[j]])):
            continue
        if ordered and ordered[-1][1][3] == p[3] and p[0] < ordered[-1][1][0]:
            continue
        ordered.append((t, p))
    times = [t for t, _ in ordered]
    levels = [list(p) for _, p in ordered]
    # Forward and backward passes tighten only constraints that can coexist
    # with the nominal path. Unknown absolute bounds stay unknown until a
    # neighboring observation constrains them.
    for i in range(1, len(levels)):
        a, b = levels[i-1:i+1]
        if a[3] == b[3] and a[1] is not None and a[1] <= b[0]:
            b[1] = max(a[1], b[1]) if b[1] is not None else a[1]
    for i in reversed(range(1, len(levels))):
        a, b = levels[i-1:i+1]
        if a[3] == b[3] and b[2] is not None and a[0] <= b[2]:
            a[2] = min(a[2], b[2]) if a[2] is not None else b[2]

    movement = [(p[0], (float(p[1]), None, None, p[5])) for p in daily
                if p[5][0][0] == 'nominal_meter_movement_v1']
    movement_times = [t for t, _ in movement]
    movement_levels = [p for _, p in movement]
    provisional_from = None
    interruptions = set(tuple(g) for g in gaps if g[0] < g[1] <= stamp)
    for cut in cuts:
        j = bisect_left(times, cut)
        if 0 < j < len(times) and times[j]-times[j-1] < 660000:
            interruptions.add((times[j-1], times[j]))
    modeled = [(a,b) for a,b in zip(times,times[1:]) if b-a >= 660000]
    if times and times[-1] < stamp:
        # Project only the tracked change witnessed after the last absolute
        # anchor. If there is no same-accumulator evidence, do not assume zero.
        a, b = (sample(movement_times,movement_levels,t) for t in (times[-1],stamp))
        if a and b and a[3] == b[3] and a[0] <= b[0]:
            provisional_from = times[-1]
            p = levels[-1]
            value = p[0]+b[0]-a[0]
            high = p[2]+ceiling*(stamp-provisional_from)/1000 if p[2] is not None and ceiling else None
            levels.append([value,p[1],high if high is not None and high>=value else None,p[3]])
            times.append(stamp)
            modeled.append((provisional_from,stamp))

    def at(t):
        p = sample(times, levels, t)
        if p is None:
            return None
        i = bisect_left(times, t)
        if i == 0 or times[i] == t:
            return p
        l, r = times[i-1:i+1]
        a, b = levels[i-1:i+1]
        value, low, high, epoch = p
        if r-l >= 660000:
            ma, mt, mb = (sample(movement_times, movement_levels, x) for x in (l,t,r))
            if ma and mt and mb and ma[3] == mt[3] == mb[3] and ma[0] <= mt[0] <= mb[0] and mb[0] > ma[0]:
                value = a[0]+(b[0]-a[0])*(mt[0]-ma[0])/(mb[0]-ma[0])
        if ceiling and b[1] is not None and a[2] is not None:
            lo = max(low if low is not None else 0, b[1]-ceiling*(r-t)/1000)
            hi = min(high if high is not None else float('inf'), a[2]+ceiling*(t-l)/1000)
            if lo <= value <= hi:
                low, high = lo, hi
        return value, low, high, epoch

    fine_bounds = [[q['start'],q['end'],*q['bounds']] for q in fine_legs if q.get('bounds')]
    out = dict(points=[], openings={}, gaps=sorted(interruptions), modeled=modeled, fineBounds=fine_bounds,
               ceiling=ceiling, through=stamp, provisionalFrom=provisional_from)
    if not times:
        return out
    first = datetime.fromtimestamp(times[0]/1000, zone).date()
    last = datetime.fromtimestamp(stamp/1000, zone).date()
    day = first
    while day <= last:
        midnight = millis(datetime.combine(day, time.min, zone))
        opening = at(midnight)
        partial = False
        if opening is None:
            # A day observed only from mid-day can retain its published tracked
            # opening. Its total must be identified as partial.
            j = bisect_left(times, midnight)
            if j < len(times) and datetime.fromtimestamp(times[j]/1000, zone).date() == day:
                m = sample(movement_times, movement_levels, times[j])
                if m and m[3][0][2] == day.isoformat():
                    p = levels[j]
                    opening = (p[0]-m[0], None, None, p[3])
                    partial = True
                else:
                    opening = (levels[j][0], None, None, levels[j][3])
                    partial = True
        out['openings'][midnight] = [*opening, partial] if opening else None
        day += timedelta(days=1)
    # The transport contains clock samples, not one point per camera exposure.
    # Include both real endpoints of sizable outages so the dashed segment
    # spans the actual interruption on zoom, and the actual latest observation.
    ticks = {t for g in interruptions if g[1]-g[0] >= 600000 for t in g}
    ticks.update((times[0], times[-1], stamp))
    if raw:
        ticks.add(raw[-1][0])
    for t in range(times[0]//60000*60000, stamp+1, 60000):
        if datetime.fromtimestamp(t/1000, zone).minute % 10 == 0:
            ticks.add(t)
    for t in sorted(ticks):
        p = at(t)
        if p is not None:
            out['points'].append([t,*p])
    points=out['points']
    near=set()
    bands_at=dict(photos)
    frame_ranges={}
    for leg in [*hours,*fine_legs]:
        for field,t in (('opening',leg['start']),('closing',leg['end'])):
            proof=leg.get('photo_evidence',{}).get(field,{})
            values=[f['value'] for f in proof.get('frames',[])]
            if values:
                frame_ranges[t]=(min(values),max(values))
    for t,v,lo,hi,_ in points:
        j=bisect_left(raw_times,t)
        if (j<len(raw_times) and t==raw_times[j] or
                0<j<len(raw_times) and raw_times[j]-raw_times[j-1]<660000):
            near.add(t)
            # An absolute envelope can include several five-foot turns.
            # Retain their dial phases instead of picking a value in a hole.
            first=j if raw_times[j]==t else j-1
            frame_ranges[t]=float(raw[first][1]),float(raw[j][1])
        if dial and t in frame_ranges and t not in bands_at and lo is not None and hi is not None:
            import math
            turn=dial['value_per_revolution']
            radius=turn*dial['position_error']/10
            l,r=frame_ranges[t]
            l-=radius
            r+=radius
            low_turn=math.ceil((lo-r)/turn)
            high_turn=math.floor((hi-l)/turn)
            if 0<=high_turn-low_turn<64 and r-l<turn:
                bands_at[t]=[(max(lo,l+k*turn),min(hi,r+k*turn)) for k in range(low_turn,high_turn+1)]
    tracked_changes=[]
    fine_by_start={q['start']:q for q in fine_legs}
    sampled={p[0]:sample(movement_times,movement_levels,p[0]) for p in points}
    clock=[p for p in points if datetime.fromtimestamp(p[0]/1000,zone).minute==0 and p[0]%60000==0]
    for a,b in zip(clock,clock[1:]):
        if (a[4]!=b[4] or b[0]-a[0]!=3600000 or a[0] in near and b[0] in near or
                any(r-l>=600000 and l<b[0] and a[0]<r for l,r in interruptions)):
            continue
        volume=0
        for t in range(a[0],b[0],600000):
            leg=fine_by_start.get(t)
            if leg and leg['end']==t+600000:
                volume+=leg['use']
            else:
                l,r=sampled.get(t),sampled.get(t+600000)
                if not l or not r or l[3]!=r[3] or r[0]<l[0]:
                    break
                volume+=r[0]-l[0]
        else:
            tracked_changes.append((a[0],b[0],volume))
    for a,b in zip(points,points[1:]):
        if a[4]!=b[4] or a[0] in near and b[0] in near or any(l<b[0] and a[0]<r for l,r in interruptions):
            continue
        left,right=sampled[a[0]],sampled[b[0]]
        if left and right and left[3]==right[3] and left[0]<=right[0]:
            tracked_changes.append((a[0],b[0],right[0]-left[0]))
    try:
        conflicts=reconcile(points,[*hours,*fine_legs],bands_at,out['gaps'],near,ceiling,tracked_changes)
    except InconsistentConstraints as exc:
        conflicts=None
        out['reconciliationIssue']=str(exc) or 'work limit'
    out['reconciled']=conflicts is not None
    out['conflicts']=conflicts or []
    if conflicts is not None:
        measured = [[q['start'],q['end'],*q['bounds']] for q in hours if q.get('bounds')]
        out['changeBounds'] = measured_change_bounds(points,out['openings'],[*measured,*fine_bounds],conflicts)
    by_time={p[0]:p for p in points}
    out['readingEstimates']={}
    for t in near:
        measured=sample(raw_times,raw_levels,t)
        if measured and abs(measured[0]-by_time[t][1])>.011:
            out['readingEstimates'][t]=measured[0]
    for day,base in out['openings'].items():
        if base and not base[4] and day in by_time:
            out['openings'][day]=[*by_time[day][1:],False]
        elif base and base[4]:
            j=bisect_left(times,day)
            if j<len(times) and times[j] in by_time:
                base[0]+=by_time[times[j]][1]-levels[j][0]
    if raw and raw[-1][0] in by_time:
        last=raw[-1]
        out['registerHead']=[last[0],float(last[1]),last[3],last[6],by_time[last[0]][1]]
    return out
