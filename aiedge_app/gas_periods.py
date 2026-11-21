"""Clock-aligned usage bounds derived from published meter intervals."""
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from math import inf
from http.client import HTTPException
import re
from threading import Lock, Thread
from time import monotonic
from zoneinfo import ZoneInfo
from gas_trend import recorder

HOUR = 3_600_000_000
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
PERIODS = ((1, 15), (6, 30), (12, 60), (24, 60))


def micros(stamp):
    time = datetime.fromisoformat(stamp)
    if time.utcoffset() is None:
        raise ValueError('unqualified_time')
    return (time - EPOCH) // timedelta(microseconds=1)


def cents(value):
    n = Decimal(str(value)) * 100
    if not n.is_finite() or n < 0 or n != n.to_integral_value():
        raise ValueError('invalid_published_bounds')
    return int(n)


def identity(src):
    return tuple(src[k] for k in ('camera', 'format_id', 'clock_id'))


def interval_rows(publication, reference):
    if (publication['unknown_gaps_preserved'] is not True or publication['timezone'] != reference['timezone']
            or publication.get('constraint_assumptions') != reference.get('constraint_assumptions')
            or publication.get('constraint_basis') != reference.get('constraint_basis')):
        return []
    through = publication['through']
    hour = publication['hour']
    quarters = publication['quarters']
    if (len(quarters) != 4 or hour['through'] != through or through['event_id'] > reference['through']['event_id']
            or (through['event_id']==reference['through']['event_id'] and through!=reference['through'])
            or hour['start'] != quarters[0]['start'] or quarters[-1]['through'] != through
            or any(a['through'] != b['start'] for a, b in zip(quarters, quarters[1:]))):
        return []
    rows = []
    for part in (hour, *quarters):
        a, b = part['start'], part['through']
        for src in (a,b):
            if (identity(src) != identity(reference['through']) or type(src['event_id']) is not int
                    or src['event_id'] <= 0 or not re.fullmatch('[a-f0-9]{64}', src['source_sha256'])):
                return []
        start, end = micros(a['captured_at']), micros(b['captured_at'])
        lo, hi = cents(part['lower']), cents(part['upper'])
        if start >= end or a['event_id'] >= b['event_id'] or lo > hi or end > micros(reference['through']['captured_at']):
            return []
        rows.append((start, end, lo, hi))
    return rows


def bounds_at(rows, start, stops):
    """Bound every prefix at once. Rows arrive in ascending end-time order."""
    ends, lower = [start], [0]
    reach, cost = [start], [0]
    first = inf
    for a,b,lo,hi in rows:
        if b <= start or a >= stops[-1]:
            continue
        first = min(first,a)
        prev = bisect_right(ends,a)-1
        packed = lower[prev]+lo if prev>=0 else 0
        if b==ends[-1]:
            lower[-1]=max(lower[-1],packed)
        else:
            ends.append(b)
            lower.append(max(lower[-1],packed))
        # Covering more time at the same or lower cost dominates a shorter chain.
        # Reach and cost both increase, so the cheapest cover needs one binary search.
        j=bisect_left(reach,max(a,start))
        if j<len(reach):
            candidate=cost[j]+hi
            if b==reach[-1] and cost[-1]<=candidate:
                continue
            while cost and cost[-1]>=candidate:
                reach.pop()
                cost.pop()
            reach.append(b)
            cost.append(candidate)
    results=[]
    for t in stops:
        j=bisect_left(reach,t)
        hi=cost[j] if j<len(reach) else None
        lo=lower[bisect_right(ends,t)-1]
        results.append((None,None) if t<=first or hi is not None and lo>hi else (lo,hi))
    return results


def limits(rows,start,end):
    return bounds_at(rows,start,[end])[0]


