"""Partial daily usage from immutable fine-dial observations, independent of the register."""
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_FLOOR
from zoneinfo import ZoneInfo

from capture_clock import interval as capture_interval
from daily_constraints import number
from dial_travel import phases
from meter_history import millis
from nominal_daily import MOVEMENT, _with_bounds, append_point, opening
from nominal_motion import PAGE, step
from reading_format import validate


def endpoint(snapshot, obs, active, now, max_age):
    """Admit only the app's coherent publication frame and current meter format."""
    c = snapshot.get('consumption') or {}
    src = c.get('event_observation') or {}
    frame = snapshot.get('latest') or {}
    doc = snapshot.get('format') or {}
    if doc.get('unit') != 'ft3' or not doc.get('maximum_rate_per_second'):
        return None
    _, revision = validate(doc)
    if (type(src.get('event_id')) is not int or src['event_id'] < 1 or not src.get('clock_id')
            or type(src.get('monotonic_us')) is not int or src['monotonic_us'] < 0
            or src.get('format_id') != revision or c.get('format_id') != revision
            or not c.get('segment_id') or snapshot.get('_publication_segment_id') != c['segment_id']
            or src.get('context_id') != c.get('observation_context')
            or src.get('event_id') != c.get('event_id') or src.get('event_id') != snapshot.get('_timing_event_id')
            or not src.get('source_sha256') or src['source_sha256'] != frame.get('sha256')
            or src['source_sha256'] != c.get('source_sha256') or src.get('captured_at') != frame.get('captured_at')):
        return None
    if obs is None:
        reading = snapshot.get('_raw_meter_reading') or {}
        conflict = reading.get('consistency') or {}
        indices = conflict.get('dial_indices') or []
        coarse = {d['index'] for d in doc['dials'][:-1]}
        if (c.get('observation_accepted') is not False or c.get('reason') != 'consumption_positions_contradict_bounds'
                or reading.get('state') != 'inconsistent' or reading.get('reason') != 'dial_bounds_disagree'
                or reading.get('format_id') != revision or reading.get('source_sha256') != src['source_sha256']
                or conflict.get('state') != 'inconsistent' or len(indices) < 2 or not set(indices) <= coarse):
            return None
    elif not active:
        return None
    try:
        stamp = datetime.fromisoformat(src['captured_at'])
    except (KeyError, TypeError, ValueError):
        return None
    if stamp.tzinfo is None or not timedelta(0) <= now - stamp <= timedelta(seconds=max_age):
        return None
    return src


