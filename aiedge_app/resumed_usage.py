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
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from daily_records import daily_records
from mqtt_consumption import fresh_range
from recovery_range import RecoveryRange
from daily_constraints import Budget, WorkLimit
from resumed_evidence import gap_edges, reviewed_edges


class ResumedPublisher:
    def __init__(self, store, policy):
        self.store, self.policy = store, copy.deepcopy(policy)
        self.engine = RecoveryRange(report_conflicts=True)
        self.register_engine = None
        self.gap_engine = RecoveryRange()
        self.photo_engine = RecoveryRange()
        self.reset()

    def reset(self):
        self.configured = False
        self.last_good = None
        self.next_refresh = 0
        self.key = None

    def refine(self, db, day, zone, document, baseline, policy, contexts, result, budget):
        if Decimal(result['upper'])-Decimal(result['lower']) < 4:
            return result
        args = (db, day, zone, document, baseline, policy, contexts)
        # Share the original publication budget. Keep only the most recent group's
        # comparisons for the second solve at the same immutable endpoint.
        cached = {}
        def compare(conn, rows, policy, work):
            key = (rows[0]['event_id'], rows[-1]['event_id'])
            if key not in cached:
                cached.clear()
                cached[key] = gap_edges(conn,rows,policy,work)
            return list(cached[key])
        tighter, _ = self.gap_engine.calculate(*args,compare=compare,budget=budget)
        if not tighter:
            return result
        lower = max(result['lower'],tighter['lower'],key=Decimal)
        upper = min(result['upper'],tighter['upper'],key=Decimal)
        if Decimal(lower)>Decimal(upper):
            return result
        result = dict(result,lower=lower,upper=upper,method='saved_gap_comparisons_v1')
        if Decimal(upper)-Decimal(lower) < 4:
            return result
        try:
            root = Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
            edges, identity, allowance = reviewed_edges(db,root,policy,result['start']['event_id'],
                result['through']['event_id'],baseline['segment_id'],budget)
            def with_reviews(conn, rows, policy, work):
                ids = {r['event_id'] for r in rows}
                return compare(conn,rows,policy,work)+[e for e in edges if e[0] in ids and e[1] in ids]
            fit, _ = self.photo_engine.calculate(*args,compare=with_reviews,evidence_key=identity,budget=budget)
            if fit:
                lo=max(Decimal(result['lower']),Decimal(fit['lower']))
                hi=min(Decimal(result['upper']),Decimal(fit['upper']))
                if 0 <= hi-lo <= 1 and (lo>Decimal(result['lower']) or hi<Decimal(result['upper'])):
                    midpoint=((lo+hi)/2).quantize(Decimal('.1'))
                    result=dict(result,estimate=dict(value=str(midpoint),lower=str(lo),upper=str(hi),
                        review_sha256=identity,assumption=f'Assumes the reviewed movements are each accurate within {allowance} ft³.'))
        except (ValueError, WorkLimit, OSError, TypeError, KeyError, IndexError, ArithmeticError, sqlite3.Error, RecursionError):
            pass
        return result

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
        args = (db, day, zone, document, dict(through=source, segment_id=obs['segment_id']), policy, contexts)
        budget = Budget()
        # After a contradiction, give the independent register calculation first
        # use of the next refresh's budget. Neither engine borrows checkpoints.
        register_result = None
        if self.register_engine is not None:
            register_result, register_reason = self.register_engine.calculate(*args, budget=budget)
        result, reason = self.engine.calculate(*args,budget=budget)
        explanation = 'Starts at the saved reading after resumption. Earlier unknown usage is excluded, not zero. Unknown gaps within this period remain in the bounds.'
        if result:
            self.register_engine = None
            result = self.refine(*args,result,budget)
        elif reason == 'conflicting_saved_constraints' or (reason == 'rebuilding_saved_history' and register_result):
            if self.register_engine is None:
                self.register_engine = RecoveryRange(register_only=True)
                register_result, register_reason = self.register_engine.calculate(*args, budget=budget)
            if not register_result:
                return None, register_reason
            result = dict(register_result, refinement_status=reason)
            explanation += ' These bounds use the saved register endpoints, segment usage limits and meter capacity.'
            if result['method'] == 'saved_register_envelopes_v1':
                explanation += ' Intermediate register readings are compared at 100 ft³ resolution.'
            if reason == 'conflicting_saved_constraints':
                explanation += ' The finer dial constraints disagree.'
            else:
                explanation += ' The finer dial calculation is still rebuilding.'
        else:
            return None, reason
        return dict(result, timezone=zone.key, segment_id=obs['segment_id'],
            label=result['lower']+'–'+result['upper']+' ft³',
            scope='since_capture_resumed',
            prior_gap_included=False,
            explanation=explanation), None

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
