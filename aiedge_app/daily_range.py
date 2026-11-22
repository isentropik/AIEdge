"""Bound calendar-day usage from ordered ledger records without assigning a midnight reading."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from daily_constraints import InconsistentConstraints, bands, merge, register_bands, supported


COARSE_BASIS = "coarse_register_after_turn_conflict"


class ReadingConflict(InconsistentConstraints):
    """A particular observation made the sequential constraints incompatible."""
    def __init__(self, message, event_id):
        super().__init__(message)
        self.event_id = event_id


def number(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("nonfinite measurement")
    return result


def absolute(record, modulus):
    native = record.get("absolute") or {}
    bounds = native.get("bounds") or {}
    if (native.get("provenance") != "temporal_consumption_bounds" or native.get("unit") != "ft3"
            or bounds.get("state") != "bounded" or bounds.get("wraps_register") is not False):
        return None
    bands = [(number(b["lower"]), number(b["upper"])) for b in bounds["ranges"]]
    if not bands or any(not 0 <= lo <= hi < modulus for lo, hi in bands):
        raise ValueError("invalid register envelope")
    return min(lo for lo, hi in bands), max(hi for lo, hi in bands)


def _legacy_range(records, day, zone, document, revision, contexts=None, *, coarse=False, rate_ceiling=None):
    midnight = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
    tomorrow = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    rate = number(document["maximum_rate_per_second"])
    if rate_ceiling is not None:
        rate = min(rate, number(rate_ceiling))
    modulus = number(document["dials"][0]["value_per_revolution"])
    if document["unit"] != "ft3" or rate <= 0 or modulus <= 0:
        raise ValueError("unsupported meter")
    before = after = end = None
    usage_low = usage_high = Decimal(0)
    segment = None
    post_midnight = False
    for record in records:
        source = record["event_observation"]
        stamp = datetime.fromisoformat(source["captured_at"])
        if stamp.utcoffset() is None:
            raise ValueError("missing time zone")
        if stamp >= tomorrow or stamp < midnight - timedelta(days=1):
            if before is not None:
                raise ValueError("record outside requested period")
            continue
        envelope = absolute(record, modulus)
        if coarse and envelope is not None:
            buckets = register_bands(record, modulus, ())
            envelope = buckets[0][0], buckets[-1][1]
        identity = tuple(source[k] for k in ("camera", "clock_id", "format_id"))
        context = source["context_id"]
        if contexts is not None:
            saved = contexts.get(context)
            if (saved is None or saved[:2] != (document["pipeline_id"], revision)
                    or type(saved[2]) is not int or not 1 <= saved[2] <= source["event_id"]):
                raise ValueError("unverified reading context")
        if post_midnight and stamp <= previous_stamp:
            raise ValueError("unordered measurement")
        if stamp <= midnight and envelope is not None:
            before = source
            start_identity = identity
            start_context = context
            midnight_min, high = envelope
            low = midnight_min
            previous = source
            previous_stamp = stamp
            after = end = None
        if stamp < midnight:
            continue
        if before is None:
            continue
        if (identity != start_identity or (contexts is None and context != start_context)
                or source["format_id"] != revision
                or record["unit"] != document["unit"] or stamp < previous_stamp):
            raise ValueError("source changed")
        elapsed = source["monotonic_us"] - previous["monotonic_us"]
        if source is not before and (elapsed <= 0 or stamp <= previous_stamp):
            raise ValueError("unordered measurement")
        high += elapsed * rate / 1000000
        if high >= modulus:
            raise ValueError("possible register rollover")
        if envelope is not None:
            low = max(low, envelope[0])
            high = min(high, envelope[1])
        if low > high:
            raise ReadingConflict("inconsistent meter readings", source["event_id"])
        step_limit = elapsed * rate / 1000000
        usage_high += step_limit
        if record.get("upper_unbounded") is False:
            lo, hi = number(record["minimum"]), number(record["maximum"])
            anchor = (context, record["segment_id"], record["anchor_captured_at"])
            if not 0 <= lo <= hi:
                raise ValueError("invalid segment envelope")
            if anchor != segment:
                # Each delta starts at a measured endpoint. Gaps keep their rate allowance.
                segment = anchor
                initial_lo, initial_hi = lo, hi
                base_low, base_high = usage_low, usage_high
            usage_low = max(usage_low, base_low + lo - initial_hi)
            usage_high = min(usage_high, base_high + hi - initial_lo)
        post_midnight = True
        previous, previous_stamp = source, stamp
        if stamp >= midnight:
            if after is None:
                after = source
                midnight_max = high
            end = source
    if end is None:
        raise ValueError("midnight lacks bracketing evidence")
    usage_low = max(usage_low, low - midnight_max)
    usage_high = min(usage_high, high - midnight_min)
    if usage_low > usage_high:
        raise InconsistentConstraints("inconsistent daily bounds")
    return {"day": day.isoformat(), "before": before, "after": after, "through": end, "segment_id": record.get("segment_id"),
            "lower": str(usage_low.quantize(Decimal(".01"), rounding=ROUND_FLOOR)),
            "upper": str(usage_high.quantize(Decimal(".01"), rounding=ROUND_CEILING))}






def _phases(intervals, turn):
    """Project disjoint register intervals onto one revolution without choosing a turn."""
    pieces = []
    for lo, hi in intervals:
        width = hi - lo
        if width >= turn:
            return [(Decimal(0), turn)]
        start = lo % turn
        end = start + width
        if end >= turn:
            pieces.extend(((start, turn), (Decimal(0), end - turn)))
        else:
            pieces.append((start, end))
    return merge(pieces)


def _possible_turns(values, buckets, turn, budget):
    """Repeat the measured phases only inside the supported register buckets."""
    from daily_constraints import MAX_BANDS, WorkLimit
    phases = _phases(values, turn)
    if phases == [(Decimal(0), turn)]:
        return buckets
    alternatives = []
    for lower, upper in buckets:
        count = int((upper - lower) // turn) + 1
        if count * len(phases) > 4 * MAX_BANDS:
            raise WorkLimit()
        budget.spend(count * len(phases))
        for index in range(count):
            start = lower + index * turn
            for lo, hi in phases:
                if start + lo <= upper:
                    alternatives.append((start + lo, min(start + hi, upper)))
    return merge(alternatives)


def _check_turn_continuity(records, first, modulus, turn, rate, budget):
    """Keep compatible register and phase alternatives together across each gap."""
    reachable = [(Decimal(0), modulus)]
    prior_tick = None
    earliest_bucket = 0
    anchors = {}
    for record in records:
        obs = record["event_observation"]
        if obs["event_id"] < first:
            continue
        budget.spend()
        tick = obs["monotonic_us"]
        if prior_tick is not None:
            step = rate * (tick - prior_tick) / 1000000
            reachable = merge((lo, min(modulus, hi + step)) for lo, hi in reachable)
        absolute_bounds = (record.get("absolute") or {}).get("bounds") or {}
        if absolute_bounds.get("wraps_register") is True:
            raise ValueError("possible register rollover during daily recovery")
        values = bands(record, modulus)
        if values is not None:
            # A hundred bucket is half-open. Two successive buckets that touch
            # at just one endpoint cannot justify a backward register movement.
            for lo, hi in values:
                if hi // 100 >= earliest_bucket:
                    earliest_bucket = max(earliest_bucket, lo // 100)
                    break
            else:
                raise ReadingConflict("coarse register moved backwards", obs["event_id"])
            buckets = register_bands(record, modulus, ())
            measured = _possible_turns(values, buckets, turn, budget)
            reachable = supported(measured, reachable, Decimal(0), Decimal(0))
        anchor = record.get("observation_full_anchor_event_id")
        if anchor == obs["event_id"]:
            anchors[anchor] = reachable
        if anchor in anchors and record.get("upper_unbounded") is False:
            lower, upper = number(record["minimum"]), number(record["maximum"])
            reachable = supported(reachable, anchors[anchor], lower, upper)
        if not reachable:
            raise ReadingConflict("finest dial positions conflict even without turn counts", obs["event_id"])
        prior_tick = tick


def daily_range(records, day, zone, document, revision, contexts=None, *, recovery_capacity_cfh=None, read_phases=None):
    from itertools import islice
    from daily_constraints import MAX_RECORDS, tighten
    rows = list(islice(records, MAX_RECORDS + 1))
    if len(rows) > MAX_RECORDS:
        raise ValueError("daily input limit exceeded")
    try:
        baseline = _legacy_range(rows, day, zone, document, revision, contexts)
        return tighten(rows, day, zone, document, baseline)
    except InconsistentConstraints:
        periods = [number(d["value_per_revolution"]) for d in document["dials"]]
        if document["unit"] != "ft3" or len(periods) != 6 or periods[-2:] != [1000, 5]:
            raise

    from daily_constraints import Budget, WorkLimit, _tighten
    with localcontext() as context:
        context.prec = 50
        budget = Budget()
        rate = number(document["maximum_rate_per_second"])
        if recovery_capacity_cfh is not None:
            rate = min(rate, number(recovery_capacity_cfh) / 3600)
        try:
            baseline = _legacy_range(rows, day, zone, document, revision, contexts,
                                     coarse=True, rate_ceiling=rate)
            recovered = _tighten(rows, day, zone, document, baseline, budget,
                                 rate_ceiling=rate, fine_endpoints=())
            _check_turn_continuity(rows, recovered["before"]["event_id"], periods[0],
                                   periods[-1], rate, budget)
            if read_phases is not None:
                from dial_travel import tail_edges
                edges = tail_edges(rows, document, rate, read_phases)
                if edges:
                    anchor_event = edges[0][0]
                    temporal = {r['event_id'] for r in rows if r['event_id'] <= anchor_event
                                and (r.get('absolute') or {}).get('provenance') == 'temporal_consumption_bounds'}
                    # An isolated single-image turn assignment can be ambiguous near zero.
                    # Keep the temporal readings and all rate-admissible turns in the tail.
                    try:
                        recovered = _tighten(rows, day, zone, document, recovered, budget,
                                             rate_ceiling=rate, fine_endpoints=temporal, extra_edges=edges)
                    except (InconsistentConstraints, WorkLimit):
                        pass
        except WorkLimit as exc:
            raise ValueError("daily register recovery work limit") from exc
    return dict(recovered, constraint_basis=COARSE_BASIS, unknown_gaps_preserved=True,
                register_resolution_ft3=100, maximum_rate_per_second=str(rate))
