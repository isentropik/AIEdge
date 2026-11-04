"""Bound calendar-day usage from ordered ledger records without assigning a midnight reading."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


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


def daily_range(records, day, zone, document, revision):
    midnight = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
    tomorrow = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    rate = number(document["maximum_rate_per_second"])
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
        identity = tuple(source[k] for k in ("camera", "clock_id", "format_id", "context_id"))
        if post_midnight and stamp <= previous_stamp:
            raise ValueError("unordered measurement")
        if stamp <= midnight and envelope is not None:
            before = source
            start_identity = identity
            midnight_min, high = envelope
            low = midnight_min
            previous = source
            previous_stamp = stamp
            after = end = None
        if stamp < midnight:
            continue
        if before is None:
            continue
        if (identity != start_identity or source["format_id"] != revision
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
            raise ValueError("inconsistent meter readings")
        step_limit = elapsed * rate / 1000000
        usage_high += step_limit
        if record.get("upper_unbounded") is False:
            lo, hi = number(record["minimum"]), number(record["maximum"])
            anchor = (record["segment_id"], record["anchor_captured_at"])
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
        raise ValueError("inconsistent daily bounds")
    return {"day": day.isoformat(), "before": before, "after": after, "through": end, "segment_id": record.get("segment_id"),
            "lower": str(usage_low.quantize(Decimal(".01"), rounding=ROUND_FLOOR)),
            "upper": str(usage_high.quantize(Decimal(".01"), rounding=ROUND_CEILING))}



