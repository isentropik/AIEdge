"""Hourly display summaries from Home Assistant's recorded meter and daily publications."""
from bisect import bisect_left
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from functools import lru_cache
from http.client import HTTPException
import re
import math
from zoneinfo import ZoneInfo

from gas_trend import recorder
from meter_history import millis

HOUR = 3600000
CENT = Decimal('.01')
DAILY = {'range_midpoint_v1', 'observed_increments', 'nominal_meter_movement_v1'}
REGISTER = {'photo_anchored_fine_dial', 'minimum_supported_forward_movement', 'photo_register_hundreds'}


def tracked_hour(start,end,detail):
    """Position the end of a partial hour with the same evidence as the ten-minute view."""
    step=600000
    legs={q['start']:q for q in detail['hours'] if q.get('end')==q.get('start',0)+step}
    levels={t:(value,basis) for t,value,basis in detail['trackedLevels']}
    spans={(q['start'],q['end']):q for q in detail.get('evidenceSpans',())}
    used=0
    bounds=[0,0]
    covered=0
    cursor=start
    while cursor<end:
        leg=legs.get(cursor)
        if leg is not None:
            used+=leg['use']
            bounds=[a+b for a,b in zip(bounds,leg['bounds'])] if bounds and leg.get('bounds') else None
            covered+=1
            cursor+=step
            continue
        first=cursor
        cursor+=step
        while cursor<end and cursor not in legs:
            cursor+=step
        left,right=levels.get(first),levels.get(cursor)
        if not left or not right or left[1]!=right[1] or right[0]<left[0]:
            return None
        delta=right[0]-left[0]
        span=spans.get((first,cursor))
        if span:
            lo,hi=span['bounds']
            if 'use' not in span and delta>hi:
                return None
            delta=span.get('use',max(lo,delta))
            bounds=[bounds[0]+lo,bounds[1]+hi] if bounds else None
        else:
            bounds=None
        used+=delta
    if covered:
        result=dict(start=start,end=end,use=used)
        if bounds:
            result['bounds']=bounds
        return result


def flow_ceiling(document,policy):
    if not document or document.get('unit')!='ft3':
        return None
    from reading_format import validate
    try:
        _,revision=validate(document)
        ceiling=float(document['maximum_rate_per_second'])
        if policy and policy.get('pipeline_id')==document['pipeline_id'] and policy.get('format_id')==revision:
            ceiling=min(ceiling,float(policy['capacity_cfh'])/3600)
        return ceiling if math.isfinite(ceiling) and ceiling>0 else None
    except (KeyError,TypeError,ValueError,ArithmeticError):
        return None


def parsed(rows, entity, zone, daily):
    """Held publications can repeat for hours. Only their original capture time has meaning."""
    result = []
    interrupted = True
    last = None
    last_publication = None
    epoch = 0
    for row in rows:
        try:
            a = row['attributes']
            if row['entity_id'] != entity or row['state'] in ('unknown', 'unavailable'):
                interrupted = True
                continue
            if a.get('status') in ('stale','held_at_last_reading'):
                # The publisher can repeat the previous observation between two
                # fresh ones. Its publication time is neither a sample nor a cut.
                same = (row['state'], a.get('event_id'), a.get('source_sha256'), a.get('value_ft3'),
                        a.get('measured_at'), a.get('anchor_event_id'), a.get('method'))
                precision = daily or a.get('method') == 'photo_anchored_fine_dial'
                if not precision or a['status'] != 'held_at_last_reading' or last is None or same != last_publication:
                    interrupted = True
                continue
            method = a['method']
            if method not in (DAILY if daily else REGISTER):
                interrupted = True
                continue
            t = datetime.fromisoformat(a['measured_at'])
            event, digest = a['event_id'], a['source_sha256']
            value = Decimal(str(a['value_ft3']))
            if (t.utcoffset() is None or type(event) != int or event <= 0 or not re.fullmatch('[a-f0-9]{64}',digest)
                    or not value.is_finite() or value < 0 or Decimal(row['state']) != value
                    or daily and (a['timezone'] != zone.key or a['day'] != t.astimezone(zone).date().isoformat())):
                raise ValueError()
            bounds = None
            if a.get('lower_ft3') is not None and a.get('upper_ft3') is not None:
                lo,hi = (Decimal(str(a[k])) for k in ('lower_ft3','upper_ft3'))
                same = not a.get('bounds_event_id') or (a['bounds_event_id'],a.get('bounds_measured_at'),a.get('bounds_source_sha256')) == (event,a['measured_at'],digest)
                if same and lo.is_finite() and hi.is_finite() and 0 <= lo <= hi and (daily or lo<=value<=hi):
                    bounds = lo,hi
            stamp = millis(t)
            basis = (method,a.get('anchor_event_id'),a.get('day'))
            if daily:
                coverage=a.get('coverage_started_at')
                if isinstance(coverage,str):
                    try:
                        origin=datetime.fromisoformat(coverage)
                        if origin.utcoffset() is None or origin>t or origin.astimezone(zone).date()!=t.astimezone(zone).date():
                            coverage=None
                    except (ValueError,OverflowError):
                        coverage=None
                else:
                    coverage=None
                basis+=(coverage,)
            if last and (stamp,event,digest,value,basis) == last:
                continue
            if last and (stamp <= last[0] or event <= last[1]):
                interrupted = True
                continue
            split = interrupted or not last or stamp-last[0] >= 660000 or basis != last[4] or value < last[3]
            point=(stamp,value,bounds,event,split)
            if daily:
                if last and (basis!=last[4] or value<last[3]):
                    epoch+=1
                point+=( (basis,epoch), )
            else:
                if last and value < last[3]:
                    epoch+=1
                identity=(epoch,method,a.get('format_id'),a.get('camera'),a.get('unit_of_measurement'))
                point+= (identity,digest)
            result.append(point)
            last = stamp,event,digest,value,basis
            last_publication = (row['state'],event,digest,a['value_ft3'],a['measured_at'],a.get('anchor_event_id'),method)
            interrupted = False
        except (KeyError, TypeError, ValueError, ArithmeticError, OverflowError):
            interrupted = True
    return result


