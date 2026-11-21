"""Continuous display estimate. The ledger and its evidence bounds are read-only here."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, time
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
from zoneinfo import ZoneInfo


def opening(day, zone):
    return dict(day=day, timezone=zone, value_ft3='0.00', status='opening_balance',
                method='calendar_day_opening', assumption='Zero at midnight. Usage after midnight is unknown until observed.',
                measured_at=None, event_id=None, source_sha256=None,
                lower_ft3=None, upper_ft3=None, low_use_estimate_ft3=None)


def _segment_estimate(previous, obs, full, today, zone):
    day = today.isoformat()
    if previous and previous['state']['timezone'] == zone and previous['state']['day'] > day:
        return previous  # A backward wall-clock correction cannot start an older day.
    if not previous or (previous['state']['day'], previous['state']['timezone']) != (day, zone):
        previous = dict(state=opening(day, zone), anchor=None)
    state = previous['state']
    if obs and datetime.fromisoformat(obs['captured_at']).astimezone(ZoneInfo(zone)).date() != today:
        obs = None
    if full and full.get('status') == 'stale' and (full['day'], full['timezone']) == (day, zone):
        through = full['through']
        checked = full['checked_through']
        if (obs and obs['segment_id'] == full['checked_segment_id']
                and through['format_id'] == checked['format_id'] == obs['format_id']
                and through['event_id'] < checked['event_id'] <= obs['event_id']
                and (checked['event_id'] != obs['event_id'] or
                     (checked['source_sha256'], checked['captured_at']) == (obs['source_sha256'], obs['captured_at']))
                and (state['method'] != 'range_midpoint_v1' or state['event_id'] < through['event_id']
                     or (state['event_id'], state['source_sha256'], state['measured_at']) ==
                        (through['event_id'], through['source_sha256'], through['captured_at']))):
            nominal = full['nominal_estimate']
            held = dict(state, status='stale', value_ft3=nominal['value_ft3'], method=nominal['method'],
                        assumption=nominal['assumption'], lower_ft3=float(full['lower']), upper_ft3=float(full['upper']),
                        low_use_estimate_ft3=float(full['low_use_estimate']['value_ft3']),
                        event_id=through['event_id'], measured_at=through['captured_at'], source_sha256=through['source_sha256'],
                        conflict_event_id=full['conflict_event_id'])
            return dict(state=held, anchor=None, stale_source=[obs['format_id'], obs['segment_id']])
        return previous
    if state['status'] == 'stale' and not full:
        if (not obs or obs['event_id'] <= state['event_id']
                or previous.get('stale_source') == [obs['format_id'], obs['segment_id']]):
            return previous
        # A different measurement series cannot inherit the held total.
        state = opening(day, zone)
        previous = dict(state=state, anchor=None)
    if not obs:
        if state['event_id'] is None or state['status'] == 'stale':
            return previous
        return dict(previous, state=dict(state, status='held_at_last_reading'))
    event = obs['event_id']
    if state['event_id'] is not None:
        if event < state['event_id'] or (event == state['event_id'] and
                (obs['source_sha256'] != state['source_sha256'] or obs['captured_at'] != state['measured_at'])):
            return previous
        if event > state['event_id'] and datetime.fromisoformat(obs['captured_at']) <= datetime.fromisoformat(state['measured_at']):
            return previous

    identity = [obs['format_id'], obs['segment_id'], obs['segment_started_at']]
    through = (full or {}).get('through') or {}
    if (full and full.get('day') == day and full.get('timezone') == zone
            and full.get('segment_id') == obs['segment_id']
            and all(through.get(k) == obs[k] for k in ('event_id', 'captured_at', 'source_sha256', 'format_id'))):
        nominal = full['nominal_estimate']
        new = dict(state, value_ft3=nominal['value_ft3'], method=nominal['method'],
                   assumption=nominal['assumption'], status='daily_range', lower_ft3=float(full['lower']),
                   upper_ft3=float(full['upper']), low_use_estimate_ft3=float(full['low_use_estimate']['value_ft3']))
        anchor = dict(identity=identity, base=new['value_ft3'], upper=str(obs['maximum']))
    elif state['status'] == 'stale':
        return previous
    elif full and state['method'] == 'range_midpoint_v1' and through.get('event_id') == state['event_id']:
        # The full publisher runs less frequently than capture. Keep its actual timestamp.
        return dict(previous, state=dict(state, status='daily_range'))
    elif event == state['event_id']:
        return dict(previous, state=dict(state, status='held_at_last_reading'))
    else:
        anchor = previous['anchor']
        if not anchor or anchor['identity'] != identity:
            start = datetime.fromisoformat(obs['segment_started_at'])
            boundary = (datetime.fromisoformat(state['measured_at']) if state['measured_at']
                        else datetime.combine(today, datetime.min.time(), ZoneInfo(zone)))
            # If the segment overlaps the baseline, count only subsequent proven movement.
            anchor = dict(identity=identity, base=state['value_ft3'],
                          upper='0' if start >= boundary else str(obs['maximum']))
        growth = max(Decimal(0), Decimal(str(obs['minimum'])) - Decimal(anchor['upper']))
        amount = max(Decimal(state['value_ft3']), Decimal(anchor['base']) + growth)
        new = dict(state, value_ft3=str(amount.quantize(Decimal('.01'), rounding=ROUND_FLOOR)),
                   status='partial_coverage', method='observed_increments',
                   assumption='Adds only supported segment increases to the previous estimate. Unobserved usage is excluded.',
                   lower_ft3=None, upper_ft3=None, low_use_estimate_ft3=None)
    new.update(event_id=event, measured_at=obs['captured_at'], source_sha256=obs['source_sha256'])
    new.pop('conflict_event_id', None)
    return dict(state=new, anchor=anchor)


MOVEMENT = 'nominal_meter_movement_v1'


def _bound_to(reading, obs):
    return (reading and obs and reading.get('method') == 'minimum_supported_forward_movement'
            and reading.get('status') in ('nominal', 'partial_coverage')
            and (reading.get('event_id'), reading.get('measured_at'), reading.get('source_sha256')) ==
                (obs['event_id'], obs['captured_at'], obs['source_sha256']))


def _range_at(full, obs, day, zone):
    if not full or not obs or (full.get('day'), full.get('timezone')) != (day, zone):
        return False
    through = full.get('through') or {}
    return (full.get('status') != 'stale' and full.get('segment_id') == obs['segment_id']
            and all(through.get(k) == obs[k] for k in ('event_id', 'source_sha256', 'captured_at', 'format_id')))


def _with_bounds(record, full):
    """Attach the last independently published range with its own source."""
    state = record['state']
    through = (full or {}).get('through') or {}
    if (not through or (full.get('day'), full.get('timezone')) != (state['day'], state['timezone'])
            or through.get('format_id') != record['movement']['format']):
        return record
    bounds_id = state.get('bounds_event_id') or 0
    if through['event_id'] < bounds_id:
        return record
    if through['event_id'] == bounds_id and (
            through['source_sha256'], through['captured_at']) != (
            state['bounds_source_sha256'], state['bounds_measured_at']):
        return record
    if through['event_id'] == state['event_id'] and (
            through['source_sha256'], through['captured_at']) != (state['source_sha256'], state['measured_at']):
        return record
    return dict(record, state=dict(state, lower_ft3=float(full['lower']), upper_ft3=float(full['upper']),
                low_use_estimate_ft3=float(full['low_use_estimate']['value_ft3']),
                bounds_event_id=through['event_id'], bounds_measured_at=through['captured_at'],
                bounds_source_sha256=through['source_sha256']))


def advance(previous, obs, full, today, zone, meter=None):
    day = today.isoformat()
    state = (previous or {}).get('state') or {}
    same_day = (state.get('day'), state.get('timezone')) == (day, zone)
    if state.get('timezone') == zone and state.get('day', day) > day:
        return previous
    track = previous.get('movement') if same_day else None
    same_source = _bound_to(meter, obs)
    if same_source:
        try:
            stamp = datetime.fromisoformat(meter['measured_at'])
            absolute = Decimal(str(meter['value_ft3']))
            same_source = (stamp.tzinfo is not None and stamp.astimezone(ZoneInfo(zone)).date() == today
                           and absolute.is_finite() and absolute >= 0)
        except (KeyError, TypeError, ValueError, InvalidOperation):
            same_source = False
    if not track and not same_source:
        # Until there is a usable absolute register, retain the segment-based fallback.
        # A later range revision cannot rebase a previously published same-day estimate.
        legacy_series = (previous or {}).get('stale_source')
        different_meter = bool(obs and legacy_series and legacy_series[0] != obs['format_id'])
        if same_day and state.get('event_id') and not different_meter:
            if full and full.get('status') != 'stale':
                full = None
            if obs and legacy_series and legacy_series[1] != obs['segment_id']:
                previous = dict(previous, state=dict(state, status='held_at_last_reading'))
        result = _segment_estimate(previous, obs, full, today, zone)
        if same_day and not different_meter and (
                Decimal(result['state']['value_ft3']) < Decimal(state['value_ft3'])
                or (state.get('event_id') or 0) > (result['state'].get('event_id') or 0)
                or (state.get('event_id') and result['state']['method'] == 'range_midpoint_v1'
                    and result['state']['value_ft3'] != state['value_ft3'])):
            return previous
        return result
    if not same_source:
        return _with_bounds(dict(previous, state=dict(state, status='held_at_last_reading')), full)
    eid = meter['event_id']
    old_event = state.get('event_id') if same_day else None
    if old_event is not None:
        if eid < old_event or (eid == old_event and (meter['measured_at'], meter['source_sha256'])
                               != (state['measured_at'], state['source_sha256'])):
            return previous
        if eid > old_event and stamp <= datetime.fromisoformat(state['measured_at']):
            return previous
    if track:
        last_meter = Decimal(track['last_meter'])
        if (obs['format_id'] != track['format'] or absolute < last_meter
                or (eid == old_event and absolute != last_meter)):
            return dict(previous, state=dict(state, status='held_at_last_reading'))
        amount = Decimal(track['base']) + (absolute - Decimal(track['first_meter']))
        track = dict(track)
    else:
        legacy_identity = ((previous or {}).get('anchor') or {}).get('identity')
        if old_event is not None and legacy_identity and legacy_identity[0] != obs['format_id']:
            return previous
        # Upgrade at the last displayed amount. On first setup use a synchronous
        # full-day estimate once, or the covered segment if midnight is missing.
        initial = state
        if old_event is None:
            source_range = full if _range_at(full, obs, day, zone) else None
            initial = _segment_estimate(None, obs, source_range, today, zone)['state']
        amount = Decimal(initial['value_ft3'])
        partial = (initial.get('method') != 'range_midpoint_v1' or initial.get('status') == 'stale'
                   or (old_event is not None and eid != old_event))
        midnight = datetime.combine(today, time.min, ZoneInfo(zone))
        track = dict(base=str(amount), first_meter=str(absolute), format=obs['format_id'],
                     partial=partial, midnight=int(midnight.timestamp() * 1000), group=0, points=[])
    if eid != old_event and (meter['status'] == 'partial_coverage'
                             or (old_event is not None and eid != old_event + 1)):
        track['partial'] = True
        track['group'] += 1
    track['last_meter'] = str(absolute)
    value = str(amount.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
    new = dict(state if same_day else opening(day, zone),
               day=day, timezone=zone, event_id=eid, measured_at=meter['measured_at'],
               source_sha256=meter['source_sha256'], value_ft3=value, method=MOVEMENT,
               partial_coverage=track['partial'],
               status='partial_coverage' if track['partial'] else 'meter_movement',
               assumption='Starting estimate plus the change in the nominal meter reading. Unknown extra turns are excluded.')
    new.pop('conflict_event_id', None)
    if not new.get('bounds_event_id') and state.get('lower_ft3') is not None and old_event is not None:
        new.update(bounds_event_id=old_event, bounds_measured_at=state['measured_at'],
                   bounds_source_sha256=state['source_sha256'])
    # Keep the first observation and the last actual observation per elapsed hour.
    # Elapsed time distinguishes both occurrences of an hour on a fall-back day.
    ms = int(stamp.replace(microsecond=0).timestamp()) * 1000 + stamp.microsecond // 1000
    point = [ms, float(value), eid, track['group']]
    points = list(track['points'])
    if not points or points[-1][2] != eid:
        hour = (ms - track['midnight']) // 3600000
        if len(points) > 1 and (points[-1][0] - track['midnight']) // 3600000 == hour:
            points[-1] = point
        else:
            points.append(point)
    track['points'] = points
    return _with_bounds(dict(state=new, anchor=None, movement=track), full)


class NominalPublisher:
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint
        self.key = None
        self.record = None
        self.sent = None

    def publish(self, output, obs, full, today, zone, meter=None, prior_meter=None):
        key = output.config['unique_id']
        if self.key != key:
            with closing(sqlite3.connect(self.checkpoint)) as db, db:
                db.execute('CREATE TABLE IF NOT EXISTS daily_nominal (identity TEXT PRIMARY KEY, record TEXT NOT NULL)')
                row = db.execute('SELECT record FROM daily_nominal WHERE identity=?', (key,)).fetchone()
            self.record = json.loads(row[0]) if row else None
            self.key = key
            self.sent = None
        prior = self.record
        # The range sensor and register can publish at different cadences. Only
        # convert a legacy checkpoint at the same event, digest and source time.
        identity = ((prior or {}).get('anchor') or {}).get('identity')
        if (prior and 'movement' not in prior and obs and prior_meter and identity
                and identity[0] == obs['format_id']
                and (prior['state']['day'], prior['state']['timezone']) == (today.isoformat(), zone)):
            old = prior['state']
            if (old.get('event_id'),old.get('measured_at'),old.get('source_sha256')) == (
                    prior_meter.get('event_id'),prior_meter.get('measured_at'),prior_meter.get('source_sha256')) and old.get('event_id'):
                bound = dict(format_id=identity[0], segment_id=identity[1], segment_started_at=identity[2],
                             event_id=old['event_id'], captured_at=old['measured_at'], source_sha256=old['source_sha256'])
                prior = advance(prior,bound,None,today,zone,prior_meter)
        record = advance(prior, obs, full, today, zone, meter)
        if record != self.record:
            with closing(sqlite3.connect(self.checkpoint)) as db, db:
                db.execute('INSERT OR REPLACE INTO daily_nominal VALUES (?,?)', (key, json.dumps(record, allow_nan=False)))
            self.record = record
        if record['state'] != self.sent:
            output._publish(output.base + '/daily_nominal', json.dumps(record['state'], allow_nan=False), True)
            self.sent = record['state']
