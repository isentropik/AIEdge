"""Bounded recent saved usage. No ledger writes, interpolation or point estimates."""
import bisect
import json
import os
import sqlite3
import time
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from daily_constraints import Budget, WorkLimit, _tighten, number, bands
from daily_empirical import validate, evidence, comparisons
from daily_records import daily_records
from mqtt_consumption import fresh_range

MAX_RECORDS = 4097
BOUNDARY_SLACK = 90  # Report actual saved endpoints; never interpolate a reading.


def recent_ranges(db, rows, document, contexts, zone, policy=None):
    if not rows or len(rows) > MAX_RECORDS:
        raise ValueError('recent_history_limit')
    policy = validate(policy or {})
    if document['unit'] != 'ft3' or number(document['maximum_rate_per_second']) <= 0:
        raise ValueError('recent_unsupported_meter')
    stamps = [datetime.fromisoformat(r['event_observation']['captured_at']) for r in rows]
    if any(t.utcoffset() is None for t in stamps):
        raise ValueError('recent_missing_timezone')
    # UTC timestamps avoid wall-clock subtraction across DST folds.
    seconds = [t.timestamp() for t in stamps]
    if any(b <= a for a, b in zip(seconds, seconds[1:])):
        raise ValueError('recent_unordered_time')
    indices = []
    for lag in (3600, 2700, 1800, 900):
        target = seconds[-1] - lag
        i = bisect.bisect_right(seconds, target) - 1
        if i < 0 or target - seconds[i] > BOUNDARY_SLACK:
            raise ValueError('recent_boundary_missing')
        indices.append(i)
    indices.append(len(rows)-1)
    if len(set(indices)) != 5:
        raise ValueError('recent_boundary_missing')
    first = indices[0]
    rows, stamps = rows[first:], stamps[first:]
    indices = [i-first for i in indices]
    identity = rows[-1]['event_observation']
    previous = None
    for row, stamp in zip(rows, stamps):
        source = row['event_observation']
        saved = contexts.get(source['context_id'])
        if (row.get('observation_accepted') is not True or row['unit'] != 'ft3'
                or saved is None or saved[:2] != (document['pipeline_id'], source['format_id'])
                or type(saved[2]) is not int or not 1 <= saved[2] <= source['event_id']
                or any(source[k] != identity[k] for k in ('camera', 'clock_id', 'format_id'))):
            raise ValueError('recent_source_changed')
        if previous and (source['event_id'] <= previous['event_id']
                         or source['monotonic_us'] <= previous['monotonic_us']):
            raise ValueError('recent_unordered_source')
        previous = source
    budget = Budget()  # One shared bound for hour + four quarters, not five budgets.
    rate = number(document['maximum_rate_per_second'])
    edges = []
    with localcontext() as context:
        context.prec = 50
        if policy:
            if (len(document['dials']) != 6
                    or number(document['dials'][-2]['value_per_revolution']) != 1000
                    or number(document['dials'][-1]['value_per_revolution']) != 5):
                raise ValueError('recent_unsupported_geometry')
            values = evidence(db, rows, policy, budget)
            edges = comparisons(rows, values, number(policy['slow_allowance_ft3']), budget)
            rate = min(rate, number(policy['capacity_cfh']) / 3600)

        def interval(left, right):
            selected = rows[left:right+1]
            start, end = selected[0]['event_observation'], selected[-1]['event_observation']
            duration = number(end['monotonic_us'] - start['monotonic_us']) / 1000000
            modulus = number(document['dials'][0]['value_per_revolution'])
            initial = bands(selected[0], modulus)
            if initial is None or initial[-1][1] + duration*rate >= modulus:
                raise ValueError('recent_possible_register_rollover')
            baseline = dict(before=start, after=start, through=end,
                            segment_id=selected[-1]['segment_id'], lower='0', upper=str(duration*rate))
            result = _tighten(selected, stamps[right].astimezone(zone).date(), zone,
                              document, baseline, budget, edges, rate, elapsed=True)
            return dict(start=start, through=end, lower=result['lower'], upper=result['upper'],
                        duration_seconds=str(duration))

        hour = interval(0, len(rows)-1)
        quarters = [interval(a, b) for a, b in zip(indices, indices[1:])]
    return dict(hour=hour, quarters=quarters, through=identity, timezone=zone.key,
                segment_id=rows[-1]['segment_id'],
                accuracy_verified=False, unknown_gaps_preserved=True,
                window_basis='saved_endpoints_at_or_before_15_minute_boundaries',
                boundary_slack_seconds=BOUNDARY_SLACK,
                constraint_assumptions=policy, constraint_basis='empirical_dial_and_household_capacity' if policy else 'saved_readings',
                label=hour['lower']+'–'+hour['upper']+' ft³')


class RecentPublisher:
    def __init__(self, store, policy=None):
        self.store, self.policy = store, validate(policy or {})
        self.reset()

    def reset(self):
        self.configured = False
        self.next_refresh = 0
        self.key = None
        self.last_good = None

    def publish(self, output, snapshot):
        topic = output.base + '/recent_usage'
        if not self.configured:
            uid = output.config['unique_id'] + '_recent_usage'
            config = dict(name='Gas used last hour', unique_id=uid, device=output.config['device'],
                          state_topic=topic, json_attributes_topic=topic, expire_after=660,
                          value_template="{{ value_json.label | default('unknown') }}",
                          availability_topic=topic,
                          availability_template="{{ 'online' if value_json.label is defined else 'offline' }}")
            output._publish('homeassistant/sensor/'+uid+'/config', json.dumps(config), True)
            self.configured = True
        now = time.monotonic()
        obs = fresh_range(snapshot, max(90, output.interval*3))
        document = snapshot.get('format') or {}
        if obs is None and self.last_good and snapshot.get('_daily_publication_pending') is True:
            previous, published, prior_document, segment = self.last_good
            if (0 <= now-published < 660 and document == prior_document
                    and os.environ.get('TZ') == previous['timezone']
                    and snapshot.get('_publication_segment_id') == segment):
                return  # Never renew MQTT expiry or borrow the newer capture's time.
        # Invalidation is immediate; do not keep a good value alive across a fault.
        key = (obs['format_id'], obs['segment_id'], os.environ.get('TZ'), json.dumps(document, sort_keys=True)) if obs else None
        if key == self.key and now < self.next_refresh:
            return
        payload = {}
        try:
            if obs is None or document.get('unit') != 'ft3':
                raise ValueError('recent_endpoint_unavailable')
            zone = ZoneInfo(os.environ['TZ'])
            event = obs['event_id']
            with self.store.connect() as db:
                contexts = {c:(p,f,n) for c,p,f,n in db.execute(
                    'SELECT context,pipeline,format_id,first_event FROM event_selection_contexts')}
                rows = list(daily_records(db, max(1,event-MAX_RECORDS+1), event, obs['segment_id']))
                payload = recent_ranges(db, rows, document, contexts, zone, self.policy)
            if any(payload['through'][k] != obs[k] for k in ('event_id','source_sha256','captured_at','format_id')):
                raise ValueError('recent_endpoint_changed')
            if payload['segment_id'] != obs['segment_id']:
                raise ValueError('recent_segment_changed')
        except (ValueError, KeyError, TypeError, ArithmeticError, IndexError, sqlite3.Error, ZoneInfoNotFoundError, WorkLimit):
            payload = {}
        output._publish(topic, json.dumps(payload, allow_nan=False))
        self.last_good = (deepcopy(payload), now, deepcopy(document), obs['segment_id']) if payload else None
        self.key = key
        self.next_refresh = now + (300 if payload else 30)