class ChartHours:
    def __init__(self, meter, daily, fetch=recorder, breaks=lambda a,b: (), ledger=None):
        self.meter, self.daily, self.fetch, self.breaks = meter,daily,fetch,breaks
        self.ledger = ledger
        self.closed_page = lru_cache(maxsize=28)(self.page)

    def page(self, entity, start, end):
        history = self.fetch(entity,start,end)
        if not isinstance(history,list) or len(history)>1 or history and not isinstance(history[0],list):
            raise ValueError('unexpected_history')
        return history[0] if history else []

    def rows(self, entity, start, end):
        # Fixed three-hour pages can be shared across views. Leave recent recorder writes uncached.
        cur = start.replace(hour=start.hour-start.hour%3,minute=0,second=0,microsecond=0)
        closed = datetime.now(timezone.utc)-timedelta(minutes=15)
        rows = []
        while cur < end:
            stop = min(end,cur+timedelta(hours=3))
            read = self.closed_page if stop-cur == timedelta(hours=3) and stop < closed else self.page
            rows.extend(read(entity,cur,stop))
            cur = stop
        return rows

    def readings(self, entity, start, end, zone, daily, missing):
        try:
            return parsed(self.rows(entity,start,end),entity,zone,daily)
        except (OSError, HTTPException, ValueError, KeyError):
            missing.append('daily' if daily else 'register')
            return []

    def snapshot(self, stamp, zone_name, usage=None, document=None, policy=None, minutes=60):
        zone = ZoneInfo(zone_name)
        end = datetime.fromtimestamp(stamp/1000,timezone.utc)
        if minutes not in (10,60):
            raise ValueError('unsupported_chart_interval')
        # Two hours contain the full last-hour window plus its preceding clock-hour anchor.
        start = end-timedelta(hours=2 if minutes==10 else 25)
        today = end.astimezone(zone).date()
        midnight = datetime.combine(today,time.min,zone)
        # Recorder indexing uses publication time. Use the capture timestamp for math and
        # admit delayed publications only if they describe a reading in this snapshot.
        fetch_end = end+timedelta(minutes=12)
        missing = []
        registers = [p for p in self.readings(self.meter,start,fetch_end,zone,False,missing) if p[0]<=stamp]
        archive=(usage or {}).get('movement_history') or {}
        tracked=(usage or {}).get('daily_nominal') or {}
        uses_archive=(tracked.get('method')=='nominal_meter_movement_v1' and archive.get('points')
                      and archive.get('midnight')==millis(midnight) and tracked.get('day')==today.isoformat())
        daily = [p for p in self.readings(self.daily,start,fetch_end,zone,True,missing) if p[0]<=stamp]
        cuts = sorted(self.breaks(start,fetch_end))
        times = [p[0] for p in registers]
        splits = [p[0] for p in registers if p[4]]
        register_changes = [b[0] for a,b in zip(registers,registers[1:])
                            if a[5][0]!=b[5][0] or a[5][2:]!=b[5][2:]]
        gaps = ((usage or {}).get('movement_history') or {}).get('dial_gaps',[])
        # The daily accumulator starts at its first capture after midnight.
        # That reporting boundary is not a break in the absolute register.
        first = archive.get('points') or []
        prefix = [millis(midnight), first[0][0]] if first and archive.get('midnight') == millis(midnight) else None

        def boundary(t):
            i = bisect_left(times,t)
            if i < len(times) and times[i] == t:
                p=registers[i]
                return p[1],p[2],p[5],[(p[3],p[6])]
            if not 0 < i < len(times):
                return None
            a,b = registers[i-1:i+1]
            if (b[4] or a[5]!=b[5] or bisect_left(cuts,b[0]+1) != bisect_left(cuts,a[0]+1)
                    or any(l<b[0] and a[0]<r and not (
                        [l,r]==prefix and a[5][1]=='photo_anchored_fine_dial' and
                        a[0]<l<=r==b[0] and b[3]==first[0][2]) for l,r in gaps)):
                return None
            weight = Decimal(t-a[0])/(b[0]-a[0])
            # A monotone register can be anywhere between its bracketing readings.
            bounds = (a[2][0],b[2][1]) if a[2] and b[2] else None
            return a[1]+weight*(b[1]-a[1]),bounds,a[5],[(a[3],a[6]),(b[3],b[6])]

        ticks = []
        cursor = start.replace(second=0,microsecond=0)
        while cursor <= end:
            if cursor.astimezone(zone).minute % minutes == 0:
                ticks.append(millis(cursor))
            cursor += timedelta(minutes=1)
        published={t:boundary(t) for t in ticks}
        offsets = []
        optical = self.ledger.snapshot(ticks,(usage or {}).get('daily_nominal'),document,policy or {},published,gaps,
                                       (usage or {}).get('movement_history'),offsets) if self.ledger else {}
        hours = []
        for a,b in zip(ticks,ticks[1:]):
            left,right = published[a],published[b]
            measured = optical.get(b)
            if measured and measured['basis']=='carried_register':
                carry=measured['carry']
                origin=carry.get('reference_time',carry['start'])
                if not any(origin<t<=b for t in register_changes):
                    hours.append(measured)
                continue
            if measured and measured['basis']=='photo_replay':
                if not any(a<t<=b for t in register_changes):
                    hours.append(measured)
                continue
            internal=[(l,r) for l,r in gaps if l<b and a<r]
            if measured and any(span not in measured.get('supported_spans',()) for span in internal):
                measured=None
            if measured:
                measured = {k:v for k,v in measured.items() if k!='supported_spans'}
            crossed = (bisect_left(cuts,b+1)!=bisect_left(cuts,a+1) or
                       bisect_left(splits,b+1)!=bisect_left(splits,a+1) or internal)
            # Independently positioned absolute registers survive an interior
            # acquisition break. Relative and coarse readings cannot establish
            # consumption across that break solely from their published numbers.
            if (not left or not right or left[2]!=right[2] or right[0]<left[0]
                    or crossed and left[2][1]!='photo_anchored_fine_dial'):
                if measured and 'use' in measured:
                    hours.append(measured)
                continue
            bounds = None
            delta = right[0]-left[0]
            if left[1] and right[1]:
                lo=max(Decimal(0),right[1][0]-left[1][1])
                hi=right[1][1]-left[1][0]
                if hi>=lo:
                    bounds=[float(lo.quantize(CENT,rounding=ROUND_FLOOR)),float(hi.quantize(CENT,rounding=ROUND_CEILING))]
            if measured:
                lo,hi=measured['bounds']
                if not lo<=float(delta)<=hi:
                    if 'use' in measured:
                        hours.append(measured)
                    continue
                bounds=[max(bounds[0],lo),min(bounds[1],hi)] if bounds else [lo,hi]
            hours.append(dict(start=a,end=b,use=float(delta),bounds=bounds,basis='register',
                              opening=float(left[0]),closing=float(right[0])))

        # Sample the previous day's daily series at clock hours before downsampling it.
        # Raw interruptions matter only when they prevent a boundary from being measured.
        daily_times=[p[0] for p in daily]
        daily_hours=[]
        tracked_levels=[]
        for t in ticks:
            if datetime.fromtimestamp(t/1000,zone).time()==time.min:
                continue
            i=bisect_left(daily_times,t)
            if i<len(daily) and daily[i][0]==t:
                _,value,bounds,*_=daily[i]
                identity=daily[i][5]
            elif 0<i<len(daily):
                a,b=daily[i-1:i+1]
                if b[4] or bisect_left(cuts,b[0]+1)!=bisect_left(cuts,a[0]+1):
                    continue
                weight=Decimal(t-a[0])/(b[0]-a[0])
                value=a[1]+weight*(b[1]-a[1])
                bounds=(a[2][0],b[2][1]) if a[2] and b[2] else None
                identity=a[5]
            else:
                continue
            if identity[0][0]=='nominal_meter_movement_v1':
                tracked_levels.append([t,float(value),identity])
            if not uses_archive or t<millis(midnight):
                daily_hours.append([t,float(value),*(map(float,bounds) if bounds else (None,None))])
        groups,gaps = [],[]
        prior = None
        for t,value,bounds,event,split,_ in daily:
            if t >= millis(midnight):
                break
            local=datetime.fromtimestamp(t/1000,zone)
            bucket=(local.date(),local.hour,local.fold)
            if prior is None or bucket[0]!=prior[1][0]:
                groups.append([])
            elif split or bisect_left(cuts,t+1)!=bisect_left(cuts,prior[0]+1):
                gaps.append([prior[0],t])
            group=groups[-1]
            point=[t,float(value),*(map(float,bounds) if bounds else (None,None)),event]
            if len(group)>1 and prior[1]==bucket:
                group[-1]=point
            else:
                group.append(point)
            prior=t,bucket
        resets=[t for t in ticks if datetime.fromtimestamp(t/1000,zone).time()==time.min]
        supported={h['end'] for h in hours}
        unknown=[[a,b] for a,b in zip(ticks,ticks[1:]) if b not in supported]
        partial=[]
        spans=[]
        openings=[]
        @lru_cache(maxsize=None)
        def fine_at(t):
            return self.snapshot(min(t+59000,stamp),zone_name,usage,document,policy,10)
        available={p[0] for p in tracked_levels}
        starts={p[5][0][3] for p in daily if p[5][0][0]=='nominal_meter_movement_v1' and p[5][0][3]}
        for opening in sorted(starts) if self.ledger else ():
            try:
                when=datetime.fromisoformat(opening)
                if when.utcoffset() is None:continue
                local=when.astimezone(zone)
                day_start=datetime.combine(local.date(),time.min,zone)
            except (TypeError,ValueError,OverflowError):
                continue
            if when-day_start<timedelta(minutes=10) or not start<=when<=end:continue
            first=next((t for t in ticks if t/1000>=when.timestamp()),None)
            if first is None:continue
            if minutes==10:
                level=self.ledger.opening(opening,first,day_start,tracked,document,policy or {})
            else:
                # Seed the hourly view from exactly the same partial first hour as the fine view.
                detail=fine_at(first)
                level=next((p[:] for p in detail['openingLevels'] if when.timestamp()<=p[0]/1000<=first/1000),None)
                legs={q['start']:q for q in detail['hours']}
                while level and level[0]<first:
                    q=legs.get(level[0])
                    if not q:level=None;break
                    lo,hi=q['bounds'] if q.get('bounds') else (None,None)
                    level=[q['end'],level[1]+q['use'],level[2]+lo if level[2] is not None and lo is not None else None,
                           level[3]+hi if level[3] is not None and hi is not None else None]
            if level:openings.append(level)
        if minutes==10 and self.ledger:
            # The outer boundaries around a missing clock tick can still
            # constrain total dial travel. They cannot place it on that tick.
            runs=[]
            for a,b in unknown:
                if runs and runs[-1][1]==a:
                    runs[-1][1]=b
                else:
                    runs.append([a,b])
            for a,b in runs:
                if a not in available or b not in available or any(a<t<=b for t in register_changes):
                    continue
                inner=(archive.get('dial_gaps') or [])
                leg=self.ledger.snapshot([a,b],tracked,document,policy or {},{t:published[t] for t in (a,b)},inner).get(b)
                if not leg or not leg.get('bounds'):
                    continue
                if leg['basis']=='fine_dial' and any((l,r) not in leg.get('supported_spans',()) for l,r in inner if l<b and a<r):
                    continue
                spans.append({k:leg[k] for k in ('start','end','bounds','use') if k in leg})
        if minutes==60 and self.ledger:
            for a,b in unknown:
                if a not in available or b not in available:
                    continue
                detail=fine_at(b)
                increment=tracked_hour(a,b,detail) if not detail['missing'] else None
                if increment:
                    partial.append(increment)
        return dict(minutes=minutes,zone=zone_name,end=stamp,midnight=millis(midnight),groups=groups,gaps=gaps,
                    resets=resets,hours=hours,unknownHours=unknown,missing=missing,
                    dailyHours=daily_hours,offsets=offsets,trackedLevels=tracked_levels,partialHours=partial,evidenceSpans=spans,
                    openingLevels=openings,
                    flowCeiling=flow_ceiling(document,policy))


def ledger_breaks(store,start,end):
    with store.connect() as db:
        rows=db.execute("""SELECT f.captured_at FROM capture_events e JOIN frames f USING(camera,frame_id)
            WHERE e.event_id IN (SELECT after_event_id+1 FROM capture_failure_boundaries
                                 UNION SELECT first_event FROM consumption_segment_links)
            AND julianday(f.captured_at) BETWEEN julianday(?) AND julianday(?)""",
            (start.isoformat(),end.isoformat()))
        return [millis(datetime.fromisoformat(t)) for t, in rows]
