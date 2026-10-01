"""Display feasible register intervals; never choose a total or count turns.

Intersect each dial's periodic error band over one full register revolution.
This supplements the native ambiguous result, which can stop before checking
the larger dials. All bands must agree before a range is shown. Work is bounded
even when the configured periods allow millions of aliases.
"""
import math
from decimal import Decimal, localcontext, ROUND_CEILING, ROUND_FLOOR


MAX_RANGES = 256
MAX_INTERSECTIONS = 4096


def diagnose_inconsistency(document, positions):
    """Reduce a conflicting group without dropping any dial from the reading.

    A group is not a diagnosis of which individual estimate is wrong. Resource
    limits retain the unchecked constraint and are explicit in the result.
    Inputs have already passed format and inference validation.
    """
    dials=document['dials']
    def check(indices):
        return feasible_ranges([dials[i]['value_per_revolution'] for i in indices],
                               [positions[i] for i in indices],
                               [dials[i]['position_error'] for i in indices])
    remaining=list(range(len(dials)))
    if check(remaining)['state']!='inconsistent':return {'state':'not_inconsistent'}
    limited=[]
    for index in list(remaining):
        trial=[i for i in remaining if i!=index]
        if not trial:continue
        state=check(trial)['state']
        if state=='inconsistent':remaining=trial
        elif state=='unavailable':limited.append(dials[index]['index'])
    return {'state':'inconsistent','dial_indices':[dials[i]['index'] for i in remaining],
            'reduction_limited_indices':limited,'assumption':'configured_dial_tolerances',
            'individual_cause_identified':False,'accuracy_verified':False,'training_allowed':False}


def feasible_ranges(scales, positions, errors):
    """Validated inputs only. Bounds depend on assumed errors, not accuracy."""
    with localcontext() as context:
        context.prec = 340
        periods = [Decimal(str(scale)) for scale in scales]
        intervals = [(Decimal(0), periods[0])]
        work = 0
        for period, position, error in zip(periods, positions, errors):
            phase = Decimal(str(position)) * period / 10
            # Same numerical slack as the native reader, separate from the
            # configured tolerance. Decimal keeps small bands at large totals.
            radius = (Decimal(str(error)) / 10 + Decimal('1e-12')) * period
            pieces = []
            for lower, upper in intervals:
                first = int(((lower - phase - radius) / period).to_integral_value(rounding=ROUND_CEILING))
                last = int(((upper - phase + radius) / period).to_integral_value(rounding=ROUND_FLOOR))
                count = max(0, last - first + 1)
                if work + count > MAX_INTERSECTIONS:
                    return {'state': 'unavailable', 'reason': 'range_limit'}
                work += count
                for turn in range(first, last + 1):
                    centre = phase + turn * period
                    lo, hi = max(lower, centre - radius), min(upper, centre + radius)
                    if lo <= hi:
                        # Adjacent/overlapping intervals form one band. Inputs
                        # and turn offsets are traversed in ascending order.
                        if pieces and lo <= pieces[-1][1]:
                            pieces[-1] = (pieces[-1][0], max(hi, pieces[-1][1]))
                        else:
                            pieces.append((lo, hi))
                            if len(pieces) > MAX_RANGES:
                                return {'state': 'unavailable', 'reason': 'range_limit'}
            intervals = pieces
            if not intervals:
                return {'state': 'inconsistent', 'reason': 'dial_bounds_disagree'}
        # The point at period is the same point as zero, not another reading.
        intervals = [(lo, hi) for lo, hi in intervals if lo < periods[0]]
        if not intervals:
            return {'state': 'inconsistent', 'reason': 'dial_bounds_disagree'}
        return {'state': 'bounded', 'intervals': intervals,
                'wraps_register': len(intervals) > 1 and intervals[0][0] == 0 and intervals[-1][1] == periods[0]}


def display_bounds(document, positions):
    dials = document['dials']
    scales = [dial['value_per_revolution'] for dial in dials]
    errors = [dial['position_error'] for dial in dials]
    result = feasible_ranges(scales, positions, errors)
    if result['state'] != 'bounded':
        return result
    return format_bounds(document, result)


def format_bounds(document, result):
    """Present exact intervals with outward rounding; does not select a value."""
    scales = [dial['value_per_revolution'] for dial in document['dials']]
    errors = [dial['position_error'] for dial in document['dials']]
    # Outward rounding: a display label must not exclude possible values, or
    # turn the upper register boundary into zero as scalar formatting does.
    resolution = max(scales[-1] / 360, scales[-1] * errors[-1] / 10)
    exponent = max(-12, math.floor(math.log10(resolution)))
    width = max(1, math.ceil(math.log10(scales[0])))
    def endpoint(value, upper):
        with localcontext() as context:
            context.prec = 340
            rounded = value.quantize(Decimal(1).scaleb(exponent), rounding=ROUND_CEILING if upper else ROUND_FLOOR)
            text = format(rounded, f'.{max(0, -exponent)}f')
        integer, separator, fraction = text.partition('.')
        number = float(value)
        # JSON floats must enclose the exact decimal endpoints too.
        if (Decimal.from_float(number) < value if upper else Decimal.from_float(number) > value):
            number = math.nextafter(number, math.inf if upper else -math.inf)
        return number, integer.zfill(width) + separator + fraction
    rows = []
    for lower, upper in result['intervals']:
        lo, lo_text = endpoint(lower, False)
        hi, hi_text = endpoint(upper, True)
        rows.append({'lower': lo, 'upper': hi, 'lower_text': lo_text, 'upper_text': hi_text})
    integers=[row[key].split('.')[0] for row in rows for key in ('lower_text','upper_text')]
    prefix=integers[0] if integers else ''
    for integer in integers[1:]:
        while prefix and not integer.startswith(prefix):prefix=prefix[:-1]
    # A rollover boundary has a different digit count. Do not report its
    # apparent textual prefix as shared register digits.
    if result.get('wraps_register') or any(len(integer)!=width for integer in integers):prefix=''
    return {**{key:value for key,value in result.items() if key!='intervals'},
            'ranges': rows, 'assumption': 'configured_dial_tolerances',
            'common_integer_prefix':prefix,
            'accuracy_verified': False, 'training_allowed': False}
