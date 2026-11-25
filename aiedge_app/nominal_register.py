"""Publish a continuous nominal absolute register using the ledger's feasible dial bands."""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal

from daily_constraints import WorkLimit, bands, number
from absolute_motion import project


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
    if prior and not previous and (prior['source_identity'] != identity or prior['format_id'] != obs['format_id']):
        return prior, 'meter_source_changed'
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


def photo_projection(prior, record, reason, snapshot, now, max_age):
    """Keep the independent whole-hundreds observation out of movement accounting."""
    old = (prior or {}).get('photo_register')
    fine = record['state']
    if not fine:
        return old, False
    if old and (fine['event_id'] > old['event_id']
                and datetime.fromisoformat(fine['measured_at']) > datetime.fromisoformat(old['measured_at'])
                and (record['clock_id'] != old['clock_id'] or record['tick'] > old['monotonic_us'])
                and number(fine['value_ft3']) >= number(old['value_ft3'])):
        old = None
    proof = snapshot.get('_photo_register')
    if not proof or reason != 'no_qualified_reading':
        return old, False
    src = proof['source']
    if (src != (snapshot.get('consumption') or {}).get('event_observation') or
            src['format_id'] != record['format_id'] or
            hashlib.sha256(src['camera'].encode()).hexdigest() != record['source_identity']):
        return old, False
    try:
        stamp = datetime.fromisoformat(src['captured_at'])
    except (TypeError, ValueError):
        return old, False
    if stamp.tzinfo is None or not 0 <= (now-stamp).total_seconds() <= max_age:
        return old, False
    value = proof.get('register_ft3')
    if (type(value) is not int or value < 0 or value % 100 or proof['resolution_ft3'] != 100
            or type(src.get('monotonic_us')) is not int or not src.get('clock_id')):
        return old, False
    if old and src['event_id'] == old['event_id']:
        same = (src['source_sha256'], src['captured_at'], src['clock_id'], src['monotonic_us'], value)
        expected = (old['source_sha256'], old['measured_at'], old['clock_id'], old['monotonic_us'], old['lower_ft3'])
        return old, same == expected and old['event_id'] >= fine['event_id']
    anchors = [(fine, record['clock_id'], record['tick'], max(number(b[1]) for b in fine['bands_ft3']))]
    if old:
        anchors.append((old, old['clock_id'], old['monotonic_us'], number(old['upper_exclusive_ft3'])))
    rate = number(snapshot['format']['maximum_rate_per_second'])
    for last, clock, tick, ceiling in anchors:
        seconds = (stamp - datetime.fromisoformat(last['measured_at'])).total_seconds()
        if clock == src['clock_id']:
            seconds = min(seconds, (src['monotonic_us'] - tick) / 1_000_000)
        if (src['event_id'] <= last['event_id'] or seconds <= 0 or value < number(last['value_ft3'])
                or value > ceiling + rate * number(seconds)):
            return old, False
    return dict(value_ft3=str(value), lower_ft3=value, upper_exclusive_ft3=value+100, resolution_ft3=100,
                event_id=src['event_id'], measured_at=src['captured_at'], source_sha256=src['source_sha256'],
                method='photo_register_hundreds', status='photo_register', reference_sha256=proof['reference_sha256'],
                clock_id=src['clock_id'], monotonic_us=src['monotonic_us'],
                assumption='Register truncated to hundreds from this photo. Usage across gaps is unknown.'), True


class AbsolutePublisher:
    def __init__(self, path):
        self.path = path
        self.originals = None
        self.sent = None
        self.displayed = None

    def publish(self, output, obs, snapshot):
        key = output.config['unique_id']
        now = datetime.now(timezone.utc)
        max_age = max(90, getattr(output, 'interval', 0) * 3)
        meter_snapshot, meter_obs = snapshot, obs
        if self.originals and obs is None:
            completed = self.originals.completed(snapshot, now, max_age)
            if completed:
                meter_snapshot, meter_obs = completed
        with closing(sqlite3.connect(self.path, timeout=1)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS nominal_register (identity TEXT PRIMARY KEY, record TEXT NOT NULL)')
            row = db.execute('SELECT record FROM nominal_register WHERE identity=?', (key,)).fetchone()
            prior = json.loads(row[0]) if row else None
            record, reason = transition(prior, obs, snapshot.get('consumption') or {}, snapshot['format'])
            if record is None:
                proof = snapshot.get('_photo_register') or {}
                source = proof.get('source') or {}
                if not proof.get('bands_ft3'):
                    if not self.originals or not meter_obs:
                        return
                    source = (meter_snapshot.get('consumption') or {}).get('event_observation') or {}
                if not source.get('camera'):
                    return
                record = dict(state=None, format_id=source['format_id'],
                              source_identity=hashlib.sha256(source['camera'].encode()).hexdigest())
            coarse, fresh = photo_projection(prior, record, reason, snapshot, now, max_age)
            motion, current = project(prior, record, reason, meter_snapshot, meter_obs, getattr(output, 'daily', None), now, max_age,
                                      originals=self.originals)
            record = dict(record)
            if coarse:
                record['photo_register'] = coarse
            else:
                record.pop('photo_register',None)
            if motion:
                record['absolute_motion'] = motion
            if not motion and not record['state']:
                return
            if record != prior:
                db.execute('INSERT OR REPLACE INTO nominal_register VALUES (?,?)', (key, json.dumps(record,allow_nan=False)))
        state = record['state']
        if state and reason:
            state = dict(state, status='held_at_last_reading', reason=reason)
        display = state
        if coarse:
            display = {k:v for k,v in coarse.items() if k not in ('clock_id','monotonic_us')}
            if not fresh:
                display['status'] = 'held_at_last_reading'
        if motion:
            display = dict(motion['display'])
            if not current:
                display['status'] = 'held_at_last_reading'
        if self.displayed != (key, display):
            output._publish(output.base+'/absolute_nominal', json.dumps(display,allow_nan=False), True)
            self.displayed = key, display
        # Daily movement uses only the original fine register and its own measurement time.
        self.sent = (key, state) if state else None
