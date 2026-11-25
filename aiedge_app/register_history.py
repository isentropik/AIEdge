"""Daily closing states of the absolute gas register, in cubic feet."""
from datetime import datetime, time, timedelta, timezone
from http.client import HTTPConnection
import json
import math
import os
from zoneinfo import ZoneInfo


def statistics(entity, start, end):
    request = dict(statistic_ids=[entity], start_time=start.isoformat(), end_time=end.isoformat(),
                   period='day', types=['state'], units={'volume': 'ft³'})
    conn = HTTPConnection('supervisor', timeout=12)
    try:
        conn.request('POST', '/core/api/services/recorder/get_statistics?return_response',
                     json.dumps(request), {'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + os.environ['SUPERVISOR_TOKEN']})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError('statistics_unavailable')
        body = response.read(128 * 1024 + 1)
        if len(body) > 128 * 1024:
            raise ValueError('statistics_response_too_large')
        return json.loads(body)['service_response']['statistics'].get(entity, [])
    finally:
        conn.close()


def reading(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def snapshot(entity, mqtt, days, until=None, *, fetch=None, now=None):
    usage = mqtt.get('usage') or {}
    zone_name = (usage.get('daily_nominal') or {}).get('timezone') or mqtt.get('overview_timezone')
    zone = ZoneInfo(zone_name)
    now = (now or datetime.now(timezone.utc)).astimezone(zone)
    today = now.date()
    end = min(until, today) if until else today
    start = end - timedelta(days=days - 1)
    first = datetime.combine(start, time.min, zone)
    stop = datetime.combine(end + timedelta(days=1), time.min, zone)
    by_day = {}
    for row in (fetch or statistics)(entity, first, min(now, stop)):
        at = datetime.fromisoformat(row['end'])
        if at.utcoffset() is None or at > now:
            continue
        day = (at.astimezone(zone) - timedelta(microseconds=1)).date()
        value = reading(row.get('state'))
        if start <= day <= end and day < today and value is not None:
            by_day[day] = dict(day=day.isoformat(), value=value, at=at.isoformat(), kind='close')
    # Today's Recorder bucket ends in the future. Use the timestamp on the
    # actual register publication, including a held reading's original time.
    head = usage.get('absolute_nominal') or {}
    value = reading(head.get('value_ft3'))
    if end == today and value is not None and head.get('measured_at'):
        try:
            at = datetime.fromisoformat(head['measured_at'])
        except (TypeError, ValueError):
            at = None
        if at and at.utcoffset() is not None and at <= now and at.astimezone(zone).date() == today:
            by_day[today] = dict(day=today.isoformat(), value=value, at=at.isoformat(), kind='latest')
    return dict(start=start.isoformat(), end=end.isoformat(), today=today.isoformat(), zone=zone_name,
                startAt=first.isoformat(), endAt=min(now, stop).isoformat(),
                points=[by_day[day] for day in sorted(by_day)])
