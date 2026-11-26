"""Reconstruct register bounds from a verified full observation and contiguous fine-dial phases."""
from capture_clock import interval
from daily_constraints import number, supported
from dial_travel import advance_band, full_bands, phases
from event_observation_read import read_batch
from observation_support import observed_rows

# Keep replay off the acquisition path. A publication reads at most this many
# historical exposures and saves its cursor in the same checkpoint as the meter.
PAGE = 64


def seed(db, doc, identity, originals=None):
    event, digest, stamp = identity
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='event_recognition_bindings'").fetchone():
        return None
    refs = db.execute('SELECT context FROM event_recognition_bindings '
                      'WHERE event_id=? AND source_sha=? AND pipeline=?',
                      (event, digest, doc['pipeline_id'])).fetchall()
    if len(refs) != 1:
        return None
    ref = dict(event_id=event, source_sha256=digest, context_id=refs[0][0])
    inf = read_batch(db, [ref], doc['pipeline_id'])[0]['result']
    source = inf.get('event_observation')
    if (inf.get('state') != 'estimated' or not source or source['captured_at'] != stamp
            or source['source_sha256'] != digest or source['event_id'] != event):
        return None
    from reading_format import validate
    if source['format_id'] != validate(doc)[1]:
        return None
    dials = doc['dials']
    bands = full_bands(inf, doc) if observed_rows(inf) == [True] * len(dials) else []
    if not bands and originals:
        sample = phases(db, event, event, doc, source).get(event)
        bands = originals.read_bands(doc, source, sample[1]) if sample and sample[0] == source else None
    if bands:
        return source, (bands[0][0], bands[-1][1])


def slow_reference(outer, phase, tick):
    return dict(base=list(map(str,outer)), origin=list(map(str,phase)), phase=list(map(str,phase)), tick=tick)


def page(db, doc, source, outer, target, rate, slow=None):
    """Return only the verified prefix, stopping before a missing or discontinuous link."""
    start = source['event_id'] + 1
    stop = min(target, start + PAGE - 1)
    if stop < start:
        return []
    cut = db.execute('SELECT MIN(e) FROM (SELECT after_event_id+1 e FROM capture_failure_boundaries '
                     'WHERE after_event_id>=? AND after_event_id<? UNION ALL SELECT first_event e '
                     'FROM consumption_segment_links WHERE first_event BETWEEN ? AND ?)',
                     (start-1, stop, start, stop)).fetchone()[0]
    if cut is not None:
        stop = cut - 1
    absolutes = {}
    slower = {}
    use_slow = slow is not None and len(doc['dials']) > 1
    options = dict(slow_phases=slower) if use_slow else {}
    first = start-1 if use_slow and not slow else start
    samples = phases(db, first, stop, doc, source, absolute_bands=absolutes, **options)
    if first < start and first in slower and samples[first][0] == source:
        slow.update(slow_reference(outer, slower[first], source['monotonic_us']))
    turn = number(doc['dials'][-1]['value_per_revolution'])
    rows = []
    for event in range(start, stop+1):
        sample = samples.get(event)
        if not sample:
            break
        current, phase = sample
        timing = interval(source, current)
        if (current['context_id'] != source['context_id'] or timing['state'] != 'continuous'
                or timing['elapsed_seconds'] >= 660):
            break
        limit = rate * (current['monotonic_us'] - source['monotonic_us']) / 1000000
        outer = advance_band(outer, phase, turn, limit)
        if outer is None:
            break
        slow_phase = slower.get(event)
        if slow_phase is not None and slow:
            tick = current['monotonic_us']
            allowed = rate * (tick - slow['tick']) / 1000000
            position = advance_band(tuple(map(number,slow['phase'])),slow_phase,
                                    number(doc['dials'][-2]['value_per_revolution']),allowed)
            if position is None:
                break
            lo, hi = map(number,slow['base'])
            left, right = map(number,slow['origin'])
            clipped = (max(outer[0],lo+position[0]-right),min(outer[1],hi+position[1]-left))
            if clipped[0] > clipped[1]:
                break
            outer = advance_band(clipped,phase,turn,0)
            if outer is None:
                break
        if event in absolutes:
            compatible = supported(absolutes[event], [outer], 0, 0)
            if not compatible:
                break
            outer = (compatible[0][0], compatible[-1][1])
        if slow_phase is not None:
            if not slow or event in absolutes:
                slow.update(slow_reference(outer,slow_phase,current['monotonic_us']))
            else:
                slow.update(phase=list(map(str,position)),tick=current['monotonic_us'])
        rows.append((current, outer))
        source = current
    return rows


