"""Independent saved-reading range from an explicitly reviewed resumption anchor.

No midnight/hour prerequisite, capture commands, ledger writes or gap filling.
The anchor survives restarts and subsequent gaps; it is never moved forward to
make a result look tighter. Missing/incompatible evidence withholds the range.
"""
import copy
import json
import os
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from daily_records import daily_records
from mqtt_consumption import fresh_range
from recovery_range import RecoveryRange


class ResumedPublisher:
    def __init__(self, store, policy):
        self.store, self.policy = store, copy.deepcopy(policy)
        self.engine = RecoveryRange()
        self.reset()

    def reset(self):
        self.configured = False
        self.last_good = None
        self.next_refresh = 0
        self.key = None

    def calculate(self, db, document, obs, zone):
        origin = self.policy.get('resumed_start_event')
        if not origin or obs['event_id'] <= origin:
            raise ValueError('awaiting_two_saved_readings')
        end = list(daily_records(db, obs['event_id'], obs['event_id'], obs['segment_id']))
        if len(end) != 1:
            raise ValueError('resumed_endpoint_missing')
        source = end[0]['event_observation']
        if any(source[k] != obs[k] for k in ('event_id', 'source_sha256', 'captured_at', 'format_id')):
            raise ValueError('resumed_endpoint_changed')
        contexts = {c: (p, f, first) for c,p,f,first in db.execute(
            'SELECT context,pipeline,format_id,first_event FROM event_selection_contexts')}
        policy = dict(self.policy)
        policy.pop('resumed_start_event')
        policy['elapsed_start_event'] = origin
        day = datetime.fromisoformat(source['captured_at']).astimezone(zone).date()
        result, reason = self.engine.calculate(db, day, zone, document,
            dict(through=source, segment_id=obs['segment_id']), policy, contexts)
        if not result:
            return None, reason
        return dict(result, timezone=zone.key, segment_id=obs['segment_id'],
            label=result['lower']+'–'+result['upper']+' ft³',
            scope='since_capture_resumed',
            prior_gap_included=False,
            explanation='Starts at the saved reading after resumption. Earlier unknown usage is excluded, not zero. Unknown gaps within this period remain in the bounds.'), None

    def publish(self, output, snapshot):
        topic = output.base + '/resumed_range'
        if not self.configured:
            uid = output.config['unique_id'] + '_resumed_range'
            config = dict(name='Gas used since capture resumed', unique_id=uid,
                device=output.config['device'], state_topic=topic, json_attributes_topic=topic,
                expire_after=660, value_template="{{ value_json.label | default('unknown') }}",
                availability_topic=topic,
                availability_template="{{ 'online' if value_json.label is defined else 'offline' }}")
            output._publish('homeassistant/sensor/'+uid+'/config', json.dumps(config), True)
            self.configured = True
        obs = fresh_range(snapshot, max(90, output.interval*3))
        now = time.monotonic()
        key = (obs['segment_id'], obs['format_id']) if obs else None
        if self.key == key and now < self.next_refresh:
            return
        payload, reason = {}, None
        try:
            zone = ZoneInfo(os.environ['TZ'])
            if obs and snapshot['format']['unit'] == 'ft3':
                with self.store.connect() as db:
                    result, reason = self.calculate(db, snapshot['format'], obs, zone)
                payload = result or {}
        except (ValueError, ArithmeticError, KeyError, TypeError, sqlite3.Error, ZoneInfoNotFoundError):
            pass
        output._publish(topic, json.dumps(payload, allow_nan=False))
        # Only a broker-acknowledged payload is exposed in the app.
        self.last_good = (copy.deepcopy(payload), now) if payload else None
        self.key = key
        self.next_refresh = now + (30 if not payload or reason else 60)
