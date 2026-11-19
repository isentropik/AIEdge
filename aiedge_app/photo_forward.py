"""Carry a reviewed cumulative range forward using source-bound five-foot dial phases."""
import sqlite3
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from time import monotonic

from capture_clock import interval
from daily_constraints import number
from daily_records import daily_records
from event_observation_read import read_batch
from observation_support import observed_rows

TURN = Decimal(5)
CENT = Decimal('.01')
PAGE = 64


def phases(db, rows, policy):
    sources = [r['event_observation'] for r in rows]
    saved = read_batch(db, sources, policy['pipeline_id'])
    for row, source, item in zip(rows, sources, saved, strict=True):
        result = item['result']
        support = row['observation_support']
        if (support['pipeline_id'] != policy['pipeline_id'] or source['format_id'] != policy['format_id']
                or result.get('state') != 'estimated' or result.get('event_observation') != source):
            raise ValueError('photo carry source mismatch')
        mask = observed_rows(result)
        if len(mask) != 6 or mask != support['reader_observed']:
            raise ValueError('photo carry observation mismatch')
        phase = None
        if mask[-1]:
            pos = number(result['dial_positions'][-1]['position'])
            if not 0 <= pos < 10:
                raise ValueError('invalid five-foot position')
            phase = pos * TURN / 10
        yield source, phase


def supported_band(lo, hi, phase, error):
    """Outer bounds over every full-turn count whose phase band intersects [lo, hi]."""
    first = ((lo-phase-error)/TURN).to_integral_value(rounding=ROUND_CEILING)
    last = ((hi-phase+error)/TURN).to_integral_value(rounding=ROUND_FLOOR)
    if first > last:
        raise ValueError('no supported turn count')
    return max(lo, phase+first*TURN-error), min(hi, phase+last*TURN+error)


class PhotoForward:
    def __init__(self):
        self.key = None
        self.cursor = None

    def advance(self, db, document, policy, current, segment, review, photo):
        try:
            return self._advance(db, document, policy, current, segment, review, photo)
        except (ValueError, ArithmeticError, TypeError, KeyError, IndexError, sqlite3.Error):
            self.key = self.cursor = None
            return photo

    def _advance(self, db, document, policy, current, segment, review, photo):
        target = current['through']
        anchor = review['through']
        origin = current['start']
        fine = document['dials'][-1]
        if (document['unit'] != 'ft3' or document['pipeline_id'] != policy['pipeline_id']
                or len(document['dials']) != 6 or fine['index'] != 5 or number(fine['value_per_revolution']) != TURN):
            raise ValueError('unsupported photo carry geometry')
        error = number(fine['position_error']) * TURN / 10
        if not 0 <= error < TURN/2:
            raise ValueError('invalid five-foot tolerance')
        key = (photo['review_sha256'], segment, error)
        if self.key != key or self.cursor is None or self.cursor > target['event_id']:
            readings = []
            for endpoint in (origin, anchor):
                e = endpoint['event_id']
                rows = list(daily_records(db, e, e, segment))
                binding, phase = next(iter(phases(db, rows, policy)), (None, None))
                if len(rows) != 1 or binding != endpoint or phase is None:
                    raise ValueError('reviewed phase unavailable')
                readings.append(phase)
            origin_phase, anchor_phase = readings
            # Absolute phase relative to the origin's revolution. Cancel the shared
            # middle endpoint instead of adding its tolerance on every publication.
            lo, hi = supported_band(origin_phase-error+number(photo['lower']),
                                    origin_phase+error+number(photo['upper']), anchor_phase, error)
            self.origin_phase = origin_phase
            self.point = (anchor, lo, hi)
            self.key, self.cursor = key, anchor['event_id']

        # Resume a bounded prefix on the next publication; never date a partial
        # calculation with the current event's timestamp. Only one page is in flight.
        deadline = monotonic()+1
        for _ in range(16):
            if self.cursor == target['event_id']:
                break
            stop = min(self.cursor+PAGE, target['event_id'])
            rows = list(daily_records(db, self.cursor+1, stop, segment))
            previous, lo, hi = self.point
            for source, phase in phases(db, rows, policy):
                if (source['context_id'] != anchor['context_id'] or
                        interval(previous, source)['state'] != 'continuous'):
                    raise ValueError('incompatible capture source or clock')
                if phase is None:
                    continue
                micros = source['monotonic_us']-previous['monotonic_us']
                capacity = number(policy['capacity_cfh']) * micros / 3600000000
                lo, hi = supported_band(lo, hi+capacity, phase, error)
                previous = source
            self.point, self.cursor = (previous, lo, hi), stop
            if monotonic() >= deadline:
                break
        end, lo, hi = self.point
        if self.cursor != target['event_id'] or end != target:
            return photo
        lower = max(number(photo['lower']), number(current['lower']), lo-self.origin_phase-error)
        upper = min(number(current['upper']), hi-self.origin_phase+error)
        if upper < lower:
            raise ValueError('photo carry outside unresolved bounds')
        return dict(photo, lower=str(lower.quantize(CENT, rounding=ROUND_FLOOR)),
                    upper=str(upper.quantize(CENT, rounding=ROUND_CEILING)),
                    through={k:end[k] for k in ('event_id','captured_at','source_sha256')},
                    unresolved_lower=current['lower'], unresolved_upper=current['upper'],
                    reviewed_through=photo['through'],
                    assumption=photo['assumption']+' Carried forward from reviewed event '+
                               str(anchor['event_id'])+' using saved five-foot dial readings.')
