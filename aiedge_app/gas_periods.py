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


def limits(rows, start, end):
    # Disjoint contained intervals give a lower bound. A chain covering every
    # instant gives an upper bound, even when portions of that chain overlap.
    ends, lower, upper = [start], [0], [0]
    for a,b,lo,hi in rows:  # sorted by end time
        if b <= start or a >= end:
            continue
        prev = bisect_right(ends, a) - 1
        inside = lower[prev] + lo if prev >= 0 and b <= end else 0
        left = bisect_left(ends, max(start, a))
        covered = min(upper[left:], default=inf) + hi
        stop = min(end, b)
        if stop == ends[-1]:
            lower[-1] = max(lower[-1], inside)
            upper[-1] = min(upper[-1], covered)
        else:
            ends.append(stop)
            lower.append(max(lower[-1], inside))
            upper.append(covered)
    if len(ends) == 1:
        return None, None
    hi = upper[-1] if ends[-1] == end and upper[-1] < inf else None
    lo = lower[-1]
    if hi is not None and lo > hi:
        return None, None
    return lo, hi


def window(rows, start, end, minutes, zone):
    def volume(c):
        return None if c is None else f'{c//100}.{c%100:02}'
    def span(a,b):
        lo,hi = limits(rows,a,b)
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
    return dict(**span(start,end),minutes=minutes,bins=[span(a,b) for a,b in zip(cuts,cuts[1:])])


class GasPeriods:
    def __init__(self, entity, fetch=recorder):
        self.entity, self.fetch = entity, fetch
        self.lock = Lock()
        self.busy = False
        self.source = self.key = self.result = self.history_end = None
        self.intervals = set()
        self.retry = 0

    def snapshot(self, recent):
        try:
            if not recent or not interval_rows(recent,recent):
                return {'status':'no_source'}
            key = (identity(recent['through']),recent['timezone'],repr(sorted((recent.get('constraint_assumptions') or {}).items())),recent.get('constraint_basis'))
            src = recent['through']
            token = (src['event_id'],src['captured_at'],src['source_sha256'])
        except (KeyError, IndexError, AttributeError, TypeError, ValueError, InvalidOperation, OverflowError):
            return {'status':'no_source'}
        with self.lock:
            if key != self.key:
                self.key, self.history_end, self.intervals = key, None, set()
                self.source = None
            if token != self.source:
                self.source, self.result, self.retry = token, None, 0
            if not self.busy and monotonic() >= self.retry:
                self.busy = True
                Thread(target=self._read,args=(key,token,recent,self.history_end,self.intervals),daemon=True).start()
            return self.result or {'status':'loading'}

    def _read(self,key,token,recent,previous,cached):
        stamp = datetime.fromisoformat(token[1])
        end = micros(token[1])
        cutoff = end - 25*HOUR
        rows = {v for v in cached if cutoff <= v[1] <= end}
        ok = False
        try:
            start = stamp - timedelta(hours=25,minutes=5)
            if previous is not None and previous <= stamp:
                start = max(start,previous-timedelta(minutes=15))
            history = self.fetch(self.entity,start,datetime.now(timezone.utc))
            if not isinstance(history,list) or len(history)>1 or (history and not isinstance(history[0],list)):
                raise ValueError('unexpected_history')
            for row in history[0] if history else ():
                try:
                    a = row['attributes']
                    if row['entity_id']==self.entity and row['state']==a['label']:
                        rows.update(interval_rows(a,recent))
                except (KeyError, IndexError, TypeError, ValueError, InvalidOperation, OverflowError):
                    continue
            ok = True
        except (OSError, ValueError, TypeError, KeyError, OverflowError, HTTPException):
            pass
        finally:
            try:
                rows.update(interval_rows(recent,recent))
                ordered = sorted(rows,key=lambda v:(v[1],v[0]))
                zone = ZoneInfo(recent['timezone'])
                periods = {str(hours):window(ordered, micros(recent['hour']['start']['captured_at']) if hours==1 else end-hours*HOUR,
                                             end, minutes, zone) for hours,minutes in PERIODS}
                current = dict(status='ready',history_available=ok,through=recent['through'],timezone=recent['timezone'],periods=periods)
            except (KeyError, TypeError, ValueError, OverflowError, InvalidOperation):
                current = {'status':'unavailable'}
            with self.lock:
                if self.key==key:
                    if ok:
                        self.intervals,self.history_end=rows,stamp
                    if self.source==token:
                        self.result=current
                        self.retry=inf if ok else monotonic()+30
                self.busy=False
