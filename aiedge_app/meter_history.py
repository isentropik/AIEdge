"""Rebuild the pre-checkpoint chart from retained recorder and capture identities."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from zoneinfo import ZoneInfo


def millis(t):
    return int(t.replace(microsecond=0).timestamp()) * 1000 + t.microsecond // 1000


def frame_ids(store, camera, ids):
    found = {}
    with store.connect() as db:
        for i in range(0, len(ids), 256):
            page = ids[i:i+256]
            marks = ','.join('?' for _ in page)
            rows = db.execute(f"""SELECT e.event_id,f.captured_at,f.sha256 FROM capture_events e
                               JOIN frames f USING(camera,frame_id)
                               WHERE e.camera=? AND e.event_id IN ({marks})""", (camera, *page))
            found.update((event,(stamp,digest)) for event,stamp,digest in rows)
    return found


def rebuild(fetch, lookup, entity, daily, track):
    """Only differences between qualified absolute readings are historical nominal movement."""
    midnight = datetime.fromtimestamp(track['midnight']/1000, timezone.utc)
    local = ZoneInfo(daily['timezone'])
    calendar_day = date.fromisoformat(daily['day'])
    if midnight != datetime.combine(calendar_day,time.min,local):
        return None
    stamp, base, event, _ = track['points'][0]
    cutoff = datetime.fromtimestamp(stamp/1000, timezone.utc)
    before, after = daily['before'], daily['after']
    if not (datetime.fromisoformat(before['captured_at']) < midnight <= datetime.fromisoformat(after['captured_at'])
            and 0 < before['event_id'] < after['event_id'] <= event
            and cutoff.astimezone(local).date() == calendar_day):
        return None
    if any(s['camera'] != daily['through']['camera'] or s['format_id'] != track['format']
           for s in (before, after, daily['through'])):
        return None
    bracket = lookup(daily['through']['camera'],[before['event_id'],after['event_id']])
    if any(bracket.get(s['event_id']) != (s['captured_at'],s['source_sha256']) for s in (before,after)):
        return None
    # A checkpoint already at the opening needs no earlier line.
    if after['event_id'] == event:
        return dict(points=[], anchor=[stamp, base, event], offset=0)
    cur = min(midnight, datetime.fromisoformat(before['captured_at'])) - timedelta(minutes=3)
    # Recorder writes can follow an actual capture by several seconds.
    end = cutoff + timedelta(minutes=3)
    prior = None
    first = anchor = pre = None
    points = []
    group = 0
    broken = True
    previous_bucket = None
    while cur < end:
        to = min(end,cur+timedelta(hours=1))
        data = fetch(entity,cur,to)
        if not isinstance(data,list) or len(data)>1 or (data and not isinstance(data[0],list)):
            raise ValueError('unexpected register history')
        rows = data[0] if data else []
        ids = sorted({r['attributes']['event_id'] for r in rows if isinstance(r,dict)
                      and isinstance(r.get('attributes'),dict) and type(r['attributes'].get('event_id')) is int})
        frames = lookup(daily['through']['camera'],ids)
        for row in rows:
            try:
                a = row['attributes']
                if (row['entity_id'] != entity or row['state'] in ('unknown','unavailable') or
                        a['method'] != 'minimum_supported_forward_movement'):
                    raise ValueError()
                eid, measured, digest = a['event_id'], a['measured_at'], a['source_sha256']
                if type(eid) is not int or eid <= 0:
                    raise ValueError()
                if eid > event:
                    continue
                value = Decimal(a['value_ft3'])
                t = datetime.fromisoformat(measured)
                if (t.utcoffset() is None or not value.is_finite() or value < 0
                        or not re.fullmatch('[0-9a-f]{64}',digest) or frames.get(eid) != (measured,digest)):
                    raise ValueError()
                identity = (eid,t,digest,value)
                if prior == identity:
                    continue
                if a['status'] not in ('nominal','partial_coverage') or Decimal(row['state']) != value:
                    raise ValueError()
                if prior and (eid<=prior[0] or t<=prior[1] or value<prior[3]):
                    raise ValueError()
                if t < midnight:
                    pre = identity
                elif eid == after['event_id']:
                    if ((measured,digest) != (after['captured_at'],after['source_sha256']) or not pre or pre[3] != value
                            or pre[0] > before['event_id'] or midnight-pre[1] > timedelta(minutes=3)):
                        return None
                    first = value
                if first is not None:
                    if (broken or a['status']=='partial_coverage'
                            or (prior and (eid!=prior[0]+1 or t-prior[1]>=timedelta(minutes=11)))):
                        group += 1
                    ms = millis(t)
                    amount = float((value-first).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
                    if eid == event:
                        if ms != stamp or value != Decimal(track['first_meter']):
                            return None
                        anchor = [ms,base,event]
                        offset = float(Decimal(str(base))-Decimal(str(amount)))
                    else:
                        point = [ms,amount,eid,'h'+str(group)]
                        bucket = ((ms-track['midnight'])//3600000,group)
                        # Keep both ends of each supported run and the last sample of each hour.
                        if bucket==previous_bucket and len(points)>1 and points[-2][3]==point[3] and (points[-2][0]-track['midnight'])//3600000==bucket[0]:
                            points[-1] = point
                        else:
                            points.append(point)
                        previous_bucket = bucket
                prior = identity
                broken = False
            except (KeyError,TypeError,ValueError,InvalidOperation,OverflowError):
                broken = True
        cur = to
    if anchor is None or not points:
        return None
    return dict(points=points,anchor=anchor,offset=offset)
