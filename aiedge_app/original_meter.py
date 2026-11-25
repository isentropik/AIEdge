"""Recover meter position from a receipted original at its own capture time."""

from decimal import Decimal
import json

from absolute_motion import elapsed_seconds, start, update
from daily_constraints import number, supported
from dial_travel import advance_band, phases
from event_observation_read import read_batch
from event_selection import digest
from mqtt_consumption import fresh_range
from observation_support import observed_rows
from reading_bounds import feasible_ranges


class OriginalMeter:
    def __init__(self, store, recognition):
        self.store = store
        self.recognition = recognition
        self.page = None
        self.after = 0

    def completed(self, snapshot, now, max_age):
        """Recognition can trail acquisition. Publish the completed event's own time."""
        from capture_recovery import publication_blocked
        doc = snapshot['format']
        latest = snapshot.get('_timing_event_id')
        if not latest or not snapshot.get('_daily_publication_pending'):
            return None
        with self.store.connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='compact_exposures'").fetchone():
                return None
            # Freeze the accounting cursor, physical head and failure boundary in one read.
            db.execute('BEGIN')
            row = db.execute('''
                SELECT r.result, e.event_id, f.captured_at, f.sha256, e.camera, k.clock_id, r.segment_id
                FROM consumption_records r JOIN capture_events e USING(event_id)
                JOIN frames f USING(camera,frame_id) JOIN capture_clocks k USING(camera,frame_id)
                WHERE r.segment_id=(SELECT segment_id FROM consumption_active WHERE singleton=1)
                ORDER BY r.event_id DESC LIMIT 1''').fetchone()
            if not row or row[1] >= latest or publication_blocked(db,latest,getattr(self.store,'active_capture_attempt',None)):
                return None
            raw, event, stamp, sha, camera, clock, segment = row
            if not db.execute('SELECT 1 FROM capture_events e JOIN capture_clocks k USING(camera,frame_id) '
                              'JOIN compact_exposures c USING(event_id) WHERE e.event_id=? AND e.camera=? '
                              'AND k.clock_id=? AND c.pipeline=? AND e.event_id=(SELECT MAX(event_id) FROM capture_events)',
                              (latest,camera,clock,doc['pipeline_id'])).fetchone():
                return None
            if db.execute('SELECT 1 FROM capture_failure_boundaries WHERE after_event_id BETWEEN ? AND ? LIMIT 1',
                          (event,latest)).fetchone():
                return None
            try:
                record = json.loads(raw)
            except (ValueError, TypeError):
                return None
            if not isinstance(record, dict):
                return None
            src = record.get('event_observation') or {}
            ctx = self.recognition.observation_context
            if (src.get('event_id'),src.get('source_sha256'),src.get('captured_at'),src.get('context_id'),
                    src.get('camera'),src.get('clock_id'),record.get('segment_id')) != (
                    event,sha,stamp,ctx,camera,clock,segment):
                return None
            hist = dict(format=doc,latest=dict(captured_at=stamp,sha256=sha),consumption=record,
                        _timing_event_id=event,_publication_segment_id=segment)
            obs = fresh_range(hist,max_age,clock=now)
            if obs is None:
                return None
            try:
                inf = read_batch(db,[src],doc['pipeline_id'])[0]['result']
            except (ValueError, TypeError, KeyError, IndexError):
                return None
            if inf.get('event_observation') != src or digest(inf) != record.get('observation_inference_sha256'):
                return None
            return hist, obs

    def candidates(self, doc, head, segment, after):
        # Restrict to receipts in this accounting segment. The JPEG can arrive
        # much later than the compact event. Its receipt time has no meter meaning.
        with self.store.connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='original_receipts'").fetchone():
                return []
            row = db.execute('SELECT first_event FROM consumption_segments WHERE segment_id=? AND format_id=?',
                             (segment, head['format_id'])).fetchone()
            if not row:
                return []
            first = max(after + 1, row[0])
            key = (head['camera'], head['clock_id'], head['context_id'], head['format_id'], segment, first)
            if key != self.page:
                self.page, self.after = key, first - 1
            rows = db.execute('''
                SELECT r.event_id, r.sha FROM original_receipts r
                JOIN capture_events e ON e.event_id=r.event_id AND e.camera=r.camera AND e.frame_id=r.frame
                JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id AND f.sha256=r.sha AND f.bytes=r.size
                JOIN capture_clocks k ON k.camera=e.camera AND k.frame_id=e.frame_id
                JOIN compact_exposures c ON c.event_id=e.event_id AND c.original_sha=r.sha AND c.packet_sha=r.proof_sha
                WHERE r.camera=? AND r.event_id>? AND r.event_id<=? AND k.clock_id=? AND c.pipeline=?
                AND NOT EXISTS (SELECT 1 FROM retired_images t WHERE t.sha256=r.sha)
                ORDER BY r.event_id LIMIT 4
            ''', (head['camera'], self.after, head['event_id'], head['clock_id'], doc['pipeline_id'])).fetchall()
            # Rescan after reaching the end so an out-of-order receipt is discoverable.
            self.after = rows[-1][0] if len(rows) == 4 else first - 1
            candidates = []
            for event, digest in rows:
                sample = phases(db, event, event, doc, head).get(event)
                if sample and sample[0]['source_sha256'] == digest and sample[0]['context_id'] == head['context_id']:
                    candidates.append(sample)
            return candidates

    def read_bands(self, doc, source, phase):
        digest = source['source_sha256']
        try:
            image = self.store.image(digest)
            with self.recognition.lock:
                reader = self.recognition.reader
                if reader is None or reader.pipeline_id != doc['pipeline_id']:
                    return []
                result = reader.read_jpeg(image)
            if (result.get('source_sha256') != digest or result.get('pipeline_id') != doc['pipeline_id']
                    or result['state'] != 'estimated' or observed_rows(result) != [True] * len(doc['dials'])):
                return []
            dials = doc['dials']
            ranges = feasible_ranges([d['value_per_revolution'] for d in dials],
                                     [result['dial_positions'][d['index']]['position'] for d in dials],
                                     [d['position_error'] for d in dials])
            if ranges['state'] != 'bounded' or ranges['wraps_register']:
                return []
            # The full JPEG and the separately encoded crop describe one exposure.
            turn = number(dials[-1]['value_per_revolution'])
            return [band for pair in ranges['intervals'] if (band := advance_band(pair, phase, turn, 0))]
        except (OSError, ValueError, TypeError, IndexError, KeyError, ArithmeticError):
            return []

    def recover(self, track, record, legacy, snapshot, head):
        doc = snapshot['format']
        state = record.get('state') or {}
        after = max(state.get('event_id', 0), legacy.get('event_id', 0),
                    track['source']['event_id'] if track else 0)
        rate = number(doc['maximum_rate_per_second'])
        for source, phase in self.candidates(doc, head, snapshot['_publication_segment_id'], after):
            options = self.read_bands(doc, source, phase)
            if not options:
                continue
            # A recovered photo must also be reachable from every existing
            # register checkpoint. This only bounds position across a gap.
            checkpoints = []
            if state:
                checkpoints.append((state, record['clock_id'], record['tick'], state['bands_ft3']))
            if legacy:
                checkpoints.append((legacy, legacy['clock_id'], legacy['monotonic_us'],
                                    [(legacy['lower_ft3'], legacy['upper_exclusive_ft3'])]))
            floor = Decimal(0)
            for saved, clock, tick, bounds in checkpoints:
                elapsed = number(elapsed_seconds(source, saved['measured_at'], clock, tick))
                if elapsed <= 0:
                    options = []
                    break
                floor = max(floor, number(saved['value_ft3']))
                options = supported(options, [tuple(map(number, pair)) for pair in bounds], 0, rate * elapsed)
                options = [(max(lo, floor), hi) for lo, hi in options if hi >= floor]
            if not options:
                continue
            if track:
                anchor = update(track, self.store, snapshot, source, options, floor)
                if anchor['source'] != source or anchor.get('needs_confirmation'):
                    continue
            else:
                anchor = start(source, options, floor) if not checkpoints else start(
                    source, options, floor, previous=floor, limit=options[-1][1] - floor)
                if not anchor:
                    continue
            return update(anchor, self.store, snapshot, head, None, floor)
        return track
