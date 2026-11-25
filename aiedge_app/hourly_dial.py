"""Clock-hour meter differences from the saved, capture-bound fine dial."""
from bisect import bisect_left,bisect_right
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from threading import Lock
import sqlite3

from capture_clock import interval
from daily_constraints import number
from dial_travel import advance_band, phases
from meter_history import millis
from reading_format import validate
from tracked_bounds import clock_bridge

CENT = Decimal('.01')
MICROSECOND = timedelta(microseconds=1)


def at_hour(t, before, after):
    """Linear point estimate. Enclose all monotone paths between the two observations."""
    t0, v0, bounds0 = before
    t1, v1, bounds1 = after
    if t == t0:
        return v0, bounds0
    if t == t1:
        return v1, bounds1
    weight = Decimal((t-t0)//MICROSECOND) / ((t1-t0)//MICROSECOND)
    return v0 + (v1-v0)*weight, (bounds0[0], bounds1[1])


def dial_hour(db, source, document, rate, start, end, first, last):
    """Enclose all admissible turns; give a point estimate only for a unique winding."""
    turn = min(number(d['value_per_revolution']) for d in document['dials'])
    cuts = {v+1 for v, in db.execute('SELECT after_event_id FROM capture_failure_boundaries '
                                      'WHERE after_event_id BETWEEN ? AND ?', (first,last-1))}
    if db.execute('SELECT 1 FROM consumption_segment_links WHERE first_event BETWEEN ? AND ? LIMIT 1',
                  (first+1,last)).fetchone():
        return None
    previous = opening = None
    supported_spans = []
    unique = True
    cursor = first
    for page in range(first,last+1,64):
        observations = phases(db,page,min(last,page+63),document,source,same_clock=False)
        for eid,(obs,phase) in sorted(observations.items()):
            if eid != cursor:
                return None
            cursor += 1
            now = datetime.fromisoformat(obs['captured_at'])
            center = sum(phase)/2
            reach = phase
            if previous is not None:
                old, old_phase, sample = previous
                then, value, band = sample
                if now <= then or now-then >= timedelta(minutes=11) or obs['context_id'] != old['context_id']:
                    return None
                timing = interval(old,obs)
                # An internal missed capture need not hide the hour's total. Both
                # sides must independently fix the turn count below. Never place
                # an interpolated hour boundary inside a missed interval.
                if eid in cuts and (timing['state']!='continuous' or then<start<now or then<end<now):
                    return None
                if timing['state'] != 'continuous':
                    if timing['reason'] != 'capture_clock_utc_discontinuity' or clock_bridge(
                            db,old,obs,old_phase,phase,turn,rate) is None:
                        return None
                elapsed = Decimal(obs['monotonic_us']-old['monotonic_us'])/1000000
                if not 0 < elapsed < 660:
                    return None
                limit = rate*elapsed
                winding = ((band[0]-phase[1])/turn).to_integral_value(rounding=ROUND_CEILING)
                last_winding = ((band[1]+limit-phase[0])/turn).to_integral_value(rounding=ROUND_FLOOR)
                unique = unique and winding == last_winding
                reach = advance_band(band,phase,turn,limit)
                if reach is None:
                    return None
                if eid in cuts or timing['state']!='continuous':
                    supported_spans.append((millis(then),millis(now)))
                center = min(reach[1],max(reach[0],value,center+winding*turn))
            current = (now,center,reach)
            if now == start:
                opening = center, reach
            elif previous and then < start < now:
                opening = at_hour(start,sample,current)
            if previous and then <= end <= now and opening is not None:
                closing, bounds = at_hour(end,sample,current)
                delta = closing-opening[0]
                lo = max(Decimal(0),bounds[0]-opening[1][1])
                hi = bounds[1]-opening[1][0]
                if lo <= hi:
                    result=dict(basis='fine_dial',supported_spans=supported_spans,
                                bounds=[float(lo.quantize(CENT,rounding=ROUND_FLOOR)),
                                        float(hi.quantize(CENT,rounding=ROUND_CEILING))])
                    if unique and lo<=delta<=hi:
                        result['use']=float(delta)
                    return result
            previous = obs,phase,current
    return None


class LedgerHours:
    def __init__(self,store,photos=None):
        self.store = store
        self.photos = photos
        self.cache = {}
        self.photo_cache = {}
        self.lock = Lock()

    def gap_flow(self,start,stamp,state,document,rate):
        from chart_gap_flow import photo_gaps
        return photo_gaps(self.store,start,stamp,state,document,rate)

    def gap_registers(self, gaps, state, document):
        """Read saved full-dial observations at the edges of substantial outages."""
        import json
        from event_observation_read import read_batch
        from observation_support import observed_rows
        from absolute_motion import observed_bands
        from reading_bounds import display_bounds

        times = sorted({t for a,b in gaps if b-a >= 600000 for t in (a,b)})
        if not times or not state or not state.get('event_id'):
            return {}
        revision = validate(document)[1]
        result = {}
        with self.store.connect() as db:
            head = db.execute('SELECT camera FROM capture_events JOIN frames USING(camera,frame_id) '
                              'WHERE event_id=? AND sha256=? AND captured_at=?',
                              (state['event_id'],state['source_sha256'],state['measured_at'])).fetchone()
            if not head:
                return {}
            for t in times:
                dt = datetime.fromtimestamp(t/1000,timezone.utc)
                rows = db.execute('SELECT e.event_id,b.context,f.sha256,r.result FROM frames f '
                    'JOIN capture_events e USING(camera,frame_id) JOIN event_recognition_bindings b '
                    'ON b.event_id=e.event_id AND b.source_sha=f.sha256 JOIN consumption_records r '
                    'ON r.event_id=e.event_id JOIN consumption_segments s ON s.segment_id=r.segment_id '
                    'WHERE f.camera=? AND f.captured_at>=? AND f.captured_at<? AND e.event_id<=? '
                    'AND b.pipeline=? AND s.format_id=?',
                    (head[0],dt.isoformat(timespec='microseconds'),(dt+timedelta(milliseconds=1)).isoformat(timespec='microseconds'),
                     state['event_id'],document['pipeline_id'],revision)).fetchall()
                if len(rows)!=1:
                    continue
                eid, context, digest, record = rows[0]
                try:
                    inf = read_batch(db,[dict(event_id=eid,context_id=context,source_sha256=digest)],document['pipeline_id'])[0]['result']
                    consumption = json.loads(record)
                except (ValueError,TypeError,KeyError,IndexError,AttributeError,RecursionError,OverflowError):
                    # A damaged optional endpoint cannot contribute a dial turn.
                    continue
                obs = inf.get('event_observation') or {}
                if (not isinstance(consumption, dict) or obs != consumption.get('event_observation') or obs.get('event_id')!=eid or
                        obs.get('camera')!=head[0] or obs.get('format_id')!=revision or obs.get('source_sha256')!=digest or
                        inf.get('state')!='estimated' or observed_rows(inf)!=[True]*len(document['dials'])):
                    continue
                dials = [inf['dial_positions'][d['index']] for d in document['dials']]
                if any(r.get('state')!='estimated' or not isinstance(r.get('position'),(int,float))
                       or not 0<=r['position']<10 for r in dials):
                    continue
                ranges = display_bounds(document,[r['position'] for r in dials])
                raw = dict(state='ambiguous', unit=document['unit'], format_id=revision, source_sha256=digest, bounds=ranges)
                bands = observed_bands(dict(format=document,consumption=consumption,_raw_meter_reading=raw),obs)
                if bands:
                    result[t] = [(float(lo),float(hi)) for lo,hi in bands]
        return result

    def opening(self,stamp,end,day_start,state,document,policy):
        """Measure from the exact first tracked exposure to the next ten-minute tick."""
        if not state or not document or document.get('unit')!='ft3' or not document.get('maximum_rate_per_second'):
            return None
        start=datetime.fromisoformat(stamp)
        close=datetime.fromtimestamp(end/1000,timezone.utc)
        if start.utcoffset() is None or not timedelta(0)<=close-start<timedelta(minutes=10):
            return None
        revision=validate(document)[1]
        rate=number(document['maximum_rate_per_second'])
        if policy.get('format_id')==revision and policy.get('pipeline_id')==document['pipeline_id']:
            rate=min(rate,number(policy['capacity_cfh'])/3600)
        with self.store.connect() as db:
            row=db.execute('SELECT e.camera FROM capture_events e JOIN frames f USING(camera,frame_id) '
                           'WHERE e.event_id=? AND f.sha256=? AND f.captured_at=?',
                           (state.get('event_id'),state.get('source_sha256'),state.get('measured_at'))).fetchone()
            if not row:return None
            camera=row[0]
            first=db.execute('SELECT e.event_id FROM frames f JOIN capture_events e USING(camera,frame_id) '
                             'WHERE f.camera=? AND f.captured_at=? AND e.event_id<=?',
                             (camera,stamp,state['event_id'])).fetchall()
            if len(first)!=1:return None
            eid=first[0][0]
            previous=db.execute('SELECT f.captured_at FROM capture_events e JOIN frames f USING(camera,frame_id) '
                                'WHERE e.camera=? AND e.event_id<? ORDER BY e.event_id DESC LIMIT 1',
                                (camera,eid)).fetchone()
            if (not previous and eid!=1) or (previous and datetime.fromisoformat(previous[0])>=day_start):
                return None
            if close==start:return [end,0,0,0]
            last=db.execute('SELECT e.event_id FROM capture_events e JOIN frames f USING(camera,frame_id) '
                            'WHERE e.camera=? AND e.event_id BETWEEN ? AND ? AND f.captured_at>=? '
                            'ORDER BY e.event_id LIMIT 1',(camera,eid,state['event_id'],close.isoformat())).fetchone()
            if not last:return None
            leg=dial_hour(db,dict(camera=camera,format_id=revision),document,rate,start,close,eid,last[0])
            if leg and 'use' in leg and not leg['supported_spans']:
                return [end,leg['use'],*leg['bounds']]

    def snapshot(self,ticks,state,document,policy,published=None,gaps=(),archive=None,offsets=None):
        if (len(ticks)<2 or not state or not document or document.get('unit')!='ft3'
                or not document.get('maximum_rate_per_second') or not state.get('event_id')):
            return {}
        revision = validate(document)[1]
        rate = number(document['maximum_rate_per_second'])
        if policy.get('format_id')==revision and policy.get('pipeline_id')==document['pipeline_id']:
            rate = min(rate,number(policy['capacity_cfh'])/3600)
        times = [datetime.fromtimestamp(t/1000,timezone.utc) for t in ticks]
        with self.lock, self.store.connect() as db:
            head = db.execute('SELECT e.camera,f.captured_at,f.sha256 FROM capture_events e JOIN frames f '
                              'USING(camera,frame_id) WHERE e.event_id=?',(state['event_id'],)).fetchone()
            if not head or tuple(head[1:])!=(state['measured_at'],state['source_sha256']):
                return {}
            source = dict(camera=head[0],format_id=revision)
            # Read the camera/event index once. Only fetch recognition for hours with both brackets.
            rows = []
            for eid,stamp in db.execute('SELECT e.event_id,f.captured_at FROM capture_events e JOIN frames f '
                    'USING(camera,frame_id) WHERE e.camera=? AND e.event_id<=? ORDER BY e.event_id DESC',
                    (head[0],state['event_id'])):
                t = datetime.fromisoformat(stamp)
                if rows and t>=rows[-1][0]:
                    break
                rows.append((t,eid))
                if t<=times[0]:
                    break
            rows.reverse()
            stamps = [r[0] for r in rows]
            stamp_ms = [millis(t) for t in stamps]
            # A stored daily knot usually precedes the clock hour by a few seconds.
            # Move it to the hour using the two actual observations around the tick.
            if offsets is not None and archive and archive.get('points'):
                points=archive['points']
                if (points[-1][:3]==[millis(datetime.fromisoformat(state['measured_at'])),
                                      float(state['value_ft3']),state['event_id']] and
                        archive.get('format')==revision):
                    by_event={p[2]:p for p in points}
                    for tick,target in zip(ticks,times):
                        j=bisect_left(stamps,target)
                        if j==len(rows):
                            continue
                        i=j if stamps[j]==target else j-1
                        if i<0 or rows[i][1] not in by_event:
                            continue
                        p=by_event[rows[i][1]]
                        if p[0]!=stamp_ms[i] or any(l<tick<r for l,r in gaps):
                            continue
                        change={'use':0,'bounds':[0,0]} if i==j else dial_hour(
                            db,source,document,rate,stamps[i],target,rows[i][1],rows[j][1])
                        if change and 'use' in change:
                            offsets.append(dict(time=tick,event=p[2],use=change['use'],bounds=change['bounds']))
            result = {}
            recovered = {}
            def endpoint(index, reference=None, *, photo_only=False):
                from hourly_photo import recover_boundary,recorded_endpoint
                key=(index,reference,photo_only)
                if key not in recovered:
                    recorded=published[ticks[index]]
                    if recorded and not photo_only:
                        recovered[key]=recorded_endpoint(db,source,recorded)
                    else:
                        target=times[index]
                        j=bisect_left(stamps,target)
                        k=j if j<len(rows) and stamps[j]==target else j-1
                        recovered[key]=None
                        if 0<=k<=j<len(rows) and not any(l<stamp_ms[j] and stamp_ms[k]<r or
                                                          l<ticks[index]<r for l,r in gaps):
                            begin=max((r for _,r in gaps if r<=stamp_ms[k]),default=stamp_ms[0])
                            stop=min((l for l,_ in gaps if l>=stamp_ms[j]),default=stamp_ms[-1])
                            recovered[key]=recover_boundary(db,self.photos,document,source,rate,target,
                                rows[k][1],rows[j][1],rows[bisect_left(stamp_ms,begin)][1],
                                rows[bisect_right(stamp_ms,stop)-1][1],dial_hour,self.photo_cache,reference)
                return recovered[key]

            def measured_leg(index):
                if index<=0:
                    return None
                start, end = ticks[index-1:index+1]
                leg = result.get(end)
                if (leg and leg['basis']=='fine_dial' and 'use' in leg and leg['start']==start
                        and all((l,r) in leg['supported_spans'] for l,r in gaps if l<end and start<r)):
                    return leg

            def carry_anchor(index):
                anchor = endpoint(index)
                if anchor:
                    return anchor
                # Look back through consecutive measured changes for a separate
                # absolute reference, stopping at the first unsupported interval.
                change = Decimal(0)
                for j in range(index,0,-1):
                    leg = measured_leg(j)
                    if leg is None:
                        break
                    change += number(leg['use'])
                    prev = j-1
                    if not (published[ticks[prev]] or result.get(ticks[prev],{}).get('basis')=='photo_replay'):
                        continue
                    base = endpoint(prev)
                    if base:
                        reference = base['value']+change
                        anchor = endpoint(index,reference)
                        if anchor:
                            anchor = dict(anchor,reference_time=ticks[prev],reference_value=float(reference))
                        return anchor
                return None
            for i,(start,end) in enumerate(zip(times,times[1:])):
                left,right = bisect_left(stamps,start),bisect_left(stamps,end)
                if left==len(rows) or right==len(rows):
                    continue
                if stamps[left]!=start:
                    left-=1
                if left<0 or start-stamps[left]>=timedelta(minutes=11) or stamps[right]-end>=timedelta(minutes=11):
                    continue
                first,last = rows[left][1],rows[right][1]
                key = (head[0],revision,rate,ticks[i],ticks[i+1],first,last)
                if key not in self.cache:
                    value = dial_hour(db,source,document,rate,start,end,first,last)
                    # A missing recognition can arrive later. Cache completed positive results only.
                    if value:
                        if len(self.cache)>=64:
                            self.cache.pop(next(iter(self.cache)))
                        self.cache[key]=value
                else:
                    value=self.cache[key]
                if value:
                    result[ticks[i+1]]=dict(value,start=ticks[i],end=ticks[i+1])
                # A zoomed rate shares clock-hour endpoints with the wider chart.
                # Prefer that independently recovered register if the dial permits it.
                recover_register = 'use' not in (value or {}) or end-start<timedelta(hours=1)
                if (self.photos and published is not None and recover_register
                        and (published[ticks[i]] is None or published[ticks[i+1]] is None)):
                    from hourly_photo import carried_difference, difference
                    try:
                        opening, closing = endpoint(i), endpoint(i+1)
                        pair = difference(opening, closing)
                        previous = measured_leg(i)
                        if closing and previous and published[ticks[i]] is None:
                            carried = carried_difference(carry_anchor(i-1), previous, closing)
                            if carried and (pair is None or abs(carried['opening']-pair['opening']) <= .01):
                                pair = carried
                        # A published nominal can sit on a different five-foot
                        # turn from the preceding photo. Check an independent
                        # photo at its boundary against the measured travel.
                        if value and 'use' not in value and (pair is None or not
                                value['bounds'][0] <= pair['use'] <= value['bounds'][1]):
                            if opening and not published[ticks[i]] and published[ticks[i+1]]:
                                other = difference(opening, endpoint(i+1, photo_only=True))
                            elif closing and published[ticks[i]] and not published[ticks[i+1]]:
                                other = difference(endpoint(i, photo_only=True), closing)
                            else:
                                other = None
                            pair = None
                            if other and value['bounds'][0] <= other['use'] <= value['bounds'][1]:
                                pair=other
                                pair['bounds']=[max(pair['bounds'][0],value['bounds'][0]),
                                                min(pair['bounds'][1],value['bounds'][1])]
                        if pair and value and (pair['basis']=='carried_register' or end-start<timedelta(hours=1)):
                            spans=value['supported_spans']
                            if all((l,r) in spans for l,r in gaps if l<ticks[i+1] and ticks[i]<r):
                                low,high=value['bounds']
                                if low<=pair['use']<=high:
                                    pair['bounds']=[max(low,pair['bounds'][0]),min(high,pair['bounds'][1])]
                                else:
                                    pair=None
                    except (sqlite3.Error, KeyError, IndexError, TypeError, ValueError, ArithmeticError, OSError):
                        # Optional photo evidence may be absent from older archives.
                        pair=None
                    if pair:
                        result[ticks[i+1]]=dict(pair,start=ticks[i],end=ticks[i+1])
        return result
