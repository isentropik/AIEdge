"""Hourly display summaries from Home Assistant's recorded meter and daily publications."""
from bisect import bisect_left
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from functools import lru_cache
from http.client import HTTPException
import re
from zoneinfo import ZoneInfo

from gas_trend import recorder
from meter_history import millis

HOUR = 3600000
CENT = Decimal('.01')
DAILY = {'range_midpoint_v1', 'observed_increments', 'nominal_meter_movement_v1'}
REGISTER = {'photo_anchored_fine_dial', 'minimum_supported_forward_movement', 'photo_register_hundreds'}


def parsed(rows, entity, zone, daily):
    """Held publications can repeat for hours. Only their original capture time has meaning."""
    result = []
    interrupted = True
    last = None
    epoch = 0
    for row in rows:
        try:
            a = row['attributes']
            if row['entity_id'] != entity or row['state'] in ('unknown', 'unavailable') or a.get('status') in ('stale','held_at_last_reading'):
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
            if last and (stamp,event,digest,value,basis) == last:
                continue
            if last and (stamp <= last[0] or event <= last[1]):
                interrupted = True
                continue
            split = interrupted or not last or stamp-last[0] >= 660000 or basis != last[4] or value < last[3]
            point=(stamp,value,bounds,event,split)
            if not daily:
                if last and value < last[3]:
                    epoch+=1
                identity=(epoch,method,a.get('format_id'),a.get('camera'),a.get('unit_of_measurement'))
                point+= (identity,digest)
            result.append(point)
            last = stamp,event,digest,value,basis
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
        uses_archive=tracked.get('method')=='nominal_meter_movement_v1' and archive.get('points')
        history_end=min(fetch_end,midnight.astimezone(timezone.utc)+timedelta(minutes=12)) if uses_archive else fetch_end
        daily = [p for p in self.readings(self.daily,start,history_end,zone,True,missing) if p[0]<=stamp]
        cuts = sorted(self.breaks(start,fetch_end))
        times = [p[0] for p in registers]
        splits = [p[0] for p in registers if p[4]]
        register_changes = [b[0] for a,b in zip(registers,registers[1:])
                            if a[5][0]!=b[5][0] or a[5][2:]!=b[5][2:]]
        gaps = ((usage or {}).get('movement_history') or {}).get('dial_gaps',[])

        def boundary(t):
            i = bisect_left(times,t)
            if i < len(times) and times[i] == t:
                p=registers[i]
                return p[1],p[2],p[5],[(p[3],p[6])]
            if not 0 < i < len(times):
                return None
            a,b = registers[i-1:i+1]
            if (b[4] or a[5]!=b[5] or bisect_left(cuts,b[0]+1) != bisect_left(cuts,a[0]+1)
                    or any(l<b[0] and a[0]<r for l,r in gaps)):
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
        for t in ticks:
            if datetime.fromtimestamp(t/1000,zone).time()==time.min:
                continue
            i=bisect_left(daily_times,t)
            if i<len(daily) and daily[i][0]==t:
                _,value,bounds,*_=daily[i]
            elif 0<i<len(daily):
                a,b=daily[i-1:i+1]
                if b[4] or bisect_left(cuts,b[0]+1)!=bisect_left(cuts,a[0]+1):
                    continue
                weight=Decimal(t-a[0])/(b[0]-a[0])
                value=a[1]+weight*(b[1]-a[1])
                bounds=(a[2][0],b[2][1]) if a[2] and b[2] else None
            else:
                continue
            daily_hours.append([t,float(value),*(map(float,bounds) if bounds else (None,None))])
        groups,gaps = [],[]
        prior = None
        for t,value,bounds,event,split in daily:
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
        return dict(minutes=minutes,zone=zone_name,end=stamp,midnight=millis(midnight),groups=groups,gaps=gaps,
                    resets=resets,hours=hours,unknownHours=unknown,missing=missing,
                    dailyHours=daily_hours,offsets=offsets)


def ledger_breaks(store,start,end):
    with store.connect() as db:
        rows=db.execute("""SELECT f.captured_at FROM capture_events e JOIN frames f USING(camera,frame_id)
            WHERE e.event_id IN (SELECT after_event_id+1 FROM capture_failure_boundaries
                                 UNION SELECT first_event FROM consumption_segment_links)
            AND julianday(f.captured_at) BETWEEN julianday(?) AND julianday(?)""",
            (start.isoformat(),end.isoformat()))
        return [millis(datetime.fromisoformat(t)) for t, in rows]
