"""Publish a calendar-day range with the original measurement time and endpoint identities."""
import hashlib
import json
import logging
import os
import sqlite3
import time
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from daily_records import daily_records
from daily_constraints import InconsistentConstraints
from daily_range import COARSE_BASIS, ReadingConflict, daily_range
from mqtt_consumption import fresh_range


ESTIMATE_ASSUMPTION = (
    "Uses the lower bound; assumes no additional consumption within unresolved uncertainty. "
    "Not a measured total or a probability-based prediction. Unknown gaps remain unknown."
)


def _decimal_bounds(result):
    lower, upper = Decimal(result['lower']), Decimal(result['upper'])
    if not lower.is_finite() or not upper.is_finite() or not 0 <= lower <= upper:
        raise ValueError('invalid estimate bounds')
    return lower, upper


def _source_digest(source):
    return hashlib.sha256(json.dumps(source, sort_keys=True, allow_nan=False, default=str).encode()).hexdigest()


def _compatible_tail(rows, index, document, revision, contexts):
    prior = rows[index]['event_observation']
    for row in rows[index+1:]:
        src = row['event_observation']
        context = contexts.get(src['context_id'])
        if (row['unit'] != document['unit'] or any(src[k] != prior[k] for k in ('camera','clock_id','format_id'))
                or not context or context[:2] != (document['pipeline_id'], revision)
                or type(context[2]) is not int or not 1 <= context[2] <= src['event_id']
                or src['event_id'] <= prior['event_id'] or src['monotonic_us'] <= prior['monotonic_us']
                or datetime.fromisoformat(src['captured_at']) <= datetime.fromisoformat(prior['captured_at'])
                or ((row.get('absolute') or {}).get('bounds') or {}).get('wraps_register') is True):
            return False
        prior = src
    return True


CHECKPOINT_FIELDS = ('day','timezone','before','after','through','segment_id','lower','upper',
                     'constraint_basis','register_resolution_ft3','maximum_rate_per_second')


def nominal_estimate(result):
    lower, upper = _decimal_bounds(result)
    middle = ((lower + upper) / 2).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    assumption = ('Midpoint of the unresolved daily bounds, rounded to 0.01 ft³. '
                  'Individual meter readings or a whole-turn count may support only parts of this range.')
    if result.get('constraint_basis') == COARSE_BASIS:
        assumption += ' Recovered from midnight using the coarse register and saved segment bounds. Gap usage is unknown.'
    return dict(value_ft3=str(middle), method='range_midpoint_v1', assumption=assumption)


def low_use_estimate(result):
    """Presentation only: never fill ledger gaps or alter accounting bounds.

    The lower envelope is a convention, not proof of a feasible point trajectory.
    Do not select a midpoint or infer a likelihood from a capacity ceiling or bill.
    """
    lower, _ = _decimal_bounds(result)
    return dict(value_ft3=str(lower),
                label='≈' + str(lower.quantize(Decimal('1'), rounding=ROUND_HALF_UP)) + ' ft³',
                method='lower_bound_assumption_v1', assumption=ESTIMATE_ASSUMPTION)