def window(rows, start, end, minutes, zone):
    def volume(c):
        return None if c is None else f'{c//100}.{c%100:02}'
    def span(a,b,amount):
        lo,hi = amount
        return dict(start=(EPOCH+timedelta(microseconds=a)).isoformat(),
                    end=(EPOCH+timedelta(microseconds=b)).isoformat(), lower=volume(lo), upper=volume(hi))
    # Advance in UTC minutes and select local clock boundaries. This preserves
    # repeated hours and non-hour offsets, including fractional DST changes.
    minute = HOUR//60
    cuts = [start]
    for t in range((start//minute+1)*minute, end, minute):
        if (EPOCH+timedelta(microseconds=t)).astimezone(zone).minute % minutes == 0:
            cuts.append(t)
    cuts.append(end)
    prefixes=bounds_at(rows,start,cuts[1:])
    bins=[]
    for a,b,(lo,hi) in zip(cuts,cuts[1:],prefixes):
        bins.append(dict(**span(a,b,limits(rows,a,b)),total_lower=volume(lo),total_upper=volume(hi)))
    return dict(**span(start,end,prefixes[-1]),minutes=minutes,bins=bins)


class GasPeriods:
    def __init__(self, entity, fetch=recorder):
        self.entity, self.fetch = entity, fetch
        self.lock = Lock()
        self.busy = False
        self.source = self.key = self.result = self.history_end = None
        self.intervals = set()
        self.retry = 0
        self.generation = 0
        self.last_recent = self.requested = None

    def snapshot(self, recent, daily=None):
        # A daily endpoint can identify the meter when the live recent sensor is offline.
        # Only an actual, compatible recent publication supplies interval values.
        live = bool(recent)  # MQTT publishes an empty object to mark this sensor offline.
        ref = recent if live else daily
        try:
            if not ref or ref.get('unknown_gaps_preserved') is not True:
                return {'status':'no_source'}
            if live and not interval_rows(ref,ref):
                return {'status':'no_source'}
            src = ref['through']
            token = (src['event_id'],src['captured_at'],src['source_sha256'])
            key = (identity(src),ref['timezone'],tuple(sorted((ref.get('constraint_assumptions') or {}).items())),ref.get('constraint_basis'))
            stamp = micros(token[1])
            if type(token[0]) is not int or not re.fullmatch('[0-9a-f]{64}',token[2]):
                return {'status':'no_source'}
        except (KeyError, IndexError, AttributeError, TypeError, ValueError, InvalidOperation, OverflowError):
            return {'status':'no_source'}
        with self.lock:
            if self.key != key:
                self.generation += 1
                self.last_recent=self.requested=None
                self.key, self.result, self.history_end, self.intervals, self.source, self.retry = key,None,None,set(),None,0
            cached = self.result
            old = self.requested
            if old and (old['event_id']>token[0] or micros(old['captured_at'])>stamp
                        or old['event_id']==token[0] and old!=src):
                self.generation += 1
                self.last_recent=None
                self.result = cached = None
                self.source,self.history_end,self.intervals,self.retry = None,None,set(),0
            self.requested = src
            target = (token,live)
            now = monotonic()
            if not self.busy and now>=self.retry and (target!=self.source or not cached or not cached.get('history_available')):
                self.busy=True
                Thread(target=self._read,args=(key,token,ref,self.history_end,self.intervals,live,self.last_recent,self.generation),daemon=True).start()
            if cached:
                return dict(cached,refreshing=self.busy)
            return {'status':'loading' if self.busy else 'no_history'}

    def _read(self,key,token,ref,previous,cached,live=True,last_recent=None,generation=None):
        stamp=datetime.fromisoformat(token[1])
        end=micros(token[1])
        recent=ref if live else last_recent
        cutoff=min(end,micros(recent["through"]["captured_at"]))-25*HOUR if recent else end-25*HOUR
        rows={v for v in cached if cutoff<=v[1]<=end}
        ok=False
        current=None
        try:
            start=stamp-timedelta(hours=25,minutes=5)
            if (live or recent is not None) and previous is not None and previous<=stamp:
                start=max(start,previous-timedelta(minutes=15))
            history=self.fetch(self.entity,start,datetime.now(timezone.utc))
            if not isinstance(history,list) or len(history)>1 or (history and not isinstance(history[0],list)):
                raise ValueError('unexpected_history')
            for row in history[0] if history else ():
                try:
                    a=row['attributes']
                    if row['entity_id']!=self.entity or row['state']!=a['label']:
                        continue
                    intervals=interval_rows(a,ref)
                    if not intervals:
                        continue
                    rows.update(intervals)
                    if not live and (recent is None or a['through']['event_id']>recent['through']['event_id']):
                        recent=a
                except (KeyError, IndexError, TypeError, ValueError, InvalidOperation, OverflowError):
                    continue
            ok=True
        except (OSError, ValueError, TypeError, KeyError, OverflowError, HTTPException):
            pass
        try:
            if recent:
                rows.update(interval_rows(recent,ref))
                zone=ZoneInfo(ref['timezone'])
                end=micros(recent['through']['captured_at'])
                ordered=sorted((r for r in rows if r[1]<=end),key=lambda v:(v[1],v[0]))
                periods={str(h):window(ordered,micros(recent['hour']['start']['captured_at']) if h==1 else end-h*HOUR,
                                       end,m,zone) for h,m in PERIODS}
                current=dict(status='ready',history_available=ok,through=recent['through'],timezone=ref['timezone'],
                             constraint_basis=ref.get('constraint_basis'),constraint_assumptions=ref.get('constraint_assumptions'),
                             periods=periods)
        except (KeyError, TypeError, ValueError, OverflowError, InvalidOperation):
            pass
        finally:
            with self.lock:
                if self.key==key and (generation is None or generation==self.generation):
                    if ok:
                        self.intervals,self.history_end=rows,stamp
                    if current and (ok or not self.result):
                        self.result=current
                        self.last_recent=recent
                    self.source=(token,live)
                    self.retry=monotonic()+(0 if live and current and ok else 60 if ok else 15)
                self.busy=False
