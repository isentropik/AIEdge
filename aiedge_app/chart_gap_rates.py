"""Chart-only hourly rates when a failed capture straddles the clock hour."""
from bisect import bisect_left
from datetime import datetime
from math import ceil, floor, isfinite
from statistics import median

from capture_clock import interval
from dial_travel import phases
from meter_history import millis
from reading_format import validate

HOUR = 3_600_000


def brackets(db, camera, event, tick):
    # Walk the camera/event index out from the known gap. Keep consecutive
    # captures in time order; never pick two nonadjacent photos by wall time.
    rows = []
    for before in (True, False):
        order, op, limit = ('DESC','<=',tick-HOUR) if before else ('ASC','>',tick+HOUR)
        side = []
        for eid, stamp, sha in db.execute(
                'SELECT e.event_id,f.captured_at,f.sha256 FROM capture_events e JOIN frames f USING(camera,frame_id) '
                f'WHERE e.camera=? AND e.event_id {op} ? ORDER BY e.event_id {order}', (camera,event)):
            ts = millis(datetime.fromisoformat(stamp))
            if side and (ts >= side[-1][0] if before else ts <= side[-1][0]):
                return {},[]
            side.append((ts,eid,sha,stamp))
            if (before and ts<=limit) or (not before and ts>=limit):
                break
        rows.extend(reversed(side) if before else side)
    times = [row[0] for row in rows]
    result = {}
    for t in (tick-HOUR,tick,tick+HOUR):
        j = bisect_left(times,t)
        if j==len(rows):
            continue
        k = j if times[j]==t else j-1
        if k>=0 and times[j]-times[k]<600000:
            result[t] = rows[k:j+1]
    return result,rows


def clock_reading(db, frames, t, point, document, source, known, inside):
    first,last = frames[0][1],frames[-1][1]
    if (last-first != len(frames)-1 or (not inside and first!=last and
            db.execute('SELECT 1 FROM capture_failure_boundaries WHERE after_event_id=? '
                       'UNION ALL SELECT 1 FROM consumption_segment_links WHERE first_event=? LIMIT 1',
                       (first,last)).fetchone())):
        return None
    samples=phases(db,first,last,document,source,same_clock=False)
    turn=document['dials'][-1]['value_per_revolution']
    reference=point[1]
    values=[]
    for ts,event,sha,stamp in frames:
        if event not in samples:
            return None
        obs,band=samples[event]
        if (obs['source_sha256'],obs['captured_at'])!=(sha,stamp):
            return None
        lo,hi=map(float,band)
        center=(lo+hi)/2
        measured=known.get((event,sha,stamp))
        level=measured if measured is not None else reference
        shift=turn*round((level-center)/turn)
        lo,hi,center=lo+shift,hi+shift,center+shift
        # A register estimate may locate the winding, never override a
        # disagreeing photo. Reject an uncertain turn near the half-way mark.
        if (abs(center-reference)+(hi-lo)/2>=turn/2 or
                measured is not None and not lo-1e-8<=measured<=hi+1e-8):
            return None
        values.append((datetime.fromisoformat(stamp).timestamp()*1000,measured if measured is not None else center,lo,hi,obs))
    left,right=values[0],values[-1]
    if first!=last and (left[4]['context_id']!=right[4]['context_id'] or
                        interval(left[4],right[4])['state']!='continuous'):
        return None
    if left[2]>right[3]:
        return None
    # When measurement noise reverses the two centers, their overlapping
    # supports admit a stationary dial.
    value=left[1]
    if left[1]>right[1]:
        value=max(left[2],min(right[3],(left[1]+right[1])/2))
    elif first!=last:
        value+=(right[1]-left[1])*(t-left[0])/(right[0]-left[0])
    if not inside and left[2]<=reference<=right[3]:
        value=reference
    if not left[2]-1e-8<=value<=right[3]+1e-8 or not point[2]<=value<=point[3]:
        return None
    return dict(time=t,value=value,local=[left[2],right[3]],outer=point[2:4],
                events=[f[1] for f in frames],times=[f[0] for f in frames],levels=[v[1] for v in values])


def travel_bounds(left, right, flow, rate, measure):
    """Sum measured uninterrupted portions. Give unobserved time its physical flow limit."""
    start,end=left['time'],right['time']
    cursor,first=start,left['events'][0]
    low=high=0.
    def segment(a,b,i,j):
        if b<=a:
            return 0.,0.
        proof=measure(a,b,i,j)
        if proof and proof.get('use') is not None and len(proof.get('bands',[]))==1:
            return proof['bands'][0]
        return 0.,rate*(b-a)/1000
    for gap in sorted(flow,key=lambda g:g['start']):
        a,b=gap['start'],gap['end']
        if b<=start or a>=end:
            continue
        i,j=gap['events']
        lo,hi=segment(cursor,min(a,end),first,i)
        low+=lo
        high+=hi
        # Stored gap endpoints are truncated to milliseconds. Restart
        # inside the captured portion, accounting for that millisecond.
        following=min(end,b+1)
        high+=rate*max(0,following-max(cursor,a))/1000
        cursor,first=following,j
    lo,hi=segment(cursor,end,first,right['events'][-1])
    return low+lo,high+hi


