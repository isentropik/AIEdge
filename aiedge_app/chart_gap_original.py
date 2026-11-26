"""Read the two chart dials from a receipted original of a compact exposure."""
from functools import lru_cache
from datetime import datetime, timezone
from math import ceil, floor, isfinite

from capture_clock import interval
from daily_constraints import number
from dial_travel import advance_band, phases
from reading_bounds import feasible_ranges

from observation_support import observed_rows


def merge_bands(bands):
    merged = []
    for lo,hi in sorted(bands):
        if merged and lo<=merged[-1][1]:
            merged[-1]=(merged[-1][0],max(hi,merged[-1][1]))
        else:
            merged.append((lo,hi))
    return merged


def reachable_pairs(bands, measured, turn, limit):
    """Keep distinct dial windings; a hole between two turns cannot seed the next exposure."""
    lo,hi=measured
    paths=[]
    for left,right in bands:
        first=ceil((left-hi)/turn)
        last=floor((right+limit-lo)/turn)
        if last-first>128 or len(paths)+max(0,last-first+1)>4096:
            return []
        for winding in range(first,last+1):
            shift=winding*turn
            paths.append(((left,right),(max(left,lo+shift),min(right+limit,hi+shift))))
    return paths


class GapOriginals:
    def __init__(self, store, recognition):
        self.store = store
        self.recognition = recognition
        self.positions = lru_cache(maxsize=128)(self._positions)

    def _positions(self, sha, pipeline, mask):
        reader = self.recognition.reader
        if reader is None or reader.pipeline_id != pipeline:
            raise ValueError('original_reader_mismatch')
        # Reader serializes inference. The captured reference stays bound to
        # this pipeline even if Setup activates another reader concurrently.
        result = reader.read_jpeg(self.store.image(sha), observed=list(mask))
        if (result.get('source_sha256') != sha or result.get('pipeline_id') != pipeline or
                result.get('state') != 'estimated' or observed_rows(result) != list(mask)):
            raise ValueError('original_observation_mismatch')
        return tuple(row.get('position') for row in result['dial_positions'])

    def verified(self, db, obs, document, compact_fine, mask):
        sha = obs['source_sha256']
        pipeline = document['pipeline_id']
        receipt = db.execute('''SELECT 1 FROM original_receipts r
            JOIN compact_exposures c ON c.event_id=r.event_id AND c.original_sha=r.sha
                AND c.packet_sha=r.proof_sha AND c.pipeline=?
            JOIN frames f ON f.camera=r.camera AND f.frame_id=r.frame AND f.sha256=r.sha AND f.bytes=r.size
            JOIN capture_events e ON e.camera=f.camera AND e.frame_id=f.frame_id AND e.event_id=r.event_id
            WHERE r.camera=? AND r.event_id=? AND r.sha=?''',
            (pipeline, obs['camera'], obs['event_id'], sha)).fetchone()
        if not receipt:
            return None
        try:
            positions = self.positions(sha, pipeline, mask)
            fine = document['dials'][-1]
            fast = positions[fine['index']]
            if not all(isinstance(v, (float, int)) and isfinite(v) and 0 <= v < 10
                       for v, observed in zip(positions,mask,strict=True) if observed):
                return None
            if abs((fast - compact_fine + 5) % 10 - 5) > 2 * fine['position_error']:
                return None
            return positions
        except (OSError, ValueError, TypeError, KeyError, IndexError):
            return None

    def pair(self, db, obs, document, compact_fine):
        coarse, fine = document['dials'][-2:]
        mask = tuple(i in (coarse['index'], fine['index']) for i in range(len(document['dials'])))
        values = self.verified(db,obs,document,compact_fine,mask)
        return values[coarse['index']] if values else None

    def next_boundary(self, db, source, document, rate, first, tick, head):
        """Project a full register through every fine exposure after the last interruption."""
        time = datetime.fromtimestamp(tick/1000,timezone.utc)
        close = db.execute('''SELECT e.event_id FROM frames f JOIN capture_events e USING(camera,frame_id)
            WHERE f.camera=? AND f.captured_at>=? AND e.event_id BETWEEN ? AND ? ORDER BY f.captured_at LIMIT 1''',
            (source['camera'],time.isoformat(),first,head)).fetchone()
        if not close or not first < close[0] <= first+128:
            return None
        last = close[0]
        if db.execute('SELECT 1 FROM capture_failure_boundaries WHERE after_event_id>=? AND after_event_id<? '
                      'UNION ALL SELECT 1 FROM consumption_segment_links WHERE first_event>? AND first_event<=? LIMIT 1',
                      (first,last,first,last)).fetchone():
            return None
        rows = phases(db,first,last,document,source,same_clock=False)
        if len(rows)!=last-first+1:
            return None
        obs,phase = rows[first]
        dials = document['dials']
        turn = number(dials[-1]['value_per_revolution'])
        values = self.verified(db,obs,document,float(sum(phase)*5/turn),tuple(True for d in dials))
        if not values:
            return None
        register = feasible_ranges([d['value_per_revolution'] for d in dials],
                                   [values[d['index']] for d in dials],[d['position_error'] for d in dials])
        if register.get('wraps_register') or not register.get('intervals'):
            return None
        bands = [a for band in register['intervals'] if (a:=advance_band(band,phase,turn,0))]
        for eid in range(first+1,last+1):
            prev,previous_phase = rows[eid-1]
            current,current_phase = rows[eid]
            timing = interval(prev,current)
            if prev['context_id']!=current['context_id'] or timing['state']!='continuous':
                return None
            limit = number(rate)*number(timing['elapsed_seconds'])
            paths = reachable_pairs(bands,current_phase,turn,limit)
            if not paths:
                return None
            if eid==last:
                a,b=(datetime.fromisoformat(r['captured_at']) for r in (prev,current))
                if not a<=time<=b or b<=a:
                    return None
                weight=number((time-a).total_seconds())/number((b-a).total_seconds())
                # Inside a capture interval movement can occur at any time.
                # Use elapsed capacity on both sides; interpolation is nominal only.
                bounds=[(max(left[0],right[0]-(1-weight)*limit),min(right[1],left[1]+weight*limit))
                        for left,right in paths]
                bounds=[[float(lo),float(hi)] for lo,hi in merge_bands((lo,hi) for lo,hi in bounds if lo<=hi)]
                if not bounds:
                    return None
                p0,p1=(sum(p)/2 for p in (previous_phase,current_phase))
                delta=(p1-p0+turn*2)%turn
                tolerance=(previous_phase[1]-previous_phase[0]+current_phase[1]-current_phase[0])/2
                if delta>turn/2 and turn-delta<=tolerance:
                    delta=0
                return dict(time=tick,bands=bounds,phase=float((p0+weight*delta)%turn),turn=float(turn))
            bands=merge_bands(right for _,right in paths)