def replay(prior, full, today, zone, store, document, src):
    tz = ZoneInfo(zone)
    midnight = datetime.combine(today, time.min, tz)
    current = (prior or {}).get('state') or {}
    if (datetime.fromisoformat(src['captured_at']).astimezone(tz).date() != today
            or current.get('timezone') == zone and current.get('day', '') > today.isoformat()):
        return None
    same_day = (current.get('day'), current.get('timezone')) == (today.isoformat(), zone)
    state = dict(current) if same_day else opening(today.isoformat(), zone)
    history = ((prior or {}).get('movement') or {}) if same_day else {}
    track = dict(history)
    fmt = src['format_id']
    old_identity = (((prior or {}).get('anchor') or {}).get('identity') or []) if same_day else []
    if (track.get('format', fmt) != fmt or track.get('optical_camera', src['camera']) != src['camera']
            or old_identity and old_identity[0] != fmt):
        return None
    if not track:
        track.update(midnight=millis(midnight), format=fmt, points=[], group=0, first_meter=None)
    track.update(partial=True, optical_camera=src['camera'])
    gaps = list(track.get('dial_gaps', []))
    previous = track.get('optical_last')
    end = src['event_id']
    last = state.get('event_id')
    if last and (end < last or end == last and (src['source_sha256'], src['captured_at']) !=
                 (state['source_sha256'], state['measured_at'])):
        return None
    turn = number(document['dials'][-1]['value_per_revolution'])
    rate = number(document['maximum_rate_per_second'])
    with store.connect() as db:
        # Bind the requested head before emitting any earlier page.
        head = phases(db, end, end, document, src)
        if end not in head or head[end][0] != src:
            return None
        cursor = track.get('optical_cursor')
        if cursor is None and last:
            row = db.execute('SELECT e.camera,f.captured_at,f.sha256 FROM capture_events e '
                             'JOIN frames f USING(camera,frame_id) WHERE e.event_id=?', (last,)).fetchone()
            if not row or tuple(row) != (src['camera'], state['measured_at'], state['source_sha256']):
                return None
            cursor = last - 1
        if cursor is None:
            # Find the opening once. Scan backwards on the camera/event index only as far as the prior day.
            row = db.execute('SELECT e.event_id FROM capture_events e JOIN frames f USING(camera,frame_id) '
                             'WHERE e.camera=? AND e.event_id<=? AND julianday(f.captured_at)<julianday(?) '
                             'ORDER BY e.event_id DESC LIMIT 1', (src['camera'], end, midnight.isoformat())).fetchone()
            cursor = row[0] if row else 0
            if row is None:
                cursor = db.execute('SELECT min(event_id) FROM capture_events WHERE camera=?',
                                    (src['camera'],)).fetchone()[0] - 1
        if cursor > end:
            return None
        stop = min(end, cursor + PAGE)
        samples = head if cursor+1 == stop == end else phases(db, cursor+1, stop, document, src, same_clock=False)
        boundaries = {row[0]+1 for row in db.execute('SELECT after_event_id FROM capture_failure_boundaries '
                      'WHERE after_event_id BETWEEN ? AND ?', (cursor, stop-1))}
        boundaries.update(r[0] for r in db.execute('SELECT first_event FROM consumption_segment_links '
                          'WHERE first_event BETWEEN ? AND ?', (cursor+1, stop)))
    for event, (source, measured) in sorted(samples.items()):
        stamp = datetime.fromisoformat(source['captured_at'])
        if (stamp.tzinfo is None or stamp.astimezone(tz).date() != today
                or not source.get('clock_id') or type(source.get('monotonic_us')) is not int
                or source['monotonic_us'] < 0):
            continue
        if state.get('measured_at') and (event != state.get('event_id') and
                stamp <= datetime.fromisoformat(state['measured_at'])):
            continue
        lifted = None
        if previous:
            old = previous['source']
            if event == old['event_id']+1 and event not in boundaries and source['context_id'] == old['context_id']:
                timing = capture_interval(old, source)
                if timing['state'] == 'continuous' and timing['elapsed_seconds'] < 660:
                    limit = rate * Decimal(source['monotonic_us'] - old['monotonic_us']) / 1000000
                    band = tuple(map(number, previous['band']))
                    # A possible extra turn cannot cancel the smallest forward displacement.
                    # Keep that minimum. A backward jump that only fits by crediting
                    # most of a revolution does not independently establish a wrap.
                    lift = step(band, measured, turn, limit)
                    if lift is not None and lift[0] - band[1] < turn / 2:
                        lifted = lift
        if lifted is None:
            if state.get('event_id') and event != state['event_id']:
                track['group'] += 1
                left = millis(datetime.fromisoformat(state['measured_at']))
                if gaps and gaps[-1][1] == left:
                    gaps[-1] = [gaps[-1][0], millis(stamp)]
                else:
                    gaps.append([left, millis(stamp)])
            base = number(previous['amount'] if previous else state['value_ft3'])
            lifted = measured
            origin = measured[1]
        else:
            base, origin = number(previous['base']), number(previous['origin'])
        # Credit only displacement beyond the starting and ending position tolerances.
        amount = base + max(Decimal(0), lifted[0] - origin)
        previous = dict(source=source, band=[str(v) for v in lifted], base=str(base), origin=str(origin), amount=str(amount))
        if 'optical_from' not in track:
            track['optical_from'] = [event, source['captured_at']]
            track.setdefault('dial_from', [event, millis(stamp)])
            if state.get('event_id') is None and millis(midnight) < millis(stamp):
                gaps.append([millis(midnight), millis(stamp)])
            if state.get('lower_ft3') is not None and not state.get('bounds_event_id') and state.get('event_id'):
                state.update(bounds_event_id=state['event_id'], bounds_measured_at=state['measured_at'],
                             bounds_source_sha256=state['source_sha256'])
        value = str(amount.quantize(Decimal('.01'), rounding=ROUND_FLOOR))
        state.update(value_ft3=value, method=MOVEMENT, partial_coverage=True, status='partial_coverage',
                     assumption='Counts verified fine-dial movement during covered intervals. Usage across gaps is unknown.',
                     coverage_started_at=track['optical_from'][1], event_id=event, measured_at=source['captured_at'],
                     source_sha256=source['source_sha256'])
        state.pop('conflict_event_id', None)
        append_point(track, [millis(stamp), float(value), event, track['group']])
    track.update(optical_cursor=stop, optical_last=previous, dial_gaps=gaps)
    if state.get('event_id') and state['event_id'] < stop:
        state['status'] = 'held_at_last_reading'
    result = dict(state=state, movement=track, anchor=None)
    if (full or {}).get('through', {}).get('camera') == src['camera']:
        return _with_bounds(result, full)
    return result