class DailyPublisher:
    def __init__(self, store, evidence_policy=None, *, checkpoint=None):
        self.store = store
        self.checkpoint = checkpoint
        self.supported_source = None
        if checkpoint is not None:
            try:
                with checkpoint.open(encoding='utf8') as stream:
                    saved = json.load(stream)
                if isinstance(saved, dict) and saved.get('sha256') == _source_digest(saved.get('source')):
                    self.supported_source = saved.get('source')
            except (OSError, ValueError):
                pass  # The ledger can still identify a conflict and its predecessor.
        from daily_empirical import validate
        self.evidence_policy = validate(evidence_policy or {})
        from recent_usage import RecentPublisher
        self.recent = RecentPublisher(store, self.evidence_policy)
        from resumed_usage import ResumedPublisher
        self.resumed = ResumedPublisher(store, self.evidence_policy)
        from recovery_range import RecoveryRange
        self.recovery = RecoveryRange()
        self.reset()

    def reset(self):
        self.recent.reset()
        self.resumed.reset()
        self.configured = False
        self.key = None
        self.next_refresh = 0
        self.last_good = None

    def chart_sources(self, format_id, zone_name):
        """Use the acknowledged day's checkpoint to locate historical chart data."""
        saved = self.supported_source
        if not saved or not zone_name or not format_id:
            return {}
        zone = ZoneInfo(zone_name)
        day = saved.get('day', '')
        today = datetime.now(zone).date().isoformat()
        if (not day or day > today or saved.get('timezone') != zone_name
                or (saved.get('through') or {}).get('format_id') != format_id
                or saved.get('policy_sha256') != _source_digest(self.evidence_policy)):
            return {}
        # These are historical query anchors. They never refresh a sensor or imply
        # a new measurement. Recent and daily calculations have different bases.
        daily = {k:v for k,v in saved.items() if k in CHECKPOINT_FIELDS}
        daily.update(historical_only=True, unknown_gaps_preserved=True)
        policy = self.recent.policy
        recent = dict(through=daily['through'], timezone=zone_name, unknown_gaps_preserved=True,
                      constraint_assumptions=policy,
                      constraint_basis='empirical_dial_and_meter_capacity' if policy else 'saved_readings')
        historical = dict(chart_period_reference=recent)
        if day == today:
            historical['chart_daily'] = daily
        return historical

    def _retain_pending(self, snapshot, today, zone, now):
        previous = self.last_good
        if not previous:
            return False
        payload, published_at, document = previous
        stale = payload.get('status') == 'stale'
        if not stale and snapshot.get("_daily_publication_pending") is not True:
            return False
        # Keep the original label/time only. Never republish it to renew HA expiry,
        # borrow a newer timestamp, or bridge a failed/unclassified capture.
        return (0 <= now - published_at < 660 and payload["day"] == today.isoformat()
                and payload["timezone"] == zone.key and snapshot.get("format") == document
                and snapshot.get("_publication_segment_id") == payload.get("checked_segment_id", payload["segment_id"]))

    def _calculate(self, db, rows, today, zone, document, revision, contexts):
        policy = self.evidence_policy
        from dial_travel import phases
        result = daily_range(rows, today, zone, document, revision, contexts,
                             read_phases=lambda *args: phases(db, *args))
        if policy and result.get('constraint_basis') != COARSE_BASIS:
            from daily_empirical import refine
            result = refine(db, rows, today, zone, document, result, policy, include_elapsed=False)
        return result

    def _prior_result(self, conflict, db, rows, today, zone, document, obs, contexts):
        """Recalculate one fully supported prefix without using any rejected volume."""
        if not rows:
            return None
        last = rows[-1]['event_observation']
        source_keys = ('event_id', 'source_sha256', 'captured_at', 'format_id')
        if (any(last[k] != obs[k] for k in source_keys)
                or rows[-1]['segment_id'] != obs['segment_id']):
            return None
        candidates = []
        if isinstance(conflict, ReadingConflict):
            index = next((i for i,r in enumerate(rows) if r['event_id'] == conflict.event_id), 0)
            if index:
                candidates.append(index - 1)
        saved = self.supported_source
        saved_matches = (isinstance(saved, dict) and saved.get('day') == today.isoformat()
                         and saved.get('timezone') == zone.key and saved.get('policy_sha256') == _source_digest(self.evidence_policy))
        if saved_matches:
            idx = next((i for i,r in enumerate(rows) if r['event_observation'] == saved.get('through')), None)
            if idx is not None and idx < len(rows)-1 and (not isinstance(conflict, ReadingConflict)
                                                         or rows[idx]['event_id'] < conflict.event_id):
                candidates.append(idx)
        for index in sorted(set(candidates), reverse=True):
            end = rows[index]['event_observation']
            if datetime.fromisoformat(end['captured_at']).astimezone(zone).date() != today:
                continue
            if not _compatible_tail(rows, index, document, obs['format_id'], contexts):
                return None
            # Reuse the acknowledged bounds only on the same lineage, with both
            # original midnight measurements and the endpoint still in the ledger.
            if (saved_matches and saved.get('through') == end and saved.get('segment_id') == rows[index]['segment_id']
                    and all(any(r['event_observation'] == saved[k] for r in rows[:index+1]) for k in ('before','after'))):
                result = {k:saved[k] for k in CHECKPOINT_FIELDS if k in saved}
                _decimal_bounds(result)
            else:
                try:
                    result = self._calculate(db, rows[:index+1], today, zone, document, obs['format_id'], contexts)
                except InconsistentConstraints:
                    continue
            if result['through'] != end or result['segment_id'] != rows[index]['segment_id']:
                return None
            return dict(result, status='stale', unknown_gaps_preserved=True,
                        conflict_event_id=getattr(conflict, 'event_id', last['event_id']),
                        checked_through=last, checked_segment_id=obs['segment_id'])
        return None

    def publish(self, output, snapshot):
        if (snapshot.get("format") or {}).get("unit") != "ft3":
            if self.last_good:
                output._publish(output.base + "/daily_range", "{}")
                self.reset()
            return
        topic = output.base + "/daily_range"
        if not self.configured:
            uid = output.config["unique_id"] + "_daily_range"
            config = dict(name="Gas used today", unique_id=uid, device=output.config["device"],
                          state_topic=topic, json_attributes_topic=topic, expire_after=660,
                          value_template="{{ value_json.label | default('unknown') }}",
                          availability_topic=topic,
                          availability_template="{{ 'online' if value_json.label is defined else 'offline' }}")
            output._publish("homeassistant/sensor/" + uid + "/config", json.dumps(config), True)
            self.configured = True
        obs = fresh_range(snapshot, max(90, output.interval * 3))
        payload = {}
        now = time.monotonic()
        key = None
        try:
            zone = ZoneInfo(os.environ["TZ"])
            today = datetime.now(zone).date()
            if obs is None and self._retain_pending(snapshot, today, zone, now):
                return
            if obs and datetime.fromisoformat(obs["captured_at"]).astimezone(zone).date() == today:
                key = (today, zone.key, obs["format_id"], obs["segment_id"])
                if self.key in (key, ("offline", key)) and now < self.next_refresh:
                    return
                event = obs["event_id"]
                with self.store.connect() as db:
                    contexts = {context: (pipeline, format_id, first_event)
                                for context, pipeline, format_id, first_event in db.execute(
                                    "SELECT context,pipeline,format_id,first_event FROM event_selection_contexts")}
                    rows = list(daily_records(db, max(1, event - 32768), event, obs["segment_id"]))
                    try:
                        result = self._calculate(db, rows, today, zone, snapshot['format'], obs['format_id'], contexts)
                    except InconsistentConstraints as conflict:
                        result = self._prior_result(conflict, db, rows, today, zone, snapshot['format'], obs, contexts)
                        if result is None:
                            raise
                    if result.get('status') != 'stale' and self.evidence_policy.get('elapsed_start_event'):
                        elapsed, reason = self.recovery.calculate(db, today, zone, snapshot['format'], result, self.evidence_policy, contexts)
                        result.update(elapsed_range=elapsed, elapsed_unavailable_reason=reason)
                end = result.get('checked_through', result["through"])
                if any(end[k] != obs[k] for k in ("event_id", "source_sha256", "captured_at", "format_id")):
                    raise ValueError("daily endpoint changed")
                if result.get('checked_segment_id', result["segment_id"]) != obs["segment_id"]:
                    raise ValueError("daily endpoint segment changed")
                payload = dict(result, timezone=zone.key,
                               label=result["lower"] + "–" + result["upper"] + " ft³",
                               low_use_estimate=low_use_estimate(result),
                               nominal_estimate=nominal_estimate(result))
        except (ValueError, ArithmeticError, KeyError, TypeError, sqlite3.Error, ZoneInfoNotFoundError):
            pass
        if not payload and self.key == ("offline", key) and now < self.next_refresh:
            return
        output._publish(topic, json.dumps(payload, allow_nan=False))
        if payload:
            source = {k: payload[k] for k in CHECKPOINT_FIELDS if k in payload}
            source['policy_sha256'] = _source_digest(self.evidence_policy)
            if source != self.supported_source:
                if self.checkpoint is not None:
                    from setup_store import Setup
                    record = dict(source=source, sha256=_source_digest(source))
                    try:
                        Setup._atomic(self.checkpoint, json.dumps(record, default=str).encode('utf8'))
                    except OSError as exc:
                        logging.getLogger(__name__).warning("Could not save the supported daily source: %s", exc)
                self.supported_source = source
        from copy import deepcopy
        self.last_good = (deepcopy(payload), now, deepcopy(snapshot["format"])) if payload else None
        self.key = key if payload else ("offline", key)
        self.next_refresh = now + (30 if not payload or payload.get('elapsed_unavailable_reason') == 'rebuilding_saved_history' else 300)


