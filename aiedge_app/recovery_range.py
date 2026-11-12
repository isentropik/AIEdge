"""Bounded, restartable saved-ledger recovery accounting. No writes or gap filling.

Completed prefix bounds constrain the actual original and boundary readings.
Both remain graph nodes in the next solve; no time interval is skipped.
Omitting cross-chunk constraints can widen, never tighten, the outer bound.
Only one in-memory checkpoint is kept. Restart rebuilds from the saved origin.
"""
import json
import sqlite3
from datetime import datetime
from decimal import Decimal, localcontext
from daily_constraints import Budget, WorkLimit, _tighten, number, bands
from daily_records import daily_records
from daily_empirical import interval_edges, validate

CHUNK_EVENTS = 2048


class RecoveryRange:
    def __init__(self):
        self.key = None
        self.segment = None
        self.checkpoint = None

    def calculate(self, db, day, zone, document, baseline, policy, contexts):
        try:
            return self._calculate(db, day, zone, document, baseline, policy, contexts), None
        except WorkLimit:
            return None, 'rebuilding_saved_history'
        except (ValueError, KeyError, TypeError, IndexError, ArithmeticError,
                sqlite3.Error, StopIteration, AttributeError, OSError):
            self.key = self.checkpoint = None
            return None, 'unavailable'

    def _calculate(self, db, day, zone, document, baseline, policy, contexts):
        policy = validate(policy)
        origin = policy['elapsed_start_event']
        target = baseline['through']['event_id']
        segment = baseline['segment_id']
        if target < origin or document['unit'] != 'ft3':
            raise ValueError('invalid recovery period')
        if [number(d['value_per_revolution']) for d in document['dials']][-2:] != [1000, 5]:
            raise ValueError('unsupported recovery geometry')
        key = json.dumps([document, policy, contexts], sort_keys=True, default=str)
        if key != self.key or (self.checkpoint and self.checkpoint[1]['event_id'] > target):
            self.key, self.checkpoint = key, None
        if self.checkpoint and self.segment != segment:
            # Reuse only if the new segment explicitly inherits the entire
            # completed prefix. No guessed continuity across interpretations.
            inherited = db.execute("""WITH RECURSIVE lineage(s,e) AS (
                SELECT ?, ? UNION SELECT l.prior_segment_id,min(e,l.first_event-1)
                FROM consumption_segment_links l JOIN lineage ON l.segment_id=s
                WHERE l.first_event > ?)
                SELECT 1 FROM lineage WHERE s=? AND e>=? LIMIT 1""",
                (segment,target,self.checkpoint[1]['event_id'],self.segment,self.checkpoint[1]['event_id'])).fetchone()
            if not inherited:
                self.checkpoint = None
        self.segment = segment
        budget = Budget()
        with localcontext() as context:
            context.prec = 50
            if self.checkpoint is None:
                rows = list(daily_records(db, origin, origin, segment))
                if len(rows) != 1:
                    raise ValueError('recovery origin missing')
                source = rows[0]['event_observation']
                self.checkpoint = (source, source, Decimal(0), Decimal(0))
            start, boundary, lower, upper = self.checkpoint
            original = list(daily_records(db, origin, origin, segment))
            if len(original) != 1 or original[0]['event_observation'] != start:
                raise ValueError('recovery origin changed')
            while boundary['event_id'] < target:
                budget.spend()
                stop = min(target, boundary['event_id'] + CHUNK_EVENTS)
                rows = list(daily_records(db, boundary['event_id'], stop, segment))
                budget.spend(len(rows))
                if not rows or rows[0]['event_observation'] != boundary:
                    raise ValueError('recovery boundary changed')
                # Do not scan unbounded empty event spans or substitute a timestamp.
                if len(rows) < 2:
                    raise ValueError('no accepted recovery endpoint in chunk')
                modulus = number(document['dials'][0]['value_per_revolution'])
                if stop < target:
                    split = next((i for i in range(len(rows)-1, 0, -1) if bands(rows[i], modulus)), None)
                    if split is None:
                        raise ValueError('no bounded recovery checkpoint')
                    rows = rows[:split+1]
                end = rows[-1]['event_observation']
                for row in rows:
                    source = row['event_observation']
                    saved = contexts.get(source['context_id'])
                    if (not saved or saved[:2] != (policy['pipeline_id'], policy['format_id'])
                            or type(saved[2]) is not int or not 1 <= saved[2] <= source['event_id']
                            or source['format_id'] != policy['format_id']):
                        raise ValueError('unverified recovery context')
                seconds = number(end['monotonic_us'] - boundary['monotonic_us']) / 1000000
                rate = min(number(document['maximum_rate_per_second']), number(policy['capacity_cfh'])/3600)
                modulus = number(document['dials'][0]['value_per_revolution'])
                first_bands = bands(rows[0], modulus)
                if not first_bands or first_bands[-1][1] + seconds*rate >= modulus:
                    raise ValueError('possible recovery register rollover')
                initial = dict(baseline, before=start, after=start, through=end,
                               lower=str(lower), upper=str(upper+seconds*rate))
                edges = interval_edges(db, rows, policy, budget)
                if not edges:
                    raise ValueError('no compatible recovery evidence')
                if boundary != start:
                    edges.append((start['event_id'], boundary['event_id'], lower, upper))
                    rows = original + rows
                result = _tighten(rows, day, zone, document, initial, budget, edges, rate, elapsed=True)
                lower = number(result['lower'])
                upper = number(result['upper'])
                boundary = end
                # Commit only completed full chunks. Recompute the short tail as
                # it grows, avoiding a new rounding/independence loss each refresh.
                if stop < target:
                    self.checkpoint = (start, boundary, lower, upper)
            if boundary != baseline['through']:
                raise ValueError('recovery publication source changed')
            return dict(start=start, through=boundary, lower=str(lower.quantize(Decimal('.01'))),
                        upper=str(upper.quantize(Decimal('.01'))),
                        method='saved_prefix_constraints_v1', unknown_gaps_preserved=True)
