"""Recover nominal daily movement from capture-bound observations of the finest dial."""
from datetime import datetime, time
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN, ROUND_HALF_UP
from math import ulp
from zoneinfo import ZoneInfo

from daily_constraints import WorkLimit, bands, number
from daily_records import daily_records
from meter_history import millis

PAGE = 256


def phase_band(row, document, dial):
    """Enclose every absolute alternative on one turn of the observed fine dial."""
    support = row.get('observation_support') or {}
    flags = support.get('document_observed') or []
    if (support.get('source_sha256') != row['source_sha256']
            or support.get('pipeline_id') != document['pipeline_id']
            or len(flags) != len(document['dials']) or flags[dial['index']] is not True):
        return None
    try:
        ranges = bands(row, number(document['dials'][0]['value_per_revolution']))
    except (WorkLimit, ValueError, ArithmeticError, TypeError, KeyError):
        return None
    if not ranges:
        return None
    turn = number(dial['value_per_revolution'])
    reference = ranges[0][0] % turn
    lower = upper = reference
    for left, right in ranges:
        turns = ((left - reference) / turn).to_integral_value(rounding=ROUND_HALF_EVEN)
        lower = min(lower, left - turns * turn)
        upper = max(upper, right - turns * turn)
    # Some stored band endpoints are binary64 values at full register magnitude.
    # Allow two endpoint ULPs in the width check. Always retain the full enclosure.
    slack = 2 * number(ulp(float(ranges[-1][1])))
    width = 2 * number(dial['position_error']) * turn / 10
    if upper - lower <= width + slack and upper - lower < turn / 2:
        return lower, upper


def step(previous, interval, turn, limit):
    """Earliest nondecreasing phase compatible with both observations and the rate cap."""
    low, high = interval
    old_low, old_high = map(number, previous)
    turns = ((old_low - high) / turn).to_integral_value(rounding=ROUND_CEILING)
    low = max(old_low, low + turns * turn)
    high = min(old_high + limit, high + turns * turn)
    if low <= high:
        return low, high


def recover(prior, obs, full, today, zone, store, snapshot):
    """Backfill the uncredited flat tail of a dev98 checkpoint once, in pages."""
    track = (prior or {}).get('movement') or {}
    state = (prior or {}).get('state') or {}
    scratch = (prior or {}).get('phase_replay')
    if (state.get('day'), state.get('timezone')) != (today.isoformat(), zone):
        scratch = None
    elif (scratch is None and track.get('dial_from') and not track.get('phase_version')
            and state.get('event_id') and obs['event_id'] >= state['event_id']):
        points = track.get('points') or []
        idx = len(points)-1
        while idx > 0 and number(points[idx-1][1]) == number(state['value_ft3']):
            idx -= 1
        if (idx < len(points)-1 and points[-1][2] == state['event_id'] and
                number(points[-1][1]) == number(state['value_ft3'])):
            point = points[idx]
            with store.connect() as db:
                def at(eid):
                    return next(daily_records(db,eid,obs['event_id'],obs['segment_id'],stop_after=eid),None)
                anchor, last = at(point[2]), at(state['event_id'])
            if (anchor and last and last['source_sha256'] == state['source_sha256']
                    and last['through_captured_at'] == state['measured_at']
                    and anchor['format_id'] == last['format_id'] == track['format']
                    and millis(datetime.fromisoformat(anchor['through_captured_at'])) == point[0]):
                history = dict(track, points=points[:idx+1], group=point[3], dial_cursor=point[2],
                               dial_gaps=[g for g in track.get('dial_gaps',[]) if g[1]<=point[0]],
                               phase_version=2)
                history.pop('dial_motion',None)
                scratch = dict(movement=history, anchor=None,
                               state=dict(state, event_id=point[2], measured_at=anchor['through_captured_at'],
                                          source_sha256=anchor['source_sha256']))
    if scratch is None:
        return _recover(prior, obs, full, today, zone, store, snapshot)
    result = _recover(scratch, obs, full, today, zone, store, snapshot)
    if result is None:
        return prior
    new = result['state']
    if (new.get('event_id',0) < state['event_id'] or number(new['value_ft3']) < number(state['value_ft3'])):
        return dict(prior, phase_replay=result)
    return result


