"""Publish a continuous nominal absolute register using the ledger's feasible dial bands."""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from decimal import Decimal

from daily_constraints import WorkLimit, bands, number


def next_value(previous, current, limit):
    """Choose the smallest supported forward movement, including the option to stand still."""
    if previous is None:
        lo, hi = current[(len(current) - 1) // 2]
        return (lo + hi) / 2
    value = number(previous['value_ft3'])
    # A revision can eliminate a candidate absolute turn without consuming five feet.
    # Bound the nominal step by the lowest feasible change across ALL old/new bands.
    changes = []
    for old_lo, old_hi in previous['bands_ft3']:
        old_lo, old_hi = number(old_lo), number(old_hi)
        for lo, hi in current:
            lower = max(0, lo - old_hi)
            upper = min(limit, hi - old_lo)
            if lower <= upper:
                changes.append((lower, upper))
    if changes:
        from daily_constraints import merge
        lower, upper = merge(changes)[0]
        for lo, hi in current:
            candidate = max(value + lower, lo)
            if candidate <= min(value + upper, hi):
                return candidate
    return None


def transition(prior, obs, consumption, document):
    previous = prior['state'] if prior else None
    if not obs:
        return prior, 'no_qualified_reading'
    source = consumption.get('event_observation') or {}
    if (not source.get('camera') or not source.get('clock_id') or type(source.get('monotonic_us')) != int
            or any(source.get(k) != obs[k] for k in ('event_id','captured_at','source_sha256','format_id'))):
        return prior, 'unbound_reading'
    identity = hashlib.sha256(source['camera'].encode()).hexdigest()
    try:
        current = bands(consumption, number(document['dials'][0]['value_per_revolution']))
    except (WorkLimit, ArithmeticError, ValueError, KeyError, TypeError):
        current = None
    if not current:
        return prior, 'absolute_bounds_missing'
    limit = Decimal(0)
    gap = False
    if previous:
        if prior['source_identity'] != identity or prior['format_id'] != obs['format_id']:
            return prior, 'meter_source_changed'
        if obs['event_id'] == previous['event_id'] and obs['source_sha256'] == previous['source_sha256'] and obs['captured_at'] == previous['measured_at']:
            return prior, None
        elapsed = (datetime.fromisoformat(obs['captured_at']) - datetime.fromisoformat(previous['measured_at'])).total_seconds()
        if prior['clock_id'] == source['clock_id']:
            elapsed = min(elapsed, (source['monotonic_us'] - prior['tick']) / 1_000_000)
        if obs['event_id'] <= previous['event_id'] or elapsed <= 0:
            return prior, 'out_of_order'
        limit = number(elapsed) * number(obs['maximum_rate_per_second'])
        gap = (obs['event_id'] != previous['event_id'] + 1 or prior['segment_id'] != obs['segment_id']
               or prior['clock_id'] != source['clock_id'] or prior['context_id'] != source.get('context_id'))
    value = next_value(previous, current, limit)
    if value is None:
        return prior, 'no_continuous_candidate'
    anchor = consumption.get('anchor_captured_at')
    if previous:
        # Reject a branch correction masquerading as one or more revolutions.
        # Segment limits provide separate evidence of movement since the last accepted event.
        fine = min(document['dials'], key=lambda dial: dial['value_per_revolution'])
        revolution = number(fine['value_per_revolution'])
        tolerance = 2 * number(fine['position_error']) * revolution / 10
        step = value - number(previous['value_ft3'])
        turns = int((step + tolerance) / revolution)
        if turns:
            proven = Decimal(0)
            if (anchor and prior['anchor'] == anchor and prior['segment_id'] == obs['segment_id']
                    and prior['clock_id'] == source['clock_id'] and prior['context_id'] == source.get('context_id')):
                proven = number(obs['minimum']) - number(prior['segment_upper'])
            if proven < turns * revolution - tolerance:
                return prior, 'whole_turn_unconfirmed'
    state = dict(value_ft3=str(value), measured_at=obs['captured_at'], event_id=obs['event_id'],
                 source_sha256=obs['source_sha256'], bands_ft3=[[float(lo), float(hi)] for lo, hi in current],
                 status='partial_coverage' if gap else 'nominal', method='minimum_supported_forward_movement',
                 assumption='Initial reading uses the middle band (lower on a tie). Unresolved extra turns are excluded.')
    return dict(state=state, format_id=obs['format_id'], source_identity=identity,
                segment_id=obs['segment_id'], context_id=source.get('context_id'),
                anchor=anchor, segment_upper=obs['maximum'],
                clock_id=source['clock_id'], tick=source['monotonic_us']), None


class AbsolutePublisher:
    def __init__(self, path):
        self.path = path
        self.sent = None

    def publish(self, output, obs, snapshot):
        key = output.config['unique_id']
        with closing(sqlite3.connect(self.path, timeout=1)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS nominal_register (identity TEXT PRIMARY KEY, record TEXT NOT NULL)')
            row = db.execute('SELECT record FROM nominal_register WHERE identity=?', (key,)).fetchone()
            prior = json.loads(row[0]) if row else None
            record, reason = transition(prior, obs, snapshot.get('consumption') or {}, snapshot['format'])
            if record is None:
                return
            if record != prior:
                db.execute('INSERT OR REPLACE INTO nominal_register VALUES (?,?)', (key, json.dumps(record,allow_nan=False)))
        state = record['state']
        if reason:
            state = dict(state, status='held_at_last_reading', reason=reason)
        if self.sent != (key, state):
            output._publish(output.base+'/absolute_nominal', json.dumps(state,allow_nan=False), True)
            self.sent = key, state