def refine(store, doc, track, rate, originals=None):
    """Repair a legacy checkpoint without holding the meter while replay catches up."""
    from absolute_motion import measurement
    anchor = track['anchor']
    identity = (anchor['event_id'], anchor['source_sha256'], anchor['captured_at'])
    key = [*identity, str(rate)]
    cursor = track.get('envelope_replay') or {}
    unavailable = dict(track, envelope_replay=dict(key=key, stopped=True))
    head = track['source']
    if cursor.get('key') == key and cursor.get('source') == head and track.get('envelope_rate') == str(rate):
        return track
    slow = dict(cursor.get('slow',{})) if cursor.get('key') == key else {}
    with store.connect() as db:
        if cursor.get('key') == key and head['event_id'] < cursor.get('retry_event', 0):
            return track
        if cursor.get('key') == key and 'retry_event' not in cursor:
            if cursor.get('stopped'):
                return track
            source, outer = cursor['source'], tuple(map(number, cursor['outer']))
        else:
            first = seed(db, doc, identity, originals)
            if not first or first[0] != anchor:
                # The independently receipted JPEG can arrive after its compact exposure.
                return dict(track, envelope_replay=dict(key=key, retry_event=head['event_id']+PAGE))
            source, outer = first
        if source['event_id'] < head['event_id']:
            expected = min(PAGE, head['event_id'] - source['event_id'])
            rows = page(db, doc, source, outer, head['event_id'], rate, slow)
            if len(rows) != expected:
                return unavailable
            source, outer = rows[-1]
    progress = dict(key=key,source=source,outer=list(map(str,outer)),slow=slow)
    if (source['event_id'] < head['event_id'] or track.get('needs_confirmation')
            or source == head and not outer[0] <= number(track['level']) <= outer[1]):
        return dict(track, envelope_replay=progress, envelope_rate=None)
    if source != head:
        return unavailable
    # Keep all turns allowed by the independent photo, including a lower turn
    # omitted by a legacy re-anchor. Keep the nominal and its actual source time.
    result = dict(track, outer=list(map(str, outer)), envelope_rate=str(rate))
    result['envelope_replay'] = progress
    result['display'] = measurement(result, source)
    if slow:
        result['display'].update(bounds_basis='full_register_and_slower_dial',
                                 bounds_flow_limit_cfh=round(float(rate * 3600), 6))
    return result


class ChartRegisterReplay:
    """Cache verified phases for the active register anchor in the background chart worker."""

    def __init__(self, store):
        from threading import Lock
        self.store = store
        self.lock = Lock()
        self.key = None
        self.bounds = {}
        self.cursor = None
        self.slow = {}
        self.stopped = False

    def readings(self, registers, head, document, policy, stopping):
        from absolute_motion import meter_rate
        from meter_history import millis
        from datetime import datetime
        if (not registers or not head or type(head.get('event_id')) is not int
                or not document or document.get('unit') != 'ft3'):
            return registers
        try:
            rate = meter_rate(document)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return registers
        if rate <= 0:
            return registers
        identity = tuple(head.get(k) for k in ('anchor_event_id','anchor_source_sha256','anchor_measured_at'))
        if type(identity[0]) is not int or identity[0] < 1 or not all(identity):
            return registers
        from reading_format import validate
        key = (*identity, validate(document)[1], rate)
        end = min(head['event_id'], registers[-1][3])
        if end < identity[0]:
            return registers
        with self.lock:
            if self.key != key:
                with self.store.connect() as db:
                    self.cursor = seed(db, document, identity)
                self.key, self.bounds, self.stopped = key, {}, self.cursor is None
                self.slow = {}
                if self.cursor:
                    src, outer = self.cursor
                    self.bounds[src['event_id']] = (src['source_sha256'], millis(datetime.fromisoformat(src['captured_at'])), outer)
            # Cold history work is bounded; later preparations resume the cursor.
            for _ in range(64):
                if self.stopped or self.cursor[0]['event_id'] >= end or stopping.is_set():
                    break
                src, outer = self.cursor
                with self.store.connect() as db:
                    rows = page(db, document, src, outer, end, rate, self.slow)
                for current, band in rows:
                    self.bounds[current['event_id']] = (current['source_sha256'], millis(datetime.fromisoformat(current['captured_at'])), band)
                if rows:
                    self.cursor = rows[-1]
                if len(rows) < min(PAGE, end - src['event_id']):
                    self.stopped = True
            # Keep a rolling cache for the displayed history even if an anchor lasts months.
            cutoff = registers[0][3]
            self.bounds = {eid: row for eid, row in self.bounds.items() if eid >= cutoff}
            result = []
            for point in registers:
                t, value, _, eid, _, identity_fields, sha = point
                match = self.bounds.get(eid)
                if (match and match[:2] == (sha, t) and identity_fields[1] == 'photo_anchored_fine_dial'
                        and match[2][0] <= value <= match[2][1]):
                    point = (*point[:2], match[2], *point[3:])
                result.append(point)
            return result