def _recover(prior, obs, full, today, zone, store, snapshot):
    from nominal_daily import MOVEMENT, _with_bounds, append_point, opening

    src = (snapshot['consumption'].get('event_observation') or {})
    document = snapshot['format']
    dial = min(document['dials'], key=lambda d: d['value_per_revolution'])
    turn = number(dial['value_per_revolution'])
    rate = number(document['maximum_rate_per_second'])
    tz = ZoneInfo(zone)
    end = obs['event_id']
    state = (prior or {}).get('state') or {}
    if (any(src.get(k) != obs[k] for k in ('event_id', 'source_sha256', 'format_id', 'captured_at'))
            or datetime.fromisoformat(obs['captured_at']).astimezone(tz).date() != today
            or state.get('day', '') > today.isoformat()):
        return None
    same_day = (state.get('day'), state.get('timezone')) == (today.isoformat(), zone)
    through = (full or {}).get('through') or {}
    if through and through.get('camera') != src.get('camera'):
        full = None
    track = dict((prior or {}).get('movement') or {}) if same_day else {}
    last = state.get('event_id') if same_day else None
    if last and (end < last or (track and track['format'] != obs['format_id'])):
        return None
    if last == end:
        if track and (state['measured_at'], state['source_sha256']) == (obs['captured_at'], obs['source_sha256']):
            return _with_bounds(prior, full)
        return None
    # With no same-day checkpoint, start at the verified post-midnight bracket
    # when available. Until the first observation, consumption is unknown.
    bracket = (full or {}).get('after') or {}
    has_opening = ((full or {}).get('day') == today.isoformat() and
                   (full or {}).get('timezone') == zone and bracket.get('camera') == src.get('camera')
                   and bracket.get('format_id') == obs['format_id'])
    pending = track.get('dial_opening')
    start = end
    if has_opening:
        start = bracket['event_id']
    if pending:
        start = pending[0]
    if last:
        start = last
    if not 0 < start <= end:
        return None
    if not track:
        track = dict(format=obs['format_id'], midnight=millis(datetime.combine(today, time.min, tz)),
                     first_meter=None, group=0, partial=True, points=[])
    if not same_day:
        state = opening(today.isoformat(), zone)
    cursor = track.get('dial_cursor', start)
    if end < cursor:
        return None
    stop = min(end, cursor + PAGE)
    with store.connect() as db:
        # Pin the live endpoint and the last displayed amount to the actual ledger lineage.
        def record(event):
            return next(daily_records(db, event, end, obs['segment_id'], stop_after=event), None)
        target = record(end)
        if target is None or target['event_observation'] != src:
            return None
        anchor = record(start)
        if (not anchor or anchor['event_observation']['camera'] != src['camera']
                or anchor['format_id'] != obs['format_id']
                or (pending and not last and pending != [start, anchor['source_sha256'], anchor['through_captured_at']])
                or (last and (anchor['source_sha256'], anchor['through_captured_at']) !=
                    (state['source_sha256'], state['measured_at']))
                or (not last and not pending and has_opening and any(anchor['event_observation'].get(k) != bracket.get(k)
                    for k in ('event_id','captured_at','source_sha256')))):
            return None
        from dial_travel import phases
        last_phase = track.get('dial_motion') or {}
        begin = max(cursor - PAGE, min(cursor, last_phase.get('event', cursor)))
        raw = phases(db, begin, stop, document, src)
        failures = {a for a, in db.execute('SELECT DISTINCT after_event_id FROM capture_failure_boundaries '
                                          'WHERE after_event_id>=? AND after_event_id<?', (begin, stop))}
        rows = list(daily_records(db, cursor, end, obs['segment_id'], stop_after=stop))
    previous = track.get('dial_motion')
    gaps = list(track.get('dial_gaps', []))
    for row in rows:
        source = row['event_observation']
        eid = row['event_id']
        stamp = datetime.fromisoformat(source['captured_at'])
        if (source['camera'] != src['camera'] or row['format_id'] != track['format']
                or stamp.astimezone(tz).date() != today):
            return None
        if previous and eid <= previous['event']:
            continue
        observed = raw.get(eid)
        if observed and observed[0] != source:
            return None
        phase = observed[1] if observed else phase_band(row, document, dial)
        if phase is None:
            continue
        identity = [row['segment_id'], source['clock_id'], source['context_id']]
        lifted = None
        center = None
        if previous:
            elapsed = number((stamp - datetime.fromisoformat(previous['stamp'])).total_seconds())
            if elapsed <= 0:
                continue
            if (observed and identity == previous['identity'] and previous['event'] in raw
                    and eid - previous['event'] <= PAGE):
                # Accounting may reject a whole-turn assignment while the reader
                # still observed the fine pointer. Require every intervening frame.
                lifted = tuple(map(number, previous['interval']))
                center = number(previous.get('center', sum(lifted) / 2))
                old_source = raw[previous['event']][0]
                for link in range(previous['event'] + 1, eid + 1):
                    sample = raw.get(link)
                    if not sample or link-1 in failures:
                        lifted = None
                        break
                    new_source, interval = sample
                    seconds = number((datetime.fromisoformat(new_source['captured_at']) -
                                      datetime.fromisoformat(old_source['captured_at'])).total_seconds())
                    ticks = new_source['monotonic_us'] - old_source['monotonic_us']
                    if (new_source['context_id'] != source['context_id'] or
                            old_source['context_id'] != source['context_id'] or not 0 < seconds < 660 or ticks <= 0):
                        lifted = None
                        break
                    lifted = step(lifted, interval, turn, min(seconds, Decimal(ticks)/1000000)*rate)
                    if lifted is None:
                        break
                    if center < lifted[0]:
                        center = sum(lifted) / 2
                    old_source = new_source
            elif (identity == previous['identity'] and eid == previous['event'] + 1
                    and eid - 1 not in failures and elapsed < 11 * 60):
                ticks = source['monotonic_us'] - previous['tick']
                if ticks <= 0:
                    continue
                lifted = step(previous['interval'], phase, turn, min(elapsed, Decimal(ticks)/1000000)*rate)
        # A discontinuity starts a fresh interval at the same amount. No delta is assigned to it.
        if lifted is None:
            if previous or (last and eid != last):
                track['partial'] = True
                track['group'] += 1
                left = millis(datetime.fromisoformat(state['measured_at']))
                if gaps and left <= gaps[-1][1]:
                    gaps[-1] = [gaps[-1][0], millis(stamp)]
                else:
                    gaps.append([left, millis(stamp)])
            base = number(previous['amount'] if previous else state['value_ft3'])
            low, high = phase
            center = (low+high)/2 if observed else None
            origin = center if observed else high
        else:
            low, high = lifted
            base, origin = number(previous['base']), number(previous['origin'])
        phase_value = low if center is None else center
        amount = max(number(previous['amount']) if previous else base,
                     base + max(Decimal(0), phase_value - origin))
        if previous is None:
            track.setdefault('dial_from', [eid, millis(stamp)])
        previous = dict(event=eid, stamp=source['captured_at'], tick=source['monotonic_us'],
                        identity=identity, interval=[str(low),str(high)], base=str(base),
                        origin=str(origin), amount=str(amount))
        if center is not None:
            previous['center'] = str(center)
        value = str(amount.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
        state = dict(state, method=MOVEMENT, assumption='Starting estimate plus supported fine-dial movement. Unknown gaps and optional turns add no usage.',
                     value_ft3=value, event_id=eid, source_sha256=source['source_sha256'],
                     measured_at=source['captured_at'], partial_coverage=track['partial'],
                     status='partial_coverage' if track['partial'] else 'meter_movement')
        append_point(track, [millis(stamp), float(value), eid, track['group']])
    track.update(dial_motion=previous, dial_cursor=stop, dial_gaps=gaps, phase_version=2)
    if not previous and not last:
        track['dial_opening'] = [start, anchor['source_sha256'], anchor['through_captured_at']]
    else:
        track.pop('dial_opening', None)
    if state.get('event_id') and (state['event_id'] < stop):
        state = dict(state, status='held_at_last_reading')
    return _with_bounds(dict(state=state, anchor=None, movement=track), full)
