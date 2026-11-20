"""Continuous display estimate. The ledger and its evidence bounds are read-only here."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from zoneinfo import ZoneInfo


def opening(day, zone):
    return dict(day=day, timezone=zone, value_ft3='0.00', status='opening_balance',
                method='calendar_day_opening', assumption='Zero at midnight. Usage after midnight is unknown until observed.',
                measured_at=None, event_id=None, source_sha256=None,
                lower_ft3=None, upper_ft3=None, low_use_estimate_ft3=None)


def advance(previous, obs, full, today, zone):
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


class NominalPublisher:
    def __init__(self, checkpoint):
        self.checkpoint = checkpoint
        self.key = None
        self.record = None
        self.sent = None

    def publish(self, output, obs, full, today, zone):
        key = output.config['unique_id']
        if self.key != key:
            with closing(sqlite3.connect(self.checkpoint)) as db, db:
                db.execute('CREATE TABLE IF NOT EXISTS daily_nominal (identity TEXT PRIMARY KEY, record TEXT NOT NULL)')
                row = db.execute('SELECT record FROM daily_nominal WHERE identity=?', (key,)).fetchone()
            self.record = json.loads(row[0]) if row else None
            self.key = key
            self.sent = None
        record = advance(self.record, obs, full, today, zone)
        if record != self.record:
            with closing(sqlite3.connect(self.checkpoint)) as db, db:
                db.execute('INSERT OR REPLACE INTO daily_nominal VALUES (?,?)', (key, json.dumps(record, allow_nan=False)))
            self.record = record
        if record['state'] != self.sent:
            output._publish(output.base + '/daily_nominal', json.dumps(record['state'], allow_nan=False), True)
            self.sent = record['state']
