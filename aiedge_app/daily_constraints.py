"""Conservative full-day constraints. Pure saved-data analysis; no ledger writes.

Bands are alternatives, not probabilities. Arc consistency can leave infeasible
combinations, so the returned interval is an OUTER bound, never an exact path.
Gaps receive only nonnegative/configured-rate constraints, never invented deltas.
"""
from collections import deque
from datetime import datetime, time, timezone
from decimal import Decimal, localcontext, ROUND_FLOOR, ROUND_CEILING
from time import monotonic

MAX_RECORDS = 32769  # The publisher's inclusive existing ledger window.
MAX_BANDS = 64
MAX_WORK = 20000000
MAX_SECONDS = 8


class WorkLimit(Exception):
    """Leave the already validated wider result unchanged; no partial result."""


class Budget:
    def __init__(self):
        self.work = 0
        self.deadline = monotonic() + MAX_SECONDS

    def spend(self, count=1):
        self.work += count
        if self.work > MAX_WORK or monotonic() > self.deadline:
            raise WorkLimit()


def number(value):
    value = Decimal(str(value))
    if not value.is_finite():
        raise ValueError("nonfinite daily constraint")
    return value


def merge(bands):
    result = []
    for lo, hi in sorted(bands):
        if result and lo <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], hi))
        else:
            result.append((lo, hi))
    return result


def bands(record, modulus):
    absolute = record.get("absolute") or {}
    bounds = absolute.get("bounds") or {}
    if (absolute.get("unit") != "ft3"
            or absolute.get("provenance") not in ("single_image", "temporal_consumption_bounds")
            or bounds.get("state") != "bounded" or bounds.get("wraps_register") is not False):
        return None
    values = bounds["ranges"]
    if len(values) > MAX_BANDS:
        raise WorkLimit()
    values = [(number(v["lower"]), number(v["upper"])) for v in values]
    if not values or any(not 0 <= lo <= hi < modulus for lo, hi in values):
        raise ValueError("invalid daily constraint bands")
    return merge(values)


def propagate(domains, edges, links, budget):
    # Nested lists are never mutated. Branches share immutable Decimal tuples.
    domains = list(domains)
    queue = deque(range(len(edges)))
    queued = set(queue)
    while queue:
        edge = queue.popleft()
        queued.discard(edge)
        i, j, lo, hi = edges[edge]
        for target, source, lower, upper in ((j, i, lo, hi), (i, j, -hi, -lo)):
            budget.spend(len(domains[target]) * len(domains[source]))
            values = []
            for a, b in domains[target]:
                for x, y in domains[source]:
                    left, right = max(a, x + lower), min(b, y + upper)
                    if left <= right:
                        values.append((left, right))
            values = merge(values)
            if not values:
                return None
            if len(values) > MAX_BANDS:
                raise WorkLimit()
            if values != domains[target]:
                domains[target] = values
                for neighbor in links[target]:
                    if neighbor not in queued:
                        queue.append(neighbor)
                        queued.add(neighbor)
    return domains


def tighten(records, day, zone, document, baseline):
    """Intersect a validated daily result with full-day necessary constraints.

The caller first runs the original identity/context/clock/rollover validation.
No rate is inferred from household capacity or appliance activity. No slow-dial
movement tolerance is introduced. On bounded-work exhaustion use baseline.
"""
    try:
        with localcontext() as context:
            context.prec = 50
            return _tighten(records, day, zone, document, baseline, Budget())
    except WorkLimit:
        return baseline


