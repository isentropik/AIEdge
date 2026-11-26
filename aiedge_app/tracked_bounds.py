"""Read-only uncertainty for movement between the Overview's actual fine-dial knots."""
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import sqlite3
from threading import Lock

from capture_clock import interval
from daily_constraints import number
from dial_travel import advance_band, phases
from meter_history import millis
from reading_format import validate


ZERO = Decimal(0)


def cents(bounds):
    return [int((100 * n).to_integral_value(rounding=mode))
            for n, mode in zip(bounds, (ROUND_FLOOR, ROUND_CEILING))]


def seconds(delta):
    return Decimal(delta // timedelta(microseconds=1)) / 1000000


def clock_bridge(db, previous, current, left, right, turn, rate):
    """A UTC-only break needs independent, ordered acquisition envelopes and one lift."""
    old, new = previous['event_id'], current['event_id']
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='continuous_capture_outcomes'").fetchone():
        return None
    rows = db.execute(
        'SELECT a.first_event,a.after_event_id,o.event_id,o.outcome,o.error,a.started_at,o.finished_at '
        'FROM continuous_capture_attempts a LEFT JOIN continuous_capture_outcomes o USING(attempt_id) '
        'WHERE a.after_event_id IN (?,?) ORDER BY a.after_event_id', (old - 1, old)).fetchall()
    if (len(rows) != 2 or rows[0][0] != rows[1][0] or
            any(tuple(row[1:5]) != (eid - 1, eid, 'committed', None) for row, eid in zip(rows, (old, new)))):
        return None
    start, finish, next_start, next_finish = (datetime.fromisoformat(t) for row in rows for t in row[5:])
    a, b = (datetime.fromisoformat(s['captured_at']) for s in (previous, current))
    if not start <= a <= finish <= next_start <= b <= next_finish:
        return None
    outer = seconds(next_finish - start)
    ticks = Decimal(current['monotonic_us'] - previous['monotonic_us']) / 1000000
    if not seconds(next_start - finish) <= ticks <= outer or not 0 < outer < 660:
        return None
    # Overlap permits zero movement. Either adjacent winding must be impossible,
    # even at the upper bound on the elapsed time. Never use capacity as a reading.
    if max(left[0], right[0]) > min(left[1], right[1]) or left[1] + rate * outer >= right[0] + turn:
        return None
    return min(rate * outer, right[1] - left[0])


class Travel:
    """Sum disjoint covered pieces, retaining the phase constraints within each piece."""
    def __init__(self, origin):
        self.origin = self.reach = origin
        self.closed = (ZERO, ZERO)
        self.moved = False

    def bounds(self):
        if not self.moved:
            return self.closed
        return (self.closed[0] + max(ZERO, self.reach[0] - self.origin[1]),
                self.closed[1] + self.reach[1] - self.origin[0])

    def restart(self, phase, bridge):
        lo, hi = self.bounds()
        self.closed = (lo, hi + bridge)
        self.origin = self.reach = phase
        self.moved = False

    def advance(self, phase, turn, limit):
        self.reach = advance_band(self.reach, phase, turn, limit)
        self.moved = True
        return self.reach is not None


class TrackedBounds:
    """Cache immutable full pages of validated phases for one source/day in memory."""
    def __init__(self, store):
        self.store = store
        self.lock = Lock()
        self.key = None
        self.pages = {}
        self.prefixes = {}

    def snapshot(self, usage, document, policy):
        track = usage.get('movement_history') or {}
        state = usage.get('daily_nominal') or {}
        points = track.get('points') or []
        if (not points or not state.get('coverage_started_at') or state.get('method') != 'nominal_meter_movement_v1'
                or not document or document.get('unit') != 'ft3' or not document.get('maximum_rate_per_second')):
            return {}
        first, tail = points[0], points[-1]
        anchor = millis(datetime.fromisoformat(state['coverage_started_at']))
        measured = state['measured_at']
        if (track.get('dial_from') != [first[2], first[0]] or first[0] != anchor or first[1] != 0
                or tail[:3] != [millis(datetime.fromisoformat(measured)), float(state['value_ft3']), state['event_id']]
                or validate(document)[1] != track['format']):
            return {}
        rate = number(document['maximum_rate_per_second'])
        with self.lock, self.store.connect() as db:
            opening = db.execute('SELECT e.camera,f.captured_at,f.sha256 FROM capture_events e '
                                 'JOIN frames f USING(camera,frame_id) WHERE e.event_id=?', (first[2],)).fetchone()
            if not opening or opening[1] != state['coverage_started_at']:
                return {}
            key = (track['midnight'], track['format'], first[2], *opening, rate)
            if self.key != key:
                self.key, self.pages, self.prefixes = key, {}, {}
            head = db.execute('SELECT e.camera,f.captured_at,f.sha256 FROM capture_events e '
                              'JOIN frames f USING(camera,frame_id) WHERE e.event_id=?', (tail[2],)).fetchone()
            if head and tuple(head) != (opening[0], measured, state['source_sha256']):
                return {}
            edges, joins, partials = self.replay(db, document, track, opening[0], rate)
            for edge, obs, closing in partials:
                try:
                    knot = self.prefix_knot(document, state, track, obs)
                except (sqlite3.Error, KeyError, ValueError, TypeError, ArithmeticError):
                    # A legacy store may lack inputs to reconstruct an extra nominal point.
                    continue
                if knot is not None and knot[1] <= closing[1]:
                    edges.append(dict(edge, point=knot, until=[closing[2], closing[0]]))
            edges.sort(key=lambda edge: edge['end'][0])
        return dict(format=track['format'], midnight=track['midnight'], anchor=track['dial_from'],
                    event=state['event_id'], measured_at=measured, digest=state['source_sha256'],
                    edges=edges, joins=joins)

    def prefix_knot(self, document, state, track, obs):
        """Recover an unarchived last usable knot with the publisher's own nominal replay."""
        from optical_daily import replay
        eid = obs['event_id']
        prior = [p for p in track['points'] if p[2] < eid]
        stamp = millis(datetime.fromisoformat(obs['captured_at']))
        gaps = [g for g in track['dial_gaps'] if g[1] <= stamp]
        key = (eid, obs['source_sha256'], tuple(map(tuple, prior)), tuple(map(tuple, gaps)))
        if key in self.prefixes:
            return self.prefixes[key]
        record = None
        cursor = -1
        while cursor < eid:
            record = replay(record, None, date.fromisoformat(state['day']), state['timezone'],
                            self.store, document, obs)
            if not record or record['movement']['optical_cursor'] <= cursor:
                return None
            cursor = record['movement']['optical_cursor']
        recovered = record['movement']
        last = recovered['points'][-1]
        if (recovered['points'][:-1] != prior or recovered['dial_gaps'] != gaps
                or last[2] != eid or last[0] != stamp or record['state']['source_sha256'] != obs['source_sha256']):
            return None
        self.prefixes[key] = last
        return last

    def samples(self, db, document, source, start, end):
        for lo in range(start, end + 1, 64):
            hi = min(lo + 63, end)
            page = self.pages.get(lo)
            if page is None:
                page = phases(db, lo, hi, document, source, same_clock=False)
                if len(page) == 64:
                    self.pages[lo] = page
            yield from sorted((eid, sample) for eid, sample in page.items() if eid <= hi)

    def replay(self, db, document, track, camera, rate):
        points = track['points']
        start, end = points[0][2], points[-1][2]
        turn = min(number(d['value_per_revolution']) for d in document['dials'])
        source = dict(camera=camera, format_id=track['format'])
        knots = {p[2]: p for p in points}
        closes = {a[2]: b for a, b in zip(points, points[1:])}
        gaps = {tuple(g) for g in track['dial_gaps']}
        failures = {r[0]+1 for r in db.execute('SELECT after_event_id FROM capture_failure_boundaries '
                                              'WHERE after_event_id BETWEEN ? AND ?', (start, end-1))}
        failures.update(r[0] for r in db.execute('SELECT first_event FROM consumption_segment_links '
                                               'WHERE first_event BETWEEN ? AND ?', (start+1, end)))
        total = piece = previous = origin = None
        edges, joins, partials = [], [], {}
        for eid, (obs, phase) in self.samples(db, document, source, start, end):
            stamp = millis(datetime.fromisoformat(obs['captured_at']))
            if previous is not None:
                old, old_phase, at = previous
                gap = at < stamp and any(left <= at and stamp <= right for left, right in gaps)
                adjacent = eid == old['event_id']+1 and obs['context_id'] == old['context_id'] and eid not in failures
                clock = interval(old, obs)
                bridge = None
                if (at, stamp) in gaps and adjacent and clock['reason'] == 'capture_clock_utc_discontinuity':
                    bridge = clock_bridge(db, old, obs, old_phase, phase, turn, rate)
                    if bridge is not None:
                        joins.append([at, stamp])
                for target in (total, piece):
                    if target is None:
                        continue
                    if gap:
                        target.restart(phase, bridge or ZERO)
                    elif not (adjacent and clock['state'] == 'continuous' and clock['elapsed_seconds'] < 660
                              and target.advance(phase, turn, rate * (obs['monotonic_us']-old['monotonic_us']) / 1000000)):
                        if target is total:
                            total = None
                        else:
                            piece = None
            closing = closes.get(origin[0]) if origin else None
            if closing and eid <= closing[2] and piece is not None:
                edge = dict(start=origin, end=[eid, stamp], use=cents(piece.bounds()),
                            total=cents(total.bounds()) if total is not None else None)
                if eid < closing[2]:
                    partials[origin[0]] = (edge, obs, closing)
                elif closing[0] == stamp:
                    edges.append(edge)
                    partials.pop(origin[0], None)
            if eid in knots and knots[eid][0] == stamp:
                if eid == start:
                    total = Travel(phase)
                origin, piece = [eid, stamp], Travel(phase)
            previous = obs, phase, stamp
        return edges, joins, list(partials.values())
