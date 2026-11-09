"""Opt-in empirical daily refinement. Never edits a record or fills an unknown gap."""
import bisect
import re
import sqlite3
from decimal import Decimal, localcontext
from daily_constraints import Budget, WorkLimit, _tighten, number

FIELDS = {'capacity_cfh', 'slow_allowance_ft3', 'pipeline_id', 'format_id'}


def validate(policy):
    if not isinstance(policy, dict):
        raise ValueError('invalid daily evidence policy')
    if not policy:
        return {}
    if set(policy) - {'elapsed_start_event'} != FIELDS:
        raise ValueError('incomplete daily evidence policy')
    if 'elapsed_start_event' in policy and (type(policy['elapsed_start_event']) is not int or policy['elapsed_start_event'] <= 0):
        raise ValueError('invalid elapsed start event')
    for key in ('capacity_cfh', 'slow_allowance_ft3'):
        if isinstance(policy[key], bool) or not isinstance(policy[key], (int, float, str, Decimal)):
            raise ValueError('invalid daily policy number')
    if not 0 < number(policy['capacity_cfh']) <= 10000 or not 6 <= number(policy['slow_allowance_ft3']) <= 100:
        raise ValueError('daily policy outside reviewed scope')
    if any(not isinstance(policy[k], str) or not re.fullmatch('[a-f0-9]{64}', policy[k])
           for k in ('pipeline_id', 'format_id')):
        raise ValueError('daily policy requires exact format and pipeline')
    return dict(policy)


def evidence(db, rows, policy, budget):
    # Reuse the historical getter's request, cache, mask and acquisition checks.
    # It reads committed saved inference only: no camera, inference or writes.
    from event_observation_read import _read
    from observation_support import observed_rows
    values = []
    for row in rows:
        budget.spend()
        source = row['event_observation']
        support = row.get('observation_support') or {}
        if source['format_id'] != policy['format_id'] or support.get('pipeline_id') != policy['pipeline_id']:
            raise ValueError('daily evidence identity changed')
        saved = _read(db, source['event_id'], source['source_sha256'], policy['pipeline_id'],
                      source['context_id'], {})
        result = saved['result']
        if result.get('state') != 'estimated' or result.get('event_observation') != source:
            raise ValueError('daily evidence unavailable')
        mask = support.get('reader_observed', [])
        if (len(mask) != 6 or any(type(v) is not bool for v in mask)
                or mask[-2:] != [True, True] or observed_rows(result) != mask):
            raise ValueError('daily evidence dial not observed')
        value = number(result['dial_positions'][-2]['position']) * 100
        values.append(value)
    return values


def comparisons(rows, values, allowance, budget):
    ticks = [r['event_observation']['monotonic_us'] for r in rows]
    edges = []
    last_selected = None
    for j, row in enumerate(rows):
        budget.spend()
        # A bounded subset of necessary constraints is conservative: omitted
        # comparisons can only leave the result wider, never remove a path.
        if j != len(rows)-1 and last_selected is not None and ticks[j]-last_selected < 60000000:
            continue
        last_selected = ticks[j]
        source = row['event_observation']
        candidates = {j - 1} if j else set()
        for lag in (60, 300, 900, 1800, 3600):
            i = bisect.bisect_left(ticks, ticks[j] - lag * 1000000)
            if i < j:
                candidates.add(i)
        for i in sorted(candidates):
            budget.spend()
            previous = rows[i]['event_observation']
            if not 0 < ticks[j] - ticks[i] <= 3600000000 or any(
                    source[k] != previous[k] for k in ('camera', 'clock_id', 'context_id', 'format_id')):
                continue
            # Do not infer a revolution of the slower dial or extend the tested scope.
            delta = values[j] - values[i]
            if abs(delta) > 27:
                continue
            edges.append((previous['event_id'], source['event_id'], max(Decimal(0), delta - allowance), delta + allowance))
    return edges


def refine(db, rows, day, zone, document, baseline, policy):
    if not policy:
        return baseline
    fallback = dict(baseline, constraint_basis='saved_readings',
                    empirical_constraints_applied=False, empirical_fallback='unavailable')
    try:
        policy = validate(policy)
        budget = Budget()
        start = next(i for i, r in enumerate(rows) if r['event_observation']['event_id'] == baseline['before']['event_id'])
        if policy.get('elapsed_start_event'):
            earlier = next((i for i,r in enumerate(rows) if r['event_observation']['event_id'] == policy['elapsed_start_event']), start)
            start = min(start, earlier)
        selected = rows[start:]
        dials = document['dials']
        if (len(dials) != 6 or number(dials[-2]['value_per_revolution']) != 1000
                or number(dials[-1]['value_per_revolution']) != 5):
            raise ValueError('daily dial geometry outside reviewed scope')
        with localcontext() as context:
            context.prec = 50
            evidence_rows = [r for r in selected if r['event_observation']['event_id'] >= policy.get('elapsed_start_event', 1)]
            values = evidence(db, evidence_rows, policy, budget)
            edges = comparisons(evidence_rows, values, number(policy['slow_allowance_ft3']), budget)
            if not edges:
                raise ValueError('no compatible empirical comparisons')
            elapsed = None
            origin = next((r for r in selected if r['event_observation']['event_id'] == policy.get('elapsed_start_event')), None)
            if origin is not None:
                source = origin['event_observation']
                seconds = number(selected[-1]['event_observation']['monotonic_us'] - source['monotonic_us']) / 1000000
                elapsed_base = dict(baseline, before=source, after=source, lower='0',
                                    upper=str(seconds * number(document['maximum_rate_per_second'])))
                bounded = _tighten(selected, day, zone, document, elapsed_base, budget,
                                   edges, number(policy['capacity_cfh']) / 3600, elapsed=True)
                elapsed = dict(start=source, through=bounded['through'], lower=bounded['lower'], upper=bounded['upper'])
            # The elapsed result is a separately completed calculation. A day
            # calculation exhausting the remaining budget must not relabel it
            # as a daily result or throw away this independently valid interval.
            try:
                result = _tighten(selected, day, zone, document, baseline, budget,
                                  edges, number(policy['capacity_cfh']) / 3600)
                applied, reason = True, None
            except WorkLimit:
                result, applied, reason = baseline, False, 'work_limit'
        return dict(result, constraint_basis='empirical_dial_and_household_capacity' if applied else 'saved_readings',
                    empirical_constraints_applied=applied, empirical_fallback=reason, accuracy_verified=False,
                    constraint_assumptions=policy, empirical_comparisons=len(edges),
                    unconstrained_lower=baseline['lower'], unconstrained_upper=baseline['upper'],
                    elapsed_range=elapsed, elapsed_unavailable_reason=None if elapsed else 'start_not_in_saved_window')
    except WorkLimit:
        return dict(fallback, empirical_fallback='work_limit')
    except (ValueError, KeyError, TypeError, IndexError, ArithmeticError, sqlite3.Error, StopIteration, AttributeError, RecursionError):
        return fallback