def estimated_rates(db, profile, flow, document, zone, known, intervals, reader=None, allowance=None, head=None):
    if not profile.get('reconciled') or not profile.get('ceiling') or not document or not flow:
        return []
    points={p[0]:p for p in profile['points']}
    hours=sorted(t for t in points if t%60000==0 and datetime.fromtimestamp(t/1000,zone).minute==0)
    unknown=set(map(tuple,profile['unknownGaps']))
    turn=document['dials'][-1]['value_per_revolution']
    fmt=validate(document)[1]
    results=[]
    for gap in flow:
        a,b=gap['start'],gap['end']
        j=bisect_left(hours,a)
        if (a,b) not in unknown or j==len(hours) or not a<hours[j]<b or b-a>=600000:
            continue
        t=hours[j]
        ticks=(t-HOUR,t,t+HOUR)
        eligible={k for k in ticks if k in points and all(v is not None and isfinite(v) for v in points[k][1:4])}
        if t not in eligible or len(eligible)<2:
            continue
        if (len({points[k][4] for k in eligible})!=1 or any(l<max(eligible) and min(eligible)<r for l,r,*_ in profile['conflicts'])
                or any(min(eligible)<=p['time']<=max(eligible) for p in profile.get('photoConflicts',[]))):
            continue
        event=gap['events'][0]
        row=db.execute('SELECT camera FROM capture_events WHERE event_id=?',(event,)).fetchone()
        if not row:
            continue
        pairs,frames=brackets(db,row[0],event,t)
        if [f[:2] for f in pairs.get(t,[])]!=[(a,event),(b,event+1)]:
            continue
        if not any((e,sha,stamp) in known for _,e,sha,stamp in pairs[t]):
            continue
        source=dict(camera=row[0],format_id=fmt)
        clocks={k:clock_reading(db,pair,k,points[k],document,source,known,k==t) for k,pair in pairs.items()
                if k in eligible and pair[-1][0]<=profile['through'] and (head is None or pair[-1][1]<=head)}
        center=clocks.get(t)
        if not center:
            continue
        spacings=[r[0]-l[0] for l,r in zip(frames,frames[1:])]
        typical=median(spacings)
        interruptions={(g['start'],g['end']):g for g in flow}
        # A slow sample can admit a winding. Bound just that spacing by
        # capacity, and keep the measured evidence before and after it.
        for l,r in zip(frames,frames[1:]):
            if r[0]-l[0]>=2*typical:
                interruptions.setdefault((l[0],r[0]),dict(start=l[0],end=r[0],events=[l[1],r[1]]))
        for start,end in zip(ticks,ticks[1:]):
            left,right=clocks.get(start),clocks.get(end)
            if not left or not right or any(s==start and e==end and v.get('use') is not None for s,e,v in intervals):
                continue
            use=right['value']-left['value']
            # The photographed phases constrain fractional turns. Keep whole
            # turns the absolute envelopes still allow. Independently measured
            # ten-minute subintervals provide a floor on total hourly travel.
            low=max(0.,right['outer'][0]-left['outer'][1])
            high=min(profile['ceiling']*3600,right['outer'][1]-left['outer'][0])
            if reader is not None and allowance is not None:
                def measure(a,b,i,j):
                    return reader.get(db,document,source,allowance,a,b,i,j,head)
                observed_lo,observed_hi=travel_bounds(left,right,interruptions.values(),profile['ceiling'],measure)
                low=max(low,observed_lo)
                high=min(high,observed_hi)
            pieces={(s,e):v['bands'][0][0] for s,e,v in intervals if start<=s<e<=end and
                    e-s==600000 and (s-start)%600000==0 and v.get('use') is not None and len(v.get('bands',[]))==1}
            low=max(low,sum(pieces.values()))
            dl=right['local'][0]-left['local'][1]
            dh=right['local'][1]-left['local'][0]
            low=max(low,dl+ceil((low-dh)/turn)*turn)
            high=min(high,dh+floor((high-dl)/turn)*turn)
            if low<=use<=high:
                results.append([start,end,dict(use=use,bands=[[low,high]],basis='interpolated_hour',
                                                readings=[left,right],gap=[a,b])])
    return results
