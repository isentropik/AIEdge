"""Read the recorder's published daily estimates without touching capture or accounting."""
from datetime import datetime, time as day_time, timedelta, timezone
import http.client
import json
import math
import os
import re
import sqlite3
from meter_history import rebuild
from threading import Lock, Thread
from time import monotonic
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo


DEFAULT_ENTITY = 'sensor.aiedge_gas_used_today'
MAX_BYTES = 16 * 1024 * 1024


def source_key(daily):
    return (daily['day'], daily['timezone'], daily['through']['camera'], daily['through']['format_id'],
            daily['before']['source_sha256'], daily['after']['source_sha256'],
            daily['before']['event_id'], daily['before']['captured_at'],
            daily['after']['event_id'], daily['after']['captured_at'])


def recorder(entity, start, end):
    if not re.fullmatch(r'sensor\.[a-z0-9_]+', entity):
        raise ValueError('invalid_history_entity')
    query = urlencode(dict(filter_entity_id=entity, end_time=end.isoformat(), significant_changes_only='0', skip_initial_state='1'))
    route = '/core/api/history/period/' + quote(start.isoformat(), safe='') + '?' + query
    conn = http.client.HTTPConnection('supervisor', timeout=12)
    try:
        conn.request('GET', route, headers={'Authorization':'Bearer ' + os.environ['SUPERVISOR_TOKEN']})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError('history_unavailable')
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('history_response_too_large')
        return json.loads(data)
    finally:
        conn.close()


def series(history, entity, daily, anchor=None):
    day, zone, *_ = identity = source_key(daily)
    local = ZoneInfo(zone)
    midnight = datetime.combine(datetime.fromisoformat(day).date(), day_time.min, local)
    limit = datetime.fromisoformat(daily['through']['captured_at'])
    groups = []
    anchor_position = None
    previous = None
    last_captured_at = None
    broken = True
    if not isinstance(history, list) or len(history) > 1 or (history and not isinstance(history[0], list)):
        raise ValueError('unexpected_history')
    for row in history[0] if history else ():
        try:
            a = row['attributes']
            if (row['entity_id'] != entity or row['state'] in ('unknown','unavailable') or row['state'] != a['label'] or source_key(a) != identity or
                    a.get('status') == 'stale' or a['nominal_estimate']['method'] != 'range_midpoint_v1'):
                broken = True
                continue
            src = a['through']
            t = datetime.fromisoformat(src['captured_at'])
            if t.utcoffset() is None or t.astimezone(local).date() != midnight.date():
                broken = True
                continue
            if t > limit:
                continue
            stamp = int(t.replace(microsecond=0).timestamp())*1000 + t.microsecond//1000
            event, digest = src['event_id'], src['source_sha256']
            mid, low, high = map(float, (a['nominal_estimate']['value_ft3'], a['lower'], a['upper']))
            if (type(event) != int or event <= 0 or not re.fullmatch('[0-9a-f]{64}',digest) or
                    not all(map(math.isfinite,(mid,low,high))) or not 0 <= low <= mid <= high):
                raise ValueError('invalid_point')
            # Segment and clock changes delimit lines even if the cumulative estimate remains valid.
            context = (a['segment_id'],src['clock_id'],src['context_id'])
            point = [stamp,mid,low,high,event]
            if previous:
                old, old_digest, old_context = previous
                if point == old and digest == old_digest and context == old_context:
                    continue
                if event <= old[4] or stamp <= old[0]:
                    broken = True
                    continue
                broken |= context != old_context or stamp-old[0] >= 660_000
            if broken:
                groups.append([])
            groups[-1].append(point)
            if anchor is not None and (point,digest,src['captured_at']) == anchor:
                anchor_position = len(groups)-1,len(groups[-1])-1
            previous = point,digest,context
            last_captured_at = src['captured_at']
            broken = False
        except (KeyError, TypeError, ValueError, OverflowError):
            broken = True
    result = {'day':day,'zone':zone,'identity':list(identity),'midnight':round(midnight.timestamp()*1000),
              'groups':groups,'last_digest':previous[1] if previous else None,'last_captured_at':last_captured_at}
    if anchor is not None:
        result['anchor_position'] = anchor_position
    return result


