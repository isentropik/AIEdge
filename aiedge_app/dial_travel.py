"""Read measured fine-dial phases from immutable capture/recognition bindings."""
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from daily_constraints import number
from event_observation_read import read_batch
from observation_support import observed_rows


def phases(db, start, end, document, source):
    dial = min(document['dials'], key=lambda d: d['value_per_revolution'])
    turn = number(dial['value_per_revolution'])
    if 'position_error' not in dial or 'index' not in dial:
        return {}
    error = number(dial['position_error']) * turn / 10
    pipeline = document['pipeline_id']
    index = dial['index']
    if not 0 <= error < turn / 4 or not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='event_recognition_bindings'").fetchone():
        return {}
    result = {}
    for lo in range(start, end + 1, 64):
        refs = [dict(event_id=e, source_sha256=sha, context_id=ctx)
                for e, sha, ctx in db.execute(
                    'SELECT event_id,source_sha,context FROM event_recognition_bindings '
                    'WHERE pipeline=? AND event_id BETWEEN ? AND ? ORDER BY event_id',
                    (pipeline, lo, min(end, lo + 63)))]
        if not refs or len({r['event_id'] for r in refs}) != len(refs):
            continue
        try:
            readings = read_batch(db, refs, pipeline)
            for item in readings:
                r = item['result']
                if r.get('state') != 'estimated':
                    continue
                obs = r['event_observation']
                if any(obs.get(k) != source[k] for k in ('camera','format_id','clock_id')):
                    continue
                mask = observed_rows(r)
                if len(mask) != len(document['dials']) or not mask[index]:
                    continue
                middle = number(r['dial_positions'][index]['position']) * turn / 10
                result[obs['event_id']] = (obs, (middle-error, middle+error))
        except (ValueError, ArithmeticError, KeyError, TypeError, IndexError):
            continue
    return result


def advance_band(previous, measured, turn, limit):
    """Outer hull of ALL nondecreasing, rate-admissible lifts of a modulo dial."""
    a,b = previous
    c,d = measured
    first = ((a-d)/turn).to_integral_value(rounding=ROUND_CEILING)
    last = ((b+limit-c)/turn).to_integral_value(rounding=ROUND_FLOOR)
    if first <= last:
        return max(a,c+first*turn), min(b+limit,d+last*turn)


def tail_edges(rows, document, rate, read):
    """Project observed phases after the last temporal register onto elapsed usage."""
    from daily_constraints import bands, merge, supported
    modulus = number(document['dials'][0]['value_per_revolution'])
    # Identify the first absolute turn assignment that cannot follow the
    # earlier register. A later temporal reading can inherit that assignment.
    reachable = [(Decimal(0), modulus)]
    prior_tick = None
    anchor = None
    for record in rows:
        tick = record['event_observation']['monotonic_us']
        if prior_tick is not None:
            allowance = rate * (tick - prior_tick) / 1000000
            reachable = merge((lo, min(modulus, hi + allowance)) for lo, hi in reachable)
        prior_tick = tick
        intervals = bands(record, modulus)
        if intervals:
            reachable = supported(intervals, reachable, Decimal(0), Decimal(0))
            if not reachable:
                break
            if record['absolute']['provenance'] == 'temporal_consumption_bounds':
                anchor = record
    else:
        return []
    if not anchor:
        return []
    first,end = anchor['event_id'],rows[-1]['event_id']
    if not 0 < end-first <= 4096:
        return []
    src = anchor['event_observation']
    values = read(first,end,document,src)
    if first not in values or values[first][0] != src:
        return []
    turn = min(number(d['value_per_revolution']) for d in document['dials'])
    prior, origin = values[first]
    reachable = origin
    accepted = {r['event_id']:r['event_observation'] for r in rows if r['event_id']>first}
    edges = []
    for event,(obs,measured) in sorted(values.items()):
        if event == first:
            continue
        if any(obs[k] != prior[k] for k in ('camera','format_id','context_id','clock_id')):
            break
        ticks = obs['monotonic_us']-prior['monotonic_us']
        elapsed = datetime.fromisoformat(obs['captured_at'])-datetime.fromisoformat(prior['captured_at'])
        if ticks<=0 or elapsed.total_seconds()<=0:
            break
        # Across missing captures every turn allowed by elapsed time remains possible.
        reachable = advance_band(reachable, measured, turn, rate*Decimal(ticks)/1000000)
        if reachable is None:
            return []
        if accepted.get(event) == obs:
            edges.append((first,event,max(Decimal(0),reachable[0]-origin[1]),reachable[1]-origin[0]))
        prior = obs
    return edges if edges and edges[-1][1] == end else []
