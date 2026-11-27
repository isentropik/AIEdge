"""Hourly display summaries from Home Assistant's recorded meter and daily publications."""
from bisect import bisect_left
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from functools import lru_cache
from http.client import HTTPException
import re
import math
import hashlib
import json
import logging
import time as clock
from threading import Event, Lock
from zoneinfo import ZoneInfo

from gas_trend import recorder
from meter_history import millis

HOUR = 3600000
CENT = Decimal('.01')
DAILY = {'range_midpoint_v1', 'observed_increments', 'nominal_meter_movement_v1'}
REGISTER = {'photo_anchored_fine_dial', 'minimum_supported_forward_movement', 'photo_register_hundreds'}


def chart_head(usage):
    """A held daily accumulator cannot hold back a newer published register."""
    daily = usage.get('daily_nominal') or {}
    absolute = usage.get('absolute_nominal') or {}
    if absolute.get('method') != 'photo_anchored_fine_dial' or not absolute.get('event_id'):
        return daily
    # Event times can have different offsets or precision; compare the instants.
    try:
        at = datetime.fromisoformat(absolute['measured_at'])
        if (at.tzinfo is not None and re.fullmatch('[0-9a-f]{64}',absolute.get('source_sha256','')) and
                math.isfinite(float(absolute['value_ft3'])) and float(absolute['value_ft3'])>=0 and
                (not daily.get('measured_at') or at>datetime.fromisoformat(daily['measured_at']))):
            return absolute
    except (KeyError, ValueError, TypeError, OverflowError):
        pass
    return daily


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
    from absolute_motion import meter_rate
    try:
        validate(document)
        ceiling=float(meter_rate(document))
        return ceiling if math.isfinite(ceiling) and ceiling>0 else None
    except (KeyError,TypeError,ValueError,ArithmeticError):
        return None


def parsed(rows, entity, zone, daily, photo_levels=None, sources=None):
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
                # A held register can still identify its original exposure.
                # Store it separately for matching against the archived photo.
                if photo_levels is not None and a.get('status')=='held_at_last_reading' and a.get('method')=='photo_anchored_fine_dial':
                    source=(a.get('event_id'),a.get('source_sha256'),a.get('measured_at'))
                    if source not in photo_levels:
                        original=parsed([dict(row,attributes=dict(a,status='estimated'))],entity,zone,False)
                        if original:
                            photo_levels[source]=float(original[0][1])
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
            if photo_levels is not None and method=='photo_anchored_fine_dial':
                photo_levels[event,digest,a['measured_at']]=float(value)
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
                # The add-on publishes value_ft3. Recorder adds the display
                # unit from discovery, which is absent on the same live event.
                unit=a.get('unit_of_measurement')
                if unit is None and method=='photo_anchored_fine_dial':
                    unit='ft³'
                identity=(epoch,method,a.get('format_id'),a.get('camera'),unit)
                point+= (identity,digest)
            result.append(point)
            if sources is not None and method=='photo_anchored_fine_dial':
                sources[event,digest]=a
            last = stamp,event,digest,value,basis
            last_publication = (row['state'],event,digest,a['value_ft3'],a['measured_at'],a.get('anchor_event_id'),method)
            interrupted = False
        except (KeyError, TypeError, ValueError, ArithmeticError, OverflowError):
            interrupted = True
    return result


def register_gaps(archive, rows, times, cuts):
    """Keep acquisition gaps when interpreting the daily accumulator's coverage."""
    gaps = archive.get('dial_gaps') or []
    points = archive.get('points')
    midnight = archive.get('midnight')
    if not gaps or not points or midnight is None:
        return gaps
    first_time, _, first_event, *_ = points[0]
    prefix = [midnight, first_time]
    if (first_time <= midnight or prefix not in gaps
            or archive.get('dial_from', [first_event, first_time]) != [first_event, first_time]):
        return gaps
    i = bisect_left(times, first_time)
    if not 0 < i < len(rows):
        return gaps
    before, after = rows[i-1:i+1]
    # Only lift the day-opening marker when the same register brackets
    # midnight and the next photo is the accumulator's first observation.
    if (before[0] > midnight or after[0] != first_time or after[3] != first_event or after[4]
            or before[5] != after[5] or before[5][1] != 'photo_anchored_fine_dial'
            or bisect_left(cuts, after[0]+1) != bisect_left(cuts, before[0]+1)):
        return gaps
    return [gap for gap in gaps if gap != prefix]