def _tighten(records, day, zone, document, baseline, budget, extra_edges=(), rate_ceiling=None, elapsed=False):
    if len(records) > MAX_RECORDS:
        raise WorkLimit()
    midnight = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
    start = next(i for i, r in enumerate(records)
                 if r["event_observation"]["event_id"] == baseline["before"]["event_id"])
    records = records[start:]
    modulus = number(document["dials"][0]["value_per_revolution"])
    rate = number(document["maximum_rate_per_second"])
    if rate_ceiling is not None:
        rate = min(rate, number(rate_ceiling))
        if rate <= 0:
            raise ValueError("invalid daily capacity")
    domains, edges, index = [], [], {}
    before = after = 0 if elapsed else None
    previous = None
    for i, record in enumerate(records):
        budget.spend()
        source = record["event_observation"]
        event = source["event_id"]
        stamp = datetime.fromisoformat(source["captured_at"])
        if (type(event) is not int or event <= 0 or event in index or record["unit"] != "ft3"
                or type(source["monotonic_us"]) is not int):
            raise ValueError("invalid daily constraint source")
        if previous:
            interval_us = source["monotonic_us"] - previous["monotonic_us"]
            if (interval_us <= 0 or event <= previous["event_id"]
                    or stamp <= datetime.fromisoformat(previous["captured_at"])
                    or any(source[k] != previous[k] for k in ("camera", "clock_id", "format_id"))):
                raise ValueError("unordered daily constraint source")
            edges.append((i - 1, i, Decimal(0), interval_us * rate / 1000000))
        values = bands(record, modulus)
        domains.append(values if values is not None else [(Decimal(0), modulus)])
        if not elapsed and stamp <= midnight and values is not None:
            before = i
        if not elapsed and stamp >= midnight and after is None:
            after = i
        index[event] = i
        previous = source
    if before is None or after is None:
        raise ValueError("midnight lacks constraint bracket")
    for i, record in enumerate(records):
        anchor = record.get("observation_full_anchor_event_id")
        if record.get("upper_unbounded") is False and anchor is not None:
            if type(anchor) is not int or anchor > record["event_observation"]["event_id"]:
                raise ValueError("invalid daily constraint anchor")
            if anchor in index:
                lo, hi = number(record["minimum"]), number(record["maximum"])
                if not 0 <= lo <= hi:
                    raise ValueError("invalid daily constraint delta")
                if record["anchor_captured_at"] != records[index[anchor]]["event_observation"]["captured_at"]:
                    raise ValueError("daily anchor timestamp mismatch")
                edges.append((index[anchor], i, lo, hi))
    for left, right, lo, hi in extra_edges:
        budget.spend()
        if left in index and right in index:
            lo, hi = number(lo), number(hi)
            if index[left] >= index[right] or not 0 <= lo <= hi:
                raise ValueError("invalid supplementary daily constraint")
            edges.append((index[left], index[right], lo, hi))
    mid, end = len(domains), len(domains) - 1
    domains.append([(Decimal(0), modulus)])
    # Midnight is anywhere between its bracketing measurements, not interpolated.
    edges.extend(((before, mid, Decimal(0), modulus), (mid, after, Decimal(0), modulus)))
    links = [[] for _ in domains]
    for k, (i, j, _, _) in enumerate(edges):
        links[i].append(k)
        links[j].append(k)
    base = propagate(domains, edges, links, budget)
    if base is None:
        raise ValueError("inconsistent full-day constraints")
    limits = []
    # Enumerate every surviving pre-midnight band. Never select a likely band.
    # This exposes correlations that taking only the global min/max loses.
    for band in base[before]:
        branch = list(base)
        branch[before] = [band]
        result = propagate(branch, edges, links, budget)
        if result is not None:
            limits.append((result[end][0][0] - result[mid][-1][1],
                           result[end][-1][1] - result[mid][0][0]))
    if not limits:
        raise ValueError("inconsistent full-day alternatives")
    lower = max(number(baseline["lower"]), min(lo for lo, _ in limits), Decimal(0))
    upper = min(number(baseline["upper"]), max(hi for _, hi in limits))
    if lower > upper:
        raise ValueError("inconsistent full-day range")
    return dict(baseline, before=records[before]["event_observation"],
                after=records[after]["event_observation"],
                lower=str(lower.quantize(Decimal(".01"), rounding=ROUND_FLOOR)),
                upper=str(upper.quantize(Decimal(".01"), rounding=ROUND_CEILING)))