def load_day(fetch, entity, daily, cached):
    zone = ZoneInfo(daily['timezone'])
    start = datetime.combine(datetime.fromisoformat(daily['day']).date(), day_time.min, zone)
    end = min(datetime.now(timezone.utc), start + timedelta(days=1, minutes=12))
    if cached and cached.get('groups'):
        anchor = cached['groups'][-1][-1]
        overlap = datetime.fromtimestamp(anchor[0]/1000, timezone.utc) - timedelta(minutes=12)
        if overlap > start:
            tail = series(fetch(entity,overlap,end), entity, daily, (anchor,cached['last_digest'],cached['last_captured_at']))
            # Extend the cached day only where both projections contain the same meter evidence.
            position = tail.pop('anchor_position')
            if position is not None:
                group,index = position
                suffix = tail['groups'][group][index+1:]
                tail['groups'] = [*cached['groups'][:-1],cached['groups'][-1]+suffix,*tail['groups'][group+1:]]
                return tail
    return series(fetch(entity,start,end),entity,daily)


class GasTrend:
    def __init__(self, entity=DEFAULT_ENTITY, fetch=recorder, *, meter_entity=None, lookup=None):
        self.meter_entity, self.lookup = meter_entity, lookup
        self.prefix_key = self.prefix = None
        self.prefix_busy = False
        self.prefix_retry = 0
        self.entity, self.fetch = entity, fetch
        self.lock = Lock()
        self.key = self.result = None
        self.busy = False
        self.next_read = 0

    def snapshot(self, daily, track=None):
        if not daily:
            return {'status':'no_source'}
        try:
            key = source_key(daily)
        except (KeyError, TypeError):
            return {'status':'no_source'}
        with self.lock:
            if self.key != key:
                self.key, self.result, self.next_read = key, None, 0
            if not self.busy and monotonic() >= self.next_read:
                self.busy = True
                Thread(target=self._read, args=(key,daily,self.result), daemon=True).start()
            result = dict(self.result, refreshing=self.busy) if self.result else {'status':'loading'}
            if self.lookup and track and track.get('points') and track.get('first_meter') and track.get('format'):
                prefix_key = (key, track['midnight'], tuple(track['points'][0]), track['first_meter'], track['format'])
                if self.prefix_key != prefix_key:
                    self.prefix_key, self.prefix, self.prefix_retry = prefix_key, None, 0
                if self.prefix is None and not self.prefix_busy and monotonic() >= self.prefix_retry:
                    self.prefix_busy = True
                    Thread(target=self._backfill,args=(prefix_key,daily,track),daemon=True).start()
                if self.prefix is not None:
                    if not result.get('identity'):
                        result.update(day=key[0],zone=key[1],identity=list(key),midnight=track['midnight'],groups=[])
                    result['meter_prefix'] = self.prefix
                if self.prefix_busy:
                    result['refreshing'] = True
            else:
                self.prefix_key = self.prefix = None
            return result

    def _backfill(self,key,daily,track):
        prefix = None
        try:
            prefix = rebuild(self.fetch,self.lookup,self.meter_entity,daily,track)
        except (OSError,http.client.HTTPException,ValueError,TypeError,KeyError,ArithmeticError,sqlite3.Error):
            pass
        finally:
            with self.lock:
                if key == self.prefix_key:
                    self.prefix = prefix
                    self.prefix_retry = monotonic()+900
                self.prefix_busy = False

    def _read(self,key,daily,cached):
        result = None
        try:
            result = load_day(self.fetch,self.entity,daily,cached)
        except (OSError, http.client.HTTPException, ValueError, TypeError, KeyError, OverflowError):
            pass
        finally:
            with self.lock:
                if self.key == key:
                    if result is not None:
                        self.result = dict(result,status='ready')
                    else:
                        self.result = dict(self.result or {},status='unavailable')
                    self.next_read = monotonic() + (120 if result is not None else 30)
                self.busy = False