def measured_hours(ticks,published,optical,gaps,cuts,splits,register_changes):
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
    # Optical rate proofs store volume over their exact interval. The chart
    # divides by elapsed hours for the rate, and accumulates the same volume
    # bounds from midnight while retaining the observed register endpoints.
    for i, hour in enumerate(hours):
        start, end = hour['start'], hour['end']
        leg = optical.get(end)
        if not leg or leg.get('start') != start or leg.get('end') != end:
            continue
        proof = leg.get('optical_rate') or {}
        bands = proof.get('bands') or []
        if len(bands) != 1 or proof.get('use') is None:
            continue
        if (bisect_left(cuts, end+1) != bisect_left(cuts, start+1)
                or any(left < end and start < right for left, right in gaps)):
            continue
        lo, hi = bands[0]
        if not 0 <= lo <= proof['use'] <= hi or not math.isfinite(hi):
            continue
        if hour.get('bounds'):
            lo = max(lo, hour['bounds'][0])
            hi = min(hi, hour['bounds'][1])
        if lo <= hour['use'] <= hi:
            hours[i] = dict(hour, bounds=[lo, hi])
    return hours


class ChartHours:
    def __init__(self, meter, daily, fetch=recorder, breaks=lambda a,b: (), ledger=None):
        self.meter, self.daily, self.fetch, self.breaks = meter,daily,fetch,breaks
        self.ledger = ledger
        self.closed_page = lru_cache(maxsize=28)(self.page)
        self.profile_lock = Lock()
        self.build_lock = Lock()
        self.stopping = Event()
        self.last_profile = None

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
            if self.stopping.is_set():
                raise InterruptedError('chart_shutdown')
            stop = min(end,cur+timedelta(hours=3))
            read = self.closed_page if stop-cur == timedelta(hours=3) and stop < closed else self.page
            rows.extend(read(entity,cur,stop))
            cur = stop
        return rows

    def readings(self, entity, start, end, zone, daily, missing, photo_levels=None, sources=None):
        try:
            return parsed(self.rows(entity,start,end),entity,zone,daily,photo_levels,sources)
        except (OSError, HTTPException, ValueError, KeyError):
            missing.append('daily' if daily else 'register')
            return []

    def published_window(self, stamp, zone_name, window, usage, document, policy):
        """First paint from published meter observations. Optical reconciliation follows separately."""
        zone = ZoneInfo(zone_name)
        minute = 60000
        step = 10*minute if window == '1' else HOUR
        end = stamp//minute*minute
        while datetime.fromtimestamp(end/1000,zone).minute % (step//minute):
            end -= minute
        midnight = datetime.combine(datetime.fromtimestamp(stamp/1000,zone).date(),time.min,zone)
        start = millis(midnight) if window == 'today' else end-int(window)*HOUR
        first = start-step
        key = self.profile_key(zone_name,usage,document,policy)
        with self.profile_lock:
            cached = self.last_profile
        if cached and key and key == cached[0] and end-step <= cached[1]['end'] <= stamp:
            data = cached[1]
            p = data['registerProfile']
            close = end if data['end']>=end else end-step
            begin = start if window=='today' else close-int(window)*HOUR
            if (data['midnight']==millis(midnight) and millis(midnight)<=close and begin<=close and
                    p['points'][0][0]<=begin-step and p['points'][-1][0]>=close):
                lower = begin-step
                hours = [dict(start=q['start'],end=q['end'],bounds=q['bounds']) for q in data['hours']
                         if q.get('bounds') and q['end']>lower and q['start']<close]
                profile = dict(p,points=[r for r in p['points'] if lower<=r[0]<=close],
                               fineBounds=[r for r in p['fineBounds'] if lower<r[1] and r[0]<close])
                profile['rateIntervals']=[r for r in p.get('rateIntervals',[]) if lower<=r[0] and r[1]<=close]
                profile['changeBounds']=[r for r in p.get('changeBounds',[]) if lower<=r[1]<=close]
                profile['estimatedChangeBounds']=[r for r in p.get('estimatedChangeBounds',[]) if lower<=r[1]<=close]
                profile['supportedTicks']=[t for t in p.get('supportedTicks',[]) if lower<=t<=close]
                profile['photoConflicts']=[q for q in p.get('photoConflicts',[]) if begin<=q['time']<=close]
                for field in ('gaps','modeled','conflicts','recoveredGaps','unknownGaps'):
                    profile[field] = [r for r in p.get(field,[]) if lower<r[1] and r[0]<close]
                for field in ('registerHead','readingEstimates'):
                    profile.pop(field,None)
                return dict(end=stamp,asOf=data['end'],window=window,zone=zone_name,midnight=data['midnight'],
                            start=begin,close=close,hours=hours,registerProfile=profile)
        first_day = datetime.fromtimestamp(start/1000,zone).date()
        since = datetime.fromtimestamp((first-11*minute)/1000,timezone.utc)
        until = datetime.fromtimestamp(stamp/1000,timezone.utc)+timedelta(minutes=12)
        missing = []
        rows = [r for r in self.readings(self.meter,since,until,zone,False,missing)
                if r[0] <= stamp]
        times = [r[0] for r in rows]
        epochs = {identity:i for i,identity in enumerate(dict.fromkeys(r[5] for r in rows))}
        cuts = sorted(self.breaks(since,until))
        gaps = register_gaps(usage.get('movement_history') or {}, rows, times, cuts)
        def interrupted(a,b):
            return bisect_left(cuts,b+1)!=bisect_left(cuts,a+1) or any(l<b and a<r for l,r in gaps)
        def observed(t):
            i = bisect_left(times,t)
            if i < len(rows) and times[i] == t:
                a = b = rows[i]
            elif 0 < i < len(rows):
                a,b = rows[i-1:i+1]
                if b[4] or a[5]!=b[5] or interrupted(a[0],b[0]):
                    return None
            else:
                return None
            if a[5][1] != 'photo_anchored_fine_dial':
                return None
            value = a[1] if a is b else a[1]+(b[1]-a[1])*Decimal(t-a[0])/(b[0]-a[0])
            bounds = (float(a[2][0]),float(b[2][1])) if a[2] and b[2] else (None,None)
            return [float(value),*bounds,epochs[a[5]]]
        samples = []
        for t in range(first,end+1,step):
            point = observed(t)
            if point is not None:
                samples.append([t,*point])
        openings = {}
        for day in (first_day,midnight.date()):
            t = millis(datetime.combine(day,time.min,zone))
            point = observed(t)
            openings[t] = [*point,False] if point is not None else None
        # An interrupted interval can have observed endpoints. Defer its rate
        # until historical evidence can establish what those endpoints support.
        breaks = [r[0] for r in rows if r[4]]
        blocked = [t for t in range(start,end+1,step) if interrupted(t-step,t) or
                   bisect_left(breaks,t+1)!=bisect_left(breaks,t-step+1)]
        return dict(end=stamp,zone=zone_name,window=window,start=start,close=end,midnight=millis(midnight),
                    points=samples,openings=openings,blocked=blocked,ceiling=flow_ceiling(document,policy))

    @staticmethod
    def profile_key(zone,usage,document,policy):
        archive=(usage or {}).get('movement_history') or {}
        if not archive.get('format') or not document:
            return None
        return [zone,archive['format'],archive.get('dial_from'),archive.get('dial_gaps',[]),
                (usage.get('absolute_nominal') or {}).get('method'),document,policy]

    def prepared(self, stamp, zone, usage, document, policy):
        """Serve the latest completed chart interval at its original evidence timestamp."""
        key = self.profile_key(zone, usage, document, policy)
        with self.build_lock:
            if self.stopping.is_set():
                raise InterruptedError('chart_shutdown')
            with self.profile_lock:
                cached = self.last_profile
            if key and cached and cached[0] == key:
                data = cached[1]
                local = datetime.fromtimestamp(stamp/1000, ZoneInfo(zone))
                tick = millis(local.replace(minute=local.minute//10*10, second=0, microsecond=0))
                if tick <= data['end'] <= stamp and data['registerProfile']['points'][-1][0] >= tick:
                    return data
            return self.snapshot(stamp,zone,usage,document,policy,profile=True)

    def snapshot(self, stamp, zone_name, usage=None, document=None, policy=None, minutes=60, *, profile=False):
        zone = ZoneInfo(zone_name)
        end = datetime.fromtimestamp(stamp/1000,timezone.utc)
        if minutes not in (10,60):
            raise ValueError('unsupported_chart_interval')
        # Two hours contain the full last-hour window plus its preceding clock-hour anchor.
        start = end-timedelta(hours=2 if minutes==10 else 25)
        today = end.astimezone(zone).date()
        midnight = datetime.combine(today,time.min,zone)
        if profile:
            # The first visible rate needs its preceding interval. A rolling
            # window crossing midnight also needs the prior day's opening.
            earliest = (end-timedelta(hours=29)).astimezone(zone).date()
            start = datetime.combine(earliest,time.min,zone).astimezone(timezone.utc)-timedelta(minutes=11)
        # Recorder indexing uses publication time. Use the capture timestamp for math and
        # admit delayed publications only if they describe a reading in this snapshot.
        fetch_end = end+timedelta(minutes=12)
        missing = []
        photo_levels={} if profile else None
        replay = getattr(self.ledger, 'register_replay', None) if profile else None
        sources = {} if replay else None
        registers = [p for p in self.readings(self.meter,start,fetch_end,zone,False,missing,photo_levels,sources) if p[0]<=stamp]
        archive=(usage or {}).get('movement_history') or {}
        tracked=(usage or {}).get('daily_nominal') or {}
        uses_archive=(tracked.get('method')=='nominal_meter_movement_v1' and archive.get('points')
                      and archive.get('midnight')==millis(midnight) and tracked.get('day')==today.isoformat())
        daily = [p for p in self.readings(self.daily,start,fetch_end,zone,True,missing) if p[0]<=stamp]
        # Recorder can lag the Overview by one publication. Accept that
        # event at its own timestamp through the same validation as history.
        if profile:
            for rows,head,entity,is_daily in ((registers,(usage or {}).get('absolute_nominal'),self.meter,False),
                                              (daily,tracked,self.daily,True)):
                if head and head.get('status') not in ('held_at_last_reading','stale'):
                    tail=parsed([dict(entity_id=entity,state=head.get('value_ft3'),attributes=head)],entity,zone,is_daily)
                    if tail and (not rows or rows[-1][0]<tail[0][0]<=stamp and rows[-1][3]<tail[0][3]) and tail[0][0]<=stamp:
                        p=list(tail[0])
                        if rows:
                            prior=rows[-1]
                            epoch=prior[5][1] if is_daily else prior[5][0]
                            if is_daily:
                                p[5]=(p[5][0],epoch+int(p[5][0]!=prior[5][0] or p[1]<prior[1]))
                            else:
                                p[5]=(epoch+int(p[1]<prior[1]),*p[5][1:])
                            p[4]=p[5]!=prior[5] or p[0]-prior[0]>=660000
                        rows.append(tuple(p))
        if self.stopping.is_set():
            raise InterruptedError('chart_shutdown')
        if replay and registers:
            last = registers[-1]
            head = (usage or {}).get('absolute_nominal') or {}
            # A historical window may end before the current full-register photo.
            # Its last accepted exposure identifies the anchor that was in use then.
            if (head.get('event_id'),head.get('source_sha256')) != (last[3],last[6]):
                recorded = sources.get((last[3],last[6]))
                if recorded and recorded.get('anchor_event_id') != head.get('anchor_event_id'):
                    # Browsing an older anchor must not discard ongoing work on the live chart.
                    replay = self.ledger.historical_register_replay
                head = recorded
            registers = replay.readings(registers, head, document, policy, self.stopping)
        cuts = sorted(self.breaks(start,fetch_end))
        times = [p[0] for p in registers]
        splits = [p[0] for p in registers if p[4]]
        register_changes = [b[0] for a,b in zip(registers,registers[1:])
                            if a[5][0]!=b[5][0] or a[5][2:]!=b[5][2:]]
        outages = register_gaps(archive, registers, times, cuts)

        def boundary(t):
            i = bisect_left(times,t)
            if i < len(times) and times[i] == t:
                p=registers[i]
                return p[1],p[2],p[5],[(p[3],p[6])]
            if not 0 < i < len(times):
                return None
            a,b = registers[i-1:i+1]
            if (b[4] or a[5]!=b[5] or bisect_left(cuts,b[0]+1) != bisect_left(cuts,a[0]+1)
                    or any(l<b[0] and a[0]<r for l,r in outages)):
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
        head=chart_head(usage or {})
        optical = self.ledger.snapshot(ticks,head,document,policy or {},published,outages,
                                       archive,offsets,tracked) if self.ledger else {}
        hours = measured_hours(ticks,published,optical,outages,cuts,splits,register_changes)

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
                leg=self.ledger.snapshot([a,b],tracked,document,policy or {},{t:published[t] for t in (a,b)},outages).get(b)
                if not leg or not leg.get('bounds'):
                    continue
                if leg['basis']=='fine_dial' and any((l,r) not in leg.get('supported_spans',()) for l,r in outages if l<b and a<r):
                    continue
                spans.append({k:leg[k] for k in ('start','end','bounds','use') if k in leg})
        if minutes==60 and self.ledger and not profile:
            for a,b in unknown:
                if a not in available or b not in available:
                    continue
                detail=fine_at(b)
                increment=tracked_hour(a,b,detail) if not detail['missing'] else None
                if increment:
                    partial.append(increment)
        result = dict(minutes=minutes,zone=zone_name,end=stamp,midnight=millis(midnight),groups=groups,gaps=gaps,
                    resets=resets,hours=hours,unknownHours=unknown,missing=missing,
                    dailyHours=daily_hours,offsets=offsets,trackedLevels=tracked_levels,partialHours=partial,evidenceSpans=spans,
                    openingLevels=openings,
                    flowCeiling=flow_ceiling(document,policy))
        if minutes==10:
            result['rateIntervals']=[[q['start'],t,q['optical_rate']] for t,q in optical.items() if 'optical_rate' in q]
        if profile:
            from register_chart import register_profile
            photos = self.ledger.gap_registers(outages, tracked, document) if self.ledger and document else {}
            # Recover sub-hour optical anchors only where the absolute series
            # cannot resolve an hour. All zooms consume these same anchors.
            fine_legs = []
            rate_intervals = [[q['start'],t,q['optical_rate']] for t,q in optical.items() if 'optical_rate' in q]
            if self.ledger and document:
                spans = []
                last_tick = stamp - stamp % 60000
                while datetime.fromtimestamp(last_tick/1000,zone).minute % 10:
                    last_tick -= 60000
                for a,b in zip(ticks,[*ticks[1:],last_tick]):
                    if b<=a or b<stamp-26*HOUR:
                        continue
                    if published.get(a) and published.get(b) and b<stamp-2*HOUR:
                        continue
                    if spans and spans[-1][1]==a:
                        spans[-1][1]=b
                    else:
                        spans.append([a,b])
                for a,b in spans:
                    if self.stopping.is_set():
                        raise InterruptedError('chart_shutdown')
                    fine_ticks=list(range(a,b+1,600000))
                    if len(fine_ticks)<2:
                        continue
                    positions={t:boundary(t) for t in fine_ticks}
                    observed=self.ledger.snapshot(fine_ticks,head,document,policy or {},positions,outages)
                    rate_intervals.extend([q['start'],t,q['optical_rate']] for t,q in observed.items() if 'optical_rate' in q)
                    fine_legs.extend(measured_hours(fine_ticks,positions,observed,outages,cuts,splits,register_changes))
            gap_flow = getattr(self.ledger,'gap_flow',None)
            flow = gap_flow(start,stamp,tracked,document,result['flowCeiling']) if gap_flow else []
            result['registerProfile'] = register_profile(stamp, zone, registers, daily, hours, outages,
                                                          cuts, photos, result['flowCeiling'], fine_legs,
                                                          min(document['dials'],key=lambda d:d['value_per_revolution']) if document else None, flow)
            if flow and getattr(self.ledger,'store',None):
                from chart_gap_rates import estimated_rates
                from chart_rate_photos import comparison_allowance
                from reading_format import validate
                allowance=comparison_allowance(document,validate(document)[1],policy)
                with self.ledger.lock,self.ledger.store.connect() as db:
                    rate_intervals.extend(estimated_rates(db,result['registerProfile'],flow,document,zone,photo_levels,rate_intervals,
                                                          self.ledger.rate_photos,allowance,head['event_id']))
            result['registerProfile']['rateIntervals'] = rate_intervals
            key = self.profile_key(zone_name,usage,document,policy)
            if key and not missing and result['registerProfile']['points']:
                with self.profile_lock:
                    if self.last_profile is None or self.last_profile[1]['end']<=stamp:
                        self.last_profile = key,result
        return result


class BackgroundCharts:
    """Prepare one shared chart when a published meter reading closes a ten-minute interval."""
    CACHE_VERSION = 12
    def __init__(self, hours, mqtt, reading_format, path):
        self.hours = hours
        self.mqtt = mqtt
        self.reading_format = reading_format
        self.path = path
        self.published = Event()
        self.stop = hours.stopping
        self.completed = None
        self.retry_after = 0
        self.attempted = None

    def request_stop(self):
        self.stop.set()
        self.published.set()

    def load(self):
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(2*1024*1024 + 1)
            if len(raw) > 2*1024*1024:
                return
            checksum, payload = raw.split(b'\n', 1)
            if hashlib.sha256(payload).hexdigest().encode() != checksum:
                return
            version, meter, daily, key, data = json.loads(payload)
            if (version, meter, daily) != (self.CACHE_VERSION, self.hours.meter, self.hours.daily):
                return
            if not key or not data['registerProfile']['points'] or data['missing']:
                return
            with self.hours.profile_lock:
                if self.hours.last_profile is None:
                    self.hours.last_profile = key, data
        except (OSError, KeyError, ValueError, TypeError):
            return

    def prepare(self):
        mqtt = self.mqtt.status()
        usage = mqtt.get('usage') or {}
        daily = usage.get('daily_nominal') or {}
        zone = daily.get('timezone') or mqtt.get('overview_timezone')
        head = chart_head(usage)
        if not head.get('measured_at') or not zone:
            return
        doc = self.reading_format.status()['format']
        policy = self.mqtt.daily.evidence_policy or {}
        key = self.hours.profile_key(zone, usage, doc, policy)
        if not key:
            return
        source = datetime.fromisoformat(head['measured_at'])
        if source.tzinfo is None:
            return
        stamp = millis(source)
        local = source.astimezone(ZoneInfo(zone))
        tick = millis(local.replace(minute=local.minute//10*10, second=0, microsecond=0))
        slot = key, tick
        if self.completed == slot or self.attempted == slot and clock.monotonic() < self.retry_after:
            return
        self.attempted = slot
        self.retry_after = clock.monotonic() + 60
        data = self.hours.prepared(stamp, zone, usage, doc, policy)
        if self.stop.is_set() or data['missing'] or not data.get('registerProfile',{}).get('points'):
            return
        from setup_store import Setup
        payload = json.dumps([self.CACHE_VERSION,self.hours.meter,self.hours.daily,key,data],
                             allow_nan=False,separators=(',',':')).encode()
        Setup._atomic(self.path, hashlib.sha256(payload).hexdigest().encode()+b'\n'+payload)
        if data['registerProfile']['points'][-1][0] >= tick:
            self.completed = slot
            self.retry_after = 0

    def run(self):
        self.load()
        while not self.stop.is_set():
            self.published.wait()
            self.published.clear()
            if self.stop.is_set():
                return
            try:
                self.prepare()
            except Exception as exc:
                # A chart failure must never change capture or MQTT publication.
                if not self.stop.is_set():
                    logging.getLogger(__name__).warning('Background chart preparation failed (%s)', type(exc).__name__)


def ledger_breaks(store,start,end):
    with store.connect() as db:
        rows=db.execute("""SELECT f.captured_at FROM capture_events e JOIN frames f USING(camera,frame_id)
            WHERE e.event_id IN (SELECT after_event_id+1 FROM capture_failure_boundaries
                                 UNION SELECT first_event FROM consumption_segment_links)
            AND julianday(f.captured_at) BETWEEN julianday(?) AND julianday(?)""",
            (start.isoformat(),end.isoformat()))
        return [millis(datetime.fromisoformat(t)) for t, in rows]
